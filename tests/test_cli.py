from __future__ import annotations

import io
import json
import shutil
import unittest
import uuid
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sagaquill.cli import main
from sagaquill.models import GenerationSummary


class CliTests(unittest.TestCase):
    def test_generate_prints_dataclass_summary(self) -> None:
        root = Path.cwd() / "runs" / "test-artifacts" / f"cli-{uuid.uuid4().hex}"
        root.mkdir(parents=True, exist_ok=True)
        spec_path = root / "spec.json"
        output_dir = root / "out"
        spec_path.write_text(
            json.dumps(
                {
                    "title": "测试小说",
                    "genre": "都市奇谭",
                    "audience": "中文读者",
                    "tone": "克制",
                    "premise": "招领员能看见遗失物里的回忆。",
                    "theme": "选择",
                    "hook": "她离弟弟失踪案更近一步。",
                    "setting": "海雾城市",
                    "protagonist": "沈雾",
                    "chapter_count": 1,
                    "target_chars_per_chapter": 120,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        stdout = io.StringIO()
        try:
            with (
                patch(
                    "sagaquill.cli.load_provider_config",
                    return_value=SimpleNamespace(model="gpt-test", light_model="gpt-test-light", review_model="gpt-test"),
                ),
                patch("sagaquill.cli.OpenAICompatibleClient", return_value=object()),
                patch("sagaquill.cli.NovelPipeline") as pipeline_cls,
                redirect_stdout(stdout),
            ):
                pipeline_cls.return_value.run.return_value = GenerationSummary(
                    output_dir=str(output_dir),
                    title="测试小说",
                    chapter_count=1,
                    volume_count=1,
                    total_chars=2048,
                    final_score=92,
                    final_passed=True,
                    final_summary="结构完整，可发布。",
                )

                exit_code = main(
                    [
                        "generate",
                        "--spec",
                        str(spec_path),
                        "--output-dir",
                        str(output_dir),
                        "--no-stream",
                    ]
                )

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["title"], "测试小说")
            self.assertEqual(payload["final_score"], 92)
            self.assertTrue(payload["final_passed"])
            self.assertEqual(payload["volume_count"], 1)
            self.assertEqual(payload["total_chars"], 2048)
        finally:
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
