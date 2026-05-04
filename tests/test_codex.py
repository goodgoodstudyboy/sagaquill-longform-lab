from __future__ import annotations

import shutil
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from sagaquill.codex import (
    clear_provider_override,
    codex_doctor,
    load_codex_provider,
    load_provider_config,
    load_provider_override,
    provider_doctor,
    provider_override_path,
    provider_panel_payload,
    save_provider_override,
)


class CodexConfigTests(unittest.TestCase):
    def test_light_model_falls_through_to_review_model_when_review_missing(self) -> None:
        root = Path.cwd() / "runs" / "test-artifacts" / f"codex-review-fallback-{uuid.uuid4().hex}"
        root.mkdir(parents=True, exist_ok=True)
        try:
            (root / "config.toml").write_text(
                '\n'.join(
                    [
                        'model_provider = "OpenAI"',
                        'model = "gpt-5.4"',
                        'light_model = "gpt-5.4-mini"',
                        '',
                        '[model_providers.OpenAI]',
                        'base_url = "https://relay.example.com"',
                        'wire_api = "responses"',
                    ]
                ),
                encoding="utf-8",
            )
            (root / "auth.json").write_text('{"OPENAI_API_KEY":"test-secret"}', encoding="utf-8")

            provider = load_codex_provider(root)
            panel = provider_panel_payload(root, project_root=root)

            self.assertEqual(provider.light_model, "gpt-5.4-mini")
            self.assertEqual(provider.review_model, "gpt-5.4-mini")
            self.assertEqual(panel["effective"]["review_model"], "gpt-5.4-mini")
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_load_codex_provider_reads_config_and_auth(self) -> None:
        root = Path.cwd() / "runs" / "test-artifacts" / f"codex-{uuid.uuid4().hex}"
        root.mkdir(parents=True, exist_ok=True)
        try:
            (root / "config.toml").write_text(
                '\n'.join(
                    [
                        'model_provider = "OpenAI"',
                        'model = "gpt-5.4"',
                        'review_model = "gpt-5.4"',
                        'model_reasoning_effort = "medium"',
                        '',
                        '[model_providers.OpenAI]',
                        'base_url = "https://relay.example.com"',
                        'wire_api = "responses"',
                    ]
                ),
                encoding="utf-8",
            )
            (root / "auth.json").write_text('{"OPENAI_API_KEY":"test-secret"}', encoding="utf-8")

            provider = load_codex_provider(root)
            doctor = codex_doctor(root)

            self.assertEqual(provider.base_url, "https://relay.example.com")
            self.assertEqual(provider.wire_api, "responses")
            self.assertEqual(provider.model, "gpt-5.4")
            self.assertEqual(provider.review_model, "gpt-5.4")
            self.assertEqual(provider.light_model, "gpt-5.4")
            self.assertIsNone(provider.flagship_reasoning_effort)
            self.assertIsNone(provider.flagship_service_tier)
            self.assertIsNone(provider.light_reasoning_effort)
            self.assertIsNone(provider.light_service_tier)
            self.assertEqual(provider.reasoning_effort, "medium")
            self.assertIsNone(provider.service_tier)
            self.assertEqual(provider.api_key, "test-secret")
            self.assertTrue(doctor["api_key_present"])
            self.assertEqual(doctor["light_model"], "gpt-5.4")
            self.assertIn("version", doctor)
            self.assertIn("revision", doctor)
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_load_provider_can_use_environment_without_codex_config(self) -> None:
        root = Path.cwd() / "runs" / "test-artifacts" / f"provider-env-only-{uuid.uuid4().hex}"
        root.mkdir(parents=True, exist_ok=True)
        try:
            with patch.dict(
                "os.environ",
                {
                    "OPENAI_API_KEY": "env-secret",
                    "SAGAQUILL_BASE_URL": "https://relay.example.com/v1",
                    "SAGAQUILL_MODEL": "gpt-env",
                    "SAGAQUILL_LIGHT_MODEL": "gpt-env-light",
                    "SAGAQUILL_REVIEW_MODEL": "gpt-env-review",
                    "SAGAQUILL_WIRE_API": "responses",
                },
                clear=False,
            ):
                provider = load_provider_config(root, project_root=root / "project")

            self.assertEqual(provider.api_key, "env-secret")
            self.assertEqual(provider.base_url, "https://relay.example.com/v1")
            self.assertEqual(provider.model, "gpt-env")
            self.assertEqual(provider.light_model, "gpt-env-light")
            self.assertEqual(provider.review_model, "gpt-env-review")
            self.assertEqual(provider.wire_api, "responses")
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_load_codex_provider_can_resolve_anthropic_env(self) -> None:
        root = Path.cwd() / "runs" / "test-artifacts" / f"codex-anthropic-{uuid.uuid4().hex}"
        root.mkdir(parents=True, exist_ok=True)
        try:
            (root / "config.toml").write_text(
                '\n'.join(
                    [
                        'model_provider = "Anthropic"',
                        'model = "claude-sonnet-4-5-20250929"',
                        '',
                        '[model_providers.Anthropic]',
                        'wire_api = "anthropic-messages"',
                    ]
                ),
                encoding="utf-8",
            )
            (root / "auth.json").write_text("{}", encoding="utf-8")

            with patch.dict(
                "os.environ",
                {
                    "ANTHROPIC_BASE_URL": "https://relay.example.com",
                    "ANTHROPIC_AUTH_TOKEN": "anthropic-secret",
                },
                clear=False,
            ):
                provider = load_codex_provider(root)

            self.assertEqual(provider.base_url, "https://relay.example.com")
            self.assertEqual(provider.wire_api, "anthropic-messages")
            self.assertEqual(provider.model, "claude-sonnet-4-5-20250929")
            self.assertEqual(provider.api_key, "anthropic-secret")
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_local_provider_override_merges_with_codex_defaults(self) -> None:
        root = Path.cwd() / "runs" / "test-artifacts" / f"provider-override-{uuid.uuid4().hex}"
        project_root = root / "project"
        project_root.mkdir(parents=True, exist_ok=True)
        try:
            (root / "config.toml").write_text(
                '\n'.join(
                    [
                        'model_provider = "OpenAI"',
                        'model = "gpt-5.4"',
                        'review_model = "gpt-5.4-review"',
                        '',
                        '[model_providers.OpenAI]',
                        'base_url = "https://relay.example.com/v1"',
                        'wire_api = "responses"',
                    ]
                ),
                encoding="utf-8",
            )
            (root / "auth.json").write_text('{"OPENAI_API_KEY":"codex-secret"}', encoding="utf-8")

            saved = save_provider_override(
                {
                    "base_url": "https://relay.alt.example.com/v1",
                    "model": "gpt-5.5",
                    "review_model": "gpt-5.5-review",
                    "flagship_reasoning_effort": "xhigh",
                    "flagship_service_tier": "fast",
                    "light_reasoning_effort": "medium",
                    "light_service_tier": "default",
                    "continuation_mode": "previous_response_id",
                    "api_key": "override-secret",
                },
                codex_dir=root,
                project_root=project_root,
            )
            provider = load_provider_config(root, project_root=project_root)
            panel = provider_panel_payload(root, project_root=project_root)
            doctor = provider_doctor(root, project_root=project_root)

            self.assertTrue(saved["override_exists"])
            self.assertEqual(load_provider_override(project_root)["model"], "gpt-5.5")
            self.assertEqual(provider.base_url, "https://relay.alt.example.com/v1")
            self.assertEqual(provider.model, "gpt-5.5")
            self.assertEqual(provider.review_model, "gpt-5.5-review")
            self.assertEqual(provider.light_model, "gpt-5.5-review")
            self.assertEqual(provider.api_key, "override-secret")
            self.assertIsNone(provider.reasoning_effort)
            self.assertIsNone(provider.service_tier)
            self.assertEqual(provider.flagship_reasoning_effort, "xhigh")
            self.assertEqual(provider.flagship_service_tier, "fast")
            self.assertEqual(provider.light_reasoning_effort, "medium")
            self.assertEqual(provider.light_service_tier, "default")
            self.assertEqual(provider.continuation_mode, "previous_response_id")
            self.assertEqual(panel["provider_source"], "override")
            self.assertEqual(panel["effective"]["light_model"], "gpt-5.5-review")
            self.assertEqual(panel["effective"]["flagship_reasoning_effort"], "xhigh")
            self.assertEqual(panel["effective"]["flagship_service_tier"], "fast")
            self.assertEqual(panel["effective"]["light_reasoning_effort"], "medium")
            self.assertEqual(panel["effective"]["light_service_tier"], "default")
            self.assertEqual(panel["form"]["flagship_reasoning_effort"], "xhigh")
            self.assertEqual(panel["form"]["flagship_service_tier"], "fast")
            self.assertEqual(panel["form"]["light_reasoning_effort"], "medium")
            self.assertEqual(panel["form"]["light_service_tier"], "default")
            self.assertEqual(panel["form"]["api_key"], "")
            self.assertTrue(panel["form"]["api_key_present"])
            self.assertEqual(doctor["provider_source"], "override")
            self.assertEqual(doctor["api_key_source"], "override")
            self.assertEqual(doctor["light_model"], "gpt-5.5-review")
            self.assertEqual(doctor["flagship_reasoning_effort"], "xhigh")
            self.assertEqual(doctor["flagship_service_tier"], "fast")
            self.assertEqual(doctor["light_reasoning_effort"], "medium")
            self.assertEqual(doctor["light_service_tier"], "default")
            self.assertEqual(provider_override_path(project_root), project_root / ".sagaquill" / "provider.json")

            cleared = clear_provider_override(project_root, codex_dir=root)
            fallback = load_provider_config(root, project_root=project_root)
            self.assertFalse(cleared["override_exists"])
            self.assertEqual(fallback.base_url, "https://relay.example.com/v1")
            self.assertEqual(fallback.api_key, "codex-secret")
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_override_keeps_distinct_review_model_from_light_model(self) -> None:
        root = Path.cwd() / "runs" / "test-artifacts" / f"provider-review-separate-{uuid.uuid4().hex}"
        project_root = root / "project"
        project_root.mkdir(parents=True, exist_ok=True)
        try:
            (root / "config.toml").write_text(
                '\n'.join(
                    [
                        'model_provider = "OpenAI"',
                        'model = "gpt-5.4"',
                        'light_model = "gpt-5.4-mini"',
                        '',
                        '[model_providers.OpenAI]',
                        'base_url = "https://relay.example.com/v1"',
                        'wire_api = "responses"',
                    ]
                ),
                encoding="utf-8",
            )
            (root / "auth.json").write_text('{"OPENAI_API_KEY":"codex-secret"}', encoding="utf-8")

            save_provider_override(
                {
                    "light_model": "gpt-5.4-mini",
                    "review_model": "gpt-5.4-review",
                },
                codex_dir=root,
                project_root=project_root,
            )

            provider = load_provider_config(root, project_root=project_root)
            panel = provider_panel_payload(root, project_root=project_root)

            self.assertEqual(provider.light_model, "gpt-5.4-mini")
            self.assertEqual(provider.review_model, "gpt-5.4-review")
            self.assertEqual(panel["effective"]["light_model"], "gpt-5.4-mini")
            self.assertEqual(panel["effective"]["review_model"], "gpt-5.4-review")
            self.assertEqual(panel["form"]["review_model"], "gpt-5.4-review")
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_optional_provider_fields_can_be_explicitly_cleared(self) -> None:
        root = Path.cwd() / "runs" / "test-artifacts" / f"provider-clear-{uuid.uuid4().hex}"
        project_root = root / "project"
        project_root.mkdir(parents=True, exist_ok=True)
        try:
            (root / "config.toml").write_text(
                '\n'.join(
                    [
                        'model_provider = "OpenAI"',
                        'model = "gpt-5.4"',
                        'review_model = "gpt-5.4"',
                        'model_reasoning_effort = "xhigh"',
                        'service_tier = "fast"',
                        '',
                        '[model_providers.OpenAI]',
                        'base_url = "https://relay.example.com/v1"',
                        'wire_api = "responses"',
                    ]
                ),
                encoding="utf-8",
            )
            (root / "auth.json").write_text('{"OPENAI_API_KEY":"codex-secret"}', encoding="utf-8")

            save_provider_override(
                {
                    "base_url": "https://relay.alt.example.com/v1",
                    "service_tier": None,
                    "reasoning_effort": None,
                    "flagship_reasoning_effort": None,
                    "flagship_service_tier": None,
                    "light_reasoning_effort": None,
                    "light_service_tier": None,
                },
                codex_dir=root,
                project_root=project_root,
            )

            provider = load_provider_config(root, project_root=project_root)
            panel = provider_panel_payload(root, project_root=project_root)
            override = load_provider_override(project_root)

            self.assertIn("service_tier", override)
            self.assertIsNone(override["service_tier"])
            self.assertIn("reasoning_effort", override)
            self.assertIsNone(override["reasoning_effort"])
            self.assertIn("flagship_reasoning_effort", override)
            self.assertIsNone(override["flagship_reasoning_effort"])
            self.assertIn("flagship_service_tier", override)
            self.assertIsNone(override["flagship_service_tier"])
            self.assertIn("light_reasoning_effort", override)
            self.assertIsNone(override["light_reasoning_effort"])
            self.assertIn("light_service_tier", override)
            self.assertIsNone(override["light_service_tier"])
            self.assertIsNone(provider.service_tier)
            self.assertIsNone(provider.reasoning_effort)
            self.assertIsNone(provider.flagship_reasoning_effort)
            self.assertIsNone(provider.flagship_service_tier)
            self.assertIsNone(provider.light_reasoning_effort)
            self.assertIsNone(provider.light_service_tier)
            self.assertEqual(panel["effective"]["service_tier"], None)
            self.assertEqual(panel["effective"]["reasoning_effort"], None)
            self.assertEqual(panel["effective"]["flagship_reasoning_effort"], None)
            self.assertEqual(panel["effective"]["flagship_service_tier"], None)
            self.assertEqual(panel["effective"]["light_reasoning_effort"], None)
            self.assertEqual(panel["effective"]["light_service_tier"], None)
            self.assertEqual(panel["form"]["service_tier"], "")
            self.assertEqual(panel["form"]["reasoning_effort"], "")
            self.assertEqual(panel["form"]["flagship_reasoning_effort"], "")
            self.assertEqual(panel["form"]["flagship_service_tier"], "")
            self.assertEqual(panel["form"]["light_reasoning_effort"], "")
            self.assertEqual(panel["form"]["light_service_tier"], "")
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_tier_specific_override_disables_shared_codex_reasoning_fallback(self) -> None:
        root = Path.cwd() / "runs" / "test-artifacts" / f"provider-tier-fallback-{uuid.uuid4().hex}"
        project_root = root / "project"
        project_root.mkdir(parents=True, exist_ok=True)
        try:
            (root / "config.toml").write_text(
                '\n'.join(
                    [
                        'model_provider = "OpenAI"',
                        'model = "gpt-5.4"',
                        'review_model = "gpt-5.4"',
                        'model_reasoning_effort = "xhigh"',
                        'service_tier = "fast"',
                        '',
                        '[model_providers.OpenAI]',
                        'base_url = "https://relay.example.com/v1"',
                        'wire_api = "responses"',
                    ]
                ),
                encoding="utf-8",
            )
            (root / "auth.json").write_text('{"OPENAI_API_KEY":"codex-secret"}', encoding="utf-8")

            save_provider_override(
                {
                    "base_url": "https://relay.alt.example.com/v1",
                    "flagship_reasoning_effort": None,
                    "flagship_service_tier": "priority",
                    "light_reasoning_effort": None,
                    "light_service_tier": "priority",
                },
                codex_dir=root,
                project_root=project_root,
            )

            provider = load_provider_config(root, project_root=project_root)
            panel = provider_panel_payload(root, project_root=project_root)

            self.assertIsNone(provider.reasoning_effort)
            self.assertIsNone(provider.flagship_reasoning_effort)
            self.assertIsNone(provider.light_reasoning_effort)
            self.assertEqual(provider.flagship_service_tier, "priority")
            self.assertEqual(provider.light_service_tier, "priority")
            self.assertEqual(panel["effective"]["flagship_reasoning_effort"], None)
            self.assertEqual(panel["effective"]["light_reasoning_effort"], None)
            self.assertEqual(panel["effective"]["flagship_service_tier"], "priority")
            self.assertEqual(panel["effective"]["light_service_tier"], "priority")
        finally:
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
