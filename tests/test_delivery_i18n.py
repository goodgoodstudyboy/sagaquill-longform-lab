from __future__ import annotations

import json
import shutil
import uuid
import zipfile
from pathlib import Path
from unittest import TestCase

from sagaquill.delivery import build_delivery_artifacts
from sagaquill.models import (
    BookOutline,
    BookPackage,
    ChapterOutlineItem,
    ChapterPlan,
    ChapterResult,
    ContinuityUpdate,
    FinalReview,
    LocalQualityReport,
    ProjectSpec,
    ReviewFeedback,
    SceneCard,
    VolumeBlueprint,
)
from sagaquill.pipeline import NovelPipeline


class DeliveryI18nTests(TestCase):
    def test_english_output_uses_non_chinese_delivery_shell(self) -> None:
        spec = _english_spec()
        chapter = _chapter_result()
        book_outline = BookOutline(
            title=spec.title,
            one_line_summary="A courier takes supernatural final deliveries.",
            act_structure=["Launch the route"],
            volumes=[
                VolumeBlueprint(
                    index=1,
                    start_chapter=1,
                    end_chapter=1,
                    title="Night Route",
                    role="opening",
                    central_question="Who ordered the last delivery?",
                    escalation="the address changes",
                    emotional_shift="from survival to agency",
                )
            ],
        )
        package = BookPackage(
            title=spec.title,
            genre=spec.genre,
            audience=spec.audience,
            tone=spec.tone,
            protagonist=spec.protagonist,
            total_chars=200,
            chapter_count=1,
            volume_count=1,
            final_score=91,
            final_passed=True,
            factual_summary="A courier accepts a haunted order and survives the first address.",
            marketing_blurb="Every last delivery pays in money, fear, and secrets.",
            catalog=[
                {
                    "volume_index": 1,
                    "title": "Night Route",
                    "chapter_range": [1, 1],
                    "chapters": [{"index": 1, "title": chapter.title}],
                }
            ],
            output_language="en",
        )

        plain = NovelPipeline.__new__(NovelPipeline)._assemble_plain_novel(spec, [chapter])
        self.assertIn("Chapter 1: The Last Order", plain)
        self.assertNotIn("第1章", plain)

        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"delivery-i18n-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            manifest = build_delivery_artifacts(
                temp_dir,
                spec=spec,
                book_outline=book_outline,
                chapters=[chapter],
                book_package=package,
                final_review=FinalReview(True, 91, ["complete"], [], [], "passed"),
                total_chars=200,
                quality_report={
                    "status": "pass",
                    "score": 91,
                    "policy_version": "test",
                    "summary": "No blocking issues.",
                    "project": {"title": spec.title},
                    "scorecard": [],
                    "checks": [],
                    "rules": [],
                    "auto_repair_log": [],
                },
            )
            toc = (temp_dir / "delivery" / "table-of-contents.md").read_text(encoding="utf-8")
            guide = (temp_dir / "delivery" / "submission-guide.md").read_text(encoding="utf-8")
            manifest_payload = json.loads((temp_dir / "delivery" / "delivery-manifest.json").read_text(encoding="utf-8"))
            epub_path = temp_dir / "delivery" / manifest["files"]["epub"]

            self.assertEqual(manifest_payload["output_language"], "en")
            self.assertIn("Table Of Contents", toc)
            self.assertIn("Volume 1: Night Route", toc)
            self.assertIn("Chapter 1: The Last Order", toc)
            self.assertIn("Submission Guide", guide)
            self.assertIn("- Output language: en", guide)
            self.assertIn("quality-report.md", guide)
            self.assertEqual(manifest_payload["files"]["quality_report"], "quality-report.md")
            self.assertTrue((temp_dir / "delivery" / "quality-report.md").exists())
            with zipfile.ZipFile(epub_path) as archive:
                content_opf = archive.read("OEBPS/content.opf").decode("utf-8")
                nav = archive.read("OEBPS/nav.xhtml").decode("utf-8")
            self.assertIn("<dc:language>en</dc:language>", content_opf)
            self.assertIn('lang="en"', nav)
            self.assertIn("Chapter 1: The Last Order", nav)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_common_non_english_languages_use_localized_delivery_shell(self) -> None:
        cases = [
            ("ja", "第1章", "第1巻", "目次", "提出ガイド"),
            ("ko", "1장", "1권", "목차", "제출 안내"),
            ("es", "Capítulo 1", "Volumen 1", "Índice", "Guía de entrega"),
            ("fr", "Chapitre 1", "Volume 1", "Table des matières", "Guide de livraison"),
            ("de", "Kapitel 1", "Band 1", "Inhaltsverzeichnis", "Übergabeanleitung"),
        ]
        for language, chapter_label, volume_label, toc_label, guide_label in cases:
            with self.subTest(language=language):
                spec = _english_spec()
                spec.output_language = language
                package = BookPackage(
                    title=spec.title,
                    genre=spec.genre,
                    audience=spec.audience,
                    tone=spec.tone,
                    protagonist=spec.protagonist,
                    total_chars=200,
                    chapter_count=1,
                    volume_count=1,
                    final_score=91,
                    final_passed=True,
                    factual_summary="Localized summary.",
                    marketing_blurb="Localized blurb.",
                    catalog=[
                        {
                            "volume_index": 1,
                            "title": "Night Route",
                            "chapter_range": [1, 1],
                            "chapters": [{"index": 1, "title": "The Last Order"}],
                        }
                    ],
                    output_language=language,
                )
                chapter = _chapter_result()
                book_outline = BookOutline(
                    title=spec.title,
                    one_line_summary="A courier takes supernatural final deliveries.",
                    act_structure=["Launch the route"],
                    volumes=[
                        VolumeBlueprint(
                            index=1,
                            start_chapter=1,
                            end_chapter=1,
                            title="Night Route",
                            role="opening",
                            central_question="Who ordered the last delivery?",
                            escalation="the address changes",
                            emotional_shift="from survival to agency",
                        )
                    ],
                )

                plain = NovelPipeline.__new__(NovelPipeline)._assemble_plain_novel(spec, [chapter])
                summary = NovelPipeline.__new__(NovelPipeline)._render_book_summary(package)
                temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"delivery-i18n-{language}-{uuid.uuid4().hex}"
                temp_dir.mkdir(parents=True, exist_ok=True)
                try:
                    build_delivery_artifacts(
                        temp_dir,
                        spec=spec,
                        book_outline=book_outline,
                        chapters=[chapter],
                        book_package=package,
                        final_review=FinalReview(True, 91, ["complete"], [], [], "passed"),
                        total_chars=200,
                    )
                    toc = (temp_dir / "delivery" / "table-of-contents.md").read_text(encoding="utf-8")
                    guide = (temp_dir / "delivery" / "submission-guide.md").read_text(encoding="utf-8")
                finally:
                    shutil.rmtree(temp_dir, ignore_errors=True)

                self.assertIn(chapter_label, plain)
                self.assertIn(chapter_label, summary)
                self.assertIn(volume_label, toc)
                self.assertIn(toc_label, toc)
                self.assertIn(guide_label, guide)
                if language != "en":
                    self.assertNotIn("Chapter 1:", plain)
                    self.assertNotIn("Table Of Contents", toc)


