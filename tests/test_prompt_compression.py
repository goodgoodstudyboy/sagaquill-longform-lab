from __future__ import annotations

import unittest

from sagaquill.models import (
    CausalityEdge,
    ChapterOutlineItem,
    ChapterPlan,
    CharacterProfile,
    CharacterState,
    ContinuityState,
    PromiseLedgerItem,
    ProjectSpec,
    SceneCard,
    WorldBible,
)
from sagaquill.prompts import continuity_user_prompt, long_memory_user_prompt


def _spec() -> ProjectSpec:
    return ProjectSpec(
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


def _bible() -> WorldBible:
    return WorldBible(
        title="测试长篇",
        logline="一句话卖点",
        setting_summary="设定摘要",
        core_conflict="核心冲突",
        theme_statement="主题表达",
        narrative_voice=["克制"],
        world_rules=["规则1", "规则2"],
        chapter_guardrails=["约束1", "约束2"],
        ending_contract=["收束1"],
        major_threads=["主线1", "主线2"],
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


def _chapter(index: int = 120) -> ChapterOutlineItem:
    return ChapterOutlineItem(
        index=index,
        volume_index=10,
        title=f"第{index}章",
        purpose="推进主线",
        conflict="外部压力升级",
        beat_summary="主角做出关键决定并暴露新风险。",
        ending_note="留下钩子",
        pov="第三人称有限视角",
        closing_mode="chapter_hook",
        chapter_role="推进章",
        scene_load_score=1.2,
        target_chars=4200,
        target_chars_min=3200,
        target_chars_max=5200,
        must_payoff=["兑现旧承诺"],
    )


def _plan(chapter_index: int = 120) -> ChapterPlan:
    return ChapterPlan(
        chapter_index=chapter_index,
        chapter_title=f"第{chapter_index}章",
        purpose="推进主线",
        continuity_targets=["追查线索", "人物站队变化"],
        opening_image="旧楼走廊",
        closing_image="深夜电话",
        closing_mode="chapter_hook",
        scenes=[
            SceneCard(
                scene_index=1,
                location="办公室",
                goal="核对线索",
                conflict="证词互相冲突",
                turn="发现真正缺口",
                must_include=["共享终端三号"],
            ),
            SceneCard(
                scene_index=2,
                location="旧楼",
                goal="追人",
                conflict="被反制",
                turn="暴露新债务",
            ),
        ],
        primary_propulsion="证据推进",
        variation_goal="避免重复",
        term_budget="low",
        theme_visibility="subtext",
        grounding_beat="夜班盒饭",
        chapter_role="推进章",
        target_chars=4200,
        target_chars_min=3200,
        target_chars_max=5200,
    )


def _continuity_state() -> ContinuityState:
    return ContinuityState(
        recent_summaries=[f"摘要{i}" for i in range(1, 15)],
        active_threads=[f"活跃线{i}" for i in range(1, 18)],
        resolved_threads=[f"已解线{i}" for i in range(1, 12)],
        timeline=[f"时间点{i}" for i in range(1, 40)],
        character_states=[
            CharacterState(
                name=f"角色{i}",
                current_goal="继续调查",
                emotional_state="警觉",
                relationship_shift="关系收紧",
                risk="暴露",
                unresolved="真相未明",
            )
            for i in range(1, 8)
        ],
        must_remember=[f"记忆{i}" for i in range(1, 20)],
        last_volume_index=10,
        last_chapter_index=119,
    )


def _long_draft() -> str:
    paragraphs = []
    for index in range(1, 41):
        paragraphs.append(
            f"第{index}段："
            + "顾临沿着旧楼走廊向前，先核对终端记录，再判断谁在提前擦痕。"
            + ("共享终端三号留下缺口，迫使他在制度风险和私人代价之间做选择。" * 8)
        )
    return "\n\n".join(paragraphs)


class PromptCompressionTests(unittest.TestCase):
    def test_continuity_prompt_uses_runtime_views_and_excerpt(self) -> None:
        draft = _long_draft()
        prompt = continuity_user_prompt(
            _spec(),
            _bible(),
            _chapter(),
            draft,
            _continuity_state(),
        )

        self.assertIn("项目 brief（运行态摘要）", prompt)
        self.assertIn("上一版连续性状态（运行态摘要）", prompt)
        self.assertIn("正文摘录（开头/中段/结尾抽样，不是全文）", prompt)
        self.assertIn("sampled_passages", prompt)
        self.assertLess(len(prompt), len(draft))

    def test_long_memory_prompt_uses_excerpt_and_trims_related_state(self) -> None:
        draft = _long_draft()
        promises = [
            PromiseLedgerItem(
                promise_id=f"promise-{index:03d}",
                label=f"承诺{index}",
                thread="主线",
                chapter_opened=index,
                target_volume=10,
                current_status="advanced" if index % 2 else "open",
                last_touched_chapter=index,
                payoff_requirements=[f"兑现条件{index}"],
                overdue=index % 5 == 0,
                deadline_state="overdue" if index % 5 == 0 else "on_track",
            )
            for index in range(1, 25)
        ]
        causality = [
            CausalityEdge(
                effect_label=f"后果{index}",
                cause=f"原因{index}",
                prerequisites=[f"前置{index}"],
                required_consequences=[f"后续{index}"],
                introduced_chapter=index,
                last_verified_chapter=index + 1,
            )
            for index in range(1, 18)
        ]

        prompt = long_memory_user_prompt(
            _spec(),
            _bible(),
            _chapter(),
            _plan(),
            draft,
            promises,
            causality,
        )

        self.assertIn("章节计划（运行态摘要）", prompt)
        self.assertIn("相关承诺账本摘要", prompt)
        self.assertIn("focused_items", prompt)
        self.assertIn("focused_edges", prompt)
        self.assertIn("正文摘录（开头/中段/结尾抽样，不是全文）", prompt)
        self.assertLessEqual(prompt.count('"promise_id"'), 11)
        self.assertLessEqual(prompt.count('"effect_label"'), 9)
        self.assertLess(len(prompt), len(draft) + 5000)


if __name__ == "__main__":
    unittest.main()
