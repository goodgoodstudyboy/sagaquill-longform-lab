from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import tomllib

from .models import ProviderConfig
from .util import ensure_directory


def default_codex_dir() -> Path:
    return Path.home() / ".codex"


def load_codex_provider(codex_dir: str | Path | None = None) -> ProviderConfig:
    root = Path(codex_dir) if codex_dir else default_codex_dir()
    config_path = root / "config.toml"
    auth_path = root / "auth.json"

    config = tomllib.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
    provider_name = str(config.get("model_provider") or "OpenAI")
    providers = config.get("model_providers") or {}
    provider = providers.get(provider_name) or {}
    auth_payload = _load_auth_payload(auth_path)
    wire_api = str(
        os.environ.get("SAGAQUILL_WIRE_API")
        or provider.get("wire_api")
        or ("anthropic-messages" if "anthropic" in provider_name.lower() else "chat-completions")
    )

    api_key = (
        os.environ.get("OPENAI_API_KEY")
        or auth_payload.get("OPENAI_API_KEY")
        or auth_payload.get("api_key")
        or os.environ.get("ANTHROPIC_AUTH_TOKEN")
        or os.environ.get("ANTHROPIC_API_KEY")
        or auth_payload.get("ANTHROPIC_AUTH_TOKEN")
        or auth_payload.get("ANTHROPIC_API_KEY")
    )
    if not api_key:
        raise ValueError("Could not resolve provider API key from environment or Codex auth.json.")

    anthropic_base_url = _string_or_none(os.environ.get("ANTHROPIC_BASE_URL"))
    openai_base_url = _string_or_none(os.environ.get("OPENAI_BASE_URL"))
    sagaquill_base_url = _string_or_none(os.environ.get("SAGAQUILL_BASE_URL"))
    default_base_url = "https://api.anthropic.com/v1" if wire_api == "anthropic-messages" else "https://api.openai.com/v1"
    model = (
        os.environ.get("SAGAQUILL_MODEL")
        or os.environ.get("ANTHROPIC_MODEL")
        or os.environ.get("OPENAI_MODEL")
        or config.get("model")
        or "gpt-4o"
    )
    review_model = (
        os.environ.get("SAGAQUILL_REVIEW_MODEL")
        or config.get("review_model")
        or os.environ.get("SAGAQUILL_LIGHT_MODEL")
        or config.get("light_model")
        or config.get("utility_model")
        or model
    )
    light_model = (
        os.environ.get("SAGAQUILL_LIGHT_MODEL")
        or config.get("light_model")
        or config.get("utility_model")
        or os.environ.get("SAGAQUILL_REVIEW_MODEL")
        or config.get("review_model")
        or model
    )

    return ProviderConfig(
        base_url=str(sagaquill_base_url or anthropic_base_url or openai_base_url or provider.get("base_url") or default_base_url),
        wire_api=wire_api,
        api_key=str(api_key),
        model=str(model),
        review_model=str(review_model),
        light_model=str(light_model),
        gateway_profile=None,
        flagship_reasoning_effort=None,
        flagship_service_tier=None,
        light_reasoning_effort=None,
        light_service_tier=None,
        reasoning_effort=_string_or_none(config.get("model_reasoning_effort")),
        service_tier=_string_or_none(config.get("service_tier")),
        continuation_mode=_string_or_none(
            os.environ.get("SAGAQUILL_CONTINUATION_MODE")
            or provider.get("continuation_mode")
            or config.get("responses_continuation_mode")
        )
        or "replay",
        default_headers={},
    )


def provider_override_path(project_root: str | Path | None = None) -> Path:
    root = Path(project_root) if project_root else Path.cwd()
    return root / ".sagaquill" / "provider.json"


def load_provider_override(project_root: str | Path | None = None) -> dict[str, Any]:
    path = provider_override_path(project_root)
    if not path.exists():
        return {}
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return {}
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError(f"Provider override must be a JSON object: {path}")
    return _sanitize_provider_override(payload)


