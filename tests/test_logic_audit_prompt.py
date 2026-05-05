from __future__ import annotations

import unittest

from sagaquill.models import (
    BookOutline,
    CausalityEdge,
    ChapterOutlineItem,
    ChapterPlan,
    ChapterResult,
    CharacterProfile,
    CharacterState,
    ContinuityState,
    ContinuityUpdate,
    LogicAuditReport,
    LocalQualityReport,
    PromiseLedgerItem,
    ProgressionLedgerItem,
    ProjectSpec,
    PowerSystemBible,
    ReviewFeedback,
    SceneCard,
    StyleBible,
    LongRangeMemoryUpdate,
    VolumeBlueprint,
    VolumeOutline,
    WorldBible,
)
from sagaquill.prompts import logic_audit_user_prompt, stagnation_judge_user_prompt


def _build_chapter_result(index: int, volume_index: int = 1) -> ChapterResult:
    outline = ChapterOutlineItem(
        index=index,
        volume_index=volume_index,
        title=f"第{index}章",
        purpose="推进主线",
        conflict="产生冲突",
        beat_summary=f"第{index}章摘要",
        ending_note="留下钩子",
        pov="第三人称有限视角",
        closing_mode="chapter_hook",
    )
    plan = ChapterPlan(
        chapter_index=index,
        chapter_title=outline.title,
        purpose=outline.purpose,
        continuity_targets=[f"线索{index}"],
        opening_image="开头",
        closing_image="结尾",
        closing_mode="chapter_hook",
        scenes=[
            SceneCard(
                scene_index=1,
                location="办公室",
                goal="调查",
                conflict="阻碍",
                turn="推进",
            )
        ],
        primary_propulsion="证据推进",
        variation_goal="避免重复",
        term_budget="low",
        theme_visibility="subtext",
        grounding_beat="吃饭",
    )
    review = ReviewFeedback(
        passed=True,
        score=88,
        strengths=["推进成立"],
        issues=[],
        required_fixes=[],
        short_summary="本章通过。",
    )
    local = LocalQualityReport(
        passed=True,
        score=88,
        issues=[],
        strengths=[],
        short_summary="本地通过。",
        metrics={},
    )
    continuity = ContinuityUpdate(
        chapter_index=index,
        chapter_summary=f"第{index}章发生了关键推进。",
        new_threads=[f"新线索{index}"],
        resolved_threads=[],
        timeline_events=[f"事件{index}"],
        character_states=[
            CharacterState(
                name="顾临",
                current_goal="继续调查",
                emotional_state="警觉",
                relationship_shift="关系收紧",
                risk="被盯上",
                unresolved="另一个顾临是谁",
            )
        ],
        next_chapter_targets=[f"继续查第{index}章线索"],
        must_remember=[f"必须记住的第{index}章事实"],
    )
    return ChapterResult(
        index=index,
        volume_index=volume_index,
        title=outline.title,
        outline_item=outline,
        draft=f"这是第{index}章正文。",
        plan=plan,
        review=review,
        local_quality=local,
        continuity=continuity,
        attempts=1,
        long_memory=LongRangeMemoryUpdate(chapter_index=index),
    )


