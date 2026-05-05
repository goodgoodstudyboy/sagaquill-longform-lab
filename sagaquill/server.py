from __future__ import annotations

import copy
import base64
import hmac
import http.client
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
import uuid
from dataclasses import asdict, dataclass, field, replace
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .client import ModelClientError, OpenAICompatibleClient
from .batching import batch_counts, batch_export_payload, batch_to_payload, create_batch_from_csv, proposal_to_project_input
from .codex import (
    clear_provider_override,
    load_provider_config,
    provider_doctor,
    provider_panel_payload,
    provider_snapshot,
    resolve_provider_config,
    save_provider_override,
)
from .models import BatchConfig, BatchItemState, BatchRecord, ProposalRecord
from .pipeline import NovelPipeline, perform_delivery_cleanup, reconcile_committed_run_state
from .projectio import (
    localized_pov,
    normalized_market_profile,
    normalized_output_language,
    normalized_progression_flavor,
    normalized_progression_mode,
    normalized_progression_pacing,
    panel_template_payload,
    project_input_from_dict,
    resolved_market_profile,
)
from .storage import BatchStore
from .retrying import is_retryable_error_text
from .util import dump_json, dump_text, ensure_directory, load_json, slugify, to_plain_data
from .webui import panel_html

_CHAPTER_INDEX_PATTERN = re.compile(r"(?:chapter\s+(\d+)|第\s*(\d+)\s*章)", re.IGNORECASE)
_TRUTHY = {"1", "true", "yes", "on"}


def _is_client_disconnect_error(exc: BaseException) -> bool:
    return isinstance(exc, (BrokenPipeError, ConnectionResetError, ConnectionAbortedError))


def _is_local_bind_host(host: str) -> bool:
    normalized = (host or "").strip().lower()
    return normalized in {"", "127.0.0.1", "localhost", "::1", "[::1]"}


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in _TRUTHY