def resolve_provider_config(
    payload: dict[str, Any] | None,
    *,
    codex_dir: str | Path | None = None,
    project_root: str | Path | None = None,
    preserve_saved_api_key: bool = True,
) -> ProviderConfig:
    codex_provider = load_codex_provider(codex_dir)
    stored_override = load_provider_override(project_root)
    transient_override = _sanitize_provider_override(
        payload or {},
        existing=stored_override,
        preserve_saved_api_key=preserve_saved_api_key,
    )
    merged_override = dict(stored_override)
    merged_override.update(transient_override)
    return _merge_provider_config(codex_provider, merged_override)


def load_provider_config(
    codex_dir: str | Path | None = None,
    *,
    project_root: str | Path | None = None,
) -> ProviderConfig:
    return resolve_provider_config({}, codex_dir=codex_dir, project_root=project_root)


def provider_panel_payload(
    codex_dir: str | Path | None = None,
    *,
    project_root: str | Path | None = None,
) -> dict[str, Any]:
    root = Path(project_root) if project_root else Path.cwd()
    codex_provider = load_codex_provider(codex_dir)
    override = load_provider_override(root)
    effective = _merge_provider_config(codex_provider, override)
    version = project_version()
    api_key_source = "override" if override.get("api_key") else "codex"
    flagship_reasoning_effort = effective.flagship_reasoning_effort or effective.reasoning_effort
    flagship_service_tier = effective.flagship_service_tier or effective.service_tier
    light_reasoning_effort = effective.light_reasoning_effort or effective.reasoning_effort
    light_service_tier = effective.light_service_tier or effective.service_tier
    return {
        "override_path": str(provider_override_path(root)),
        "override_exists": bool(override),
        "provider_source": "override" if override else "codex",
        "effective": {
            "base_url": effective.base_url,
            "wire_api": effective.wire_api,
            "model": effective.model,
            "light_model": effective.light_model or effective.review_model or effective.model,
            "review_model": effective.review_model or effective.light_model or effective.model,
            "gateway_profile": effective.gateway_profile,
            "flagship_reasoning_effort": flagship_reasoning_effort,
            "flagship_service_tier": flagship_service_tier,
            "light_reasoning_effort": light_reasoning_effort,
            "light_service_tier": light_service_tier,
            "reasoning_effort": effective.reasoning_effort,
            "service_tier": effective.service_tier,
            "continuation_mode": effective.continuation_mode,
            "api_key_present": bool(effective.api_key),
            "api_key_source": api_key_source,
        },
        "form": {
            "base_url": override.get("base_url") or effective.base_url,
            "wire_api": override.get("wire_api") or effective.wire_api,
            "model": override.get("model") or effective.model,
            "light_model": override.get("light_model") or effective.light_model or effective.review_model or effective.model,
            "review_model": override.get("review_model") or effective.review_model or effective.light_model or effective.model,
            "gateway_profile": _form_override_value(override, "gateway_profile", effective.gateway_profile),
            "flagship_reasoning_effort": _form_override_value(override, "flagship_reasoning_effort", flagship_reasoning_effort),
            "flagship_service_tier": _form_override_value(override, "flagship_service_tier", flagship_service_tier),
            "light_reasoning_effort": _form_override_value(override, "light_reasoning_effort", light_reasoning_effort),
            "light_service_tier": _form_override_value(override, "light_service_tier", light_service_tier),
            "reasoning_effort": _form_override_value(override, "reasoning_effort", effective.reasoning_effort),
            "service_tier": _form_override_value(override, "service_tier", effective.service_tier),
            "continuation_mode": override.get("continuation_mode") or effective.continuation_mode,
            "api_key": "",
            "api_key_present": bool(override.get("api_key")) or bool(effective.api_key),
            "api_key_source": api_key_source,
        },
        "version": version["version"],
        "revision": version["revision"],
    }