class LogicAuditPromptTests(unittest.TestCase):
    def test_logic_audit_prompt_uses_section_digests_and_trims_ledger(self) -> None:
        spec = ProjectSpec(
            title="测试长篇",
            genre="悬疑",
            audience="男频",
            tone="冷硬",
            premise="前提",
            theme="主题",
            hook="钩子",
            setting="设定",
            protagonist="顾临",
            outline_hint="总纲",
            world_hint="世界观",
            ending_mode="series",
            pov="第三人称有限视角",
            target_total_chars=3_000_000,
            target_chars_per_chapter=3500,
            chapter_count=900,
            volume_count=80,
            chapters_per_volume=12,
        )
        bible = WorldBible(
            title="测试长篇",
            logline="一句话卖点",
            setting_summary="设定摘要",
            core_conflict="核心冲突",
            theme_statement="主题表达",
            narrative_voice=["克制"],
            world_rules=["规则1"],
            chapter_guardrails=["约束1"],
            ending_contract=["收束1"],
            major_threads=["主线1"],
            characters=[
                CharacterProfile(
                    name="顾临",
                    role="主角",
                    goal="查真相",
                    fear="失控",
                    contradiction="理智与偏执",
                    arc="看见真相",
                    public_image="冷静",
                    private_truth="被替换",
                    speaking_style="短句",
                    signature_image="白灯",
                )
            ],
        )
        book_outline = BookOutline(
            title="测试长篇",
            one_line_summary="一句话简介",
            act_structure=["起", "承", "转", "合"],
            volumes=[
                VolumeBlueprint(
                    index=i,
                    start_chapter=(i - 1) * 12 + 1,
                    end_chapter=i * 12,
                    title=f"第{i}卷",
                    role="推进",
                    central_question="问题",
                    escalation="升级",
                    emotional_shift="变化",
                )
                for i in range(1, 8)
            ],
        )
        volume_outline = VolumeOutline(
            volume_index=5,
            title="第五卷",
            goal="卷目标",
            climax="卷高潮",
            carry_over_threads=["延续主线"],
            chapter_targets=[_build_chapter_result(i, 5).outline_item for i in range(49, 61)],
        )
        chapters = [_build_chapter_result(i, 5) for i in range(49, 61)]
        continuity = ContinuityState(
            recent_summaries=[f"摘要{i}" for i in range(1, 10)],
            active_threads=[f"活跃线{i}" for i in range(1, 20)],
            resolved_threads=[f"已解线{i}" for i in range(1, 10)],
            timeline=[f"时间点{i}" for i in range(1, 30)],
            character_states=[
                CharacterState(
                    name="顾临",
                    current_goal="继续调查",
                    emotional_state="警觉",
                    relationship_shift="更紧张",
                    risk="暴露",
                    unresolved="真相未明",
                )
            ],
            must_remember=[f"记忆{i}" for i in range(1, 25)],
            last_volume_index=5,
            last_chapter_index=60,
        )
        promise_ledger = [
            PromiseLedgerItem(
                promise_id=f"promise-{i:03d}",
                label=f"承诺{i}",
                thread="主线",
                chapter_opened=i,
                target_volume=5,
                current_status="advanced" if i % 2 else "open",
                last_touched_chapter=i,
                payoff_requirements=[f"兑现条件{i}"],
                overdue=i % 5 == 0,
                deadline_state="overdue" if i % 5 == 0 else "at_risk" if i % 3 == 0 else "on_track",
            )
            for i in range(1, 25)
        ]
        causality_graph = [
            CausalityEdge(
                effect_label=f"后果{i}",
                cause=f"原因{i}",
                prerequisites=[f"前置{i}"],
                required_consequences=[f"后续{i}"],
                introduced_chapter=i,
                last_verified_chapter=i + 1,
            )
            for i in range(1, 20)
        ]
        prompt = logic_audit_user_prompt(
            spec,
            bible,
            book_outline,
            volume_outline,
            chapters,
            continuity,
            promise_ledger,
            causality_graph,
            previous_audit={
                "passed": True,
                "gate_passed": True,
                "gate_level": "warn",
                "summary": "上一卷逻辑总体稳定。",
                "issues": ["旧问题1", "旧问题2"],
                "watch_items": ["继续盯住A"],
                "required_followups": ["兑现B"],
            },
            ledger_sanity={"total": 24, "overdue": 4},
        )

        self.assertIn("earlier_section_digests", prompt)
        self.assertIn("focused_items", prompt)
        self.assertIn("focused_edges", prompt)
        self.assertIn("focus_window", prompt)
        self.assertEqual(prompt.count('"promise_id": "promise-'), 12)
        self.assertEqual(prompt.count('"effect_label": "后果'), 10)

    def test_logic_audit_prompt_includes_market_profile_guidance(self) -> None:
        spec = ProjectSpec(
            title="番茄测试",
            genre="都市高武",
            audience="番茄大众男频",
            tone="小白快节奏",
            premise="主角接管神税局。",
            theme="活下来",
            hook="高考当天全城扣寿。",
            setting="现代都市",
            protagonist="林渊",
            outline_hint="前期追读优先。",
            world_hint="术语少一点。",
            ending_mode="series",
            pov="第三人称有限视角",
            target_total_chars=2_000_000,
            target_chars_per_chapter=2800,
            chapter_count=720,
            volume_count=60,
            chapters_per_volume=12,
            market_profile="tomato_mass",
        )
        prompt = logic_audit_user_prompt(
            spec,
            WorldBible(
                title="番茄测试",
                logline="一句话卖点",
                setting_summary="设定摘要",
                core_conflict="核心冲突",
                theme_statement="主题表达",
                narrative_voice=["白快狠"],
                world_rules=["规则1"],
                chapter_guardrails=["约束1"],
                ending_contract=["收束1"],
                major_threads=["主线1"],
                characters=[],
            ),
            BookOutline(title="番茄测试", one_line_summary="简介", act_structure=[], volumes=[]),
            VolumeOutline(volume_index=1, title="第一卷", goal="卷目标", climax="卷高潮", carry_over_threads=[], chapter_targets=[]),
            [_build_chapter_result(1)],
            ContinuityState(last_volume_index=1, last_chapter_index=1),
            [],
            [],
        )

        self.assertIn("番茄爆款", prompt)
        self.assertIn("追读", prompt)

    def test_logic_audit_prompt_carries_non_chinese_language_guard(self) -> None:
        spec = ProjectSpec(
            title="English Test",
            genre="urban fantasy",
            audience="webnovel readers",
            tone="fast and concrete",
            premise="A courier delivers haunted final orders.",
            theme="survival and choice",
            hook="Every delivery changes the address.",
            setting="a modern city",
            protagonist="Mara",
            outline_hint="escalate quickly",
            world_hint="rules serve plot",
            ending_mode="series",
            pov="third person limited",
            target_total_chars=2_000_000,
            target_chars_per_chapter=2800,
            chapter_count=720,
            volume_count=60,
            chapters_per_volume=12,
            output_language="en",
        )
        prompt = logic_audit_user_prompt(
            spec,
            WorldBible(
                title="English Test",
                logline="hook",
                setting_summary="setting",
                core_conflict="conflict",
                theme_statement="theme",
                narrative_voice=["fast"],
                world_rules=["rule"],
                chapter_guardrails=["guardrail"],
                ending_contract=["closure"],
                major_threads=["thread"],
                characters=[],
            ),
            BookOutline(title="English Test", one_line_summary="summary", act_structure=[], volumes=[]),
            VolumeOutline(volume_index=1, title="Volume One", goal="goal", climax="climax", carry_over_threads=[], chapter_targets=[]),
            [_build_chapter_result(1)],
            ContinuityState(last_volume_index=1, last_chapter_index=1),
            [],
            [],
        )

        self.assertIn("输出语言要求（English）", prompt)
        self.assertIn("不能中途切回中文", prompt)

    def test_stagnation_judge_prompt_includes_market_profile_guidance(self) -> None:
        spec = ProjectSpec(
            title="番茄测试",
            genre="都市高武",
            audience="番茄大众男频",
            tone="小白快节奏",
            premise="主角接管神税局。",
            theme="活下来",
            hook="高考当天全城扣寿。",
            setting="现代都市",
            protagonist="林渊",
            outline_hint="前期追读优先。",
            world_hint="术语少一点。",
            ending_mode="series",
            pov="第三人称有限视角",
            target_total_chars=2_000_000,
            target_chars_per_chapter=2800,
            chapter_count=720,
            volume_count=60,
            chapters_per_volume=12,
            market_profile="tomato_mass",
            progression_mode="hard_realm_progression",
            progression_flavor="xuanhuan_fast",
            progression_pacing="fast",
        )
        prompt = stagnation_judge_user_prompt(
            spec,
            WorldBible(
                title="番茄测试",
                logline="一句话卖点",
                setting_summary="设定摘要",
                core_conflict="核心冲突",
                theme_statement="主题表达",
                narrative_voice=["白快狠"],
                world_rules=["规则1"],
                chapter_guardrails=["约束1"],
                ending_contract=["收束1"],
                major_threads=["主线1"],
                characters=[],
            ),
            VolumeOutline(volume_index=1, title="第一卷", goal="卷目标", climax="卷高潮", carry_over_threads=[], chapter_targets=[]),
            {"signal_level": "escalation"},
            [{"chapter_index": 1, "summary": "主角查账推进。"}],
            {"last_chapter_index": 1},
            {
                "chapter_index": 2,
                "goal": "继续查账",
                "progression_step_type": "breakthrough",
                "current_tier": "斗者",
                "target_tier": "斗师",
            },
            power_system=PowerSystemBible(
                progression_mode="hard_realm_progression",
                progression_flavor="xuanhuan_fast",
                progression_pacing="fast",
                core_axis="斗气境界",
                progression_contract=["短周期升级兑现"],
            ),
            progression_ledger=[
                ProgressionLedgerItem(
                    milestone_label="斗者到斗师",
                    current_tier="斗者",
                    target_tier="斗师",
                    status="ready",
                    objective="拿到突破火种",
                )
            ],
        )

        self.assertIn("番茄爆款", prompt)
        self.assertIn("回报不足", prompt)
        self.assertIn("硬境界升级", prompt)
        self.assertIn("升级账本（聚焦摘要）", prompt)

    def test_stagnation_judge_prompt_carries_non_chinese_language_guard(self) -> None:
        spec = ProjectSpec(
            title="English Test",
            genre="urban fantasy",
            audience="webnovel readers",
            tone="fast and concrete",
            premise="A courier delivers haunted final orders.",
            theme="survival and choice",
            hook="Every delivery changes the address.",
            setting="a modern city",
            protagonist="Mara",
            outline_hint="escalate quickly",
            world_hint="rules serve plot",
            ending_mode="series",
            pov="third person limited",
            target_total_chars=2_000_000,
            target_chars_per_chapter=2800,
            chapter_count=720,
            volume_count=60,
            chapters_per_volume=12,
            output_language="en",
        )
        prompt = stagnation_judge_user_prompt(
            spec,
            WorldBible(
                title="English Test",
                logline="hook",
                setting_summary="setting",
                core_conflict="conflict",
                theme_statement="theme",
                narrative_voice=["fast"],
                world_rules=["rule"],
                chapter_guardrails=["guardrail"],
                ending_contract=["closure"],
                major_threads=["thread"],
                characters=[],
            ),
            VolumeOutline(volume_index=1, title="Volume One", goal="goal", climax="climax", carry_over_threads=[], chapter_targets=[]),
            {"signal_level": "normal"},
            [{"chapter_index": 1, "summary": "The courier survives."}],
            {"last_chapter_index": 1},
            {"chapter_index": 2, "goal": "keep moving"},
        )

        self.assertIn("输出语言要求（English）", prompt)
        self.assertIn("不能中途切回中文", prompt)


if __name__ == "__main__":
    unittest.main()
