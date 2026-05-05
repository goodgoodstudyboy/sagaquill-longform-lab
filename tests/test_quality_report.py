from __future__ import annotations

import unittest

from sagaquill.models import (
    CausalityEdge,
    ChapterOutlineItem,
    ChapterPlan,
    ChapterResult,
    CharacterState,
    ContinuityState,
    ContinuityUpdate,
    FinalReview,
    LocalQualityReport,
    PromiseLedgerItem,
    ProjectSpec,
    ReviewFeedback,
)
from sagaquill.quality_report import build_quality_report, render_quality_report_markdown


class QualityReportTests(unittest.TestCase):
    def test_build_quality_report_collects_red_fail_warn_and_repairs(self) -> None:
        spec = ProjectSpec(
            title="质检测试",
            genre="都市悬疑",
            audience="中文读者",
            tone="紧张",
            premise="主角追查旧案。",
            theme="真相",
            hook="账本牵出旧案。",
            setting="旧城",
            protagonist="主角",
            outline_hint="完整闭环。",
            world_hint="设定服务剧情。",
            pov="第三人称有限视角",
            target_total_chars=3000,
            target_chars_per_chapter=1500,
            chapter_count=2,
            volume_count=1,
            chapters_per_volume=2,
            ending_mode="standalone",
        )
        chapter = _chapter(
            1,
            local=LocalQualityReport(
                False,
                62,
                ["出现占位词或未完成痕迹。", "存在重复段落，像是生成时打转。"],
                [],
                "本地检查发现可读性风险。",
                {
                    "placeholder_hits": ["TODO"],
                    "duplicate_paragraphs": 1,
                    "duplicate_sentences": 3,
                    "char_count": 600,
                    "target_chars_min": 1200,
                    "target_chars_max": 1800,
                    "length_hard_fail": True,
                },
            ),
            review=ReviewFeedback(False, 55, [], ["人物动机不够清楚。"], ["补足人物选择。"], "审校未通过。"),
            attempts=3,
        )
        final_review = FinalReview(
            False,
            70,
            [],
            ["结尾闭环不足。"],
            ["重写最终章。"],
            "终审未通过。",
            local_quality=LocalQualityReport(
                False,
                75,
                ["存在重复段落，像是生成时打转。"],
                [],
                "整本本地检查发现风险。",
                {
                    "duplicate_paragraphs": 2,
                    "allowed_duplicate_paragraphs": 0,
                    "placeholder_hits": [],
                },
            ),
        )
        report = build_quality_report(
            spec=spec,
            chapters=[chapter],
            final_review=final_review,
            continuity=ContinuityState(last_chapter_index=1, active_threads=["线索"] * 24),
            promise_ledger=[
                PromiseLedgerItem(
                    promise_id="p1",
                    label="旧案真相",
                    thread="主线",
                    chapter_opened=1,
                    target_volume=1,
                    current_status="open",
                    last_touched_chapter=1,
                    overdue=True,
                    deadline_state="overdue",
                )
            ],
            causality_graph=[
                CausalityEdge(
                    effect_label="主角被追杀",
                    cause="拿到账本",
                    prerequisites=["账本存在"],
                    required_consequences=["追杀升级"],
                    introduced_chapter=1,
                    last_verified_chapter=1,
                )
            ],
            total_chars=1200,
        )

        self.assertEqual(report["status"], "fail")
        self.assertGreater(report["counts"]["red"], 0)
        self.assertGreater(report["counts"]["fail"], 0)
        self.assertTrue(any(item["id"] == "hygiene.placeholder" for item in report["checks"]))
        self.assertTrue(any(item["id"] == "continuity.promise_overdue" for item in report["checks"]))
        self.assertEqual(report["auto_repair_log"][0]["attempts"], 3)

        markdown = render_quality_report_markdown(report, output_language="zh-Hans")
        self.assertIn("质量报告", markdown)
        self.assertIn("红线与失败项", markdown)
        self.assertIn("TODO", markdown)


def _chapter(
    index: int,
    *,
    local: LocalQualityReport,
    review: ReviewFeedback,
    attempts: int = 1,
) -> ChapterResult:
    outline = ChapterOutlineItem(
        index=index,
        volume_index=1,
        title=f"第{index}章",
        purpose="推进主线",
        conflict="阻力",
        beat_summary="主角推进线索。",
        ending_note="留下压力。",
        pov="第三人称有限视角",
        closing_mode="chapter_hook",
    )
    plan = ChapterPlan(
        chapter_index=index,
        chapter_title=outline.title,
        purpose=outline.purpose,
        continuity_targets=["线索"],
        opening_image="开场",
        closing_image="结尾",
        closing_mode="chapter_hook",
        scenes=[],
    )
    return ChapterResult(
        index=index,
        volume_index=1,
        title=outline.title,
        outline_item=outline,
        draft="TODO 正文。",
        plan=plan,
        review=review,
        local_quality=local,
        continuity=ContinuityUpdate(
            index,
            "主角推进线索。",
            ["线索"],
            [],
            ["第一天夜里主角拿到账本。"],
            [CharacterState("主角", "查案", "紧张", "关系变化", "被追杀", "旧案未解")],
            ["继续查"],
            ["账本"],
        ),
        attempts=attempts,
    )


if __name__ == "__main__":
    unittest.main()