def _legacy_batch_market_profile_payload(
    config_payload: dict[str, Any] | None,
    raw_proposals: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    base = dict(config_payload or {})
    return {
        **base,
        "audience": "\n".join(str(item.get("platform_fit") or "") for item in (raw_proposals or []) if isinstance(item, dict)),
        "tone": "\n".join(str(item.get("style_seed") or "") for item in (raw_proposals or []) if isinstance(item, dict)),
        "hook": "\n".join(str(item.get("hook") or "") for item in (raw_proposals or []) if isinstance(item, dict)),
        "outline_hint": "\n".join(
            str(item.get("reference_requirements") or "")
            for item in (raw_proposals or [])
            if isinstance(item, dict)
        ),
        "style_examples": [
            str(item.get("style_seed") or "")
            for item in (raw_proposals or [])
            if isinstance(item, dict) and item.get("style_seed")
        ],
        "must_include": [
            str(item.get("reference_requirements") or "")
            for item in (raw_proposals or [])
            if isinstance(item, dict) and item.get("reference_requirements")
        ],
    }


@dataclass(slots=True)
class JobLogEntry:
    step: str
    message: str
    created_at: float


@dataclass(slots=True)
class JobState:
    job_id: str
    title: str
    output_dir: str
    status: str
    created_at: float
    updated_at: float
    step: str = "queued"
    message: str = "已创建任务。"
    summary: dict[str, Any] | None = None
    error: str | None = None
    attempt_count: int = 0
    auto_resume_count: int = 0
    cancel_requested: bool = False
    hidden: bool = False
    stall_timeout_seconds: int = 0
    upstream_retry_count: int = 0
    upstream_next_retry_at: float = 0.0
    upstream_last_error: str | None = None
    run_token: str = ""
    input_payload: dict[str, Any] = field(default_factory=dict, repr=False)
    provider_override: dict[str, Any] = field(default_factory=dict, repr=False)
    pending_upper_decision: dict[str, Any] | None = field(default=None, repr=False)
    log: list[JobLogEntry] = field(default_factory=list)


class JobRunCancelled(RuntimeError):
    pass


class StaleJobAttempt(RuntimeError):
    pass


class GuardedClient:
    def __init__(self, inner: OpenAICompatibleClient, guard: Any) -> None:
        self.inner = inner
        self.guard = guard

    def generate_json(self, *args: Any, **kwargs: Any) -> Any:
        self.guard()
        result = self.inner.generate_json(*args, **kwargs)
        self.guard()
        return result

    def generate_text(self, *args: Any, **kwargs: Any) -> str:
        self.guard()
        result = self.inner.generate_text(*args, **kwargs)
        self.guard()
        return result

    def reset_session(self, session_id: str) -> None:
        self.inner.reset_session(session_id)

    def request_time_budget_seconds(self) -> int:
        return self.inner.request_time_budget_seconds()

    def set_routing_namespace(self, namespace: str | None) -> None:
        setter = getattr(self.inner, "set_routing_namespace", None)
        if callable(setter):
            setter(namespace)


class SagaQuillApp:
    UPSTREAM_RETRY_STAGE_LIMITS: tuple[int, ...] = (3, 6, 9)
    UPSTREAM_RETRY_STAGE_COOLDOWNS: tuple[int, ...] = (600, 1200)
    BATCH_LAUNCH_STALE_SECONDS: int = 120

    def __init__(
        self,
        codex_dir: str | None = None,
        project_root: str | Path | None = None,
        *,
        stall_timeout_seconds: int = 300,
        max_auto_resumes: int = 2,
        batch_global_max_running: int = 200,
        watchdog_interval_seconds: float = 3.0,
        start_watchdog: bool = True,
        autoload_existing: bool = True,
    ) -> None:
        self.codex_dir = codex_dir
        self.root = Path(project_root) if project_root else Path.cwd()
        self.jobs: dict[str, JobState] = {}
        self.batches: dict[str, BatchRecord] = {}
        self.batch_proposals: dict[str, list[ProposalRecord]] = {}
        self.batch_items: dict[str, list[BatchItemState]] = {}
        self._active_threads: dict[str, dict[str, threading.Thread]] = {}
        self.lock = threading.Lock()
        self.stall_timeout_seconds = stall_timeout_seconds
        self.max_auto_resumes = max_auto_resumes
        self.batch_global_max_running = batch_global_max_running
        self.watchdog_interval_seconds = watchdog_interval_seconds
        self._stop_event = threading.Event()
        self._watchdog_thread: threading.Thread | None = None
        self.startup_recovery_running = False
        self.startup_recovery_started_at = 0.0
        self.startup_recovery_completed_at = 0.0
        self.startup_recovery_error: str | None = None
        self._startup_recovery_thread: threading.Thread | None = None
        if autoload_existing:
            self._load_existing_jobs()
            self._load_existing_batches()
        if start_watchdog:
            self._watchdog_thread = threading.Thread(target=self._watchdog_loop, daemon=True)
            self._watchdog_thread.start()
            self._batch_tick()

    @staticmethod
    def _sanitize_provider_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
        if not payload:
            return {}
        sanitized = dict(payload)
        sanitized.pop("api_key", None)
        return sanitized

    def create_job(self, payload: dict[str, Any]) -> dict[str, Any]:
        project_input = project_input_from_dict(payload)
        provider_data = self._resolved_provider_payload(payload)
        return self._create_job_payload(to_plain_data(project_input), provider_override=provider_data)

    def _runs_root(self) -> Path:
        return self.root / "runs"

    def _batch_run_root(self, batch: BatchRecord) -> Path:
        label = slugify(batch.name or batch.batch_id)
        return self._runs_root() / "batches" / f"{label}-{batch.batch_id[-6:]}"

    def _batch_projects_root(self, batch: BatchRecord) -> Path:
        return self._batch_run_root(batch) / "projects"

    def _batch_delivery_root(self, batch: BatchRecord) -> Path:
        return self._batch_run_root(batch) / "delivery"

    def _candidate_run_directories(self) -> list[Path]:
        runs_dir = self._runs_root()
        if not runs_dir.exists():
            return []
        candidates: list[Path] = []
        for entry in runs_dir.iterdir():
            if not entry.is_dir():
                continue
            if entry.name != "batches":
                candidates.append(entry)
                continue
            for batch_dir in entry.iterdir():
                projects_dir = batch_dir / "projects"
                if not projects_dir.exists():
                    continue
                for project_dir in projects_dir.iterdir():
                    if project_dir.is_dir():
                        candidates.append(project_dir)
        return sorted(candidates, key=lambda item: item.stat().st_mtime, reverse=True)

    def _create_job_payload(
        self,
        payload: dict[str, Any],
        *,
        provider_override: dict[str, Any] | None = None,
        output_root: Path | None = None,
    ) -> dict[str, Any]:
        title = str(payload.get("title") or "").strip()
        if not title:
            raise ValueError("Project input must include a title.")
        job_id = uuid.uuid4().hex[:8]
        base_root = output_root or self._runs_root()
        output_dir = base_root / f"{slugify(title)}-{time.strftime('%Y%m%d-%H%M%S')}-{job_id}"
        ensure_directory(output_dir)
        provider_data = dict(provider_override or {})
        if not provider_data:
            provider = load_provider_config(self.codex_dir, project_root=self.root)
            provider_data = provider_snapshot(provider, include_api_key=True)
        persisted_provider_data = self._sanitize_provider_payload(provider_data)
        if persisted_provider_data:
            ensure_directory(output_dir / "data")
            (output_dir / "data" / "provider.snapshot.json").write_text(
                json.dumps(persisted_provider_data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        state = JobState(
            job_id=job_id,
            title=title,
            output_dir=str(output_dir),
            status="queued",
            created_at=time.time(),
            updated_at=time.time(),
            step="queued",
            stall_timeout_seconds=self.stall_timeout_seconds,
            input_payload=dict(payload),
            provider_override=provider_data,
            log=[JobLogEntry(step="queued", message="任务已进入队列。", created_at=time.time())],
        )
        with self.lock:
            self.jobs[job_id] = state
        self._launch_job(
            job_id,
            resume=False,
            step="start",
            message="开始执行生成任务。",
        )
        return self.job_snapshot(job_id)

    def _write_job_provider_snapshot_locked(self, state: JobState) -> None:
        data_dir = Path(state.output_dir) / "data"
        ensure_directory(data_dir)
        snapshot_path = data_dir / "provider.snapshot.json"
        persisted_provider_data = self._sanitize_provider_payload(state.provider_override)
        if persisted_provider_data:
            snapshot_path.write_text(
                json.dumps(persisted_provider_data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        elif snapshot_path.exists():
            snapshot_path.unlink()

    def _pending_upper_decision_path(self, output_dir: Path) -> Path:
        return output_dir / "data" / "pending-upper-decision.json"

    def _pause_snapshot_path(self, output_dir: Path) -> Path:
        return output_dir / "data" / "pause-state.json"

    def _load_pending_upper_decision(self, output_dir: Path) -> dict[str, Any] | None:
        path = self._pending_upper_decision_path(output_dir)
        if not path.exists():
            return None
        try:
            payload = load_json(path)
        except Exception:
            return None
        return payload if isinstance(payload, dict) else None

    def _load_pause_snapshot(self, output_dir: Path) -> dict[str, Any] | None:
        path = self._pause_snapshot_path(output_dir)
        if not path.exists():
            return None
        try:
            payload = load_json(path)
        except Exception:
            return None
        return payload if isinstance(payload, dict) else None

    def _write_pending_upper_decision_locked(self, state: JobState) -> None:
        path = self._pending_upper_decision_path(Path(state.output_dir))
        if state.pending_upper_decision:
            ensure_directory(path.parent)
            path.write_text(json.dumps(state.pending_upper_decision, ensure_ascii=False, indent=2), encoding="utf-8")
        elif path.exists():
            path.unlink()

    def _write_pause_snapshot_locked(self, state: JobState, *, reason: str, message: str) -> None:
        path = self._pause_snapshot_path(Path(state.output_dir))
        ensure_directory(path.parent)
        path.write_text(
            json.dumps(
                {
                    "reason": reason,
                    "step": state.step,
                    "message": message,
                    "updated_at": state.updated_at,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def _clear_pause_snapshot_locked(self, state: JobState) -> None:
        self._pause_snapshot_path(Path(state.output_dir)).unlink(missing_ok=True)

    def _resolved_provider_payload(self, payload: dict[str, Any] | None) -> dict[str, Any]:
        provider_payload = (payload or {}).get("provider") if isinstance(payload, dict) else None
        if not provider_payload:
            return {}
        provider = resolve_provider_config(
            provider_payload or {},
            codex_dir=self.codex_dir,
            project_root=self.root,
            preserve_saved_api_key=True,
        )
        return provider_snapshot(provider, include_api_key=True)

    def _apply_provider_to_job_locked(self, job_id: str, provider_data: dict[str, Any]) -> None:
        if not provider_data:
            return
        state = self.jobs.get(job_id)
        if state is None:
            raise KeyError(job_id)
        state.provider_override = dict(provider_data)
        self._write_job_provider_snapshot_locked(state)

    def _batch_job_ids_locked(self) -> set[str]:
        return {
            item.job_id
            for items in self.batch_items.values()
            for item in items
            if item.job_id
        }

    def _copy_job_state_locked(self, state: JobState) -> JobState:
        return replace(
            state,
            summary=copy.deepcopy(state.summary),
            input_payload=dict(state.input_payload),
            provider_override=dict(state.provider_override),
            pending_upper_decision=copy.deepcopy(state.pending_upper_decision),
            log=list(state.log),
        )

    def _is_batch_output_dir(self, output_dir: str | Path | None) -> bool:
        if not output_dir:
            return False
        path = Path(output_dir)
        batch_root = self._runs_root() / "batches"
        try:
            path.relative_to(batch_root)
            return True
        except ValueError:
            return False

    def _job_kind_for_job_id_locked(self, job_id: str, *, batch_job_ids: set[str] | None = None) -> str:
        if batch_job_ids is None:
            batch_job_ids = self._batch_job_ids_locked()
        return "batch" if job_id in batch_job_ids else "single"

    def _job_kind_for_state_locked(self, state: JobState, *, batch_job_ids: set[str] | None = None) -> str:
        if self._is_batch_output_dir(state.output_dir):
            return "batch"
        return self._job_kind_for_job_id_locked(state.job_id, batch_job_ids=batch_job_ids)

    def list_jobs(self, *, include_hidden: bool = False, job_kind: str = "all") -> dict[str, Any]:
        normalized_kind = job_kind if job_kind in {"all", "single", "batch"} else "all"
        with self.lock:
            ordered = sorted(self.jobs.values(), key=lambda item: item.created_at, reverse=True)
            batch_job_ids = self._batch_job_ids_locked()
            visible_jobs = [state for state in ordered if include_hidden or not state.hidden]
            if normalized_kind != "all":
                visible_jobs = [
                    state
                    for state in visible_jobs
                    if self._job_kind_for_state_locked(state, batch_job_ids=batch_job_ids) == normalized_kind
                ]
            hidden_count = sum(1 for state in ordered if state.hidden)
            visible_snapshots = [self._copy_job_state_locked(state) for state in visible_jobs]
        jobs = [
            self._snapshot(state, include_preview=False, include_log=False, batch_job_ids=batch_job_ids)
            for state in visible_snapshots
        ]
        return {
            "jobs": jobs,
            "hidden_count": hidden_count,
            "include_hidden": include_hidden,
            "job_kind": normalized_kind,
        }

    def job_snapshot(self, job_id: str) -> dict[str, Any]:
        with self.lock:
            state = self.jobs.get(job_id)
            if state is None:
                raise KeyError(job_id)
            state_copy = self._copy_job_state_locked(state)
            batch_job_ids = self._batch_job_ids_locked()
        return self._snapshot(state_copy, include_preview=True, batch_job_ids=batch_job_ids)

    def novel_text(self, job_id: str) -> str:
        with self.lock:
            state = self.jobs.get(job_id)
            if state is None:
                raise KeyError(job_id)
            output_dir = Path(state.output_dir)
        novel_path = output_dir / "novel.md"
        if not novel_path.exists():
            raise FileNotFoundError(str(novel_path))
        return novel_path.read_text(encoding="utf-8")

    def info(self) -> dict[str, Any]:
        payload = provider_doctor(self.codex_dir, project_root=self.root)
        payload["startup_recovery_running"] = self.startup_recovery_running
        payload["startup_recovery_started_at"] = self.startup_recovery_started_at or None
        payload["startup_recovery_completed_at"] = self.startup_recovery_completed_at or None
        payload["startup_recovery_error"] = self.startup_recovery_error
        return payload

    def provider_settings(self) -> dict[str, Any]:
        return provider_panel_payload(self.codex_dir, project_root=self.root)

    def save_provider_settings(self, payload: dict[str, Any]) -> dict[str, Any]:
        save_provider_override(payload, codex_dir=self.codex_dir, project_root=self.root)
        return provider_panel_payload(self.codex_dir, project_root=self.root) | {"saved": True}

    def reset_provider_settings(self) -> dict[str, Any]:
        clear_provider_override(self.root, codex_dir=self.codex_dir)
        return provider_panel_payload(self.codex_dir, project_root=self.root) | {"saved": False}

    def test_provider(self, payload: dict[str, Any]) -> dict[str, Any]:
        provider = resolve_provider_config(payload, codex_dir=self.codex_dir, project_root=self.root, preserve_saved_api_key=True)
        started_at = time.time()
        client = OpenAICompatibleClient(provider, timeout_seconds=30, retries=0)
        light_model = getattr(provider, "light_model", getattr(provider, "review_model", None)) or provider.model
        review_model = getattr(provider, "review_model", None) or light_model or provider.model
        prompt_system = "You are a provider connectivity probe. Reply with exactly OK."
        prompt_user = "Return OK."

        def tier_reasoning(tier: str) -> str | None:
            if tier == "light":
                return provider.light_reasoning_effort or provider.reasoning_effort
            return provider.flagship_reasoning_effort or provider.reasoning_effort

        def tier_service(tier: str) -> str | None:
            if tier == "light":
                return provider.light_service_tier or provider.service_tier
            return provider.flagship_service_tier or provider.service_tier

        def probe(model_name: str, provider_tier: str) -> dict[str, Any]:
            probe_started_at = time.time()
            try:
                reply = client.generate_text(
                    prompt_system,
                    prompt_user,
                    model=model_name,
                    temperature=0.0,
                    max_output_tokens=16,
                    stream=False,
                    provider_tier=provider_tier,
                )
                return {
                    "ok": True,
                    "model": model_name,
                    "provider_tier": provider_tier,
                    "elapsed_ms": int((time.time() - probe_started_at) * 1000),
                    "reply": reply.strip(),
                    "error": None,
                    "reused": False,
                }
            except Exception as exc:
                if (
                    provider.wire_api == "responses"
                    and "Could not extract text from responses payload." in str(exc)
                ):
                    try:
                        reply = client.generate_text(
                            prompt_system,
                            prompt_user,
                            model=model_name,
                            temperature=0.0,
                            max_output_tokens=16,
                            stream=True,
                            provider_tier=provider_tier,
                        )
                        return {
                            "ok": True,
                            "model": model_name,
                            "provider_tier": provider_tier,
                            "elapsed_ms": int((time.time() - probe_started_at) * 1000),
                            "reply": reply.strip(),
                            "error": None,
                            "reused": False,
                        }
                    except Exception:
                        pass
                return {
                    "ok": False,
                    "model": model_name,
                    "provider_tier": provider_tier,
                    "elapsed_ms": int((time.time() - probe_started_at) * 1000),
                    "reply": "",
                    "error": str(exc),
                    "reused": False,
                }

        flagship_result = probe(provider.model, "flagship")
        if (
            light_model == provider.model
            and tier_reasoning("light") == tier_reasoning("flagship")
            and tier_service("light") == tier_service("flagship")
        ):
            light_result = dict(flagship_result)
            light_result["model"] = light_model
            light_result["provider_tier"] = "light"
            light_result["reused"] = True
        else:
            light_result = probe(light_model, "light")
        if (
            review_model == provider.model
            and tier_reasoning("flagship") == tier_reasoning("flagship")
            and tier_service("flagship") == tier_service("flagship")
        ):
            review_result = dict(flagship_result)
            review_result["model"] = review_model
            review_result["provider_tier"] = "review"
            review_result["reused"] = True
        elif (
            review_model == light_model
            and tier_reasoning("light") == tier_reasoning("light")
            and tier_service("light") == tier_service("light")
        ):
            review_result = dict(light_result)
            review_result["model"] = review_model
            review_result["provider_tier"] = "review"
            review_result["reused"] = True
        else:
            review_result = probe(review_model, "flagship")
        elapsed_ms = int((time.time() - started_at) * 1000)
        any_success = bool(flagship_result["ok"] or light_result["ok"] or review_result["ok"])
        all_success = bool(flagship_result["ok"] and light_result["ok"] and review_result["ok"])
        return {
            "ok": all_success,
            "partial": any_success and not all_success,
            "elapsed_ms": elapsed_ms,
            "reply": flagship_result["reply"],
            "tests": {
                "flagship": flagship_result,
                "light": light_result,
                "review": review_result,
            },
            "resolved": {
                "base_url": provider.base_url,
                "wire_api": provider.wire_api,
                "model": provider.model,
                "light_model": light_model,
                "review_model": review_model,
                "flagship_reasoning_effort": tier_reasoning("flagship"),
                "flagship_service_tier": tier_service("flagship"),
                "light_reasoning_effort": tier_reasoning("light"),
                "light_service_tier": tier_service("light"),
                "continuation_mode": provider.continuation_mode,
            },
        }

    def template(self) -> dict[str, Any]:
        return panel_template_payload()

    def import_batch_csv(self, payload: dict[str, Any]) -> dict[str, Any]:
        csv_text = str(payload.get("csv_text") or "").strip()
        if not csv_text:
            csv_path_text = str(payload.get("csv_path") or "").strip()
            if not csv_path_text:
                raise ValueError("Batch import requires csv_text or csv_path.")
            csv_path = Path(csv_path_text)
            if not csv_path.is_absolute():
                csv_path = self.root / csv_path
            if not csv_path.exists():
                raise FileNotFoundError(str(csv_path))
            csv_text = csv_path.read_text(encoding="utf-8")
            payload = dict(payload)
            payload["source_name"] = payload.get("source_name") or csv_path.name
        source_name = str(payload.get("source_name") or "batch.csv").strip() or "batch.csv"
        batch_name = str(payload.get("batch_name") or "").strip() or None
        config = self._batch_config_from_payload(payload)
        provider = resolve_provider_config(payload.get("provider") or {}, codex_dir=self.codex_dir, project_root=self.root, preserve_saved_api_key=True)
        batch, proposals, items = create_batch_from_csv(
            csv_text,
            source_name=source_name,
            batch_name=batch_name,
            provider_snapshot=provider_snapshot(provider, include_api_key=True),
            config=config,
        )
        if payload.get("max_concurrent") not in {None, ""}:
            batch.max_concurrent = max(1, int(payload["max_concurrent"]))
        with self.lock:
            self.batches[batch.batch_id] = batch
            self.batch_proposals[batch.batch_id] = proposals
            self.batch_items[batch.batch_id] = items
            self._persist_batch_locked(batch.batch_id)
            return self._batch_snapshot_locked(batch.batch_id, include_proposals=True)

    def list_batches(self, *, include_hidden: bool = False) -> dict[str, Any]:
        with self.lock:
            ordered = sorted(self.batches.values(), key=lambda item: item.created_at, reverse=True)
            hidden_count = sum(1 for batch in ordered if batch.hidden)
            visible = ordered if include_hidden else [batch for batch in ordered if not batch.hidden]
            items = [self._batch_list_entry_locked(batch.batch_id) for batch in visible]
        return {"batches": items, "hidden_count": hidden_count}

    def batch_snapshot(self, batch_id: str) -> dict[str, Any]:
        with self.lock:
            if batch_id not in self.batches:
                raise KeyError(batch_id)
            return self._batch_snapshot_locked(batch_id, include_proposals=True)

    def launch_batch(self, batch_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        selected_ids = {str(item) for item in payload.get("selected_proposal_ids") or []}
        with self.lock:
            batch = self.batches.get(batch_id)
            if batch is None:
                raise KeyError(batch_id)
            if payload.get("max_concurrent") is not None:
                batch.max_concurrent = max(1, int(payload["max_concurrent"]))
            batch.config = self._batch_config_from_payload(payload, existing=batch.config)
            if payload.get("provider"):
                provider = resolve_provider_config(payload.get("provider") or {}, codex_dir=self.codex_dir, project_root=self.root, preserve_saved_api_key=True)
                batch.provider_snapshot = provider_snapshot(provider, include_api_key=True)
            items = self.batch_items.get(batch_id, [])
            if selected_ids:
                for item in items:
                    if item.status == "completed":
                        continue
                    item.selected = item.proposal_id in selected_ids
                    if item.selected and item.status == "draft":
                        item.status = "queued"
                    elif not item.selected and item.status in {"draft", "queued", "failed"}:
                        item.status = "draft"
                    if item.status in {"draft", "queued", "launching", "running"}:
                        item.pause_reason = None
                    item.updated_at = time.time()
            else:
                for item in items:
                    if item.status == "draft" and item.selected:
                        item.status = "queued"
                        item.pause_reason = None
                        item.updated_at = time.time()
            batch.paused = False
            batch.status = "running"
            batch.updated_at = time.time()
            self._persist_batch_locked(batch_id)
        self._batch_tick()
        return self.batch_snapshot(batch_id)

    def pause_batch(self, batch_id: str) -> dict[str, Any]:
        job_ids_to_pause: list[str] = []
        with self.lock:
            batch = self.batches.get(batch_id)
            if batch is None:
                raise KeyError(batch_id)
            items = self.batch_items.get(batch_id, [])
            batch.paused = True
            batch.status = "paused"
            batch.updated_at = time.time()
            for item in items:
                if not item.selected:
                    continue
                proposal = self._find_proposal_locked(batch_id, item.proposal_id)
                if item.job_id:
                    job = self.jobs.get(item.job_id)
                    if job is not None and job.status not in {"completed", "failed", "paused"}:
                        job_ids_to_pause.append(item.job_id)
                    item.status = "paused"
                    item.last_error = None
                elif item.status in {"queued", "launching"}:
                    item.status = "paused"
                    item.last_error = None
                item.updated_at = batch.updated_at
                if proposal is not None:
                    proposal.status = item.status
            self._persist_batch_locked(batch_id)
        for job_id in job_ids_to_pause:
            try:
                self.pause_job(job_id)
            except (KeyError, ValueError):
                continue
        with self.lock:
            self._sync_batch_items_locked(batch_id)
            return self._batch_snapshot_locked(batch_id, include_proposals=True)

    def pause_batch_item(self, batch_id: str, proposal_id: str) -> dict[str, Any]:
        with self.lock:
            batch = self.batches.get(batch_id)
            item = self._find_batch_item_locked(batch_id, proposal_id)
            if batch is None or item is None:
                raise KeyError(proposal_id)
            proposal = self._find_proposal_locked(batch_id, proposal_id)
            job = self.jobs.get(item.job_id) if item.job_id else None
            if item.status in {"completed"}:
                return self._batch_snapshot_locked(batch_id, include_proposals=True)
            if item.job_id and job is not None and job.status in {"queued", "running", "waiting_retry"}:
                job_id = item.job_id
            else:
                job_id = None
                item.status = "paused"
                item.pause_reason = "manual_pause"
                item.updated_at = time.time()
                item.last_error = None
                if proposal is not None:
                    proposal.status = "paused"
                batch.updated_at = max(batch.updated_at, item.updated_at)
                self._persist_batch_locked(batch_id)
        if job_id:
            self.pause_job(job_id)
            with self.lock:
                item = self._find_batch_item_locked(batch_id, proposal_id)
                proposal = self._find_proposal_locked(batch_id, proposal_id)
                if item is not None:
                    item.status = "paused"
                    item.pause_reason = "manual_pause"
                    item.last_error = None
                    item.updated_at = time.time()
                if proposal is not None:
                    proposal.status = "paused"
                batch = self.batches.get(batch_id)
                if batch is not None:
                    batch.updated_at = time.time()
                    self._persist_batch_locked(batch_id)
        with self.lock:
            self._sync_batch_items_locked(batch_id)
            return self._batch_snapshot_locked(batch_id, include_proposals=True)

    def resume_batch(self, batch_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        provider_data = self._resolved_provider_payload(payload)
        with self.lock:
            batch = self.batches.get(batch_id)
            if batch is None:
                raise KeyError(batch_id)
            self._apply_batch_runtime_overrides_locked(batch, payload)
            if provider_data:
                batch.provider_snapshot = dict(provider_data)
            batch.paused = False
            batch.status = "running"
            batch.updated_at = time.time()
            items = self.batch_items.get(batch_id, [])
            for item in items:
                if not item.selected:
                    continue
                proposal = self._find_proposal_locked(batch_id, item.proposal_id)
                job = self.jobs.get(item.job_id) if item.job_id else None
                if provider_data and item.job_id and item.job_id in self.jobs:
                    self._apply_provider_to_job_locked(item.job_id, provider_data)
                if self._hold_batch_item_for_char_limit_locked(
                    batch,
                    item,
                    proposal,
                    job,
                    message="批次恢复：已达到自动暂停字数，保持暂停。",
                ):
                    continue
                if item.status == "draft":
                    item.status = "queued"
                    item.pause_reason = None
                elif item.status == "paused" and not item.job_id:
                    item.status = "queued"
                    item.pause_reason = None
                elif item.status == "paused" and item.job_id and item.job_id not in self.jobs:
                    item.status = "queued"
                    item.pause_reason = None
                elif item.status == "paused":
                    item.status = "queued"
                    item.pause_reason = None
                elif item.status == "queued":
                    item.pause_reason = None
                else:
                    continue
                item.updated_at = batch.updated_at
                if proposal is not None:
                    proposal.status = item.status
            self._persist_batch_locked(batch_id)
        self._batch_tick()
        return self.batch_snapshot(batch_id)

    def resume_all_batch(self, batch_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        provider_data = self._resolved_provider_payload(payload)
        with self.lock:
            batch = self.batches.get(batch_id)
            if batch is None:
                raise KeyError(batch_id)
            self._apply_batch_runtime_overrides_locked(batch, payload)
            if provider_data:
                batch.provider_snapshot = dict(provider_data)
            batch.paused = False
            batch.status = "running"
            batch.updated_at = time.time()
            items = self.batch_items.get(batch_id, [])
            for item in items:
                if not item.selected:
                    continue
                proposal = self._find_proposal_locked(batch_id, item.proposal_id)
                job = self.jobs.get(item.job_id) if item.job_id else None
                if provider_data and item.job_id and item.job_id in self.jobs:
                    self._apply_provider_to_job_locked(item.job_id, provider_data)
                if item.status == "completed":
                    continue
                if self._hold_batch_item_for_char_limit_locked(
                    batch,
                    item,
                    proposal,
                    job,
                    message="批次全量检查并续跑：已达到自动暂停字数，保持暂停。",
                ):
                    continue
                if item.status == "failed":
                    if job is not None and job.status in {"failed", "paused", "interrupted"}:
                        item.status = "queued"
                        job.status = "paused"
                        job.step = "paused"
                        job.message = "批次全量检查并续跑：将失败任务转为可恢复状态。"
                        job.updated_at = batch.updated_at
                        job.error = None
                    else:
                        item.status = "queued"
                        item.job_id = None
                        item.output_dir = None
                    item.last_error = None
                    item.pause_reason = None
                elif item.status == "paused":
                    item.status = "queued"
                    item.pause_reason = None
                elif item.status == "draft":
                    item.status = "queued"
                    item.pause_reason = None
                elif item.status == "queued":
                    item.pause_reason = None
                elif item.status == "launching" and (not item.job_id or item.job_id not in self.jobs):
                    item.status = "queued"
                    item.pause_reason = None
                if proposal is not None:
                    proposal.status = item.status
                item.updated_at = batch.updated_at
            self._persist_batch_locked(batch_id)
        self._batch_tick()
        return self.batch_snapshot(batch_id)

    def resume_batch_item(self, batch_id: str, proposal_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        provider_data = self._resolved_provider_payload(payload)
        with self.lock:
            batch = self.batches.get(batch_id)
            item = self._find_batch_item_locked(batch_id, proposal_id)
            if batch is None or item is None:
                raise KeyError(proposal_id)
            self._apply_batch_runtime_overrides_locked(batch, payload)
            proposal = self._find_proposal_locked(batch_id, proposal_id)
            job = self.jobs.get(item.job_id) if item.job_id else None
            if provider_data:
                batch.provider_snapshot = dict(provider_data)
            batch.paused = False
            batch.status = "running"
            batch.updated_at = time.time()
            if provider_data and item.job_id and item.job_id in self.jobs:
                self._apply_provider_to_job_locked(item.job_id, provider_data)
            if item.status == "completed":
                return self._batch_snapshot_locked(batch_id, include_proposals=True)
            if self._hold_batch_item_for_char_limit_locked(
                batch,
                item,
                proposal,
                job,
                message="批量单本继续：已达到自动暂停字数，保持暂停。",
            ):
                self._persist_batch_locked(batch_id)
                return self._batch_snapshot_locked(batch_id, include_proposals=True)
            if item.status == "failed":
                if job is not None and job.status in {"failed", "paused", "interrupted"}:
                    item.status = "queued"
                    job.status = "paused"
                    job.step = "paused"
                    job.message = "批量单本继续：将失败任务转为可恢复状态。"
                    job.updated_at = batch.updated_at
                    job.error = None
                else:
                    item.status = "queued"
                    item.job_id = None
                    item.output_dir = None
                item.last_error = None
                item.pause_reason = None
            elif item.status == "paused":
                item.status = "queued"
                item.pause_reason = None
            elif item.status == "draft":
                item.status = "queued"
                item.pause_reason = None
            elif item.status == "queued":
                item.pause_reason = None
            elif item.status == "launching" and (not item.job_id or item.job_id not in self.jobs):
                item.status = "queued"
                item.pause_reason = None
            if proposal is not None:
                proposal.status = item.status
            item.updated_at = batch.updated_at
            self._persist_batch_locked(batch_id)
        self._batch_tick()
        return self.batch_snapshot(batch_id)

    def retry_failed_batch(self, batch_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        provider_data = self._resolved_provider_payload(payload)
        with self.lock:
            batch = self.batches.get(batch_id)
            if batch is None:
                raise KeyError(batch_id)
            self._apply_batch_runtime_overrides_locked(batch, payload)
            if provider_data:
                batch.provider_snapshot = dict(provider_data)
            for item in self.batch_items.get(batch_id, []):
                proposal = self._find_proposal_locked(batch_id, item.proposal_id)
                job = self.jobs.get(item.job_id) if item.job_id else None
                if provider_data and item.job_id and item.job_id in self.jobs and item.status in {"failed", "paused", "interrupted"}:
                    self._apply_provider_to_job_locked(item.job_id, provider_data)
                if item.status == "failed":
                    if self._hold_batch_item_for_char_limit_locked(
                        batch,
                        item,
                        proposal,
                        job,
                        message="批次重试失败项：已达到自动暂停字数，保持暂停。",
                    ):
                        continue
                    item.status = "queued" if item.selected else "draft"
                    item.job_id = None
                    item.output_dir = None
                    item.last_error = None
                    item.pause_reason = None
                    item.updated_at = time.time()
            batch.paused = False
            batch.status = "running"
            batch.updated_at = time.time()
            self._persist_batch_locked(batch_id)
        self._batch_tick()
        return self.batch_snapshot(batch_id)

    def delete_batch(self, batch_id: str) -> dict[str, Any]:
        store = BatchStore(self.root, batch_id)
        with self.lock:
            batch = self.batches.get(batch_id)
            if batch is None:
                raise KeyError(batch_id)
            items = self.batch_items.get(batch_id, [])
            if any(item.status in {"launching", "running"} for item in items):
                raise ValueError("Pause or finish the batch before deleting it.")
            snapshot = self._batch_snapshot_locked(batch_id, include_proposals=False)
            self.batches.pop(batch_id, None)
            self.batch_proposals.pop(batch_id, None)
            self.batch_items.pop(batch_id, None)
        shutil.rmtree(store.root, ignore_errors=False)
        return {"deleted": True, "batch": snapshot}

    def hide_batch(self, batch_id: str) -> dict[str, Any]:
        with self.lock:
            batch = self.batches.get(batch_id)
            if batch is None:
                raise KeyError(batch_id)
            batch.hidden = True
            batch.updated_at = time.time()
            self._persist_batch_locked(batch_id)
            return self._batch_snapshot_locked(batch_id, include_proposals=False)

    def unhide_batch(self, batch_id: str) -> dict[str, Any]:
        with self.lock:
            batch = self.batches.get(batch_id)
            if batch is None:
                raise KeyError(batch_id)
            batch.hidden = False
            batch.updated_at = time.time()
            self._persist_batch_locked(batch_id)
            return self._batch_snapshot_locked(batch_id, include_proposals=False)

    def batch_export(self, batch_id: str) -> dict[str, Any]:
        with self.lock:
            if batch_id not in self.batches:
                raise KeyError(batch_id)
            export = batch_export_payload(
                self.batches[batch_id],
                self.batch_proposals.get(batch_id, []),
                self.batch_items.get(batch_id, []),
            )
            BatchStore(self.root, batch_id).write_export(export)
            return export

    def open_output_dir(self, job_id: str) -> dict[str, Any]:
        with self.lock:
            state = self.jobs.get(job_id)
            if state is None:
                raise KeyError(job_id)
            output_dir = Path(state.output_dir)
        if not output_dir.exists():
            raise FileNotFoundError(str(output_dir))
        self._open_path_in_file_manager(output_dir)
        return {
            "opened": True,
            "job_id": job_id,
            "title": state.title,
            "output_dir": str(output_dir),
        }

    def open_batch_dir(self, batch_id: str) -> dict[str, Any]:
        with self.lock:
            batch = self.batches.get(batch_id)
            if batch is None:
                raise KeyError(batch_id)
            batch_root = self._batch_run_root(batch)
        if not batch_root.exists():
            raise FileNotFoundError(str(batch_root))
        self._open_path_in_file_manager(batch_root)
        return {
            "opened": True,
            "batch_id": batch_id,
            "name": batch.name,
            "batch_root": str(batch_root),
        }

    def delivery_cleanup(self, job_id: str) -> dict[str, Any]:
        with self.lock:
            state = self.jobs.get(job_id)
            if state is None:
                raise KeyError(job_id)
            if state.status in {"queued", "running"}:
                raise ValueError("Wait until the job finishes before delivery cleanup.")
            if self._has_live_threads_locked(job_id):
                raise ValueError("The previous attempt is still draining. Try delivery cleanup again in a moment.")
            output_dir = Path(state.output_dir)
        if not output_dir.exists():
            raise FileNotFoundError(str(output_dir))
        report = perform_delivery_cleanup(output_dir, mode="manual")
        with self.lock:
            state = self.jobs.get(job_id)
            if state is not None:
                now = time.time()
                state.updated_at = now
                state.log.append(
                    JobLogEntry(
                        step="delivery_cleanup",
                        message=f"交付清理已完成，移除 {report['removed_count']} 个调试快照。",
                        created_at=now,
                    )
                )
                if len(state.log) > 120:
                    state.log = state.log[-120:]
        return {
            "cleaned": True,
            "job_id": job_id,
            "title": state.title if state is not None else "",
            "output_dir": str(output_dir),
            "report": report,
        }

    def pause_job(self, job_id: str) -> dict[str, Any]:
        with self.lock:
            state = self.jobs.get(job_id)
            if state is None:
                raise KeyError(job_id)
            if state.status == "completed":
                raise ValueError("Completed jobs cannot be paused.")
            if state.status == "paused":
                return self._snapshot(state, include_preview=True)
            now = time.time()
            state.cancel_requested = True
            state.run_token = uuid.uuid4().hex
            state.status = "paused"
            state.step = "paused"
            state.message = "已暂停任务。当前上游调用返回后，系统会忽略这次结果；稍后可恢复运行。"
            state.updated_at = now
            state.error = None
            self._clear_upstream_retry_state_locked(state)
            state.log.append(JobLogEntry(step="paused", message=state.message, created_at=now))
            if len(state.log) > 120:
                state.log = state.log[-120:]
            self._write_pause_snapshot_locked(state, reason="manual_pause", message=state.message)
            return self._snapshot(state, include_preview=True)

    def cancel_job(self, job_id: str) -> dict[str, Any]:
        return self.pause_job(job_id)

    def resume_job(self, job_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        provider_data = self._resolved_provider_payload(payload)
        with self.lock:
            state = self.jobs.get(job_id)
            if state is None:
                raise KeyError(job_id)
            status = state.status
            if provider_data:
                self._apply_provider_to_job_locked(job_id, provider_data)
            if state.pending_upper_decision:
                state.log.append(
                    JobLogEntry(
                        step="upper_review_legacy_resume",
                        message="检测到旧版上层决策快照，按当前自动修复策略继续后续章节生成。",
                        created_at=time.time(),
                    )
                )
                if len(state.log) > 120:
                    state.log = state.log[-120:]
                state.pending_upper_decision = None
                self._write_pending_upper_decision_locked(state)
            else:
                pending_path = self._pending_upper_decision_path(Path(state.output_dir))
                pending_path.unlink(missing_ok=True)
            self._clear_pause_snapshot_locked(state)
        if status == "completed":
            raise ValueError("Completed jobs do not need resume.")
        if status in {"queued", "running"}:
            raise ValueError("Running jobs do not need resume.")
        message = "从已写入产物恢复运行。"
        self._launch_job(job_id, resume=True, step="resume", message=message)
        return self.job_snapshot(job_id)

    def hide_job(self, job_id: str) -> dict[str, Any]:
        with self.lock:
            state = self.jobs.get(job_id)
            if state is None:
                raise KeyError(job_id)
            state.hidden = True
            state.updated_at = time.time()
            self._write_panel_state_locked(state)
            return self._snapshot(state, include_preview=True)

    def unhide_job(self, job_id: str) -> dict[str, Any]:
        with self.lock:
            state = self.jobs.get(job_id)
            if state is None:
                raise KeyError(job_id)
            state.hidden = False
            state.updated_at = time.time()
            self._write_panel_state_locked(state)
            return self._snapshot(state, include_preview=True)

    def delete_job(self, job_id: str, *, confirm_title: str, confirm_job_id: str) -> dict[str, Any]:
        with self.lock:
            state = self.jobs.get(job_id)
            if state is None:
                raise KeyError(job_id)
            if state.status in {"queued", "running"}:
                raise ValueError("Pause the job before deleting it.")
            if self._has_live_threads_locked(job_id):
                raise ValueError("The previous attempt is still draining. Try deleting again in a moment.")
            if confirm_title != state.title or confirm_job_id != state.job_id:
                raise ValueError("Delete confirmation did not match the selected job.")
            output_dir = Path(state.output_dir)
            snapshot = self._snapshot(state, include_preview=False)
            del self.jobs[job_id]
        shutil.rmtree(output_dir, ignore_errors=False)
        return {"deleted": True, "job": snapshot}

    def close(self) -> None:
        with self.lock:
            now = time.time()
            batches_to_persist: set[str] = set()
            for batch_id, batch in self.batches.items():
                items = self.batch_items.get(batch_id, [])
                touched = False
                if any(item.selected and item.status in {"queued", "launching", "running"} for item in items):
                    batch.paused = True
                    batch.status = "paused"
                    batch.updated_at = now
                    touched = True
                for item in items:
                    if not item.selected:
                        continue
                    if item.status in {"running", "launching"}:
                        item.status = "paused"
                        item.pause_reason = "service_close"
                        item.updated_at = now
                        proposal = self._find_proposal_locked(batch_id, item.proposal_id)
                        if proposal is not None:
                            proposal.status = "paused"
                        touched = True
                if touched:
                    batches_to_persist.add(batch_id)
            for state in self.jobs.values():
                if state.status not in {"running", "waiting_retry"}:
                    continue
                previous_step = state.step
                state.cancel_requested = True
                state.run_token = uuid.uuid4().hex
                state.status = "paused"
                state.step = "paused"
                state.message = (
                    f"服务关闭时已安全暂停，原步骤 {previous_step or '当前步骤'}。"
                    " 重启后需手动恢复运行。"
                )
                state.updated_at = now
                state.error = None
                state.log.append(JobLogEntry(step="paused", message=state.message, created_at=now))
                if len(state.log) > 120:
                    state.log = state.log[-120:]
                self._write_pause_snapshot_locked(state, reason="service_close", message=state.message)
            for batch_id in batches_to_persist:
                self._persist_batch_locked(batch_id)
        self._stop_event.set()
        if self._watchdog_thread is not None:
            self._watchdog_thread.join(timeout=5)

    def _load_existing_jobs(self) -> None:
        for entry in self._candidate_run_directories():
            recovered = self._recover_job_state(entry)
            if recovered is None:
                continue
            with self.lock:
                self.jobs[recovered.job_id] = recovered

    def _load_existing_batches(self) -> None:
        batches_dir = self.root / ".sagaquill" / "batches"
        if not batches_dir.exists():
            return
        for entry in sorted(batches_dir.iterdir(), key=lambda item: item.stat().st_mtime, reverse=True):
            if not entry.is_dir():
                continue
            recovered = self._recover_batch_state(entry.name)
            if recovered is None:
                continue
            batch, proposals, items = recovered
            with self.lock:
                self.batches[batch.batch_id] = batch
                self.batch_proposals[batch.batch_id] = proposals
                self.batch_items[batch.batch_id] = items
                self._sync_batch_items_locked(batch.batch_id)

    def _run_startup_recovery(self) -> None:
        self.startup_recovery_running = True
        self.startup_recovery_started_at = time.time()
        self.startup_recovery_completed_at = 0.0
        self.startup_recovery_error = None
        try:
            self._load_existing_jobs()
            self._load_existing_batches()
            self._batch_tick()
        except Exception as exc:
            self.startup_recovery_error = str(exc)
        finally:
            self.startup_recovery_running = False
            self.startup_recovery_completed_at = time.time()

    def start_background_recovery(self) -> None:
        if self.startup_recovery_running:
            return
        thread = self._startup_recovery_thread
        if thread is not None and thread.is_alive():
            return
        thread = threading.Thread(target=self._run_startup_recovery, daemon=True)
        self._startup_recovery_thread = thread
        thread.start()

    def _recover_batch_state(self, batch_id: str) -> tuple[BatchRecord, list[ProposalRecord], list[BatchItemState]] | None:
        store = BatchStore(self.root, batch_id)
        if not store.batch_path.exists() or not store.proposals_path.exists() or not store.items_path.exists():
            return None
        try:
            raw_batch = load_json(store.batch_path)
            raw_proposals = load_json(store.proposals_path)
            raw_items = load_json(store.items_path)
        except Exception:
            return None
        if not isinstance(raw_batch, dict) or not isinstance(raw_proposals, list) or not isinstance(raw_items, list):
            return None
        config_payload = (raw_batch.get("config") or {}) if isinstance(raw_batch.get("config"), dict) else {}
        inferred_market_profile = resolved_market_profile(
            config_payload.get("market_profile"),
            _legacy_batch_market_profile_payload(config_payload, raw_proposals),
        )
        raw_config = dict(raw_batch.get("config") or {})
        raw_config.setdefault("market_profile", inferred_market_profile)
        batch = BatchRecord(
            batch_id=str(raw_batch.get("batch_id") or batch_id),
            name=str(raw_batch.get("name") or batch_id),
            source_name=str(raw_batch.get("source_name") or ""),
            created_at=float(raw_batch.get("created_at") or time.time()),
            updated_at=float(raw_batch.get("updated_at") or time.time()),
            status=str(raw_batch.get("status") or "draft"),
            max_concurrent=max(1, int(raw_batch.get("max_concurrent") or 2)),
            paused=bool(raw_batch.get("paused")),
            hidden=bool(raw_batch.get("hidden")),
            provider_snapshot=dict(raw_batch.get("provider_snapshot") or {}),
            config=self._batch_config_from_payload(raw_config),
        )
        proposals = [
            ProposalRecord(
                proposal_id=str(item.get("proposal_id") or ""),
                row_index=int(item.get("row_index") or 0),
                source_batch_id=str(item.get("source_batch_id") or batch.batch_id),
                title=str(item.get("title") or ""),
                track=str(item.get("track") or ""),
                platform_fit=str(item.get("platform_fit") or ""),
                reference_requirements=str(item.get("reference_requirements") or ""),
                hook=str(item.get("hook") or ""),
                platform_blurb=str(item.get("platform_blurb") or ""),
                core_story=str(item.get("core_story") or ""),
                theme=str(item.get("theme") or ""),
                world_scene=str(item.get("world_scene") or ""),
                world_seed=str(item.get("world_seed") or ""),
                style_seed=str(item.get("style_seed") or ""),
                chapter_seed=str(item.get("chapter_seed") or ""),
                volume_seed=str(item.get("volume_seed") or ""),
                character_seed=str(item.get("character_seed") or ""),
                notes=str(item.get("notes") or ""),
                status=str(item.get("status") or "draft"),
                raw=dict(item.get("raw") or {}),
            )
            for item in raw_proposals
            if isinstance(item, dict)
        ]
        items = [
            BatchItemState(
                batch_id=str(item.get("batch_id") or batch.batch_id),
                proposal_id=str(item.get("proposal_id") or ""),
                title=str(item.get("title") or ""),
                status=str(item.get("status") or "draft"),
                selected=bool(item.get("selected", True)),
                priority=int(item.get("priority") or 0),
                job_id=str(item.get("job_id")) if item.get("job_id") else None,
                output_dir=str(item.get("output_dir")) if item.get("output_dir") else None,
                last_error=str(item.get("last_error")) if item.get("last_error") else None,
                created_at=float(item.get("created_at") or time.time()),
                updated_at=float(item.get("updated_at") or time.time()),
            )
            for item in raw_items
            if isinstance(item, dict)
        ]
        return batch, proposals, items

    def _persist_batch_locked(self, batch_id: str) -> None:
        batch = self.batches[batch_id]
        store = BatchStore(self.root, batch_id)
        payload = batch_to_payload(batch)
        payload["provider_snapshot"] = self._sanitize_provider_payload(batch.provider_snapshot)
        store.write_batch(payload)
        store.write_proposals(self.batch_proposals.get(batch_id, []))
        store.write_items(self.batch_items.get(batch_id, []))

    def _batch_snapshot_locked(self, batch_id: str, *, include_proposals: bool) -> dict[str, Any]:
        self._sync_batch_items_locked(batch_id)
        batch = self.batches[batch_id]
        items = self.batch_items.get(batch_id, [])
        batch_job_ids = self._batch_job_ids_locked()
        enriched_items: list[dict[str, Any]] = []
        for item in items:
            effective_job = self._effective_batch_item_job_locked(item)
            item_payload = to_plain_data(item)
            item_payload["job_kind"] = "batch"
            item_payload["job_status"] = effective_job.status if effective_job is not None else None
            item_payload["step"] = effective_job.step if effective_job is not None else None
            item_payload["message"] = effective_job.message if effective_job is not None else item.last_error
            item_payload["job_updated_at"] = effective_job.updated_at if effective_job is not None else None
            item_payload["attempt_count"] = effective_job.attempt_count if effective_job is not None else 0
            item_payload["auto_resume_count"] = effective_job.auto_resume_count if effective_job is not None else 0
            item_payload["upstream_retry_count"] = effective_job.upstream_retry_count if effective_job is not None else 0
            item_payload["stalled_for_seconds"] = max(0, int(time.time() - effective_job.updated_at)) if effective_job is not None and effective_job.status == "running" else 0
            item_payload["written_chars"] = int(item.written_chars or 0)
            item_payload["target_total_chars"] = int(batch.config.target_total_chars or 0)
            item_payload["pause_at_chars"] = int(batch.config.pause_at_chars or 0) if batch.config.run_to_completion is False else 0
            item_payload["run_to_completion"] = bool(batch.config.run_to_completion)
            if effective_job is not None:
                item_payload["job_id"] = effective_job.job_id
                item_payload["job_kind"] = self._job_kind_for_state_locked(effective_job, batch_job_ids=batch_job_ids)
            enriched_items.append(item_payload)
        payload = {
            "batch_id": batch.batch_id,
            "name": batch.name,
            "source_name": batch.source_name,
            "status": batch.status,
            "paused": batch.paused,
            "hidden": batch.hidden,
            "created_at": batch.created_at,
            "updated_at": batch.updated_at,
            "max_concurrent": batch.max_concurrent,
            "provider_snapshot": {
                "base_url": batch.provider_snapshot.get("base_url"),
                "wire_api": batch.provider_snapshot.get("wire_api"),
                "model": batch.provider_snapshot.get("model"),
                "light_model": batch.provider_snapshot.get("light_model") or batch.provider_snapshot.get("review_model"),
                "review_model": batch.provider_snapshot.get("review_model") or batch.provider_snapshot.get("light_model"),
                "continuation_mode": batch.provider_snapshot.get("continuation_mode"),
            },
            "config": asdict(batch.config),
            "counts": batch_counts(items),
            "paths": {
                "batch_root": str(self._batch_run_root(batch)),
                "projects_root": str(self._batch_projects_root(batch)),
                "delivery_root": str(self._batch_delivery_root(batch)),
            },
            "items": enriched_items,
        }
        if include_proposals:
            payload["proposals"] = [to_plain_data(item) for item in self.batch_proposals.get(batch_id, [])]
        return payload

    def _effective_batch_item_job_locked(self, item: BatchItemState) -> JobState | None:
        recovered_job = self._recover_job_state(Path(item.output_dir)) if item.output_dir else None
        effective_job: JobState | None = None
        if item.job_id and item.job_id in self.jobs:
            effective_job = self.jobs[item.job_id]
            if recovered_job is not None and self._should_use_recovered_batch_job_state(item, effective_job, recovered_job):
                effective_job = recovered_job
        elif recovered_job is not None:
            effective_job = recovered_job
        return effective_job

    def _batch_list_entry_locked(self, batch_id: str) -> dict[str, Any]:
        batch = self.batches[batch_id]
        items = self.batch_items.get(batch_id, [])
        return {
            "batch_id": batch.batch_id,
            "name": batch.name,
            "source_name": batch.source_name,
            "status": batch.status,
            "paused": batch.paused,
            "hidden": batch.hidden,
            "created_at": batch.created_at,
            "updated_at": batch.updated_at,
            "max_concurrent": batch.max_concurrent,
            "provider_snapshot": {
                "base_url": batch.provider_snapshot.get("base_url"),
                "wire_api": batch.provider_snapshot.get("wire_api"),
                "model": batch.provider_snapshot.get("model"),
                "light_model": batch.provider_snapshot.get("light_model") or batch.provider_snapshot.get("review_model"),
                "review_model": batch.provider_snapshot.get("review_model") or batch.provider_snapshot.get("light_model"),
                "continuation_mode": batch.provider_snapshot.get("continuation_mode"),
            },
            "config": asdict(batch.config),
            "counts": batch_counts(items),
            "paths": {
                "batch_root": str(self._batch_run_root(batch)),
                "projects_root": str(self._batch_projects_root(batch)),
                "delivery_root": str(self._batch_delivery_root(batch)),
            },
        }

    def _batch_delivery_item_stem(self, item: BatchItemState, job: JobState) -> str:
        return f"{slugify(item.title or job.title)}-{job.job_id}"

    def _batch_written_chars(self, output_dir: Path) -> int:
        try:
            reconcile_committed_run_state(output_dir)
        except Exception:
            pass
        summary_path = output_dir / "data" / "run-summary.json"
        if summary_path.exists():
            try:
                summary = load_json(summary_path)
                if isinstance(summary, dict):
                    total_chars = int(summary.get("total_chars", 0) or 0)
                    if total_chars > 0:
                        return total_chars
            except Exception:
                pass
        committed_path = output_dir / "data" / "committed-progress.json"
        if committed_path.exists():
            try:
                committed = load_json(committed_path)
                if isinstance(committed, dict):
                    total_chars = int(committed.get("total_committed_chars", 0) or 0)
                    committed_index = int(committed.get("last_committed_chapter_index", 0) or 0)
                    chapter_dir = output_dir / "chapters"
                    has_chapter_files = chapter_dir.exists() and any(chapter_dir.glob("chapter-*.md"))
                    if total_chars >= 0 and (committed_index > 0 or has_chapter_files):
                        return total_chars
            except Exception:
                pass
        novel_txt_path = output_dir / "novel.txt"
        if novel_txt_path.exists():
            try:
                return len(novel_txt_path.read_text(encoding="utf-8"))
            except OSError:
                pass
        novel_md_path = output_dir / "novel.md"
        if novel_md_path.exists():
            try:
                return len(novel_md_path.read_text(encoding="utf-8"))
            except OSError:
                pass
        chapter_dir = output_dir / "chapters"
        if not chapter_dir.exists():
            return 0
        total = 0
        for chapter_path in sorted(chapter_dir.glob("chapter-*.md")):
            try:
                total += len(chapter_path.read_text(encoding="utf-8"))
            except OSError:
                continue
        return total

    def _batch_delivery_status_payload(
        self,
        batch: BatchRecord,
        item: BatchItemState,
        job: JobState,
        *,
        completed: bool,
        written_chars: int,
    ) -> dict[str, Any]:
        return {
            "batch_id": batch.batch_id,
            "batch_name": batch.name,
            "job_id": job.job_id,
            "title": item.title or job.title,
            "status": "completed" if completed else "unfinished",
            "pause_reason": item.pause_reason,
            "target_total_chars": int(batch.config.target_total_chars or 0),
            "written_chars": written_chars,
            "output_dir": str(item.output_dir or job.output_dir),
        }

    def _sync_batch_delivery_artifacts_locked(self, batch: BatchRecord, item: BatchItemState, job: JobState) -> bool:
        if not item.output_dir:
            return False
        source_root = Path(item.output_dir)
        if not source_root.exists():
            return False
        delivery_root = self._batch_delivery_root(batch)
        ensure_directory(delivery_root)
        completed_root = delivery_root / "completed"
        unfinished_root = delivery_root / "unfinished"
        ensure_directory(completed_root)
        ensure_directory(unfinished_root)
        stem = self._batch_delivery_item_stem(item, job)
        completed_dir = completed_root / stem
        unfinished_dir = unfinished_root / stem
        written_chars = max(int(item.written_chars or 0), self._batch_written_chars(source_root))
        copied = False

        def copy_if_needed(source_name: str, target_dir: Path) -> bool:
            source_path = source_root / source_name
            if not source_path.exists():
                return False
            ensure_directory(target_dir)
            target_path = target_dir / source_name
            if target_path.exists():
                try:
                    same_size = target_path.stat().st_size == source_path.stat().st_size
                    same_mtime = int(target_path.stat().st_mtime) >= int(source_path.stat().st_mtime)
                    if same_size and same_mtime:
                        return False
                except OSError:
                    pass
            shutil.copy2(source_path, target_path)
            return True

        def copy_tree_if_needed(source_name: str, target_dir: Path) -> bool:
            source_path = source_root / source_name
            if not source_path.exists() or not source_path.is_dir():
                return False
            target_path = target_dir / source_name
            changed = False
            for child in source_path.rglob("*"):
                if not child.is_file():
                    continue
                relative = child.relative_to(source_path)
                destination = target_path / relative
                ensure_directory(destination.parent)
                should_copy = True
                if destination.exists():
                    try:
                        size_changed = destination.stat().st_size != child.stat().st_size
                        source_newer = int(destination.stat().st_mtime) < int(child.stat().st_mtime)
                        should_copy = size_changed or source_newer
                    except OSError:
                        should_copy = True
                if should_copy:
                    shutil.copy2(child, destination)
                    changed = True
            return changed

        if job.status == "completed":
            if unfinished_dir.exists():
                shutil.rmtree(unfinished_dir, ignore_errors=True)
                copied = True
            copied = copy_if_needed("novel.txt", completed_dir) or copied
            copied = copy_if_needed("book-summary.md", completed_dir) or copied
            copied = copy_tree_if_needed("delivery", completed_dir) or copied
            status_path = completed_dir / "delivery-status.json"
            if status_path.exists():
                status_path.unlink()
                copied = True
            return copied

        if item.pause_reason == "char_limit" and job.status == "paused":
            if completed_dir.exists():
                shutil.rmtree(completed_dir, ignore_errors=True)
                copied = True
            copied = copy_if_needed("novel.txt", unfinished_dir) or copied
            summary_path = unfinished_dir / "book-summary.md"
            if summary_path.exists():
                summary_path.unlink()
                copied = True
            delivery_path = unfinished_dir / "delivery"
            if delivery_path.exists():
                shutil.rmtree(delivery_path, ignore_errors=True)
                copied = True
            status_path = unfinished_dir / "delivery-status.json"
            if status_path.exists():
                status_path.unlink()
                copied = True
            readme_path = unfinished_dir / "README.md"
            if readme_path.exists():
                readme_path.unlink()
                copied = True
            return copied

        if unfinished_dir.exists():
            shutil.rmtree(unfinished_dir, ignore_errors=True)
            copied = True
        return copied

    def _sync_batch_items_locked(self, batch_id: str) -> None:
        batch = self.batches.get(batch_id)
        if batch is None:
            return
        items = self.batch_items.get(batch_id, [])
        proposal_map = {proposal.proposal_id: proposal for proposal in self.batch_proposals.get(batch_id, [])}
        dirty = False
        batch_updated_at = batch.updated_at
        for item in items:
            effective_job = self._effective_batch_item_job_locked(item)
            if effective_job is not None:
                mapped_status = self._batch_item_status_for_job(effective_job.status)
                if (
                    item.status == "queued"
                    and mapped_status == "paused"
                    and item.job_id
                    and item.pause_reason is None
                    and effective_job.status in {"paused", "interrupted", "failed"}
                ):
                    mapped_status = "queued"
                if item.status != mapped_status:
                    item.status = mapped_status
                    dirty = True
                if item.job_id is None and effective_job.job_id:
                    item.job_id = effective_job.job_id
                    dirty = True
                if item.output_dir != effective_job.output_dir:
                    item.output_dir = effective_job.output_dir
                    dirty = True
                next_error = effective_job.message if mapped_status == "failed" else None
                if item.last_error != next_error:
                    item.last_error = next_error
                    dirty = True
                next_pause_reason = "upper_decision" if mapped_status == "paused" and effective_job.step == "upper_review" else item.pause_reason
                if mapped_status == "paused" and next_pause_reason != item.pause_reason:
                    item.pause_reason = next_pause_reason
                    dirty = True
                if mapped_status != "paused" and item.pause_reason is not None:
                    item.pause_reason = None
                    dirty = True
                next_updated_at = max(item.updated_at, effective_job.updated_at)
                if next_updated_at != item.updated_at:
                    item.updated_at = next_updated_at
                    dirty = True
                if item.output_dir:
                    next_written_chars = max(int(item.written_chars or 0), self._batch_written_chars(Path(item.output_dir)))
                    if next_written_chars != item.written_chars:
                        item.written_chars = next_written_chars
                        dirty = True
                if self._sync_batch_delivery_artifacts_locked(batch, item, effective_job):
                    dirty = True
            elif item.status == "launching":
                launch_age = max(0.0, time.time() - item.updated_at)
                if launch_age < self.BATCH_LAUNCH_STALE_SECONDS:
                    proposal = proposal_map.get(item.proposal_id)
                    if proposal is not None and proposal.status != item.status:
                        proposal.status = item.status
                        dirty = True
                    batch_updated_at = max(batch_updated_at, item.updated_at)
                    continue
                item.status = "queued"
                item.updated_at = max(item.updated_at, time.time())
                dirty = True
            proposal = proposal_map.get(item.proposal_id)
            if proposal is not None and proposal.status != item.status:
                proposal.status = item.status
                dirty = True
            batch_updated_at = max(batch_updated_at, item.updated_at)
        previous_status = batch.status
        batch.status = self._derive_batch_status_locked(batch_id)
        if batch.status != previous_status:
            dirty = True
        if batch_updated_at != batch.updated_at:
            batch.updated_at = batch_updated_at
            dirty = True
        if dirty:
            self._persist_batch_locked(batch_id)

    def _derive_batch_status_locked(self, batch_id: str) -> str:
        batch = self.batches[batch_id]
        items = self.batch_items.get(batch_id, [])
        if batch.paused:
            return "paused"
        selected_items = [item for item in items if item.selected]
        if any(item.status in {"launching", "running", "queued"} for item in selected_items):
            return "running"
        if any(item.status == "paused" for item in selected_items):
            return "paused"
        if selected_items and all(item.status == "completed" for item in selected_items):
            return "completed"
        if any(item.status == "failed" for item in selected_items):
            return "failed"
        return "draft"

    def _batch_item_status_for_job(self, job_status: str) -> str:
        mapping = {
            "queued": "queued",
            "running": "running",
            "waiting_retry": "running",
            "paused": "paused",
            "completed": "completed",
            "failed": "failed",
            "interrupted": "paused",
        }
        return mapping.get(job_status, "failed")

    def _batch_item_counts_as_active_locked(self, item: BatchItemState) -> bool:
        if not item.selected:
            return False
        if item.status == "running":
            return True
        if item.status != "launching":
            return False
        if not item.job_id:
            return True
        job = self.jobs.get(item.job_id)
        if job is None:
            return False
        if job.status == "running":
            return True
        return self._has_live_threads_locked(item.job_id)

    def _should_prefer_recovered_job_state(self, current: JobState, recovered: JobState) -> bool:
        if current.status == "running":
            return False
        current_terminal = current.status in {"completed", "failed"}
        recovered_terminal = recovered.status in {"completed", "failed"}
        if recovered_terminal and not current_terminal:
            return True
        if recovered.status == "completed" and current.status != "completed":
            return True
        if recovered.status == "failed" and current.status in {"paused", "interrupted", "queued"}:
            return True
        return recovered.updated_at >= current.updated_at

    def _should_use_recovered_batch_job_state(
        self,
        item: BatchItemState,
        current: JobState,
        recovered: JobState,
    ) -> bool:
        if self._should_prefer_recovered_job_state(current, recovered):
            return True
        return self._is_stale_failed_batch_item_state(item, current, recovered)

    def _is_stale_failed_batch_item_state(
        self,
        item: BatchItemState,
        current: JobState,
        recovered: JobState,
    ) -> bool:
        if current.status != "failed":
            return False
        if recovered.status in {"failed", "completed"}:
            return False
        if not item.output_dir:
            return False
        progress_chapter = self._recovered_progress_chapter_index(Path(item.output_dir))
        if progress_chapter <= 0:
            return False
        failed_chapter = max(
            self._extract_chapter_index_from_text(current.message),
            self._extract_chapter_index_from_text(item.last_error),
        )
        if failed_chapter <= 0:
            return False
        return progress_chapter > failed_chapter

    def _recovered_progress_chapter_index(self, output_dir: Path) -> int:
        best = 0
        committed_path = output_dir / "data" / "committed-progress.json"
        if committed_path.exists():
            try:
                committed = load_json(committed_path)
                if isinstance(committed, dict):
                    best = max(best, int(committed.get("last_committed_chapter_index", 0) or 0))
            except Exception:
                pass
        progress_path = output_dir / "data" / "progress.json"
        if progress_path.exists():
            try:
                progress = load_json(progress_path)
                if isinstance(progress, dict):
                    best = max(best, self._extract_chapter_index_from_progress_payload(progress))
            except Exception:
                pass
        return best

    def _extract_chapter_index_from_progress_payload(self, payload: dict[str, Any]) -> int:
        best = 0
        data = payload.get("data")
        if isinstance(data, dict):
            for key in ("chapter_index", "chapter", "index"):
                raw_value = data.get(key)
                try:
                    best = max(best, int(raw_value or 0))
                except (TypeError, ValueError):
                    continue
        best = max(best, self._extract_chapter_index_from_text(payload.get("message")))
        best = max(best, self._extract_chapter_index_from_text(payload.get("step")))
        return best

    def _extract_chapter_index_from_text(self, text: object) -> int:
        haystack = str(text or "")
        if not haystack:
            return 0
        match = _CHAPTER_INDEX_PATTERN.search(haystack)
        if match is None:
            return 0
        value = match.group(1) or match.group(2) or ""
        try:
            return int(value or 0)
        except ValueError:
            return 0

    def _batch_config_from_payload(self, payload: dict[str, Any], *, existing: BatchConfig | None = None) -> BatchConfig:
        base = existing or BatchConfig()
        tolerance = payload.get("chapter_char_tolerance")
        if tolerance in {None, ""}:
            base_tolerance = base.chapter_char_tolerance
            normalized_tolerance = 0.25 if base_tolerance in {None, ""} else max(0.05, min(0.4, float(base_tolerance)))
        else:
            normalized_tolerance = max(0.05, min(0.4, float(tolerance)))
        raw_run_to_completion = payload.get("run_to_completion")
        if raw_run_to_completion in {None, ""}:
            run_to_completion = bool(base.run_to_completion)
        elif isinstance(raw_run_to_completion, bool):
            run_to_completion = raw_run_to_completion
        else:
            run_to_completion = str(raw_run_to_completion).strip().lower() in {"1", "true", "yes", "on", "full", "complete", "completed"}
        raw_pause_at_chars = payload.get("pause_at_chars")
        if raw_pause_at_chars in {None, ""}:
            pause_at_chars = int(base.pause_at_chars or 300000)
        else:
            pause_at_chars = max(1, int(raw_pause_at_chars))
        if "chapter_count" in payload:
            raw_chapter_count = payload.get("chapter_count")
            chapter_count = None if raw_chapter_count in {None, ""} else int(raw_chapter_count)
        else:
            chapter_count = base.chapter_count
        if "volume_count" in payload:
            raw_volume_count = payload.get("volume_count")
            volume_count = None if raw_volume_count in {None, ""} else int(raw_volume_count)
        else:
            volume_count = base.volume_count
        if "ending_mode" in payload:
            raw_ending_mode = str(payload.get("ending_mode") or "").strip().lower()
            ending_mode = raw_ending_mode or ("series" if not run_to_completion else "standalone")
        else:
            ending_mode = base.ending_mode or ("series" if not run_to_completion else "standalone")
        market_profile = resolved_market_profile(
            payload.get("market_profile") or base.market_profile,
            payload,
        )
        output_language = normalized_output_language(payload.get("output_language") or base.output_language)
        pov = localized_pov(payload.get("pov") or base.pov, output_language)
        return BatchConfig(
            target_total_chars=int(payload["target_total_chars"]) if payload.get("target_total_chars") not in {None, ""} else base.target_total_chars,
            target_chars_per_chapter=int(payload["target_chars_per_chapter"]) if payload.get("target_chars_per_chapter") not in {None, ""} else base.target_chars_per_chapter,
            chapter_char_tolerance=normalized_tolerance,
            chapter_count=chapter_count,
            volume_count=volume_count,
            structure_mode=str(payload.get("structure_mode") or base.structure_mode or "story_driven"),
            market_profile=market_profile,
            progression_mode=normalized_progression_mode(payload.get("progression_mode") or base.progression_mode),
            progression_flavor=normalized_progression_flavor(payload.get("progression_flavor") or base.progression_flavor),
            progression_pacing=normalized_progression_pacing(payload.get("progression_pacing") or base.progression_pacing),
            power_system_hint=str(payload.get("power_system_hint") or base.power_system_hint or "").strip() or None,
            ending_mode=ending_mode,
            pov=pov,
            run_to_completion=run_to_completion,
            pause_at_chars=pause_at_chars,
            output_language=output_language,
        )

    def _batch_runtime_config_from_payload(self, payload: dict[str, Any] | None, *, existing: BatchConfig) -> BatchConfig:
        payload = payload or {}
        runtime_payload: dict[str, Any] = {}
        if "run_to_completion" in payload:
            runtime_payload["run_to_completion"] = payload.get("run_to_completion")
        if "pause_at_chars" in payload:
            runtime_payload["pause_at_chars"] = payload.get("pause_at_chars")
        if not runtime_payload:
            return existing
        return self._batch_config_from_payload(runtime_payload, existing=existing)

    def _apply_batch_runtime_overrides_locked(self, batch: BatchRecord, payload: dict[str, Any] | None) -> None:
        payload = payload or {}
        if payload.get("max_concurrent") not in {None, ""}:
            batch.max_concurrent = max(1, int(payload["max_concurrent"]))
        batch.config = self._batch_runtime_config_from_payload(payload, existing=batch.config)

    def _batch_item_hits_char_limit_locked(
        self,
        batch: BatchRecord,
        item: BatchItemState,
        job: JobState | None = None,
    ) -> tuple[bool, int]:
        if batch.config.run_to_completion:
            return False, 0
        output_dir_text = item.output_dir or (job.output_dir if job is not None else None)
        if not output_dir_text:
            return False, 0
        written_chars = self._batch_written_chars(Path(output_dir_text))
        limit = max(int(batch.config.pause_at_chars or 0), 1)
        return written_chars >= limit, written_chars

    def _hold_batch_item_for_char_limit_locked(
        self,
        batch: BatchRecord,
        item: BatchItemState,
        proposal: ProposalRecord | None,
        job: JobState | None = None,
        *,
        message: str,
    ) -> bool:
        reached, written_chars = self._batch_item_hits_char_limit_locked(batch, item, job)
        if not reached:
            return False
        item.status = "paused"
        item.pause_reason = "char_limit"
        item.last_error = None
        item.written_chars = written_chars
        item.updated_at = batch.updated_at
        if proposal is not None:
            proposal.status = "paused"
        if job is not None:
            job.status = "paused"
            job.step = "paused"
            job.message = message
            job.updated_at = batch.updated_at
            job.error = None
        return True

    def _running_job_total_locked(self) -> int:
        return sum(1 for state in self.jobs.values() if state.status == "running")

    def _queued_batch_candidate_locked(
        self,
        batch_id: str,
    ) -> tuple[ProposalRecord, BatchItemState, BatchRecord] | None:
        batch = self.batches.get(batch_id)
        if batch is None or batch.paused:
            return None
        items = self.batch_items.get(batch_id, [])
        active = sum(1 for item in items if self._batch_item_counts_as_active_locked(item))
        if active >= batch.max_concurrent:
            return None
        proposals = {proposal.proposal_id: proposal for proposal in self.batch_proposals.get(batch_id, [])}
        for item in sorted(items, key=lambda current: (current.priority, current.created_at)):
            if not item.selected or item.status != "queued":
                continue
            if item.job_id:
                continue
            proposal = proposals.get(item.proposal_id)
            if proposal is None:
                item.status = "failed"
                item.last_error = "Missing proposal payload."
                item.updated_at = time.time()
                self._persist_batch_locked(batch_id)
                continue
            return proposal, item, batch
        return None

    def _resumable_batch_candidate_locked(
        self,
        batch_id: str,
    ) -> tuple[BatchItemState, BatchRecord] | None:
        batch = self.batches.get(batch_id)
        if batch is None or batch.paused:
            return None
        items = self.batch_items.get(batch_id, [])
        active = sum(1 for item in items if self._batch_item_counts_as_active_locked(item))
        if active >= batch.max_concurrent:
            return None
        for item in sorted(items, key=lambda current: (current.priority, current.created_at)):
            if not item.selected or item.status not in {"paused", "queued"} or not item.job_id:
                continue
            if item.pause_reason == "char_limit":
                continue
            job = self.jobs.get(item.job_id)
            if job is None:
                continue
            if job.status in {"interrupted", "paused", "failed"}:
                return item, batch
        return None

    def _batch_tick(self) -> None:
        char_limit_candidates: list[tuple[str, str, str, Path, int]] = []
        launches: list[tuple[str, str, str, dict[str, Any] | None, dict[str, Any] | None, Path | None]] = []
        with self.lock:
            for batch_id in list(self.batches):
                self._sync_batch_items_locked(batch_id)
            for batch in self.batches.values():
                if batch.paused or batch.config.run_to_completion:
                    continue
                limit = max(int(batch.config.pause_at_chars or 0), 1)
                for item in self.batch_items.get(batch.batch_id, []):
                    if not item.selected or item.status != "running" or not item.job_id:
                        continue
                    job = self.jobs.get(item.job_id)
                    if job is None or job.status != "running" or not (item.output_dir or job.output_dir):
                        continue
                    char_limit_candidates.append(
                        (
                            batch.batch_id,
                            item.proposal_id,
                            item.job_id,
                            Path(item.output_dir or job.output_dir),
                            limit,
                        )
                    )
        for batch_id, proposal_id, job_id, output_dir, limit in char_limit_candidates:
            written_chars = self._batch_written_chars(output_dir)
            if written_chars < limit:
                continue
            try:
                self.pause_job(job_id)
            except (KeyError, ValueError):
                continue
            with self.lock:
                batch = self.batches.get(batch_id)
                item = self._find_batch_item_locked(batch_id, proposal_id)
                proposal = self._find_proposal_locked(batch_id, proposal_id)
                job = self.jobs.get(job_id)
                if batch is None or item is None or job is None or job.status != "paused":
                    continue
                item.pause_reason = "char_limit"
                item.written_chars = written_chars
                item.updated_at = max(item.updated_at, time.time())
                if proposal is not None:
                    proposal.status = "paused"
                batch.updated_at = max(batch.updated_at, item.updated_at)
                self._sync_batch_delivery_artifacts_locked(batch, item, job)
                self._persist_batch_locked(batch_id)
        with self.lock:
            for batch_id in list(self.batches):
                self._sync_batch_items_locked(batch_id)
            available_slots = max(0, self.batch_global_max_running - self._running_job_total_locked())
            if available_slots <= 0:
                return
            ordered_batches = sorted(self.batches.values(), key=lambda item: item.created_at)
            now = time.time()
            for batch in ordered_batches:
                if available_slots <= 0:
                    break
                while available_slots > 0:
                    resume_candidate = self._resumable_batch_candidate_locked(batch.batch_id)
                    if resume_candidate is not None:
                        item, _ = resume_candidate
                        proposal = self._find_proposal_locked(batch.batch_id, item.proposal_id)
                        item.status = "launching"
                        item.last_error = None
                        item.pause_reason = None
                        item.updated_at = now
                        batch.status = "running"
                        batch.updated_at = now
                        if proposal is not None:
                            proposal.status = "launching"
                        launches.append(("resume", batch.batch_id, item.proposal_id, None, None, None))
                        self._persist_batch_locked(batch.batch_id)
                        available_slots -= 1
                        continue
                    create_candidate = self._queued_batch_candidate_locked(batch.batch_id)
                    if create_candidate is None:
                        break
                    proposal, item, _ = create_candidate
                    item.status = "launching"
                    item.last_error = None
                    item.pause_reason = None
                    item.updated_at = now
                    batch.status = "running"
                    batch.updated_at = now
                    proposal.status = "launching"
                    payload = to_plain_data(proposal_to_project_input(proposal, batch.config))
                    launches.append(
                        (
                            "create",
                            batch.batch_id,
                            proposal.proposal_id,
                            payload,
                            dict(batch.provider_snapshot),
                            self._batch_projects_root(batch),
                        )
                    )
                    self._persist_batch_locked(batch.batch_id)
                    available_slots -= 1
        for action, batch_id, proposal_id, payload, provider_data, output_root in launches:
            try:
                with self.lock:
                    batch = self.batches.get(batch_id)
                    item = self._find_batch_item_locked(batch_id, proposal_id)
                    if batch is None or batch.paused or item is None or not item.selected or item.status != "launching":
                        continue
                if action == "resume":
                    with self.lock:
                        item = self._find_batch_item_locked(batch_id, proposal_id)
                        if item is None or not item.job_id:
                            continue
                        job = self.jobs.get(item.job_id)
                        if job is None or job.status not in {"paused", "interrupted"}:
                            item.status = "paused"
                            item.updated_at = max(item.updated_at, time.time())
                            proposal = self._find_proposal_locked(batch_id, proposal_id)
                            if proposal is not None:
                                proposal.status = item.status
                            self._persist_batch_locked(batch_id)
                            continue
                    if item is None or not item.job_id:
                        raise ValueError("Missing paused batch job for resume.")
                    self._launch_job(
                        item.job_id,
                        resume=True,
                        step="resume",
                        message="从批量任务恢复运行。",
                    )
                    with self.lock:
                        current_item = self._find_batch_item_locked(batch_id, proposal_id)
                        proposal = self._find_proposal_locked(batch_id, proposal_id)
                        job = self.jobs.get(item.job_id)
                        if current_item is not None and job is not None:
                            current_item.status = self._batch_item_status_for_job(job.status)
                            current_item.output_dir = job.output_dir
                            current_item.last_error = None
                            current_item.updated_at = time.time()
                            if proposal is not None:
                                proposal.status = current_item.status
                            self._persist_batch_locked(batch_id)
                    continue
                created = self._create_job_payload(payload or {}, provider_override=provider_data, output_root=output_root)
            except Exception as exc:
                with self.lock:
                    item = self._find_batch_item_locked(batch_id, proposal_id)
                    proposal = self._find_proposal_locked(batch_id, proposal_id)
                    if item is not None:
                        item.status = "failed"
                        item.last_error = str(exc)
                        item.updated_at = time.time()
                    if proposal is not None:
                        proposal.status = "failed"
                    self._persist_batch_locked(batch_id)
                continue
            with self.lock:
                item = self._find_batch_item_locked(batch_id, proposal_id)
                proposal = self._find_proposal_locked(batch_id, proposal_id)
                if item is None:
                    continue
                item.job_id = created["job_id"]
                item.output_dir = created["output_dir"]
                item.status = self._batch_item_status_for_job(created["status"])
                item.last_error = None
                item.updated_at = time.time()
                if proposal is not None:
                    proposal.status = item.status
                self._persist_batch_locked(batch_id)

    def _find_batch_item_locked(self, batch_id: str, proposal_id: str) -> BatchItemState | None:
        for item in self.batch_items.get(batch_id, []):
            if item.proposal_id == proposal_id:
                return item
        return None

    def _find_proposal_locked(self, batch_id: str, proposal_id: str) -> ProposalRecord | None:
        for proposal in self.batch_proposals.get(batch_id, []):
            if proposal.proposal_id == proposal_id:
                return proposal
        return None

    def _panel_state_path(self, output_dir: Path) -> Path:
        return output_dir / "data" / "panel-state.json"

    def _open_path_in_file_manager(self, path: Path) -> None:
        if hasattr(os, "startfile"):
            os.startfile(str(path))  # type: ignore[attr-defined]
            return
        command = ["open", str(path)] if sys.platform == "darwin" else ["xdg-open", str(path)]
        subprocess.Popen(command)

    def _load_panel_state(self, output_dir: Path) -> dict[str, Any]:
        panel_state_path = self._panel_state_path(output_dir)
        if not panel_state_path.exists():
            return {}
        try:
            loaded = load_json(panel_state_path)
        except Exception:
            return {}
        return loaded if isinstance(loaded, dict) else {}

    def _write_panel_state_locked(self, state: JobState) -> None:
        output_dir = Path(state.output_dir)
        data_dir = output_dir / "data"
        ensure_directory(data_dir)
        self._panel_state_path(output_dir).write_text(
            json.dumps({"hidden": state.hidden}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _recover_failed_chapter_snapshot(self, output_dir: Path) -> tuple[int, str, float] | None:
        state_dir = output_dir / "state"
        if not state_dir.exists():
            return None
        candidates = sorted(
            state_dir.glob("chapter-*.failed.review.json"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for path in candidates:
            try:
                payload = load_json(path)
            except Exception:
                payload = None
            chapter_match = re.search(r"chapter-(\d+)", path.name, re.IGNORECASE)
            if chapter_match is not None:
                try:
                    chapter_index = int(chapter_match.group(1) or 0)
                except ValueError:
                    chapter_index = 0
            else:
                chapter_index = self._extract_chapter_index_from_text(path.name)
            message = f"Chapter {chapter_index} failed quality gates." if chapter_index > 0 else "章节审校未通过。"
            if isinstance(payload, dict):
                model = payload.get("model") if isinstance(payload.get("model"), dict) else {}
                local = payload.get("local") if isinstance(payload.get("local"), dict) else {}
                issues = model.get("issues") if isinstance(model.get("issues"), list) else []
                local_issues = local.get("issues") if isinstance(local.get("issues"), list) else []
                message = str(
                    model.get("short_summary")
                    or next((str(item) for item in issues if item), "")
                    or local.get("short_summary")
                    or next((str(item) for item in local_issues if item), "")
                    or message
                )
            try:
                updated_at = path.stat().st_mtime
            except OSError:
                updated_at = output_dir.stat().st_mtime
            return chapter_index, message, updated_at
        return None

    def _recover_job_state(self, output_dir: Path) -> JobState | None:
        failed_chapter_snapshot = self._recover_failed_chapter_snapshot(output_dir)
        try:
            reconcile_committed_run_state(output_dir)
        except Exception:
            pass
        data_dir = output_dir / "data"
        state_dir = output_dir / "state"
        input_path = data_dir / "project-input.json"
        provider_path = data_dir / "provider.snapshot.json"
        if not input_path.exists():
            return None
        try:
            payload = load_json(input_path)
        except Exception:
            return None
        title = str(payload.get("title") or output_dir.name)
        summary_path = data_dir / "run-summary.json"
        progress_path = data_dir / "progress.json"
        final_review_path = state_dir / "final-review.latest.json"
        summary = None
        step = "interrupted"
        status = "interrupted"
        message = "检测到未完成任务，可点击恢复运行。"
        pending_upper_decision = self._load_pending_upper_decision(output_dir)
        pause_snapshot = self._load_pause_snapshot(output_dir)
        progress_payload: dict[str, Any] | None = None
        if summary_path.exists():
            try:
                loaded_summary = load_json(summary_path)
                if isinstance(loaded_summary, dict):
                    summary = loaded_summary
                    status = "completed"
                    step = "completed"
                    message = str(loaded_summary.get("final_summary") or "任务已完成。")
            except Exception:
                pass
        if summary is None and final_review_path.exists():
            try:
                loaded_review = load_json(final_review_path)
                if isinstance(loaded_review, dict) and not bool(loaded_review.get("passed")):
                    status = "failed"
                    step = "failed"
                    issues = loaded_review.get("issues") if isinstance(loaded_review.get("issues"), list) else []
                    issue_summary = "；".join(str(item) for item in issues[:2] if item)
                    message = str(loaded_review.get("short_summary") or issue_summary or "终审未通过。")
            except Exception:
                pass
        if summary is None and progress_path.exists():
            try:
                progress = load_json(progress_path)
                if isinstance(progress, dict):
                    progress_payload = progress
                    step = str(progress.get("step") or step)
                    original_message = str(progress.get("message") or message)
                    if status == "failed":
                        message = message or original_message
                    elif step == "failed":
                        status = "failed"
                        message = original_message
                    else:
                        message = f"检测到未完成任务，上次停在 {step}，可点击恢复运行。"
            except Exception:
                pass
        if summary is None and status != "failed" and failed_chapter_snapshot is not None:
            failed_chapter, failed_message, _failed_updated_at = failed_chapter_snapshot
            progress_chapter = self._extract_chapter_index_from_progress_payload(progress_payload or {})
            if progress_chapter <= failed_chapter:
                status = "failed"
                step = "failed"
                message = failed_message
        if summary is None and pause_snapshot is not None and status != "failed":
            status = "paused"
            step = "paused"
            message = str(pause_snapshot.get("message") or "检测到服务关闭前的暂停快照，可点击恢复运行。")
        if summary is None and pending_upper_decision is not None:
            status = "interrupted"
            step = "resume"
            decision_name = str(pending_upper_decision.get("decision") or "phase_repair")
            scope_start = int(pending_upper_decision.get("scope_start_chapter") or 0)
            scope_end = int(pending_upper_decision.get("scope_end_chapter") or 0)
            reason = str(pending_upper_decision.get("reason") or "").strip()
            message = (
                f"检测到旧版上层决策快照 {decision_name}，范围 {scope_start}-{scope_end}。"
                + (f" {reason}" if reason else "")
                + " 当前版本会在恢复运行时按自动修复策略继续。"
            )
            pending_upper_decision = None
        job_id = output_dir.name.rsplit("-", 1)[-1]
        if len(job_id) != 8:
            job_id = slugify(output_dir.name)[:8] or uuid.uuid4().hex[:8]
        updated_at = max(
            input_path.stat().st_mtime,
            summary_path.stat().st_mtime if summary_path.exists() else 0.0,
            progress_path.stat().st_mtime if progress_path.exists() else 0.0,
            final_review_path.stat().st_mtime if final_review_path.exists() else 0.0,
            failed_chapter_snapshot[2] if failed_chapter_snapshot is not None else 0.0,
            output_dir.stat().st_mtime,
        )
        created_at = min(input_path.stat().st_mtime, output_dir.stat().st_mtime)
        panel_state = self._load_panel_state(output_dir)
        provider_data: dict[str, Any] = {}
        if provider_path.exists():
            try:
                loaded_provider = load_json(provider_path)
                if isinstance(loaded_provider, dict):
                    provider_data = loaded_provider
            except Exception:
                provider_data = {}
        return JobState(
            job_id=job_id,
            title=title,
            output_dir=str(output_dir),
            status=status,
            created_at=created_at,
            updated_at=updated_at,
            step=step,
            message=message,
            summary=summary,
            hidden=bool(panel_state.get("hidden")),
            stall_timeout_seconds=self.stall_timeout_seconds,
            input_payload=payload if isinstance(payload, dict) else {},
            provider_override=provider_data,
            pending_upper_decision=pending_upper_decision,
            log=[JobLogEntry(step=step, message=message, created_at=updated_at)],
        )

    def _run_job(self, job_id: str, payload: dict[str, Any], output_dir: Path, *, resume: bool, run_token: str) -> None:
        try:
            self._assert_run_is_current(job_id, run_token)
            preserve_resume_controls = False
            with self.lock:
                current_state = self.jobs.get(job_id)
                if (
                    resume
                    and current_state is not None
                    and current_state.run_token == run_token
                    and current_state.step == "upstream_retry"
                ):
                    preserve_resume_controls = True
            provider = self._provider_for_job(job_id)
            self._assert_run_is_current(job_id, run_token)
            base_client = OpenAICompatibleClient(provider)
            effective_stall_timeout = max(self.stall_timeout_seconds, base_client.request_time_budget_seconds() + 60)
            self._set_job_stall_timeout(job_id, effective_stall_timeout, run_token=run_token)
            client = GuardedClient(base_client, lambda: self._assert_run_is_current(job_id, run_token))
            pipeline = NovelPipeline(
                client,
                output_dir,
                flagship_model=provider.model,
                light_model=getattr(provider, "light_model", getattr(provider, "review_model", None)),
                review_model=getattr(provider, "review_model", getattr(provider, "light_model", None)),
                resume=resume,
                preserve_resume_controls=preserve_resume_controls,
                progress_callback=self._progress_callback(job_id, run_token),
            )
            summary = pipeline.run(project_input_from_dict(payload))
            self._update_job(
                job_id,
                status="completed",
                step="completed",
                message=summary.final_summary,
                summary=asdict(summary),
                run_token=run_token,
            )
        except (JobRunCancelled, StaleJobAttempt):
            return
        except Exception as exc:
            if self._maybe_auto_resume_after_failure(job_id, run_token, exc):
                return
            self._update_job(
                job_id,
                status="failed",
                step="failed",
                message=str(exc),
                error=traceback.format_exc(),
                run_token=run_token,
            )

    def _provider_for_job(self, job_id: str):
        with self.lock:
            state = self.jobs.get(job_id)
            provider_data = dict(state.provider_override) if state is not None else {}
        if provider_data:
            return resolve_provider_config(
                provider_data,
                codex_dir=self.codex_dir,
                project_root=self.root,
                preserve_saved_api_key=True,
            )
        return load_provider_config(self.codex_dir, project_root=self.root)

    def _job_provider_summary_locked(self, state: JobState) -> dict[str, Any]:
        provider_data = self._sanitize_provider_payload(state.provider_override)
        source = "job_snapshot"
        if not provider_data:
            provider = load_provider_config(self.codex_dir, project_root=self.root)
            provider_data = provider_snapshot(provider, include_api_key=False)
            source = "current_default"
        return {
            "source": source,
            "base_url": provider_data.get("base_url"),
            "wire_api": provider_data.get("wire_api"),
            "model": provider_data.get("model"),
            "light_model": provider_data.get("light_model") or provider_data.get("review_model"),
            "review_model": provider_data.get("review_model") or provider_data.get("light_model"),
            "continuation_mode": provider_data.get("continuation_mode"),
            "gateway_profile": provider_data.get("gateway_profile"),
        }

    def _progress_callback(self, job_id: str, run_token: str):
        def callback(step: str, message: str, data: dict[str, Any]) -> None:
            self._assert_run_is_current(job_id, run_token)
            self._update_job(job_id, status="running", step=step, message=message, run_token=run_token)

        return callback

    def _update_job(
        self,
        job_id: str,
        *,
        status: str,
        step: str,
        message: str,
        summary: dict[str, Any] | None = None,
        error: str | None = None,
        run_token: str | None = None,
    ) -> bool:
        with self.lock:
            state = self.jobs.get(job_id)
            if state is None:
                return False
            if run_token is not None and state.run_token != run_token:
                return False
            state.status = status
            state.step = step
            state.message = message
            state.updated_at = time.time()
            if status == "running" and step not in {"start", "resume", "auto_resume", "upstream_retry", "upstream_backoff"}:
                self._clear_upstream_retry_state_locked(state)
            if summary is not None:
                state.summary = summary
            if error is not None:
                state.error = error
            if status != "paused":
                self._clear_pause_snapshot_locked(state)
            state.log.append(JobLogEntry(step=step, message=message, created_at=time.time()))
            if len(state.log) > 120:
                state.log = state.log[-120:]
            return True

    def _launch_job(
        self,
        job_id: str,
        *,
        resume: bool,
        step: str,
        message: str,
        auto: bool = False,
        upstream_retry: bool = False,
        expected_run_token: str | None = None,
    ) -> None:
        launched = self._activate_attempt(
            job_id,
            resume=resume,
            step=step,
            message=message,
            auto=auto,
            upstream_retry=upstream_retry,
            expected_run_token=expected_run_token,
        )
        if launched is None:
            return
        payload, output_dir, run_token = launched
        self._spawn_job_thread(job_id, payload, output_dir, resume=resume, run_token=run_token)

    def _activate_attempt(
        self,
        job_id: str,
        *,
        resume: bool,
        step: str,
        message: str,
        auto: bool,
        upstream_retry: bool,
        expected_run_token: str | None,
    ) -> tuple[dict[str, Any], Path, str] | None:
        with self.lock:
            state = self.jobs.get(job_id)
            if state is None:
                raise KeyError(job_id)
            if state.status == "completed":
                raise ValueError("Completed jobs do not need another attempt.")
            if expected_run_token is not None and state.run_token != expected_run_token:
                return None
            if auto and state.auto_resume_count >= self.max_auto_resumes:
                return None
            if state.cancel_requested and not resume:
                return None
            now = time.time()
            state.cancel_requested = False
            state.status = "running"
            state.step = step
            state.message = message
            state.updated_at = now
            state.error = None
            state.summary = None
            state.attempt_count += 1
            if auto:
                state.auto_resume_count += 1
            if step == "resume" and not upstream_retry:
                self._clear_upstream_retry_state_locked(state)
            if upstream_retry:
                state.upstream_retry_count += 1
                state.upstream_next_retry_at = 0.0
            state.stall_timeout_seconds = max(state.stall_timeout_seconds or 0, self.stall_timeout_seconds)
            state.run_token = uuid.uuid4().hex
            state.log.append(JobLogEntry(step=step, message=message, created_at=now))
            if len(state.log) > 120:
                state.log = state.log[-120:]
            return dict(state.input_payload), Path(state.output_dir), state.run_token

    def _spawn_job_thread(
        self,
        job_id: str,
        payload: dict[str, Any],
        output_dir: Path,
        *,
        resume: bool,
        run_token: str,
    ) -> None:
        def runner() -> None:
            try:
                self._run_job(job_id, payload, output_dir, resume=resume, run_token=run_token)
            finally:
                with self.lock:
                    threads = self._active_threads.get(job_id)
                    if threads is not None:
                        threads.pop(run_token, None)
                        if not threads:
                            self._active_threads.pop(job_id, None)
                self._batch_tick()

        thread = threading.Thread(
            target=runner,
            daemon=True,
        )
        with self.lock:
            self._active_threads.setdefault(job_id, {})[run_token] = thread
        thread.start()

    def _has_live_threads_locked(self, job_id: str) -> bool:
        threads = self._active_threads.get(job_id, {})
        alive_tokens = [token for token, thread in threads.items() if thread.is_alive()]
        if len(alive_tokens) != len(threads):
            self._active_threads[job_id] = {token: threads[token] for token in alive_tokens}
        if not alive_tokens:
            self._active_threads.pop(job_id, None)
            return False
        return True

    def _assert_run_is_current(self, job_id: str, run_token: str) -> None:
        with self.lock:
            state = self.jobs.get(job_id)
            if state is None or state.run_token != run_token:
                raise StaleJobAttempt(job_id)
            if state.cancel_requested or state.status == "paused":
                raise JobRunCancelled(job_id)

    def _maybe_auto_resume_after_failure(self, job_id: str, run_token: str, exc: Exception) -> bool:
        if not self._is_retryable_exception(exc):
            return False
        schedule = self._plan_upstream_retry(job_id, run_token, exc)
        if schedule is None:
            return False
        if schedule["action"] == "retry":
            self._launch_job(
                job_id,
                resume=True,
                step="upstream_retry",
                message=str(schedule["message"]),
                upstream_retry=True,
                expected_run_token=run_token,
            )
        return True

    def _plan_upstream_retry(self, job_id: str, run_token: str, exc: Exception) -> dict[str, Any] | None:
        summary = self._short_error(exc)
        now = time.time()
        with self.lock:
            state = self.jobs.get(job_id)
            if state is None or state.run_token != run_token or state.cancel_requested:
                return None
            launched = state.upstream_retry_count
            state.upstream_last_error = summary
            if launched in {0, 1, 2, 4, 5, 7, 8}:
                next_attempt = launched + 1
                return {
                    "action": "retry",
                    "message": f"上游调用异常，正在重试当前任务（{next_attempt}/9）：{summary}",
                }
            if launched == self.UPSTREAM_RETRY_STAGE_LIMITS[0]:
                state.status = "waiting_retry"
                state.step = "upstream_backoff"
                state.message = f"上游连续异常，已暂停自动重试 10 分钟后继续（下一轮 4-6/9）：{summary}"
                state.updated_at = now
                state.upstream_next_retry_at = now + self.UPSTREAM_RETRY_STAGE_COOLDOWNS[0]
                state.log.append(JobLogEntry(step="upstream_backoff", message=state.message, created_at=now))
                if len(state.log) > 120:
                    state.log = state.log[-120:]
                return {"action": "wait"}
            if launched == self.UPSTREAM_RETRY_STAGE_LIMITS[1]:
                state.status = "waiting_retry"
                state.step = "upstream_backoff"
                state.message = f"上游仍未恢复，已暂停自动重试 20 分钟后继续（下一轮 7-9/9）：{summary}"
                state.updated_at = now
                state.upstream_next_retry_at = now + self.UPSTREAM_RETRY_STAGE_COOLDOWNS[1]
                state.log.append(JobLogEntry(step="upstream_backoff", message=state.message, created_at=now))
                if len(state.log) > 120:
                    state.log = state.log[-120:]
                return {"action": "wait"}
            if launched >= self.UPSTREAM_RETRY_STAGE_LIMITS[2]:
                state.status = "paused"
                state.step = "paused"
                state.message = f"上游连续异常，已按 3+3+3 重试计划耗尽，任务已暂停：{summary}"
                state.error = state.message
                state.updated_at = now
                state.upstream_next_retry_at = 0.0
                state.log.append(JobLogEntry(step="paused", message=state.message, created_at=now))
                if len(state.log) > 120:
                    state.log = state.log[-120:]
                return {"action": "pause"}
        return None

    def _clear_upstream_retry_state_locked(self, state: JobState) -> None:
        state.upstream_retry_count = 0
        state.upstream_next_retry_at = 0.0
        state.upstream_last_error = None

    def _set_job_stall_timeout(self, job_id: str, stall_timeout_seconds: int, *, run_token: str) -> None:
        with self.lock:
            state = self.jobs.get(job_id)
            if state is None or state.run_token != run_token:
                return
            state.stall_timeout_seconds = max(stall_timeout_seconds, self.stall_timeout_seconds)

    def _watchdog_loop(self) -> None:
        while not self._stop_event.wait(self.watchdog_interval_seconds):
            self._watchdog_tick()

    def _watchdog_tick(self, now: float | None = None) -> None:
        current = time.time() if now is None else now
        to_resume: list[tuple[str, str, str, int, int]] = []
        to_fail: list[tuple[str, str, str, int]] = []
        to_retry_after_backoff: list[tuple[str, str, str, int]] = []
        with self.lock:
            for state in self.jobs.values():
                if state.status == "waiting_retry" and state.upstream_next_retry_at and current >= state.upstream_next_retry_at:
                    to_retry_after_backoff.append(
                        (state.job_id, state.run_token, state.upstream_last_error or "上游异常", state.upstream_retry_count + 1)
                    )
                    continue
                if state.status != "running" or state.cancel_requested or not state.run_token:
                    continue
                stalled_for = int(current - state.updated_at)
                effective_limit = state.stall_timeout_seconds or self.stall_timeout_seconds
                if stalled_for < effective_limit:
                    continue
                if state.auto_resume_count < self.max_auto_resumes:
                    to_resume.append((state.job_id, state.run_token, state.step, stalled_for, state.auto_resume_count + 1))
                else:
                    to_fail.append((state.job_id, state.run_token, state.step, stalled_for))

        for job_id, run_token, summary, next_count in to_retry_after_backoff:
            self._launch_job(
                job_id,
                resume=True,
                step="upstream_retry",
                message=f"上游恢复窗口已到，继续重试当前任务（{next_count}/9）：{summary}",
                upstream_retry=True,
                expected_run_token=run_token,
            )
        for job_id, run_token, step, stalled_for, next_count in to_resume:
            self._launch_job(
                job_id,
                resume=True,
                step="auto_resume",
                message=f"步骤 {step} 已 {stalled_for} 秒无进展，已自动续跑（{next_count}/{self.max_auto_resumes}）。",
                auto=True,
                expected_run_token=run_token,
            )
        for job_id, run_token, step, stalled_for in to_fail:
            self._fail_stalled_job(
                job_id,
                run_token=run_token,
                message=f"步骤 {step} 已 {stalled_for} 秒无进展，且超过自动恢复次数。",
            )
        self._batch_tick()

    def _fail_stalled_job(self, job_id: str, *, run_token: str, message: str) -> None:
        with self.lock:
            state = self.jobs.get(job_id)
            if state is None or state.run_token != run_token:
                return
            state.run_token = uuid.uuid4().hex
            state.status = "failed"
            state.step = "failed"
            state.message = message
            state.error = message
            state.updated_at = time.time()
            state.log.append(JobLogEntry(step="failed", message=message, created_at=time.time()))
            if len(state.log) > 120:
                state.log = state.log[-120:]

    def _is_retryable_exception(self, exc: Exception) -> bool:
        if isinstance(exc, TimeoutError):
            return True
        if isinstance(exc, (http.client.RemoteDisconnected, http.client.IncompleteRead, ConnectionResetError, ConnectionAbortedError, BrokenPipeError)):
            return True
        if isinstance(exc, ModelClientError):
            return is_retryable_error_text(str(exc))
        return is_retryable_error_text(str(exc))

    def _short_error(self, exc: Exception) -> str:
        text = " ".join(str(exc).split())
        return text[:180] if len(text) > 180 else text

    def _load_preview_text(self, output_dir: Path, *, limit: int = 6000) -> str | None:
        novel_path = output_dir / "novel.md"
        if novel_path.exists():
            return novel_path.read_text(encoding="utf-8")[:limit]
        chapter_dir = output_dir / "chapters"
        if not chapter_dir.exists():
            return None
        chapter_files: list[tuple[int, Path]] = []
        for path in chapter_dir.glob("chapter-*.md"):
            try:
                chapter_index = int(path.stem.split("-")[1])
            except (IndexError, ValueError):
                continue
            chapter_files.append((chapter_index, path))
        if not chapter_files:
            return None
        chapter_files.sort(key=lambda item: item[0])
        for chapter_index, path in reversed(chapter_files):
            text = path.read_text(encoding="utf-8").strip()
            if not text:
                continue
            header = f"运行预览：已完成 {len(chapter_files)} 章，当前展示第 {chapter_index} 章正文。\n\n"
            return (header + text)[:limit]
        return None

    def _snapshot(
        self,
        state: JobState,
        *,
        include_preview: bool,
        include_log: bool = True,
        batch_job_ids: set[str] | None = None,
    ) -> dict[str, Any]:
        stalled_for_seconds = 0
        if state.status == "running":
            stalled_for_seconds = max(0, int(time.time() - state.updated_at))
        payload = {
            "job_id": state.job_id,
            "title": state.title,
            "output_dir": state.output_dir,
            "status": state.status,
            "step": state.step,
            "hidden": state.hidden,
            "created_at": state.created_at,
            "updated_at": state.updated_at,
            "message": state.message,
            "summary": state.summary,
            "error": state.error,
            "attempt_count": state.attempt_count,
            "auto_resume_count": state.auto_resume_count,
            "upstream_retry_count": state.upstream_retry_count,
            "upstream_next_retry_at": state.upstream_next_retry_at or None,
            "upstream_last_error": state.upstream_last_error,
            "cancel_requested": state.cancel_requested,
            "stall_timeout_seconds": state.stall_timeout_seconds or self.stall_timeout_seconds,
            "stalled_for_seconds": stalled_for_seconds,
            "job_kind": self._job_kind_for_state_locked(state, batch_job_ids=batch_job_ids),
            "provider_snapshot": self._job_provider_summary_locked(state),
        }
        if include_log:
            payload["log"] = [{"step": item.step, "message": item.message, "created_at": item.created_at} for item in state.log]
        if include_preview:
            output_dir = Path(state.output_dir)
            preview_text = self._load_preview_text(output_dir)
            if preview_text:
                payload["novel_preview"] = preview_text
            summary_path = output_dir / "data" / "run-summary.json"
            if summary_path.exists():
                payload["summary"] = load_json(summary_path)
        return payload


class _Handler(BaseHTTPRequestHandler):
    app: SagaQuillApp
    access_token: str = ""
    require_auth: bool = False

    def _is_authorized(self) -> bool:
        if not self.require_auth:
            return True
        token = (self.access_token or "").strip()
        if not token:
            return False
        candidates = [
            self.headers.get("X-SagaQuill-Token", ""),
            self.headers.get("X-Access-Token", ""),
        ]
        auth_header = self.headers.get("Authorization", "")
        if auth_header.lower().startswith("bearer "):
            candidates.append(auth_header[7:].strip())
        if auth_header.lower().startswith("basic "):
            try:
                decoded = base64.b64decode(auth_header[6:].strip()).decode("utf-8")
            except Exception:
                decoded = ""
            if ":" in decoded:
                candidates.append(decoded.split(":", 1)[1])
            else:
                candidates.append(decoded)
        return any(hmac.compare_digest(token, str(candidate or "").strip()) for candidate in candidates)

    def _reject_unauthorized(self) -> None:
        body = b"SagaQuill access token required.\n"
        self.send_response(HTTPStatus.UNAUTHORIZED)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("WWW-Authenticate", 'Basic realm="SagaQuill"')
        self.send_header("WWW-Authenticate", 'Bearer realm="SagaQuill"')
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _safe_send_error(self, status: HTTPStatus) -> None:
        try:
            self.send_error(status)
        except Exception as exc:
            if _is_client_disconnect_error(exc):
                return
            raise

    def _safe_send_text(
        self,
        text: str,
        *,
        status: HTTPStatus = HTTPStatus.OK,
        content_type: str = "text/plain; charset=utf-8",
    ) -> None:
        try:
            self._send_text(text, status=status, content_type=content_type)
        except Exception as exc:
            if _is_client_disconnect_error(exc):
                return
            raise

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        try:
            if parsed.path == "/healthz":
                self._send_json({"ok": True})
                return
            if not self._is_authorized():
                self._reject_unauthorized()
                return
            if parsed.path == "/":
                self._send_text(panel_html(), content_type="text/html; charset=utf-8")
                return
            if parsed.path == "/api/info":
                self._send_json(self.app.info())
                return
            if parsed.path == "/api/provider":
                self._send_json(self.app.provider_settings())
                return
            if parsed.path == "/api/template":
                self._send_json(self.app.template())
                return
            if parsed.path == "/api/batches":
                include_hidden = query.get("include_hidden", ["0"])[0].lower() in {"1", "true", "yes", "on"}
                try:
                    payload = self.app.list_batches(include_hidden=include_hidden)
                except TypeError:
                    payload = self.app.list_batches()
                self._send_json(payload)
                return
            if parsed.path.startswith("/api/batches/") and parsed.path.endswith("/export"):
                batch_id = parsed.path.split("/")[3]
                self._send_json(self.app.batch_export(batch_id))
                return
            if parsed.path.startswith("/api/batches/"):
                batch_id = parsed.path.split("/")[3]
                self._send_json(self.app.batch_snapshot(batch_id))
                return
            if parsed.path == "/api/jobs":
                include_hidden = query.get("include_hidden", ["0"])[0].lower() in {"1", "true", "yes", "on"}
                job_kind = query.get("kind", ["all"])[0].lower()
                self._send_json(self.app.list_jobs(include_hidden=include_hidden, job_kind=job_kind))
                return
            if parsed.path.startswith("/api/jobs/") and parsed.path.endswith("/novel"):
                job_id = parsed.path.split("/")[3]
                self._send_text(self.app.novel_text(job_id), content_type="text/plain; charset=utf-8")
                return
            if parsed.path.startswith("/api/jobs/"):
                job_id = parsed.path.split("/")[3]
                self._send_json(self.app.job_snapshot(job_id))
                return
            self.send_error(HTTPStatus.NOT_FOUND)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return
        except KeyError:
            self._safe_send_error(HTTPStatus.NOT_FOUND)
        except FileNotFoundError:
            self._safe_send_error(HTTPStatus.NOT_FOUND)
        except Exception as exc:
            self._safe_send_text(str(exc), status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_POST(self) -> None:  # noqa: N802
        if not self._is_authorized():
            self._reject_unauthorized()
            return
        parsed = urlparse(self.path)
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            raw_body = self.rfile.read(content_length) if content_length else b""
            payload = json.loads(raw_body.decode("utf-8")) if raw_body else {}
            if parsed.path.startswith("/api/jobs/") and parsed.path.endswith("/cancel"):
                job_id = parsed.path.split("/")[3]
                self._send_json(self.app.cancel_job(job_id))
                return
            if parsed.path.startswith("/api/jobs/") and parsed.path.endswith("/pause"):
                job_id = parsed.path.split("/")[3]
                self._send_json(self.app.pause_job(job_id))
                return
            if parsed.path.startswith("/api/jobs/") and parsed.path.endswith("/resume"):
                job_id = parsed.path.split("/")[3]
                self._send_json(self.app.resume_job(job_id, payload))
                return
            if parsed.path.startswith("/api/jobs/") and parsed.path.endswith("/hide"):
                job_id = parsed.path.split("/")[3]
                self._send_json(self.app.hide_job(job_id))
                return
            if parsed.path.startswith("/api/jobs/") and parsed.path.endswith("/unhide"):
                job_id = parsed.path.split("/")[3]
                self._send_json(self.app.unhide_job(job_id))
                return
            if parsed.path.startswith("/api/jobs/") and parsed.path.endswith("/delete"):
                job_id = parsed.path.split("/")[3]
                confirm_title = str(payload.get("confirm_title") or "")
                confirm_job_id = str(payload.get("confirm_job_id") or "")
                self._send_json(self.app.delete_job(job_id, confirm_title=confirm_title, confirm_job_id=confirm_job_id))
                return
            if parsed.path.startswith("/api/jobs/") and parsed.path.endswith("/open-folder"):
                job_id = parsed.path.split("/")[3]
                self._send_json(self.app.open_output_dir(job_id))
                return
            if parsed.path.startswith("/api/jobs/") and parsed.path.endswith("/delivery-cleanup"):
                job_id = parsed.path.split("/")[3]
                self._send_json(self.app.delivery_cleanup(job_id))
                return
            if parsed.path == "/api/provider":
                self._send_json(self.app.save_provider_settings(payload))
                return
            if parsed.path == "/api/provider/reset":
                self._send_json(self.app.reset_provider_settings())
                return
            if parsed.path == "/api/provider/test":
                self._send_json(self.app.test_provider(payload))
                return
            if parsed.path == "/api/batches/import-csv":
                self._send_json(self.app.import_batch_csv(payload), status=HTTPStatus.CREATED)
                return
            if parsed.path.startswith("/api/batches/") and parsed.path.endswith("/launch"):
                batch_id = parsed.path.split("/")[3]
                self._send_json(self.app.launch_batch(batch_id, payload))
                return
            if parsed.path.startswith("/api/batches/") and parsed.path.endswith("/open-folder"):
                batch_id = parsed.path.split("/")[3]
                self._send_json(self.app.open_batch_dir(batch_id))
                return
            if parsed.path.startswith("/api/batches/") and parsed.path.endswith("/hide"):
                batch_id = parsed.path.split("/")[3]
                self._send_json(self.app.hide_batch(batch_id))
                return
            if parsed.path.startswith("/api/batches/") and parsed.path.endswith("/unhide"):
                batch_id = parsed.path.split("/")[3]
                self._send_json(self.app.unhide_batch(batch_id))
                return
            if parsed.path.startswith("/api/batches/") and "/items/" in parsed.path and parsed.path.endswith("/pause"):
                parts = parsed.path.strip("/").split("/")
                batch_id = parts[2]
                proposal_id = parts[4]
                self._send_json(self.app.pause_batch_item(batch_id, proposal_id))
                return
            if parsed.path.startswith("/api/batches/") and parsed.path.endswith("/pause"):
                batch_id = parsed.path.split("/")[3]
                self._send_json(self.app.pause_batch(batch_id))
                return
            if parsed.path.startswith("/api/batches/") and "/items/" in parsed.path and parsed.path.endswith("/resume"):
                parts = parsed.path.strip("/").split("/")
                batch_id = parts[2]
                proposal_id = parts[4]
                self._send_json(self.app.resume_batch_item(batch_id, proposal_id, payload))
                return
            if parsed.path.startswith("/api/batches/") and parsed.path.endswith("/resume"):
                batch_id = parsed.path.split("/")[3]
                self._send_json(self.app.resume_batch(batch_id, payload))
                return
            if parsed.path.startswith("/api/batches/") and parsed.path.endswith("/resume-all"):
                batch_id = parsed.path.split("/")[3]
                self._send_json(self.app.resume_all_batch(batch_id, payload))
                return
            if parsed.path.startswith("/api/batches/") and parsed.path.endswith("/retry-failed"):
                batch_id = parsed.path.split("/")[3]
                self._send_json(self.app.retry_failed_batch(batch_id, payload))
                return
            if parsed.path.startswith("/api/batches/") and parsed.path.endswith("/delete"):
                batch_id = parsed.path.split("/")[3]
                self._send_json(self.app.delete_batch(batch_id))
                return
            if parsed.path == "/api/jobs":
                self._send_json(self.app.create_job(payload), status=HTTPStatus.CREATED)
                return
            self.send_error(HTTPStatus.NOT_FOUND)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return
        except ValueError as exc:
            self._safe_send_text(str(exc), status=HTTPStatus.CONFLICT)
        except KeyError:
            self._safe_send_error(HTTPStatus.NOT_FOUND)
        except Exception as exc:
            self._safe_send_text(str(exc), status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _send_json(self, payload: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_text(self, text: str, *, status: HTTPStatus = HTTPStatus.OK, content_type: str = "text/plain; charset=utf-8") -> None:
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class SagaQuillServer(ThreadingHTTPServer):
    def __init__(self, server_address: tuple[str, int], handler_class: type[BaseHTTPRequestHandler], app: SagaQuillApp) -> None:
        self.app = app
        super().__init__(server_address, handler_class)

    def server_close(self) -> None:
        try:
            self.app.close()
        finally:
            super().server_close()


def build_server(
    host: str,
    port: int,
    codex_dir: str | None = None,
    project_root: str | Path | None = None,
    *,
    batch_global_max_running: int = 200,
    access_token: str | None = None,
    require_auth: bool | None = None,
) -> ThreadingHTTPServer:
    resolved_token = (access_token if access_token is not None else os.environ.get("SAGAQUILL_ACCESS_TOKEN", "")).strip()
    if require_auth is None:
        require_auth = bool(resolved_token) or (not _is_local_bind_host(host) and not _env_truthy("SAGAQUILL_ALLOW_NO_AUTH"))
    if require_auth and not resolved_token:
        raise ValueError(
            "SAGAQUILL_ACCESS_TOKEN is required when binding SagaQuill to a non-local host. "
            "Use --access-token or set SAGAQUILL_ACCESS_TOKEN. For trusted private networks only, set SAGAQUILL_ALLOW_NO_AUTH=1."
        )
    app = SagaQuillApp(
        codex_dir=codex_dir,
        project_root=project_root,
        batch_global_max_running=batch_global_max_running,
        autoload_existing=False,
    )

    class Handler(_Handler):
        pass

    Handler.app = app
    Handler.access_token = resolved_token
    Handler.require_auth = bool(require_auth)
    server = SagaQuillServer((host, port), Handler, app)
    app.start_background_recovery()
    return server


def run_server(
    host: str = "127.0.0.1",
    port: int = 8765,
    codex_dir: str | None = None,
    *,
    batch_global_max_running: int = 200,
    access_token: str | None = None,
    require_auth: bool | None = None,
) -> None:
    server = build_server(
        host,
        port,
        codex_dir=codex_dir,
        batch_global_max_running=batch_global_max_running,
        access_token=access_token,
        require_auth=require_auth,
    )
    print(f"http://{host}:{port}")
    if getattr(server.RequestHandlerClass, "require_auth", False):
        print("SagaQuill access token authentication is enabled.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
