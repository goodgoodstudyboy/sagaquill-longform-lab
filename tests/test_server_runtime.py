from __future__ import annotations

import http.client
import json
import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path
import uuid
from unittest.mock import patch

from sagaquill.client import ModelClientError
from sagaquill.models import BatchConfig, BatchItemState, BatchRecord, GenerationSummary, ProposalRecord, ProviderConfig
from sagaquill.models import StagnationDecision
from sagaquill.server import (
    GuardedClient,
    JobLogEntry,
    JobState,
    JobRunCancelled,
    SagaQuillApp,
    _is_client_disconnect_error,
    _legacy_batch_market_profile_payload,
)


class ServerRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory(prefix="sagaquill-server-runtime-")
        self.root = Path(self.tempdir.name)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _app(self, **kwargs: object) -> SagaQuillApp:
        return SagaQuillApp(project_root=self.root, **kwargs)

    def test_client_disconnect_errors_are_classified_as_non_fatal(self) -> None:
        self.assertTrue(_is_client_disconnect_error(BrokenPipeError()))
        self.assertTrue(_is_client_disconnect_error(ConnectionResetError()))
        self.assertTrue(_is_client_disconnect_error(ConnectionAbortedError()))
        self.assertFalse(_is_client_disconnect_error(RuntimeError("boom")))

    def test_guarded_client_blocks_stale_attempt_after_provider_returns(self) -> None:
        events: list[str] = []

        class FakeClient:
            def generate_json(self, *args, **kwargs):
                events.append("inner")
                return {"ok": True}

            def generate_text(self, *args, **kwargs):
                events.append("text")
                return "ok"

            def reset_session(self, session_id: str) -> None:
                return

            def request_time_budget_seconds(self) -> int:
                return 10

        allow = {"value": True}

        def guard() -> None:
            if allow["value"]:
                allow["value"] = False
                return
            raise JobRunCancelled("job-1")

        client = GuardedClient(FakeClient(), guard)

        with self.assertRaises(JobRunCancelled):
            client.generate_json("system", "user")
        self.assertEqual(events, ["inner"])

    def test_watchdog_auto_resumes_stalled_job(self) -> None:
        app = self._app(start_watchdog=False, stall_timeout_seconds=5, max_auto_resumes=1)
        try:
            output_dir = Path.cwd() / "runs" / "test-artifacts" / "watchdog-auto-resume"
            now = time.time()
            app.jobs["job-1"] = JobState(
                job_id="job-1",
                title="测试小说",
                output_dir=str(output_dir),
                status="running",
                created_at=now - 20,
                updated_at=now - 10,
                step="world",
                attempt_count=1,
                auto_resume_count=0,
                run_token="token-1",
                input_payload={"title": "测试小说"},
                log=[JobLogEntry(step="world", message="生成设定圣经。", created_at=now - 10)],
            )
            launches: list[tuple[str, dict[str, object], bool, str]] = []
            app._spawn_job_thread = lambda job_id, payload, output_dir, *, resume, run_token: launches.append((job_id, payload, resume, run_token))  # type: ignore[method-assign]

            app._watchdog_tick(now=now)

            snapshot = app.job_snapshot("job-1")
            self.assertEqual(snapshot["status"], "running")
            self.assertEqual(snapshot["step"], "auto_resume")
            self.assertEqual(snapshot["attempt_count"], 2)
            self.assertEqual(snapshot["auto_resume_count"], 1)
            self.assertEqual(len(launches), 1)
            self.assertTrue(launches[0][2])
        finally:
            app.close()

    def test_watchdog_uses_job_specific_stall_timeout(self) -> None:
        app = self._app(start_watchdog=False, stall_timeout_seconds=5, max_auto_resumes=1)
        try:
            output_dir = Path.cwd() / "runs" / "test-artifacts" / "watchdog-budget"
            now = time.time()
            app.jobs["job-1"] = JobState(
                job_id="job-1",
                title="测试小说",
                output_dir=str(output_dir),
                status="running",
                created_at=now - 20,
                updated_at=now - 10,
                step="world",
                attempt_count=1,
                auto_resume_count=0,
                stall_timeout_seconds=600,
                run_token="token-1",
                input_payload={"title": "测试小说"},
                log=[JobLogEntry(step="world", message="生成设定圣经。", created_at=now - 10)],
            )
            launches: list[tuple[str, dict[str, object], bool, str]] = []
            app._spawn_job_thread = lambda job_id, payload, output_dir, *, resume, run_token: launches.append((job_id, payload, resume, run_token))  # type: ignore[method-assign]

            app._watchdog_tick(now=now)

            snapshot = app.job_snapshot("job-1")
            self.assertEqual(snapshot["status"], "running")
            self.assertEqual(snapshot["step"], "world")
            self.assertEqual(len(launches), 0)
        finally:
            app.close()

    def test_watchdog_fails_job_after_retry_budget_is_exhausted(self) -> None:
        app = self._app(start_watchdog=False, stall_timeout_seconds=5, max_auto_resumes=1)
        try:
            output_dir = Path.cwd() / "runs" / "test-artifacts" / "watchdog-fail"
            now = time.time()
            app.jobs["job-1"] = JobState(
                job_id="job-1",
                title="测试小说",
                output_dir=str(output_dir),
                status="running",
                created_at=now - 30,
                updated_at=now - 10,
                step="world",
                attempt_count=2,
                auto_resume_count=1,
                run_token="token-1",
                input_payload={"title": "测试小说"},
                log=[JobLogEntry(step="auto_resume", message="已自动续跑。", created_at=now - 9)],
            )

            app._watchdog_tick(now=now)

            snapshot = app.job_snapshot("job-1")
            self.assertEqual(snapshot["status"], "failed")
            self.assertEqual(snapshot["step"], "failed")
            self.assertIn("超过自动恢复次数", snapshot["message"])
        finally:
            app.close()

    def test_retryable_failure_starts_resume_attempt(self) -> None:
        app = self._app(start_watchdog=False, max_auto_resumes=1)
        try:
            output_dir = Path.cwd() / "runs" / "test-artifacts" / "failure-retry"
            now = time.time()
            app.jobs["job-1"] = JobState(
                job_id="job-1",
                title="测试小说",
                output_dir=str(output_dir),
                status="running",
                created_at=now - 10,
                updated_at=now - 1,
                step="world",
                attempt_count=1,
                auto_resume_count=0,
                run_token="token-1",
                input_payload={"title": "测试小说"},
                log=[JobLogEntry(step="world", message="生成设定圣经。", created_at=now - 1)],
            )
            launches: list[tuple[str, dict[str, object], bool, str]] = []
            app._spawn_job_thread = lambda job_id, payload, output_dir, *, resume, run_token: launches.append((job_id, payload, resume, run_token))  # type: ignore[method-assign]

            handled = app._maybe_auto_resume_after_failure("job-1", "token-1", ModelClientError("HTTP 524 from provider"))

            snapshot = app.job_snapshot("job-1")
            self.assertTrue(handled)
            self.assertEqual(snapshot["status"], "running")
            self.assertEqual(snapshot["step"], "upstream_retry")
            self.assertEqual(snapshot["auto_resume_count"], 0)
            self.assertEqual(snapshot["upstream_retry_count"], 1)
            self.assertEqual(len(launches), 1)
            self.assertTrue(launches[0][2])
        finally:
            app.close()

    def test_remote_disconnect_failure_starts_resume_attempt(self) -> None:
        app = self._app(start_watchdog=False, max_auto_resumes=1)
        try:
            output_dir = Path.cwd() / "runs" / "test-artifacts" / "failure-remote-disconnect"
            now = time.time()
            app.jobs["job-1"] = JobState(
                job_id="job-1",
                title="测试小说",
                output_dir=str(output_dir),
                status="running",
                created_at=now - 10,
                updated_at=now - 1,
                step="chapter_draft",
                attempt_count=1,
                auto_resume_count=0,
                run_token="token-1",
                input_payload={"title": "测试小说"},
                log=[JobLogEntry(step="chapter_draft", message="生成第 1 章正文。", created_at=now - 1)],
            )
            launches: list[tuple[str, dict[str, object], bool, str]] = []
            app._spawn_job_thread = lambda job_id, payload, output_dir, *, resume, run_token: launches.append((job_id, payload, resume, run_token))  # type: ignore[method-assign]

            handled = app._maybe_auto_resume_after_failure("job-1", "token-1", http.client.RemoteDisconnected("Remote end closed connection without response"))

            snapshot = app.job_snapshot("job-1")
            self.assertTrue(handled)
            self.assertEqual(snapshot["status"], "running")
            self.assertEqual(snapshot["step"], "upstream_retry")
            self.assertEqual(snapshot["auto_resume_count"], 0)
            self.assertEqual(snapshot["upstream_retry_count"], 1)
            self.assertEqual(len(launches), 1)
            self.assertTrue(launches[0][2])
        finally:
            app.close()

    def test_stream_read_error_starts_resume_attempt(self) -> None:
        app = self._app(start_watchdog=False, max_auto_resumes=1)
        try:
            output_dir = Path.cwd() / "runs" / "test-artifacts" / "failure-stream-read-error"
            now = time.time()
            app.jobs["job-1"] = JobState(
                job_id="job-1",
                title="测试小说",
                output_dir=str(output_dir),
                status="running",
                created_at=now - 10,
                updated_at=now - 1,
                step="chapter_draft",
                attempt_count=1,
                auto_resume_count=0,
                run_token="token-1",
                input_payload={"title": "测试小说"},
                log=[JobLogEntry(step="chapter_draft", message="生成第 1 章正文。", created_at=now - 1)],
            )
            launches: list[tuple[str, dict[str, object], bool, str]] = []
            app._spawn_job_thread = lambda job_id, payload, output_dir, *, resume, run_token: launches.append((job_id, payload, resume, run_token))  # type: ignore[method-assign]

            handled = app._maybe_auto_resume_after_failure("job-1", "token-1", ModelClientError("stream_read_error"))

            snapshot = app.job_snapshot("job-1")
            self.assertTrue(handled)
            self.assertEqual(snapshot["status"], "running")
            self.assertEqual(snapshot["step"], "upstream_retry")
            self.assertEqual(snapshot["auto_resume_count"], 0)
            self.assertEqual(snapshot["upstream_retry_count"], 1)
            self.assertEqual(len(launches), 1)
            self.assertTrue(launches[0][2])
        finally:
            app.close()

    def test_streaming_response_without_text_starts_resume_attempt(self) -> None:
        app = self._app(start_watchdog=False, max_auto_resumes=1)
        try:
            output_dir = Path.cwd() / "runs" / "test-artifacts" / "failure-stream-no-text"
            now = time.time()
            app.jobs["job-1"] = JobState(
                job_id="job-1",
                title="测试小说",
                output_dir=str(output_dir),
                status="running",
                created_at=now - 10,
                updated_at=now - 1,
                step="continuity",
                attempt_count=1,
                auto_resume_count=0,
                run_token="token-1",
                input_payload={"title": "测试小说"},
                log=[JobLogEntry(step="continuity", message="更新连续性状态。", created_at=now - 1)],
            )
            launches: list[tuple[str, dict[str, object], bool, str]] = []
            app._spawn_job_thread = lambda job_id, payload, output_dir, *, resume, run_token: launches.append((job_id, payload, resume, run_token))  # type: ignore[method-assign]

            handled = app._maybe_auto_resume_after_failure(
                "job-1",
                "token-1",
                ModelClientError("Streaming response completed without text."),
            )

            snapshot = app.job_snapshot("job-1")
            self.assertTrue(handled)
            self.assertEqual(snapshot["status"], "running")
            self.assertEqual(snapshot["step"], "upstream_retry")
            self.assertEqual(snapshot["upstream_retry_count"], 1)
            self.assertEqual(len(launches), 1)
            self.assertTrue(launches[0][2])
        finally:
            app.close()

    def test_upstream_retry_enters_ten_minute_backoff_after_three_attempts(self) -> None:
        app = self._app(start_watchdog=False)
        try:
            output_dir = Path.cwd() / "runs" / "test-artifacts" / "upstream-backoff-10m"
            now = time.time()
            app.jobs["job-1"] = JobState(
                job_id="job-1",
                title="测试小说",
                output_dir=str(output_dir),
                status="running",
                created_at=now - 10,
                updated_at=now - 1,
                step="chapter_draft",
                attempt_count=4,
                upstream_retry_count=3,
                run_token="token-1",
                input_payload={"title": "测试小说"},
                log=[JobLogEntry(step="upstream_retry", message="重试 3/9。", created_at=now - 1)],
            )

            handled = app._maybe_auto_resume_after_failure("job-1", "token-1", ModelClientError("HTTP 503 from provider"))

            snapshot = app.job_snapshot("job-1")
            self.assertTrue(handled)
            self.assertEqual(snapshot["status"], "waiting_retry")
            self.assertEqual(snapshot["step"], "upstream_backoff")
            self.assertEqual(snapshot["upstream_retry_count"], 3)
            self.assertIsNotNone(snapshot["upstream_next_retry_at"])
            self.assertGreaterEqual(snapshot["upstream_next_retry_at"], now + 599)
        finally:
            app.close()

    def test_watchdog_launches_due_upstream_retry_after_backoff(self) -> None:
        app = self._app(start_watchdog=False)
        try:
            output_dir = Path.cwd() / "runs" / "test-artifacts" / "upstream-backoff-due"
            now = time.time()
            app.jobs["job-1"] = JobState(
                job_id="job-1",
                title="测试小说",
                output_dir=str(output_dir),
                status="waiting_retry",
                created_at=now - 20,
                updated_at=now - 10,
                step="upstream_backoff",
                attempt_count=4,
                upstream_retry_count=3,
                upstream_next_retry_at=now - 1,
                upstream_last_error="HTTP 503 from provider",
                run_token="token-1",
                input_payload={"title": "测试小说"},
                log=[JobLogEntry(step="upstream_backoff", message="等待上游恢复。", created_at=now - 10)],
            )
            launches: list[tuple[str, dict[str, object], bool, str]] = []
            app._spawn_job_thread = lambda job_id, payload, output_dir, *, resume, run_token: launches.append((job_id, payload, resume, run_token))  # type: ignore[method-assign]

            app._watchdog_tick(now=now)

            snapshot = app.job_snapshot("job-1")
            self.assertEqual(snapshot["status"], "running")
            self.assertEqual(snapshot["step"], "upstream_retry")
            self.assertEqual(snapshot["upstream_retry_count"], 4)
            self.assertEqual(len(launches), 1)
        finally:
            app.close()

    def test_upstream_retry_pauses_job_after_three_three_three_plan_is_exhausted(self) -> None:
        app = self._app(start_watchdog=False)
        try:
            output_dir = Path.cwd() / "runs" / "test-artifacts" / "upstream-backoff-exhausted"
            now = time.time()
            app.jobs["job-1"] = JobState(
                job_id="job-1",
                title="测试小说",
                output_dir=str(output_dir),
                status="running",
                created_at=now - 10,
                updated_at=now - 1,
                step="chapter_draft",
                attempt_count=10,
                upstream_retry_count=9,
                run_token="token-1",
                input_payload={"title": "测试小说"},
                log=[JobLogEntry(step="upstream_retry", message="重试 9/9。", created_at=now - 1)],
            )

            handled = app._maybe_auto_resume_after_failure("job-1", "token-1", ModelClientError("HTTP 503 from provider"))

            snapshot = app.job_snapshot("job-1")
            self.assertTrue(handled)
            self.assertEqual(snapshot["status"], "paused")
            self.assertEqual(snapshot["step"], "paused")
            self.assertIn("3+3+3", snapshot["message"])
        finally:
            app.close()

    def test_progress_update_clears_upstream_retry_streak(self) -> None:
        app = self._app(start_watchdog=False)
        try:
            output_dir = Path.cwd() / "runs" / "test-artifacts" / "upstream-progress-reset"
            now = time.time()
            app.jobs["job-1"] = JobState(
                job_id="job-1",
                title="测试小说",
                output_dir=str(output_dir),
                status="running",
                created_at=now - 10,
                updated_at=now - 1,
                step="upstream_retry",
                attempt_count=3,
                upstream_retry_count=2,
                upstream_next_retry_at=now + 60,
                upstream_last_error="HTTP 503 from provider",
                run_token="token-1",
                input_payload={"title": "测试小说"},
                log=[JobLogEntry(step="upstream_retry", message="重试 2/9。", created_at=now - 1)],
            )

            app._update_job("job-1", status="running", step="chapter_plan", message="生成第 1 章计划。", run_token="token-1")

            snapshot = app.job_snapshot("job-1")
            self.assertEqual(snapshot["upstream_retry_count"], 0)
            self.assertIsNone(snapshot["upstream_next_retry_at"])
            self.assertIsNone(snapshot["upstream_last_error"])
        finally:
            app.close()

    def test_run_job_preserves_style_and_voice_controls_when_resuming_from_upstream_retry(self) -> None:
        app = self._app(start_watchdog=False)
        try:
            output_dir = self.root / "runs" / "preserve-controls"
            output_dir.mkdir(parents=True, exist_ok=True)
            now = time.time()
            app.jobs["job-1"] = JobState(
                job_id="job-1",
                title="测试小说",
                output_dir=str(output_dir),
                status="running",
                created_at=now - 10,
                updated_at=now - 1,
                step="upstream_retry",
                attempt_count=2,
                upstream_retry_count=1,
                run_token="token-1",
                input_payload={"title": "测试小说"},
                log=[JobLogEntry(step="upstream_retry", message="重试 1/9。", created_at=now - 1)],
            )
            fake_provider = ProviderConfig(
                base_url="https://relay.example.com/v1",
                wire_api="responses",
                api_key="secret",
                model="gpt-flagship",
                review_model="gpt-flagship",
                light_model="gpt-light",
            )
            constructed: list[dict[str, object]] = []

            class FakeBaseClient:
                def __init__(self, provider) -> None:
                    self.provider = provider

                def request_time_budget_seconds(self) -> int:
                    return 10

                def generate_json(self, *args, **kwargs):
                    raise AssertionError("Guarded client should not reach generate_json in this test.")

                def generate_text(self, *args, **kwargs):
                    raise AssertionError("Guarded client should not reach generate_text in this test.")

                def reset_session(self, session_id: str) -> None:
                    return

                def set_routing_namespace(self, namespace: str | None) -> None:
                    return

            class FakePipeline:
                def __init__(self, *args, **kwargs) -> None:
                    constructed.append(kwargs)

                def run(self, project_input):
                    return GenerationSummary(
                        output_dir=str(output_dir),
                        title="测试小说",
                        chapter_count=1,
                        volume_count=1,
                        total_chars=2000,
                        final_score=90,
                        final_passed=True,
                        final_summary="完成。",
                    )

            with (
                patch.object(app, "_provider_for_job", return_value=fake_provider),
                patch("sagaquill.server.OpenAICompatibleClient", FakeBaseClient),
                patch("sagaquill.server.NovelPipeline", FakePipeline),
            ):
                app._run_job("job-1", {"title": "测试小说"}, output_dir, resume=True, run_token="token-1")

            self.assertEqual(len(constructed), 1)
            self.assertTrue(constructed[0]["resume"])
            self.assertTrue(constructed[0]["preserve_resume_controls"])
        finally:
            app.close()

    def test_failed_to_read_request_body_is_retryable(self) -> None:
        app = self._app(start_watchdog=False)
        try:
            self.assertTrue(app._is_retryable_exception(ModelClientError("Failed to read request body")))
            self.assertTrue(app._is_retryable_exception(ModelClientError("invalid_request_error")))
            self.assertTrue(app._is_retryable_exception(ModelClientError("HTTP 429: Too Many Requests")))
            self.assertTrue(
                app._is_retryable_exception(
                    ModelClientError("Concurrency limit exceeded for user, please retry later")
                )
            )
            self.assertTrue(
                app._is_retryable_exception(
                    ModelClientError("Concurrency limit exceeded for account, please retry later")
                )
            )
            self.assertTrue(
                app._is_retryable_exception(
                    ModelClientError(
                        "An error occurred while processing your request. You can retry your request."
                    )
                )
            )
            self.assertTrue(
                app._is_retryable_exception(
                    ModelClientError("stream error: stream ID 207; INTERNAL_ERROR; received from peer")
                )
            )
            self.assertTrue(
                app._is_retryable_exception(
                    ModelClientError("HTTP 502: error code: 502")
                )
            )
            self.assertTrue(
                app._is_retryable_exception(
                    ModelClientError("provider relay temporary failure while handling request")
                )
            )
            self.assertFalse(app._is_retryable_exception(ModelClientError("HTTP 401 Unauthorized")))
            self.assertFalse(app._is_retryable_exception(ModelClientError("HTTP 403 Forbidden")))
            self.assertFalse(app._is_retryable_exception(ModelClientError("permission denied")))
            self.assertFalse(app._is_retryable_exception(ModelClientError("billing hard limit reached")))
            self.assertFalse(app._is_retryable_exception(ModelClientError("Unsupported parameter: reasoning_effort")))
            self.assertFalse(app._is_retryable_exception(ModelClientError("model not found")))
            self.assertFalse(app._is_retryable_exception(ModelClientError("insufficient_quota")))
        finally:
            app.close()

    def test_close_marks_running_jobs_paused_and_persists_pause_snapshot(self) -> None:
        app = self._app(start_watchdog=False)
        output_dir = self.root / "runs" / "close-pause"
        output_dir.mkdir(parents=True, exist_ok=True)
        now = time.time()
        app.jobs["job-1"] = JobState(
            job_id="job-1",
            title="测试小说",
            output_dir=str(output_dir),
            status="running",
            created_at=now - 10,
            updated_at=now - 1,
            step="chapter_room",
            run_token="token-1",
            input_payload={"title": "测试小说"},
            log=[JobLogEntry(step="chapter_room", message="召开写前会。", created_at=now - 1)],
        )

        app.close()

        snapshot = app.job_snapshot("job-1")
        self.assertEqual(snapshot["status"], "paused")
        self.assertEqual(snapshot["step"], "paused")
        self.assertIn("服务关闭时已安全暂停", snapshot["message"])
        pause_state = json.loads((output_dir / "data" / "pause-state.json").read_text(encoding="utf-8"))
        self.assertEqual(pause_state["reason"], "service_close")

    def test_recover_job_state_prefers_pause_snapshot(self) -> None:
        job_id = uuid.uuid4().hex[:8]
        output_dir = self.root / "runs" / f"暂停恢复测试-20260327-000000-{job_id}"
        data_dir = output_dir / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        try:
            (data_dir / "project-input.json").write_text(
                json.dumps({"title": "暂停恢复测试"}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            (data_dir / "progress.json").write_text(
                json.dumps({"step": "chapter_room", "message": "召开第 10 章写前会。"}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            (data_dir / "pause-state.json").write_text(
                json.dumps(
                    {
                        "reason": "service_close",
                        "step": "chapter_room",
                        "message": "服务关闭时已安全暂停，原步骤 chapter_room。 重启后需手动恢复运行。",
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            app = self._app(start_watchdog=False)
            try:
                snapshot = app.job_snapshot(job_id)
                self.assertEqual(snapshot["status"], "paused")
                self.assertEqual(snapshot["step"], "paused")
                self.assertIn("安全暂停", snapshot["message"])
            finally:
                app.close()
        finally:
            shutil.rmtree(output_dir, ignore_errors=True)

    def test_recover_job_state_uses_latest_failed_chapter_snapshot(self) -> None:
        job_id = uuid.uuid4().hex[:8]
        output_dir = self.root / "runs" / f"失败快照测试-20260327-000000-{job_id}"
        data_dir = output_dir / "data"
        state_dir = output_dir / "state"
        data_dir.mkdir(parents=True, exist_ok=True)
        state_dir.mkdir(parents=True, exist_ok=True)
        try:
            (data_dir / "project-input.json").write_text(
                json.dumps({"title": "失败快照测试"}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            (state_dir / "chapter-85.failed.review.json").write_text(
                json.dumps(
                    {
                        "model": {
                            "short_summary": "第85章审校未通过，需继续回修。",
                            "issues": ["群像压迫感不足。"],
                        },
                        "local": {"short_summary": "本地门未通过。"},
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            app = self._app(start_watchdog=False)
            try:
                snapshot = app.job_snapshot(job_id)
                self.assertEqual(snapshot["status"], "failed")
                self.assertEqual(snapshot["step"], "failed")
                self.assertIn("第85章审校未通过", snapshot["message"])
            finally:
                app.close()
        finally:
            shutil.rmtree(output_dir, ignore_errors=True)

    def test_close_pauses_running_batch_and_keeps_queued_items_queued(self) -> None:
        app = self._app(start_watchdog=False)
        try:
            batch_id = "batch-test"
            now = time.time()
            app.batches[batch_id] = BatchRecord(
                batch_id=batch_id,
                name="批次",
                source_name="ideas.csv",
                created_at=now - 20,
                updated_at=now - 10,
                status="running",
                max_concurrent=2,
                paused=False,
                provider_snapshot={},
            )
            app.batch_proposals[batch_id] = [
                ProposalRecord(proposal_id="proposal-1", row_index=1, source_batch_id=batch_id, title="甲", status="running"),
                ProposalRecord(proposal_id="proposal-2", row_index=2, source_batch_id=batch_id, title="乙", status="queued"),
            ]
            app.batch_items[batch_id] = [
                BatchItemState(batch_id=batch_id, proposal_id="proposal-1", title="甲", status="running", selected=True, created_at=now - 20, updated_at=now - 5),
                BatchItemState(batch_id=batch_id, proposal_id="proposal-2", title="乙", status="queued", selected=True, created_at=now - 20, updated_at=now - 5),
            ]

            app.close()

            self.assertTrue(app.batches[batch_id].paused)
            self.assertEqual(app.batches[batch_id].status, "paused")
            self.assertEqual(app.batch_items[batch_id][0].status, "paused")
            self.assertEqual(app.batch_items[batch_id][0].pause_reason, "service_close")
            self.assertEqual(app.batch_items[batch_id][1].status, "queued")
        finally:
            app.close()

    def test_resume_rejects_running_job(self) -> None:
        app = self._app(start_watchdog=False)
        try:
            output_dir = Path.cwd() / "runs" / "test-artifacts" / "resume-running"
            now = time.time()
            app.jobs["job-1"] = JobState(
                job_id="job-1",
                title="测试小说",
                output_dir=str(output_dir),
                status="running",
                created_at=now - 10,
                updated_at=now - 1,
                step="world",
                attempt_count=1,
                auto_resume_count=0,
                stall_timeout_seconds=600,
                run_token="token-1",
                input_payload={"title": "测试小说"},
                log=[JobLogEntry(step="world", message="生成设定圣经。", created_at=now - 1)],
            )

            with self.assertRaisesRegex(ValueError, "Running jobs do not need resume"):
                app.resume_job("job-1")
        finally:
            app.close()

    def test_resume_job_applies_current_provider_override(self) -> None:
        app = self._app(start_watchdog=False)
        try:
            output_dir = self.root / "runs" / "resume-provider"
            (output_dir / "data").mkdir(parents=True, exist_ok=True)
            now = time.time()
            app.jobs["job-1"] = JobState(
                job_id="job-1",
                title="测试小说",
                output_dir=str(output_dir),
                status="paused",
                created_at=now - 10,
                updated_at=now - 1,
                step="paused",
                attempt_count=1,
                auto_resume_count=0,
                run_token="token-1",
                input_payload={"title": "测试小说"},
                provider_override={"base_url": "https://old.example.com", "api_key": "old-secret", "model": "old-model"},
                log=[JobLogEntry(step="paused", message="已暂停", created_at=now - 1)],
            )
            launches: list[tuple[str, bool, str]] = []
            app._launch_job = lambda job_id, *, resume, step, message, auto=False, upstream_retry=False, expected_run_token=None: launches.append((job_id, resume, step))  # type: ignore[method-assign]

            with patch(
                "sagaquill.server.resolve_provider_config",
                return_value=ProviderConfig(
                    base_url="https://relay.example.com",
                    wire_api="responses",
                    api_key="new-secret",
                    model="gpt-new",
                    review_model="gpt-new",
                    light_model="gpt-light",
                    continuation_mode="hybrid",
                ),
            ):
                app.resume_job("job-1", {"provider": {"base_url": "https://relay.example.com", "api_key": "new-secret", "model": "gpt-new"}})

            self.assertEqual(launches, [("job-1", True, "resume")])
            self.assertEqual(app.jobs["job-1"].provider_override["api_key"], "new-secret")
            self.assertEqual(app.jobs["job-1"].provider_override["model"], "gpt-new")
            snapshot = json.loads((output_dir / "data" / "provider.snapshot.json").read_text(encoding="utf-8"))
            self.assertEqual(snapshot["base_url"], "https://relay.example.com")
            self.assertEqual(snapshot["model"], "gpt-new")
            self.assertNotIn("api_key", snapshot)
        finally:
            app.close()

    def test_resume_job_clears_legacy_pending_upper_decision_before_launch(self) -> None:
        app = self._app(start_watchdog=False)
        try:
            output_dir = self.root / "runs" / "resume-upper-review"
            data_dir = output_dir / "data"
            data_dir.mkdir(parents=True, exist_ok=True)
            pending = {
                "chapter_index": 32,
                "signal_level": "escalation",
                "decision": "phase_repair",
                "confidence": 86,
                "reason": "最近章节簇被上层判定为阶段级空转风险。",
                "scope_start_chapter": 24,
                "scope_end_chapter": 32,
                "next_chapter_constraints": ["后续必须产生新的不可逆后果。"],
                "repair_goal": "建议阶段级回修。",
            }
            (data_dir / "pending-upper-decision.json").write_text(json.dumps(pending, ensure_ascii=False, indent=2), encoding="utf-8")
            now = time.time()
            app.jobs["job-1"] = JobState(
                job_id="job-1",
                title="测试小说",
                output_dir=str(output_dir),
                status="paused",
                created_at=now - 10,
                updated_at=now - 1,
                step="upper_review",
                run_token="token-1",
                input_payload={"title": "测试小说"},
                pending_upper_decision=dict(pending),
                log=[JobLogEntry(step="upper_review", message="等待上层处理。", created_at=now - 1)],
            )
            launches: list[tuple[str, bool, str]] = []
            app._launch_job = lambda job_id, *, resume, step, message, auto=False, upstream_retry=False, expected_run_token=None: launches.append((job_id, resume, step))  # type: ignore[method-assign]

            app.resume_job("job-1")

            snapshot = app.job_snapshot("job-1")
            self.assertEqual(launches, [("job-1", True, "resume")])
            self.assertNotIn("pending_upper_decision", snapshot)
            self.assertFalse((data_dir / "pending-upper-decision.json").exists())
        finally:
            app.close()

    def test_pause_marks_job_as_paused_and_resume_keeps_outputs(self) -> None:
        app = self._app(start_watchdog=False)
        try:
            output_dir = Path.cwd() / "runs" / "test-artifacts" / "pause-job"
            now = time.time()
            app.jobs["job-1"] = JobState(
                job_id="job-1",
                title="测试小说",
                output_dir=str(output_dir),
                status="running",
                created_at=now - 10,
                updated_at=now - 1,
                step="chapter_draft",
                attempt_count=1,
                auto_resume_count=0,
                run_token="token-1",
                input_payload={"title": "测试小说"},
                log=[JobLogEntry(step="chapter_draft", message="生成第 1 章正文。", created_at=now - 1)],
            )

            snapshot = app.pause_job("job-1")

            self.assertEqual(snapshot["status"], "paused")
            self.assertEqual(snapshot["step"], "paused")
            self.assertIn("已暂停任务", snapshot["message"])
        finally:
            app.close()

    def test_open_output_dir_uses_file_manager(self) -> None:
        app = self._app(start_watchdog=False)
        output_dir = Path.cwd() / "runs" / "test-artifacts" / f"open-output-dir-{uuid.uuid4().hex[:8]}"
        output_dir.mkdir(parents=True, exist_ok=True)
        try:
            now = time.time()
            app.jobs["job-1"] = JobState(
                job_id="job-1",
                title="测试小说",
                output_dir=str(output_dir),
                status="paused",
                created_at=now - 10,
                updated_at=now - 1,
                step="paused",
                run_token="token-1",
                input_payload={"title": "测试小说"},
            )
            opened: list[str] = []
            app._open_path_in_file_manager = lambda path: opened.append(str(path))  # type: ignore[method-assign]

            snapshot = app.open_output_dir("job-1")

            self.assertTrue(snapshot["opened"])
            self.assertEqual(opened, [str(output_dir)])
        finally:
            app.close()
            shutil.rmtree(output_dir, ignore_errors=True)

    def test_delivery_cleanup_removes_failed_snapshots_for_completed_job(self) -> None:
        app = self._app(start_watchdog=False)
        output_dir = Path.cwd() / "runs" / "test-artifacts" / f"delivery-cleanup-{uuid.uuid4().hex[:8]}"
        state_dir = output_dir / "state"
        data_dir = output_dir / "data"
        state_dir.mkdir(parents=True, exist_ok=True)
        data_dir.mkdir(parents=True, exist_ok=True)
        try:
            (output_dir / "novel.md").write_text("正式正文", encoding="utf-8")
            (state_dir / "chapter-499.failed.md").write_text("失败快照", encoding="utf-8")
            (state_dir / "chapter-499.failed.review.json").write_text("{}", encoding="utf-8")
            now = time.time()
            app.jobs["job-1"] = JobState(
                job_id="job-1",
                title="测试小说",
                output_dir=str(output_dir),
                status="completed",
                created_at=now - 10,
                updated_at=now - 1,
                step="completed",
                summary={"final_summary": "完成。"},
                run_token="token-1",
                input_payload={"title": "测试小说"},
                log=[JobLogEntry(step="completed", message="任务已完成。", created_at=now - 1)],
            )

            result = app.delivery_cleanup("job-1")

            self.assertTrue(result["cleaned"])
            self.assertEqual(result["report"]["removed_count"], 2)
            self.assertFalse((state_dir / "chapter-499.failed.md").exists())
            self.assertFalse((state_dir / "chapter-499.failed.review.json").exists())
            self.assertTrue((output_dir / "novel.md").exists())
            self.assertTrue((data_dir / "delivery-cleanup.json").exists())
        finally:
            app.close()
            shutil.rmtree(output_dir, ignore_errors=True)

    def test_delete_rejects_running_job(self) -> None:
        app = self._app(start_watchdog=False)
        try:
            output_dir = Path.cwd() / "runs" / "test-artifacts" / "delete-running"
            now = time.time()
            app.jobs["job-1"] = JobState(
                job_id="job-1",
                title="测试小说",
                output_dir=str(output_dir),
                status="running",
                created_at=now - 10,
                updated_at=now - 1,
                step="world",
                run_token="token-1",
                input_payload={"title": "测试小说"},
            )

            with self.assertRaisesRegex(ValueError, "Pause the job before deleting it"):
                app.delete_job("job-1", confirm_title="测试小说", confirm_job_id="job-1")
        finally:
            app.close()

    def test_delete_requires_confirmation_and_removes_project_directory(self) -> None:
        app = self._app(start_watchdog=False)
        output_dir = Path.cwd() / "runs" / "test-artifacts" / f"delete-job-{uuid.uuid4().hex[:8]}"
        data_dir = output_dir / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        try:
            (data_dir / "project-input.json").write_text(
                json.dumps({"title": "测试小说"}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            now = time.time()
            app.jobs["job-1"] = JobState(
                job_id="job-1",
                title="测试小说",
                output_dir=str(output_dir),
                status="paused",
                created_at=now - 10,
                updated_at=now - 1,
                step="paused",
                run_token="token-1",
                input_payload={"title": "测试小说"},
            )

            with self.assertRaisesRegex(ValueError, "Delete confirmation did not match"):
                app.delete_job("job-1", confirm_title="别的标题", confirm_job_id="job-1")

            deleted = app.delete_job("job-1", confirm_title="测试小说", confirm_job_id="job-1")

            self.assertTrue(deleted["deleted"])
            self.assertFalse(output_dir.exists())
            self.assertNotIn("job-1", app.jobs)
        finally:
            app.close()
            shutil.rmtree(output_dir, ignore_errors=True)

    def test_delete_rejects_paused_job_while_old_attempt_is_still_alive(self) -> None:
        app = self._app(start_watchdog=False)
        output_dir = Path.cwd() / "runs" / "test-artifacts" / f"delete-live-thread-{uuid.uuid4().hex[:8]}"
        output_dir.mkdir(parents=True, exist_ok=True)
        sleeper = threading.Event()
        try:
            now = time.time()
            app.jobs["job-1"] = JobState(
                job_id="job-1",
                title="测试小说",
                output_dir=str(output_dir),
                status="paused",
                created_at=now - 10,
                updated_at=now - 1,
                step="paused",
                run_token="token-1",
                input_payload={"title": "测试小说"},
            )
            live_thread = threading.Thread(target=lambda: sleeper.wait(1.5), daemon=True)
            with app.lock:
                app._active_threads["job-1"] = {"token-1": live_thread}
            live_thread.start()

            with self.assertRaisesRegex(ValueError, "still draining"):
                app.delete_job("job-1", confirm_title="测试小说", confirm_job_id="job-1")
        finally:
            sleeper.set()
            app.close()
            shutil.rmtree(output_dir, ignore_errors=True)

    def test_hide_persists_across_reload_and_is_omitted_by_default(self) -> None:
        output_dir = self.root / "runs" / f"隐藏测试-20260322-000000-{uuid.uuid4().hex[:8]}"
        data_dir = output_dir / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        try:
            (data_dir / "project-input.json").write_text(
                json.dumps({"title": "隐藏测试"}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            (data_dir / "progress.json").write_text(
                json.dumps({"step": "world", "message": "生成设定圣经。"}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            app = self._app(start_watchdog=False)
            try:
                hidden = app.hide_job(output_dir.name.rsplit("-", 1)[-1])
                self.assertTrue(hidden["hidden"])
            finally:
                app.close()

            reloaded = self._app(start_watchdog=False)
            try:
                job_id = output_dir.name.rsplit("-", 1)[-1]
                listed = reloaded.list_jobs()
                self.assertNotIn(job_id, {item["job_id"] for item in listed["jobs"]})
                with_hidden = reloaded.list_jobs(include_hidden=True)
                target = next(item for item in with_hidden["jobs"] if item["job_id"] == job_id)
                self.assertGreaterEqual(with_hidden["hidden_count"], 1)
                self.assertTrue(target["hidden"])
            finally:
                reloaded.close()
        finally:
            shutil.rmtree(output_dir, ignore_errors=True)

    def test_list_jobs_filters_single_and_batch_items(self) -> None:
        app = self._app(start_watchdog=False)
        try:
            now = time.time()
            single_dir = self.root / "runs" / "single-job"
            batch_dir = self.root / "runs" / "batch-job"
            single_dir.mkdir(parents=True, exist_ok=True)
            batch_dir.mkdir(parents=True, exist_ok=True)
            app.jobs["single-1"] = JobState(
                job_id="single-1",
                title="单独任务",
                output_dir=str(single_dir),
                status="paused",
                created_at=now - 20,
                updated_at=now - 10,
                step="paused",
                input_payload={"title": "单独任务"},
            )
            app.jobs["batch-1"] = JobState(
                job_id="batch-1",
                title="批量任务",
                output_dir=str(batch_dir),
                status="running",
                created_at=now - 5,
                updated_at=now - 1,
                step="chapter_plan",
                input_payload={"title": "批量任务"},
            )
            batch_id = "batch-test"
            app.batches[batch_id] = BatchRecord(
                batch_id=batch_id,
                name="测试批次",
                source_name="ideas.csv",
                created_at=now - 30,
                updated_at=now - 1,
                status="running",
                max_concurrent=1,
                paused=False,
                provider_snapshot={},
                config=BatchConfig(),
            )
            app.batch_items[batch_id] = [
                BatchItemState(
                    batch_id=batch_id,
                    proposal_id="proposal-1",
                    title="批量任务",
                    status="running",
                    selected=True,
                    job_id="batch-1",
                    output_dir=str(batch_dir),
                    created_at=now - 30,
                    updated_at=now - 1,
                )
            ]

            single_jobs = app.list_jobs(job_kind="single")
            batch_jobs = app.list_jobs(job_kind="batch")

            self.assertEqual([item["job_id"] for item in single_jobs["jobs"]], ["single-1"])
            self.assertEqual([item["job_id"] for item in batch_jobs["jobs"]], ["batch-1"])
            self.assertEqual(batch_jobs["jobs"][0]["job_kind"], "batch")
            self.assertNotIn("log", single_jobs["jobs"][0])
            self.assertNotIn("log", batch_jobs["jobs"][0])
        finally:
            app.close()

    def test_hide_batch_persists_across_reload_and_is_omitted_by_default(self) -> None:
        batch_id = "batch-hidden"
        app = self._app(start_watchdog=False)
        try:
            now = time.time()
            app.batches[batch_id] = BatchRecord(
                batch_id=batch_id,
                name="隐藏批次",
                source_name="ideas.csv",
                created_at=now - 30,
                updated_at=now - 1,
                status="draft",
                max_concurrent=2,
                paused=False,
                hidden=False,
                provider_snapshot={},
                config=BatchConfig(),
            )
            app.batch_proposals[batch_id] = []
            app.batch_items[batch_id] = []
            app._persist_batch_locked(batch_id)

            hidden = app.hide_batch(batch_id)

            self.assertTrue(hidden["hidden"])
            listed = app.list_batches()
            self.assertEqual(listed["batches"], [])
            self.assertEqual(listed["hidden_count"], 1)
        finally:
            app.close()

        reloaded = self._app(start_watchdog=False)
        try:
            listed = reloaded.list_batches()
            self.assertEqual(listed["batches"], [])
            self.assertEqual(listed["hidden_count"], 1)
            with_hidden = reloaded.list_batches(include_hidden=True)
            self.assertEqual(len(with_hidden["batches"]), 1)
            self.assertTrue(with_hidden["batches"][0]["hidden"])

            unhidden = reloaded.unhide_batch(batch_id)

            self.assertFalse(unhidden["hidden"])
            listed_after = reloaded.list_batches()
            self.assertEqual(len(listed_after["batches"]), 1)
            self.assertEqual(listed_after["hidden_count"], 0)
        finally:
            reloaded.close()

    def test_list_batches_returns_lightweight_summary_without_items(self) -> None:
        app = self._app(start_watchdog=False)
        try:
            batch_id = "batch-list"
            now = time.time()
            app.batches[batch_id] = BatchRecord(
                batch_id=batch_id,
                name="测试批次",
                source_name="ideas.csv",
                created_at=now - 30,
                updated_at=now - 1,
                status="running",
                max_concurrent=3,
                paused=False,
                hidden=False,
                provider_snapshot={"model": "gpt-5.4", "light_model": "gpt-5.4", "continuation_mode": "hybrid"},
                config=BatchConfig(target_total_chars=2000000),
            )
            app.batch_proposals[batch_id] = [
                ProposalRecord(
                    proposal_id="proposal-1",
                    row_index=1,
                    source_batch_id=batch_id,
                    title="测试小说",
                    status="queued",
                )
            ]
            app.batch_items[batch_id] = [
                BatchItemState(
                    batch_id=batch_id,
                    proposal_id="proposal-1",
                    title="测试小说",
                    status="queued",
                    selected=True,
                    priority=1,
                    created_at=now - 20,
                    updated_at=now - 10,
                )
            ]

            listed = app.list_batches()

            self.assertEqual(len(listed["batches"]), 1)
            item = listed["batches"][0]
            self.assertEqual(item["name"], "测试批次")
            self.assertEqual(item["counts"]["queued"], 1)
            self.assertNotIn("items", item)
            self.assertNotIn("proposals", item)
        finally:
            app.close()

    def test_open_batch_dir_uses_file_manager(self) -> None:
        app = self._app(start_watchdog=False)
        try:
            now = time.time()
            batch_id = "batch-open"
            batch = BatchRecord(
                batch_id=batch_id,
                name="打开批次",
                source_name="ideas.csv",
                created_at=now - 30,
                updated_at=now - 1,
                status="paused",
                max_concurrent=2,
                paused=True,
                hidden=False,
                provider_snapshot={},
                config=BatchConfig(),
            )
            app.batches[batch_id] = batch
            app.batch_proposals[batch_id] = []
            app.batch_items[batch_id] = []
            batch_root = app._batch_run_root(batch)
            batch_root.mkdir(parents=True, exist_ok=True)
            opened: list[str] = []
            app._open_path_in_file_manager = lambda path: opened.append(str(path))  # type: ignore[method-assign]

            snapshot = app.open_batch_dir(batch_id)

            self.assertTrue(snapshot["opened"])
            self.assertEqual(snapshot["batch_root"], str(batch_root))
            self.assertEqual(opened, [str(batch_root)])
        finally:
            app.close()
            shutil.rmtree(self.root / "runs", ignore_errors=True)

    def test_list_jobs_treats_orphaned_run_under_batch_root_as_batch(self) -> None:
        app = self._app(start_watchdog=False)
        try:
            now = time.time()
            orphan_dir = self.root / "runs" / "batches" / "demo-batch-abc123" / "projects" / "orphan-job"
            orphan_dir.mkdir(parents=True, exist_ok=True)
            app.jobs["orphan-1"] = JobState(
                job_id="orphan-1",
                title="批量孤儿任务",
                output_dir=str(orphan_dir),
                status="paused",
                created_at=now - 20,
                updated_at=now - 10,
                step="paused",
                input_payload={"title": "批量孤儿任务"},
            )

            single_jobs = app.list_jobs(job_kind="single")
            batch_jobs = app.list_jobs(job_kind="batch")

            self.assertEqual([item["job_id"] for item in single_jobs["jobs"]], [])
            self.assertEqual([item["job_id"] for item in batch_jobs["jobs"]], ["orphan-1"])
            self.assertEqual(batch_jobs["jobs"][0]["job_kind"], "batch")
        finally:
            app.close()

    def test_sync_batch_items_prefers_recovered_run_state_over_stale_failed_item(self) -> None:
        app = self._app(start_watchdog=False)
        batch_id = "batch-test"
        output_dir = self.root / "runs" / f"恢复批次-20260324-000000-{uuid.uuid4().hex[:8]}"
        data_dir = output_dir / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        try:
            now = time.time()
            (data_dir / "project-input.json").write_text(
                json.dumps({"title": "恢复批次测试"}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            (data_dir / "run-summary.json").write_text(
                json.dumps({"final_summary": "已完成。", "final_passed": True}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            app.batches[batch_id] = BatchRecord(
                batch_id=batch_id,
                name="测试批次",
                source_name="ideas.csv",
                created_at=now - 60,
                updated_at=now - 30,
                status="failed",
                max_concurrent=1,
                paused=False,
                provider_snapshot={},
                config=BatchConfig(),
            )
            app.batch_proposals[batch_id] = [
                ProposalRecord(
                    proposal_id="proposal-1",
                    source_batch_id=batch_id,
                    row_index=1,
                    title="恢复批次测试",
                    status="failed",
                )
            ]
            app.batch_items[batch_id] = [
                BatchItemState(
                    batch_id=batch_id,
                    proposal_id="proposal-1",
                    title="恢复批次测试",
                    status="failed",
                    selected=True,
                    job_id=output_dir.name.rsplit("-", 1)[-1],
                    output_dir=str(output_dir),
                    last_error="旧错误",
                    created_at=now - 60,
                    updated_at=now - 40,
                )
            ]

            app._sync_batch_items_locked(batch_id)

            item = app.batch_items[batch_id][0]
            proposal = app.batch_proposals[batch_id][0]
            self.assertEqual(item.status, "completed")
            self.assertIsNone(item.last_error)
            self.assertEqual(proposal.status, "completed")
            self.assertEqual(app.batches[batch_id].status, "completed")
        finally:
            app.close()

    def test_sync_batch_items_does_not_drift_updated_at_to_now(self) -> None:
        app = self._app(start_watchdog=False)
        try:
            batch_id = "batch-test"
            original_updated = 120.0
            app.batches[batch_id] = BatchRecord(
                batch_id=batch_id,
                name="批次",
                source_name="ideas.csv",
                created_at=100.0,
                updated_at=original_updated,
                status="running",
                max_concurrent=2,
                provider_snapshot={},
            )
            app.batch_proposals[batch_id] = [
                ProposalRecord(
                    proposal_id="proposal-1",
                    row_index=1,
                    source_batch_id=batch_id,
                    title="测试小说",
                    status="running",
                )
            ]
            app.jobs["job-1"] = JobState(
                job_id="job-1",
                title="测试小说",
                output_dir=str(self.root / "runs" / "job-1"),
                status="running",
                created_at=90.0,
                updated_at=110.0,
                step="chapter_plan",
            )
            app.batch_items[batch_id] = [
                BatchItemState(
                    batch_id=batch_id,
                    proposal_id="proposal-1",
                    title="测试小说",
                    status="running",
                    selected=True,
                    job_id="job-1",
                    created_at=100.0,
                    updated_at=original_updated,
                )
            ]

            with patch("time.time", return_value=9999.0):
                app._sync_batch_items_locked(batch_id)

            self.assertEqual(app.batch_items[batch_id][0].updated_at, original_updated)
            self.assertEqual(app.batches[batch_id].updated_at, original_updated)
        finally:
            app.close()

    def test_batch_written_chars_prefers_committed_progress_over_orphaned_chapters(self) -> None:
        app = self._app(start_watchdog=False)
        try:
            output_dir = self.root / "runs" / "job-with-orphans"
            (output_dir / "data").mkdir(parents=True, exist_ok=True)
            (output_dir / "chapters").mkdir(parents=True, exist_ok=True)
            (output_dir / "chapters" / "chapter-02.md").write_text("第二章正文", encoding="utf-8")
            (output_dir / "chapters" / "chapter-03.md").write_text("第三章正文", encoding="utf-8")
            (output_dir / "data" / "continuity-state.json").write_text(
                json.dumps({"last_chapter_index": 0}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            total = app._batch_written_chars(output_dir)

            self.assertEqual(total, 0)
            self.assertTrue((output_dir / "state" / "orphaned-chapters" / "chapter-02.md").exists())
            self.assertTrue((output_dir / "state" / "orphaned-chapters" / "chapter-03.md").exists())
            committed = json.loads((output_dir / "data" / "committed-progress.json").read_text(encoding="utf-8"))
            self.assertEqual(committed["last_committed_chapter_index"], 0)
            self.assertEqual(committed["total_committed_chars"], 0)
        finally:
            app.close()

    def test_sync_batch_items_keeps_fresh_launching_item_without_job_id(self) -> None:
        app = self._app(start_watchdog=False)
        try:
            batch_id = "batch-test"
            app.batches[batch_id] = BatchRecord(
                batch_id=batch_id,
                name="批次",
                source_name="ideas.csv",
                created_at=900.0,
                updated_at=990.0,
                status="running",
                max_concurrent=1,
                provider_snapshot={},
            )
            app.batch_proposals[batch_id] = [
                ProposalRecord(
                    proposal_id="proposal-1",
                    row_index=1,
                    source_batch_id=batch_id,
                    title="测试小说",
                    status="launching",
                )
            ]
            app.batch_items[batch_id] = [
                BatchItemState(
                    batch_id=batch_id,
                    proposal_id="proposal-1",
                    title="测试小说",
                    status="launching",
                    selected=True,
                    priority=1,
                    created_at=900.0,
                    updated_at=995.0,
                )
            ]

            with patch("time.time", return_value=1000.0):
                app._sync_batch_items_locked(batch_id)

            self.assertEqual(app.batch_items[batch_id][0].status, "launching")
            self.assertEqual(app.batch_proposals[batch_id][0].status, "launching")
        finally:
            app.close()

    def test_sync_batch_items_requeues_stale_launching_item_without_job_id(self) -> None:
        app = self._app(start_watchdog=False)
        try:
            batch_id = "batch-test"
            app.batches[batch_id] = BatchRecord(
                batch_id=batch_id,
                name="批次",
                source_name="ideas.csv",
                created_at=900.0,
                updated_at=990.0,
                status="running",
                max_concurrent=1,
                provider_snapshot={},
            )
            app.batch_proposals[batch_id] = [
                ProposalRecord(
                    proposal_id="proposal-1",
                    row_index=1,
                    source_batch_id=batch_id,
                    title="测试小说",
                    status="launching",
                )
            ]
            app.batch_items[batch_id] = [
                BatchItemState(
                    batch_id=batch_id,
                    proposal_id="proposal-1",
                    title="测试小说",
                    status="launching",
                    selected=True,
                    priority=1,
                    created_at=900.0,
                    updated_at=1000.0 - app.BATCH_LAUNCH_STALE_SECONDS - 1,
                )
            ]

            with patch("time.time", return_value=1000.0):
                app._sync_batch_items_locked(batch_id)

            self.assertEqual(app.batch_items[batch_id][0].status, "queued")
            self.assertEqual(app.batch_proposals[batch_id][0].status, "queued")
        finally:
            app.close()

    def test_sync_batch_items_reverts_fresh_launching_item_for_resumable_job_to_paused(self) -> None:
        app = self._app(start_watchdog=False)
        try:
            batch_id = "batch-test"
            output_dir = self.root / "runs" / "job-1"
            output_dir.mkdir(parents=True, exist_ok=True)
            app.batches[batch_id] = BatchRecord(
                batch_id=batch_id,
                name="批次",
                source_name="ideas.csv",
                created_at=900.0,
                updated_at=990.0,
                status="running",
                max_concurrent=2,
                provider_snapshot={},
            )
            app.batch_proposals[batch_id] = [
                ProposalRecord(
                    proposal_id="proposal-1",
                    row_index=1,
                    source_batch_id=batch_id,
                    title="测试小说",
                    status="launching",
                )
            ]
            app.batch_items[batch_id] = [
                BatchItemState(
                    batch_id=batch_id,
                    proposal_id="proposal-1",
                    title="测试小说",
                    status="launching",
                    selected=True,
                    priority=1,
                    job_id="job-1",
                    output_dir=str(output_dir),
                    created_at=900.0,
                    updated_at=995.0,
                )
            ]
            app.jobs["job-1"] = JobState(
                job_id="job-1",
                title="测试小说",
                output_dir=str(output_dir),
                status="paused",
                created_at=900.0,
                updated_at=994.0,
                step="paused",
                message="已暂停任务。",
                input_payload={"title": "测试小说"},
            )

            with patch("time.time", return_value=1000.0):
                app._sync_batch_items_locked(batch_id)

            self.assertEqual(app.batch_items[batch_id][0].status, "paused")
            self.assertEqual(app.batch_proposals[batch_id][0].status, "paused")
        finally:
            app.close()

    def test_batch_snapshot_reconciles_stale_failed_item_when_disk_progress_has_advanced(self) -> None:
        app = self._app(start_watchdog=False)
        try:
            batch_id = "batch-test"
            output_dir = self.root / "runs" / "job-1"
            (output_dir / "data").mkdir(parents=True, exist_ok=True)
            (output_dir / "data" / "project-input.json").write_text(
                json.dumps({"title": "测试小说"}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            (output_dir / "data" / "progress.json").write_text(
                json.dumps(
                    {
                        "step": "chapter_rewrite",
                        "message": "重写第92章正文。",
                        "data": {"chapter_index": 92},
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            (output_dir / "data" / "committed-progress.json").write_text(
                json.dumps(
                    {"last_committed_chapter_index": 91, "total_committed_chars": 12345},
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            now = time.time()
            app.batches[batch_id] = BatchRecord(
                batch_id=batch_id,
                name="批次",
                source_name="ideas.csv",
                created_at=now - 100,
                updated_at=now - 50,
                status="running",
                max_concurrent=1,
                provider_snapshot={},
            )
            app.batch_proposals[batch_id] = [
                ProposalRecord(
                    proposal_id="proposal-1",
                    row_index=1,
                    source_batch_id=batch_id,
                    title="测试小说",
                    status="failed",
                )
            ]
            app.batch_items[batch_id] = [
                BatchItemState(
                    batch_id=batch_id,
                    proposal_id="proposal-1",
                    title="测试小说",
                    status="failed",
                    selected=True,
                    priority=1,
                    job_id="job-1",
                    output_dir=str(output_dir),
                    last_error="Chapter 65 failed quality gates after 5 attempts.",
                    created_at=now - 100,
                    updated_at=now - 10,
                )
            ]
            app.jobs["job-1"] = JobState(
                job_id="job-1",
                title="测试小说",
                output_dir=str(output_dir),
                status="failed",
                created_at=now - 100,
                updated_at=now + 1000,
                step="failed",
                message="Chapter 65 failed quality gates after 5 attempts.",
                input_payload={"title": "测试小说"},
            )

            snapshot = app._batch_snapshot_locked(batch_id, include_proposals=False)

            self.assertEqual(app.batch_items[batch_id][0].status, "paused")
            self.assertEqual(app.batch_proposals[batch_id][0].status, "paused")
            self.assertEqual(snapshot["items"][0]["job_status"], "interrupted")
            self.assertEqual(snapshot["items"][0]["step"], "chapter_rewrite")
            self.assertIn("chapter_rewrite", snapshot["items"][0]["message"])
        finally:
            app.close()

    def test_sync_batch_items_marks_launching_item_failed_when_disk_has_failed_snapshot(self) -> None:
        app = self._app(start_watchdog=False)
        try:
            batch_id = "batch-test"
            output_dir = self.root / "runs" / "job-failed-snapshot"
            (output_dir / "data").mkdir(parents=True, exist_ok=True)
            (output_dir / "state").mkdir(parents=True, exist_ok=True)
            (output_dir / "data" / "project-input.json").write_text(
                json.dumps({"title": "测试小说"}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            (output_dir / "state" / "chapter-85.failed.review.json").write_text(
                json.dumps(
                    {
                        "model": {"short_summary": "第85章审校未通过。", "issues": ["群像压迫感不足。"]},
                        "local": {"short_summary": "本地门未通过。"},
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            now = time.time()
            app.batches[batch_id] = BatchRecord(
                batch_id=batch_id,
                name="批次",
                source_name="ideas.csv",
                created_at=now - 100,
                updated_at=now - 50,
                status="running",
                max_concurrent=1,
                provider_snapshot={},
            )
            app.batch_proposals[batch_id] = [
                ProposalRecord(
                    proposal_id="proposal-1",
                    row_index=1,
                    source_batch_id=batch_id,
                    title="测试小说",
                    status="launching",
                )
            ]
            app.batch_items[batch_id] = [
                BatchItemState(
                    batch_id=batch_id,
                    proposal_id="proposal-1",
                    title="测试小说",
                    status="launching",
                    selected=True,
                    priority=1,
                    job_id="job-1",
                    output_dir=str(output_dir),
                    created_at=now - 100,
                    updated_at=now - 10,
                )
            ]

            app._sync_batch_items_locked(batch_id)

            self.assertEqual(app.batch_items[batch_id][0].status, "failed")
            self.assertEqual(app.batch_proposals[batch_id][0].status, "failed")
            self.assertIn("第85章审校未通过", app.batch_items[batch_id][0].last_error or "")
        finally:
            app.close()

    def test_resumable_batch_candidate_ignores_launching_limbo_for_concurrency(self) -> None:
        app = self._app(start_watchdog=False)
        try:
            batch_id = "batch-test"
            output_dir_1 = self.root / "runs" / "job-1"
            output_dir_2 = self.root / "runs" / "job-2"
            output_dir_1.mkdir(parents=True, exist_ok=True)
            output_dir_2.mkdir(parents=True, exist_ok=True)
            app.batches[batch_id] = BatchRecord(
                batch_id=batch_id,
                name="批次",
                source_name="ideas.csv",
                created_at=900.0,
                updated_at=990.0,
                status="running",
                max_concurrent=1,
                provider_snapshot={},
            )
            app.batch_items[batch_id] = [
                BatchItemState(
                    batch_id=batch_id,
                    proposal_id="proposal-1",
                    title="卡住的任务",
                    status="launching",
                    selected=True,
                    priority=1,
                    job_id="job-1",
                    output_dir=str(output_dir_1),
                    created_at=900.0,
                    updated_at=995.0,
                ),
                BatchItemState(
                    batch_id=batch_id,
                    proposal_id="proposal-2",
                    title="应继续恢复的任务",
                    status="paused",
                    selected=True,
                    priority=2,
                    job_id="job-2",
                    output_dir=str(output_dir_2),
                    created_at=900.0,
                    updated_at=995.0,
                ),
            ]
            app.jobs["job-1"] = JobState(
                job_id="job-1",
                title="卡住的任务",
                output_dir=str(output_dir_1),
                status="paused",
                created_at=900.0,
                updated_at=994.0,
                step="paused",
                message="已暂停任务。",
                input_payload={"title": "卡住的任务"},
            )
            app.jobs["job-2"] = JobState(
                job_id="job-2",
                title="应继续恢复的任务",
                output_dir=str(output_dir_2),
                status="paused",
                created_at=900.0,
                updated_at=994.0,
                step="paused",
                message="已暂停任务。",
                input_payload={"title": "应继续恢复的任务"},
            )

            candidate = app._resumable_batch_candidate_locked(batch_id)

            self.assertIsNotNone(candidate)
            item, _ = candidate  # type: ignore[misc]
            self.assertEqual(item.proposal_id, "proposal-2")
        finally:
            app.close()

    def test_pause_batch_pauses_running_children_and_freezes_queue(self) -> None:
        app = self._app(start_watchdog=False)
        try:
            batch_id = "batch-test"
            now = time.time()
            app.batches[batch_id] = BatchRecord(
                batch_id=batch_id,
                name="批次",
                source_name="ideas.csv",
                created_at=now - 20,
                updated_at=now - 10,
                status="running",
                max_concurrent=2,
                provider_snapshot={},
            )
            app.batch_proposals[batch_id] = [
                ProposalRecord(
                    proposal_id="proposal-1",
                    row_index=1,
                    source_batch_id=batch_id,
                    title="甲",
                    status="running",
                ),
                ProposalRecord(
                    proposal_id="proposal-2",
                    row_index=2,
                    source_batch_id=batch_id,
                    title="乙",
                    status="queued",
                ),
            ]
            app.jobs["job-1"] = JobState(
                job_id="job-1",
                title="甲",
                output_dir=str(self.root / "runs" / "job-1"),
                status="running",
                created_at=now - 20,
                updated_at=now - 5,
                step="chapter_draft",
            )
            app.batch_items[batch_id] = [
                BatchItemState(
                    batch_id=batch_id,
                    proposal_id="proposal-1",
                    title="甲",
                    status="running",
                    selected=True,
                    job_id="job-1",
                    created_at=now - 20,
                    updated_at=now - 5,
                ),
                BatchItemState(
                    batch_id=batch_id,
                    proposal_id="proposal-2",
                    title="乙",
                    status="queued",
                    selected=True,
                    created_at=now - 20,
                    updated_at=now - 6,
                ),
            ]

            snapshot = app.pause_batch(batch_id)

            self.assertTrue(snapshot["paused"])
            self.assertEqual(snapshot["status"], "paused")
            self.assertEqual(app.jobs["job-1"].status, "paused")
            self.assertEqual(app.batch_items[batch_id][0].status, "paused")
            self.assertEqual(app.batch_items[batch_id][1].status, "paused")
            self.assertEqual(app.batch_proposals[batch_id][0].status, "paused")
            self.assertEqual(app.batch_proposals[batch_id][1].status, "paused")
        finally:
            app.close()

    def test_resume_batch_only_restores_paused_and_queued_items(self) -> None:
        app = self._app(start_watchdog=False)
        try:
            batch_id = "batch-test"
            now = time.time()
            app.batches[batch_id] = BatchRecord(
                batch_id=batch_id,
                name="批次",
                source_name="ideas.csv",
                created_at=now - 20,
                updated_at=now - 10,
                status="paused",
                max_concurrent=2,
                paused=True,
                provider_snapshot={},
                config=BatchConfig(
                    target_total_chars=2500000,
                    target_chars_per_chapter=None,
                    chapter_count=None,
                    volume_count=None,
                    structure_mode="story_driven",
                    market_profile="tomato_mass",
                    ending_mode="series",
                    run_to_completion=False,
                    pause_at_chars=400000,
                ),
            )
            app.batch_proposals[batch_id] = [
                ProposalRecord(proposal_id="proposal-1", row_index=1, source_batch_id=batch_id, title="甲", status="paused"),
                ProposalRecord(proposal_id="proposal-2", row_index=2, source_batch_id=batch_id, title="乙", status="failed"),
                ProposalRecord(proposal_id="proposal-3", row_index=3, source_batch_id=batch_id, title="丙", status="queued"),
            ]
            app.jobs["job-1"] = JobState(
                job_id="job-1",
                title="甲",
                output_dir=str(self.root / "runs" / "job-1"),
                status="paused",
                created_at=now - 20,
                updated_at=now - 5,
                step="paused",
                input_payload={"title": "甲"},
            )
            app.batch_items[batch_id] = [
                BatchItemState(batch_id=batch_id, proposal_id="proposal-1", title="甲", status="paused", selected=True, job_id="job-1", pause_reason="char_limit", created_at=now - 20, updated_at=now - 5),
                BatchItemState(batch_id=batch_id, proposal_id="proposal-2", title="乙", status="failed", selected=True, job_id="missing", last_error="旧错误", created_at=now - 20, updated_at=now - 5),
                BatchItemState(batch_id=batch_id, proposal_id="proposal-3", title="丙", status="queued", selected=True, created_at=now - 20, updated_at=now - 5),
            ]
            app._batch_tick = lambda: None  # type: ignore[method-assign]

            snapshot = app.resume_batch(
                batch_id,
                {
                    "max_concurrent": 25,
                    "target_total_chars": 4000000,
                    "target_chars_per_chapter": 2000,
                    "chapter_count": 200,
                    "volume_count": 20,
                    "structure_mode": "legacy",
                    "market_profile": "qidian_longform",
                    "ending_mode": "standalone",
                    "run_to_completion": True,
                    "pause_at_chars": 500000,
                },
            )

            self.assertFalse(snapshot["paused"])
            self.assertEqual(app.batches[batch_id].max_concurrent, 25)
            self.assertEqual(app.batches[batch_id].config.target_total_chars, 2500000)
            self.assertIsNone(app.batches[batch_id].config.target_chars_per_chapter)
            self.assertIsNone(app.batches[batch_id].config.chapter_count)
            self.assertIsNone(app.batches[batch_id].config.volume_count)
            self.assertEqual(app.batches[batch_id].config.structure_mode, "story_driven")
            self.assertEqual(app.batches[batch_id].config.market_profile, "tomato_mass")
            self.assertEqual(app.batches[batch_id].config.ending_mode, "series")
            self.assertTrue(app.batches[batch_id].config.run_to_completion)
            self.assertEqual(app.batches[batch_id].config.pause_at_chars, 500000)
            self.assertEqual(app.batch_items[batch_id][0].status, "queued")
            self.assertIsNone(app.batch_items[batch_id][0].pause_reason)
            self.assertEqual(app.batch_items[batch_id][1].status, "failed")
            self.assertEqual(app.batch_items[batch_id][2].status, "queued")
        finally:
            app.close()

    def test_resume_all_batch_requeues_failed_and_clears_pause_reason(self) -> None:
        app = self._app(start_watchdog=False)
        try:
            batch_id = "batch-test"
            now = time.time()
            app.batches[batch_id] = BatchRecord(
                batch_id=batch_id,
                name="批次",
                source_name="ideas.csv",
                created_at=now - 20,
                updated_at=now - 10,
                status="paused",
                max_concurrent=2,
                paused=True,
                provider_snapshot={},
            )
            app.batch_proposals[batch_id] = [
                ProposalRecord(proposal_id="proposal-1", row_index=1, source_batch_id=batch_id, title="甲", status="failed"),
                ProposalRecord(proposal_id="proposal-2", row_index=2, source_batch_id=batch_id, title="乙", status="paused"),
            ]
            app.jobs["job-1"] = JobState(
                job_id="job-1",
                title="甲",
                output_dir=str(self.root / "runs" / "job-1"),
                status="failed",
                created_at=now - 20,
                updated_at=now - 5,
                step="failed",
                input_payload={"title": "甲"},
            )
            app.jobs["job-2"] = JobState(
                job_id="job-2",
                title="乙",
                output_dir=str(self.root / "runs" / "job-2"),
                status="paused",
                created_at=now - 20,
                updated_at=now - 5,
                step="paused",
                input_payload={"title": "乙"},
            )
            app.batch_items[batch_id] = [
                BatchItemState(batch_id=batch_id, proposal_id="proposal-1", title="甲", status="failed", selected=True, job_id="job-1", last_error="旧错误", created_at=now - 20, updated_at=now - 5),
                BatchItemState(batch_id=batch_id, proposal_id="proposal-2", title="乙", status="paused", selected=True, job_id="job-2", pause_reason="char_limit", created_at=now - 20, updated_at=now - 5),
            ]
            app._batch_tick = lambda: None  # type: ignore[method-assign]

            snapshot = app.resume_all_batch(batch_id)

            self.assertFalse(snapshot["paused"])
            self.assertEqual(app.batch_items[batch_id][0].status, "queued")
            self.assertIsNone(app.batch_items[batch_id][0].last_error)
            self.assertEqual(app.batch_items[batch_id][1].status, "queued")
            self.assertIsNone(app.batch_items[batch_id][1].pause_reason)
        finally:
            app.close()

    def test_legacy_batch_market_profile_payload_collects_tomato_hints_from_proposals(self) -> None:
        payload = _legacy_batch_market_profile_payload(
            {
                "target_total_chars": 2500000,
                "structure_mode": "story_driven",
            },
            [
                {
                    "platform_fit": "番茄大众男频",
                    "reference_requirements": "黄金三章要狠，要小白快节奏",
                    "style_seed": "番茄爆款，小白爽文",
                    "hook": "高考当天全城扣寿",
                }
            ],
        )

        self.assertIn("番茄大众男频", payload["audience"])
        self.assertIn("小白爽文", payload["tone"])
        self.assertIn("黄金三章", payload["outline_hint"])
        self.assertIn("番茄爆款，小白爽文", payload["style_examples"])

    def test_resume_all_batch_keeps_failed_item_paused_when_new_char_limit_is_already_reached(self) -> None:
        app = self._app(start_watchdog=False)
        try:
            batch_id = "batch-test"
            now = time.time()
            output_dir = self.root / "runs" / "job-1"
            (output_dir / "data").mkdir(parents=True, exist_ok=True)
            (output_dir / "data" / "run-summary.json").write_text('{"total_chars": 600}', encoding="utf-8")
            app.batches[batch_id] = BatchRecord(
                batch_id=batch_id,
                name="批次",
                source_name="ideas.csv",
                created_at=now - 20,
                updated_at=now - 10,
                status="paused",
                max_concurrent=2,
                paused=True,
                provider_snapshot={},
                config=BatchConfig(
                    target_total_chars=2500000,
                    structure_mode="story_driven",
                    ending_mode="series",
                    run_to_completion=True,
                    pause_at_chars=300000,
                ),
            )
            app.batch_proposals[batch_id] = [
                ProposalRecord(proposal_id="proposal-1", row_index=1, source_batch_id=batch_id, title="甲", status="failed"),
            ]
            app.jobs["job-1"] = JobState(
                job_id="job-1",
                title="甲",
                output_dir=str(output_dir),
                status="failed",
                created_at=now - 20,
                updated_at=now - 5,
                step="failed",
                input_payload={"title": "甲"},
            )
            app.batch_items[batch_id] = [
                BatchItemState(
                    batch_id=batch_id,
                    proposal_id="proposal-1",
                    title="甲",
                    status="failed",
                    selected=True,
                    job_id="job-1",
                    output_dir=str(output_dir),
                    last_error="旧错误",
                    created_at=now - 20,
                    updated_at=now - 5,
                )
            ]
            app._batch_tick = lambda: None  # type: ignore[method-assign]

            snapshot = app.resume_all_batch(
                batch_id,
                {
                    "run_to_completion": False,
                    "pause_at_chars": 100,
                },
            )

            self.assertFalse(snapshot["paused"])
            self.assertFalse(app.batches[batch_id].config.run_to_completion)
            self.assertEqual(app.batches[batch_id].config.pause_at_chars, 100)
            self.assertEqual(app.batch_items[batch_id][0].status, "paused")
            self.assertEqual(app.batch_items[batch_id][0].pause_reason, "char_limit")
            self.assertEqual(app.batch_items[batch_id][0].written_chars, 600)
            self.assertIsNone(app.batch_items[batch_id][0].last_error)
            self.assertEqual(app.jobs["job-1"].status, "paused")
        finally:
            app.close()

    def test_pause_batch_item_pauses_only_target_item(self) -> None:
        app = self._app(start_watchdog=False)
        try:
            batch_id = "batch-test"
            now = time.time()
            app.batches[batch_id] = BatchRecord(
                batch_id=batch_id,
                name="批次",
                source_name="ideas.csv",
                created_at=now - 20,
                updated_at=now - 10,
                status="running",
                max_concurrent=2,
                paused=False,
                provider_snapshot={},
            )
            app.batch_proposals[batch_id] = [
                ProposalRecord(proposal_id="proposal-1", row_index=1, source_batch_id=batch_id, title="甲", status="running"),
                ProposalRecord(proposal_id="proposal-2", row_index=2, source_batch_id=batch_id, title="乙", status="running"),
            ]
            app.jobs["job-1"] = JobState(job_id="job-1", title="甲", output_dir=str(self.root / "runs" / "job-1"), status="running", created_at=now - 20, updated_at=now - 5, step="chapter_draft", input_payload={"title": "甲"})
            app.jobs["job-2"] = JobState(job_id="job-2", title="乙", output_dir=str(self.root / "runs" / "job-2"), status="running", created_at=now - 20, updated_at=now - 5, step="chapter_draft", input_payload={"title": "乙"})
            app.batch_items[batch_id] = [
                BatchItemState(batch_id=batch_id, proposal_id="proposal-1", title="甲", status="running", selected=True, job_id="job-1", created_at=now - 20, updated_at=now - 5),
                BatchItemState(batch_id=batch_id, proposal_id="proposal-2", title="乙", status="running", selected=True, job_id="job-2", created_at=now - 20, updated_at=now - 5),
            ]

            app.pause_batch_item(batch_id, "proposal-1")

            self.assertEqual(app.batch_items[batch_id][0].status, "paused")
            self.assertEqual(app.batch_items[batch_id][0].pause_reason, "manual_pause")
            self.assertEqual(app.batch_items[batch_id][1].status, "running")
        finally:
            app.close()

    def test_resume_batch_item_recovers_failed_target_without_touching_others(self) -> None:
        app = self._app(start_watchdog=False)
        try:
            batch_id = "batch-test"
            now = time.time()
            app.batches[batch_id] = BatchRecord(
                batch_id=batch_id,
                name="批次",
                source_name="ideas.csv",
                created_at=now - 20,
                updated_at=now - 10,
                status="paused",
                max_concurrent=2,
                paused=True,
                provider_snapshot={},
            )
            app.batch_proposals[batch_id] = [
                ProposalRecord(proposal_id="proposal-1", row_index=1, source_batch_id=batch_id, title="甲", status="failed"),
                ProposalRecord(proposal_id="proposal-2", row_index=2, source_batch_id=batch_id, title="乙", status="paused"),
            ]
            app.jobs["job-1"] = JobState(job_id="job-1", title="甲", output_dir=str(self.root / "runs" / "job-1"), status="failed", created_at=now - 20, updated_at=now - 5, step="failed", input_payload={"title": "甲"})
            app.jobs["job-2"] = JobState(job_id="job-2", title="乙", output_dir=str(self.root / "runs" / "job-2"), status="paused", created_at=now - 20, updated_at=now - 5, step="paused", input_payload={"title": "乙"})
            app.batch_items[batch_id] = [
                BatchItemState(batch_id=batch_id, proposal_id="proposal-1", title="甲", status="failed", selected=True, job_id="job-1", last_error="旧错误", created_at=now - 20, updated_at=now - 5),
                BatchItemState(batch_id=batch_id, proposal_id="proposal-2", title="乙", status="paused", selected=True, job_id="job-2", pause_reason="manual_pause", created_at=now - 20, updated_at=now - 5),
            ]
            app._batch_tick = lambda: None  # type: ignore[method-assign]

            app.resume_batch_item(batch_id, "proposal-1")

            self.assertFalse(app.batches[batch_id].paused)
            self.assertEqual(app.batch_items[batch_id][0].status, "queued")
            self.assertIsNone(app.batch_items[batch_id][0].last_error)
            self.assertEqual(app.batch_items[batch_id][1].status, "paused")
            self.assertEqual(app.batch_items[batch_id][1].pause_reason, "manual_pause")
        finally:
            app.close()

    def test_derive_batch_status_returns_paused_when_selected_items_are_paused(self) -> None:
        app = self._app(start_watchdog=False)
        try:
            batch_id = "batch-test"
            now = time.time()
            app.batches[batch_id] = BatchRecord(
                batch_id=batch_id,
                name="批次",
                source_name="ideas.csv",
                created_at=now - 20,
                updated_at=now - 10,
                status="running",
                max_concurrent=2,
                provider_snapshot={},
            )
            app.batch_items[batch_id] = [
                BatchItemState(
                    batch_id=batch_id,
                    proposal_id="proposal-1",
                    title="甲",
                    status="paused",
                    selected=True,
                    pause_reason="upper_decision",
                    created_at=now - 20,
                    updated_at=now - 5,
                )
            ]

            self.assertEqual(app._derive_batch_status_locked(batch_id), "paused")
        finally:
            app.close()

    def test_job_provider_snapshot_is_persisted_without_api_key(self) -> None:
        app = self._app(start_watchdog=False)
        try:
            provider = ProviderConfig(
                base_url="https://relay.example.com",
                wire_api="responses",
                api_key="secret",
                model="gpt-flagship",
                review_model="gpt-flagship",
                light_model="gpt-light",
                continuation_mode="hybrid",
            )
            with patch("sagaquill.server.resolve_provider_config") as resolve_provider:
                resolve_provider.return_value = provider
                app._launch_job = lambda *args, **kwargs: None  # type: ignore[method-assign]
                payload = app._create_job_payload(  # type: ignore[attr-defined]
                    {"title": "测试小说"},
                    provider_override={"base_url": "https://relay.example.com", "api_key": "secret"},
                )

            output_dir = Path(payload["output_dir"])
            provider_snapshot = json.loads((output_dir / "data" / "provider.snapshot.json").read_text(encoding="utf-8"))
            self.assertEqual(app.jobs[payload["job_id"]].provider_override["api_key"], "secret")
            self.assertNotIn("api_key", provider_snapshot)
        finally:
            app.close()

    def test_job_snapshot_uses_latest_chapter_preview_before_novel_exists(self) -> None:
        app = self._app(start_watchdog=False)
        output_dir = Path.cwd() / "runs" / "test-artifacts" / f"preview-chapters-{uuid.uuid4().hex[:8]}"
        chapter_dir = output_dir / "chapters"
        chapter_dir.mkdir(parents=True, exist_ok=True)
        try:
            (chapter_dir / "chapter-02.md").write_text("第二章正文。", encoding="utf-8")
            (chapter_dir / "chapter-10.md").write_text("第十章正文。", encoding="utf-8")
            now = time.time()
            app.jobs["job-1"] = JobState(
                job_id="job-1",
                title="测试小说",
                output_dir=str(output_dir),
                status="running",
                created_at=now - 10,
                updated_at=now - 1,
                step="chapter_draft",
                attempt_count=1,
                auto_resume_count=0,
                run_token="token-1",
                input_payload={"title": "测试小说"},
                log=[JobLogEntry(step="chapter_draft", message="生成第 11 章正文。", created_at=now - 1)],
            )

            snapshot = app.job_snapshot("job-1")

            self.assertIn("运行预览：已完成 2 章", snapshot["novel_preview"])
            self.assertIn("第 10 章", snapshot["novel_preview"])
            self.assertIn("第十章正文。", snapshot["novel_preview"])
            self.assertNotIn("第二章正文。", snapshot["novel_preview"])
        finally:
            app.close()
            shutil.rmtree(output_dir, ignore_errors=True)

    def test_job_snapshot_prefers_novel_preview_when_novel_exists(self) -> None:
        app = self._app(start_watchdog=False)
        output_dir = Path.cwd() / "runs" / "test-artifacts" / f"preview-novel-{uuid.uuid4().hex[:8]}"
        chapter_dir = output_dir / "chapters"
        chapter_dir.mkdir(parents=True, exist_ok=True)
        try:
            (chapter_dir / "chapter-01.md").write_text("章节正文。", encoding="utf-8")
            (output_dir / "novel.md").write_text("整本预览。", encoding="utf-8")
            now = time.time()
            app.jobs["job-1"] = JobState(
                job_id="job-1",
                title="测试小说",
                output_dir=str(output_dir),
                status="completed",
                created_at=now - 10,
                updated_at=now - 1,
                step="completed",
                summary={"final_summary": "完成。"},
                run_token="token-1",
                input_payload={"title": "测试小说"},
                log=[JobLogEntry(step="completed", message="任务已完成。", created_at=now - 1)],
            )

            snapshot = app.job_snapshot("job-1")

            self.assertEqual(snapshot["novel_preview"], "整本预览。")
        finally:
            app.close()
            shutil.rmtree(output_dir, ignore_errors=True)

    def test_job_snapshot_builds_preview_outside_lock(self) -> None:
        app = self._app(start_watchdog=False)
        output_dir = Path.cwd() / "runs" / "test-artifacts" / f"preview-lock-{uuid.uuid4().hex[:8]}"
        output_dir.mkdir(parents=True, exist_ok=True)
        try:
            (output_dir / "novel.md").write_text("整本预览。", encoding="utf-8")
            now = time.time()
            app.jobs["job-1"] = JobState(
                job_id="job-1",
                title="测试小说",
                output_dir=str(output_dir),
                status="running",
                created_at=now - 10,
                updated_at=now - 1,
                step="chapter_review",
                run_token="token-1",
                input_payload={"title": "测试小说"},
            )

            original_load_preview = app._load_preview_text

            def load_preview_checked(path: Path) -> str:
                lock_was_held = not app.lock.acquire(blocking=False)
                if not lock_was_held:
                    app.lock.release()
                self.assertFalse(lock_was_held)
                return original_load_preview(path)

            app._load_preview_text = load_preview_checked  # type: ignore[method-assign]
            snapshot = app.job_snapshot("job-1")

            self.assertEqual(snapshot["novel_preview"], "整本预览。")
        finally:
            app.close()
            shutil.rmtree(output_dir, ignore_errors=True)

    def test_list_jobs_builds_snapshots_outside_lock(self) -> None:
        app = self._app(start_watchdog=False)
        output_dir = Path.cwd() / "runs" / "test-artifacts" / f"list-jobs-lock-{uuid.uuid4().hex[:8]}"
        output_dir.mkdir(parents=True, exist_ok=True)
        try:
            now = time.time()
            app.jobs["job-1"] = JobState(
                job_id="job-1",
                title="测试小说",
                output_dir=str(output_dir),
                status="running",
                created_at=now - 10,
                updated_at=now - 1,
                step="chapter_plan",
                run_token="token-1",
                input_payload={"title": "测试小说"},
            )

            original_snapshot = app._snapshot

            def snapshot_checked(*args, **kwargs):
                lock_was_held = not app.lock.acquire(blocking=False)
                if not lock_was_held:
                    app.lock.release()
                self.assertFalse(lock_was_held)
                return original_snapshot(*args, **kwargs)

            app._snapshot = snapshot_checked  # type: ignore[method-assign]
            payload = app.list_jobs()

            self.assertEqual(len(payload["jobs"]), 1)
            self.assertEqual(payload["jobs"][0]["job_id"], "job-1")
        finally:
            app.close()
            shutil.rmtree(output_dir, ignore_errors=True)

    def test_app_recovers_interrupted_run_from_disk(self) -> None:
        job_id = uuid.uuid4().hex[:8]
        output_dir = self.root / "runs" / f"恢复测试-20260319-000000-{job_id}"
        data_dir = output_dir / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        try:
            (data_dir / "project-input.json").write_text(
                json.dumps({"title": "恢复测试"}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            (data_dir / "progress.json").write_text(
                json.dumps({"step": "world", "message": "生成设定圣经。"}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            app = self._app(start_watchdog=False)
            try:
                snapshot = app.job_snapshot(job_id)
                self.assertEqual(snapshot["status"], "interrupted")
                self.assertEqual(snapshot["step"], "world")
                self.assertIn("可点击恢复运行", snapshot["message"])
            finally:
                app.close()
        finally:
            shutil.rmtree(output_dir, ignore_errors=True)

    def test_app_recovers_legacy_upper_review_run_as_interrupted(self) -> None:
        job_id = uuid.uuid4().hex[:8]
        output_dir = self.root / "runs" / f"上层决策恢复-20260319-000000-{job_id}"
        data_dir = output_dir / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        try:
            (data_dir / "project-input.json").write_text(
                json.dumps({"title": "上层决策恢复"}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            (data_dir / "pending-upper-decision.json").write_text(
                json.dumps(
                    {
                        "chapter_index": 32,
                        "signal_level": "escalation",
                        "decision": "phase_repair",
                        "confidence": 86,
                        "reason": "最近章节簇被上层判定为阶段级空转风险。",
                        "scope_start_chapter": 24,
                        "scope_end_chapter": 32,
                        "next_chapter_constraints": ["后续必须产生新的不可逆后果。"],
                        "repair_goal": "建议阶段级回修。",
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            app = self._app(start_watchdog=False)
            try:
                snapshot = app.job_snapshot(job_id)
                self.assertEqual(snapshot["status"], "interrupted")
                self.assertEqual(snapshot["step"], "resume")
                self.assertNotIn("pending_upper_decision", snapshot)
                self.assertIn("自动修复策略", snapshot["message"])
            finally:
                app.close()
        finally:
            shutil.rmtree(output_dir, ignore_errors=True)

    def test_app_recovers_failed_run_from_latest_final_review_snapshot(self) -> None:
        job_id = uuid.uuid4().hex[:8]
        output_dir = self.root / "runs" / f"终审失败恢复-20260319-000000-{job_id}"
        data_dir = output_dir / "data"
        state_dir = output_dir / "state"
        data_dir.mkdir(parents=True, exist_ok=True)
        state_dir.mkdir(parents=True, exist_ok=True)
        try:
            (data_dir / "project-input.json").write_text(
                json.dumps({"title": "终审失败恢复"}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            (state_dir / "final-review.latest.json").write_text(
                json.dumps({"passed": False, "short_summary": "终审未通过，需要收束主线。"}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            app = self._app(start_watchdog=False)
            try:
                snapshot = app.job_snapshot(job_id)
                self.assertEqual(snapshot["status"], "failed")
                self.assertEqual(snapshot["step"], "failed")
                self.assertIn("终审未通过", snapshot["message"])
            finally:
                app.close()
        finally:
            shutil.rmtree(output_dir, ignore_errors=True)

    def test_provider_settings_round_trip_and_reset(self) -> None:
        root = Path.cwd() / "runs" / "test-artifacts" / f"provider-roundtrip-{uuid.uuid4().hex}"
        root.mkdir(parents=True, exist_ok=True)
        app = SagaQuillApp(start_watchdog=False, project_root=root)
        try:
            with patch(
                "sagaquill.server.provider_panel_payload",
                side_effect=lambda codex_dir=None, project_root=None: {
                    "provider_source": "override" if (Path(project_root) / ".sagaquill" / "provider.json").exists() else "codex",
                    "override_exists": (Path(project_root) / ".sagaquill" / "provider.json").exists(),
                    "override_path": str(Path(project_root) / ".sagaquill" / "provider.json"),
                    "effective": {
                        "base_url": "https://relay.example.com/v1",
                        "wire_api": "responses",
                        "model": "gpt-test",
                        "review_model": "gpt-review",
                        "continuation_mode": "replay",
                        "api_key_present": True,
                        "api_key_source": "codex",
                    },
                    "form": {
                        "base_url": "https://relay.example.com/v1",
                        "wire_api": "responses",
                        "model": "gpt-test",
                        "review_model": "gpt-review",
                        "continuation_mode": "replay",
                        "api_key": "",
                        "api_key_present": True,
                        "api_key_source": "codex",
                    },
                    "version": "test",
                    "revision": "deadbee",
                },
            ):
                saved = app.save_provider_settings(
                    {
                        "base_url": "https://relay.example.com/v1",
                        "wire_api": "responses",
                        "model": "gpt-test",
                        "review_model": "gpt-review",
                        "continuation_mode": "replay",
                        "api_key": "secret",
                    }
                )
                self.assertTrue(saved["saved"])
                self.assertTrue((root / ".sagaquill" / "provider.json").exists())

                reset = app.reset_provider_settings()
                self.assertFalse(reset["saved"])
                self.assertFalse((root / ".sagaquill" / "provider.json").exists())
        finally:
            app.close()
            shutil.rmtree(root, ignore_errors=True)

    def test_provider_test_uses_resolved_payload(self) -> None:
        root = Path.cwd() / "runs" / "test-artifacts" / f"provider-test-{uuid.uuid4().hex}"
        root.mkdir(parents=True, exist_ok=True)
        app = SagaQuillApp(start_watchdog=False, project_root=root)
        try:
            fake_provider = type(
                "Provider",
                (),
                {
                    "base_url": "https://relay.example.com/v1",
                    "wire_api": "responses",
                    "api_key": "secret",
                    "model": "gpt-test",
                    "light_model": "gpt-light",
                    "review_model": "gpt-review",
                    "continuation_mode": "replay",
                    "reasoning_effort": None,
                    "service_tier": None,
                    "flagship_reasoning_effort": "xhigh",
                    "flagship_service_tier": "fast",
                    "light_reasoning_effort": "medium",
                    "light_service_tier": "default",
                    "default_headers": {},
                },
            )()
            with (
                patch("sagaquill.server.resolve_provider_config", return_value=fake_provider),
                patch("sagaquill.server.OpenAICompatibleClient") as client_cls,
            ):
                client_cls.return_value.generate_text.side_effect = ["OK", "OK", "OK"]
                result = app.test_provider({"base_url": "https://relay.example.com/v1", "api_key": "secret"})

            self.assertTrue(result["ok"])
            self.assertEqual(result["reply"], "OK")
            self.assertEqual(result["resolved"]["model"], "gpt-test")
            self.assertEqual(result["resolved"]["light_model"], "gpt-light")
            self.assertEqual(result["resolved"]["review_model"], "gpt-review")
            self.assertEqual(result["resolved"]["flagship_reasoning_effort"], "xhigh")
            self.assertEqual(result["resolved"]["flagship_service_tier"], "fast")
            self.assertEqual(result["resolved"]["light_reasoning_effort"], "medium")
            self.assertEqual(result["resolved"]["light_service_tier"], "default")
            self.assertEqual(result["tests"]["flagship"]["model"], "gpt-test")
            self.assertEqual(result["tests"]["light"]["model"], "gpt-light")
            self.assertEqual(result["tests"]["review"]["model"], "gpt-review")
            self.assertTrue(result["tests"]["flagship"]["ok"])
            self.assertTrue(result["tests"]["light"]["ok"])
            self.assertTrue(result["tests"]["review"]["ok"])
            self.assertFalse(result["tests"]["light"]["reused"])
            self.assertFalse(result["tests"]["review"]["reused"])
            self.assertEqual(client_cls.return_value.generate_text.call_count, 3)
            first_call = client_cls.return_value.generate_text.call_args_list[0]
            second_call = client_cls.return_value.generate_text.call_args_list[1]
            third_call = client_cls.return_value.generate_text.call_args_list[2]
            self.assertEqual(first_call.kwargs["model"], "gpt-test")
            self.assertEqual(first_call.kwargs["provider_tier"], "flagship")
            self.assertEqual(second_call.kwargs["model"], "gpt-light")
            self.assertEqual(second_call.kwargs["provider_tier"], "light")
            self.assertEqual(third_call.kwargs["model"], "gpt-review")
            self.assertEqual(third_call.kwargs["provider_tier"], "flagship")
        finally:
            app.close()
            shutil.rmtree(root, ignore_errors=True)

    def test_provider_test_reuses_probe_when_light_model_matches_flagship(self) -> None:
        root = Path.cwd() / "runs" / "test-artifacts" / f"provider-test-reuse-{uuid.uuid4().hex}"
        root.mkdir(parents=True, exist_ok=True)
        app = SagaQuillApp(start_watchdog=False, project_root=root)
        try:
            fake_provider = type(
                "Provider",
                (),
                {
                    "base_url": "https://relay.example.com/v1",
                    "wire_api": "responses",
                    "api_key": "secret",
                    "model": "gpt-test",
                    "light_model": "gpt-test",
                    "review_model": "gpt-test",
                    "continuation_mode": "hybrid",
                    "reasoning_effort": None,
                    "service_tier": None,
                    "flagship_reasoning_effort": "xhigh",
                    "flagship_service_tier": "fast",
                    "light_reasoning_effort": "xhigh",
                    "light_service_tier": "fast",
                    "default_headers": {},
                },
            )()
            with (
                patch("sagaquill.server.resolve_provider_config", return_value=fake_provider),
                patch("sagaquill.server.OpenAICompatibleClient") as client_cls,
            ):
                client_cls.return_value.generate_text.return_value = "OK"
                result = app.test_provider({"base_url": "https://relay.example.com/v1", "api_key": "secret"})

            self.assertTrue(result["ok"])
            self.assertTrue(result["tests"]["light"]["reused"])
            self.assertEqual(result["tests"]["light"]["reply"], "OK")
            self.assertEqual(client_cls.return_value.generate_text.call_count, 1)
        finally:
            app.close()
            shutil.rmtree(root, ignore_errors=True)

    def test_provider_test_does_not_reuse_probe_when_tier_settings_differ(self) -> None:
        root = Path.cwd() / "runs" / "test-artifacts" / f"provider-test-tier-split-{uuid.uuid4().hex}"
        root.mkdir(parents=True, exist_ok=True)
        app = SagaQuillApp(start_watchdog=False, project_root=root)
        try:
            fake_provider = type(
                "Provider",
                (),
                {
                    "base_url": "https://relay.example.com/v1",
                    "wire_api": "responses",
                    "api_key": "secret",
                    "model": "gpt-test",
                    "light_model": "gpt-test",
                    "review_model": "gpt-test",
                    "continuation_mode": "hybrid",
                    "reasoning_effort": None,
                    "service_tier": None,
                    "flagship_reasoning_effort": "xhigh",
                    "flagship_service_tier": "fast",
                    "light_reasoning_effort": "medium",
                    "light_service_tier": "default",
                    "default_headers": {},
                },
            )()
            with (
                patch("sagaquill.server.resolve_provider_config", return_value=fake_provider),
                patch("sagaquill.server.OpenAICompatibleClient") as client_cls,
            ):
                client_cls.return_value.generate_text.side_effect = ["OK", "OK"]
                result = app.test_provider({"base_url": "https://relay.example.com/v1", "api_key": "secret"})

            self.assertTrue(result["ok"])
            self.assertFalse(result["tests"]["light"]["reused"])
            self.assertEqual(client_cls.return_value.generate_text.call_count, 2)
        finally:
            app.close()
            shutil.rmtree(root, ignore_errors=True)

    def test_provider_test_reports_partial_success_when_light_model_fails(self) -> None:
        root = Path.cwd() / "runs" / "test-artifacts" / f"provider-test-partial-{uuid.uuid4().hex}"
        root.mkdir(parents=True, exist_ok=True)
        app = SagaQuillApp(start_watchdog=False, project_root=root)
        try:
            fake_provider = type(
                "Provider",
                (),
                {
                    "base_url": "https://relay.example.com/v1",
                    "wire_api": "responses",
                    "api_key": "secret",
                    "model": "gpt-flagship",
                    "light_model": "gpt-light-missing",
                    "review_model": "gpt-light-missing",
                    "continuation_mode": "hybrid",
                    "reasoning_effort": None,
                    "service_tier": None,
                    "flagship_reasoning_effort": "high",
                    "flagship_service_tier": None,
                    "light_reasoning_effort": "low",
                    "light_service_tier": None,
                    "default_headers": {},
                },
            )()
            with (
                patch("sagaquill.server.resolve_provider_config", return_value=fake_provider),
                patch("sagaquill.server.OpenAICompatibleClient") as client_cls,
            ):
                client_cls.return_value.generate_text.side_effect = ["OK", RuntimeError("model not found")]
                result = app.test_provider({"base_url": "https://relay.example.com/v1", "api_key": "secret"})

            self.assertFalse(result["ok"])
            self.assertTrue(result["partial"])
            self.assertTrue(result["tests"]["flagship"]["ok"])
            self.assertFalse(result["tests"]["light"]["ok"])
            self.assertIn("model not found", result["tests"]["light"]["error"])
        finally:
            app.close()
            shutil.rmtree(root, ignore_errors=True)

    def test_provider_test_reports_full_failure_without_raising(self) -> None:
        root = Path.cwd() / "runs" / "test-artifacts" / f"provider-test-fail-{uuid.uuid4().hex}"
        root.mkdir(parents=True, exist_ok=True)
        app = SagaQuillApp(start_watchdog=False, project_root=root)
        try:
            fake_provider = type(
                "Provider",
                (),
                {
                    "base_url": "https://relay.example.com/v1",
                    "wire_api": "responses",
                    "api_key": "secret",
                    "model": "gpt-flagship",
                    "light_model": "gpt-light",
                    "review_model": "gpt-light",
                    "continuation_mode": "replay",
                    "reasoning_effort": None,
                    "service_tier": None,
                    "flagship_reasoning_effort": None,
                    "flagship_service_tier": None,
                    "light_reasoning_effort": None,
                    "light_service_tier": None,
                    "default_headers": {},
                },
            )()
            with (
                patch("sagaquill.server.resolve_provider_config", return_value=fake_provider),
                patch("sagaquill.server.OpenAICompatibleClient") as client_cls,
            ):
                client_cls.return_value.generate_text.side_effect = [RuntimeError("flagship down"), RuntimeError("light down")]
                result = app.test_provider({"base_url": "https://relay.example.com/v1", "api_key": "secret"})

            self.assertFalse(result["ok"])
            self.assertFalse(result["partial"])
            self.assertFalse(result["tests"]["flagship"]["ok"])
            self.assertFalse(result["tests"]["light"]["ok"])
            self.assertIn("flagship down", result["tests"]["flagship"]["error"])
            self.assertIn("light down", result["tests"]["light"]["error"])
        finally:
            app.close()
            shutil.rmtree(root, ignore_errors=True)

    def test_provider_test_falls_back_to_stream_when_responses_text_extraction_fails(self) -> None:
        root = Path.cwd() / "runs" / "test-artifacts" / f"provider-test-stream-fallback-{uuid.uuid4().hex}"
        root.mkdir(parents=True, exist_ok=True)
        app = SagaQuillApp(start_watchdog=False, project_root=root)
        try:
            fake_provider = type(
                "Provider",
                (),
                {
                    "base_url": "https://relay.example.com/v1",
                    "wire_api": "responses",
                    "api_key": "secret",
                    "model": "gpt-flagship",
                    "light_model": "gpt-flagship",
                    "review_model": "gpt-flagship",
                    "continuation_mode": "hybrid",
                    "reasoning_effort": None,
                    "service_tier": None,
                    "flagship_reasoning_effort": None,
                    "flagship_service_tier": None,
                    "light_reasoning_effort": None,
                    "light_service_tier": None,
                    "default_headers": {},
                },
            )()
            with (
                patch("sagaquill.server.resolve_provider_config", return_value=fake_provider),
                patch("sagaquill.server.OpenAICompatibleClient") as client_cls,
            ):
                client = client_cls.return_value
                client.generate_text.side_effect = [
                    ModelClientError("Could not extract text from responses payload."),
                    "OK",
                ]
                result = app.test_provider({"base_url": "https://relay.example.com/v1", "api_key": "secret"})

            self.assertTrue(result["ok"])
            self.assertEqual(result["tests"]["flagship"]["reply"], "OK")
            self.assertEqual(client.generate_text.call_args_list[0].kwargs["stream"], False)
            self.assertEqual(client.generate_text.call_args_list[1].kwargs["stream"], True)
        finally:
            app.close()
            shutil.rmtree(root, ignore_errors=True)

    def test_create_job_applies_inline_provider_override(self) -> None:
        root = Path.cwd() / "runs" / "test-artifacts" / f"create-job-provider-{uuid.uuid4().hex}"
        root.mkdir(parents=True, exist_ok=True)
        app = SagaQuillApp(start_watchdog=False, project_root=root)
        try:
            fake_provider = type(
                "Provider",
                (),
                {
                    "base_url": "https://relay.example.com",
                    "wire_api": "anthropic-messages",
                    "api_key": "secret",
                    "model": "claude-test",
                    "light_model": "claude-test",
                    "review_model": "claude-test",
                    "gateway_profile": None,
                    "continuation_mode": "replay",
                    "flagship_reasoning_effort": None,
                    "flagship_service_tier": None,
                    "light_reasoning_effort": None,
                    "light_service_tier": None,
                    "reasoning_effort": None,
                    "service_tier": None,
                    "default_headers": {},
                },
            )()
            with (
                patch("sagaquill.server.resolve_provider_config", return_value=fake_provider),
                patch.object(app, "_launch_job"),
            ):
                snapshot = app.create_job(
                    {
                        "title": "测试书",
                        "market_profile": "tomato_mass",
                        "provider": {
                            "base_url": "https://relay.example.com",
                            "wire_api": "anthropic-messages",
                            "model": "claude-test",
                            "light_model": "claude-test",
                            "api_key": "secret",
                        },
                    }
                )

            provider_path = Path(snapshot["output_dir"]) / "data" / "provider.snapshot.json"
            provider_payload = json.loads(provider_path.read_text(encoding="utf-8"))
            self.assertEqual(provider_payload["wire_api"], "anthropic-messages")
            self.assertEqual(provider_payload["model"], "claude-test")
            self.assertEqual(snapshot["provider_snapshot"]["wire_api"], "anthropic-messages")
            self.assertEqual(snapshot["provider_snapshot"]["model"], "claude-test")
            self.assertEqual(snapshot["provider_snapshot"]["light_model"], "claude-test")
            self.assertEqual(snapshot["provider_snapshot"]["source"], "job_snapshot")
        finally:
            app.close()
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
