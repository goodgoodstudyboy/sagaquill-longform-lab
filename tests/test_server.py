from __future__ import annotations

import json
import threading
import unittest
import urllib.error
import urllib.request

from sagaquill.server import build_server


class ServerTests(unittest.TestCase):
    def test_remote_bind_requires_access_token(self) -> None:
        with self.assertRaises(ValueError):
            build_server("0.0.0.0", 0)

    def test_access_token_protects_panel_and_api(self) -> None:
        server = build_server("127.0.0.1", 0, access_token="secret", require_auth=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_port}"
            health = json.loads(urllib.request.urlopen(f"{base}/healthz", timeout=5).read().decode("utf-8"))
            self.assertTrue(health["ok"])

            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(f"{base}/api/info", timeout=5)
            self.assertEqual(caught.exception.code, 401)

            request = urllib.request.Request(f"{base}/api/info", headers={"Authorization": "Bearer secret"})
            payload = json.loads(urllib.request.urlopen(request, timeout=5).read().decode("utf-8"))
            self.assertIn("version", payload)
        finally:
            server.shutdown()
            server.server_close()

    def test_server_exposes_panel_template_and_job_creation(self) -> None:
        server = build_server("127.0.0.1", 0)
        app = server.RequestHandlerClass.app
        app.info = lambda: {  # type: ignore[method-assign]
            "model": "gpt-test",
            "base_url": "https://relay.example.com",
            "provider_source": "codex",
            "version": "v0.2.1",
            "revision": "2cb6e87",
        }
        app.provider_settings = lambda: {  # type: ignore[method-assign]
            "provider_source": "codex",
            "override_exists": False,
            "override_path": ".sagaquill/provider.json",
            "effective": {
                "base_url": "https://relay.example.com",
                "wire_api": "responses",
                "model": "gpt-test",
                "review_model": "gpt-review",
                "continuation_mode": "replay",
                "api_key_present": True,
                "api_key_source": "codex",
            },
            "form": {
                "base_url": "https://relay.example.com",
                "wire_api": "responses",
                "model": "gpt-test",
                "review_model": "gpt-review",
                "continuation_mode": "replay",
                "api_key": "",
                "api_key_present": True,
                "api_key_source": "codex",
            },
            "version": "v0.2.1",
            "revision": "2cb6e87",
        }
        app.save_provider_settings = lambda payload: {  # type: ignore[method-assign]
            "saved": True,
            "provider_source": "override",
            "override_exists": True,
            "override_path": ".sagaquill/provider.json",
            "effective": {
                "base_url": payload["base_url"],
                "wire_api": payload["wire_api"],
                "model": payload["model"],
                "review_model": payload["review_model"],
                "continuation_mode": payload["continuation_mode"],
                "api_key_present": True,
                "api_key_source": "override",
            },
            "form": {
                "base_url": payload["base_url"],
                "wire_api": payload["wire_api"],
                "model": payload["model"],
                "review_model": payload["review_model"],
                "continuation_mode": payload["continuation_mode"],
                "api_key": "",
                "api_key_present": True,
                "api_key_source": "override",
            },
            "version": "v0.2.1",
            "revision": "2cb6e87",
        }
        app.reset_provider_settings = lambda: {  # type: ignore[method-assign]
            "saved": False,
            "provider_source": "codex",
            "override_exists": False,
            "override_path": ".sagaquill/provider.json",
            "effective": {
                "base_url": "https://relay.example.com",
                "wire_api": "responses",
                "model": "gpt-test",
                "review_model": "gpt-review",
                "continuation_mode": "replay",
                "api_key_present": True,
                "api_key_source": "codex",
            },
            "form": {
                "base_url": "https://relay.example.com",
                "wire_api": "responses",
                "model": "gpt-test",
                "review_model": "gpt-review",
                "continuation_mode": "replay",
                "api_key": "",
                "api_key_present": True,
                "api_key_source": "codex",
            },
            "version": "v0.2.1",
            "revision": "2cb6e87",
        }
        app.test_provider = lambda payload: {  # type: ignore[method-assign]
            "ok": True,
            "elapsed_ms": 123,
            "reply": "OK",
            "resolved": {
                "base_url": payload["base_url"],
                "wire_api": payload["wire_api"],
                "model": payload["model"],
                "review_model": payload["review_model"],
                "continuation_mode": payload["continuation_mode"],
            },
        }
        app.import_batch_csv = lambda payload: {  # type: ignore[method-assign]
            "batch_id": "batch-1",
            "name": payload.get("batch_name") or "批次",
            "status": "draft",
            "paused": False,
            "max_concurrent": payload.get("max_concurrent") or 2,
            "counts": {"total": 1, "selected": 1, "draft": 1, "queued": 0, "launching": 0, "running": 0, "paused": 0, "completed": 0, "failed": 0},
            "provider_snapshot": {
                "base_url": "https://custom.example.com/v1",
                "wire_api": "responses",
                "model": "gpt-custom",
                "light_model": "gpt-custom-mini",
                "continuation_mode": "hybrid",
            },
            "config": {"target_total_chars": 12000, "target_chars_per_chapter": 2000, "chapter_count": 6, "volume_count": 1, "ending_mode": "standalone", "pov": "第三人称有限视角"},
            "items": [{"proposal_id": "p-1", "title": "批量测试", "status": "draft", "selected": True}],
            "proposals": [{"proposal_id": "p-1", "title": "批量测试", "row_index": 1, "track": "都市", "platform_fit": "起点", "hook": "一句话钩子", "status": "draft"}],
        }
        app.list_batches = lambda: {  # type: ignore[method-assign]
            "batches": [{
                "batch_id": "batch-1",
                "name": "批次",
                "status": "running",
                "paused": False,
                "max_concurrent": 2,
                "counts": {"total": 1, "selected": 1, "draft": 0, "queued": 0, "launching": 0, "running": 1, "paused": 0, "completed": 0, "failed": 0},
                "provider_snapshot": {"model": "gpt-custom", "light_model": "gpt-custom-mini", "continuation_mode": "hybrid"},
                "config": {"target_total_chars": 12000, "target_chars_per_chapter": 2000, "chapter_count": 6, "volume_count": 1, "ending_mode": "standalone", "pov": "第三人称有限视角"},
                "items": [],
            }]
        }
        app.batch_snapshot = lambda batch_id: {  # type: ignore[method-assign]
            "batch_id": batch_id,
            "name": "批次",
            "status": "running",
            "paused": False,
            "max_concurrent": 2,
            "counts": {"total": 1, "selected": 1, "draft": 0, "queued": 0, "launching": 0, "running": 1, "paused": 0, "completed": 0, "failed": 0},
            "provider_snapshot": {"model": "gpt-custom", "light_model": "gpt-custom-mini", "continuation_mode": "hybrid"},
            "config": {"target_total_chars": 12000, "target_chars_per_chapter": 2000, "chapter_count": 6, "volume_count": 1, "ending_mode": "standalone", "pov": "第三人称有限视角"},
            "items": [{"proposal_id": "p-1", "title": "批量测试", "status": "running", "selected": True, "job_id": "job-1"}],
            "proposals": [{"proposal_id": "p-1", "title": "批量测试", "row_index": 1, "track": "都市", "platform_fit": "起点", "hook": "一句话钩子", "status": "running"}],
            "source_name": "batch.csv",
        }
        app.launch_batch = lambda batch_id, payload: app.batch_snapshot(batch_id)  # type: ignore[method-assign]
        app.pause_batch = lambda batch_id: app.batch_snapshot(batch_id) | {"status": "paused", "paused": True}  # type: ignore[method-assign]
        app.resume_batch = lambda batch_id, payload=None: app.batch_snapshot(batch_id)  # type: ignore[method-assign]
        app.retry_failed_batch = lambda batch_id, payload=None: app.batch_snapshot(batch_id)  # type: ignore[method-assign]
        app.delete_batch = lambda batch_id: {"deleted": True, "batch": {"batch_id": batch_id}}  # type: ignore[method-assign]
        app.batch_export = lambda batch_id: {"batch_id": batch_id, "counts": {"total": 1, "completed": 0, "failed": 0}}  # type: ignore[method-assign]
        app.create_job = lambda payload: {  # type: ignore[method-assign]
            "job_id": "job-1",
            "title": payload["title"],
            "status": "queued",
            "step": "queued",
            "message": "任务已进入队列。",
            "output_dir": "runs/test",
            "log": [],
        }
        app.list_jobs = lambda include_hidden=False, job_kind="all": {  # type: ignore[method-assign]
            "jobs": [{"job_id": "job-1", "title": "测试小说", "status": "queued", "step": "queued", "output_dir": "runs/test"}],
            "hidden_count": 0,
            "include_hidden": include_hidden,
            "job_kind": job_kind,
        }
        app.pause_job = lambda job_id: {  # type: ignore[method-assign]
            "job_id": job_id,
            "title": "测试小说",
            "status": "paused",
            "step": "paused",
            "message": "已暂停任务。",
            "output_dir": "runs/test",
            "log": [],
        }
        app.hide_job = lambda job_id: {  # type: ignore[method-assign]
            "job_id": job_id,
            "title": "测试小说",
            "status": "paused",
            "step": "paused",
            "hidden": True,
            "message": "已隐藏任务。",
            "output_dir": "runs/test",
            "log": [],
        }
        app.delete_job = lambda job_id, *, confirm_title, confirm_job_id: {  # type: ignore[method-assign]
            "deleted": True,
            "job": {"job_id": job_id, "title": confirm_title, "status": "paused"},
            "confirm_job_id": confirm_job_id,
        }
        app.open_output_dir = lambda job_id: {  # type: ignore[method-assign]
            "opened": True,
            "job_id": job_id,
            "title": "测试小说",
            "output_dir": "runs/test",
        }
        app.resume_job = lambda job_id, payload=None: {  # type: ignore[method-assign]
            "job_id": job_id,
            "title": "测试小说",
            "status": "running",
            "step": "resume",
            "message": "从已写入产物恢复运行。",
            "output_dir": "runs/test",
            "log": [],
        }
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_port}"
            html = urllib.request.urlopen(f"{base}/", timeout=5).read().decode("utf-8")
            self.assertIn("SagaQuill", html)
            self.assertIn("version-tag", html)
            self.assertIn("批量控制台", html)
            info = json.loads(urllib.request.urlopen(f"{base}/api/info", timeout=5).read().decode("utf-8"))
            self.assertEqual(info["version"], "v0.2.1")
            provider = json.loads(urllib.request.urlopen(f"{base}/api/provider", timeout=5).read().decode("utf-8"))
            self.assertEqual(provider["effective"]["model"], "gpt-test")
            batches = json.loads(urllib.request.urlopen(f"{base}/api/batches", timeout=5).read().decode("utf-8"))
            self.assertEqual(batches["batches"][0]["status"], "running")
            template = json.loads(urllib.request.urlopen(f"{base}/api/template", timeout=5).read().decode("utf-8"))
            self.assertIn("title", template)
            self.assertIn("preset_catalog", template)
            self.assertIn("audience_presets", template["preset_catalog"])
            self.assertIn("style_presets", template["preset_catalog"])

            provider_save_request = urllib.request.Request(
                f"{base}/api/provider",
                data=json.dumps(
                    {
                        "base_url": "https://custom.example.com/v1",
                        "wire_api": "responses",
                        "model": "gpt-custom",
                        "review_model": "gpt-custom-review",
                        "continuation_mode": "replay",
                        "api_key": "secret",
                    }
                ).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            provider_saved = json.loads(urllib.request.urlopen(provider_save_request, timeout=5).read().decode("utf-8"))
            self.assertTrue(provider_saved["saved"])
            self.assertEqual(provider_saved["effective"]["model"], "gpt-custom")

            provider_test_request = urllib.request.Request(
                f"{base}/api/provider/test",
                data=json.dumps(
                    {
                        "base_url": "https://custom.example.com/v1",
                        "wire_api": "responses",
                        "model": "gpt-custom",
                        "review_model": "gpt-custom-review",
                        "continuation_mode": "replay",
                        "api_key": "secret",
                    }
                ).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            provider_tested = json.loads(urllib.request.urlopen(provider_test_request, timeout=5).read().decode("utf-8"))
            self.assertTrue(provider_tested["ok"])
            self.assertEqual(provider_tested["reply"], "OK")

            batch_import_request = urllib.request.Request(
                f"{base}/api/batches/import-csv",
                data=json.dumps(
                    {
                        "csv_text": "编号,书名,赛道,平台适配,一句话钩子,故事核心\\n1,批量测试,都市,起点,一句话钩子,核心",
                        "batch_name": "批次",
                        "max_concurrent": 2,
                    }
                ).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            imported = json.loads(urllib.request.urlopen(batch_import_request, timeout=5).read().decode("utf-8"))
            self.assertEqual(imported["batch_id"], "batch-1")

            batch_launch_request = urllib.request.Request(
                f"{base}/api/batches/batch-1/launch",
                data=json.dumps({"selected_proposal_ids": ["p-1"]}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            launched_batch = json.loads(urllib.request.urlopen(batch_launch_request, timeout=5).read().decode("utf-8"))
            self.assertEqual(launched_batch["batch_id"], "batch-1")

            provider_reset_request = urllib.request.Request(
                f"{base}/api/provider/reset",
                data=b"{}",
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            provider_reset = json.loads(urllib.request.urlopen(provider_reset_request, timeout=5).read().decode("utf-8"))
            self.assertFalse(provider_reset["override_exists"])

            request = urllib.request.Request(
                f"{base}/api/jobs",
                data=json.dumps({"title": "测试小说"}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            response = urllib.request.urlopen(request, timeout=5)
            created = json.loads(response.read().decode("utf-8"))
            self.assertEqual(response.status, 201)
            self.assertEqual(created["job_id"], "job-1")

            jobs = json.loads(urllib.request.urlopen(f"{base}/api/jobs", timeout=5).read().decode("utf-8"))
            self.assertEqual(jobs["jobs"][0]["title"], "测试小说")

            pause_request = urllib.request.Request(f"{base}/api/jobs/job-1/pause", data=b"{}", headers={"Content-Type": "application/json"}, method="POST")
            paused = json.loads(urllib.request.urlopen(pause_request, timeout=5).read().decode("utf-8"))
            self.assertEqual(paused["status"], "paused")

            resume_request = urllib.request.Request(f"{base}/api/jobs/job-1/resume", data=b"{}", headers={"Content-Type": "application/json"}, method="POST")
            resumed = json.loads(urllib.request.urlopen(resume_request, timeout=5).read().decode("utf-8"))
            self.assertEqual(resumed["step"], "resume")

            hide_request = urllib.request.Request(f"{base}/api/jobs/job-1/hide", data=b"{}", headers={"Content-Type": "application/json"}, method="POST")
            hidden = json.loads(urllib.request.urlopen(hide_request, timeout=5).read().decode("utf-8"))
            self.assertTrue(hidden["hidden"])

            delete_request = urllib.request.Request(
                f"{base}/api/jobs/job-1/delete",
                data=json.dumps({"confirm_title": "测试小说", "confirm_job_id": "job-1"}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            deleted = json.loads(urllib.request.urlopen(delete_request, timeout=5).read().decode("utf-8"))
            self.assertTrue(deleted["deleted"])

            open_folder_request = urllib.request.Request(
                f"{base}/api/jobs/job-1/open-folder",
                data=b"{}",
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            opened = json.loads(urllib.request.urlopen(open_folder_request, timeout=5).read().decode("utf-8"))
            self.assertTrue(opened["opened"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
