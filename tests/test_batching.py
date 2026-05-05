from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from sagaquill.batching import create_batch_from_csv, proposal_to_project_input
from sagaquill.models import BatchConfig, ProviderConfig
from sagaquill.server import JobState, SagaQuillApp
from sagaquill.util import slugify


def _fake_provider(*args, **kwargs) -> ProviderConfig:
    return ProviderConfig(
        base_url="https://relay.example.com",
        wire_api="responses",
        api_key="secret",
        model="gpt-flagship",
        review_model="gpt-flagship",
        light_model="gpt-light",
        continuation_mode="hybrid",
    )


class BatchingTests(unittest.TestCase):
    def test_create_batch_from_csv_maps_chinese_columns(self) -> None:
        csv_text = (
            "编号,书名,赛道,平台适配,一句话钩子,故事核心,风格,前30章,卷纲,人物表\n"
            "1,收骨船,都市灵异,起点,南水十三湾收骨,骨船夜航与旧账,潮湿冷硬,前三十章推进,一卷到底,沈雾：收骨人\n"
        )
        batch, proposals, items = create_batch_from_csv(
            csv_text,
            source_name="ideas.csv",
            batch_name="首批提案",
            provider_snapshot={"model": "gpt-flagship"},
            config=BatchConfig(target_total_chars=12000, chapter_count=6, volume_count=1),
        )

        self.assertEqual(batch.name, "首批提案")
        self.assertEqual(len(proposals), 1)
        self.assertEqual(proposals[0].title, "收骨船")
        self.assertEqual(proposals[0].track, "都市灵异")
        self.assertEqual(items[0].status, "draft")
        self.assertTrue(items[0].selected)

    def test_proposal_to_project_input_builds_short_story_defaults(self) -> None:
        csv_text = (
            "编号,书名,赛道,平台适配,一句话钩子,故事核心,风格,前30章,卷纲,人物表\n"
            "1,收骨船,都市灵异,起点,南水十三湾收骨,骨船夜航与旧账,潮湿冷硬,前三十章推进,一卷到底,沈雾：收骨人\n"
        )
        _, proposals, _ = create_batch_from_csv(csv_text, source_name="ideas.csv")
        project_input = proposal_to_project_input(
            proposals[0],
            BatchConfig(
                target_total_chars=12000,
                target_chars_per_chapter=2000,
                chapter_char_tolerance=0.25,
                chapter_count=6,
                volume_count=1,
            ),
        )

        self.assertEqual(project_input.title, "收骨船")
        self.assertEqual(project_input.target_total_chars, 12000)
        self.assertEqual(project_input.chapter_count, 6)
        self.assertEqual(project_input.chapter_char_tolerance, 0.25)
        self.assertTrue(project_input.hook)
        self.assertTrue(project_input.outline_hint)

    def test_proposal_to_project_input_keeps_style_and_market_constraints(self) -> None:
        csv_text = (
            "编号,书名,赛道,平台适配,参考需求,一句话钩子,故事核心,风格\n"
            "1,高武菜市场,都市高武,番茄,要小白要快节奏,别人练刀去武馆他在菜市场杀妖肉,菜市场小工一路砍进高武体系,小白、扎实、烟火气强。\n"
        )
        _, proposals, _ = create_batch_from_csv(csv_text, source_name="ideas.csv")
        project_input = proposal_to_project_input(
            proposals[0],
            BatchConfig(
                target_total_chars=300000,
                target_chars_per_chapter=2500,
                chapter_char_tolerance=0.25,
                chapter_count=120,
                volume_count=8,
            ),
        )

        self.assertEqual(project_input.audience, "番茄")
        self.assertEqual(project_input.tone, "小白、扎实、烟火气强。")
        self.assertIn("小白、扎实、烟火气强。", project_input.style_examples)
        self.assertIn("要小白要快节奏", project_input.style_examples)
        self.assertIn("番茄", project_input.style_examples)

    def test_proposal_to_project_input_batch_trial_defaults_to_series_without_forced_shape(self) -> None:
        csv_text = (
            "编号,书名,赛道,平台适配,一句话钩子,故事核心,风格\n"
            "1,神明寄存处,都市奇幻,番茄,这家寄存处保管的是快失效的神明,失业青年接手夜班寄存处,轻怪谈、强职业感。\n"
        )
        _, proposals, _ = create_batch_from_csv(csv_text, source_name="ideas.csv")
        project_input = proposal_to_project_input(
            proposals[0],
            BatchConfig(
                target_total_chars=2_000_000,
                target_chars_per_chapter=2000,
                chapter_char_tolerance=0.25,
                chapter_count=None,
                volume_count=None,
                ending_mode=None,
                run_to_completion=False,
                pause_at_chars=400000,
            ),
        )

        self.assertEqual(project_input.ending_mode, "series")
        self.assertIsNone(project_input.chapter_count)
        self.assertIsNone(project_input.volume_count)

    def test_proposal_to_project_input_preserves_market_profile(self) -> None:
        csv_text = (
            "编号,书名,赛道,平台适配,一句话钩子,故事核心\n"
            "1,高考当天，我接管了神明税务局,都市高武,番茄,高考日突然被拉去清税,少年接管神明税务局一路查到天庭黑账\n"
        )
        _, proposals, _ = create_batch_from_csv(csv_text, source_name="ideas.csv")
        project_input = proposal_to_project_input(
            proposals[0],
            BatchConfig(
                target_total_chars=3_000_000,
                target_chars_per_chapter=None,
                chapter_count=None,
                volume_count=None,
                market_profile="tomato_mass",
            ),
        )

        self.assertEqual(project_input.market_profile, "tomato_mass")

    def test_proposal_to_project_input_preserves_progression_config(self) -> None:
        csv_text = (
            "编号,书名,赛道,平台适配,一句话钩子,故事核心\n"
            "1,凡人修城记,仙侠,起点,少年从外门开始往上爬,寒门少年靠丹药洞府与宗门考核逐级突破\n"
        )
        _, proposals, _ = create_batch_from_csv(csv_text, source_name="ideas.csv")
        project_input = proposal_to_project_input(
            proposals[0],
            BatchConfig(
                target_total_chars=3_000_000,
                chapter_count=None,
                volume_count=None,
                market_profile="qidian_longform",
                progression_mode="hard_realm_progression",
                progression_flavor="xianxia_steady",
                progression_pacing="slow",
                power_system_hint="练气-筑基-结丹；每次突破都要丹药、洞府和寿元代价。",
            ),
        )

        self.assertEqual(project_input.progression_mode, "hard_realm_progression")
        self.assertEqual(project_input.progression_flavor, "xianxia_steady")
        self.assertEqual(project_input.progression_pacing, "slow")
        self.assertEqual(project_input.power_system_hint, "练气-筑基-结丹；每次突破都要丹药、洞府和寿元代价。")

    def test_proposal_to_project_input_preserves_output_language(self) -> None:
        csv_text = (
            "编号,书名,赛道,平台适配,一句话钩子,故事核心\n"
            "1,Night Courier,urban fantasy,webnovel,last delivery to a haunted address,a courier survives supernatural orders\n"
        )
        _, proposals, _ = create_batch_from_csv(csv_text, source_name="ideas.csv")
        project_input = proposal_to_project_input(
            proposals[0],
            BatchConfig(output_language="en", target_total_chars=800_000),
        )

        self.assertEqual(project_input.output_language, "en")
        self.assertEqual(project_input.pov, "third person limited")

    def test_proposal_to_project_input_keeps_chinese_pov_for_chinese_alias(self) -> None:
        csv_text = (
            "编号,书名,赛道,平台适配,一句话钩子,故事核心\n"
            "1,中文书,都市悬疑,中文读者,主角一路追查旧案,旧案重新浮出水面\n"
        )
        _, proposals, _ = create_batch_from_csv(csv_text, source_name="ideas.csv")
        project_input = proposal_to_project_input(
            proposals[0],
            BatchConfig(output_language="zh-CN", target_total_chars=800_000),
        )

        self.assertEqual(project_input.output_language, "zh-CN")
        self.assertEqual(project_input.pov, "第三人称有限视角")


class BatchRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory(prefix="sagaquill-batch-")
        self.root = Path(self.tempdir.name)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_import_launch_and_queue_respect_batch_concurrency(self) -> None:
        csv_text = (
            "编号,书名,赛道,平台适配,一句话钩子,故事核心\n"
            "1,甲,都市,起点,钩子1,核心1\n"
            "2,乙,都市,起点,钩子2,核心2\n"
            "3,丙,都市,起点,钩子3,核心3\n"
        )
        app = SagaQuillApp(project_root=self.root, start_watchdog=False, batch_global_max_running=3)
        created_jobs: list[tuple[dict[str, object], dict[str, object] | None]] = []
        job_counter = {"value": 0}
        try:
            with patch("sagaquill.server.resolve_provider_config", side_effect=_fake_provider):
                imported = app.import_batch_csv(
                    {
                        "csv_text": csv_text,
                        "source_name": "batch.csv",
                        "max_concurrent": 2,
                        "target_total_chars": 12000,
                        "chapter_count": 6,
                        "volume_count": 1,
                        "provider": {"model": "gpt-flagship", "light_model": "gpt-light", "continuation_mode": "hybrid"},
                    }
                )

            batch_id = imported["batch_id"]

            def fake_create_job(
                payload: dict[str, object],
                *,
                provider_override: dict[str, object] | None = None,
                output_root: Path | None = None,
            ) -> dict[str, object]:
                job_counter["value"] += 1
                job_id = f"job-{job_counter['value']}"
                self.assertIsNotNone(output_root)
                output_dir = (output_root or (self.root / "runs")) / job_id
                output_dir.mkdir(parents=True, exist_ok=True)
                created_jobs.append((dict(payload), dict(provider_override or {})))
                app.jobs[job_id] = app.jobs.get(job_id) or JobState(
                    job_id=job_id,
                    title=str(payload.get("title") or job_id),
                    output_dir=str(output_dir),
                    status="running",
                    created_at=time.time(),
                    updated_at=time.time(),
                    step="chapter_plan",
                    message="生成章节计划。",
                    input_payload=dict(payload),
                    provider_override=dict(provider_override or {}),
                )
                return {
                    "job_id": job_id,
                    "title": payload.get("title"),
                    "status": "running",
                    "output_dir": str(output_dir),
                }

            app._create_job_payload = fake_create_job  # type: ignore[method-assign]
            launched = app.launch_batch(batch_id, {"selected_proposal_ids": [item["proposal_id"] for item in imported["items"]]})

            self.assertEqual(launched["counts"]["running"], 2)
            self.assertEqual(launched["counts"]["queued"], 1)
            self.assertEqual(len(created_jobs), 2)
            self.assertEqual(created_jobs[0][1]["continuation_mode"], "hybrid")
            created_output_dir = Path(app.jobs["job-1"].output_dir)
            self.assertIn(str(self.root / "runs" / "batches"), str(created_output_dir))
            self.assertIn("\\projects\\", str(created_output_dir))

            running_item = next(item for item in app.batch_items[batch_id] if item.job_id == "job-1")
            app.jobs[running_item.job_id].status = "completed"  # type: ignore[index]
            app.jobs[running_item.job_id].updated_at = time.time()  # type: ignore[index]
            output_dir = Path(app.jobs[running_item.job_id].output_dir)  # type: ignore[index]
            (output_dir / "novel.txt").write_text("正文", encoding="utf-8")
            (output_dir / "book-summary.md").write_text("简介", encoding="utf-8")
            (output_dir / "delivery" / "epub").mkdir(parents=True, exist_ok=True)
            (output_dir / "delivery" / "epub" / "demo.epub").write_text("epub", encoding="utf-8")
            (output_dir / "delivery" / "delivery-manifest.json").write_text("{}", encoding="utf-8")

            app._batch_tick()
            snapshot = app.batch_snapshot(batch_id)

            self.assertEqual(snapshot["counts"]["running"], 2)
            self.assertEqual(snapshot["counts"]["queued"], 0)
            self.assertEqual(snapshot["counts"]["completed"], 1)
            self.assertEqual(len(created_jobs), 3)
            delivery_root = Path(snapshot["paths"]["delivery_root"])
            completed_dir = delivery_root / "completed" / f"{slugify(running_item.title)}-job-1"
            self.assertTrue((completed_dir / "novel.txt").exists())
            self.assertTrue((completed_dir / "book-summary.md").exists())
            self.assertTrue((completed_dir / "delivery" / "epub" / "demo.epub").exists())
            self.assertTrue((completed_dir / "delivery" / "delivery-manifest.json").exists())
            self.assertFalse((completed_dir / "delivery-status.json").exists())
        finally:
            app.close()

    def test_resume_batch_applies_current_provider_to_paused_jobs(self) -> None:
        csv_text = (
            "编号,书名,赛道,平台适配,一句话钩子,故事核心\n"
            "1,甲,都市,起点,钩子1,核心1\n"
        )
        app = SagaQuillApp(project_root=self.root, start_watchdog=False, batch_global_max_running=3)
        try:
            with patch("sagaquill.server.resolve_provider_config", side_effect=_fake_provider):
                imported = app.import_batch_csv(
                    {
                        "csv_text": csv_text,
                        "source_name": "batch.csv",
                        "max_concurrent": 1,
                        "target_total_chars": 12000,
                        "chapter_count": 6,
                        "volume_count": 1,
                    }
                )

            batch_id = imported["batch_id"]
            item = app.batch_items[batch_id][0]
            item.status = "paused"
            job_id = "job-paused"
            item.job_id = job_id
            output_dir = self.root / "runs" / "batches" / "tmp" / "projects" / job_id
            (output_dir / "data").mkdir(parents=True, exist_ok=True)
            app.jobs[job_id] = JobState(
                job_id=job_id,
                title=item.title,
                output_dir=str(output_dir),
                status="paused",
                created_at=time.time(),
                updated_at=time.time(),
                step="paused",
                message="已暂停",
                input_payload={"title": item.title},
                provider_override={"base_url": "https://old.example.com", "api_key": "old-secret", "model": "old-model"},
            )
            app._batch_tick = lambda: None  # type: ignore[method-assign]

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
                app.resume_batch(batch_id, {"provider": {"base_url": "https://relay.example.com", "api_key": "new-secret", "model": "gpt-new"}})

            self.assertEqual(app.batches[batch_id].provider_snapshot["api_key"], "new-secret")
            self.assertEqual(app.jobs[job_id].provider_override["api_key"], "new-secret")
            self.assertEqual(app.jobs[job_id].provider_override["model"], "gpt-new")
            snapshot = json.loads((output_dir / "data" / "provider.snapshot.json").read_text(encoding="utf-8"))
            self.assertEqual(snapshot["base_url"], "https://relay.example.com")
            self.assertEqual(snapshot["model"], "gpt-new")
            self.assertNotIn("api_key", snapshot)
        finally:
            app.close()

    def test_import_batch_trial_defaults_to_series_and_clears_shape_when_blank(self) -> None:
        csv_text = (
            "编号,书名,赛道,平台适配,一句话钩子,故事核心\n"
            "1,甲,都市,起点,钩子1,核心1\n"
        )
        app = SagaQuillApp(project_root=self.root, start_watchdog=False, batch_global_max_running=3)
        try:
            with patch("sagaquill.server.resolve_provider_config", side_effect=_fake_provider):
                imported = app.import_batch_csv(
                    {
                        "csv_text": csv_text,
                        "source_name": "batch.csv",
                        "max_concurrent": 1,
                        "target_total_chars": 2_000_000,
                        "target_chars_per_chapter": 2000,
                        "run_to_completion": False,
                        "pause_at_chars": 400000,
                        "chapter_count": None,
                        "volume_count": None,
                        "ending_mode": None,
                    }
                )

            batch = app.batches[imported["batch_id"]]
            self.assertFalse(batch.config.run_to_completion)
            self.assertEqual(batch.config.ending_mode, "series")
            self.assertIsNone(batch.config.chapter_count)
            self.assertIsNone(batch.config.volume_count)
        finally:
            app.close()

    def test_batch_char_limit_pause_exports_unfinished_delivery(self) -> None:
        csv_text = (
            "编号,书名,赛道,平台适配,一句话钩子,故事核心\n"
            "1,甲,都市,起点,钩子1,核心1\n"
        )
        app = SagaQuillApp(project_root=self.root, start_watchdog=False, batch_global_max_running=1)
        try:
            with patch("sagaquill.server.resolve_provider_config", side_effect=_fake_provider):
                imported = app.import_batch_csv(
                    {
                        "csv_text": csv_text,
                        "source_name": "batch.csv",
                        "max_concurrent": 1,
                        "target_total_chars": 1000000,
                        "target_chars_per_chapter": 2000,
                        "chapter_count": 100,
                        "volume_count": 10,
                        "run_to_completion": False,
                        "pause_at_chars": 100,
                    }
                )
            batch_id = imported["batch_id"]
            batch = app.batches[batch_id]
            batch.status = "running"
            batch.paused = False
            item = app.batch_items[batch_id][0]
            item.status = "running"
            item.selected = True
            job_output = self.root / "runs" / "batches" / "demo-batch" / "projects" / "job-1"
            job_output.mkdir(parents=True, exist_ok=True)
            (job_output / "novel.txt").write_text("正文" * 80, encoding="utf-8")
            (job_output / "delivery" / "epub").mkdir(parents=True, exist_ok=True)
            (job_output / "delivery" / "epub" / "demo.epub").write_text("epub", encoding="utf-8")
            app.jobs["job-1"] = JobState(
                job_id="job-1",
                title=item.title,
                output_dir=str(job_output),
                status="running",
                created_at=time.time(),
                updated_at=time.time(),
                step="chapter_draft",
                message="写作中",
                input_payload={"title": item.title},
                provider_override={},
            )
            item.job_id = "job-1"
            item.output_dir = str(job_output)

            app._batch_tick()

            snapshot = app.batch_snapshot(batch_id)
            paused_item = next(current for current in snapshot["items"] if current["proposal_id"] == item.proposal_id)
            self.assertEqual(paused_item["status"], "paused")
            self.assertEqual(paused_item["pause_reason"], "char_limit")
            self.assertGreaterEqual(paused_item["written_chars"], 100)
            self.assertEqual(app.jobs["job-1"].status, "paused")

            delivery_root = Path(snapshot["paths"]["delivery_root"])
            unfinished_dir = delivery_root / "unfinished" / f"{slugify(item.title)}-job-1"
            self.assertTrue((unfinished_dir / "novel.txt").exists())
            self.assertFalse((unfinished_dir / "book-summary.md").exists())
            self.assertFalse((unfinished_dir / "delivery").exists())
            self.assertFalse((unfinished_dir / "delivery-status.json").exists())
            self.assertFalse((unfinished_dir / "README.md").exists())
        finally:
            app.close()

    def test_batch_state_survives_restart(self) -> None:
        csv_text = (
            "编号,书名,赛道,平台适配,一句话钩子,故事核心\n"
            "1,甲,都市,起点,钩子1,核心1\n"
            "2,乙,都市,起点,钩子2,核心2\n"
        )
        with patch("sagaquill.server.resolve_provider_config", side_effect=_fake_provider):
            app = SagaQuillApp(project_root=self.root, start_watchdog=False)
            try:
                imported = app.import_batch_csv({"csv_text": csv_text, "source_name": "batch.csv"})
                batch_id = imported["batch_id"]
            finally:
                app.close()

        recovered = SagaQuillApp(project_root=self.root, start_watchdog=False)
        try:
            snapshot = recovered.batch_snapshot(batch_id)
            self.assertEqual(snapshot["batch_id"], batch_id)
            self.assertEqual(snapshot["counts"]["total"], 2)
        finally:
            recovered.close()

    def test_batch_tick_resumes_interrupted_items_before_launching_new_jobs(self) -> None:
        csv_text = (
            "编号,书名,赛道,平台适配,一句话钩子,故事核心\n"
            "1,甲,都市,起点,钩子1,核心1\n"
            "2,乙,都市,起点,钩子2,核心2\n"
        )
        app = SagaQuillApp(project_root=self.root, start_watchdog=False, batch_global_max_running=2)
        created_jobs: list[str] = []
        resumed_jobs: list[str] = []
        try:
            with patch("sagaquill.server.resolve_provider_config", side_effect=_fake_provider):
                imported = app.import_batch_csv(
                    {
                        "csv_text": csv_text,
                        "source_name": "batch.csv",
                        "max_concurrent": 2,
                    }
                )
            batch_id = imported["batch_id"]
            app.batches[batch_id].status = "running"
            app.batches[batch_id].paused = False
            first_item = app.batch_items[batch_id][0]
            second_item = app.batch_items[batch_id][1]

            interrupted_output_dir = self.root / "runs" / "batches" / "demo-batch" / "projects" / "job-old"
            interrupted_output_dir.mkdir(parents=True, exist_ok=True)
            app.jobs["job-old"] = JobState(
                job_id="job-old",
                title=first_item.title,
                output_dir=str(interrupted_output_dir),
                status="interrupted",
                created_at=time.time(),
                updated_at=time.time(),
                step="continuity",
                message="检测到未完成任务。",
                input_payload={"title": first_item.title},
                provider_override={
                    "base_url": "https://relay.example.com",
                    "wire_api": "responses",
                    "api_key": "secret",
                    "model": "gpt-flagship",
                    "review_model": "gpt-flagship",
                    "light_model": "gpt-light",
                    "continuation_mode": "hybrid",
                },
            )
            first_item.job_id = "job-old"
            first_item.output_dir = str(interrupted_output_dir)
            first_item.status = "paused"
            second_item.job_id = None
            second_item.output_dir = None
            second_item.status = "queued"

            def fake_launch_job(job_id: str, *, resume: bool, step: str, message: str, auto: bool = False, expected_run_token: str | None = None) -> None:
                resumed_jobs.append(job_id)
                app.jobs[job_id].status = "running"
                app.jobs[job_id].step = step
                app.jobs[job_id].message = message
                app.jobs[job_id].updated_at = time.time()

            def fake_create_job(
                payload: dict[str, object],
                *,
                provider_override: dict[str, object] | None = None,
                output_root: Path | None = None,
            ) -> dict[str, object]:
                job_id = "job-new"
                self.assertIsNotNone(output_root)
                output_dir = (output_root or (self.root / "runs")) / job_id
                output_dir.mkdir(parents=True, exist_ok=True)
                created_jobs.append(job_id)
                app.jobs[job_id] = JobState(
                    job_id=job_id,
                    title=str(payload.get("title") or job_id),
                    output_dir=str(output_dir),
                    status="running",
                    created_at=time.time(),
                    updated_at=time.time(),
                    step="chapter_plan",
                    message="生成章节计划。",
                    input_payload=dict(payload),
                    provider_override=dict(provider_override or {}),
                )
                return {
                    "job_id": job_id,
                    "title": payload.get("title"),
                    "status": "running",
                    "output_dir": str(output_dir),
                }

            app._launch_job = fake_launch_job  # type: ignore[method-assign]
            app._create_job_payload = fake_create_job  # type: ignore[method-assign]

            app._batch_tick()

            self.assertEqual(resumed_jobs, ["job-old"])
            self.assertEqual(created_jobs, ["job-new"])
            self.assertEqual(first_item.status, "running")
            self.assertEqual(second_item.status, "running")
        finally:
            app.close()

    def test_load_existing_jobs_recovers_nested_batch_runs(self) -> None:
        batch_root = self.root / "runs" / "batches" / "demo-batch-abc123" / "projects" / "nested-job"
        data_dir = batch_root / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / "project-input.json").write_text(json.dumps({"title": "批次书"}), encoding="utf-8")
        (data_dir / "progress.json").write_text(
            json.dumps(
                {
                    "status": "running",
                    "step": "chapter_plan",
                    "message": "继续中",
                    "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        app = SagaQuillApp(project_root=self.root, start_watchdog=False)
        try:
            self.assertEqual(len(app.jobs), 1)
            recovered = next(iter(app.jobs.values()))
            self.assertIn("\\runs\\batches\\", recovered.output_dir)
            self.assertEqual(recovered.title, "批次书")
        finally:
            app.close()

    def test_import_batch_csv_accepts_local_path(self) -> None:
        csv_path = self.root / "ideas.csv"
        csv_path.write_text(
            "编号,书名,赛道,平台适配,一句话钩子,故事核心\n1,甲,都市,起点,钩子1,核心1\n",
            encoding="utf-8",
        )
        app = SagaQuillApp(project_root=self.root, start_watchdog=False)
        try:
            with patch("sagaquill.server.resolve_provider_config", side_effect=_fake_provider):
                imported = app.import_batch_csv({"csv_path": str(csv_path)})
            self.assertEqual(imported["counts"]["total"], 1)
            self.assertEqual(imported["proposals"][0]["title"], "甲")
        finally:
            app.close()

    def test_import_batch_persists_sanitized_provider_snapshot(self) -> None:
        csv_text = "编号,书名,赛道,平台适配,一句话钩子,故事核心\n1,甲,都市,起点,钩子1,核心1\n"
        app = SagaQuillApp(project_root=self.root, start_watchdog=False)
        try:
            with patch("sagaquill.server.resolve_provider_config", side_effect=_fake_provider):
                imported = app.import_batch_csv(
                    {
                        "csv_text": csv_text,
                        "source_name": "batch.csv",
                        "provider": {
                            "base_url": "https://relay.example.com",
                            "api_key": "secret",
                            "model": "gpt-flagship",
                            "light_model": "gpt-light",
                            "continuation_mode": "hybrid",
                        },
                    }
                )
            batch_file = self.root / ".sagaquill" / "batches" / imported["batch_id"] / "batch.json"
            persisted = json.loads(batch_file.read_text(encoding="utf-8"))
            self.assertNotIn("api_key", persisted["provider_snapshot"])
        finally:
            app.close()
