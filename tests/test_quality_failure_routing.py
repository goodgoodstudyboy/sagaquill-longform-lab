from __future__ import annotations

import unittest

import sagaquill.pipeline as pipeline_module
from sagaquill.models import LocalQualityReport, ReviewFeedback


class QualityFailureRoutingTests(unittest.TestCase):
    def test_placeholder_failure_prefers_cleanup_then_targeted_fix(self) -> None:
        local = LocalQualityReport(
            passed=False,
            score=75,
            issues=["出现占位词或未完成痕迹。"],
            strengths=[],
            short_summary="本地检查发现可读性风险。",
            metrics={"placeholder_hits": ["占位"]},
        )
        review = ReviewFeedback(
            passed=False,
            score=84,
            strengths=[],
            issues=["制度后果利用度略不足。"],
            required_fixes=["清除正文中的占位词。", "增强制度后果的现实作用。"],
            short_summary="章节主体成立，但仍需修正。",
        )

        instructions = pipeline_module._quality_failure_fix_instructions(review, local)

        self.assertEqual(instructions[0][0], "chapter_cleanup")
        self.assertEqual(instructions[1][0], "chapter_targeted_fix")

    def test_structural_failures_skip_targeted_fix(self) -> None:
        local = LocalQualityReport(
            passed=False,
            score=68,
            issues=["近期同一推进簇内功能重复。"],
            strengths=[],
            short_summary="本地检查发现结构风险。",
            metrics={"propulsion_hard_fail": True},
        )
        review = ReviewFeedback(
            passed=False,
            score=80,
            strengths=[],
            issues=["近期推进同构明显，需要重排结构。"],
            required_fixes=["重排本章推进结构。"],
            short_summary="需要结构调整。",
        )

        instructions = pipeline_module._quality_failure_fix_instructions(review, local)

        self.assertEqual(instructions, [])


if __name__ == "__main__":
    unittest.main()