def save_provider_override(
    payload: dict[str, Any],
    *,
    codex_dir: str | Path | None = None,
    project_root: str | Path | None = None,
) -> dict[str, Any]:
    root = Path(project_root) if project_root else Path.cwd()
    existing = load_provider_override(root)
    override = _sanitize_provider_override(payload, existing=existing, preserve_saved_api_key=True)
    path = provider_override_path(root)
    if override:
        ensure_directory(path.parent)
        path.write_text(json.dumps(override, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    elif path.exists():
        path.unlink()
    return provider_panel_payload(codex_dir, project_root=root)


def clear_provider_override(
    project_root: str | Path | None = None,
    *,
    codex_dir: str | Path | None = None,
) -> dict[str, Any]:
    root = Path(project_root) if project_root else Path.cwd()
    path = provider_override_path(root)
    if path.exists():
        path.unlink()
    return provider_panel_payload(codex_dir, project_root=root)


def codex_doctor(codex_dir: str | Path | None = None) -> dict[str, Any]:
    root = Path(codex_dir) if codex_dir else default_codex_dir()
    config_path = root / "config.toml"
    auth_path = root / "auth.json"
    provider = load_codex_provider(root)
    version = project_version()
    return {
        "codex_dir": str(root),
        "config_path": str(config_path),
        "auth_path": str(auth_path),
        "base_url": provider.base_url,
        "wire_api": provider.wire_api,
        "model": provider.model,
        "light_model": provider.light_model or provider.review_model or provider.model,
        "review_model": provider.review_model or provider.light_model or provider.model,
        "continuation_mode": provider.continuation_mode,
        "api_key_present": bool(provider.api_key),
        "version": version["version"],
        "revision": version["revision"],
    }


def provider_doctor(
    codex_dir: str | Path | None = None,
    *,
    project_root: str | Path | None = None,
) -> dict[str, Any]:
    details = provider_panel_payload(codex_dir, project_root=project_root)
    effective = details["effective"]
    root = Path(project_root) if project_root else Path.cwd()
    payload = codex_doctor(codex_dir)
    payload.update(
        {
            "base_url": effective["base_url"],
            "wire_api": effective["wire_api"],
            "model": effective["model"],
            "light_model": effective["light_model"],
            "review_model": effective["review_model"],
            "flagship_reasoning_effort": effective["flagship_reasoning_effort"],
            "flagship_service_tier": effective["flagship_service_tier"],
            "light_reasoning_effort": effective["light_reasoning_effort"],
            "light_service_tier": effective["light_service_tier"],
            "reasoning_effort": effective["reasoning_effort"],
            "service_tier": effective["service_tier"],
            "continuation_mode": effective["continuation_mode"],
            "api_key_present": effective["api_key_present"],
            "provider_source": details["provider_source"],
            "override_path": str(provider_override_path(root)),
            "override_exists": details["override_exists"],
            "api_key_source": effective["api_key_source"],
        }
    )
    return payload


def provider_snapshot(provider: ProviderConfig, *, include_api_key: bool = False) -> dict[str, Any]:
    payload = {
        "base_url": provider.base_url,
        "wire_api": provider.wire_api,
        "model": provider.model,
        "review_model": provider.review_model,
        "light_model": provider.light_model,
        "gateway_profile": provider.gateway_profile,
        "continuation_mode": provider.continuation_mode,
        "flagship_reasoning_effort": provider.flagship_reasoning_effort,
        "flagship_service_tier": provider.flagship_service_tier,
        "light_reasoning_effort": provider.light_reasoning_effort,
        "light_service_tier": provider.light_service_tier,
        "reasoning_effort": provider.reasoning_effort,
        "service_tier": provider.service_tier,
        "default_headers": dict(provider.default_headers or {}),
    }
    if include_api_key and provider.api_key:
        payload["api_key"] = provider.api_key
    return payload


def project_version(project_root: str | Path | None = None) -> dict[str, str]:
    root = Path(project_root) if project_root else Path(__file__).resolve().parents[1]
    fallback = {
        "version": os.environ.get("SAGAQUILL_VERSION", "unknown"),
        "revision": os.environ.get("SAGAQUILL_REVISION", "unknown"),
    }
    try:
        version = subprocess.check_output(
            ["git", "-C", str(root), "describe", "--tags", "--always"],
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
        ).strip()
        revision = subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return fallback
    return {
        "version": version or fallback["version"],
        "revision": revision or fallback["revision"],
    }


def _load_auth_payload(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return {}
    return json.loads(raw)


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _sanitize_provider_override(
    payload: dict[str, Any],
    *,
    existing: dict[str, Any] | None = None,
    preserve_saved_api_key: bool = False,
) -> dict[str, Any]:
    current = existing or {}
    cleaned: dict[str, Any] = {}
    clearable_keys = {
        "flagship_reasoning_effort",
        "flagship_service_tier",
        "light_reasoning_effort",
        "light_service_tier",
        "reasoning_effort",
        "service_tier",
    }
    for key in (
        "base_url",
        "wire_api",
        "api_key",
        "model",
        "light_model",
        "gateway_profile",
        "review_model",
        "flagship_reasoning_effort",
        "flagship_service_tier",
        "light_reasoning_effort",
        "light_service_tier",
        "reasoning_effort",
        "service_tier",
        "continuation_mode",
    ):
        if key in payload and payload.get(key) is None and key in clearable_keys:
            cleaned[key] = None
            continue
        text = _string_or_none(payload.get(key))
        if text is not None:
            cleaned[key] = text
            continue
        if key == "api_key" and preserve_saved_api_key and current.get("api_key"):
            cleaned[key] = str(current["api_key"])
    return cleaned


def _merge_provider_config(base: ProviderConfig, override: dict[str, Any]) -> ProviderConfig:
    light_model = _string_or_none(override.get("light_model") or override.get("review_model")) or base.light_model or base.review_model or base.model
    review_model = _string_or_none(override.get("review_model") or override.get("light_model")) or base.review_model or base.light_model or base.model
    tier_fields_present = any(
        key in override
        for key in (
            "flagship_reasoning_effort",
            "flagship_service_tier",
            "light_reasoning_effort",
            "light_service_tier",
        )
    )
    shared_reasoning_base = None if tier_fields_present and "reasoning_effort" not in override else base.reasoning_effort
    shared_service_tier_base = None if tier_fields_present and "service_tier" not in override else base.service_tier
    return ProviderConfig(
        base_url=str(override.get("base_url") or base.base_url),
        wire_api=str(override.get("wire_api") or base.wire_api),
        api_key=str(override.get("api_key") or base.api_key),
        model=str(override.get("model") or base.model),
        review_model=str(review_model),
        light_model=str(light_model),
        gateway_profile=_merged_optional_override(override, "gateway_profile", base.gateway_profile),
        flagship_reasoning_effort=_merged_optional_override(override, "flagship_reasoning_effort", base.flagship_reasoning_effort),
        flagship_service_tier=_merged_optional_override(override, "flagship_service_tier", base.flagship_service_tier),
        light_reasoning_effort=_merged_optional_override(override, "light_reasoning_effort", base.light_reasoning_effort),
        light_service_tier=_merged_optional_override(override, "light_service_tier", base.light_service_tier),
        reasoning_effort=_merged_optional_override(override, "reasoning_effort", shared_reasoning_base),
        service_tier=_merged_optional_override(override, "service_tier", shared_service_tier_base),
        continuation_mode=_string_or_none(override.get("continuation_mode")) or base.continuation_mode,
        default_headers=dict(base.default_headers),
    )


def _merged_optional_override(override: dict[str, Any], key: str, base_value: str | None) -> str | None:
    if key in override:
        return _string_or_none(override.get(key))
    return base_value


def _form_override_value(override: dict[str, Any], key: str, effective_value: str | None) -> str:
    if key in override:
        return _string_or_none(override.get(key)) or ""
    return effective_value or ""