def _english_spec() -> ProjectSpec:
    return ProjectSpec(
        title="Night Courier",
        genre="urban fantasy",
        audience="web fiction readers",
        tone="fast, concrete, suspenseful",
        premise="A courier only delivers final orders to haunted addresses.",
        theme="ordinary work under extraordinary pressure",
        hook="The last order pays ten times the fee, if the courier survives.",
        setting="a rain-soaked city with cursed delivery zones",
        protagonist="Mara Finch",
        outline_hint="Each delivery reveals a larger route.",
        world_hint="Rules must be clear and costly.",
        ending_mode="standalone",
        pov="third person limited",
        target_total_chars=200,
        target_chars_per_chapter=200,
        chapter_count=1,
        volume_count=1,
        chapters_per_volume=1,
        output_language="en",
    )


def _chapter_result() -> ChapterResult:
    outline = ChapterOutlineItem(
        index=1,
        volume_index=1,
        title="The Last Order",
        purpose="open the haunted delivery route",
        conflict="the address changes after pickup",
        beat_summary="Mara accepts a final order and reaches the first cursed door.",
        ending_note="the receipt writes back",
        pov="third person limited",
        closing_mode="chapter_hook",
    )
    plan = ChapterPlan(
        chapter_index=1,
        chapter_title=outline.title,
        purpose=outline.purpose,
        continuity_targets=["route"],
        opening_image="rain on a delivery bag",
        closing_image="a receipt writing itself",
        closing_mode="chapter_hook",
        scenes=[
            SceneCard(
                scene_index=1,
                location="noodle shop doorway",
                goal="pick up the order",
                conflict="the customer is already dead",
                turn="Mara takes the receipt anyway",
            )
        ],
    )
    quality = LocalQualityReport(True, 90, [], ["clear hook"], "solid", {"chars": 200})
    return ChapterResult(
        index=1,
        volume_index=1,
        title=outline.title,
        outline_item=outline,
        draft="Rain needled the courier bag when Mara took the package. The receipt named an address that had burned down three years ago.",
        plan=plan,
        review=ReviewFeedback(True, 90, ["clear hook"], [], [], "passed"),
        local_quality=quality,
        continuity=ContinuityUpdate(1, "Mara takes the first cursed order.", ["route"], [], [], [], [], []),
        attempts=1,
    )
