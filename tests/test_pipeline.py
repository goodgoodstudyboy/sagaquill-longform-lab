from __future__ import annotations

import copy
import shutil
import unittest
import uuid
from pathlib import Path
import json

import sagaquill.pipeline as pipeline_module
from sagaquill.models import ProjectInput
from sagaquill.client import JsonParseModelClientError
from sagaquill.pipeline import NovelPipeline, perform_delivery_cleanup
from sagaquill.models import (
    ChapterOutlineItem,
    ChapterPlan,
    ChapterResult,
    CharacterProfile,
    CharacterVoiceCard,
    CausalityEdge,
    CharacterSeed,
    CharacterState,
    ContinuityState,
    ContinuityUpdate,
    FinalReview,
    LocalQualityReport,
    LongRangeMemoryUpdate,
    PromiseLedgerItem,
    ProjectSpec,
    ReviewFeedback,
    SceneCard,
    StagnationJudgeReview,
    StyleBible,
    StylePassage,
    VolumeOutline,
    WorldBible,
    BookOutline,
    VolumeBlueprint,
    LogicAuditReport,
)
from sagaquill.prompts import chapter_review_user_prompt
from sagaquill.prompts import chapter_plan_user_prompt
from sagaquill.prompts import final_review_user_prompt
from sagaquill.prompts import rewrite_user_prompt


class StubClient:
    def __init__(self, json_payloads, text_payloads):
        self.json_payloads = list(json_payloads)
        self.text_payloads = list(text_payloads)
        self.json_calls = 0
        self.text_calls = 0
        self.models_by_session: dict[str, list[str | None]] = {}
        self.user_prompts_by_session: dict[str, list[str]] = {}
        self.system_prompts_by_session: dict[str, list[str]] = {}

    def generate_json(
        self,
        system_prompt,
        user_prompt,
        *,
        model=None,
        temperature=0.2,
        max_output_tokens=None,
        session_id=None,
        session_max_chars=None,
        provider_tier="flagship",
        stream=False,
        stream_observer=None,
    ):
        key = session_id or "__none__"
        self.models_by_session.setdefault(key, []).append(model)
        self.user_prompts_by_session.setdefault(key, []).append(user_prompt)
        self.system_prompts_by_session.setdefault(key, []).append(system_prompt)
        default_payload = self._default_json_payload(session_id)
        if default_payload is not None:
            self.json_calls += 1
            return default_payload
        if not self.json_payloads:
            raise AssertionError("No JSON payload left for test.")
        self.json_calls += 1
        return self.json_payloads.pop(0)

    def generate_text(
        self,
        system_prompt,
        user_prompt,
        *,
        model=None,
        temperature=0.3,
        max_output_tokens=None,
        json_mode=False,
        session_id=None,
        session_max_chars=None,
        provider_tier="flagship",
        stream=False,
        stream_observer=None,
    ):
        if not self.text_payloads:
            raise AssertionError("No text payload left for test.")
        self.text_calls += 1
        return self.text_payloads.pop(0)

    def reset_session(self, session_id: str) -> None:
        return

    def _default_json_payload(self, session_id: str | None):
        if session_id == "planner-style":
            return {
                "audience_contract": ["读者要快速进入主线。"],
                "tone_targets": ["克制", "具体"],
                "pacing_rules": ["每章都要有实质推进。"],
                "propulsion_rules": ["连续几章不要用同一种推进发动机。"],
                "clarity_rules": ["前段先讲人和局势，再讲制度词。"],
                "dialogue_rules": ["对白短，少废话。"],
                "prose_rules": ["少解释，多动作。"],
                "sensory_rules": ["保留一到两个稳定意象。"],
                "thematic_subtext_rules": ["主题藏在动作和代价里。"],
                "pressure_curve_rules": ["高压段之间要给换气。"],
                "grounding_rules": ["定期给生活落点。"],
                "taboo_phrases": ["作者按", "待续"],
                "sample_passages": [
                    {
                        "label": "默认样例",
                        "use_case": "压低情绪推进",
                        "text": "灯没亮全，话也没说全，先动的是手上的东西。",
                    }
                ],
            }
        if session_id == "planner-voice":
            return {
                "voice_cards": [
                    {
                        "name": "沈雾",
                        "speech_rhythm": "简短",
                        "emotional_expression": "情绪落在动作和停顿里",
                        "sentence_shape": "短句为主",
                        "social_register": "说话会先试探场面，再决定抬不抬杠。",
                        "humor_style": "几乎不开玩笑。",
                        "silence_pattern": "先停一下，再给结论。",
                        "contrast_anchor": "她的冷是收束信息，不是压人。",
                        "common_words": ["先等等"],
                        "tension_triggers": ["家人相关线索"],
                        "forbidden_drifts": ["不能突然滔滔不绝"],
                    }
                ]
            }
        if session_id == "planner-power-system":
            return {
                "progression_mode": "soft_progression",
                "progression_flavor": "",
                "progression_pacing": "steady",
                "core_axis": "主线推进",
                "secondary_axes": ["资源", "人脉"],
                "progression_contract": ["每卷都要有阶段目标和回报。"],
                "realm_ladder": [
                    {
                        "name": "起步阶段",
                        "order": 1,
                        "summary": "先立住生存与主线入场资格。",
                        "signature_capabilities": ["获得进入主线的最低能力。"],
                        "breakthrough_requirements": [{"name": "跨过第一道现实门槛"}],
                    }
                ],
                "resource_axes": [
                    {
                        "name": "主资源",
                        "role": "驱动推进",
                        "early_game": "入场资格",
                        "mid_game": "关键资源",
                        "late_game": "决定性筹码",
                    }
                ],
                "enemy_ladder": [
                    {
                        "name": "第一层阻力",
                        "threat_profile": "现实阻力",
                        "entry_tier": "起步阶段",
                        "ceiling_tier": "起步阶段",
                        "signature_tests": ["先活下来"],
                    }
                ],
                "milestone_plan": [
                    {
                        "phase": "第一阶段",
                        "tier_target": "起步阶段",
                        "resource_goal": "拿到入场资格",
                        "required_breakthrough": "跨过第一道现实门槛",
                        "enemy_band": "第一层阻力",
                        "key_trial": "证明自己能进主线",
                        "payoff": "开启后续长线推进",
                    }
                ],
                "forbidden_shortcuts": ["不能无代价跳阶段。"],
            }
        if session_id == "long-memory":
            return {
                "chapter_index": 0,
                "promise_updates": [],
                "causality_updates": [],
            }
        return None


class PipelineStructureTests(unittest.TestCase):
    def _make_spec(self, **overrides) -> ProjectSpec:
        base = dict(
            title="测试",
            genre="玄幻",
            audience="男频",
            tone="热血",
            premise="主角要一路突破变强。",
            theme="成长",
            hook="开局就遇到突破门槛。",
            setting="修真世界",
            protagonist="少年修士",
            outline_hint="每卷都有明确境界目标。",
            world_hint="宗门、秘境、丹药与试炼并行。",
            ending_mode="series",
            pov="第三人称有限视角",
            target_total_chars=36000,
            target_chars_per_chapter=3000,
            chapter_count=12,
            volume_count=2,
            chapters_per_volume=6,
        )
        base.update(overrides)
        return ProjectSpec(**base)

    def test_derive_structure_uses_non_uniform_volume_targets(self) -> None:
        structure = pipeline_module._derive_structure(
            ProjectInput(
                title="测试",
                target_total_chars=36000,
                target_chars_per_chapter=2000,
                chapter_count=18,
                volume_count=3,
            )
        )

        self.assertEqual(structure["chapter_count"], 18)
        self.assertEqual(structure["volume_count"], 3)
        self.assertEqual(sum(structure["volume_chapter_targets"]), 18)
        self.assertNotEqual(len(set(structure["volume_chapter_targets"])), 1)
        self.assertEqual(structure["chapter_char_tolerance"], 0.25)

    def test_story_driven_counts_treat_user_inputs_as_soft_targets(self) -> None:
        structure = pipeline_module._derive_structure(
            ProjectInput(
                title="测试",
                structure_mode="story_driven",
                target_total_chars=100000,
                target_chars_per_chapter=2000,
                chapter_count=20,
                volume_count=1,
            )
        )

        self.assertNotEqual(structure["chapter_count"], 20)
        self.assertGreater(structure["chapter_count"], 20)
        self.assertNotEqual(structure["volume_count"], 1)
        self.assertEqual(sum(structure["volume_chapter_targets"]), structure["chapter_count"])

    def test_legacy_counts_remain_exact_when_user_sets_them(self) -> None:
        structure = pipeline_module._derive_structure(
            ProjectInput(
                title="测试",
                structure_mode="legacy",
                target_total_chars=100000,
                target_chars_per_chapter=2000,
                chapter_count=20,
                volume_count=1,
            )
        )

        self.assertEqual(structure["chapter_count"], 20)
        self.assertEqual(structure["volume_count"], 1)
        self.assertEqual(structure["volume_chapter_targets"], [20])

    def test_story_driven_derives_adaptive_chapter_target_chars_when_left_blank(self) -> None:
        structure = pipeline_module._derive_structure(
            ProjectInput(
                title="测试",
                structure_mode="story_driven",
                ending_mode="series",
                target_total_chars=2_500_000,
                target_chars_per_chapter=None,
                chapter_count=None,
                volume_count=None,
            )
        )

        self.assertGreaterEqual(structure["target_chars_per_chapter"], 3000)

    def test_market_profile_biases_adaptive_chapter_target_chars(self) -> None:
        qidian = pipeline_module._derive_structure(
            ProjectInput(
                title="起点测试",
                structure_mode="story_driven",
                ending_mode="series",
                market_profile="qidian_longform",
                target_total_chars=2_500_000,
                target_chars_per_chapter=None,
                chapter_count=None,
                volume_count=None,
            )
        )
        tomato = pipeline_module._derive_structure(
            ProjectInput(
                title="番茄测试",
                structure_mode="story_driven",
                ending_mode="series",
                market_profile="tomato_mass",
                target_total_chars=2_500_000,
                target_chars_per_chapter=None,
                chapter_count=None,
                volume_count=None,
            )
        )

        self.assertGreater(qidian["target_chars_per_chapter"], tomato["target_chars_per_chapter"])

    def test_detects_claude_refusal_draft(self) -> None:
        refusal = (
            "我理解这是一个中文网络小说写作任务。但根据我的使用政策，我不能：\n"
            "1. 生成大量创意内容用于商业出版\n"
            "2. 替代人类创作者的核心创作工作\n"
            "我可以提供的替代帮助：写作建议。"
        )
        self.assertTrue(pipeline_module._draft_looks_like_model_refusal(refusal))
        self.assertFalse(pipeline_module._draft_looks_like_model_refusal("林知遥端着饭盆走进食堂，手指伤口隐隐作痛。"))

    def test_detects_tail_that_looks_like_next_chapter_opening(self) -> None:
        draft = (
            "顾闻溪把便签纸放进口袋。\n\n"
            "她知道明天要去找苏曼，把法律顾问的事说清楚。\n\n"
            "第二天早上六点，她从口袋里拿出那半个馒头，慢慢吃完，出门去护理站。"
        )
        self.assertTrue(pipeline_module._draft_tail_looks_like_next_chapter_opening(draft))
        self.assertFalse(pipeline_module._draft_tail_looks_like_next_chapter_opening("她把门关上，靠着墙慢慢坐下。"))

    def test_trim_next_chapter_opening_from_tail_trims_next_day_tail(self) -> None:
        draft = (
            "下午三点半，顾闻溪回到护理站。\n\n"
            "她把便签纸放进口袋，决定明天去找苏曼把法律顾问的事说清楚。\n\n"
            "第二天早上六点，顾闻溪从口袋里拿出那半个馒头，慢慢吃完，出门去护理站。"
        )
        trimmed, changed = pipeline_module._trim_next_chapter_opening_from_tail(draft)
        self.assertTrue(changed)
        self.assertNotIn("第二天早上六点", trimmed)
        self.assertIn("明天去找苏曼", trimmed)

    def test_soft_short_hard_fail_counts_as_semantic_retry_eligible(self) -> None:
        local_quality = LocalQualityReport(
            passed=False,
            score=88,
            issues=["正文严重偏短，当前约 953 字，明显低于番茄模式容忍带下限 2093 字。"],
            strengths=["段落层次基本成立。", "核心角色被明确写入正文。"],
            short_summary="本地检查发现可读性风险。",
            metrics={
                "char_count": 953,
                "length_under_ratio": 0.4553,
                "length_hard_fail": True,
                "procedural_density_hard_fail": False,
                "propulsion_hard_fail": False,
                "ending_voice_hard_fail": False,
            },
        )

        self.assertTrue(pipeline_module._local_quality_allows_semantic_retry(local_quality))
        softened = pipeline_module._soften_anthropic_short_length_failure(local_quality)
        self.assertTrue(softened.passed)
        self.assertTrue(softened.metrics["length_debt"])
        self.assertFalse(softened.metrics["length_hard_fail"])

    def test_detects_malformed_review_for_very_short_but_positive_claude_case(self) -> None:
        local_quality = LocalQualityReport(
            passed=False,
            score=88,
            issues=["正文严重偏短，当前约 803 字，明显低于番茄模式容忍带下限 2508 字。"],
            strengths=["段落层次基本成立。", "核心角色被明确写入正文。"],
            short_summary="本地检查发现可读性风险。",
            metrics={
                "char_count": 803,
                "length_under_ratio": 0.3202,
                "length_hard_fail": True,
                "procedural_density_hard_fail": False,
                "propulsion_hard_fail": False,
                "ending_voice_hard_fail": False,
            },
        )
        review = ReviewFeedback(
            passed=False,
            score=0,
            strengths=[],
            issues=[
                "战术突围的基本逻辑成立，关系压力与撤离执行链条完整。",
                "账本保护压力持续，意志力兑现到位，章尾拉力明确。",
            ],
            required_fixes=[
                "战术突围的基本逻辑成立，关系压力与撤离执行链条完整。",
                "账本保护压力持续，意志力兑现到位，章尾拉力明确。",
            ],
            short_summary="本章可用。",
        )

        self.assertTrue(pipeline_module._local_quality_allows_semantic_retry(local_quality))
        self.assertTrue(pipeline_module._review_feedback_looks_malformed(review, local_quality))
        self.assertTrue(pipeline_module._anthropic_short_chapter_can_soft_pass(review, local_quality))

    def test_detects_anthropic_review_local_divergence_needing_expansion(self) -> None:
        local_quality = LocalQualityReport(
            passed=True,
            score=87,
            issues=["正文偏短，当前约 1761 字；番茄模式建议补一层动作后果、情绪回弹或章尾钩子，但不必因此直接判死。"],
            strengths=["段落层次基本成立。", "核心角色被明确写入正文。"],
            short_summary="本地检查通过。",
            metrics={
                "char_count": 1761,
                "length_debt": True,
                "length_hard_fail": False,
                "procedural_density_hard_fail": False,
                "propulsion_hard_fail": False,
                "ending_voice_hard_fail": False,
            },
        )
        review = ReviewFeedback(
            passed=False,
            score=72,
            strengths=["情感递进自然。", "秘境入口氛围危险感强。"],
            issues=[
                "【硬伤】篇幅严重不足，情感铺垫不够。",
                "【硬伤】秘境入口场景缺少其他选手的具体反应，压迫感不够立体。",
                "【节奏问题】拥抱场景结束后缺少余波反应，情绪落地不够充分。",
            ],
            required_fixes=["补充群像压迫感、情绪反应和章尾牵引。"],
            short_summary="整体可读，但展开明显不够。",
        )

        self.assertTrue(pipeline_module._anthropic_review_local_divergence_needs_expansion(review, local_quality))
        softened = pipeline_module._synthesize_anthropic_expansion_divergence_pass(review, local_quality)
        self.assertTrue(softened.passed)
        self.assertGreaterEqual(softened.score, 88)
        self.assertIn("扩写债务", softened.short_summary)

    def test_detects_anthropic_review_local_divergence_when_local_only_warns_on_length(self) -> None:
        local_quality = LocalQualityReport(
            passed=True,
            score=81,
            issues=["正文略短，当前约 1827 字；番茄模式允许这种紧章，但建议补强余波、回报或章尾牵引。"],
            strengths=["段落层次基本成立。", "本章升级步骤已显式标注。"],
            short_summary="本地检查通过。",
            metrics={
                "char_count": 1827,
                "target_chars_min": 2084,
                "length_warning": True,
                "length_debt": False,
                "length_hard_fail": False,
                "procedural_density_hard_fail": False,
                "propulsion_hard_fail": False,
                "ending_voice_hard_fail": False,
            },
        )
        review = ReviewFeedback(
            passed=False,
            score=74,
            strengths=[
                "醒来过程展示细腻且有层次感。",
                "境界巩固过程展示具体且有感受变化。",
            ],
            issues=[
                "正文严重偏短，必须扩充到2084-3473字区间。",
                "场景4当前状态分析和下一步计划思考严重不足。",
                "场景3恢复验证展示仍不足，监视者反应细节不够。",
            ],
            required_fixes=[
                "扩充场景4目标明确，增加当前状态分析和下一步计划思考。",
                "扩充场景3恢复验证，增加监视者反应细节。",
            ],
            short_summary="整体成立，但展开明显不够。",
        )

        self.assertTrue(pipeline_module._anthropic_review_local_divergence_needs_expansion(review, local_quality))
        self.assertTrue(pipeline_module._review_feedback_is_expansion_only_failure(review, local_quality))

    def test_detects_malformed_review_when_positive_praise_is_duplicated_in_issues(self) -> None:
        local_quality = LocalQualityReport(
            passed=True,
            score=90,
            issues=[],
            strengths=["本地门通过。"],
            short_summary="本地检查通过。",
            metrics={},
        )
        review = ReviewFeedback(
            passed=False,
            score=0,
            strengths=[],
            issues=[
                "核心承诺全部兑现，人物关系推进清晰。",
                "升级收益兑现到位，节奏层次扎实。",
            ],
            required_fixes=[
                "核心承诺全部兑现，人物关系推进清晰。",
                "升级收益兑现到位，节奏层次扎实。",
            ],
            short_summary="本章整体可用。",
        )

        self.assertTrue(pipeline_module._review_feedback_looks_malformed(review, local_quality))

    def test_detects_extreme_underwrite_as_expansion_candidate_below_700_chars(self) -> None:
        local_quality = LocalQualityReport(
            passed=False,
            score=88,
            issues=["正文严重偏短。"],
            strengths=["突破骨架成立。"],
            short_summary="长度不足。",
            metrics={
                "char_count": 525,
                "target_chars_min": 2278,
                "length_hard_fail": True,
                "length_debt": False,
                "procedural_density_hard_fail": False,
                "propulsion_hard_fail": False,
                "ending_voice_hard_fail": False,
            },
        )
        review = ReviewFeedback(
            passed=False,
            score=72,
            strengths=["突破方向成立。"],
            issues=[
                "篇幅严重不足，突破过程、代价与时间压迫都没展开够。",
                "外部锚点与群像反应不够充分。",
            ],
            required_fixes=["补足突破过程、代价、外部反馈与章尾牵引。"],
            short_summary="骨架在，但展开明显不够。",
        )

        self.assertTrue(
            pipeline_module._underwritten_but_structured_needs_expansion(
                "林昼吞下丹药，胸口一热，勉强站稳。",
                review,
                local_quality,
            )
        )
        self.assertTrue(
            pipeline_module._quality_failure_needs_window_repair(
                "林昼吞下丹药，胸口一热，勉强站稳。",
                review,
                local_quality,
            )
        )

    def test_reconcile_committed_run_state_orphans_future_chapter_artifacts(self) -> None:
        output_dir = Path.cwd() / "runs" / "test-artifacts" / f"reconcile-run-{uuid.uuid4().hex[:8]}"
        output_dir.mkdir(parents=True, exist_ok=True)
        try:
            store = pipeline_module.ProjectStore(output_dir)
            store.write_json("data/continuity-state.json", {"last_chapter_index": 0})
            store.write_text("chapters/chapter-02.md", "第二章正文")
            store.write_text("chapters/chapter-03.md", "第三章正文")
            store.write_json("plans/chapter-02.plan.json", {"chapter_index": 2})
            store.write_json("reviews/chapter-02.review.json", {"model": {"passed": True}})
            report = pipeline_module.reconcile_committed_run_state(output_dir)

            self.assertEqual(report["committed_index"], 0)
            self.assertEqual(report["moved_count"], 4)
            self.assertFalse((store.chapter_dir / "chapter-02.md").exists())
            self.assertFalse((store.chapter_dir / "chapter-03.md").exists())
            self.assertTrue((store.orphaned_chapters_dir() / "chapter-02.md").exists())
            self.assertTrue((store.orphaned_chapters_dir() / "chapter-03.md").exists())
            committed = json.loads(store.committed_progress_path().read_text(encoding="utf-8"))
            self.assertEqual(committed["last_committed_chapter_index"], 0)
            self.assertEqual(committed["total_committed_chars"], 0)
        finally:
            shutil.rmtree(output_dir, ignore_errors=True)


class AnthropicExpansionRecoveryTests(unittest.TestCase):
    def _make_spec(self, **overrides) -> ProjectSpec:
        base = dict(
            title="测试",
            genre="都市高武",
            audience="男频",
            tone="热血",
            premise="普通高中生在全民修仙时代靠呼吸法往上爬。",
            theme="普通人也能改命",
            hook="秘境开启前夜，他必须撑过第一次关键补药。",
            setting="全民修仙时代",
            protagonist="陈一川",
            outline_hint="每卷都要有明确升级目标。",
            world_hint="学校、赛场、秘境与家庭回报并行。",
            ending_mode="series",
            pov="第三人称有限视角",
            target_total_chars=50000,
            target_chars_per_chapter=3200,
            chapter_count=16,
            volume_count=2,
            chapters_per_volume=8,
            market_profile="tomato_mass",
            progression_mode="hard_realm_progression",
            progression_flavor="xuanhuan_fast",
            progression_pacing="fast",
        )
        base.update(overrides)
        return ProjectSpec(**base)

    def _make_bible(self) -> WorldBible:
        return WorldBible(
            title="测试",
            logline="一句话简介",
            setting_summary="学校、赛场和秘境并存。",
            core_conflict="普通人如何踩着规则往上爬。",
            theme_statement="普通人也要争口气。",
            narrative_voice=["白", "快", "燃"],
            world_rules=["每次突破都要有资源和代价。"],
            chapter_guardrails=["每章都要有实质推进。"],
            ending_contract=["系列长篇"],
            major_threads=["校赛线", "秘境线"],
            characters=[],
        )

    def test_attempt_quality_failure_recovery_soft_passes_anthropic_expansion_divergence(self) -> None:
        client = StubClient(
            [],
            [
                "扩写后的第二十二章正文（第1轮），补足了群像反应和情绪余波。",
                "扩写后的第二十二章正文（第2轮），补足了群像反应和情绪余波。",
                "扩写后的第二十二章正文（第3轮），补足了群像反应和情绪余波。",
                "扩写后的第二十二章正文（第4轮），补足了群像反应和情绪余波。",
            ],
        )
        client.provider = type(
            "Provider",
            (),
            {
                "wire_api": "anthropic-messages",
                "model": "claude-sonnet-4-5-20250929",
                "light_model": "claude-sonnet-4-5-20250929",
                "review_model": "claude-sonnet-4-5-20250929",
            },
        )()
        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"anthropic-expand-divergence-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        original_analyze = pipeline_module.analyze_chapter
        original_fix_instructions = pipeline_module._quality_failure_fix_instructions
        try:
            pipeline = NovelPipeline(client, temp_dir)
            pipeline._style_bible = StyleBible()
            pipeline._voice_cards = []
            spec = self._make_spec()
            bible = self._make_bible()
            chapter = ChapterOutlineItem(
                22,
                2,
                "秘境开启前夜",
                "卷收尾",
                "补药冲击与秘境压力叠加",
                "陈一川在天台修炼后迎来秘境开启前的情感与危机确认。",
                "他攥紧护身符踏进漩涡。",
                "第三人称有限视角",
                "volume_hook",
                chapter_role="pivot",
                target_chars=3200,
                target_chars_min=2597,
                target_chars_max=4329,
                progression_step_type="train",
                progression_reward="修为提升并完成秘境前心理准备",
                progression_cost="消耗纳灵丹并承担秘境死亡风险",
                current_tier="淬体9层修为900",
                target_tier="淬体9层修为930",
            )
            plan = ChapterPlan(
                22,
                "秘境开启前夜",
                "卷收尾",
                ["秘境线", "情感线"],
                "天台深夜吞丹",
                "他踏进漩涡",
                "volume_hook",
                [SceneCard(1, "天台", "吞丹修炼", "经脉撕裂", "修为涨到930", "train")],
                progression_step_type="train",
                progression_reward="修为涨到930，拿到护身符",
                progression_cost="身体透支，秘境死亡风险临近",
                current_tier="淬体9层修为900",
                target_tier="淬体9层修为930",
            )
            continuity = ContinuityState()
            local_quality = LocalQualityReport(
                passed=True,
                score=87,
                issues=["正文偏短，当前约 1761 字；番茄模式建议补一层动作后果、情绪回弹或章尾钩子，但不必因此直接判死。"],
                strengths=["段落层次基本成立。", "核心角色被明确写入正文。"],
                short_summary="本地检查通过。",
                metrics={
                    "char_count": 1761,
                    "target_chars_min": 2597,
                    "length_debt": True,
                    "length_hard_fail": False,
                    "procedural_density_hard_fail": False,
                    "propulsion_hard_fail": False,
                    "ending_voice_hard_fail": False,
                },
            )
            review = ReviewFeedback(
                passed=False,
                score=72,
                strengths=["纳灵丹使用身体感受落实到位。", "林晓雨情感递进有层次。"],
                issues=[
                    "【硬伤】篇幅严重不足，情感铺垫不够，章末钩子力度不足。",
                    "【硬伤】秘境入口场景缺少其他选手的具体反应，压迫感不够立体。",
                    "【节奏问题】拥抱场景结束后缺少余波反应，情绪落地不够充分。",
                ],
                required_fixes=["补充群像压迫感、情绪反应和章尾牵引。"],
                short_summary="整体可读，但展开明显不够。",
            )

            pipeline_module.analyze_chapter = lambda *_args, **_kwargs: local_quality
            pipeline_module._quality_failure_fix_instructions = lambda *_args, **_kwargs: []
            pipeline._review_chapter = lambda *_args, **_kwargs: review  # type: ignore[method-assign]

            draft, rerun_local, rerun_review, attempts = pipeline._attempt_quality_failure_recovery(
                spec,
                bible,
                chapter,
                plan,
                "原始第22章正文。",
                local_quality,
                review,
                continuity,
                execution_packet={},
                retrieved_memory=[],
                style_memory=[],
                promise_memory=[],
                causality_memory=[],
                logic_audit=None,
                chapter_room={},
                chapter_target_chars=3200,
                character_names=["陈一川", "林晓雨"],
                prior_chapters=[],
                attempts=1,
            )

            self.assertEqual(draft, "扩写后的第二十二章正文（第1轮），补足了群像反应和情绪余波。")
            self.assertTrue(rerun_local.passed)
            self.assertTrue(rerun_review.passed)
            self.assertIn("扩写债务", rerun_review.short_summary)
            self.assertGreaterEqual(attempts, 2)
            self.assertEqual(client.text_calls, 1)
        finally:
            pipeline_module.analyze_chapter = original_analyze
            pipeline_module._quality_failure_fix_instructions = original_fix_instructions
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_attempt_quality_failure_window_repair_repairs_recent_cluster(self) -> None:
        client = StubClient([], [])
        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"quality-window-repair-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            pipeline = NovelPipeline(client, temp_dir)
            spec = self._make_spec()
            bible = self._make_bible()
            book_outline = BookOutline(
                title="测试",
                one_line_summary="一句话简介",
                act_structure=["起", "承", "转", "合"],
                volumes=[VolumeBlueprint(1, 1, 3, "第一卷", "推进", "能否进秘境", "卷末开门", "从普通人被推上去")],
            )
            volume_outline = VolumeOutline(
                volume_index=1,
                title="第一卷",
                goal="进入秘境",
                climax="卷末开门",
                carry_over_threads=["秘境线"],
                chapter_targets=[
                    ChapterOutlineItem(1, 1, "第一章", "铺垫", "测试开局", "活下来", "继续冲", "第三人称有限视角", "chapter_hook"),
                    ChapterOutlineItem(2, 1, "第二章", "逼近", "资源不够", "再拿一层资源", "继续冲", "第三人称有限视角", "chapter_hook"),
                    ChapterOutlineItem(3, 1, "第三章", "卷收尾", "秘境入口压迫感不够", "把入口和情绪都立住", "踏进漩涡", "第三人称有限视角", "volume_hook", chapter_role="pivot"),
                ],
            )
            prior = [
                ChapterResult(
                    index=1,
                    volume_index=1,
                    title="第一章",
                    outline_item=volume_outline.chapter_targets[0],
                    draft="第一章旧稿。",
                    plan=ChapterPlan(1, "第一章", "铺垫", ["秘境线"], "开场", "推进", "chapter_hook", []),
                    review=ReviewFeedback(True, 90, ["通过"], [], [], "通过。"),
                    local_quality=LocalQualityReport(True, 90, [], ["通过"], "通过。", {}),
                    continuity=ContinuityUpdate(1, "第一章摘要", ["秘境线"], [], ["事件1"], [], ["目标1"], []),
                    attempts=1,
                    long_memory=LongRangeMemoryUpdate(chapter_index=1),
                ),
                ChapterResult(
                    index=2,
                    volume_index=1,
                    title="第二章",
                    outline_item=volume_outline.chapter_targets[1],
                    draft="第二章旧稿。",
                    plan=ChapterPlan(2, "第二章", "逼近", ["秘境线"], "开场", "推进", "chapter_hook", []),
                    review=ReviewFeedback(True, 90, ["通过"], [], [], "通过。"),
                    local_quality=LocalQualityReport(True, 90, [], ["通过"], "通过。", {}),
                    continuity=ContinuityUpdate(2, "第二章摘要", ["秘境线"], [], ["事件2"], [], ["目标2"], []),
                    attempts=1,
                    long_memory=LongRangeMemoryUpdate(chapter_index=2),
                ),
            ]
            chapter = volume_outline.chapter_targets[2]
            plan = ChapterPlan(
                3,
                "第三章",
                "卷收尾",
                ["秘境线"],
                "开场",
                "踏进漩涡",
                "volume_hook",
                [SceneCard(1, "秘境门前", "等待开门", "其他选手施压", "他最终跨进去", "volume_hook")],
            )
            local_quality = LocalQualityReport(
                True,
                86,
                [],
                ["正文基础成立。"],
                "本地通过。",
                {"char_count": 1761, "length_debt": True},
            )
            review = ReviewFeedback(
                False,
                0,
                [],
                ["卷收尾兑现到位，秘境入口压迫感清晰。", "群像压力和情绪回弹都已经落地。"],
                ["卷收尾兑现到位，秘境入口压迫感清晰。"],
                "结构化审校异常。",
            )
            repaired_prior = copy.deepcopy(prior[1])
            repaired_prior.draft = "第二章窗口回修稿。"
            repaired_current = ChapterResult(
                index=3,
                volume_index=1,
                title="第三章",
                outline_item=chapter,
                draft="第三章窗口回修稿。",
                plan=plan,
                review=ReviewFeedback(True, 92, ["通过"], [], [], "通过。"),
                local_quality=LocalQualityReport(True, 91, [], ["通过"], "通过。", {"char_count": 2450}),
                continuity=ContinuityUpdate(3, "第三章窗口回修后通过。", [], [], ["事件3"], [], ["目标3"], []),
                attempts=2,
                long_memory=LongRangeMemoryUpdate(chapter_index=3),
            )
            pipeline._repair_chapter_cluster = lambda *_args, **_kwargs: [prior[0], repaired_prior, repaired_current]  # type: ignore[method-assign]
            pipeline._rebuild_continuity_state = lambda *_args, **_kwargs: ContinuityState(last_volume_index=1, last_chapter_index=3)  # type: ignore[method-assign]
            pipeline._rebuild_long_range_state = lambda *_args, **_kwargs: ([], [], [])  # type: ignore[method-assign]
            pipeline._sync_runtime_views = lambda *_args, **_kwargs: None  # type: ignore[method-assign]
            pipeline._write_partial_novel = lambda *_args, **_kwargs: None  # type: ignore[method-assign]

            result = pipeline._attempt_quality_failure_window_repair(
                spec,
                bible,
                chapter,
                plan,
                "第三章失败稿。",
                local_quality,
                review,
                ContinuityState(last_volume_index=1, last_chapter_index=2),
                prior_chapters=prior,
                book_outline=book_outline,
                volume_outline=volume_outline,
                attempts=4,
            )

            self.assertIsNotNone(result)
            self.assertEqual(result.draft, "第三章窗口回修稿。")
            self.assertEqual(prior[1].draft, "第二章窗口回修稿。")
            self.assertTrue((temp_dir / "data" / "progression-ledger.json").exists())
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_generate_chapter_uses_quality_failure_window_repair_before_failing(self) -> None:
        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"generate-chapter-window-repair-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        original_analyze = pipeline_module.analyze_chapter
        try:
            client = StubClient([], ["第二章失败正文。"])
            pipeline = NovelPipeline(client, temp_dir)
            pipeline.max_rewrites = 0
            pipeline._style_bible = StyleBible()
            pipeline._voice_cards = []
            pipeline._build_chapter_room = lambda *_args, **_kwargs: {}  # type: ignore[method-assign]
            pipeline._select_story_memories = lambda *_args, **_kwargs: []  # type: ignore[method-assign]
            pipeline._select_style_memories = lambda *_args, **_kwargs: []  # type: ignore[method-assign]
            pipeline._select_promise_memories = lambda *_args, **_kwargs: []  # type: ignore[method-assign]
            pipeline._select_causality_memories = lambda *_args, **_kwargs: []  # type: ignore[method-assign]
            pipeline._latest_logic_audit_for_volume = lambda *_args, **_kwargs: None  # type: ignore[method-assign]
            spec = self._make_spec(target_total_chars=12000, chapter_count=4, volume_count=1, chapters_per_volume=4)
            bible = self._make_bible()
            book_outline = BookOutline(
                title="测试",
                one_line_summary="一句话简介",
                act_structure=["起", "承", "转", "合"],
                volumes=[VolumeBlueprint(1, 1, 4, "第一卷", "推进", "能否进秘境", "卷末开门", "从普通人被推上去")],
            )
            volume_outline = VolumeOutline(
                volume_index=1,
                title="第一卷",
                goal="进入秘境",
                climax="卷末开门",
                carry_over_threads=["秘境线"],
                chapter_targets=[
                    ChapterOutlineItem(1, 1, "第一章", "铺垫", "测试开局", "活下来", "继续冲", "第三人称有限视角", "chapter_hook"),
                    ChapterOutlineItem(2, 1, "第二章", "卷收尾", "入口压迫感不够", "把入口和情绪立住", "踏进漩涡", "第三人称有限视角", "volume_hook", chapter_role="pivot"),
                ],
            )
            chapter = volume_outline.chapter_targets[1]
            plan = ChapterPlan(
                2,
                "第二章",
                "卷收尾",
                ["秘境线"],
                "开场",
                "踏进漩涡",
                "volume_hook",
                [SceneCard(1, "秘境门前", "等待开门", "其他选手施压", "他最终跨进去", "volume_hook")],
            )
            prior = [
                ChapterResult(
                    index=1,
                    volume_index=1,
                    title="第一章",
                    outline_item=volume_outline.chapter_targets[0],
                    draft="第一章旧稿。",
                    plan=ChapterPlan(1, "第一章", "铺垫", ["秘境线"], "开场", "推进", "chapter_hook", []),
                    review=ReviewFeedback(True, 90, ["通过"], [], [], "通过。"),
                    local_quality=LocalQualityReport(True, 90, [], ["通过"], "通过。", {}),
                    continuity=ContinuityUpdate(1, "第一章摘要", ["秘境线"], [], ["事件1"], [], ["目标1"], []),
                    attempts=1,
                    long_memory=LongRangeMemoryUpdate(chapter_index=1),
                )
            ]
            continuity = pipeline._rebuild_continuity_state(bible, prior)
            failed_local = LocalQualityReport(True, 86, [], ["正文基础成立。"], "本地通过。", {"char_count": 1761, "length_debt": True})
            failed_review = ReviewFeedback(False, 0, [], ["卷收尾兑现到位，秘境入口压迫感清晰。"], ["卷收尾兑现到位，秘境入口压迫感清晰。"], "结构化审校异常。")
            repaired_result = ChapterResult(
                index=2,
                volume_index=1,
                title="第二章",
                outline_item=chapter,
                draft="第二章窗口回修稿。",
                plan=plan,
                review=ReviewFeedback(True, 92, ["通过"], [], [], "通过。"),
                local_quality=LocalQualityReport(True, 91, [], ["通过。"], "通过。", {"char_count": 2400}),
                continuity=ContinuityUpdate(2, "第二章窗口回修后通过。", [], [], ["事件2"], [], ["目标2"], []),
                attempts=3,
                long_memory=LongRangeMemoryUpdate(chapter_index=2),
            )
            window_calls: list[int] = []
            pipeline_module.analyze_chapter = lambda *_args, **_kwargs: failed_local
            pipeline._review_chapter = lambda *_args, **_kwargs: failed_review  # type: ignore[method-assign]
            pipeline._attempt_quality_failure_recovery = lambda *_args, **_kwargs: ("第二章失败正文。", failed_local, failed_review, 2)  # type: ignore[method-assign]
            pipeline._attempt_quality_failure_window_repair = lambda *_args, **_kwargs: (window_calls.append(1) or repaired_result)  # type: ignore[method-assign]

            result = pipeline._generate_chapter(
                spec,
                bible,
                chapter,
                plan,
                continuity,
                prior,
                book_outline=book_outline,
                volume_outline=volume_outline,
            )

            self.assertEqual(result.draft, "第二章窗口回修稿。")
            self.assertEqual(window_calls, [1])
            self.assertEqual((temp_dir / "chapters" / "chapter-02.md").read_text(encoding="utf-8"), "第二章窗口回修稿。")
        finally:
            pipeline_module.analyze_chapter = original_analyze
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_attempt_quality_failure_recovery_continues_truncated_draft(self) -> None:
        client = StubClient([], ["补完后的第82章正文，收束了尾段并补上章尾钩子。"])
        client.provider = type(
            "Provider",
            (),
            {
                "wire_api": "anthropic-messages",
                "model": "claude-sonnet-4-5-20250929",
                "light_model": "claude-sonnet-4-5-20250929",
                "review_model": "claude-sonnet-4-5-20250929",
            },
        )()
        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"anthropic-truncation-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        original_analyze = pipeline_module.analyze_chapter
        original_fix_instructions = pipeline_module._quality_failure_fix_instructions
        try:
            pipeline = NovelPipeline(client, temp_dir)
            pipeline._style_bible = StyleBible()
            pipeline._voice_cards = []
            spec = self._make_spec(target_total_chars=40000, chapter_count=16, volume_count=2, chapters_per_volume=8)
            bible = self._make_bible()
            chapter = ChapterOutlineItem(
                82,
                11,
                "深夜回宿舍",
                "卷收尾",
                "补齐尾段回响",
                "把收款反馈、夜路与章尾钩子接完整。",
                "她把钥匙攥得更紧。",
                "第三人称有限视角",
                "chapter_hook",
                target_chars=2800,
                target_chars_min=1939,
                target_chars_max=3798,
            )
            plan = ChapterPlan(
                82,
                "深夜回宿舍",
                "卷收尾",
                ["家庭线"],
                "夜路回寝",
                "她决定第二天去找苏曼。",
                "chapter_hook",
                [SceneCard(1, "宿舍楼下", "夜路回寝", "钱不够", "她看清下一步", "payoff")],
            )
            continuity = ContinuityState()
            failed_local = LocalQualityReport(
                passed=False,
                score=68,
                issues=["正文严重偏短。"],
                strengths=["冲突骨架成立。"],
                short_summary="本章未完成。",
                metrics={
                    "char_count": 345,
                    "target_chars_min": 1939,
                    "length_hard_fail": True,
                    "length_debt": False,
                    "procedural_density_hard_fail": False,
                    "propulsion_hard_fail": False,
                    "ending_voice_hard_fail": False,
                },
            )
            passed_local = LocalQualityReport(
                passed=True,
                score=90,
                issues=[],
                strengths=["尾段补齐，章尾成立。"],
                short_summary="通过。",
                metrics={
                    "char_count": 2210,
                    "target_chars_min": 1939,
                    "length_hard_fail": False,
                    "length_debt": False,
                    "procedural_density_hard_fail": False,
                    "propulsion_hard_fail": False,
                    "ending_voice_hard_fail": False,
                },
            )
            failed_review = ReviewFeedback(
                passed=False,
                score=40,
                strengths=["前段冲突成立。"],
                issues=["正文在“她算了算，从”处突然中断，后续收尾与章尾钩子缺失。"],
                required_fixes=["从截断处续写，补齐收款反馈、回宿舍、次日动作与章尾钩子。"],
                short_summary="明显截断。",
            )
            passed_review = ReviewFeedback(
                passed=True,
                score=90,
                strengths=["截断处补齐后情绪与钩子都成立。"],
                issues=[],
                required_fixes=[],
                short_summary="通过。",
            )

            def analyze_stub(text: str, *_args, **_kwargs):
                return passed_local if "补完后的第82章正文" in text else failed_local

            pipeline_module.analyze_chapter = analyze_stub
            pipeline_module._quality_failure_fix_instructions = lambda *_args, **_kwargs: []
            pipeline._review_chapter = lambda *_args, **_kwargs: passed_review if "补完后的第82章正文" in _args[4] else failed_review  # type: ignore[method-assign]

            draft, rerun_local, rerun_review, attempts = pipeline._attempt_quality_failure_recovery(
                spec,
                bible,
                chapter,
                plan,
                "她算了算，从",
                failed_local,
                failed_review,
                continuity,
                execution_packet={},
                retrieved_memory=[],
                style_memory=[],
                promise_memory=[],
                causality_memory=[],
                logic_audit=None,
                chapter_room={},
                chapter_target_chars=2800,
                character_names=["顾闻溪"],
                prior_chapters=[],
                attempts=1,
            )

            self.assertEqual(draft, "补完后的第82章正文，收束了尾段并补上章尾钩子。")
            self.assertTrue(rerun_local.passed)
            self.assertTrue(rerun_review.passed)
            self.assertEqual(client.text_calls, 1)
            self.assertGreaterEqual(attempts, 2)
        finally:
            pipeline_module.analyze_chapter = original_analyze
            pipeline_module._quality_failure_fix_instructions = original_fix_instructions
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_attempt_quality_failure_recovery_soft_passes_underwritten_structured_expand(self) -> None:
        client = StubClient(
            [],
            [
                "扩写后的第80章正文，补了更多环境、情绪和尾段回响。",
                "扩写后的第80章正文，补了更多环境、情绪和尾段回响。",
                "扩写后的第80章正文，补了更多环境、情绪和尾段回响。",
                "扩写后的第80章正文，补了更多环境、情绪和尾段回响。",
            ],
        )
        client.provider = type(
            "Provider",
            (),
            {
                "wire_api": "anthropic-messages",
                "model": "claude-sonnet-4-5-20250929",
                "light_model": "claude-sonnet-4-5-20250929",
                "review_model": "claude-sonnet-4-5-20250929",
            },
        )()
        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"anthropic-underwrite-structured-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        original_analyze = pipeline_module.analyze_chapter
        original_fix_instructions = pipeline_module._quality_failure_fix_instructions
        try:
            pipeline = NovelPipeline(client, temp_dir)
            pipeline._style_bible = StyleBible()
            pipeline._voice_cards = []
            spec = self._make_spec(target_total_chars=40000, chapter_count=16, volume_count=2, chapters_per_volume=8)
            bible = self._make_bible()
            chapter = ChapterOutlineItem(
                80,
                10,
                "嫁妆库房前",
                "卷收尾",
                "把压迫感和奶团反应补足",
                "这一章要立住群像压迫、萌宝感与章尾牵引。",
                "她看见奶团手心那枚钥匙发烫。",
                "第三人称有限视角",
                "volume_hook",
                target_chars=2800,
                target_chars_min=2176,
                target_chars_max=3798,
            )
            plan = ChapterPlan(
                80,
                "嫁妆库房前",
                "卷收尾",
                ["萌宝线", "家门反打"],
                "库房门前对峙",
                "奶团把钥匙塞回袖口。",
                "volume_hook",
                [SceneCard(1, "库房门前", "对峙", "嫁妆要被动手脚", "她决定先压住场面", "challenge")],
            )
            continuity = ContinuityState()
            failed_local = LocalQualityReport(
                passed=False,
                score=72,
                issues=["正文严重偏短。"],
                strengths=["冲突骨架成立。"],
                short_summary="长度不足。",
                metrics={
                    "char_count": 807,
                    "target_chars_min": 2176,
                    "length_hard_fail": True,
                    "length_debt": False,
                    "length_under_ratio": 0.62,
                    "procedural_density_hard_fail": False,
                    "propulsion_hard_fail": False,
                    "ending_voice_hard_fail": False,
                },
            )
            failed_review = ReviewFeedback(
                passed=False,
                score=71,
                strengths=["冲突骨架是成立的。", "奶团卖点还在。"],
                issues=[
                    "篇幅严重不足，库房门前的压迫感不够立体。",
                    "苏嬷嬷和众人的反应展开不够充分。",
                    "情绪回弹和章尾牵引都明显不够。",
                ],
                required_fixes=["补足环境压迫、人物反应、萌宝细节和章尾钩子。"],
                short_summary="骨架在，但展开明显不够。",
            )

            pipeline_module.analyze_chapter = lambda *_args, **_kwargs: failed_local
            pipeline_module._quality_failure_fix_instructions = lambda *_args, **_kwargs: []
            pipeline._review_chapter = lambda *_args, **_kwargs: failed_review  # type: ignore[method-assign]

            draft, rerun_local, rerun_review, attempts = pipeline._attempt_quality_failure_recovery(
                spec,
                bible,
                chapter,
                plan,
                "奶团把袖口往里缩了缩，盯着库房门上的锁。",
                failed_local,
                failed_review,
                continuity,
                execution_packet={},
                retrieved_memory=[],
                style_memory=[],
                promise_memory=[],
                causality_memory=[],
                logic_audit=None,
                chapter_room={},
                chapter_target_chars=2800,
                character_names=["奶团", "苏嬷嬷"],
                prior_chapters=[],
                attempts=1,
            )

            self.assertTrue(rerun_local.passed)
            self.assertTrue(rerun_review.passed)
            self.assertTrue(rerun_local.metrics["length_debt"])
            self.assertFalse(rerun_local.metrics["length_hard_fail"])
            self.assertIn("扩写债务", rerun_review.short_summary)
            self.assertEqual(client.text_calls, 1)
            self.assertGreaterEqual(attempts, 2)
        finally:
            pipeline_module.analyze_chapter = original_analyze
            pipeline_module._quality_failure_fix_instructions = original_fix_instructions
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_attempt_quality_failure_recovery_force_expands_warning_divergence_after_fix_loop(self) -> None:
        client = StubClient([], ["强制扩写后的第85章正文，补齐了状态分析、监视反应和章尾牵引。"])
        client.provider = type(
            "Provider",
            (),
            {
                "wire_api": "anthropic-messages",
                "model": "claude-sonnet-4-5-20250929",
                "light_model": "claude-sonnet-4-5-20250929",
                "review_model": "claude-sonnet-4-5-20250929",
            },
        )()
        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"anthropic-force-expand-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        original_analyze = pipeline_module.analyze_chapter
        original_fix_instructions = pipeline_module._quality_failure_fix_instructions
        try:
            pipeline = NovelPipeline(client, temp_dir)
            pipeline._style_bible = StyleBible()
            pipeline._voice_cards = []
            spec = self._make_spec(target_total_chars=40000, chapter_count=16, volume_count=2, chapters_per_volume=8)
            bible = self._make_bible()
            chapter = ChapterOutlineItem(
                85,
                11,
                "醒来后的巩固",
                "卷收尾",
                "把巩固余波和监视反应立住",
                "把境界巩固后的状态分析、监视反应和三日准备立住。",
                "窗外风声更近了一点。",
                "第三人称有限视角",
                "chapter_hook",
                target_chars=2778,
                target_chars_min=2084,
                target_chars_max=3473,
                progression_step_type="consolidate",
            )
            plan = ChapterPlan(
                85,
                "醒来后的巩固",
                "卷收尾",
                ["监视线", "升级线"],
                "醒来确认",
                "窗外风声更近了一点。",
                "chapter_hook",
                [SceneCard(1, "柴房", "醒来后确认状态", "监视者可能试探", "决定先稳住", "consolidate")],
                progression_step_type="consolidate",
            )
            continuity = ContinuityState()
            warning_local = LocalQualityReport(
                passed=True,
                score=81,
                issues=["正文略短，当前约 1827 字；番茄模式允许这种紧章，但建议补强余波、回报或章尾牵引。"],
                strengths=["段落层次基本成立。", "本章升级步骤已显式标注。"],
                short_summary="本地检查通过。",
                metrics={
                    "char_count": 1827,
                    "target_chars_min": 2084,
                    "length_warning": True,
                    "length_debt": False,
                    "length_hard_fail": False,
                    "procedural_density_hard_fail": False,
                    "propulsion_hard_fail": False,
                    "ending_voice_hard_fail": False,
                },
            )
            divergence_review = ReviewFeedback(
                passed=False,
                score=74,
                strengths=[
                    "醒来过程展示细腻且有层次感。",
                    "境界巩固过程展示具体且有感受变化。",
                ],
                issues=[
                    "正文严重偏短，必须扩充到2084-3473字区间。",
                    "场景4当前状态分析和下一步计划思考严重不足。",
                    "场景3恢复验证展示仍不足，监视者反应细节不够。",
                ],
                required_fixes=[
                    "扩充场景4目标明确，增加当前状态分析和下一步计划思考。",
                    "扩充场景3恢复验证，增加监视者反应细节。",
                ],
                short_summary="整体成立，但展开明显不够。",
            )

            pipeline_module.analyze_chapter = lambda *_args, **_kwargs: warning_local
            pipeline_module._quality_failure_fix_instructions = lambda *_args, **_kwargs: []
            pipeline._review_chapter = lambda *_args, **_kwargs: divergence_review  # type: ignore[method-assign]

            draft, rerun_local, rerun_review, attempts = pipeline._attempt_quality_failure_recovery(
                spec,
                bible,
                chapter,
                plan,
                "醒来后的第85章旧稿。",
                warning_local,
                divergence_review,
                continuity,
                execution_packet={},
                retrieved_memory=[],
                style_memory=[],
                promise_memory=[],
                causality_memory=[],
                logic_audit=None,
                chapter_room={},
                chapter_target_chars=2778,
                character_names=["林昼"],
                prior_chapters=[],
                attempts=1,
            )

            self.assertEqual(draft, "强制扩写后的第85章正文，补齐了状态分析、监视反应和章尾牵引。")
            self.assertTrue(rerun_local.passed)
            self.assertTrue(rerun_review.passed)
            self.assertIn("扩写债务", rerun_review.short_summary)
            self.assertEqual(client.text_calls, 1)
            self.assertGreaterEqual(attempts, 2)
        finally:
            pipeline_module.analyze_chapter = original_analyze
            pipeline_module._quality_failure_fix_instructions = original_fix_instructions
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_project_spec_from_dict_restores_volume_targets_and_tolerance(self) -> None:
        spec = pipeline_module._project_spec_from_dict(
            {
                "title": "测试",
                "chapter_count": 9,
                "volume_count": 2,
                "chapters_per_volume": 5,
                "volume_chapter_targets": [4, 5],
                "chapter_char_tolerance": 0.2,
            }
        )

        self.assertEqual(spec.volume_chapter_targets, [4, 5])
        self.assertEqual(spec.chapter_char_tolerance, 0.2)

    def test_volume_blueprints_preserve_progression_targets(self) -> None:
        spec = self._make_spec()
        skeleton = pipeline_module._volume_skeletons(spec)
        payloads = {
            1: {
                "title": "第一卷",
                "tier_floor": "练气六层",
                "tier_target": "练气九层",
                "required_breakthrough": "拿到聚灵丹",
                "resource_goal": "聚灵丹",
                "enemy_band": "外门执事",
                "progression_payoff": "拿到参加大比资格",
            }
        }

        volumes = pipeline_module._build_volume_blueprints_from_outline_payload(spec, skeleton, payloads)

        self.assertEqual(volumes[0].tier_floor, "练气六层")
        self.assertEqual(volumes[0].tier_target, "练气九层")
        self.assertEqual(volumes[0].required_breakthrough, "拿到聚灵丹")
        self.assertEqual(volumes[0].resource_goal, "聚灵丹")
        self.assertEqual(volumes[0].enemy_band, "外门执事")
        self.assertEqual(volumes[0].progression_payoff, "拿到参加大比资格")


class PipelinePayloadNormalizationTests(unittest.TestCase):
    def test_normalize_book_outline_merges_named_blocks(self) -> None:
        payload = [
            {"title": "神明寄存处"},
            {"one_line_summary": "旧商场地下寄存神明，也寄存旧城余温。"},
            {
                "volumes": [
                    {
                        "index": 1,
                        "title": "第一卷",
                        "role": "立住寄存处规则",
                        "central_question": "为什么神明正在系统性失效",
                    }
                ]
            },
        ]

        normalized = pipeline_module._normalize_book_outline_payload(payload)

        self.assertEqual(normalized["title"], "神明寄存处")
        self.assertEqual(len(normalized["volumes"]), 1)
        self.assertEqual(normalized["volumes"][0]["index"], 1)

    def test_normalize_book_outline_accepts_volume_alias_wrapper(self) -> None:
        payload = {
            "outline": {
                "title": "神明寄存处",
                "one_line_summary": "一句话简介",
                "volume_outlines": {
                    "items": [
                        {
                            "index": 1,
                            "title": "第一卷",
                            "role": "起势",
                            "central_question": "真相是什么",
                        }
                    ]
                },
            }
        }

        normalized = pipeline_module._normalize_book_outline_payload(payload)

        self.assertEqual(normalized["title"], "神明寄存处")
        self.assertEqual(len(normalized["volumes"]), 1)
        self.assertNotIn("volume_outlines", normalized)

    def test_normalize_volume_outline_merges_named_blocks(self) -> None:
        volume = VolumeBlueprint(
            index=1,
            start_chapter=1,
            end_chapter=3,
            title="第一卷",
            role="起势",
            central_question="真相是什么",
            escalation="局势升级",
            emotional_shift="从迟疑到行动",
        )
        payload = [
            {"goal": "先立住业务流程和神明规则。"},
            {"climax": "回收链第一次露头。"},
            {
                "chapters": [
                    {
                        "index": 1,
                        "title": "第一章",
                        "purpose": "开局接单",
                        "conflict": "现场反常",
                        "beat_summary": "寄存处开门",
                        "ending_note": "留下编号异常",
                    }
                ]
            },
        ]

        normalized = pipeline_module._normalize_volume_outline_payload(payload, volume)

        self.assertEqual(normalized["volume_index"], 1)
        self.assertEqual(normalized["title"], "第一卷")
        self.assertEqual(len(normalized["chapter_targets"]), 1)

    def test_normalize_chapter_plan_merges_named_blocks(self) -> None:
        payload = [
            {"chapter_title": "第九章 夜渡"},
            {"purpose": "夜里渡河，换掉推进发动机。"},
            {"scenes": [{"scene_index": 1, "location": "渡口", "goal": "过河", "conflict": "被盯梢", "turn": "换道"}]},
            {"term_budget": "low"},
        ]

        normalized = pipeline_module._normalize_chapter_plan_payload(payload)

        self.assertEqual(normalized["chapter_title"], "第九章 夜渡")
        self.assertEqual(normalized["purpose"], "夜里渡河，换掉推进发动机。")
        self.assertEqual(len(normalized["scenes"]), 1)
        self.assertEqual(normalized["term_budget"], "low")

    def test_normalize_chapter_plan_unwraps_wrapped_payload_and_nested_scene_items(self) -> None:
        payload = {
            "chapter_plan": [
                {"chapter_title": "第十章 回城"},
                {"purpose": "把局势从公开对撞拉回私下托底。"},
                {
                    "scenes": {
                        "items": [
                            {
                                "scene_index": 1,
                                "location": "后巷",
                                "goal": "接人",
                                "conflict": "旧债追来",
                                "turn": "改走水路",
                            }
                        ]
                    }
                },
            ]
        }

        normalized = pipeline_module._normalize_chapter_plan_payload(payload)

        self.assertEqual(normalized["chapter_title"], "第十章 回城")
        self.assertEqual(len(normalized["scenes"]), 1)
        self.assertEqual(normalized["scenes"][0]["location"], "后巷")

    def test_normalize_chapter_plan_accepts_scene_cards_alias_blocks(self) -> None:
        payload = [
            {"chapter_title": "第十一章 断桥"},
            {"purpose": "从案前围压换成私下换船。"},
            {
                "scene_cards": [
                    {
                        "scene_index": 1,
                        "location": "断桥下游",
                        "goal": "换船",
                        "conflict": "旧债堵口",
                        "turn": "改走暗湾",
                    }
                ]
            },
        ]

        normalized = pipeline_module._normalize_chapter_plan_payload(payload)

        self.assertEqual(normalized["chapter_title"], "第十一章 断桥")
        self.assertEqual(len(normalized["scenes"]), 1)
        self.assertEqual(normalized["scenes"][0]["location"], "断桥下游")
        self.assertNotIn("scene_cards", normalized)

    def test_normalize_chapter_plan_accepts_chapter_scenes_alias_in_wrapper(self) -> None:
        payload = {
            "plan": {
                "chapter_title": "第十二章 回潮",
                "purpose": "把局势从围观响应拉回两个人的托底。",
                "chapter_scenes": {
                    "items": [
                        {
                            "scene_index": 1,
                            "location": "潮汐巷口",
                            "goal": "接应",
                            "conflict": "伤情拖住节奏",
                            "turn": "先藏人再追账",
                        }
                    ]
                },
            }
        }

        normalized = pipeline_module._normalize_chapter_plan_payload(payload)

        self.assertEqual(normalized["chapter_title"], "第十二章 回潮")
        self.assertEqual(len(normalized["scenes"]), 1)
        self.assertEqual(normalized["scenes"][0]["location"], "潮汐巷口")
        self.assertNotIn("chapter_scenes", normalized)

    def test_normalize_chapter_plan_drops_string_scene_blocks_to_force_repair(self) -> None:
        payload = {
            "chapter_title": "第十三章 夜检",
            "purpose": "夜里去旧库房验货。",
            "scenes": [
                "场景一：沈雾夜里去旧库房验货，发现台账被人提前换过。",
                "场景二：她在后门撞见盯梢人，决定先带着账页撤走。",
            ],
        }

        normalized = pipeline_module._normalize_chapter_plan_payload(payload)

        self.assertEqual(normalized["chapter_title"], "第十三章 夜检")
        self.assertEqual(normalized["purpose"], "夜里去旧库房验货。")
        self.assertNotIn("scenes", normalized)

    def test_normalize_power_system_payload_merges_named_blocks(self) -> None:
        payload = [
            {
                "progression_mode": "hard_realm_progression",
                "progression_flavor": "xianxia_steady",
                "progression_pacing": "slow",
                "core_axis": "修士境界",
            },
            {
                "realm_ladder": [
                    {
                        "name": "练气",
                        "order": 1,
                        "summary": "打基础、攒灵力。",
                        "signature_capabilities": ["御物初成"],
                        "breakthrough_requirements": [{"name": "聚灵丹"}],
                    }
                ]
            },
            {
                "resource_axes": [
                    {
                        "name": "丹药",
                        "role": "主资源",
                        "early_game": "聚灵丹",
                        "mid_game": "筑基丹",
                    }
                ]
            },
            {
                "milestone_plan": [
                    {
                        "phase": "第一阶段",
                        "tier_target": "筑基",
                        "resource_goal": "拿到筑基丹",
                        "required_breakthrough": "外门大比"
                    }
                ]
            },
        ]

        normalized = pipeline_module._normalize_power_system_payload(payload)

        self.assertEqual(normalized["progression_mode"], "hard_realm_progression")
        self.assertEqual(normalized["progression_flavor"], "xianxia_steady")
        self.assertEqual(normalized["progression_pacing"], "slow")
        self.assertEqual(normalized["core_axis"], "修士境界")
        self.assertEqual(len(normalized["realm_ladder"]), 1)
        self.assertEqual(len(normalized["resource_axes"]), 1)
        self.assertEqual(len(normalized["milestone_plan"]), 1)

    def test_power_system_payload_signal_and_content_detection(self) -> None:
        signal_only = {
            "progression_mode": "hard_realm_progression",
            "core_axis": "修士境界",
            "realm_ladder": [],
            "resource_axes": [],
            "milestone_plan": [],
        }
        populated = {
            "progression_mode": "hard_realm_progression",
            "core_axis": "修士境界",
            "realm_ladder": [{"name": "练气", "order": 1}],
            "resource_axes": [],
            "milestone_plan": [],
        }

        self.assertTrue(pipeline_module._power_system_payload_has_signal(signal_only))
        self.assertFalse(pipeline_module._power_system_payload_has_content(signal_only))
        self.assertTrue(pipeline_module._power_system_payload_has_content(populated))

    def test_chapter_plan_from_payload_preserves_progression_fields(self) -> None:
        spec = ProjectSpec(
            title="测试",
            genre="玄幻",
            audience="男频",
            tone="热血",
            premise="主角要一路突破变强。",
            theme="成长",
            hook="开局就遇到突破门槛。",
            setting="修真世界",
            protagonist="少年修士",
            outline_hint="每章都要体现升级推进。",
            world_hint="宗门与秘境并行。",
            ending_mode="series",
            pov="第三人称有限视角",
            chapter_count=10,
            volume_count=1,
            chapters_per_volume=10,
            target_total_chars=30000,
            target_chars_per_chapter=3000,
        )
        chapter = ChapterOutlineItem(
            index=3,
            volume_index=1,
            title="第三章",
            purpose="拿到突破资源",
            conflict="被同门截胡",
            beat_summary="先拿资源再突围。",
            ending_note="资源到手但代价更大。",
            pov="第三人称有限视角",
            closing_mode="chapter_hook",
            progression_step_type="acquire",
            current_tier="练气八层",
            target_tier="练气九层",
            enemy_band="同阶内门弟子",
            resource_focus="聚灵丹",
        )
        payload = {
            "chapter_index": 3,
            "chapter_title": "第三章",
            "purpose": "拿到突破资源",
            "scenes": [
                {
                    "scene_index": 1,
                    "location": "药库",
                    "goal": "拿药",
                    "conflict": "同门拦截",
                    "turn": "反抢成功",
                }
            ],
            "progression_step_type": "acquire",
            "progression_reward": "拿到聚灵丹",
            "progression_cost": "暴露了底牌",
            "current_tier": "练气八层",
            "target_tier": "练气九层",
            "enemy_band": "同阶内门弟子",
            "resource_focus": "聚灵丹",
        }

        plan = pipeline_module._chapter_plan_from_payload(spec, chapter, payload)

        self.assertEqual(plan.progression_step_type, "acquire")
        self.assertEqual(plan.progression_reward, "拿到聚灵丹")
        self.assertEqual(plan.progression_cost, "暴露了底牌")
        self.assertEqual(plan.current_tier, "练气八层")
        self.assertEqual(plan.target_tier, "练气九层")
        self.assertEqual(plan.enemy_band, "同阶内门弟子")
        self.assertEqual(plan.resource_focus, "聚灵丹")

    def test_merge_continuity_state_preserves_progression_updates(self) -> None:
        state = ContinuityState(
            recent_summaries=["第一章摘要"],
            active_threads=["主线A"],
            resolved_threads=[],
            timeline=[],
            character_states=[],
            must_remember=[],
            progression_notes=["还缺聚灵丹"],
            current_tier="练气八层",
            next_breakthrough="拿到聚灵丹",
            last_volume_index=1,
            last_chapter_index=1,
        )
        update = ContinuityUpdate(
            chapter_index=2,
            chapter_summary="第二章摘要",
            new_threads=["资源线"],
            resolved_threads=[],
            timeline_events=["拿到聚灵丹线索"],
            character_states=[],
            next_chapter_targets=["去药库"],
            must_remember=["下章必须进药库"],
            progression_updates=["拿到聚灵丹就能冲击练气九层"],
            current_tier="练气八层",
            next_breakthrough="冲击练气九层",
        )

        merged = pipeline_module._merge_continuity_state(state, update, 1)

        self.assertIn("拿到聚灵丹就能冲击练气九层", merged.progression_notes)
        self.assertEqual(merged.current_tier, "练气八层")
        self.assertEqual(merged.next_breakthrough, "冲击练气九层")

    def test_logic_audit_from_dict_preserves_progression_risks(self) -> None:
        audit = pipeline_module._logic_audit_from_dict(
            {
                "passed": False,
                "gate_passed": False,
                "gate_level": "repair_cluster",
                "summary": "升级链开始失真。",
                "issues": ["敌人层级抬得太快。"],
                "watch_items": ["下一卷必须补突破代价。"],
                "required_followups": ["把资源线补清楚。"],
                "progression_risks": ["突破没有真实代价。"],
            }
        )

        self.assertEqual(audit.progression_risks, ["突破没有真实代价。"])

    def test_repair_chapter_plan_payload_when_scene_items_are_strings(self) -> None:
        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"chapter-plan-repair-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            client = StubClient(
                json_payloads=[
                    {
                        "chapter_title": "第十三章 夜检",
                        "purpose": "夜里去旧库房验货。",
                        "scenes": [
                            {
                                "scene_index": 1,
                                "location": "旧库房",
                                "goal": "验货",
                                "conflict": "台账被调包",
                                "turn": "先带走账页再追人",
                            }
                        ],
                    }
                ],
                text_payloads=[],
            )
            pipeline = NovelPipeline(client, temp_dir, flagship_model="flagship-model", light_model="light-model")
            chapter = ChapterOutlineItem(
                index=13,
                volume_index=2,
                title="第十三章 夜检",
                purpose="夜里去旧库房验货。",
                conflict="台账被调包",
                beat_summary="她在夜里摸进旧库房核账。",
                ending_note="先撤走账页。",
                pov="第三人称有限视角",
                closing_mode="hook",
            )

            payload = {
                "chapter_title": "第十三章 夜检",
                "purpose": "夜里去旧库房验货。",
                "scenes": [
                    "场景一：沈雾夜里去旧库房验货，发现台账被人提前换过。",
                    "场景二：她在后门撞见盯梢人，决定先带着账页撤走。",
                ],
            }

            repaired = pipeline._normalize_or_repair_chapter_plan_payload(
                chapter,
                payload,
                reason="initial_plan",
            )

            self.assertEqual(repaired["chapter_title"], "第十三章 夜检")
            self.assertEqual(len(repaired["scenes"]), 1)
            self.assertEqual(repaired["scenes"][0]["location"], "旧库房")
            self.assertEqual(client.models_by_session["planner-chapter-normalizer-13"][-1], "light-model")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_resolve_generated_chapter_plan_payload_regenerates_when_scene_content_is_missing(self) -> None:
        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"chapter-plan-regenerate-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            client = StubClient(json_payloads=[], text_payloads=[])
            pipeline = NovelPipeline(client, temp_dir, flagship_model="flagship-model", light_model="light-model")
            chapter = ChapterOutlineItem(
                index=2,
                volume_index=1,
                title="第2章",
                purpose="推进主线",
                conflict="冲突升级",
                beat_summary="摘要",
                ending_note="结尾",
                pov="第三人称有限视角",
                closing_mode="chapter_hook",
            )
            calls: list[tuple[list[str], object, int]] = []

            def regenerate(notes: list[str], previous_payload: object, attempt: int) -> object:
                calls.append((notes, previous_payload, attempt))
                return {
                    "chapter_index": 2,
                    "chapter_title": "第2章",
                    "purpose": "推进主线",
                    "scenes": [
                        {
                            "scene_index": 1,
                            "location": "库房",
                            "goal": "核查账页",
                            "conflict": "证据被调包",
                            "turn": "改去追人",
                        }
                    ],
                }

            resolved = pipeline._resolve_generated_chapter_plan_payload(
                chapter,
                [
                    "延续上一章风险。",
                    "兑现主角承诺。",
                    "结尾制造下一章压力。",
                ],
                reason="initial_plan",
                regenerate=regenerate,
            )

            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0][2], 1)
            self.assertEqual(len(resolved["scenes"]), 1)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_resolve_generated_chapter_plan_payload_repairs_dirty_scene_items_before_regenerating(self) -> None:
        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"chapter-plan-regenerate-dirty-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            client = StubClient(
                json_payloads=[
                    {
                        "chapter_title": "第3章 夜检",
                        "purpose": "夜里验货。",
                        "scenes": [
                            {
                                "scene_index": 1,
                                "location": "旧库房",
                                "goal": "验货",
                                "conflict": "台账被调包",
                                "turn": "先撤再追",
                            }
                        ],
                    }
                ],
                text_payloads=[],
            )
            pipeline = NovelPipeline(client, temp_dir, flagship_model="flagship-model", light_model="light-model")
            chapter = ChapterOutlineItem(
                index=3,
                volume_index=1,
                title="第3章 夜检",
                purpose="夜里验货。",
                conflict="台账被调包",
                beat_summary="摘要",
                ending_note="先撤再追。",
                pov="第三人称有限视角",
                closing_mode="chapter_hook",
            )
            calls: list[tuple[list[str], object, int]] = []

            resolved = pipeline._resolve_generated_chapter_plan_payload(
                chapter,
                {
                    "chapter_title": "第3章 夜检",
                    "purpose": "夜里验货。",
                    "scenes": [
                        "场景一：沈雾夜里去旧库房验货，发现台账被人提前换过。",
                        "场景二：她决定先带着账页撤走。",
                    ],
                },
                reason="initial_plan",
                regenerate=lambda notes, previous_payload, attempt: calls.append((notes, previous_payload, attempt)) or {},
            )

            self.assertEqual(calls, [])
            self.assertEqual(len(resolved["scenes"]), 1)
            self.assertEqual(client.models_by_session["planner-chapter-normalizer-3"][-1], "light-model")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_build_plan_falls_back_to_minimal_scene_skeleton_when_no_scenes_remain(self) -> None:
        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"chapter-plan-fallback-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        original_restructure = pipeline_module._chapter_plan_restructure_notes
        try:
            client = StubClient(
                json_payloads=[
                    [
                        "延续上一章风险。",
                        "兑现主角承诺。",
                        "结尾制造下一章压力。",
                    ],
                    [
                        "继续压住风险。",
                        "还是没有给出有效 scenes。",
                    ],
                    [
                        "仍然只给原则。",
                        "不给结构化场景。",
                    ],
                ],
                text_payloads=[],
            )
            pipeline = NovelPipeline(client, temp_dir, flagship_model="flagship-model", light_model="light-model")
            pipeline_module._chapter_plan_restructure_notes = lambda *_args, **_kwargs: []
            spec = ProjectSpec(
                title="测试小说",
                genre="都市奇谭",
                audience="中文读者",
                tone="克制",
                premise="她追查一份名单。",
                theme="代价",
                hook="名单再度浮出水面。",
                setting="旧港",
                protagonist="沈雾",
                outline_hint="完整闭环",
                world_hint="设定服务剧情",
                ending_mode="standalone",
                pov="第三人称有限视角",
                target_total_chars=4000,
                target_chars_per_chapter=2000,
                chapter_count=2,
                volume_count=1,
                chapters_per_volume=2,
                style_examples=["克制"],
                must_include=["名单"],
                avoid=["作者按"],
                character_seeds=[CharacterSeed(name="沈雾", role="主角")],
            )
            bible = WorldBible(
                title="测试小说",
                logline="名单再度浮出水面。",
                setting_summary="旧港",
                core_conflict="追查旧账",
                theme_statement="代价",
                narrative_voice=["克制"],
                world_rules=["规则一"],
                chapter_guardrails=["先写人再写制度"],
                ending_contract=["必须闭环"],
                major_threads=["名单线"],
                characters=[],
            )
            chapter = ChapterOutlineItem(
                index=2,
                volume_index=1,
                title="第2章 夜检",
                purpose="夜里回旧库房核账。",
                conflict="台账被人提前换过。",
                beat_summary="她在夜里确认库房台账被调包。",
                ending_note="她决定先带着账页撤走，再反查谁提前埋伏。",
                pov="第三人称有限视角",
                closing_mode="chapter_hook",
                must_payoff=["账页"],
            )
            book_outline = BookOutline(
                title="测试小说",
                one_line_summary="名单再度浮出水面。",
                act_structure=["追查名单"],
                volumes=[
                    VolumeBlueprint(
                        index=1,
                        start_chapter=1,
                        end_chapter=2,
                        title="第一卷 旧港",
                        role="推进主线",
                        central_question="谁换了台账",
                        escalation="风险升级",
                        emotional_shift="更主动",
                    )
                ],
            )
            volume_outline = VolumeOutline(
                volume_index=1,
                title="第一卷 旧港",
                goal="追回被调包的账页",
                climax="确认埋伏者身份",
                carry_over_threads=["名单线"],
                chapter_targets=[chapter],
            )
            continuity = ContinuityState(active_threads=["名单线"], must_remember=["账页"], last_chapter_index=1)

            plan = pipeline._build_plan(spec, bible, book_outline, volume_outline, chapter, continuity, [])

            self.assertEqual(len(plan.scenes), 3)
            self.assertEqual(plan.scenes[0].scene_type, "setup")
            self.assertEqual(plan.scenes[-1].scene_type, "hook")
            self.assertTrue((temp_dir / "state" / "chapter-02.plan-fallback.json").exists())
        finally:
            pipeline_module._chapter_plan_restructure_notes = original_restructure
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_resolve_generated_structured_mapping_payload_regenerates_after_unsuccessful_repair(self) -> None:
        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"structured-resolve-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            pipeline = NovelPipeline(StubClient(json_payloads=[], text_payloads=[]), temp_dir)
            calls: list[str] = []

            def normalize(value: object) -> dict[str, object]:
                if value == {"ok": True}:
                    return {"ok": True}
                return {}

            def has_content(payload: dict[str, object]) -> bool:
                return bool(payload.get("ok"))

            def has_signal(payload: object) -> bool:
                return isinstance(payload, list)

            def repair(payload: object) -> object:
                calls.append("repair")
                return {"notes": []}

            def regenerate(attempt: int, previous_payload: object) -> object:
                calls.append(f"regen-{attempt}")
                return {"ok": True}

            resolved = pipeline._resolve_generated_structured_mapping_payload(
                payload=["只有散句，没有有效对象"],
                normalize=normalize,
                has_content=has_content,
                has_signal=has_signal,
                regenerate=regenerate,
                repair=repair,
            )

            self.assertEqual(resolved, {"ok": True})
            self.assertEqual(calls, ["repair", "regen-1"])
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_normalize_continuity_unwraps_named_blocks(self) -> None:
        chapter = ChapterOutlineItem(
            index=3,
            volume_index=1,
            title="第3章",
            purpose="推进主线",
            conflict="冲突",
            beat_summary="摘要",
            ending_note="结尾",
            pov="第三人称",
            closing_mode="chapter_hook",
        )
        payload = {
            "continuity": [
                {"chapter_summary": "局势被迫换挡。"},
                {"must_remember": ["码头名单换了位置。"]},
                {"next_chapter_targets": ["先保人，再追账。"]},
            ]
        }

        normalized = pipeline_module._normalize_continuity_payload(payload, chapter)

        self.assertEqual(normalized["chapter_index"], 3)
        self.assertEqual(normalized["chapter_summary"], "局势被迫换挡。")
        self.assertEqual(normalized["must_remember"], ["码头名单换了位置。"])

    def test_normalize_review_unwraps_wrapped_feedback_blocks(self) -> None:
        payload = {
            "feedback": [
                {"passed": True},
                {"score": 91},
                {"issues": ["中段术语略密。"]},
                {"required_fixes": ["减一层制度解释。"]},
            ]
        }

        normalized = pipeline_module._normalize_review_payload(payload)

        self.assertTrue(normalized["passed"])
        self.assertEqual(normalized["score"], 91)
        self.assertEqual(normalized["issues"], ["中段术语略密。"])


class PipelineTests(unittest.TestCase):
    def test_pipeline_sets_client_routing_namespace_from_output_dir(self) -> None:
        class RoutingClient(StubClient):
            def __init__(self) -> None:
                super().__init__(json_payloads=[], text_payloads=[])
                self.namespace: str | None = None

            def set_routing_namespace(self, namespace: str | None) -> None:
                self.namespace = namespace

        output_dir = Path.cwd() / "runs" / "test-artifacts" / f"routing-namespace-{uuid.uuid4().hex[:8]}"
        output_dir.mkdir(parents=True, exist_ok=True)
        try:
            client = RoutingClient()
            NovelPipeline(client, output_dir)
            self.assertEqual(client.namespace, str(output_dir))
        finally:
            shutil.rmtree(output_dir, ignore_errors=True)

    def test_style_and_voice_controls_use_flagship_for_initial_build_and_light_for_calibration(self) -> None:
        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"model-tier-style-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            client = StubClient([], [])
            pipeline = NovelPipeline(
                client,
                temp_dir,
                flagship_model="gpt-flagship",
                light_model="gpt-light",
            )
            spec = ProjectSpec(
                title="测试小说",
                genre="都市奇谭",
                audience="中文读者",
                tone="克制",
                premise="她追查一份名单。",
                theme="代价",
                hook="名单再度浮出水面。",
                setting="旧港",
                protagonist="沈雾",
                outline_hint="完整闭环",
                world_hint="设定服务剧情",
                ending_mode="standalone",
                pov="第三人称有限视角",
                target_total_chars=4000,
                target_chars_per_chapter=2000,
                chapter_count=2,
                volume_count=1,
                chapters_per_volume=2,
                style_examples=["克制"],
                must_include=["名单"],
                avoid=["作者按"],
                character_seeds=[CharacterSeed(name="沈雾", role="主角")],
            )
            bible = WorldBible(
                title="测试小说",
                logline="名单再度浮出水面。",
                setting_summary="旧港",
                core_conflict="追查旧账",
                theme_statement="代价",
                narrative_voice=["克制"],
                world_rules=["规则一"],
                chapter_guardrails=["先写人再写制度"],
                ending_contract=["必须闭环"],
                major_threads=["名单线"],
                characters=[
                    CharacterProfile(
                        name="沈雾",
                        role="主角",
                        goal="追回血债名单",
                        fear="线索再断",
                        contradiction="想冷静，但一碰家人线索就急",
                        arc="从旁观转为承担",
                        public_image="冷静",
                        private_truth="其实一直紧绷",
                        speaking_style="简短",
                        signature_image="湿透的封套",
                    )
                ],
            )
            chapter = ChapterOutlineItem(
                index=1,
                volume_index=1,
                title="旧港回潮",
                purpose="拿回名单封套。",
                conflict="有人抢先一步。",
                beat_summary="沈雾在雨夜旧港摸到被调包的名单封套。",
                ending_note="她确认对方知道她会来。",
                pov="第三人称有限视角",
                closing_mode="hook",
                must_payoff=["名单封套"],
            )
            plan = ChapterPlan(
                chapter_index=1,
                chapter_title="旧港回潮",
                purpose="拿回名单封套。",
                continuity_targets=["名单封套"],
                opening_image="雨夜旧港",
                closing_image="名单封套被掉包",
                closing_mode="hook",
                scenes=[SceneCard(scene_index=1, location="旧港", goal="拿回名单", conflict="被人盯上", turn="发现封套被调包")],
                primary_propulsion="evidence",
                variation_goal="先抢证据，再稳情绪",
                term_budget="low",
                theme_visibility="subtext",
                grounding_beat="她鞋里进了水，走路发沉。",
            )
            review = ReviewFeedback(True, 92, ["推进明确"], [], [], "可用。")
            local_quality = LocalQualityReport(True, 94, [], ["动作明确"], "可用。", {})
            continuity = ContinuityUpdate(1, "她拿回了封套。", ["名单线"], [], ["封套回到她手里"], [], ["核封套"], ["名单封套已回手"])
            result = ChapterResult(
                index=1,
                volume_index=1,
                title="旧港回潮",
                outline_item=chapter,
                draft='沈雾抹掉封套上的水，低声说：“先等等。”\n\n她把名单封套塞回袖口，没有立刻走。',
                plan=plan,
                review=review,
                local_quality=local_quality,
                continuity=continuity,
                attempts=1,
            )

            pipeline._build_style_bible(spec, bible, anchor_style=None, chapters=None)
            pipeline._build_voice_cards(spec, bible, StyleBible(), [])
            pipeline._build_style_bible(spec, bible, anchor_style=StyleBible(audience_contract=["锚点"]), chapters=[result])
            pipeline._build_voice_cards(spec, bible, StyleBible(), [result])

            self.assertEqual(client.models_by_session["planner-style"][0], "gpt-flagship")
            self.assertEqual(client.models_by_session["planner-style"][-1], "gpt-light")
            self.assertEqual(client.models_by_session["planner-voice"][0], "gpt-flagship")
            self.assertEqual(client.models_by_session["planner-voice"][-1], "gpt-light")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_flagship_and_light_model_routing_split_review_from_extraction(self) -> None:
        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"model-tier-runtime-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            client = StubClient(
                [
                    {"passed": True, "score": 91, "strengths": ["推进清楚"], "issues": [], "required_fixes": [], "short_summary": "可用。"},
                    {
                        "chapter_index": 1,
                        "chapter_summary": "她拿回名单封套。",
                        "new_threads": ["名单线"],
                        "resolved_threads": [],
                        "timeline_events": ["封套回到她手里"],
                        "character_states": [],
                        "next_chapter_targets": ["核封套"],
                        "must_remember": ["名单封套已回手"],
                    },
                    {
                        "passed": True,
                        "gate_passed": True,
                        "summary": "本卷逻辑成立。",
                        "issues": [],
                        "watch_items": [],
                        "required_followups": [],
                    },
                    {
                        "factual_summary": "沈雾在旧港夺回名单封套，并循着被调包的痕迹继续追查旧账，故事沿着名单线稳定推进。",
                        "marketing_blurb": "她以为自己只是去拿回一只封套，却摸到一整条不该被打开的旧账线。",
                    },
                ],
                [],
            )
            pipeline = NovelPipeline(
                client,
                temp_dir,
                flagship_model="gpt-flagship",
                light_model="gpt-light",
            )
            spec = ProjectSpec(
                title="测试小说",
                genre="都市奇谭",
                audience="中文读者",
                tone="克制",
                premise="她追查一份名单。",
                theme="代价",
                hook="名单再度浮出水面。",
                setting="旧港",
                protagonist="沈雾",
                outline_hint="完整闭环",
                world_hint="设定服务剧情",
                ending_mode="standalone",
                pov="第三人称有限视角",
                target_total_chars=4000,
                target_chars_per_chapter=2000,
                chapter_count=2,
                volume_count=1,
                chapters_per_volume=2,
                style_examples=["克制"],
                must_include=["名单"],
                avoid=["作者按"],
                character_seeds=[CharacterSeed(name="沈雾", role="主角")],
            )
            bible = WorldBible(
                title="测试小说",
                logline="名单再度浮出水面。",
                setting_summary="旧港",
                core_conflict="追查旧账",
                theme_statement="代价",
                narrative_voice=["克制"],
                world_rules=["规则一"],
                chapter_guardrails=["先写人再写制度"],
                ending_contract=["必须闭环"],
                major_threads=["名单线"],
                characters=[
                    CharacterProfile(
                        name="沈雾",
                        role="主角",
                        goal="追回血债名单",
                        fear="线索再断",
                        contradiction="想冷静，但一碰家人线索就急",
                        arc="从旁观转为承担",
                        public_image="冷静",
                        private_truth="其实一直紧绷",
                        speaking_style="简短",
                        signature_image="湿透的封套",
                    )
                ],
            )
            chapter = ChapterOutlineItem(
                index=1,
                volume_index=1,
                title="旧港回潮",
                purpose="拿回名单封套。",
                conflict="有人抢先一步。",
                beat_summary="沈雾在雨夜旧港摸到被调包的名单封套。",
                ending_note="她确认对方知道她会来。",
                pov="第三人称有限视角",
                closing_mode="hook",
                must_payoff=["名单封套"],
            )
            plan = ChapterPlan(
                chapter_index=1,
                chapter_title="旧港回潮",
                purpose="拿回名单封套。",
                continuity_targets=["名单封套"],
                opening_image="雨夜旧港",
                closing_image="名单封套被掉包",
                closing_mode="hook",
                scenes=[SceneCard(scene_index=1, location="旧港", goal="拿回名单", conflict="被人盯上", turn="发现封套被调包")],
                primary_propulsion="evidence",
                variation_goal="先抢证据，再稳情绪",
                term_budget="low",
                theme_visibility="subtext",
                grounding_beat="她鞋里进了水，走路发沉。",
            )
            continuity_state = ContinuityState(active_threads=["名单线"], must_remember=["名单封套"], last_chapter_index=0)
            local_quality = LocalQualityReport(True, 94, [], ["动作明确"], "可用。", {})
            pipeline._style_bible = StyleBible(audience_contract=["读者要快速进入主线。"], tone_targets=["克制"])
            pipeline._voice_cards = [
                CharacterVoiceCard(
                    name="沈雾",
                    speech_rhythm="简短",
                    emotional_expression="情绪落在动作和停顿里",
                    sentence_shape="短句为主",
                )
            ]
            review = pipeline._review_chapter(spec, bible, chapter, plan, "正文。", local_quality, continuity_state, {})
            continuity_update = pipeline._extract_continuity(spec, bible, chapter, "正文。", continuity_state)
            pipeline._long_memory_context = continuity_state
            long_memory = pipeline._extract_long_range_memory(spec, bible, chapter, plan, "正文。")
            chapter_result = ChapterResult(
                index=1,
                volume_index=1,
                title="旧港回潮",
                outline_item=chapter,
                draft="正文。",
                plan=plan,
                review=review,
                local_quality=local_quality,
                continuity=continuity_update,
                attempts=1,
                long_memory=long_memory,
            )
            book_outline = BookOutline(
                title="测试小说",
                one_line_summary="名单再度浮出水面。",
                act_structure=["追查名单"],
                volumes=[VolumeBlueprint(index=1, start_chapter=1, end_chapter=2, title="第一卷", role="推进主线", central_question="名单去哪了", escalation="风险升级", emotional_shift="更主动")],
            )
            volume_outline = VolumeOutline(
                volume_index=1,
                title="第一卷",
                goal="追查名单",
                climax="找到名单流向",
                carry_over_threads=["名单线"],
                chapter_targets=[chapter],
            )
            audit = pipeline._audit_volume_logic(spec, bible, book_outline, volume_outline, [chapter_result], continuity_state, force_refresh=True)
            package = pipeline._build_book_package(
                spec,
                bible,
                book_outline,
                [chapter_result],
                continuity_state,
                FinalReview(True, 93, ["完整"], [], [], "通过。"),
                total_chars=len(chapter_result.draft),
            )

            self.assertTrue(review.passed)
            self.assertTrue(audit and audit.gate_passed)
            self.assertEqual(package.title, "测试小说")
            self.assertEqual(client.models_by_session["reviewer"][-1], "gpt-light")
            self.assertEqual(client.models_by_session["logic-audit"][-1], "gpt-light")
            self.assertEqual(client.models_by_session["continuity"][-1], "gpt-light")
            self.assertEqual(client.models_by_session["long-memory"][-1], "gpt-light")
            self.assertEqual(client.models_by_session["book-package"][-1], "gpt-light")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_extract_continuity_accepts_list_payload_blocks(self) -> None:
        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"continuity-list-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            client = StubClient(
                json_payloads=[
                    [
                        {"chapter_summary": "她确认名单被调包。"},
                        {"new_threads": ["名单线"]},
                        {"must_remember": ["名单还没追回"]},
                        {"character_states": [{"name": "沈雾", "current_goal": "追回血名单"}]},
                    ]
                ],
                text_payloads=[],
            )
            pipeline = NovelPipeline(
                client,
                temp_dir,
                flagship_model="gpt-flagship",
                light_model="gpt-light",
                review_model="claude-sonnet-4-5-20250929",
            )
            spec = ProjectSpec(
                title="测试小说",
                genre="都市奇谭",
                audience="中文读者",
                tone="克制",
                premise="她追查一份名单。",
                theme="代价",
                hook="名单再度浮出水面。",
                setting="旧港",
                protagonist="沈雾",
                outline_hint="完整闭环",
                world_hint="设定服务剧情",
                ending_mode="standalone",
                pov="第三人称有限视角",
                target_total_chars=4000,
                target_chars_per_chapter=2000,
                chapter_count=2,
                volume_count=1,
                chapters_per_volume=2,
                style_examples=["克制"],
                must_include=["名单"],
                avoid=["作者按"],
                character_seeds=[CharacterSeed(name="沈雾", role="主角")],
            )
            bible = WorldBible(
                title="测试小说",
                logline="名单再度浮出水面。",
                setting_summary="旧港",
                core_conflict="她要追回被调包的名单。",
                theme_statement="代价决定真相值不值得追。",
                narrative_voice=["克制", "具体"],
                world_rules=["旧账必须留痕。"],
                chapter_guardrails=["每章都要推进名单线。"],
                ending_contract=["名单必须追回。"],
                major_threads=["名单线"],
                characters=[],
            )
            chapter = ChapterOutlineItem(
                index=2,
                volume_index=1,
                title="旧港回潮",
                purpose="拿回名单封套。",
                conflict="有人抢先一步。",
                beat_summary="她确认名单被调包。",
                ending_note="她看见留下的记号。",
                pov="第三人称有限视角",
                closing_mode="hook",
            )
            continuity = pipeline._extract_continuity(
                spec,
                bible,
                chapter,
                "正文。",
                ContinuityState(active_threads=["旧账线"], must_remember=["封套还没回手"]),
            )

            self.assertEqual(continuity.chapter_index, 2)
            self.assertEqual(continuity.chapter_summary, "她确认名单被调包。")
            self.assertEqual(continuity.new_threads, ["名单线"])
            self.assertEqual(continuity.must_remember, ["名单还没追回"])
            self.assertEqual(len(continuity.character_states), 1)
            self.assertEqual(continuity.character_states[0].name, "沈雾")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_extract_continuity_falls_back_when_payload_stays_empty(self) -> None:
        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"continuity-fallback-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            client = StubClient(
                json_payloads=[
                    ["只有散句，没有结构。"],
                    ["继续没有结构。"],
                    ["仍然不给连续性字段。"],
                ],
                text_payloads=[],
            )
            pipeline = NovelPipeline(
                client,
                temp_dir,
                flagship_model="gpt-flagship",
                light_model="gpt-light",
                review_model="claude-sonnet-4-5-20250929",
            )
            spec = ProjectSpec(
                title="测试小说",
                genre="都市奇谭",
                audience="中文读者",
                tone="克制",
                premise="她追查一份名单。",
                theme="代价",
                hook="名单再度浮出水面。",
                setting="旧港",
                protagonist="沈雾",
                outline_hint="完整闭环",
                world_hint="设定服务剧情",
                ending_mode="standalone",
                pov="第三人称有限视角",
                target_total_chars=4000,
                target_chars_per_chapter=2000,
                chapter_count=2,
                volume_count=1,
                chapters_per_volume=2,
                style_examples=["克制"],
                must_include=["名单"],
                avoid=["作者按"],
                character_seeds=[CharacterSeed(name="沈雾", role="主角")],
            )
            bible = WorldBible(
                title="测试小说",
                logline="名单再度浮出水面。",
                setting_summary="旧港",
                core_conflict="她要追回被调包的名单。",
                theme_statement="代价决定真相值不值得追。",
                narrative_voice=["克制", "具体"],
                world_rules=["旧账必须留痕。"],
                chapter_guardrails=["每章都要推进名单线。"],
                ending_contract=["名单必须追回。"],
                major_threads=["名单线"],
                characters=[],
            )
            chapter = ChapterOutlineItem(
                index=2,
                volume_index=1,
                title="旧港回潮",
                purpose="拿回名单封套。",
                conflict="有人抢先一步。",
                beat_summary="她确认名单被调包。",
                ending_note="她看见留下的记号。",
                pov="第三人称有限视角",
                closing_mode="hook",
                must_payoff=["名单线"],
            )
            continuity = pipeline._extract_continuity(
                spec,
                bible,
                chapter,
                "正文里她确认名单被调包，并决定先保人再追账。",
                ContinuityState(active_threads=["旧账线"], must_remember=["封套还没回手"]),
            )

            self.assertEqual(continuity.chapter_index, 2)
            self.assertTrue(continuity.chapter_summary)
            self.assertTrue((temp_dir / "state" / "chapter-02.continuity-fallback.json").exists())
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_extract_continuity_falls_back_after_json_parse_error(self) -> None:
        class ParseFailClient(StubClient):
            def generate_json(self, system_prompt, user_prompt, **kwargs):
                raise JsonParseModelClientError(
                    "Model did not return valid JSON: Could not parse JSON payload from model output.",
                    raw_text="只有散句，没有合法 JSON。",
                )

        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"continuity-parse-fallback-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            client = ParseFailClient([], [])
            pipeline = NovelPipeline(
                client,
                temp_dir,
                flagship_model="gpt-flagship",
                light_model="gpt-light",
                review_model="claude-sonnet-4-5-20250929",
            )
            spec = ProjectSpec(
                title="测试小说",
                genre="都市奇谭",
                audience="中文读者",
                tone="克制",
                premise="她追查一份名单。",
                theme="代价",
                hook="名单再度浮出水面。",
                setting="旧港",
                protagonist="沈雾",
                outline_hint="完整闭环",
                world_hint="设定服务剧情",
                ending_mode="standalone",
                pov="第三人称有限视角",
                target_total_chars=4000,
                target_chars_per_chapter=2000,
                chapter_count=2,
                volume_count=1,
                chapters_per_volume=2,
                style_examples=["克制"],
                must_include=["名单"],
                avoid=["作者按"],
                character_seeds=[CharacterSeed(name="沈雾", role="主角")],
            )
            bible = WorldBible(
                title="测试小说",
                logline="名单再度浮出水面。",
                setting_summary="旧港",
                core_conflict="她要追回被调包的名单。",
                theme_statement="代价决定真相值不值得追。",
                narrative_voice=["克制", "具体"],
                world_rules=["旧账必须留痕。"],
                chapter_guardrails=["每章都要推进名单线。"],
                ending_contract=["名单必须追回。"],
                major_threads=["名单线"],
                characters=[],
            )
            chapter = ChapterOutlineItem(
                index=2,
                volume_index=1,
                title="旧港回潮",
                purpose="拿回名单封套。",
                conflict="有人抢先一步。",
                beat_summary="她确认名单被调包。",
                ending_note="她看见留下的记号。",
                pov="第三人称有限视角",
                closing_mode="hook",
                must_payoff=["名单线"],
            )
            continuity = pipeline._extract_continuity(
                spec,
                bible,
                chapter,
                "正文里她确认名单被调包，并决定先保人再追账。",
                ContinuityState(active_threads=["旧账线"], must_remember=["封套还没回手"]),
            )

            self.assertEqual(continuity.chapter_index, 2)
            self.assertTrue((temp_dir / "state" / "chapter-02.continuity-fallback.json").exists())
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_review_chapter_accepts_list_payload_blocks(self) -> None:
        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"review-list-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            client = StubClient(
                json_payloads=[
                    [
                        {"passed": True},
                        {"score": 91},
                        {"strengths": ["人物动机稳定。"]},
                        {"issues": []},
                        {"required_fixes": []},
                        {"short_summary": "本章可用。"},
                    ]
                ],
                text_payloads=[],
            )
            pipeline = NovelPipeline(
                client,
                temp_dir,
                flagship_model="gpt-flagship",
                light_model="gpt-light",
                review_model="claude-sonnet-4-5-20250929",
            )
            spec = ProjectSpec(
                title="测试小说",
                genre="都市奇谭",
                audience="中文读者",
                tone="克制",
                premise="她追查一份名单。",
                theme="代价",
                hook="名单再度浮出水面。",
                setting="旧港",
                protagonist="沈雾",
                outline_hint="完整闭环",
                world_hint="设定服务剧情",
                ending_mode="standalone",
                pov="第三人称有限视角",
                target_total_chars=4000,
                target_chars_per_chapter=2000,
                chapter_count=2,
                volume_count=1,
                chapters_per_volume=2,
                style_examples=["克制"],
                must_include=["名单"],
                avoid=["作者按"],
                character_seeds=[CharacterSeed(name="沈雾", role="主角")],
            )
            bible = WorldBible(
                title="测试小说",
                logline="名单再度浮出水面。",
                setting_summary="旧港",
                core_conflict="追查旧账",
                theme_statement="代价",
                narrative_voice=["克制"],
                world_rules=["规则一"],
                chapter_guardrails=["先写人再写制度"],
                ending_contract=["必须闭环"],
                major_threads=["名单线"],
                characters=[],
            )
            chapter = ChapterOutlineItem(
                index=1,
                volume_index=1,
                title="旧港回潮",
                purpose="拿回名单封套。",
                conflict="有人抢先一步。",
                beat_summary="沈雾在雨夜旧港摸到被调包的名单封套。",
                ending_note="她确认对方知道她会来。",
                pov="第三人称有限视角",
                closing_mode="hook",
                must_payoff=["名单封套"],
            )
            plan = ChapterPlan(
                chapter_index=1,
                chapter_title="旧港回潮",
                purpose="拿回名单封套。",
                continuity_targets=["名单封套"],
                opening_image="雨夜旧港",
                closing_image="名单封套被掉包",
                closing_mode="hook",
                scenes=[SceneCard(scene_index=1, location="旧港", goal="拿回名单", conflict="被人盯上", turn="发现封套被调包")],
                primary_propulsion="evidence",
                variation_goal="先抢证据，再稳情绪",
                term_budget="low",
                theme_visibility="subtext",
                grounding_beat="她鞋里进了水，走路发沉。",
            )
            continuity_state = ContinuityState(active_threads=["名单线"], must_remember=["名单封套"], last_chapter_index=0)
            local_quality = LocalQualityReport(True, 94, [], ["动作明确"], "可用。", {})
            pipeline._style_bible = StyleBible(audience_contract=["读者要快速进入主线。"], tone_targets=["克制"])
            pipeline._voice_cards = [
                CharacterVoiceCard(
                    name="沈雾",
                    speech_rhythm="简短",
                    emotional_expression="情绪落在动作和停顿里",
                    sentence_shape="短句为主",
                )
            ]

            review = pipeline._review_chapter(spec, bible, chapter, plan, "正文。", local_quality, continuity_state, {})

            self.assertTrue(review.passed)
            self.assertEqual(review.score, 91)
            self.assertEqual(review.short_summary, "本章可用。")
            self.assertEqual(review.strengths, ["人物动机稳定。"])
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_review_chapter_retries_malformed_semantic_failure(self) -> None:
        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"review-semantic-retry-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            client = StubClient(
                json_payloads=[
                    {
                        "passed": False,
                        "score": 0,
                        "strengths": ["人物动机稳定。", "章尾钩子成立。"],
                        "issues": [],
                        "required_fixes": ["人物动机稳定。", "章尾钩子成立。"],
                        "short_summary": "本章可用。",
                    },
                    {
                        "passed": True,
                        "score": 93,
                        "strengths": ["人物动机稳定。", "章尾钩子成立。"],
                        "issues": [],
                        "required_fixes": [],
                        "short_summary": "本章通过。",
                    },
                ],
                text_payloads=[],
            )
            pipeline = NovelPipeline(
                client,
                temp_dir,
                flagship_model="gpt-flagship",
                light_model="gpt-light",
                review_model="claude-sonnet-4-5-20250929",
            )
            spec = ProjectSpec(
                title="测试小说",
                genre="都市奇谭",
                audience="中文读者",
                tone="克制",
                premise="她追查一份名单。",
                theme="代价",
                hook="名单再度浮出水面。",
                setting="旧港",
                protagonist="沈雾",
                outline_hint="完整闭环",
                world_hint="设定服务剧情",
                ending_mode="standalone",
                pov="第三人称有限视角",
                target_total_chars=4000,
                target_chars_per_chapter=2000,
                chapter_count=2,
                volume_count=1,
                chapters_per_volume=2,
                style_examples=["克制"],
                must_include=["名单"],
                avoid=["作者按"],
                character_seeds=[CharacterSeed(name="沈雾", role="主角")],
            )
            bible = WorldBible(
                title="测试小说",
                logline="名单再度浮出水面。",
                setting_summary="旧港",
                core_conflict="追查旧账",
                theme_statement="代价",
                narrative_voice=["克制"],
                world_rules=["规则一"],
                chapter_guardrails=["先写人再写制度"],
                ending_contract=["必须闭环"],
                major_threads=["名单线"],
                characters=[],
            )
            chapter = ChapterOutlineItem(
                index=1,
                volume_index=1,
                title="旧港回潮",
                purpose="拿回名单封套。",
                conflict="有人抢先一步。",
                beat_summary="沈雾在雨夜旧港摸到被调包的名单封套。",
                ending_note="她确认对方知道她会来。",
                pov="第三人称有限视角",
                closing_mode="hook",
                must_payoff=["名单封套"],
            )
            plan = ChapterPlan(
                chapter_index=1,
                chapter_title="旧港回潮",
                purpose="拿回名单封套。",
                continuity_targets=["名单封套"],
                opening_image="雨夜旧港",
                closing_image="名单封套被掉包",
                closing_mode="hook",
                scenes=[SceneCard(scene_index=1, location="旧港", goal="拿回名单", conflict="被人盯上", turn="发现封套被调包")],
                primary_propulsion="evidence",
                variation_goal="先抢证据，再稳情绪",
                term_budget="low",
                theme_visibility="subtext",
                grounding_beat="她鞋里进了水，走路发沉。",
            )
            continuity_state = ContinuityState(active_threads=["名单线"], must_remember=["名单封套"], last_chapter_index=0)
            local_quality = LocalQualityReport(True, 94, [], ["动作明确"], "可用。", {})
            pipeline._style_bible = StyleBible(audience_contract=["读者要快速进入主线。"], tone_targets=["克制"])
            pipeline._voice_cards = [
                CharacterVoiceCard(
                    name="沈雾",
                    speech_rhythm="简短",
                    emotional_expression="情绪落在动作和停顿里",
                    sentence_shape="短句为主",
                )
            ]

            review = pipeline._review_chapter(spec, bible, chapter, plan, "正文。", local_quality, continuity_state, {})

            self.assertTrue(review.passed)
            self.assertEqual(review.score, 93)
            self.assertEqual(client.json_calls, 2)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_review_chapter_retries_when_positive_feedback_is_stuffed_into_issues(self) -> None:
        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"review-positive-issues-retry-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            client = StubClient(
                json_payloads=[
                    {
                        "passed": False,
                        "score": 0,
                        "strengths": [],
                        "issues": ["人物动机稳定。", "章尾钩子成立。"],
                        "required_fixes": ["人物动机稳定。", "章尾钩子成立。"],
                        "short_summary": "本章可用。",
                    },
                    {
                        "passed": True,
                        "score": 93,
                        "strengths": ["人物动机稳定。", "章尾钩子成立。"],
                        "issues": [],
                        "required_fixes": [],
                        "short_summary": "本章通过。",
                    },
                ],
                text_payloads=[],
            )
            pipeline = NovelPipeline(
                client,
                temp_dir,
                flagship_model="gpt-flagship",
                light_model="gpt-light",
                review_model="claude-sonnet-4-5-20250929",
            )
            spec = ProjectSpec(
                title="测试小说",
                genre="都市奇谭",
                audience="中文读者",
                tone="克制",
                premise="她追查一份名单。",
                theme="代价",
                hook="名单再度浮出水面。",
                setting="旧港",
                protagonist="沈雾",
                outline_hint="完整闭环",
                world_hint="设定服务剧情",
                ending_mode="standalone",
                pov="第三人称有限视角",
                target_total_chars=4000,
                target_chars_per_chapter=2000,
                chapter_count=2,
                volume_count=1,
                chapters_per_volume=2,
                style_examples=["克制"],
                must_include=["名单"],
                avoid=["作者按"],
                character_seeds=[CharacterSeed(name="沈雾", role="主角")],
            )
            bible = WorldBible(
                title="测试小说",
                logline="名单再度浮出水面。",
                setting_summary="旧港",
                core_conflict="追查旧账",
                theme_statement="代价",
                narrative_voice=["克制"],
                world_rules=["规则一"],
                chapter_guardrails=["先写人再写制度"],
                ending_contract=["必须闭环"],
                major_threads=["名单线"],
                characters=[],
            )
            chapter = ChapterOutlineItem(
                index=1,
                volume_index=1,
                title="旧港回潮",
                purpose="拿回名单封套。",
                conflict="有人抢先一步。",
                beat_summary="沈雾在雨夜旧港摸到被调包的名单封套。",
                ending_note="她确认对方知道她会来。",
                pov="第三人称有限视角",
                closing_mode="hook",
            )
            plan = ChapterPlan(
                chapter_index=1,
                chapter_title="旧港回潮",
                purpose="拿回名单封套。",
                continuity_targets=["名单封套"],
                opening_image="雨夜旧港",
                closing_image="名单封套被掉包",
                closing_mode="hook",
                scenes=[SceneCard(scene_index=1, location="旧港", goal="拿回名单", conflict="被人盯上", turn="发现封套被调包")],
            )
            local_quality = LocalQualityReport(True, 94, [], ["动作明确"], "可用。", {})
            review = pipeline._review_chapter(spec, bible, chapter, plan, "正文。", local_quality, ContinuityState(), {})

            self.assertTrue(review.passed)
            self.assertEqual(review.score, 93)
            self.assertEqual(client.json_calls, 2)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_review_chapter_soft_passes_when_retry_is_still_semantically_malformed(self) -> None:
        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"review-positive-issues-soft-pass-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            client = StubClient(
                json_payloads=[
                    {
                        "passed": False,
                        "score": 0,
                        "strengths": [],
                        "issues": ["核心承诺全部兑现。", "楼道舆论战三层递进清晰。"],
                        "required_fixes": ["核心承诺全部兑现。", "楼道舆论战三层递进清晰。"],
                        "short_summary": "本章可用。",
                    },
                    {
                        "passed": False,
                        "score": 0,
                        "strengths": [],
                        "issues": ["核心承诺全部兑现。", "楼道舆论战三层递进清晰。"],
                        "required_fixes": ["核心承诺全部兑现。", "楼道舆论战三层递进清晰。"],
                        "short_summary": "本章可用。",
                    },
                ],
                text_payloads=[],
            )
            pipeline = NovelPipeline(
                client,
                temp_dir,
                flagship_model="gpt-flagship",
                light_model="gpt-light",
                review_model="claude-sonnet-4-5-20250929",
            )
            spec = ProjectSpec(
                title="测试小说",
                genre="都市奇谭",
                audience="中文读者",
                tone="克制",
                premise="她追查一份名单。",
                theme="代价",
                hook="名单再度浮出水面。",
                setting="旧港",
                protagonist="沈雾",
                outline_hint="完整闭环",
                world_hint="设定服务剧情",
                ending_mode="standalone",
                pov="第三人称有限视角",
                target_total_chars=4000,
                target_chars_per_chapter=2000,
                chapter_count=2,
                volume_count=1,
                chapters_per_volume=2,
                style_examples=["克制"],
                must_include=["名单"],
                avoid=["作者按"],
                character_seeds=[CharacterSeed(name="沈雾", role="主角")],
            )
            bible = WorldBible(
                title="测试小说",
                logline="名单再度浮出水面。",
                setting_summary="旧港",
                core_conflict="追查旧账",
                theme_statement="代价",
                narrative_voice=["克制"],
                world_rules=["规则一"],
                chapter_guardrails=["先写人再写制度"],
                ending_contract=["必须闭环"],
                major_threads=["名单线"],
                characters=[],
            )
            chapter = ChapterOutlineItem(
                index=1,
                volume_index=1,
                title="旧港回潮",
                purpose="拿回名单封套。",
                conflict="有人抢先一步。",
                beat_summary="沈雾在雨夜旧港摸到被调包的名单封套。",
                ending_note="她确认对方知道她会来。",
                pov="第三人称有限视角",
                closing_mode="hook",
            )
            plan = ChapterPlan(
                chapter_index=1,
                chapter_title="旧港回潮",
                purpose="拿回名单封套。",
                continuity_targets=["名单封套"],
                opening_image="雨夜旧港",
                closing_image="名单封套被掉包",
                closing_mode="hook",
                scenes=[SceneCard(scene_index=1, location="旧港", goal="拿回名单", conflict="被人盯上", turn="发现封套被调包")],
            )
            local_quality = LocalQualityReport(True, 94, [], ["动作明确"], "可用。", {})

            review = pipeline._review_chapter(spec, bible, chapter, plan, "正文。", local_quality, ContinuityState(), {})

            self.assertTrue(review.passed)
            self.assertGreaterEqual(review.score, 88)
            self.assertIn("语义漂移", review.short_summary)
            self.assertEqual(client.json_calls, 2)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_review_chapter_retries_malformed_semantic_failure_when_local_only_fails_for_short_length(self) -> None:
        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"review-short-semantic-retry-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            client = StubClient(
                json_payloads=[
                    {
                        "passed": False,
                        "score": 0,
                        "strengths": [],
                        "issues": ["听觉信息收集过程具体且有层次。", "短句节奏有效。"],
                        "required_fixes": ["听觉信息收集过程具体且有层次。", "短句节奏有效。"],
                        "short_summary": "本章可用。",
                    },
                    {
                        "passed": True,
                        "score": 91,
                        "strengths": ["听觉信息收集过程具体且有层次。", "短句节奏有效。"],
                        "issues": [],
                        "required_fixes": [],
                        "short_summary": "本章通过。",
                    },
                ],
                text_payloads=[],
            )
            pipeline = NovelPipeline(
                client,
                temp_dir,
                flagship_model="gpt-flagship",
                light_model="gpt-light",
                review_model="claude-sonnet-4-5-20250929",
            )
            spec = ProjectSpec(
                title="测试小说",
                genre="都市奇谭",
                audience="中文读者",
                tone="克制",
                premise="她被困在旧楼里。",
                theme="代价",
                hook="门外脚步声停在门口。",
                setting="旧楼",
                protagonist="林砚",
                outline_hint="完整闭环",
                world_hint="设定服务剧情",
                ending_mode="standalone",
                pov="第三人称有限视角",
                target_total_chars=4000,
                target_chars_per_chapter=2500,
                chapter_count=2,
                volume_count=1,
                chapters_per_volume=2,
                market_profile="tomato_mass",
                style_examples=["克制"],
                must_include=["脚步声"],
                avoid=["作者按"],
                character_seeds=[CharacterSeed(name="林砚", role="主角")],
            )
            bible = WorldBible(
                title="测试小说",
                logline="她被困在旧楼里。",
                setting_summary="旧楼",
                core_conflict="被困与逃脱",
                theme_statement="代价",
                narrative_voice=["克制"],
                world_rules=["规则一"],
                chapter_guardrails=["先写人再写制度"],
                ending_contract=["必须闭环"],
                major_threads=["旧楼线"],
                characters=[],
            )
            chapter = ChapterOutlineItem(
                index=1,
                volume_index=1,
                title="门外脚步",
                purpose="听清门外局势。",
                conflict="不能出门。",
                beat_summary="她靠着门，听门外的人对话。",
                ending_note="门外暂时没破门。",
                pov="第三人称有限视角",
                closing_mode="hook",
            )
            plan = ChapterPlan(
                chapter_index=1,
                chapter_title="门外脚步",
                purpose="听清门外局势。",
                continuity_targets=["门外有两个人"],
                opening_image="门外脚步停住",
                closing_image="手机震动传来消息",
                closing_mode="hook",
                scenes=[SceneCard(scene_index=1, location="房门口", goal="辨别局势", conflict="伤口太痛", turn="确认门外暂不破门")],
            )
            local_quality = LocalQualityReport(
                passed=False,
                score=88,
                issues=["正文严重偏短，当前约 953 字，明显低于番茄模式容忍带下限 2093 字。"],
                strengths=["段落层次基本成立。", "核心角色被明确写入正文。"],
                short_summary="本地检查发现可读性风险。",
                metrics={
                    "char_count": 953,
                    "length_under_ratio": 0.4553,
                    "length_hard_fail": True,
                    "procedural_density_hard_fail": False,
                    "propulsion_hard_fail": False,
                    "ending_voice_hard_fail": False,
                },
            )
            review = pipeline._review_chapter(spec, bible, chapter, plan, "正文。", local_quality, ContinuityState(), {})

            self.assertTrue(review.passed)
            self.assertEqual(review.score, 91)
            self.assertEqual(client.json_calls, 2)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_provider_behavior_profile_uses_pipeline_models_without_client_provider(self) -> None:
        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"provider-profile-models-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            pipeline = NovelPipeline(
                StubClient([], []),
                temp_dir,
                flagship_model="gpt-flagship",
                light_model="gpt-light",
                review_model="claude-sonnet-4-5-20250929",
            )

            profile = pipeline._provider_behavior_profile()

            self.assertTrue(profile.review_semantic_drift_prone)
            self.assertTrue(profile.underwrite_prone)
            self.assertTrue(profile.refusal_prone)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_finalize_retries_malformed_semantic_failure(self) -> None:
        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"final-review-semantic-retry-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            client = StubClient(
                json_payloads=[
                    {
                        "passed": False,
                        "score": 0,
                        "strengths": ["主线闭环完整。", "人物弧线成立。"],
                        "issues": [],
                        "required_fixes": ["主线闭环完整。", "人物弧线成立。"],
                        "short_summary": "整书可用。",
                    },
                    {
                        "passed": True,
                        "score": 95,
                        "strengths": ["主线闭环完整。", "人物弧线成立。"],
                        "issues": [],
                        "required_fixes": [],
                        "short_summary": "整书通过。",
                    },
                ],
                text_payloads=[],
            )
            pipeline = NovelPipeline(client, temp_dir, flagship_model="gpt-flagship", light_model="gpt-light")
            spec = ProjectSpec(
                title="测试小说",
                genre="都市奇谭",
                audience="中文读者",
                tone="克制",
                premise="她追查一份名单。",
                theme="代价",
                hook="名单再度浮出水面。",
                setting="旧港",
                protagonist="沈雾",
                outline_hint="完整闭环",
                world_hint="设定服务剧情",
                ending_mode="standalone",
                pov="第三人称有限视角",
                target_total_chars=4000,
                target_chars_per_chapter=2000,
                chapter_count=2,
                volume_count=1,
                chapters_per_volume=2,
                style_examples=["克制"],
                must_include=["名单"],
                avoid=["作者按"],
                character_seeds=[CharacterSeed(name="沈雾", role="主角")],
            )
            bible = WorldBible(
                title="测试小说",
                logline="名单再度浮出水面。",
                setting_summary="旧港",
                core_conflict="追查旧账",
                theme_statement="代价",
                narrative_voice=["克制"],
                world_rules=["规则一"],
                chapter_guardrails=["先写人再写制度"],
                ending_contract=["必须闭环"],
                major_threads=["名单线"],
                characters=[],
            )
            chapter = ChapterOutlineItem(
                index=1,
                volume_index=1,
                title="旧港回潮",
                purpose="拿回名单封套。",
                conflict="有人抢先一步。",
                beat_summary="沈雾在雨夜旧港摸到被调包的名单封套。",
                ending_note="她确认对方知道她会来。",
                pov="第三人称有限视角",
                closing_mode="hook",
                must_payoff=["名单封套"],
            )
            plan = ChapterPlan(
                chapter_index=1,
                chapter_title="旧港回潮",
                purpose="拿回名单封套。",
                continuity_targets=["名单封套"],
                opening_image="雨夜旧港",
                closing_image="名单封套被掉包",
                closing_mode="hook",
                scenes=[SceneCard(scene_index=1, location="旧港", goal="拿回名单", conflict="被人盯上", turn="发现封套被调包")],
            )
            local_quality = LocalQualityReport(True, 94, [], ["动作明确"], "可用。", {})
            chapter_result = ChapterResult(
                index=1,
                volume_index=1,
                title="旧港回潮",
                outline_item=chapter,
                draft="正文。",
                plan=plan,
                review=ReviewFeedback(True, 93, ["通过"], [], [], "通过。"),
                local_quality=local_quality,
                continuity=ContinuityUpdate(
                    chapter_index=1,
                    chapter_summary="她拿回名单封套。",
                    new_threads=["名单线"],
                    resolved_threads=[],
                    timeline_events=["封套回到她手里"],
                    character_states=[],
                    next_chapter_targets=["核封套"],
                    must_remember=["名单封套已回手"],
                ),
                attempts=1,
                long_memory=LongRangeMemoryUpdate(chapter_index=1),
            )
            book_outline = BookOutline(
                title="测试小说",
                one_line_summary="名单再度浮出水面。",
                act_structure=["追查名单"],
                volumes=[VolumeBlueprint(index=1, start_chapter=1, end_chapter=1, title="第一卷", role="推进主线", central_question="名单去哪了", escalation="风险升级", emotional_shift="更主动")],
            )

            review = pipeline._finalize(spec, bible, book_outline, [chapter_result], ContinuityState(last_chapter_index=1))

            self.assertFalse(review.passed)
            self.assertEqual(review.score, 68)
            self.assertEqual(review.short_summary, "整书通过。")
            self.assertEqual(client.json_calls, 2)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_extract_long_memory_accepts_list_payload_blocks(self) -> None:
        class LongMemoryListClient(StubClient):
            def _default_json_payload(self, session_id: str | None):
                if session_id == "long-memory":
                    return None
                return super()._default_json_payload(session_id)

        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"long-memory-list-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            client = LongMemoryListClient(
                json_payloads=[
                    [
                        {
                            "promise_id": "p-1",
                            "label": "名单回收",
                            "thread": "名单线",
                            "current_status": "open",
                            "payoff_requirements": ["必须追回名单"],
                        },
                        {
                            "effect_label": "公开名单",
                            "cause": "她拿到账册",
                            "prerequisites": ["账册在手"],
                            "required_consequences": ["公开名单"],
                        },
                    ]
                ],
                text_payloads=[],
            )
            pipeline = NovelPipeline(client, temp_dir, flagship_model="gpt-flagship", light_model="gpt-light")
            spec = ProjectSpec(
                title="测试小说",
                genre="都市奇谭",
                audience="中文读者",
                tone="克制",
                premise="她追查一份名单。",
                theme="代价",
                hook="名单再度浮出水面。",
                setting="旧港",
                protagonist="沈雾",
                outline_hint="完整闭环",
                world_hint="设定服务剧情",
                ending_mode="standalone",
                pov="第三人称有限视角",
                target_total_chars=4000,
                target_chars_per_chapter=2000,
                chapter_count=2,
                volume_count=1,
                chapters_per_volume=2,
                style_examples=["克制"],
                must_include=["名单"],
                avoid=["作者按"],
                character_seeds=[CharacterSeed(name="沈雾", role="主角")],
            )
            bible = WorldBible(
                title="测试小说",
                logline="名单再度浮出水面。",
                setting_summary="旧港",
                core_conflict="她要追回被调包的名单。",
                theme_statement="代价决定真相值不值得追。",
                narrative_voice=["克制", "具体"],
                world_rules=["旧账必须留痕。"],
                chapter_guardrails=["每章都要推进名单线。"],
                ending_contract=["名单必须追回。"],
                major_threads=["名单线"],
                characters=[],
            )
            chapter = ChapterOutlineItem(
                index=2,
                volume_index=1,
                title="旧港回潮",
                purpose="拿回名单封套。",
                conflict="有人抢先一步。",
                beat_summary="她确认名单被调包。",
                ending_note="她看见留下的记号。",
                pov="第三人称有限视角",
                closing_mode="hook",
            )
            plan = ChapterPlan(
                chapter_index=2,
                chapter_title="旧港回潮",
                purpose="拿回名单封套。",
                continuity_targets=["名单回收"],
                opening_image="雨夜旧港",
                closing_image="封套被调包",
                closing_mode="hook",
                scenes=[SceneCard(scene_index=1, location="旧港", goal="拿回名单", conflict="被人盯上", turn="封套被调包")],
            )
            pipeline._long_memory_context = ContinuityState(active_threads=["名单线"], must_remember=["名单回收"])

            update = pipeline._extract_long_range_memory(spec, bible, chapter, plan, "正文。")

            self.assertEqual(update.chapter_index, 2)
            self.assertEqual(len(update.promise_updates), 1)
            self.assertEqual(update.promise_updates[0].promise_id, "p-1")
            self.assertEqual(len(update.causality_updates), 1)
            self.assertEqual(update.causality_updates[0].effect_label, "公开名单")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_extract_long_memory_falls_back_when_payload_stays_empty(self) -> None:
        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"long-memory-fallback-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            client = StubClient(
                json_payloads=[
                    ["只有散句，没有账本结构。"],
                    ["继续没有结构。"],
                    ["仍然不给账本字段。"],
                ],
                text_payloads=[],
            )
            pipeline = NovelPipeline(client, temp_dir, flagship_model="gpt-flagship", light_model="gpt-light")
            spec = ProjectSpec(
                title="测试小说",
                genre="都市奇谭",
                audience="中文读者",
                tone="克制",
                premise="她追查一份名单。",
                theme="代价",
                hook="名单再度浮出水面。",
                setting="旧港",
                protagonist="沈雾",
                outline_hint="完整闭环",
                world_hint="设定服务剧情",
                ending_mode="standalone",
                pov="第三人称有限视角",
                target_total_chars=4000,
                target_chars_per_chapter=2000,
                chapter_count=2,
                volume_count=1,
                chapters_per_volume=2,
                style_examples=["克制"],
                must_include=["名单"],
                avoid=["作者按"],
                character_seeds=[CharacterSeed(name="沈雾", role="主角")],
            )
            bible = WorldBible(
                title="测试小说",
                logline="名单再度浮出水面。",
                setting_summary="旧港",
                core_conflict="追查旧账",
                theme_statement="代价",
                narrative_voice=["克制"],
                world_rules=["规则一"],
                chapter_guardrails=["先写人再写制度"],
                ending_contract=["必须闭环"],
                major_threads=["名单线"],
                characters=[],
            )
            chapter = ChapterOutlineItem(
                index=2,
                volume_index=1,
                title="第2章",
                purpose="推进主线",
                conflict="冲突升级",
                beat_summary="她确认名单被调包。",
                ending_note="她要先保人再追账。",
                pov="第三人称",
                closing_mode="chapter_hook",
            )
            plan = ChapterPlan(
                chapter_index=2,
                chapter_title="第2章",
                purpose="推进主线",
                continuity_targets=["名单线"],
                opening_image="旧港夜雨",
                closing_image="她决定先保人再追账",
                closing_mode="chapter_hook",
                scenes=[SceneCard(scene_index=1, location="旧港", goal="确认名单", conflict="证据被调包", turn="决定追查")],
            )
            pipeline._long_memory_context = ContinuityState(active_threads=["名单线"], must_remember=["名单线"])

            update = pipeline._extract_long_range_memory(spec, bible, chapter, plan, "正文。")

            self.assertEqual(update.chapter_index, 2)
            self.assertEqual(update.promise_updates, [])
            self.assertEqual(update.causality_updates, [])
            self.assertTrue(
                (temp_dir / "state" / "chapter-02.long-memory-fallback.json").exists()
                or client.json_calls >= 1
            )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_build_chapter_room_regenerates_when_payload_has_no_effective_content(self) -> None:
        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"chapter-room-regenerate-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            client = StubClient(
                json_payloads=[
                    ["只给原则，不给纪要结构。"],
                    {
                        "notes": [
                            {
                                "agent": "continuity_guard",
                                "must_land": ["接住旧案线"],
                                "risks": ["前后文会打架"],
                                "summary": "必须把旧案线接住。",
                            },
                            {
                                "agent": "drama_editor",
                                "must_land": ["先落冲突，再抬风险"],
                                "risks": ["戏剧线过平"],
                                "summary": "中段要抬压。",
                            },
                            {
                                "agent": "style_guard",
                                "must_land": ["把术语压低"],
                                "risks": ["解释过多"],
                                "summary": "先写动作再解释。",
                            },
                        ],
                        "shared_mandates": ["先写动作，再写解释。"],
                        "blocking_issues": ["不能把旧案线写断。"],
                    },
                ],
                text_payloads=[],
            )
            pipeline = NovelPipeline(client, temp_dir, flagship_model="gpt-flagship", light_model="gpt-light")
            spec = ProjectSpec(
                title="测试小说",
                genre="都市奇谭",
                audience="中文读者",
                tone="克制",
                premise="她在旧楼里追一条旧案线。",
                theme="代价",
                hook="旧案再起。",
                setting="旧楼",
                protagonist="沈雾",
                outline_hint="完整闭环",
                world_hint="设定服务剧情",
                ending_mode="series",
                pov="第三人称有限视角",
                target_total_chars=300000,
                target_chars_per_chapter=3000,
                chapter_count=100,
                volume_count=10,
                chapters_per_volume=10,
                style_examples=["克制"],
                must_include=["旧案线"],
                avoid=["作者按"],
                character_seeds=[CharacterSeed(name="沈雾", role="主角")],
            )
            bible = WorldBible(
                title="测试小说",
                logline="旧案再起。",
                setting_summary="旧楼",
                core_conflict="她要把旧案线接住。",
                theme_statement="代价",
                narrative_voice=["克制"],
                world_rules=["旧案必须留痕。"],
                chapter_guardrails=["每章都要推进旧案线。"],
                ending_contract=["旧案线必须兑现。"],
                major_threads=["旧案线"],
                characters=[],
            )
            chapter = ChapterOutlineItem(
                index=3,
                volume_index=1,
                title="第三章",
                purpose="接住旧案线",
                conflict="现场变复杂",
                beat_summary="旧案线回到台面。",
                ending_note="她意识到对方抢先一步。",
                pov="第三人称有限视角",
                closing_mode="hook",
            )
            plan = ChapterPlan(
                chapter_index=3,
                chapter_title="第三章",
                purpose="接住旧案线",
                continuity_targets=["旧案线"],
                opening_image="天未亮透",
                closing_image="她意识到对方抢先一步",
                closing_mode="hook",
                scenes=[SceneCard(scene_index=1, location="档案室", goal="核对旧档", conflict="记录缺页", turn="发现对手抢先一步")],
            )

            room = pipeline._build_chapter_room(spec, bible, chapter, plan, {})

            self.assertEqual(len(room["notes"]), 3)
            self.assertEqual(room["shared_mandates"], ["先写动作，再写解释。"])
            self.assertIsNone(client.models_by_session["chapter-room"][-1])
            self.assertEqual(len(client.models_by_session["chapter-room"]), 2)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_build_chapter_room_falls_back_when_payload_stays_empty(self) -> None:
        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"chapter-room-fallback-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            client = StubClient(
                json_payloads=[
                    ["只给原则，不给纪要结构。"],
                    ["继续只给原则。"],
                    ["还是不给结构。"],
                ],
                text_payloads=[],
            )
            pipeline = NovelPipeline(client, temp_dir, flagship_model="gpt-flagship", light_model="gpt-light")
            spec = ProjectSpec(
                title="测试小说",
                genre="都市奇谭",
                audience="中文读者",
                tone="克制",
                premise="她在旧楼里追一条旧案线。",
                theme="代价",
                hook="旧案再起。",
                setting="旧楼",
                protagonist="沈雾",
                outline_hint="完整闭环",
                world_hint="设定服务剧情",
                ending_mode="series",
                pov="第三人称有限视角",
                target_total_chars=300000,
                target_chars_per_chapter=3000,
                chapter_count=100,
                volume_count=10,
                chapters_per_volume=10,
                style_examples=["克制"],
                must_include=["旧案线"],
                avoid=["作者按"],
                character_seeds=[CharacterSeed(name="沈雾", role="主角")],
            )
            bible = WorldBible(
                title="测试小说",
                logline="旧案再起。",
                setting_summary="旧楼",
                core_conflict="她要把旧案线接住。",
                theme_statement="代价",
                narrative_voice=["克制"],
                world_rules=["旧案必须留痕。"],
                chapter_guardrails=["每章都要推进旧案线。"],
                ending_contract=["旧案线必须兑现。"],
                major_threads=["旧案线"],
                characters=[],
            )
            chapter = ChapterOutlineItem(
                index=3,
                volume_index=1,
                title="第三章",
                purpose="接住旧案线",
                conflict="现场变复杂",
                beat_summary="旧案线回到台面。",
                ending_note="她意识到对方抢先一步。",
                pov="第三人称有限视角",
                closing_mode="hook",
                must_payoff=["旧案线"],
            )
            plan = ChapterPlan(
                chapter_index=3,
                chapter_title="第三章",
                purpose="接住旧案线",
                continuity_targets=["旧案线"],
                opening_image="天未亮透",
                closing_image="她意识到对方抢先一步",
                closing_mode="hook",
                scenes=[SceneCard(scene_index=1, location="档案室", goal="核对旧档", conflict="记录缺页", turn="发现对手抢先一步")],
            )

            room = pipeline._build_chapter_room(spec, bible, chapter, plan, {})

            self.assertEqual(len(room["notes"]), 3)
            self.assertIn("旧案线", room["shared_mandates"])
            self.assertTrue((temp_dir / "state" / "chapter-03.room-fallback.json").exists())
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_run_stagnation_judge_regenerates_when_payload_has_no_effective_content(self) -> None:
        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"stagnation-judge-regenerate-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            client = StubClient(
                json_payloads=[
                    ["只说要谨慎处理。"],
                    {
                        "verdict": "reasonable_cluster",
                        "recommended_action": "accept",
                        "confidence": 86,
                        "reason": "虽然同簇推进，但仍有新后果和新站位变化。",
                        "scope_start_chapter": 8,
                        "scope_end_chapter": 12,
                        "next_chapter_constraints": ["继续保持新后果输出。"],
                        "repair_goal": "",
                    },
                ],
                text_payloads=[],
            )
            pipeline = NovelPipeline(client, temp_dir, flagship_model="gpt-flagship", light_model="gpt-light")
            spec = ProjectSpec(
                title="测试小说",
                genre="都市奇谭",
                audience="中文读者",
                tone="克制",
                premise="公开局持续升级。",
                theme="代价",
                hook="旧案再起。",
                setting="旧楼",
                protagonist="沈雾",
                outline_hint="完整闭环",
                world_hint="设定服务剧情",
                ending_mode="series",
                pov="第三人称有限视角",
                target_total_chars=300000,
                target_chars_per_chapter=3000,
                chapter_count=100,
                volume_count=10,
                chapters_per_volume=10,
                style_examples=["克制"],
                must_include=["旧案线"],
                avoid=["作者按"],
                character_seeds=[CharacterSeed(name="沈雾", role="主角")],
            )
            bible = WorldBible(
                title="测试小说",
                logline="旧案再起。",
                setting_summary="旧楼",
                core_conflict="公开局持续升级。",
                theme_statement="代价",
                narrative_voice=["克制"],
                world_rules=["旧案必须留痕。"],
                chapter_guardrails=["每章都要推进旧案线。"],
                ending_contract=["旧案线必须兑现。"],
                major_threads=["旧案线"],
                characters=[],
            )
            chapter = ChapterOutlineItem(
                index=12,
                volume_index=2,
                title="第十二章",
                purpose="把公开局继续往前顶",
                conflict="对手继续加压",
                beat_summary="局势继续升级。",
                ending_note="她确认对方没收手。",
                pov="第三人称有限视角",
                closing_mode="hook",
                chapter_role="escalation",
            )
            plan = ChapterPlan(
                chapter_index=12,
                chapter_title="第十二章",
                purpose="把公开局继续往前顶",
                continuity_targets=["旧案线"],
                opening_image="天色压低",
                closing_image="她确认对方没收手",
                closing_mode="hook",
                scenes=[SceneCard(scene_index=1, location="旧楼", goal="接住旧线", conflict="被继续施压", turn="局势未停")],
                primary_propulsion="证据推进",
                variation_goal="通过新后果避免空转",
                chapter_role="escalation",
            )
            result = ChapterResult(
                index=12,
                volume_index=2,
                title="第十二章",
                outline_item=chapter,
                draft="正文。",
                plan=plan,
                review=ReviewFeedback(True, 90, [], [], [], "通过。"),
                local_quality=LocalQualityReport(True, 88, [], [], "可用。", {}),
                continuity=ContinuityUpdate(
                    chapter_index=12,
                    chapter_summary="局势继续升级。",
                    new_threads=[],
                    resolved_threads=[],
                    timeline_events=[],
                    character_states=[],
                    next_chapter_targets=[],
                    must_remember=[],
                ),
                attempts=1,
                long_memory=LongRangeMemoryUpdate(chapter_index=12),
            )

            review = pipeline._run_stagnation_judge(
                spec,
                bible,
                result,
                {
                    "chapter_index": 12,
                    "signal_level": "escalation",
                    "same_family_cluster": 10,
                    "metrics": {},
                },
                None,
                ContinuityState(last_volume_index=2, last_chapter_index=11),
                {},
                [],
            )

            self.assertEqual(review.verdict, "reasonable_cluster")
            self.assertEqual(review.recommended_action, "accept")
            self.assertEqual(client.models_by_session["judge-stagnation"][-1], "gpt-light")
            self.assertEqual(len(client.models_by_session["judge-stagnation"]), 2)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_run_stagnation_judge_retries_when_payload_is_semantically_contradictory(self) -> None:
        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"stagnation-judge-semantic-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            client = StubClient(
                json_payloads=[
                    {
                        "verdict": "true_stagnation",
                        "recommended_action": "arc_repair",
                        "confidence": 93,
                        "reason": "这段推进完整、自然、有效，当前写法成立。",
                        "scope_start_chapter": 8,
                        "scope_end_chapter": 12,
                        "next_chapter_constraints": ["继续保持当前推进节奏。"],
                        "repair_goal": "",
                    },
                    {
                        "verdict": "reasonable_cluster",
                        "recommended_action": "accept",
                        "confidence": 88,
                        "reason": "虽然同簇推进，但仍有新代价与新站位变化。",
                        "scope_start_chapter": 8,
                        "scope_end_chapter": 12,
                        "next_chapter_constraints": ["继续保持新后果输出。"],
                        "repair_goal": "",
                    },
                ],
                text_payloads=[],
            )
            pipeline = NovelPipeline(client, temp_dir, flagship_model="gpt-flagship", light_model="gpt-light")
            spec = ProjectSpec(
                title="测试小说",
                genre="都市奇谭",
                audience="中文读者",
                tone="克制",
                premise="公开局持续升级。",
                theme="代价",
                hook="旧案再起。",
                setting="旧楼",
                protagonist="沈雾",
                outline_hint="完整闭环",
                world_hint="设定服务剧情",
                ending_mode="series",
                pov="第三人称有限视角",
                target_total_chars=300000,
                target_chars_per_chapter=3000,
                chapter_count=100,
                volume_count=10,
                chapters_per_volume=10,
            )
            bible = WorldBible(
                title="测试小说",
                logline="旧案再起。",
                setting_summary="旧楼",
                core_conflict="公开局持续升级。",
                theme_statement="代价",
                narrative_voice=["克制"],
                world_rules=["旧案必须留痕。"],
                chapter_guardrails=["每章都要推进旧案线。"],
                ending_contract=["旧案线必须兑现。"],
                major_threads=["旧案线"],
                characters=[],
            )
            chapter = ChapterOutlineItem(
                index=12,
                volume_index=2,
                title="第十二章",
                purpose="把公开局继续往前顶",
                conflict="对手继续加压",
                beat_summary="局势继续升级。",
                ending_note="她确认对方没收手。",
                pov="第三人称有限视角",
                closing_mode="hook",
                chapter_role="escalation",
            )
            plan = ChapterPlan(
                chapter_index=12,
                chapter_title="第十二章",
                purpose="把公开局继续往前顶",
                continuity_targets=["旧案线"],
                opening_image="天色压低",
                closing_image="她确认对方没收手",
                closing_mode="hook",
                scenes=[SceneCard(scene_index=1, location="旧楼", goal="接住旧线", conflict="被继续施压", turn="局势未停")],
                primary_propulsion="证据推进",
                variation_goal="通过新后果避免空转",
                chapter_role="escalation",
            )
            result = ChapterResult(
                index=12,
                volume_index=2,
                title="第十二章",
                outline_item=chapter,
                draft="正文。",
                plan=plan,
                review=ReviewFeedback(True, 90, [], [], [], "通过。"),
                local_quality=LocalQualityReport(True, 88, [], [], "可用。", {}),
                continuity=ContinuityUpdate(
                    chapter_index=12,
                    chapter_summary="局势继续升级。",
                    new_threads=[],
                    resolved_threads=[],
                    timeline_events=[],
                    character_states=[],
                    next_chapter_targets=[],
                    must_remember=[],
                ),
                attempts=1,
                long_memory=LongRangeMemoryUpdate(chapter_index=12),
            )

            review = pipeline._run_stagnation_judge(
                spec,
                bible,
                result,
                {"chapter_index": 12, "signal_level": "escalation", "same_family_cluster": 10, "metrics": {}},
                None,
                ContinuityState(last_volume_index=2, last_chapter_index=11),
                {},
                [],
            )

            self.assertEqual(review.verdict, "reasonable_cluster")
            self.assertEqual(review.recommended_action, "accept")
            self.assertEqual(len(client.models_by_session["judge-stagnation"]), 2)
            self.assertIn("语义异常", client.user_prompts_by_session["judge-stagnation"][-1])
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_delivery_cleanup_removes_failed_snapshots_and_keeps_delivery_files(self) -> None:
        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"delivery-cleanup-{uuid.uuid4().hex}"
        state_dir = temp_dir / "state"
        data_dir = temp_dir / "data"
        state_dir.mkdir(parents=True, exist_ok=True)
        data_dir.mkdir(parents=True, exist_ok=True)
        try:
            (temp_dir / "novel.md").write_text("正式正文", encoding="utf-8")
            (temp_dir / "novel.txt").write_text("正式纯文本", encoding="utf-8")
            (temp_dir / "book-summary.md").write_text("正式简介", encoding="utf-8")
            (data_dir / "final-review.json").write_text("{}", encoding="utf-8")
            (state_dir / "chapter-180.failed.md").write_text("失败稿", encoding="utf-8")
            (state_dir / "chapter-180.failed.review.json").write_text("{}", encoding="utf-8")
            (state_dir / "final-review.latest.json").write_text("{}", encoding="utf-8")
            (state_dir / "final-state.preview.json").write_text("{}", encoding="utf-8")

            report = perform_delivery_cleanup(temp_dir, mode="manual")

            self.assertEqual(report["removed_count"], 4)
            self.assertFalse((state_dir / "chapter-180.failed.md").exists())
            self.assertFalse((state_dir / "chapter-180.failed.review.json").exists())
            self.assertFalse((state_dir / "final-review.latest.json").exists())
            self.assertFalse((state_dir / "final-state.preview.json").exists())
            self.assertTrue((temp_dir / "novel.md").exists())
            self.assertTrue((temp_dir / "novel.txt").exists())
            self.assertTrue((temp_dir / "book-summary.md").exists())
            self.assertTrue((data_dir / "delivery-cleanup.json").exists())
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_chapter_review_prompt_prefers_plan_over_stale_outline(self) -> None:
        spec = ProjectSpec(
            title="测试小说",
            genre="海洋悬疑",
            audience="中文读者",
            tone="克制",
            premise="有人在追旧账。",
            theme="代价",
            hook="一句话钩子",
            setting="沉月海",
            protagonist="桑提罗",
            outline_hint="完整闭环",
            world_hint="设定服务剧情",
            ending_mode="standalone",
            pov="第三人称有限视角",
            target_total_chars=4000,
            target_chars_per_chapter=2000,
            chapter_count=2,
            volume_count=1,
            chapters_per_volume=2,
            style_examples=["克制"],
            must_include=["证据链"],
            avoid=["下一本再说"],
            character_seeds=[CharacterSeed(name="桑提罗", role="主角")],
        )
        bible = WorldBible(
            title="测试小说",
            logline="一句话卖点",
            setting_summary="设定摘要",
            core_conflict="核心冲突",
            theme_statement="主题表达",
            narrative_voice=["克制"],
            world_rules=["规则一"],
            chapter_guardrails=["章节约束"],
            ending_contract=["结局约束"],
            major_threads=["主线"],
            characters=[],
        )
        chapter = ChapterOutlineItem(
            index=103,
            volume_index=6,
            title="签名页",
            purpose="推进夺取能锁死责任链的关键证据。",
            conflict="阿尔瓦封水在即。",
            beat_summary="桑提罗只带洛弥和老账手从退水暗缝潜下。",
            ending_note="发现名单索引。",
            pov="第三人称有限视角",
            closing_mode="chapter_hook",
            must_payoff=["拿到签名页"],
        )
        plan = ChapterPlan(
            chapter_index=103,
            chapter_title="签名页",
            purpose="推进夺取能锁死责任链的关键证据。",
            continuity_targets=["兑现桑提罗已决定立刻再潜，只带洛弥同行"],
            opening_image="桑提罗带洛弥俯身下去。",
            closing_image="名单索引露出儿子名字。",
            closing_mode="chapter_hook",
            scenes=[
                SceneCard(
                    scene_index=1,
                    location="退水缝入口",
                    goal="桑提罗带洛弥切入退水缝。",
                    conflict="封水彻底合拢前必须下潜。",
                    turn="桑提罗成功带洛弥滑入退水缝。",
                    must_include=["老账手留船拖住书记官"],
                )
            ],
        )

        prompt = chapter_review_user_prompt(
            spec,
            bible,
            StyleBible(tone_targets=["克制"]),
            chapter,
            plan,
            "正文",
            {"passed": True, "score": 100, "issues": [], "strengths": [], "short_summary": "", "metrics": {}},
            ContinuityState(must_remember=["桑提罗决定只带洛弥同行"]),
            [],
        )

        self.assertIn("若原始章节目标中的 beat_summary 与章节计划或当前连续性状态冲突，以章节计划和当前连续性状态为准。", prompt)
        self.assertIn("当前执行基准", prompt)
        self.assertIn("桑提罗带洛弥切入退水缝", prompt)

    def test_chapter_plan_prompt_includes_density_variation_and_grounding_controls(self) -> None:
        spec = ProjectSpec(
            title="遮海录",
            genre="东方悬疑玄幻",
            audience="中文读者",
            tone="冷峻",
            premise="一份旧名单把人拖回沉埋制度。",
            theme="代价与承担",
            hook="有人在替死人续签。",
            setting="灰港",
            protagonist="叶霜河",
            outline_hint="长线闭环",
            world_hint="设定服务冲突",
            ending_mode="standalone",
            pov="第三人称有限视角",
            target_total_chars=1000000,
            target_chars_per_chapter=2800,
            chapter_count=500,
            volume_count=20,
            chapters_per_volume=25,
            style_examples=["冷峻", "克制"],
            must_include=["证据链"],
            avoid=["作者说理"],
            character_seeds=[CharacterSeed(name="叶霜河", role="主角")],
        )
        bible = WorldBible(
            title="遮海录",
            logline="一句话卖点",
            setting_summary="设定摘要",
            core_conflict="核心冲突",
            theme_statement="主题表达",
            narrative_voice=["冷峻"],
            world_rules=["规则一"],
            chapter_guardrails=["每章推进"],
            ending_contract=["闭环"],
            major_threads=["黑碑线"],
            characters=[],
        )
        book_outline = BookOutline(title="遮海录", one_line_summary="一句话", act_structure=["起"], volumes=[])
        volume_outline = VolumeOutline(volume_index=1, title="第一卷", goal="起势", climax="揭碑", carry_over_threads=["黑碑线"], chapter_targets=[])
        chapter = ChapterOutlineItem(
            index=12,
            volume_index=1,
            title="灰港名册",
            purpose="推进名册线并建立地面代价。",
            conflict="名册会牵出更深制度链。",
            beat_summary="他先确认名册真假，再决定是否冒险公开。",
            ending_note="他没有立刻开口。",
            pov="第三人称有限视角",
            closing_mode="chapter_hook",
            must_payoff=["名册线"],
        )
        continuity = ContinuityState(active_threads=["名册线"], must_remember=["港税会压到普通人头上"])

        prompt = chapter_plan_user_prompt(
            spec,
            bible,
            book_outline,
            volume_outline,
            chapter,
            continuity,
            phase_brief={"phase": "early", "term_budget": "low", "grounding_focus": "写出路费和伤势。"},
            recent_propulsion_history=[
                {"chapter_index": 9, "primary_propulsion": "证据推进"},
                {"chapter_index": 10, "primary_propulsion": "证据推进"},
            ],
            logic_audit={"density_risks": ["前段术语偏密。"]},
        )

        self.assertIn("primary_propulsion", prompt)
        self.assertIn("variation_goal", prompt)
        self.assertIn("term_budget", prompt)
        self.assertIn("grounding_beat", prompt)
        self.assertIn("最近推进发动机历史", prompt)
        self.assertIn("前段术语偏密", prompt)
        self.assertIn("顶层必须是一个 JSON 对象", prompt)
        self.assertIn("场景字段名必须是 scenes", prompt)

    def test_story_memory_retrieval_prefers_relevant_prior_chapter(self) -> None:
        client = StubClient([], [])
        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"memory-retrieval-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            pipeline = NovelPipeline(client, temp_dir)
            chapter = ChapterOutlineItem(
                index=12,
                volume_index=2,
                title="旧影院名单",
                purpose="核对旧影院名单，锁定弟弟最后去向。",
                conflict="名单可能被人提前改过。",
                beat_summary="沈雾要把旧表里的回忆和旧影院名单对应起来。",
                ending_note="她确认弟弟曾到过后场。",
                pov="第三人称有限视角",
                closing_mode="chapter_hook",
                must_payoff=["旧影院名单", "弟弟去向"],
            )
            plan = ChapterPlan(
                chapter_index=12,
                chapter_title="旧影院名单",
                purpose="核对旧影院名单，锁定弟弟最后去向。",
                continuity_targets=["兑现旧影院线索", "锁定弟弟去向"],
                opening_image="湿冷的旧影院票房",
                closing_image="后场门锁上留下新划痕",
                closing_mode="chapter_hook",
                scenes=[
                    SceneCard(
                        scene_index=1,
                        location="旧影院票房",
                        goal="核对名单",
                        conflict="记录被人动过",
                        turn="她找到弟弟名字",
                        must_include=["旧影院名单"],
                    )
                ],
            )
            continuity = ContinuityState(
                active_threads=["旧影院线索", "弟弟去向"],
                must_remember=["旧表触发了与弟弟相关的回忆"],
                character_states=[CharacterState(name="沈雾", current_goal="核对旧影院名单", emotional_state="警惕", relationship_shift="更主动", risk="被人先一步清理证据", unresolved="弟弟最后去向")],
            )
            prior_irrelevant = ChapterResult(
                index=4,
                volume_index=1,
                title="海堤风向",
                outline_item=chapter,
                draft="",
                plan=plan,
                review=ReviewFeedback(True, 88, [], [], [], "通过。"),
                local_quality=LocalQualityReport(True, 90, [], [], "通过。", {}),
                continuity=ContinuityUpdate(
                    chapter_index=4,
                    chapter_summary="沈雾在海堤确认风向异常。",
                    new_threads=["海堤风向"],
                    resolved_threads=[],
                    timeline_events=["她记下风向异常"],
                    character_states=[],
                    next_chapter_targets=["继续查海堤"],
                    must_remember=["海堤风向异常"],
                ),
                attempts=1,
            )
            prior_relevant = ChapterResult(
                index=11,
                volume_index=2,
                title="旧影院门牌",
                outline_item=chapter,
                draft="",
                plan=plan,
                review=ReviewFeedback(True, 92, [], [], [], "通过。"),
                local_quality=LocalQualityReport(True, 93, [], [], "通过。", {}),
                continuity=ContinuityUpdate(
                    chapter_index=11,
                    chapter_summary="沈雾从旧表回忆里确认弟弟最后进了旧影院后场。",
                    new_threads=["旧影院线索", "弟弟去向"],
                    resolved_threads=[],
                    timeline_events=["她确认弟弟进入旧影院后场"],
                    character_states=[CharacterState(name="沈雾", current_goal="查旧影院名单", emotional_state="压着慌乱", relationship_shift="对旧案不再回避", risk="证据被毁", unresolved="弟弟最后去向")],
                    next_chapter_targets=["查旧影院名单"],
                    must_remember=["弟弟最后进了旧影院后场", "要核对旧影院名单"],
                ),
                attempts=1,
            )

            memories = pipeline._select_story_memories(chapter, plan, continuity, [prior_irrelevant, prior_relevant])

            self.assertTrue(memories)
            self.assertEqual(memories[0]["chapter_index"], 11)
            self.assertIn("旧影院", json.dumps(memories[0], ensure_ascii=False))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_volume_logic_audit_uses_streaming_json_and_writes_report(self) -> None:
        class RecordingClient:
            def __init__(self) -> None:
                self.calls: list[dict[str, object]] = []

            def generate_json(
                self,
                system_prompt,
                user_prompt,
                *,
                model=None,
                temperature=0.2,
                max_output_tokens=None,
                session_id=None,
                session_max_chars=None,
                provider_tier="flagship",
                stream=False,
                stream_observer=None,
            ):
                self.calls.append({"session_id": session_id, "stream": stream, "user_prompt": user_prompt})
                return {
                    "passed": True,
                    "summary": "主线与人物状态仍然稳定。",
                    "issues": [],
                    "watch_items": ["继续兑现旧影院名单和弟弟去向。"],
                    "required_followups": ["下一卷必须让旧影院名单转成现实证据链。"],
                    "flagged_chapters": [],
                }

            def generate_text(self, *args, **kwargs):
                raise AssertionError("generate_text should not be called in this test.")

            def reset_session(self, session_id: str) -> None:
                return

        client = RecordingClient()
        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"logic-audit-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            pipeline = NovelPipeline(client, temp_dir, review_model="gpt-review")
            spec = ProjectSpec(
                title="测试小说",
                genre="都市悬疑",
                audience="中文读者",
                tone="克制",
                premise="失物牵出旧案。",
                theme="面对过去",
                hook="旧影院名单会改写真相。",
                setting="海边旧城",
                protagonist="沈雾",
                outline_hint="完整闭环",
                world_hint="证据链必须可落地",
                ending_mode="standalone",
                pov="第三人称有限视角",
                target_total_chars=120000,
                target_chars_per_chapter=2500,
                chapter_count=24,
                volume_count=2,
                chapters_per_volume=12,
                style_examples=["克制"],
                must_include=["证据链"],
                avoid=["新案钩子"],
                character_seeds=[CharacterSeed(name="沈雾", role="主角")],
            )
            bible = WorldBible(
                title="测试小说",
                logline="一句话卖点",
                setting_summary="设定摘要",
                core_conflict="核心冲突",
                theme_statement="主题表达",
                narrative_voice=["克制"],
                world_rules=["规则一"],
                chapter_guardrails=["每章推进主线"],
                ending_contract=["主线闭环"],
                major_threads=["旧影院线索"],
                characters=[],
            )
            book_outline = BookOutline(
                title="测试小说",
                one_line_summary="一句话简介",
                act_structure=["开端", "推进", "收束"],
                volumes=[
                    VolumeBlueprint(1, 1, 12, "第一卷", "推进主线", "弟弟去向", "局势升级", "从回避到行动", ["旧影院线索"]),
                    VolumeBlueprint(2, 13, 24, "第二卷", "收束主线", "真相确认", "责任落地", "从行动到承担", ["证据链"]),
                ],
            )
            volume_outline = VolumeOutline(
                volume_index=1,
                title="第一卷",
                goal="推进旧影院线索",
                climax="找到名单",
                carry_over_threads=["旧影院线索"],
                chapter_targets=[],
            )
            chapters = [
                ChapterResult(
                    index=11,
                    volume_index=1,
                    title="旧影院门牌",
                    outline_item=ChapterOutlineItem(11, 1, "旧影院门牌", "推进名单线", "有人删改记录", "找到名单入口", "她决定继续查", "第三人称有限视角", "chapter_hook", ["旧影院名单"]),
                    draft="正文",
                    plan=ChapterPlan(11, "旧影院门牌", "推进名单线", ["旧影院线索"], "门牌滴水", "她看见后场门", "chapter_hook", []),
                    review=ReviewFeedback(True, 90, [], [], [], "通过。"),
                    local_quality=LocalQualityReport(True, 90, [], [], "通过。", {}),
                    continuity=ContinuityUpdate(11, "她确认旧影院名单被人动过。", ["旧影院名单"], [], ["她确认名单被动过"], [], ["查名单"], ["旧影院名单被动过"]),
                    attempts=1,
                )
            ]
            continuity = ContinuityState(
                active_threads=["旧影院线索", "名单被改动"],
                must_remember=["旧影院名单被动过"],
                last_volume_index=1,
                last_chapter_index=11,
            )

            audit = pipeline._audit_volume_logic(spec, bible, book_outline, volume_outline, chapters, continuity)

            self.assertIsNotNone(audit)
            self.assertEqual(client.calls[0]["session_id"], "logic-audit")
            self.assertEqual(client.calls[0]["stream"], True)
            self.assertTrue((temp_dir / "audits" / "volume-01.logic-audit.json").exists())
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_style_memory_retrieval_uses_style_bible_and_recent_excerpt(self) -> None:
        client = StubClient([], [])
        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"style-memory-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            pipeline = NovelPipeline(client, temp_dir)
            pipeline._style_bible = StyleBible(
                tone_targets=["克制", "压着情绪推进"],
                sample_passages=[
                    StylePassage(
                        label="雨夜证据推进",
                        use_case="chapter_hook",
                        text="雨点敲在档案盒边，她先看手里的证据，再决定要不要把话说完。",
                    ),
                    StylePassage(
                        label="轻松闲聊",
                        use_case="日常插科打诨",
                        text="大家围着桌子聊天，故意把紧张感全卸掉。",
                    ),
                ],
            )
            chapter = ChapterOutlineItem(
                index=18,
                volume_index=2,
                title="雨夜档案",
                purpose="在雨夜里核对档案，确认名单证据能不能直接落地。",
                conflict="只要说错一句，名单证据就会被人提前毁掉。",
                beat_summary="沈雾必须一边压住情绪，一边把证据链扣紧。",
                ending_note="她在档案封套里摸到新的缺页痕迹。",
                pov="第三人称有限视角",
                closing_mode="chapter_hook",
                must_payoff=["名单证据"],
            )
            plan = ChapterPlan(
                chapter_index=18,
                chapter_title="雨夜档案",
                purpose="核对名单证据。",
                continuity_targets=["名单证据", "雨夜对峙"],
                opening_image="雨打在旧档案柜上",
                closing_image="封套里多出一道缺页痕",
                closing_mode="chapter_hook",
                scenes=[],
            )
            prior = ChapterResult(
                index=17,
                volume_index=2,
                title="封套外侧",
                outline_item=chapter,
                draft=(
                    "雨敲在窗沿上，像有人不断提醒她别把那份名单当成纸。"
                    "沈雾没急着开口，只先把档案封套往灯下推，确认证据链上每个名字都还在原位。"
                ),
                plan=plan,
                review=ReviewFeedback(True, 92, [], [], [], "通过。"),
                local_quality=LocalQualityReport(True, 93, [], [], "通过。", {}),
                continuity=ContinuityUpdate(
                    chapter_index=17,
                    chapter_summary="她在封套外侧确认名单没有被调包。",
                    new_threads=["名单证据"],
                    resolved_threads=[],
                    timeline_events=["她保住了第一份名单"],
                    character_states=[],
                    next_chapter_targets=["继续核档"],
                    must_remember=["名单证据暂时安全"],
                ),
                attempts=1,
            )

            memories = pipeline._select_style_memories(chapter, plan, [prior])

            self.assertGreaterEqual(len(memories), 2)
            self.assertEqual(memories[0]["source"], "style_bible")
            self.assertIn("证据", memories[0]["text"])
            self.assertTrue(any(item["source"] == "chapter_excerpt" and item["chapter_index"] == 17 for item in memories))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_resume_backfills_style_and_voice_from_recent_chapters(self) -> None:
        class RecordingClient:
            def __init__(self) -> None:
                self.prompts: dict[str, str] = {}

            def generate_json(
                self,
                system_prompt,
                user_prompt,
                *,
                model=None,
                temperature=0.2,
                max_output_tokens=None,
                session_id=None,
                session_max_chars=None,
                provider_tier="flagship",
                stream=False,
                stream_observer=None,
            ):
                if session_id is not None:
                    self.prompts[session_id] = user_prompt
                if session_id == "planner-style":
                    return {
                        "audience_contract": ["读者期待快速进入主线。"],
                        "tone_targets": ["克制", "压着情绪推进"],
                        "pacing_rules": ["每章都要有实质推进。"],
                        "propulsion_rules": ["连续几章不要用同一种推进发动机。"],
                        "clarity_rules": ["前段先讲人和局势，再讲制度词。"],
                        "dialogue_rules": ["对白短，少废话。"],
                        "prose_rules": ["少解释，多动作。"],
                        "sensory_rules": ["保留潮气和灯光意象。"],
                        "thematic_subtext_rules": ["主题不要讲透。"],
                        "pressure_curve_rules": ["高压段之间留换气。"],
                        "grounding_rules": ["定期落回生活动作。"],
                        "taboo_phrases": ["作者按"],
                        "sample_passages": [
                            {"label": "证据推进", "use_case": "chapter_hook", "text": "她先压住呼吸，再把证据摆到灯下。"}
                        ],
                    }
                if session_id == "planner-voice":
                    return {
                        "voice_cards": [
                            {
                                "name": "沈雾",
                                "speech_rhythm": "短句",
                                "emotional_expression": "情绪不直说，落在停顿里",
                                "sentence_shape": "短句为主",
                                "social_register": "会先看场面再出声。",
                                "humor_style": "几乎不开玩笑。",
                                "silence_pattern": "先停一下再说。",
                                "contrast_anchor": "她的冷是收束信息，不是压人。",
                                "common_words": ["先等等"],
                                "tension_triggers": ["弟弟相关线索"],
                                "forbidden_drifts": ["不能突然话痨"],
                            }
                        ]
                    }
                raise AssertionError(f"Unexpected session_id: {session_id}")

            def generate_text(self, *args, **kwargs):
                raise AssertionError("generate_text should not be called in this test.")

            def reset_session(self, session_id: str) -> None:
                return

        client = RecordingClient()
        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"resume-backfill-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            pipeline = NovelPipeline(client, temp_dir, resume=True)
            pipeline._story_room = {"shared_contract": ["文风不能跳脱"]}
            spec = ProjectSpec(
                title="测试小说",
                genre="都市悬疑",
                audience="中文读者",
                tone="克制",
                premise="旧物牵出旧账。",
                theme="承担代价",
                hook="名单会改写真相。",
                setting="海边旧城",
                protagonist="沈雾",
                outline_hint="完整闭环",
                world_hint="设定服务剧情",
                ending_mode="standalone",
                pov="第三人称有限视角",
                target_total_chars=4000,
                target_chars_per_chapter=2000,
                chapter_count=2,
                volume_count=1,
                chapters_per_volume=2,
                style_examples=["克制", "潮湿"],
                must_include=["证据链"],
                avoid=["油滑腔调"],
                character_seeds=[CharacterSeed(name="沈雾", role="主角")],
            )
            bible = WorldBible(
                title="测试小说",
                logline="一句话卖点",
                setting_summary="设定摘要",
                core_conflict="核心冲突",
                theme_statement="主题表达",
                narrative_voice=["克制"],
                world_rules=["规则一"],
                chapter_guardrails=["每章推进主线"],
                ending_contract=["闭环"],
                major_threads=["名单线"],
                characters=[
                    CharacterProfile(
                        name="沈雾",
                        role="主角",
                        goal="查真相",
                        fear="失去家人",
                        contradiction="想知道又害怕知道",
                        arc="从回避到面对",
                        public_image="冷淡",
                        private_truth="自责",
                        speaking_style="简短",
                        signature_image="潮湿玻璃",
                        relationship_tensions=[],
                        do_not_break=["不能突然滔滔不绝"],
                    )
                ],
            )
            chapter = ChapterOutlineItem(12, 2, "旧影院名单", "推进名单线", "记录被改", "核对名单", "她确认去向", "第三人称有限视角", "chapter_hook", ["名单线"])
            plan = ChapterPlan(12, "旧影院名单", "推进名单线", ["名单线"], "旧影院票房", "后场门", "chapter_hook", [])
            previous = ChapterResult(
                index=11,
                volume_index=2,
                title="旧影院门牌",
                outline_item=chapter,
                draft="雨敲在窗沿上。沈雾没急着开口，只把名单封套往灯下推，先确认每一行还在不在。",
                plan=plan,
                review=ReviewFeedback(True, 92, [], [], [], "通过。"),
                local_quality=LocalQualityReport(True, 93, [], [], "通过。", {}),
                continuity=ContinuityUpdate(11, "她确认名单没有被调包。", ["名单线"], [], ["她保住了名单"], [], ["继续核对"], ["名单还在"]),
                attempts=1,
            )

            style_bible = pipeline._load_or_build_style_bible(spec, bible, [previous])
            voice_cards = pipeline._load_or_build_voice_cards(spec, bible, style_bible, [previous])

            self.assertEqual(style_bible.tone_targets[0], "克制")
            self.assertIn("连续几章不要用同一种推进发动机。", style_bible.propulsion_rules)
            self.assertIn("前段先讲人和局势，再讲制度词。", style_bible.clarity_rules)
            self.assertEqual(voice_cards[0].name, "沈雾")
            self.assertEqual(voice_cards[0].contrast_anchor, "她的冷是收束信息，不是压人。")
            self.assertIn("旧影院门牌", client.prompts["planner-style"])
            self.assertIn("名单封套", client.prompts["planner-style"])
            self.assertIn("沈雾", client.prompts["planner-voice"])
            self.assertIn("名单封套", client.prompts["planner-voice"])
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_resume_refreshes_existing_style_and_voice_when_metadata_is_missing(self) -> None:
        class RecordingClient:
            def __init__(self) -> None:
                self.prompts: dict[str, str] = {}

            def generate_json(
                self,
                system_prompt,
                user_prompt,
                *,
                model=None,
                temperature=0.2,
                max_output_tokens=None,
                session_id=None,
                session_max_chars=None,
                provider_tier="flagship",
                stream=False,
                stream_observer=None,
            ):
                if session_id is not None:
                    self.prompts[session_id] = user_prompt
                if session_id == "planner-style":
                    return {
                        "audience_contract": ["读者期待快速进入主线。"],
                        "tone_targets": ["克制", "潮湿"],
                        "pacing_rules": ["每章都要有实质推进。"],
                        "sample_passages": [
                            {"label": "雨夜证据", "use_case": "chapter_hook", "text": "雨压在窗上，她先看证据，再看人。"}
                        ],
                    }
                if session_id == "planner-voice":
                    return {
                        "voice_cards": [
                            {
                                "name": "沈雾",
                                "speech_rhythm": "短句",
                                "emotional_expression": "情绪落在动作和停顿里",
                                "sentence_shape": "短句为主",
                                "contrast_anchor": "她的冷是收束信息，不是压人。",
                            }
                        ]
                    }
                raise AssertionError(f"Unexpected session_id: {session_id}")

            def generate_text(self, *args, **kwargs):
                raise AssertionError("generate_text should not be called in this test.")

            def reset_session(self, session_id: str) -> None:
                return

        client = RecordingClient()
        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"resume-refresh-controls-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            pipeline = NovelPipeline(client, temp_dir, resume=True)
            pipeline._story_room = {"shared_contract": ["文风不能跳脱"]}
            (temp_dir / "data").mkdir(exist_ok=True)
            (temp_dir / "data" / "style-bible.json").write_text(
                json.dumps({"tone_targets": ["旧风格"]}, ensure_ascii=False),
                encoding="utf-8",
            )
            (temp_dir / "data" / "voice-cards.json").write_text(
                json.dumps([{"name": "沈雾", "speech_rhythm": "旧节奏"}], ensure_ascii=False),
                encoding="utf-8",
            )
            spec = ProjectSpec(
                title="测试小说",
                genre="都市悬疑",
                audience="中文读者",
                tone="克制",
                premise="旧物牵出旧账。",
                theme="承担代价",
                hook="名单会改写真相。",
                setting="海边旧城",
                protagonist="沈雾",
                outline_hint="完整闭环",
                world_hint="设定服务剧情",
                ending_mode="standalone",
                pov="第三人称有限视角",
                target_total_chars=4000,
                target_chars_per_chapter=2000,
                chapter_count=24,
                volume_count=2,
                chapters_per_volume=12,
                style_examples=["克制", "潮湿"],
                must_include=["证据链"],
                avoid=["油滑腔调"],
                character_seeds=[CharacterSeed(name="沈雾", role="主角")],
            )
            bible = WorldBible(
                title="测试小说",
                logline="一句话卖点",
                setting_summary="设定摘要",
                core_conflict="核心冲突",
                theme_statement="主题表达",
                narrative_voice=["克制"],
                world_rules=["规则一"],
                chapter_guardrails=["每章推进主线"],
                ending_contract=["闭环"],
                major_threads=["名单线"],
                characters=[
                    CharacterProfile(
                        name="沈雾",
                        role="主角",
                        goal="查真相",
                        fear="失去家人",
                        contradiction="想知道又害怕知道",
                        arc="从回避到面对",
                        public_image="冷淡",
                        private_truth="自责",
                        speaking_style="简短",
                        signature_image="潮湿玻璃",
                        relationship_tensions=[],
                        do_not_break=["不能突然滔滔不绝"],
                    )
                ],
            )
            chapter = ChapterOutlineItem(12, 2, "旧影院名单", "推进名单线", "记录被改", "核对名单", "她确认去向", "第三人称有限视角", "chapter_hook", ["名单线"])
            plan = ChapterPlan(12, "旧影院名单", "推进名单线", ["名单线"], "旧影院票房", "后场门", "chapter_hook", [])
            previous = ChapterResult(
                index=11,
                volume_index=2,
                title="旧影院门牌",
                outline_item=chapter,
                draft="雨敲在窗沿上。沈雾没急着开口，只把名单封套往灯下推，先确认每一行还在不在。",
                plan=plan,
                review=ReviewFeedback(True, 92, [], [], [], "通过。"),
                local_quality=LocalQualityReport(True, 93, [], [], "通过。", {}),
                continuity=ContinuityUpdate(11, "她确认名单没有被调包。", ["名单线"], [], ["她保住了名单"], [], ["继续核对"], ["名单还在"]),
                attempts=1,
            )

            style_bible = pipeline._load_or_build_style_bible(spec, bible, [previous])
            voice_cards = pipeline._load_or_build_voice_cards(spec, bible, style_bible, [previous])

            self.assertEqual(style_bible.tone_targets[0], "克制")
            self.assertEqual(voice_cards[0].name, "沈雾")
            self.assertIn("旧影院门牌", client.prompts["planner-style"])
            self.assertIn("名单封套", client.prompts["planner-voice"])
            self.assertTrue((temp_dir / "data" / "style-bible.meta.json").exists())
            self.assertTrue((temp_dir / "data" / "voice-cards.meta.json").exists())
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_resume_preserve_controls_reuses_existing_style_and_voice_without_refresh(self) -> None:
        class RecordingClient:
            def __init__(self) -> None:
                self.prompts: dict[str, str] = {}

            def generate_json(
                self,
                system_prompt,
                user_prompt,
                *,
                model=None,
                temperature=0.2,
                max_output_tokens=None,
                session_id=None,
                session_max_chars=None,
                provider_tier="flagship",
                stream=False,
                stream_observer=None,
            ):
                if session_id is not None:
                    self.prompts[session_id] = user_prompt
                raise AssertionError("generate_json should not be called when preserve_resume_controls=True.")

            def generate_text(self, *args, **kwargs):
                raise AssertionError("generate_text should not be called in this test.")

            def reset_session(self, session_id: str) -> None:
                return

        client = RecordingClient()
        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"resume-preserve-controls-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            pipeline = NovelPipeline(client, temp_dir, resume=True, preserve_resume_controls=True)
            pipeline._story_room = {"shared_contract": ["文风不能跳脱"]}
            (temp_dir / "data").mkdir(exist_ok=True)
            (temp_dir / "data" / "style-bible.json").write_text(
                json.dumps({"tone_targets": ["现有风格"], "audience_contract": ["保持现状"]}, ensure_ascii=False),
                encoding="utf-8",
            )
            (temp_dir / "data" / "style-bible.anchor.json").write_text(
                json.dumps({"tone_targets": ["锚点风格"], "audience_contract": ["保持现状"]}, ensure_ascii=False),
                encoding="utf-8",
            )
            (temp_dir / "data" / "style-bible.meta.json").write_text(
                json.dumps({"through_chapter": 3, "through_volume": 1}, ensure_ascii=False),
                encoding="utf-8",
            )
            (temp_dir / "data" / "voice-cards.json").write_text(
                json.dumps(
                    [
                        {
                            "name": "沈雾",
                            "speech_rhythm": "旧节奏",
                            "emotional_expression": "旧表达",
                            "sentence_shape": "短句为主",
                        }
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (temp_dir / "data" / "voice-cards.meta.json").write_text(
                json.dumps({"through_chapter": 3, "through_volume": 1}, ensure_ascii=False),
                encoding="utf-8",
            )
            spec = ProjectSpec(
                title="测试小说",
                genre="都市悬疑",
                audience="中文读者",
                tone="克制",
                premise="旧物牵出旧账。",
                theme="承担代价",
                hook="名单会改写真相。",
                setting="海边旧城",
                protagonist="沈雾",
                outline_hint="完整闭环",
                world_hint="设定服务剧情",
                ending_mode="standalone",
                pov="第三人称有限视角",
                target_total_chars=4000,
                target_chars_per_chapter=2000,
                chapter_count=24,
                volume_count=2,
                chapters_per_volume=12,
                style_examples=["克制", "潮湿"],
                must_include=["证据链"],
                avoid=["油滑腔调"],
                character_seeds=[CharacterSeed(name="沈雾", role="主角")],
            )
            bible = WorldBible(
                title="测试小说",
                logline="一句话卖点",
                setting_summary="设定摘要",
                core_conflict="核心冲突",
                theme_statement="主题表达",
                narrative_voice=["克制"],
                world_rules=["规则一"],
                chapter_guardrails=["每章推进主线"],
                ending_contract=["闭环"],
                major_threads=["名单线"],
                characters=[],
            )
            chapter = ChapterOutlineItem(12, 2, "旧影院名单", "推进名单线", "记录被改", "核对名单", "她确认去向", "第三人称有限视角", "chapter_hook", ["名单线"])
            plan = ChapterPlan(12, "旧影院名单", "推进名单线", ["名单线"], "旧影院票房", "后场门", "chapter_hook", [])
            previous = ChapterResult(
                index=11,
                volume_index=2,
                title="旧影院门牌",
                outline_item=chapter,
                draft="雨敲在窗沿上。沈雾没急着开口，只把名单封套往灯下推，先确认每一行还在不在。",
                plan=plan,
                review=ReviewFeedback(True, 92, [], [], [], "通过。"),
                local_quality=LocalQualityReport(True, 93, [], [], "通过。", {}),
                continuity=ContinuityUpdate(11, "她确认名单没有被调包。", ["名单线"], [], ["她保住了名单"], [], ["继续核对"], ["名单还在"]),
                attempts=1,
            )

            style_bible = pipeline._load_or_build_style_bible(spec, bible, [previous])
            voice_cards = pipeline._load_or_build_voice_cards(spec, bible, style_bible, [previous])

            self.assertEqual(style_bible.tone_targets[0], "现有风格")
            self.assertEqual(style_bible.audience_contract[0], "保持现状")
            self.assertEqual(voice_cards[0].name, "沈雾")
            self.assertEqual(voice_cards[0].speech_rhythm, "旧节奏")
            self.assertFalse(client.prompts)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_resume_reuses_existing_controls_when_metadata_lag_is_small_without_refresh(self) -> None:
        class RecordingClient:
            def generate_json(self, *args, **kwargs):
                raise AssertionError("generate_json should not be called when control lag is within the reuse threshold.")

            def generate_text(self, *args, **kwargs):
                raise AssertionError("generate_text should not be called in this test.")

            def reset_session(self, session_id: str) -> None:
                return

        client = RecordingClient()
        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"resume-small-lag-controls-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            pipeline = NovelPipeline(client, temp_dir, resume=True)
            pipeline._story_room = {"shared_contract": ["文风不能跳脱"]}
            (temp_dir / "data").mkdir(exist_ok=True)
            (temp_dir / "data" / "style-bible.json").write_text(
                json.dumps({"tone_targets": ["旧风格"], "audience_contract": ["旧契约"]}, ensure_ascii=False),
                encoding="utf-8",
            )
            (temp_dir / "data" / "style-bible.anchor.json").write_text(
                json.dumps({"tone_targets": ["锚点风格"], "audience_contract": ["锚点契约"]}, ensure_ascii=False),
                encoding="utf-8",
            )
            (temp_dir / "data" / "style-bible.meta.json").write_text(
                json.dumps({"through_chapter": 132, "through_volume": 3}, ensure_ascii=False),
                encoding="utf-8",
            )
            (temp_dir / "data" / "voice-cards.json").write_text(
                json.dumps(
                    [
                        {
                            "name": "沈雾",
                            "speech_rhythm": "旧节奏",
                            "emotional_expression": "旧表达",
                            "sentence_shape": "短句为主",
                        }
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (temp_dir / "data" / "voice-cards.meta.json").write_text(
                json.dumps({"through_chapter": 132, "through_volume": 3}, ensure_ascii=False),
                encoding="utf-8",
            )
            spec = ProjectSpec(
                title="测试小说",
                genre="都市悬疑",
                audience="中文读者",
                tone="克制",
                premise="旧物牵出旧账。",
                theme="承担代价",
                hook="名单会改写真相。",
                setting="海边旧城",
                protagonist="沈雾",
                outline_hint="完整闭环",
                world_hint="设定服务剧情",
                ending_mode="series",
                pov="第三人称有限视角",
                target_total_chars=400000,
                target_chars_per_chapter=4000,
                chapter_count=120,
                volume_count=10,
                chapters_per_volume=12,
                style_examples=["克制", "潮湿"],
                must_include=["证据链"],
                avoid=["油滑腔调"],
                character_seeds=[CharacterSeed(name="沈雾", role="主角")],
            )
            bible = WorldBible(
                title="测试小说",
                logline="一句话卖点",
                setting_summary="设定摘要",
                core_conflict="核心冲突",
                theme_statement="主题表达",
                narrative_voice=["克制"],
                world_rules=["规则一"],
                chapter_guardrails=["每章推进主线"],
                ending_contract=["闭环"],
                major_threads=["名单线"],
                characters=[],
            )
            chapter = ChapterOutlineItem(140, 4, "旧影院名单", "推进名单线", "记录被改", "核对名单", "她确认去向", "第三人称有限视角", "chapter_hook", ["名单线"])
            plan = ChapterPlan(140, "旧影院名单", "推进名单线", ["名单线"], "旧影院票房", "后场门", "chapter_hook", [])
            previous = ChapterResult(
                index=140,
                volume_index=4,
                title="旧影院门牌",
                outline_item=chapter,
                draft="雨敲在窗沿上。沈雾没急着开口，只把名单封套往灯下推，先确认每一行还在不在。",
                plan=plan,
                review=ReviewFeedback(True, 92, [], [], [], "通过。"),
                local_quality=LocalQualityReport(True, 93, [], [], "通过。", {}),
                continuity=ContinuityUpdate(140, "她确认名单没有被调包。", ["名单线"], [], ["她保住了名单"], [], ["继续核对"], ["名单还在"]),
                attempts=1,
            )

            style_bible = pipeline._load_or_build_style_bible(spec, bible, [previous])
            voice_cards = pipeline._load_or_build_voice_cards(spec, bible, style_bible, [previous])

            self.assertEqual(style_bible.tone_targets[0], "旧风格")
            self.assertEqual(style_bible.audience_contract[0], "旧契约")
            self.assertEqual(voice_cards[0].speech_rhythm, "旧节奏")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_resume_control_refresh_failure_falls_back_to_existing_controls(self) -> None:
        class FailingClient:
            def generate_json(self, *args, **kwargs):
                raise RuntimeError("Failed to read request body")

            def generate_text(self, *args, **kwargs):
                raise AssertionError("generate_text should not be called in this test.")

            def reset_session(self, session_id: str) -> None:
                return

        client = FailingClient()
        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"resume-control-fallback-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            pipeline = NovelPipeline(client, temp_dir, resume=True)
            pipeline._story_room = {"shared_contract": ["文风不能跳脱"]}
            (temp_dir / "data").mkdir(exist_ok=True)
            (temp_dir / "data" / "style-bible.json").write_text(
                json.dumps({"tone_targets": ["旧风格"], "audience_contract": ["旧契约"]}, ensure_ascii=False),
                encoding="utf-8",
            )
            (temp_dir / "data" / "style-bible.anchor.json").write_text(
                json.dumps({"tone_targets": ["锚点风格"], "audience_contract": ["锚点契约"]}, ensure_ascii=False),
                encoding="utf-8",
            )
            (temp_dir / "data" / "style-bible.meta.json").write_text(
                json.dumps({"through_chapter": 100, "through_volume": 2}, ensure_ascii=False),
                encoding="utf-8",
            )
            (temp_dir / "data" / "voice-cards.json").write_text(
                json.dumps(
                    [
                        {
                            "name": "沈雾",
                            "speech_rhythm": "旧节奏",
                            "emotional_expression": "旧表达",
                            "sentence_shape": "短句为主",
                        }
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (temp_dir / "data" / "voice-cards.meta.json").write_text(
                json.dumps({"through_chapter": 100, "through_volume": 2}, ensure_ascii=False),
                encoding="utf-8",
            )
            spec = ProjectSpec(
                title="测试小说",
                genre="都市悬疑",
                audience="中文读者",
                tone="克制",
                premise="旧物牵出旧账。",
                theme="承担代价",
                hook="名单会改写真相。",
                setting="海边旧城",
                protagonist="沈雾",
                outline_hint="完整闭环",
                world_hint="设定服务剧情",
                ending_mode="series",
                pov="第三人称有限视角",
                target_total_chars=400000,
                target_chars_per_chapter=4000,
                chapter_count=120,
                volume_count=10,
                chapters_per_volume=12,
                style_examples=["克制", "潮湿"],
                must_include=["证据链"],
                avoid=["油滑腔调"],
                character_seeds=[CharacterSeed(name="沈雾", role="主角")],
            )
            bible = WorldBible(
                title="测试小说",
                logline="一句话卖点",
                setting_summary="设定摘要",
                core_conflict="核心冲突",
                theme_statement="主题表达",
                narrative_voice=["克制"],
                world_rules=["规则一"],
                chapter_guardrails=["每章推进主线"],
                ending_contract=["闭环"],
                major_threads=["名单线"],
                characters=[],
            )
            chapter = ChapterOutlineItem(140, 4, "旧影院名单", "推进名单线", "记录被改", "核对名单", "她确认去向", "第三人称有限视角", "chapter_hook", ["名单线"])
            plan = ChapterPlan(140, "旧影院名单", "推进名单线", ["名单线"], "旧影院票房", "后场门", "chapter_hook", [])
            previous = ChapterResult(
                index=140,
                volume_index=4,
                title="旧影院门牌",
                outline_item=chapter,
                draft="雨敲在窗沿上。沈雾没急着开口，只把名单封套往灯下推，先确认每一行还在不在。",
                plan=plan,
                review=ReviewFeedback(True, 92, [], [], [], "通过。"),
                local_quality=LocalQualityReport(True, 93, [], [], "通过。", {}),
                continuity=ContinuityUpdate(140, "她确认名单没有被调包。", ["名单线"], [], ["她保住了名单"], [], ["继续核对"], ["名单还在"]),
                attempts=1,
            )

            style_bible = pipeline._load_or_build_style_bible(spec, bible, [previous])
            voice_cards = pipeline._load_or_build_voice_cards(spec, bible, style_bible, [previous])

            self.assertEqual(style_bible.tone_targets[0], "旧风格")
            self.assertEqual(style_bible.audience_contract[0], "旧契约")
            self.assertEqual(voice_cards[0].speech_rhythm, "旧节奏")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_style_bible_calibration_preserves_anchor_contract_and_blends_recent_adjustments(self) -> None:
        class WeightedStyleClient:
            def __init__(self) -> None:
                self.prompts: list[str] = []
                self.style_calls = 0

            def generate_json(
                self,
                system_prompt,
                user_prompt,
                *,
                model=None,
                temperature=0.2,
                max_output_tokens=None,
                session_id=None,
                session_max_chars=None,
                provider_tier="flagship",
                stream=False,
                stream_observer=None,
            ):
                if session_id != "planner-style":
                    raise AssertionError(f"Unexpected session_id: {session_id}")
                self.style_calls += 1
                self.prompts.append(user_prompt)
                if self.style_calls == 1:
                    return {
                        "audience_contract": ["男频长篇读者需要主线清晰并最终兑现。"],
                        "tone_targets": ["冷硬", "克制"],
                        "pacing_rules": ["每章必须完成一个清晰推进。"],
                        "propulsion_rules": ["线索推进要和关系推进轮换。"],
                        "clarity_rules": ["先写人在做什么，再解释制度词。"],
                        "dialogue_rules": ["对白短，重点落在信息差。"],
                        "prose_rules": ["叙述贴着动作走。"],
                        "sensory_rules": ["保留冷气、金属声和潮气。"],
                        "thematic_subtext_rules": ["主题藏在代价和选择里。"],
                        "pressure_curve_rules": ["高压后必须安排一段换气。"],
                        "grounding_rules": ["定期写食宿、伤势和账目。"],
                        "taboo_phrases": ["玩梗腔"],
                        "sample_passages": [
                            {
                                "label": "冷室账册",
                                "use_case": "压低情绪推进",
                                "text": "门一关，声响就剩下纸页摩擦。谁也没抢着开口，先动的是手里的账册。",
                            }
                        ],
                    }
                return {
                    "audience_contract": ["短视频读者需要每一段都立刻炸开。"],
                    "tone_targets": ["轻佻", "玩梗"],
                    "pacing_rules": ["每章都要快速回报。"],
                    "propulsion_rules": ["用关系推进兑现旧账。", "加入生活性债务压力。", "每章都开新节点。"],
                    "clarity_rules": ["一个场景最多只引入一个新术语。", "说明不能先于动作。", "制度词可以连续堆叠。"],
                    "dialogue_rules": ["对白里允许带一点黑色玩笑。"],
                    "prose_rules": ["句子可以略带锋利感。"],
                    "sensory_rules": ["在冷气之外加一点潮湿的黏滞。"],
                    "thematic_subtext_rules": ["主题只在关键抉择后收一下，不要盖过动作。"],
                    "pressure_curve_rules": ["高压段之间插入债务和休整，让压力落回地面。", "重大揭示后留半章消化。"],
                    "grounding_rules": ["把欠账、食水和药材消耗写到台面上。", "每卷至少安排一次完整的日常换气。", "每次都要回到集市买卖。"],
                    "taboo_phrases": ["口嗨式爽文腔"],
                    "sample_passages": [
                        {
                            "label": "债灯样例",
                            "use_case": "生活压力落点",
                            "text": "灯油只够再烧半夜，话要省，钱也要省。她把欠条压在碗底，先把伤口重新包好。",
                        },
                        {
                            "label": "人情换气",
                            "use_case": "卷间换气",
                            "text": "摊子刚支开，旧相识就把热汤放到她手边。谁都没提昨夜的事，风却先把沉默吹开了一角。",
                        },
                        {
                            "label": "节点禁用",
                            "use_case": "错误示范",
                            "text": "她一脚踏进新节点，世界又向下翻了一层。",
                        },
                    ],
                }

            def generate_text(self, *args, **kwargs):
                raise AssertionError("generate_text should not be called in this test.")

            def reset_session(self, session_id: str) -> None:
                return

        client = WeightedStyleClient()
        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"style-calibration-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            pipeline = NovelPipeline(client, temp_dir)
            pipeline._story_room = {"shared_contract": ["文风要稳定，不准换书感。"]}
            spec = ProjectSpec(
                title="测试小说",
                genre="玄幻悬疑",
                audience="男频长篇读者",
                tone="冷硬克制",
                premise="一册旧账牵出山门暗债。",
                theme="代价不能转嫁",
                hook="她欠的是灵石，挖出来的是旧账。",
                setting="山门外的矿镇与旧库",
                protagonist="沈雾",
                outline_hint="前中后段都要持续推进旧账主线，最后闭环。",
                world_hint="设定要服务债务主线。",
                ending_mode="standalone",
                pov="第三人称有限视角",
                target_total_chars=120000,
                target_chars_per_chapter=2500,
                chapter_count=24,
                volume_count=2,
                chapters_per_volume=12,
                style_examples=["冷硬", "克制"],
                must_include=["旧账", "债务压力"],
                avoid=["短视频口嗨腔"],
                character_seeds=[CharacterSeed(name="沈雾", role="主角")],
            )
            bible = WorldBible(
                title="测试小说",
                logline="一句话卖点",
                setting_summary="设定摘要",
                core_conflict="核心冲突",
                theme_statement="主题表达",
                narrative_voice=["冷硬", "克制"],
                world_rules=["规则一"],
                chapter_guardrails=["每章推进主线"],
                ending_contract=["主线闭环"],
                major_threads=["旧账线"],
                characters=[],
            )
            chapter = ChapterOutlineItem(12, 1, "旧库借灯", "推进旧账", "灯油告急", "她拿到旧账副本", "她决定追下去", "第三人称有限视角", "chapter_hook", ["旧账线"])
            plan = ChapterPlan(
                12,
                "旧库借灯",
                "推进旧账",
                ["旧账线"],
                "冷库门响",
                "灯火压低",
                "chapter_hook",
                [],
                primary_propulsion="关系推进",
                variation_goal="加入债务压力",
                term_budget="low",
                theme_visibility="subtext",
                grounding_beat="借灯和欠账",
            )
            previous = ChapterResult(
                index=11,
                volume_index=1,
                title="旧库借灯",
                outline_item=chapter,
                draft="灯油只剩半盏，她先把账册摊平，再去摸怀里的欠条。门外风大，谁都没把声音抬高。",
                plan=plan,
                review=ReviewFeedback(True, 92, [], [], [], "通过。"),
                local_quality=LocalQualityReport(True, 93, [], [], "通过。", {}),
                continuity=ContinuityUpdate(11, "她拿到账册副本。", ["旧账线"], [], ["账册副本到手"], [], ["继续核旧账"], ["她还欠着灯油钱"]),
                attempts=1,
            )

            anchor_style = pipeline._load_or_build_style_bible(spec, bible, [])
            calibrated_style = pipeline._load_or_build_style_bible(spec, bible, [previous])

            self.assertEqual(anchor_style.audience_contract, ["男频长篇读者需要主线清晰并最终兑现。"])
            self.assertEqual(calibrated_style.audience_contract, anchor_style.audience_contract)
            self.assertEqual(calibrated_style.tone_targets, anchor_style.tone_targets)
            self.assertIn("每章都要快速回报。", calibrated_style.pacing_rules)
            self.assertIn("用关系推进兑现旧账。", calibrated_style.propulsion_rules)
            self.assertIn("加入生活性债务压力。", calibrated_style.propulsion_rules)
            self.assertNotIn("每章都开新节点。", calibrated_style.propulsion_rules)
            self.assertIn("一个场景最多只引入一个新术语。", calibrated_style.clarity_rules)
            self.assertIn("说明不能先于动作。", calibrated_style.clarity_rules)
            self.assertNotIn("制度词可以连续堆叠。", calibrated_style.clarity_rules)
            self.assertTrue((temp_dir / "data" / "style-bible.anchor.json").exists())
            self.assertTrue((temp_dir / "data" / "style-bible.calibration.json").exists())

            calibration_report = json.loads((temp_dir / "data" / "style-bible.calibration.json").read_text(encoding="utf-8"))
            self.assertEqual(calibration_report["mode"], "weighted_calibration")
            self.assertEqual(calibration_report["anchor_weight"], 0.75)
            self.assertEqual(calibration_report["calibration_weight"], 0.25)
            self.assertIn("短视频读者需要每一段都立刻炸开。", calibration_report["blocked_adjustments"]["audience_contract"])
            self.assertIn("轻佻", calibration_report["blocked_adjustments"]["tone_targets"])
            self.assertIn("每章都开新节点。", calibration_report["blocked_adjustments"]["propulsion_rules"])
            self.assertIn("制度词可以连续堆叠。", calibration_report["blocked_adjustments"]["clarity_rules"])
            self.assertIn("用关系推进兑现旧账。", calibration_report["applied_adjustments"]["propulsion_rules"])
            self.assertIn("冷硬", client.prompts[1])
            self.assertIn("旧库借灯", client.prompts[1])
            self.assertIn("灯油只剩半盏", client.prompts[1])
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_weighted_style_rules_reserve_slots_for_calibration(self) -> None:
        anchor = StyleBible(
            audience_contract=["核心读者契约"],
            tone_targets=["冷硬", "克制"],
            pacing_rules=[f"anchor-{index}" for index in range(1, 7)],
            sample_passages=[StylePassage("anchor", "baseline", "基线样例")],
        )
        calibration = StyleBible(
            audience_contract=["不该替换主锚的读者契约"],
            tone_targets=["轻佻"],
            pacing_rules=["recent-1", "recent-2"],
            sample_passages=[StylePassage("recent", "volume", "近卷样例")],
        )
        merged, report = pipeline_module._blend_style_bibles(
            anchor,
            calibration,
            [ChapterResult(
                index=6,
                volume_index=2,
                title="卷末",
                outline_item=ChapterOutlineItem(6, 2, "卷末", "推进", "冲突", "节拍", "收束", "第三人称有限视角", "chapter_hook", []),
                draft="正文",
                plan=ChapterPlan(6, "卷末", "推进", [], "开头", "结尾", "chapter_hook", []),
                review=ReviewFeedback(True, 90, [], [], [], "通过。"),
                local_quality=LocalQualityReport(True, 90, [], [], "通过。", {}),
                continuity=ContinuityUpdate(6, "摘要", [], [], [], [], [], []),
                attempts=1,
            )],
        )

        self.assertEqual(merged.audience_contract, ["核心读者契约"])
        self.assertEqual(merged.tone_targets, ["冷硬", "克制"])
        self.assertEqual(len(merged.pacing_rules), 7)
        self.assertIn("recent-1", merged.pacing_rules)
        self.assertNotIn("recent-2", merged.pacing_rules)
        self.assertEqual(report["applied_adjustments"]["pacing_rules"], ["recent-1"])
        self.assertIn("recent-2", report["blocked_adjustments"]["pacing_rules"])
        self.assertTrue(any("不该替换主锚的读者契约" in item for item in report["blocked_adjustments"]["audience_contract"]))

    def test_story_room_alignment_appends_missing_constraints_to_world_bible(self) -> None:
        client = StubClient([], [])
        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"story-room-alignment-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            pipeline = NovelPipeline(client, temp_dir)
            pipeline._story_room = {
                "shared_contract": ["主线闭环", "文风克制"],
                "notes": [
                    {"agent": "world_architect", "must_hold": ["世界规则必须自洽"]},
                    {"agent": "plot_architect", "must_hold": ["结局必须回收旧名单"]},
                ],
            }
            bible = WorldBible(
                title="测试小说",
                logline="一句话卖点",
                setting_summary="设定摘要",
                core_conflict="核心冲突",
                theme_statement="主题表达",
                narrative_voice=["冷峻"],
                world_rules=["旧规则"],
                chapter_guardrails=["每章推进主线"],
                ending_contract=["闭环"],
                major_threads=["旧名单"],
                characters=[],
            )

            report = pipeline._align_world_with_story_room(bible)

            self.assertIn("主线闭环", bible.ending_contract)
            self.assertIn("文风克制", bible.narrative_voice)
            self.assertIn("世界规则必须自洽", bible.world_rules)
            self.assertIn("结局必须回收旧名单", bible.ending_contract)
            self.assertEqual(report["added_constraints"]["narrative_voice"], ["文风克制"])
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_overdue_promises_are_always_injected(self) -> None:
        client = StubClient([], [])
        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"overdue-promises-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            pipeline = NovelPipeline(client, temp_dir)
            pipeline._promise_ledger = [
                PromiseLedgerItem(
                    promise_id="p1",
                    label="旧名单必须兑现",
                    thread="旧名单",
                    chapter_opened=3,
                    target_volume=1,
                    current_status="open",
                    last_touched_chapter=8,
                    overdue=True,
                    deadline_state="overdue",
                ),
                PromiseLedgerItem(
                    promise_id="p2",
                    label="别的线索",
                    thread="旁支",
                    chapter_opened=6,
                    target_volume=2,
                    current_status="open",
                    last_touched_chapter=10,
                    overdue=False,
                    deadline_state="on_track",
                ),
            ]
            chapter = ChapterOutlineItem(12, 1, "新章", "推进名单", "冲突", "摘要", "结尾", "第三人称有限视角", "chapter_hook", ["旧名单"])
            continuity = ContinuityState(active_threads=["别的主线"], must_remember=["还欠旧名单回收"])

            memories = pipeline._select_promise_memories(chapter, None, continuity, limit=1)

            self.assertEqual(memories[0]["promise_id"], "p1")
            self.assertIn("高危", memories[0]["why"])
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_overdue_promise_injection_is_capped_and_keeps_guardrail(self) -> None:
        client = StubClient([], [])
        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"overdue-cap-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            pipeline = NovelPipeline(client, temp_dir)
            pipeline._promise_ledger = [
                PromiseLedgerItem(
                    promise_id=f"p{index}",
                    label=f"逾期承诺{index}",
                    thread="主线",
                    chapter_opened=index,
                    target_volume=1,
                    current_status="open",
                    last_touched_chapter=index,
                    overdue=True,
                )
                for index in range(1, 8)
            ]
            chapter = ChapterOutlineItem(20, 1, "新章", "推进旧账", "冲突", "摘要", "结尾", "第三人称有限视角", "chapter_hook", ["逾期承诺1"])
            continuity = ContinuityState(active_threads=["主线"], must_remember=["逾期承诺1"])

            memories = pipeline._select_promise_memories(chapter, None, continuity, limit=4)

            self.assertLessEqual(len(memories), 4)
            self.assertTrue(any("高危" in item.get("why", "") or "逾期" in item.get("why", "") for item in memories))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_recent_advanced_promises_are_not_kept_overdue(self) -> None:
        merged = pipeline_module._merge_promise_ledger(
            [
                PromiseLedgerItem(
                    promise_id="p1",
                    label="乙库线",
                    thread="主线",
                    chapter_opened=12,
                    target_volume=3,
                    current_status="open",
                    last_touched_chapter=44,
                    overdue=True,
                )
            ],
            [
                PromiseLedgerItem(
                    promise_id="p1",
                    label="乙库线",
                    thread="主线",
                    chapter_opened=12,
                    target_volume=3,
                    current_status="advanced",
                    last_touched_chapter=68,
                    overdue=True,
                )
            ],
            current_volume=4,
            current_chapter=68,
        )

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].current_status, "advanced")
        self.assertEqual(merged[0].deadline_state, "on_track")
        self.assertFalse(merged[0].overdue)

    def test_sync_runtime_views_writes_compact_runtime_files(self) -> None:
        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"runtime-views-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            pipeline = NovelPipeline(StubClient([], []), temp_dir)
            pipeline._style_bible = StyleBible(
                audience_contract=["男频强剧情", "爽点要兑现"],
                tone_targets=["克制", "凌厉"],
                pacing_rules=["每章推进"],
                propulsion_rules=["不要连续同构"],
                clarity_rules=["先讲行动"],
                dialogue_rules=["对白要短"],
                prose_rules=["动作里带情绪"],
                sensory_rules=[],
                thematic_subtext_rules=["主题压进代价"],
                pressure_curve_rules=["高压后换气"],
                grounding_rules=["保留生活面"],
                taboo_phrases=["作者按"],
                sample_passages=[StylePassage(label="样例", use_case="压住情绪", text="风吹过来，人先缩了缩肩。")],
            )
            pipeline._voice_cards = [
                CharacterVoiceCard(
                    name="沈雾",
                    speech_rhythm="短句",
                    emotional_expression="情绪压在动作里",
                    sentence_shape="短句为主",
                    social_register="先看场面再接话",
                    humor_style="少开玩笑",
                    silence_pattern="先停顿再落结论",
                    contrast_anchor="冷不是压人，是收信息",
                    common_words=["先等等"],
                    tension_triggers=["家人"],
                    forbidden_drifts=["不能突然滔滔不绝"],
                )
            ]
            continuity = ContinuityState(
                recent_summaries=["第一章推进", "第二章推进", "第三章推进", "第四章推进", "第五章推进"],
                active_threads=["旧账", "欠债", "追兵"],
                must_remember=["名单还没回收"],
                last_chapter_index=5,
            )

            pipeline._sync_runtime_views(continuity)

            style_runtime = json.loads(pipeline.store.style_bible_runtime_path().read_text(encoding="utf-8"))
            voice_runtime = json.loads(pipeline.store.voice_cards_runtime_path().read_text(encoding="utf-8"))
            continuity_runtime = json.loads(pipeline.store.continuity_runtime_path().read_text(encoding="utf-8"))

            self.assertIn("audience_contract", style_runtime)
            self.assertLessEqual(len(style_runtime["sample_passages"]), 2)
            self.assertEqual(voice_runtime[0]["name"], "沈雾")
            self.assertLessEqual(len(continuity_runtime["recent_summaries"]), 4)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_generate_chapter_writes_execution_packet(self) -> None:
        client = StubClient([], ["门内先响了一声，沈雾才抬头。"])
        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"execution-packet-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        original_analyze = pipeline_module.analyze_chapter
        try:
            pipeline = NovelPipeline(client, temp_dir)
            pipeline_module.analyze_chapter = lambda *args, **kwargs: LocalQualityReport(True, 95, [], [], "通过。", {})  # type: ignore[assignment]
            pipeline._style_bible = StyleBible(
                audience_contract=["中文读者"],
                tone_targets=["克制"],
                pacing_rules=["每章推进"],
                dialogue_rules=["对白短"],
                prose_rules=["动作先行"],
            )
            pipeline._voice_cards = [
                CharacterVoiceCard(
                    name="沈雾",
                    speech_rhythm="短句",
                    emotional_expression="压着说",
                    sentence_shape="短句",
                    social_register="普通",
                    humor_style="几乎没有",
                    silence_pattern="先停一下",
                    contrast_anchor="冷静",
                    common_words=["先等等"],
                    tension_triggers=["旧账"],
                    forbidden_drifts=["突然长篇大论"],
                )
            ]
            continuity = ContinuityState(active_threads=["旧账"], must_remember=["名单要回收"], last_chapter_index=0)
            pipeline._sync_runtime_views(continuity)
            pipeline._build_chapter_room = lambda *args, **kwargs: {"shared_mandates": ["推进旧账"], "blocking_issues": []}  # type: ignore[method-assign]
            pipeline._review_chapter = lambda *args, **kwargs: ReviewFeedback(True, 95, [], [], [], "通过。")  # type: ignore[method-assign]
            pipeline._extract_continuity = lambda *args, **kwargs: ContinuityUpdate(1, "推进旧账。", ["旧账"], [], ["发现名单"], [], ["继续查"], ["名单要回收"])  # type: ignore[method-assign]
            pipeline._extract_long_range_memory = lambda *args, **kwargs: LongRangeMemoryUpdate(1, [], [])  # type: ignore[method-assign]
            spec = ProjectSpec(
                title="测试小说",
                genre="悬疑",
                audience="中文读者",
                tone="克制",
                premise="旧账浮起。",
                theme="代价",
                hook="旧名单再次出现。",
                setting="旧港",
                protagonist="沈雾",
                outline_hint="完整闭环",
                world_hint="设定服务剧情",
                ending_mode="standalone",
                pov="第三人称有限视角",
                target_total_chars=4000,
                target_chars_per_chapter=2000,
                chapter_count=2,
                volume_count=1,
                chapters_per_volume=2,
            )
            bible = WorldBible(
                title="测试小说",
                logline="旧名单再次出现。",
                setting_summary="旧港",
                core_conflict="旧账浮起",
                theme_statement="代价",
                narrative_voice=["克制"],
                world_rules=["别把设定写满"],
                chapter_guardrails=["推进旧账"],
                ending_contract=["名单要回收"],
                major_threads=["旧账"],
                characters=[CharacterProfile(name="沈雾", role="主角", goal="追回名单", fear="失手", contradiction="想查又怕牵连人", arc="面对旧账", public_image="冷静", private_truth="不安", speaking_style="短句", signature_image="潮湿的名单")],
            )
            chapter = ChapterOutlineItem(1, 1, "名单", "推进旧账", "追兵逼近", "确认名单真假", "门外有人", "第三人称有限视角", "chapter_hook", ["名单"])
            plan = ChapterPlan(
                chapter_index=1,
                chapter_title="名单",
                purpose="推进旧账",
                continuity_targets=["名单要回收"],
                opening_image="门内先响了一声。",
                closing_image="门外脚步停了。",
                closing_mode="chapter_hook",
                scenes=[SceneCard(scene_index=1, location="旧屋", goal="确认名单", conflict="追兵逼近", turn="名单是真的", must_include=["潮湿纸页"])],
                primary_propulsion="证据推进",
                variation_goal="压低解释，先写动作",
                term_budget="low",
                theme_visibility="subtext",
                grounding_beat="纸页潮湿黏手",
            )

            pipeline._generate_chapter(spec, bible, chapter, plan, continuity, [])

            packet_path = pipeline.store.chapter_execution_path(1)
            self.assertTrue(packet_path.exists())
            packet = json.loads(packet_path.read_text(encoding="utf-8"))
            self.assertIn("chapter", packet)
            self.assertIn("style", packet)
            self.assertIn("voices", packet)
        finally:
            pipeline_module.analyze_chapter = original_analyze  # type: ignore[assignment]
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_long_memory_prompt_uses_relevant_subset_not_full_ledger(self) -> None:
        class RecordingClient(StubClient):
            def __init__(self) -> None:
                super().__init__(json_payloads=[], text_payloads=[])
                self.long_memory_prompt = ""

            def generate_json(self, system_prompt, user_prompt, **kwargs):
                if kwargs.get("session_id") == "long-memory":
                    self.long_memory_prompt = user_prompt
                return super().generate_json(system_prompt, user_prompt, **kwargs)

        client = RecordingClient()
        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"long-memory-subset-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            pipeline = NovelPipeline(client, temp_dir)
            pipeline._promise_ledger = [
                PromiseLedgerItem("p1", "名单回收", "主线", 1, 1, "open", 6, True),
                PromiseLedgerItem("p2", "掌柜旧债", "支线", 2, 1, "open", 5, False),
                PromiseLedgerItem("p3", "遥远北地副线", "远线", 3, 3, "open", 3, False),
            ]
            pipeline._causality_graph = [
                CausalityEdge("名单被补写", "有人提前动手", ["名单存在"], ["必须查补写人"], 4, 6),
                CausalityEdge("北地雪灾", "边军断粮", ["北地"], ["后文处理"], 3, 3),
            ]
            pipeline._long_memory_context = ContinuityState(active_threads=["名单"], must_remember=["查补写人"], last_chapter_index=7)
            spec = ProjectSpec(
                title="测试小说",
                genre="悬疑",
                audience="中文读者",
                tone="克制",
                premise="名单回收。",
                theme="代价",
                hook="名单再次出现。",
                setting="旧港",
                protagonist="沈雾",
                outline_hint="完整闭环",
                world_hint="设定服务剧情",
                ending_mode="standalone",
                pov="第三人称有限视角",
                target_total_chars=4000,
                target_chars_per_chapter=2000,
                chapter_count=2,
                volume_count=1,
                chapters_per_volume=2,
            )
            bible = WorldBible("测试小说", "名单再次出现。", "旧港", "名单回收", "代价", ["克制"], ["规则"], ["护栏"], ["名单回收"], ["旧账"], [])
            chapter = ChapterOutlineItem(8, 1, "追查", "追查补写人", "追兵逼近", "推进名单线", "门外有脚步", "第三人称有限视角", "chapter_hook", ["名单回收"])
            plan = ChapterPlan(
                chapter_index=8,
                chapter_title="追查",
                purpose="推进名单线",
                continuity_targets=["名单回收"],
                opening_image="门外有脚步。",
                closing_image="她决定先去码头。",
                closing_mode="chapter_hook",
                scenes=[SceneCard(1, "旧屋", "追查补写人", "追兵", "她先去码头", ["补写痕迹"])],
                primary_propulsion="证据推进",
                variation_goal="少解释",
                term_budget="low",
                theme_visibility="subtext",
                grounding_beat="门轴发涩",
            )

            pipeline._extract_long_range_memory(spec, bible, chapter, plan, "她看着名单边角。")

            self.assertIn("相关承诺账本子集", client.long_memory_prompt)
            self.assertIn("名单回收", client.long_memory_prompt)
            self.assertNotIn("遥远北地副线", client.long_memory_prompt)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_logic_audit_starts_at_twelve_chapters(self) -> None:
        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"logic-threshold-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            pipeline = NovelPipeline(StubClient([], []), temp_dir)
            spec = ProjectSpec(
                title="测试小说",
                genre="悬疑",
                audience="中文读者",
                tone="克制",
                premise="旧案浮起。",
                theme="承担",
                hook="名单再次出现。",
                setting="旧港",
                protagonist="沈雾",
                outline_hint="完整闭环",
                world_hint="设定服务剧情",
                ending_mode="standalone",
                pov="第三人称有限视角",
                target_total_chars=24000,
                target_chars_per_chapter=2000,
                chapter_count=12,
                volume_count=1,
                chapters_per_volume=12,
            )

            self.assertTrue(pipeline._should_run_logic_audit(spec))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_build_plan_backfills_extended_controls_for_legacy_payload(self) -> None:
        client = StubClient(
            [
                {
                    "chapter_index": 5,
                    "chapter_title": "旧码头",
                    "purpose": "推进旧账线",
                    "continuity_targets": ["旧账线"],
                    "opening_image": "他踩上湿木板。",
                    "closing_image": "他决定不再等天亮。",
                    "closing_mode": "chapter_hook",
                    "scenes": [
                        {
                            "scene_index": 1,
                            "location": "旧码头",
                            "goal": "确认名单是真是假",
                            "conflict": "潮水抹掉字迹",
                            "turn": "他发现名单被补写过",
                            "must_include": ["名单边角的泥痕"],
                        }
                    ],
                }
            ],
            [],
        )
        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"legacy-plan-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            pipeline = NovelPipeline(client, temp_dir)
            spec = ProjectSpec(
                title="测试小说",
                genre="悬疑",
                audience="中文读者",
                tone="克制",
                premise="有人在追旧账。",
                theme="代价",
                hook="旧名册再次出现。",
                setting="旧港",
                protagonist="沈雾",
                outline_hint="完整闭环",
                world_hint="设定服务剧情",
                ending_mode="standalone",
                pov="第三人称有限视角",
                target_total_chars=1000000,
                target_chars_per_chapter=2400,
                chapter_count=500,
                volume_count=20,
                chapters_per_volume=25,
                style_examples=["克制"],
                must_include=["旧账线"],
                avoid=["空讲规则"],
                character_seeds=[CharacterSeed(name="沈雾", role="主角")],
            )
            bible = WorldBible(
                title="测试小说",
                logline="一句话卖点",
                setting_summary="设定摘要",
                core_conflict="核心冲突",
                theme_statement="主题表达",
                narrative_voice=["克制"],
                world_rules=["规则一"],
                chapter_guardrails=["章节约束"],
                ending_contract=["结局约束"],
                major_threads=["旧账线"],
                characters=[],
            )
            book_outline = BookOutline(
                title="测试小说",
                one_line_summary="一句话简介",
                act_structure=["起"],
                volumes=[VolumeBlueprint(1, 1, 25, "第一卷", "推进主线", "旧账是真是假", "局势升级", "情绪收紧", ["旧账线"])],
            )
            chapter = ChapterOutlineItem(
                index=5,
                volume_index=1,
                title="旧码头",
                purpose="推进旧账线并确认名册真假。",
                conflict="制度痕迹太多，读者需要先看懂人在做什么。",
                beat_summary="他踩上旧码头，先护住名册，再决定是否公开。",
                ending_note="他决定今晚不回去。",
                pov="第三人称有限视角",
                closing_mode="chapter_hook",
                must_payoff=["旧账线"],
            )
            volume_outline = VolumeOutline(1, "第一卷", "推进主线", "揭出旧账", ["旧账线"], [chapter])
            continuity = ContinuityState(active_threads=["旧账线"], must_remember=["先保名册，再谈制度"])

            plan = pipeline._build_plan(spec, bible, book_outline, volume_outline, chapter, continuity, [])

            self.assertEqual(plan.term_budget, "low")
            self.assertEqual(plan.theme_visibility, "subtext")
            self.assertTrue(plan.primary_propulsion)
            self.assertTrue(plan.variation_goal)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_build_plan_accepts_scene_array_payload(self) -> None:
        class SceneArrayClient:
            def generate_json(
                self,
                system_prompt,
                user_prompt,
                *,
                model=None,
                temperature=0.2,
                max_output_tokens=None,
                session_id=None,
                session_max_chars=None,
                provider_tier="flagship",
                stream=False,
                stream_observer=None,
            ):
                if session_id != "planner-chapter-1":
                    raise AssertionError(f"Unexpected session_id: {session_id}")
                return [
                    {
                        "scene_index": 1,
                        "location": "旧库门口",
                        "goal": "确认借灯名单",
                        "conflict": "门房不肯放人",
                        "turn": "她拿旧欠条换到半刻钟空档",
                        "must_include": ["旧欠条"],
                    },
                    {
                        "scene_index": 2,
                        "location": "冷库内侧",
                        "goal": "核对账册缺口",
                        "conflict": "灯油快灭",
                        "turn": "她发现旧账被人提前动过",
                        "must_include": ["账册缺页"],
                    },
                ]

            def generate_text(self, *args, **kwargs):
                raise AssertionError("generate_text should not be called in this test.")

            def reset_session(self, session_id: str) -> None:
                return

        client = SceneArrayClient()
        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"scene-array-plan-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            pipeline = NovelPipeline(client, temp_dir)
            spec = ProjectSpec(
                title="测试小说",
                genre="悬疑",
                audience="中文读者",
                tone="克制",
                premise="旧账牵出旧案。",
                theme="代价",
                hook="借灯名单里少了一页。",
                setting="矿镇旧库",
                protagonist="沈雾",
                outline_hint="完整闭环",
                world_hint="设定服务剧情",
                ending_mode="standalone",
                pov="第三人称有限视角",
                target_total_chars=10000,
                target_chars_per_chapter=2500,
                chapter_count=4,
                volume_count=1,
                chapters_per_volume=4,
                style_examples=["克制"],
                must_include=["旧账"],
                avoid=["油滑腔"],
                character_seeds=[CharacterSeed(name="沈雾", role="主角")],
            )
            bible = WorldBible(
                title="测试小说",
                logline="一句话卖点",
                setting_summary="设定摘要",
                core_conflict="核心冲突",
                theme_statement="主题表达",
                narrative_voice=["克制"],
                world_rules=["规则一"],
                chapter_guardrails=["每章推进主线"],
                ending_contract=["闭环"],
                major_threads=["旧账线"],
                characters=[],
            )
            book_outline = BookOutline(
                title="测试小说",
                one_line_summary="一句话简介",
                act_structure=["开端", "推进", "收束"],
                volumes=[VolumeBlueprint(1, 1, 4, "第一卷", "推进主线", "旧账去哪了", "局势升级", "从回避到追查", ["旧账线"])],
            )
            volume_outline = VolumeOutline(
                volume_index=1,
                title="第一卷",
                goal="推进旧账线",
                climax="账册缺页被确认",
                carry_over_threads=["旧账线"],
                chapter_targets=[],
            )
            chapter = ChapterOutlineItem(
                1,
                1,
                "旧库借灯",
                "推进旧账",
                "借灯名单被扣",
                "她拿旧欠条换进门机会",
                "她发现账册缺页",
                "第三人称有限视角",
                "chapter_hook",
                ["旧账线"],
            )

            plan = pipeline._build_plan(spec, bible, book_outline, volume_outline, chapter, ContinuityState())

            self.assertEqual(plan.chapter_index, 1)
            self.assertEqual(plan.chapter_title, "旧库借灯")
            self.assertEqual(len(plan.scenes), 2)
            self.assertEqual(plan.scenes[0].location, "旧库门口")
            self.assertEqual(plan.scenes[1].must_include, ["账册缺页"])
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_build_plan_repairs_misaligned_plan_shape_via_normalizer(self) -> None:
        client = StubClient(
            [
                [
                    {"chapter_title": "旧库借灯"},
                    {"purpose": "推进旧账"},
                    {
                        "scene_payload_blocks": [
                            {
                                "scene_index": 1,
                                "location": "旧库门口",
                                "goal": "确认借灯名单",
                                "conflict": "门房不肯放人",
                                "turn": "她拿旧欠条换到半刻钟空档",
                                "must_include": ["旧欠条"],
                            }
                        ],
                    },
                ],
                {
                    "chapter_title": "旧库借灯",
                    "purpose": "推进旧账",
                    "scenes": [
                        {
                            "scene_index": 1,
                            "location": "旧库门口",
                            "goal": "确认借灯名单",
                            "conflict": "门房不肯放人",
                            "turn": "她拿旧欠条换到半刻钟空档",
                            "must_include": ["旧欠条"],
                        }
                    ],
                },
            ],
            [],
        )
        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"plan-normalizer-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            pipeline = NovelPipeline(client, temp_dir, flagship_model="flagship-model", light_model="light-model")
            spec = ProjectSpec(
                title="测试小说",
                genre="悬疑",
                audience="中文读者",
                tone="克制",
                premise="旧账牵出旧案。",
                theme="代价",
                hook="借灯名单里少了一页。",
                setting="矿镇旧库",
                protagonist="沈雾",
                outline_hint="完整闭环",
                world_hint="设定服务剧情",
                ending_mode="standalone",
                pov="第三人称有限视角",
                target_total_chars=10000,
                target_chars_per_chapter=2500,
                chapter_count=4,
                volume_count=1,
                chapters_per_volume=4,
                style_examples=["克制"],
                must_include=["旧账"],
                avoid=["油滑腔"],
                character_seeds=[CharacterSeed(name="沈雾", role="主角")],
            )
            bible = WorldBible(
                title="测试小说",
                logline="一句话卖点",
                setting_summary="设定摘要",
                core_conflict="核心冲突",
                theme_statement="主题表达",
                narrative_voice=["克制"],
                world_rules=["规则一"],
                chapter_guardrails=["每章推进主线"],
                ending_contract=["闭环"],
                major_threads=["旧账线"],
                characters=[],
            )
            book_outline = BookOutline(
                title="测试小说",
                one_line_summary="一句话简介",
                act_structure=["开端", "推进", "收束"],
                volumes=[VolumeBlueprint(1, 1, 4, "第一卷", "推进主线", "旧账去哪了", "局势升级", "从回避到追查", ["旧账线"])],
            )
            volume_outline = VolumeOutline(
                volume_index=1,
                title="第一卷",
                goal="推进旧账线",
                climax="账册缺页被确认",
                carry_over_threads=["旧账线"],
                chapter_targets=[],
            )
            chapter = ChapterOutlineItem(
                1,
                1,
                "旧库借灯",
                "推进旧账",
                "借灯名单被扣",
                "她拿旧欠条换进门机会",
                "她发现账册缺页",
                "第三人称有限视角",
                "chapter_hook",
                ["旧账线"],
            )

            plan = pipeline._build_plan(spec, bible, book_outline, volume_outline, chapter, ContinuityState())

            self.assertEqual(len(plan.scenes), 1)
            self.assertEqual(plan.scenes[0].location, "旧库门口")
            self.assertEqual(client.models_by_session["planner-chapter-normalizer-1"], ["light-model"])
            self.assertTrue((temp_dir / "state" / "chapter-01.plan-normalizer.json").exists())
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_build_plan_normalizer_protects_long_text_leaves(self) -> None:
        long_location = "旧库门口那块已经被雨水浸透的青石台阶旁边，灯影斜着压在残破门轴上"
        client = StubClient(
            [
                [
                    {"chapter_title": "旧库借灯"},
                    {"purpose": "推进旧账"},
                    {
                        "scene_payload_blocks": [
                            {
                                "scene_index": 1,
                                "location": long_location,
                                "goal": "确认借灯名单",
                                "conflict": "门房不肯放人",
                                "turn": "她拿旧欠条换到半刻钟空档",
                            }
                        ],
                    },
                ],
                {
                    "chapter_title": "旧库借灯",
                    "purpose": "推进旧账",
                    "scenes": [
                        {
                            "scene_index": 1,
                            "location": "__NF_TOKEN_0000__",
                            "goal": "确认借灯名单",
                            "conflict": "门房不肯放人",
                            "turn": "她拿旧欠条换到半刻钟空档",
                        }
                    ],
                },
            ],
            [],
        )
        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"plan-normalizer-protect-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            pipeline = NovelPipeline(client, temp_dir, flagship_model="flagship-model", light_model="light-model")
            spec = ProjectSpec(
                title="测试小说",
                genre="悬疑",
                audience="中文读者",
                tone="克制",
                premise="旧账牵出旧案。",
                theme="代价",
                hook="借灯名单里少了一页。",
                setting="矿镇旧库",
                protagonist="沈雾",
                outline_hint="完整闭环",
                world_hint="设定服务剧情",
                ending_mode="standalone",
                pov="第三人称有限视角",
                target_total_chars=10000,
                target_chars_per_chapter=2500,
                chapter_count=4,
                volume_count=1,
                chapters_per_volume=4,
                style_examples=["克制"],
                must_include=["旧账"],
                avoid=["油滑腔"],
                character_seeds=[CharacterSeed(name="沈雾", role="主角")],
            )
            bible = WorldBible(
                title="测试小说",
                logline="一句话卖点",
                setting_summary="设定摘要",
                core_conflict="核心冲突",
                theme_statement="主题表达",
                narrative_voice=["克制"],
                world_rules=["规则一"],
                chapter_guardrails=["每章推进主线"],
                ending_contract=["闭环"],
                major_threads=["旧账线"],
                characters=[],
            )
            book_outline = BookOutline(
                title="测试小说",
                one_line_summary="一句话简介",
                act_structure=["开端", "推进", "收束"],
                volumes=[VolumeBlueprint(1, 1, 4, "第一卷", "推进主线", "旧账去哪了", "局势升级", "从回避到追查", ["旧账线"])],
            )
            volume_outline = VolumeOutline(
                volume_index=1,
                title="第一卷",
                goal="推进旧账线",
                climax="账册缺页被确认",
                carry_over_threads=["旧账线"],
                chapter_targets=[],
            )
            chapter = ChapterOutlineItem(
                1,
                1,
                "旧库借灯",
                "推进旧账",
                "借灯名单被扣",
                "她拿旧欠条换进门机会",
                "她发现账册缺页",
                "第三人称有限视角",
                "chapter_hook",
                ["旧账线"],
            )

            plan = pipeline._build_plan(spec, bible, book_outline, volume_outline, chapter, ContinuityState())

            self.assertEqual(plan.scenes[0].location, long_location)
            normalizer_prompt = client.user_prompts_by_session["planner-chapter-normalizer-1"][0]
            self.assertIn("__NF_TOKEN_0000__", normalizer_prompt)
            self.assertNotIn(long_location, normalizer_prompt)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_build_plan_restructures_when_propulsion_repeats(self) -> None:
        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"plan-restructure-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            client = StubClient(
                [
                    {
                        "chapter_index": 4,
                        "chapter_title": "旧桥拆证",
                        "purpose": "推进旧账线。",
                        "continuity_targets": ["旧账线"],
                        "opening_image": "雨夜旧桥",
                        "closing_image": "她拿到另一份残页",
                        "closing_mode": "chapter_hook",
                        "primary_propulsion": "证据推进",
                        "variation_goal": "继续拆证",
                        "term_budget": "low",
                        "theme_visibility": "subtext",
                        "grounding_beat": "她把湿透的袖口拧了一下。",
                        "scenes": [
                            {
                                "scene_index": 1,
                                "scene_type": "investigation",
                                "load_weight": 1.1,
                                "location": "旧桥下",
                                "goal": "核对残页",
                                "conflict": "巡夜人逼近",
                                "turn": "她确认残页和旧账能拼上",
                                "must_include": ["残页"],
                            }
                        ],
                    },
                    {
                        "chapter_index": 4,
                        "chapter_title": "旧桥拆证",
                        "purpose": "推进旧账线。",
                        "continuity_targets": ["旧账线"],
                        "opening_image": "雨夜旧桥",
                        "closing_image": "她逼出同伴一句真话",
                        "closing_mode": "chapter_hook",
                        "primary_propulsion": "关系推进",
                        "variation_goal": "从证据转为人际对撞",
                        "term_budget": "low",
                        "theme_visibility": "subtext",
                        "grounding_beat": "她抹掉掌心的雨水才继续说话。",
                        "scenes": [
                            {
                                "scene_index": 1,
                                "scene_type": "dialogue",
                                "load_weight": 0.9,
                                "location": "旧桥下",
                                "goal": "逼同伴开口",
                                "conflict": "对方一直装傻",
                                "turn": "她确认同伴早就见过残页",
                                "must_include": ["残页"],
                            }
                        ],
                    },
                ],
                [],
            )
            pipeline = NovelPipeline(client, temp_dir)
            spec = ProjectSpec(
                title="测试小说",
                genre="悬疑",
                audience="中文读者",
                tone="克制",
                premise="旧账牵出旧案。",
                theme="代价",
                hook="桥下残页再次出现。",
                setting="旧港桥区",
                protagonist="沈雾",
                outline_hint="完整闭环",
                world_hint="设定服务剧情",
                ending_mode="standalone",
                pov="第三人称有限视角",
                target_total_chars=12000,
                target_chars_per_chapter=2500,
                chapter_count=5,
                volume_count=1,
                chapters_per_volume=5,
            )
            bible = WorldBible(
                title="测试小说",
                logline="桥下残页再次出现。",
                setting_summary="旧港桥区",
                core_conflict="旧账重开",
                theme_statement="代价",
                narrative_voice=["克制"],
                world_rules=["先讲人，再讲制度"],
                chapter_guardrails=["每章推进"],
                ending_contract=["闭环"],
                major_threads=["旧账线"],
                characters=[],
            )
            book_outline = BookOutline(
                title="测试小说",
                one_line_summary="桥下残页再次出现。",
                act_structure=["起", "承", "合"],
                volumes=[VolumeBlueprint(1, 1, 5, "第一卷", "推进主线", "残页真假", "局势升级", "收紧", ["旧账线"])],
            )
            chapter = ChapterOutlineItem(
                4,
                1,
                "旧桥拆证",
                "推进旧账线。",
                "巡夜人逼近，桥下时间不够。",
                "她试图确认残页真假。",
                "她逼出同伴一句真话。",
                "第三人称有限视角",
                "chapter_hook",
                ["旧账线"],
            )
            volume_outline = VolumeOutline(1, "第一卷", "推进主线", "残页真假", ["旧账线"], [chapter])
            continuity = ContinuityState(active_threads=["旧账线"], must_remember=["残页已出现"], last_chapter_index=3)

            def _prior_result(index: int) -> ChapterResult:
                outline = ChapterOutlineItem(
                    index,
                    1,
                    f"前章{index}",
                    "推进旧账",
                    "阻力",
                    "拿新证据。",
                    "更深一层。",
                    "第三人称有限视角",
                    "chapter_hook",
                    ["旧账线"],
                )
                plan = ChapterPlan(
                    chapter_index=index,
                    chapter_title=f"前章{index}",
                    purpose="推进旧账",
                    continuity_targets=["旧账线"],
                    opening_image="旧港",
                    closing_image="证据更深",
                    closing_mode="chapter_hook",
                    scenes=[SceneCard(1, "旧港", "拿证据", "有人阻拦", "她拿到了更深一层的证据")],
                    primary_propulsion="证据推进",
                    variation_goal="继续拆证",
                    term_budget="low",
                    theme_visibility="subtext",
                    grounding_beat="她鞋里进了水。",
                )
                return ChapterResult(
                    index=index,
                    volume_index=1,
                    title=f"前章{index}",
                    outline_item=outline,
                    draft="她继续拆证。",
                    plan=plan,
                    review=ReviewFeedback(True, 90, [], [], [], "通过。"),
                    local_quality=LocalQualityReport(True, 90, [], [], "通过。", {}),
                    continuity=ContinuityUpdate(index, "她继续拆证。", ["旧账线"], [], ["拿到新证据"], [], ["继续查"], ["残页仍是关键"]),
                    attempts=1,
                )

            plan = pipeline._build_plan(
                spec,
                bible,
                book_outline,
                volume_outline,
                chapter,
                continuity,
                [_prior_result(1), _prior_result(2), _prior_result(3)],
            )

            self.assertEqual(client.json_calls, 2)
            self.assertEqual(plan.primary_propulsion, "关系推进")
            guard = json.loads((temp_dir / "state" / "chapter-04.plan-guard.json").read_text(encoding="utf-8"))
            self.assertTrue(guard["restructure_notes"])
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_sync_runtime_views_seals_runtime_state_and_filters_stale_memory(self) -> None:
        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"runtime-seal-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            pipeline = NovelPipeline(StubClient([], []), temp_dir)
            pipeline._promise_ledger = [
                PromiseLedgerItem(
                    promise_id="p-recent",
                    label="旧账线索",
                    thread="旧账线",
                    chapter_opened=5,
                    target_volume=1,
                    current_status="stalled",
                    last_touched_chapter=6,
                    payoff_requirements=["拿到账本缺页"],
                    overdue=True,
                    deadline_state="overdue",
                ),
                PromiseLedgerItem(
                    promise_id="p-stale",
                    label="旧门牌",
                    thread="旧门牌线",
                    chapter_opened=1,
                    target_volume=1,
                    current_status="advanced",
                    last_touched_chapter=1,
                    payoff_requirements=["确认门牌主人"],
                    overdue=False,
                    deadline_state="on_track",
                ),
            ]
            pipeline._causality_graph = [
                CausalityEdge(
                    effect_label="账本缺页",
                    cause="旧账线索",
                    prerequisites=["拿到账本缺页"],
                    required_consequences=["逼出保管人"],
                    introduced_chapter=5,
                    last_verified_chapter=6,
                ),
                CausalityEdge(
                    effect_label="旧门牌旧事",
                    cause="旧门牌",
                    prerequisites=["确认门牌主人"],
                    required_consequences=["牵出旧巷旧案"],
                    introduced_chapter=1,
                    last_verified_chapter=1,
                ),
            ]
            continuity = ContinuityState(
                recent_summaries=["她围绕旧账线索继续查。"],
                active_threads=["旧账线索", "旧门牌", "杂线"],
                must_remember=["账本缺页还没补齐。"],
                last_chapter_index=6,
                last_volume_index=1,
            )
            chapter = ChapterOutlineItem(
                6,
                1,
                "旧账回潮",
                "围绕旧账线索推进。",
                "对方试图抹平缺页。",
                "她确认账本缺页和旧账线索对上。",
                "保管人身份快露出来。",
                "第三人称有限视角",
                "chapter_hook",
                ["旧账线索"],
            )
            plan = ChapterPlan(
                chapter_index=6,
                chapter_title="旧账回潮",
                purpose="推进旧账线索。",
                continuity_targets=["旧账线索"],
                opening_image="冷雨码头",
                closing_image="账本缺页对上",
                closing_mode="chapter_hook",
                scenes=[SceneCard(1, "码头", "核对缺页", "对方销账", "她确认旧账线索对上")],
                primary_propulsion="关系推进",
                variation_goal="从人际逼问推进",
                term_budget="low",
                theme_visibility="subtext",
                grounding_beat="她把湿透的袖口拧了一下。",
            )
            result = ChapterResult(
                index=6,
                volume_index=1,
                title="旧账回潮",
                outline_item=chapter,
                draft="她围着旧账线索追到码头，终于把账本缺页和保管人对上了。",
                plan=plan,
                review=ReviewFeedback(True, 92, [], [], [], "通过。"),
                local_quality=LocalQualityReport(True, 92, [], [], "通过。", {}),
                continuity=ContinuityUpdate(6, "她确认旧账线索仍是主线。", ["旧账线索"], [], ["账本缺页对上"], [], ["逼出保管人"], ["旧账线索仍在推进"]),
                attempts=1,
            )

            pipeline._sync_runtime_views(continuity, [result])

            promise_runtime = json.loads((temp_dir / "data" / "promise-ledger.runtime.json").read_text(encoding="utf-8"))
            causality_runtime = json.loads((temp_dir / "data" / "causality-graph.runtime.json").read_text(encoding="utf-8"))
            continuity_runtime = json.loads((temp_dir / "data" / "continuity.runtime.json").read_text(encoding="utf-8"))
            seal_report = json.loads((temp_dir / "data" / "runtime-state-seal.json").read_text(encoding="utf-8"))

            self.assertEqual([item["label"] for item in promise_runtime], ["旧账线索"])
            self.assertEqual([item["effect_label"] for item in causality_runtime], ["账本缺页"])
            self.assertEqual(continuity_runtime["active_threads"], ["旧账线索"])
            self.assertEqual(seal_report["promise_pool_after"], 1)
            self.assertEqual(seal_report["causality_pool_after"], 1)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_logic_audit_parses_extended_risk_buckets(self) -> None:
        report = pipeline_module._logic_audit_from_dict(
            {
                "passed": True,
                "gate_passed": True,
                "summary": "主线稳定。",
                "issues": [],
                "watch_items": ["注意中段同构。"],
                "required_followups": ["下一卷换推进手感。"],
                "structure_risks": ["连续三章都靠证据推进。"],
                "voice_risks": ["核心角色说话越来越像。"],
                "density_risks": ["前段术语偏密。"],
                "pressure_risks": ["长期高压。"],
                "grounding_risks": ["地面生活不足。"],
            }
        )

        self.assertEqual(report.structure_risks, ["连续三章都靠证据推进。"])
        self.assertEqual(report.voice_risks, ["核心角色说话越来越像。"])
        self.assertEqual(report.density_risks, ["前段术语偏密。"])
        self.assertEqual(report.pressure_risks, ["长期高压。"])
        self.assertEqual(report.grounding_risks, ["地面生活不足。"])

    def test_logic_audit_infers_metadata_gate_from_ledger_drift(self) -> None:
        report = pipeline_module._logic_audit_from_dict(
            {
                "passed": False,
                "gate_passed": False,
                "summary": "卷四闭环有效，但账本失真。",
                "issues": ["承诺账本维护失真已到影响判断的程度。"],
                "watch_items": [],
                "required_followups": [],
            }
        )

        self.assertEqual(report.gate_level, "repair_metadata")

    def test_rewrite_prompt_uses_micro_edit_rules_for_final_fix(self) -> None:
        spec = ProjectSpec(
            title="测试小说",
            genre="都市悬疑",
            audience="中文读者",
            tone="克制",
            premise="旧档案牵出旧案。",
            theme="承担代价",
            hook="一份名单不该存在。",
            setting="海边旧城",
            protagonist="沈雾",
            outline_hint="完整闭环",
            world_hint="设定服务剧情",
            ending_mode="standalone",
            pov="第三人称有限视角",
            target_total_chars=4000,
            target_chars_per_chapter=2000,
            chapter_count=2,
            volume_count=1,
            chapters_per_volume=2,
            style_examples=["克制"],
            must_include=["证据链"],
            avoid=["作者总结腔"],
            character_seeds=[CharacterSeed(name="沈雾", role="主角")],
        )
        bible = WorldBible(
            title="测试小说",
            logline="一句话卖点",
            setting_summary="设定摘要",
            core_conflict="核心冲突",
            theme_statement="主题表达",
            narrative_voice=["克制"],
            world_rules=["规则一"],
            chapter_guardrails=["每章推进主线"],
            ending_contract=["闭环"],
            major_threads=["名单线"],
            characters=[],
        )
        chapter = ChapterOutlineItem(
            index=12,
            volume_index=1,
            title="旧档封口",
            purpose="推进证据线",
            conflict="名单将被抹去",
            beat_summary="她护住旧档逃出封锁",
            ending_note="名单还在手里",
            pov="第三人称有限视角",
            closing_mode="volume_hook",
            must_payoff=["名单线"],
        )
        plan = ChapterPlan(
            chapter_index=12,
            chapter_title="旧档封口",
            purpose="推进证据线",
            continuity_targets=["护住名单"],
            opening_image="她先把封套压在灯下。",
            closing_image="她带着名单冲进夜里。",
            closing_mode="volume_hook",
            scenes=[
                SceneCard(
                    scene_index=1,
                    location="旧档库",
                    goal="护住名单",
                    conflict="门口开始封锁",
                    turn="她带着名单冲出门线",
                    must_include=["名单不能丢"],
                )
            ],
        )
        prompt = rewrite_user_prompt(
            spec,
            bible,
            StyleBible(tone_targets=["克制"]),
            chapter,
            plan,
            "旧稿正文",
            {
                "model_review": {"passed": True, "score": 95, "strengths": ["场面成立"], "issues": [], "required_fixes": []},
                "local_review": {"passed": True, "score": 95, "issues": [], "strengths": []},
                "final_fix": "删掉作者总结腔，微调结尾并补一笔去向安排。",
            },
            ContinuityState(),
            [],
        )

        self.assertIn("若这是终审修订，优先做微创改稿", prompt)
        self.assertIn("不要为了修一个问题把其他已通过的部分改坏", prompt)

    def test_final_review_prompt_separates_documentation_cleanup_from_chapter_fixes(self) -> None:
        spec = ProjectSpec(
            title="测试小说",
            genre="都市悬疑",
            audience="中文读者",
            tone="克制",
            premise="旧档案牵出旧案。",
            theme="承担代价",
            hook="名单不该存在。",
            setting="海边旧城",
            protagonist="沈雾",
            outline_hint="完整闭环",
            world_hint="设定服务剧情",
            ending_mode="standalone",
            pov="第三人称有限视角",
            target_total_chars=4000,
            target_chars_per_chapter=2000,
            chapter_count=2,
            volume_count=1,
            chapters_per_volume=2,
            style_examples=["克制"],
            must_include=["证据链"],
            avoid=["作者总结腔"],
            character_seeds=[CharacterSeed(name="沈雾", role="主角")],
        )
        bible = WorldBible(
            title="测试小说",
            logline="一句话卖点",
            setting_summary="设定摘要",
            core_conflict="核心冲突",
            theme_statement="主题表达",
            narrative_voice=["克制"],
            world_rules=["规则一"],
            chapter_guardrails=["每章推进主线"],
            ending_contract=["闭环"],
            major_threads=["名单线"],
            characters=[],
        )
        book_outline = BookOutline(
            title="测试小说",
            one_line_summary="一句话简介",
            act_structure=["开端", "推进", "收束"],
            volumes=[VolumeBlueprint(1, 1, 2, "第一卷", "推进", "名单去哪了", "责任落地", "她决定承担", ["名单线"])],
        )
        chapter = ChapterOutlineItem(1, 1, "第一章", "推进名单线", "记录被改", "护住名单", "她决定继续追", "第三人称有限视角", "chapter_hook", ["名单线"])
        plan = ChapterPlan(1, "第一章", "推进名单线", ["名单线"], "开场", "收束", "chapter_hook", [])
        chapters = [
            ChapterResult(
                index=1,
                volume_index=1,
                title="第一章",
                outline_item=chapter,
                draft="正文",
                plan=plan,
                review=ReviewFeedback(True, 92, [], [], [], "通过。"),
                local_quality=LocalQualityReport(True, 92, [], [], "通过。", {}),
                continuity=ContinuityUpdate(1, "她护住名单。", ["名单线"], [], ["事件1"], [], ["目标1"], ["名单还在"]),
                attempts=1,
                long_memory=LongRangeMemoryUpdate(chapter_index=1),
            )
        ]
        prompt = final_review_user_prompt(
            spec,
            bible,
            book_outline,
            chapters,
            ContinuityState(active_threads=["长期执行", "待持续检验"]),
            {"passed": True, "score": 100, "issues": [], "strengths": [], "short_summary": "", "metrics": {}},
            [PromiseLedgerItem("promise-1", "名单线", "主线", 1, 1, "paid_off", 1, ["护住名单"])],
            [],
            [],
        )

        self.assertIn("资料池污染", prompt)
        self.assertIn("不要开 chapter_fixes", prompt)
        self.assertIn("focus_window", prompt)
        self.assertIn("focused_items", prompt)
        self.assertIn("focused_edges", prompt)
        self.assertIn("recent_chapters", prompt)

    def test_standalone_final_continuity_prefers_resolved_threads_over_stale_active_threads(self) -> None:
        client = StubClient([], [])
        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"final-state-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            pipeline = NovelPipeline(client, temp_dir)
            spec = ProjectSpec(
                title="测试小说",
                genre="都市悬疑",
                audience="中文读者",
                tone="克制",
                premise="旧档案牵出旧案。",
                theme="承担代价",
                hook="名单不该存在。",
                setting="海边旧城",
                protagonist="沈雾",
                outline_hint="完整闭环",
                world_hint="设定服务剧情",
                ending_mode="standalone",
                pov="第三人称有限视角",
                target_total_chars=6000,
                target_chars_per_chapter=2000,
                chapter_count=3,
                volume_count=1,
                chapters_per_volume=3,
                style_examples=["克制"],
                must_include=["证据链"],
                avoid=["作者总结腔"],
                character_seeds=[CharacterSeed(name="沈雾", role="主角")],
            )
            bible = WorldBible(
                title="测试小说",
                logline="一句话卖点",
                setting_summary="设定摘要",
                core_conflict="核心冲突",
                theme_statement="主题表达",
                narrative_voice=["克制"],
                world_rules=["规则一"],
                chapter_guardrails=["每章推进主线"],
                ending_contract=["闭环"],
                major_threads=["名单线"],
                characters=[
                    CharacterProfile(
                        name="沈雾",
                        role="主角",
                        goal="公开名单",
                        fear="旧案继续被埋",
                        contradiction="既想追真相又怕连累活人",
                        arc="从只想自保到承担公开责任",
                        public_image="沉默谨慎",
                        private_truth="始终没放下弟弟那条线",
                        speaking_style="短句，先确认再行动",
                        signature_image="把名单压在灯下再开口",
                    )
                ],
            )
            chapter = ChapterOutlineItem(3, 1, "第三章", "收束主线", "名单公开", "她把名单交出去", "旧案落地", "第三人称有限视角", "book_closure", ["名单线"])
            plan = ChapterPlan(3, "第三章", "收束主线", ["名单线"], "她站在碑前。", "她把名单交出去。", "book_closure", [])
            chapters = [
                ChapterResult(
                    index=2,
                    volume_index=1,
                    title="第二章",
                    outline_item=chapter,
                    draft="第二章正文",
                    plan=plan,
                    review=ReviewFeedback(True, 92, [], [], [], "通过。"),
                    local_quality=LocalQualityReport(True, 92, [], [], "通过。", {}),
                    continuity=ContinuityUpdate(2, "她确认名单。", ["名单线"], [], ["事件2"], [CharacterState("沈雾", "公开名单", "绷着", "更主动", "证据被毁", "名单还没公开")], ["公开名单"], ["名单还在"]),
                    attempts=1,
                    long_memory=LongRangeMemoryUpdate(chapter_index=2),
                ),
                ChapterResult(
                    index=3,
                    volume_index=1,
                    title="第三章",
                    outline_item=chapter,
                    draft="第三章正文",
                    plan=plan,
                    review=ReviewFeedback(True, 95, [], [], [], "通过。"),
                    local_quality=LocalQualityReport(True, 95, [], [], "通过。", {}),
                    continuity=ContinuityUpdate(3, "她公开名单，主线闭环。", [], ["名单线"], ["事件3"], [CharacterState("沈雾", "守住公开记录", "平静", "承担结果", "余波", "后续制度运行")], [], ["主线已闭环"]),
                    attempts=1,
                    long_memory=LongRangeMemoryUpdate(chapter_index=3),
                ),
            ]
            pipeline._promise_ledger = [
                PromiseLedgerItem("promise-1", "名单线", "主线", 1, 1, "paid_off", 3, ["公开名单"]),
            ]
            sealed = pipeline._seal_final_continuity(
                spec,
                bible,
                chapters,
                ContinuityState(
                    recent_summaries=["旧摘要"],
                    active_threads=["长期执行", "待持续检验"],
                    resolved_threads=["名单线已闭环"],
                    timeline=["旧事件"],
                    character_states=[CharacterState("旧角色", "旧目标", "旧情绪", "旧关系", "旧风险", "旧未解")],
                    must_remember=["旧记忆"],
                    last_volume_index=1,
                    last_chapter_index=3,
                ),
            )

            self.assertEqual(sealed.active_threads, [])
            self.assertTrue(any(state.name == "沈雾" for state in sealed.character_states))
            self.assertIn("名单线", json.dumps(sealed.resolved_threads, ensure_ascii=False))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_prepare_final_review_state_cleans_short_standalone_metadata_drift(self) -> None:
        client = StubClient([], [])
        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"short-final-cleanup-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            pipeline = NovelPipeline(client, temp_dir)
            spec = ProjectSpec(
                title="短篇测试",
                genre="都市悬疑",
                audience="中文读者",
                tone="克制",
                premise="她要追回一份旧名单。",
                theme="承担",
                hook="名单重新浮出水面。",
                setting="旧港",
                protagonist="沈雾",
                outline_hint="完整闭环",
                world_hint="现实流程优先",
                ending_mode="standalone",
                pov="第三人称有限视角",
                target_total_chars=12000,
                target_chars_per_chapter=2000,
                chapter_count=4,
                volume_count=1,
                chapters_per_volume=4,
                style_examples=["克制"],
                must_include=["名单"],
                avoid=["作者总结腔"],
                character_seeds=[CharacterSeed(name="沈雾", role="主角")],
            )
            bible = WorldBible(
                title="短篇测试",
                logline="名单重新浮出水面。",
                setting_summary="旧港",
                core_conflict="追回旧名单",
                theme_statement="承担",
                narrative_voice=["克制"],
                world_rules=["规则一"],
                chapter_guardrails=["每章推进主线"],
                ending_contract=["闭环"],
                major_threads=["名单线"],
                characters=[],
            )
            chapter = ChapterOutlineItem(4, 1, "第四章", "闭环", "名单公开", "她交出名单", "主线闭环", "第三人称有限视角", "book_closure", ["名单线"])
            plan = ChapterPlan(4, "第四章", "闭环", ["名单线"], "她站在档案柜前。", "她把名单交出去。", "book_closure", [])
            chapters = [
                ChapterResult(
                    index=3,
                    volume_index=1,
                    title="第三章",
                    outline_item=chapter,
                    draft="第三章正文",
                    plan=plan,
                    review=ReviewFeedback(True, 92, [], [], [], "通过。"),
                    local_quality=LocalQualityReport(True, 92, [], [], "通过。", {}),
                    continuity=ContinuityUpdate(3, "她确认名单是真的。", ["名单线"], [], ["事件3"], [], ["公开名单"], ["名单即将公开"]),
                    attempts=1,
                    long_memory=LongRangeMemoryUpdate(chapter_index=3),
                ),
                ChapterResult(
                    index=4,
                    volume_index=1,
                    title="第四章",
                    outline_item=chapter,
                    draft="第四章正文",
                    plan=plan,
                    review=ReviewFeedback(True, 95, [], [], [], "通过。"),
                    local_quality=LocalQualityReport(True, 95, [], [], "通过。", {}),
                    continuity=ContinuityUpdate(4, "她公开名单，主线闭环。", [], ["名单线"], ["事件4"], [], [], ["主线已闭环"]),
                    attempts=1,
                    long_memory=LongRangeMemoryUpdate(chapter_index=4),
                ),
            ]
            continuity = ContinuityState(
                recent_summaries=["旧摘要"],
                active_threads=["名单线", "无关旧线程"],
                resolved_threads=["旧闭环"],
                timeline=["旧事件"],
                must_remember=["旧记忆"],
                last_volume_index=1,
                last_chapter_index=4,
            )
            pipeline._promise_ledger = [
                PromiseLedgerItem("p1", "名单线", "主线", 1, 1, "paid_off", 4, ["公开名单"], deadline_state="on_track"),
                PromiseLedgerItem("p2", "旧误报线程", "杂线", 1, 1, "advanced", 1, ["无"], deadline_state="overdue"),
            ]
            pipeline._causality_graph = [
                CausalityEdge("名单公开", "制度回补", ["公示留档"], ["名单公示"], 4, 4),
                CausalityEdge("旧误报线程", "无关后果", ["无关结果"], ["无"], 1, 1),
            ]

            sealed_continuity, sealed_promises, sealed_causality = pipeline._prepare_final_review_state(
                spec,
                bible,
                chapters,
                continuity,
            )

            self.assertNotIn("无关旧线程", json.dumps(sealed_continuity.active_threads, ensure_ascii=False))
            self.assertTrue(any(item.label == "名单线" for item in sealed_promises))
            self.assertFalse(any(item.label == "旧误报线程" for item in sealed_promises))
            self.assertFalse(any(edge.cause == "旧误报线程" for edge in sealed_causality))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_prepare_final_review_state_cleans_metadata_drift_for_long_form_project(self) -> None:
        client = StubClient([], [])
        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"long-final-cleanup-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            pipeline = NovelPipeline(client, temp_dir)
            spec = ProjectSpec(
                title="中篇测试",
                genre="现实悬疑",
                audience="中文读者",
                tone="克制",
                premise="他要追查一条旧报损链。",
                theme="代价",
                hook="旧报损单据重新出现。",
                setting="旧港仓储线",
                protagonist="顾平生",
                outline_hint="多卷推进",
                world_hint="流程现实优先",
                ending_mode="series",
                pov="第三人称有限视角",
                target_total_chars=100000,
                target_chars_per_chapter=9000,
                chapter_count=10,
                volume_count=4,
                chapters_per_volume=3,
                volume_chapter_targets=[3, 3, 2, 2],
                style_examples=["克制"],
                must_include=["旧报损链"],
                avoid=["作者总结腔"],
                character_seeds=[CharacterSeed(name="顾平生", role="主角")],
            )
            bible = WorldBible(
                title="中篇测试",
                logline="旧报损链重新浮出水面。",
                setting_summary="旧港仓储线",
                core_conflict="追查旧报损链",
                theme_statement="代价",
                narrative_voice=["克制"],
                world_rules=["规则一"],
                chapter_guardrails=["每章推进主线"],
                ending_contract=["主线持续推进。"],
                major_threads=["旧报损链", "后方薄证线"],
                characters=[],
            )
            outline = ChapterOutlineItem(
                10,
                4,
                "第十章",
                "卷尾收束",
                "追出旧报损链负责人",
                "他把旧链条的真正缺口钉死。",
                "卷尾进入下一阶段。",
                "第三人称有限视角",
                "volume_hook",
                must_payoff=["旧报损链"],
            )
            plan = ChapterPlan(10, "第十章", "卷尾收束", ["旧报损链"], "他在旧库房外停住。", "他决定去前线追人。", "volume_hook", [])
            chapters = [
                ChapterResult(
                    index=8,
                    volume_index=3,
                    title="第八章",
                    outline_item=outline,
                    draft="第八章正文",
                    plan=plan,
                    review=ReviewFeedback(True, 92, [], [], [], "通过。"),
                    local_quality=LocalQualityReport(True, 92, [], [], "通过。", {}),
                    continuity=ContinuityUpdate(8, "他确认后方薄证不是主线核心。", [], [], ["事件8"], [], [], ["旧编号可暂时后放"]),
                    attempts=1,
                    long_memory=LongRangeMemoryUpdate(chapter_index=8),
                ),
                ChapterResult(
                    index=9,
                    volume_index=4,
                    title="第九章",
                    outline_item=outline,
                    draft="第九章正文",
                    plan=plan,
                    review=ReviewFeedback(True, 93, [], [], [], "通过。"),
                    local_quality=LocalQualityReport(True, 93, [], [], "通过。", {}),
                    continuity=ContinuityUpdate(9, "他拿到新的装卸口供。", ["旧报损链"], [], ["事件9"], [], ["追到负责人"], ["当前关键是报损链负责人"]),
                    attempts=1,
                    long_memory=LongRangeMemoryUpdate(chapter_index=9),
                ),
                ChapterResult(
                    index=10,
                    volume_index=4,
                    title="第十章",
                    outline_item=outline,
                    draft="第十章正文",
                    plan=plan,
                    review=ReviewFeedback(True, 95, [], [], [], "通过。"),
                    local_quality=LocalQualityReport(True, 95, [], [], "通过。", {}),
                    continuity=ContinuityUpdate(10, "他钉死了旧报损链的缺口。", [], ["旧报损链"], ["事件10"], [], ["转向负责人"], ["卷尾只保留当前高危入口"]),
                    attempts=1,
                    long_memory=LongRangeMemoryUpdate(chapter_index=10),
                ),
            ]
            continuity = ContinuityState(
                recent_summaries=["旧摘要"],
                active_threads=["旧报损链", "陈年误报线", "无关旧感情线"],
                resolved_threads=["旧闭环"],
                timeline=["旧事件"],
                must_remember=["旧记忆"],
                last_volume_index=4,
                last_chapter_index=10,
            )
            pipeline._promise_ledger = [
                PromiseLedgerItem("p1", "旧报损链", "主线", 1, 4, "advanced", 10, ["钉死缺口"], deadline_state="at_risk"),
                PromiseLedgerItem("p2", "后方薄证线", "支线", 3, 5, "advanced", 8, ["确认薄证"], deadline_state="on_track"),
                PromiseLedgerItem("p3", "无关旧感情线", "杂线", 1, 2, "advanced", 2, ["无"], deadline_state="overdue"),
            ]
            pipeline._causality_graph = [
                CausalityEdge("旧报损链缺口钉死", "旧口供互证", ["新装卸口供"], ["负责人暴露"], 10, 10),
                CausalityEdge("无关旧感情线", "旧时误会", ["无"], ["无"], 1, 1),
            ]

            sealed_continuity, sealed_promises, sealed_causality = pipeline._prepare_final_review_state(
                spec,
                bible,
                chapters,
                continuity,
            )

            self.assertIn("旧报损链", json.dumps(sealed_continuity.active_threads, ensure_ascii=False))
            self.assertNotIn("无关旧感情线", json.dumps(sealed_continuity.active_threads, ensure_ascii=False))
            self.assertTrue(any(item.label == "旧报损链" for item in sealed_promises))
            self.assertFalse(any(item.label == "无关旧感情线" for item in sealed_promises))
            self.assertFalse(any(edge.cause == "无关旧感情线" for edge in sealed_causality))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_sanitize_continuity_state_collapses_semantic_duplicate_threads(self) -> None:
        continuity = ContinuityState(
            active_threads=[
                "确保案边封看的七张假单和现场见证人不被夜里清走或翻供。",
                "继续保住案边封看的七张假结赔单和现场守证人，防止统一口径前夜里清证。",
                "名单线",
            ],
            resolved_threads=["名单线已闭环"],
            must_remember=[
                "继续保住案边封看的七张假单和现场见证人。",
                "保住案边封看的七张假结赔单和现场守证人。",
            ],
            last_volume_index=4,
            last_chapter_index=80,
        )

        sealed = pipeline_module._sanitize_continuity_state(continuity)

        self.assertEqual(len(sealed.active_threads), 1)
        self.assertIn("案边封看", sealed.active_threads[0])
        self.assertEqual(len(sealed.must_remember), 1)
        self.assertEqual(len(sealed.resolved_threads), 1)

    def test_prepare_final_review_state_semantically_dedupes_runtime_promises(self) -> None:
        client = StubClient([], [])
        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"semantic-promise-cleanup-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            pipeline = NovelPipeline(client, temp_dir)
            spec = ProjectSpec(
                title="中篇测试",
                genre="现实悬疑",
                audience="中文读者",
                tone="克制",
                premise="他要追查守证线。",
                theme="代价",
                hook="守证线重新出现。",
                setting="旧港仓储线",
                protagonist="顾平生",
                outline_hint="多卷推进",
                world_hint="流程现实优先",
                ending_mode="series",
                pov="第三人称有限视角",
                target_total_chars=100000,
                target_chars_per_chapter=9000,
                chapter_count=10,
                volume_count=4,
                chapters_per_volume=3,
                volume_chapter_targets=[3, 3, 2, 2],
                style_examples=["克制"],
                must_include=["守证线"],
                avoid=["作者总结腔"],
                character_seeds=[CharacterSeed(name="顾平生", role="主角")],
            )
            bible = WorldBible(
                title="中篇测试",
                logline="守证线重新出现。",
                setting_summary="旧港仓储线",
                core_conflict="追查守证线",
                theme_statement="代价",
                narrative_voice=["克制"],
                world_rules=["规则一"],
                chapter_guardrails=["每章推进主线"],
                ending_contract=["主线持续推进。"],
                major_threads=["守证线"],
                characters=[],
            )
            outline = ChapterOutlineItem(
                10,
                4,
                "第十章",
                "卷尾收束",
                "保住案边封看的七张假单和守证人。",
                "他把守证线钉死。",
                "卷尾进入下一阶段。",
                "第三人称有限视角",
                "volume_hook",
                must_payoff=["守证线"],
            )
            plan = ChapterPlan(10, "第十章", "卷尾收束", ["守证线"], "他在旧库房外停住。", "他决定先守住见证人。", "volume_hook", [])
            chapters = [
                ChapterResult(
                    index=9,
                    volume_index=4,
                    title="第九章",
                    outline_item=outline,
                    draft="第九章正文",
                    plan=plan,
                    review=ReviewFeedback(True, 93, [], [], [], "通过。"),
                    local_quality=LocalQualityReport(True, 93, [], [], "通过。", {}),
                    continuity=ContinuityUpdate(9, "他重新守住案边封看的七张假单和守证人。", ["守证线"], [], ["事件9"], [], ["守住见证"], ["当前关键是守证线"]),
                    attempts=1,
                    long_memory=LongRangeMemoryUpdate(chapter_index=9),
                ),
                ChapterResult(
                    index=10,
                    volume_index=4,
                    title="第十章",
                    outline_item=outline,
                    draft="第十章正文",
                    plan=plan,
                    review=ReviewFeedback(True, 95, [], [], [], "通过。"),
                    local_quality=LocalQualityReport(True, 95, [], [], "通过。", {}),
                    continuity=ContinuityUpdate(10, "他钉死守证线。", [], ["守证线"], ["事件10"], [], ["转向负责人"], ["卷尾只保留当前高危入口"]),
                    attempts=1,
                    long_memory=LongRangeMemoryUpdate(chapter_index=10),
                ),
            ]
            continuity = ContinuityState(
                recent_summaries=["旧摘要"],
                active_threads=[
                    "确保案边封看的七张假单和现场见证人不被夜里清走或翻供。",
                    "继续保住案边封看的七张假结赔单和现场守证人，防止统一口径前夜里清证。",
                ],
                resolved_threads=[],
                timeline=["旧事件"],
                must_remember=["旧记忆"],
                last_volume_index=4,
                last_chapter_index=10,
            )
            pipeline._promise_ledger = [
                PromiseLedgerItem(
                    "p1",
                    "保住案边封看的七张假单和现场见证人",
                    "守证线",
                    8,
                    4,
                    "advanced",
                    10,
                    ["守住见证人"],
                    deadline_state="at_risk",
                ),
                PromiseLedgerItem(
                    "p2",
                    "继续保住案边封看的七张假结赔单和现场守证人",
                    "守证链",
                    9,
                    4,
                    "advanced",
                    10,
                    ["防止夜里清证"],
                    deadline_state="overdue",
                ),
            ]
            pipeline._causality_graph = []

            sealed_continuity, sealed_promises, _ = pipeline._prepare_final_review_state(
                spec,
                bible,
                chapters,
                continuity,
            )

            self.assertEqual(len(sealed_continuity.active_threads), 1)
            self.assertEqual(len(sealed_promises), 1)
            self.assertIn("守证", sealed_promises[0].label)
            self.assertIn("守住见证人", json.dumps(sealed_promises[0].payoff_requirements, ensure_ascii=False))
            self.assertIn("防止夜里清证", json.dumps(sealed_promises[0].payoff_requirements, ensure_ascii=False))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_generate_chapter_runs_length_compaction_before_failing_short_standalone(self) -> None:
        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"chapter-compaction-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        original_analyze = pipeline_module.analyze_chapter
        try:
            client = StubClient([], ["长稿" * 1100, "短稿" * 700])
            pipeline = NovelPipeline(client, temp_dir)
            pipeline._style_bible = StyleBible(tone_targets=["克制"])
            pipeline._voice_cards = []
            spec = ProjectSpec(
                title="短篇测试",
                genre="都市悬疑",
                audience="中文读者",
                tone="克制",
                premise="她要追回一份旧名单。",
                theme="承担",
                hook="名单重新浮出水面。",
                setting="旧港",
                protagonist="沈雾",
                outline_hint="完整闭环",
                world_hint="现实流程优先",
                ending_mode="standalone",
                pov="第三人称有限视角",
                target_total_chars=9000,
                target_chars_per_chapter=1400,
                chapter_count=4,
                volume_count=1,
                chapters_per_volume=4,
                style_examples=["克制"],
                must_include=["名单"],
                avoid=["作者总结腔"],
                character_seeds=[CharacterSeed(name="沈雾", role="主角")],
            )
            bible = WorldBible(
                title="短篇测试",
                logline="名单重新浮出水面。",
                setting_summary="旧港",
                core_conflict="追回旧名单",
                theme_statement="承担",
                narrative_voice=["克制"],
                world_rules=["规则一"],
                chapter_guardrails=["每章推进主线"],
                ending_contract=["闭环"],
                major_threads=["名单线"],
                characters=[],
            )
            chapter = ChapterOutlineItem(1, 1, "第一章", "起手", "名单回潮", "她决定追下去", "次日回访旧站台", "第三人称有限视角", "chapter_hook", ["名单线"])
            plan = ChapterPlan(
                1,
                "第一章",
                "起手",
                ["名单线"],
                "她看见旧包。",
                "她记下旧站台时间。",
                "chapter_hook",
                [SceneCard(scene_index=1, location="旧港", goal="确认旧包", conflict="委托人施压", turn="她决定回访旧站台")],
            )
            continuity = ContinuityState(active_threads=["名单线"], must_remember=["旧包"], last_chapter_index=0)

            def fake_review(_spec, _bible, _chapter, _plan, draft, local_quality, *_args):
                if len(draft) > 1750:
                    return ReviewFeedback(False, 88, ["主线成立"], ["篇幅超标"], ["压缩至少 300 字"], "未通过。")
                return ReviewFeedback(True, 93, ["通过"], [], [], "通过。")

            def fake_extract(*_args, **_kwargs):
                return ContinuityUpdate(1, "她决定回访旧站台。", ["名单线"], [], ["事件1"], [], ["回访站台"], ["旧站台时间已记下"])

            pipeline._review_chapter = fake_review  # type: ignore[method-assign]
            pipeline._extract_continuity = fake_extract  # type: ignore[method-assign]
            pipeline._extract_long_range_memory = lambda *_args, **_kwargs: LongRangeMemoryUpdate(chapter_index=1)  # type: ignore[method-assign]
            pipeline._build_chapter_room = lambda *_args, **_kwargs: {}  # type: ignore[method-assign]
            pipeline_module.analyze_chapter = lambda draft, *_args, **_kwargs: LocalQualityReport(
                passed=len(draft) <= 1750,
                score=90 if len(draft) <= 1750 else 80,
                issues=[] if len(draft) <= 1750 else ["正文偏长。"],
                strengths=["通过。"],
                short_summary="通过。" if len(draft) <= 1750 else "偏长。",
                metrics={"char_count": len(draft), "target_chars_max": 1750},
            )

            result = pipeline._generate_chapter(spec, bible, chapter, plan, continuity, [])

            self.assertTrue(result.review.passed)
            self.assertTrue(result.local_quality.passed)
            self.assertEqual(result.draft, "短稿" * 700)
            self.assertEqual(client.text_calls, 2)
        finally:
            pipeline_module.analyze_chapter = original_analyze
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_chapter_local_quality_kwargs_use_relaxed_length_gate_for_mid_long_form(self) -> None:
        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"chapter-length-gate-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            pipeline = NovelPipeline(StubClient([], []), temp_dir)
            spec = ProjectSpec(
                title="长篇测试",
                genre="都市悬疑",
                audience="中文读者",
                tone="克制",
                premise="她要追回一份旧名单。",
                theme="承担",
                hook="名单重新浮出水面。",
                setting="旧港",
                protagonist="沈雾",
                outline_hint="长篇推进",
                world_hint="现实流程优先",
                ending_mode="serialized",
                pov="第三人称有限视角",
                target_total_chars=120000,
                target_chars_per_chapter=2000,
                chapter_count=40,
                volume_count=4,
                chapters_per_volume=10,
                style_examples=["克制"],
                must_include=["名单"],
                avoid=["作者总结腔"],
                character_seeds=[CharacterSeed(name="沈雾", role="主角")],
            )
            chapter = ChapterOutlineItem(1, 1, "第一章", "起手", "名单回潮", "她决定追下去", "次日回访旧站台", "第三人称有限视角", "chapter_hook", ["名单线"])
            plan = ChapterPlan(
                1,
                "第一章",
                "起手",
                ["名单线"],
                "她看见旧包。",
                "她记下旧站台时间。",
                "chapter_hook",
                [SceneCard(scene_index=1, location="旧港", goal="确认旧包", conflict="委托人施压", turn="她决定回访旧站台")],
            )
            kwargs = pipeline._chapter_local_quality_kwargs(spec, chapter, plan, [])
            self.assertFalse(kwargs["strict_length_gate"])
            self.assertEqual(kwargs["length_extreme_multiplier"], 3.0)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_chapter_local_quality_kwargs_keep_strict_length_gate_for_explicit_short_form(self) -> None:
        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"chapter-length-gate-short-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            pipeline = NovelPipeline(StubClient([], []), temp_dir)
            spec = ProjectSpec(
                title="短篇测试",
                genre="都市悬疑",
                audience="中文读者",
                tone="克制",
                premise="她要追回一份旧名单。",
                theme="承担",
                hook="名单重新浮出水面。",
                setting="旧港",
                protagonist="沈雾",
                outline_hint="短篇闭环",
                world_hint="现实流程优先",
                ending_mode="standalone",
                pov="第三人称有限视角",
                target_total_chars=12000,
                target_chars_per_chapter=2000,
                chapter_count=4,
                volume_count=1,
                chapters_per_volume=4,
                style_examples=["克制"],
                must_include=["名单"],
                avoid=["作者总结腔"],
                character_seeds=[CharacterSeed(name="沈雾", role="主角")],
            )
            chapter = ChapterOutlineItem(1, 1, "第一章", "起手", "名单回潮", "她决定追下去", "次日回访旧站台", "第三人称有限视角", "chapter_hook", ["名单线"])
            plan = ChapterPlan(
                1,
                "第一章",
                "起手",
                ["名单线"],
                "她看见旧包。",
                "她记下旧站台时间。",
                "chapter_hook",
                [SceneCard(scene_index=1, location="旧港", goal="确认旧包", conflict="委托人施压", turn="她决定回访旧站台")],
            )
            kwargs = pipeline._chapter_local_quality_kwargs(spec, chapter, plan, [])
            self.assertTrue(kwargs["strict_length_gate"])
            self.assertEqual(kwargs["length_extreme_multiplier"], 3.0)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_chapter_local_quality_kwargs_soften_tomato_projects_and_keep_tighter_cap(self) -> None:
        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"chapter-length-gate-tomato-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            pipeline = NovelPipeline(StubClient([], []), temp_dir)
            spec = ProjectSpec(
                title="番茄测试",
                genre="都市高武",
                audience="番茄大众男频",
                tone="白快狠",
                premise="主角接管神明税务局。",
                theme="活下来",
                hook="高考当天全城扣寿。",
                setting="现代都市",
                protagonist="林渊",
                outline_hint="前期追读优先",
                world_hint="术语别太重",
                ending_mode="series",
                pov="第三人称有限视角",
                target_total_chars=2_000_000,
                target_chars_per_chapter=2800,
                chapter_count=720,
                volume_count=60,
                chapters_per_volume=12,
                market_profile="tomato_mass",
                style_examples=["小白快节奏"],
                must_include=["黄金三章"],
                avoid=["慢热"],
                character_seeds=[CharacterSeed(name="林渊", role="主角")],
            )
            chapter = ChapterOutlineItem(1, 1, "第一章", "起手", "全城扣寿", "主角绑定神印", "马上去税务局", "第三人称有限视角", "chapter_hook", ["神税线"])
            plan = ChapterPlan(
                1,
                "第一章",
                "起手",
                ["神税线"],
                "高考考场异变。",
                "主角决定进税务局。",
                "chapter_hook",
                [SceneCard(scene_index=1, location="考场", goal="保命", conflict="全城扣寿", turn="绑定残印")],
            )
            kwargs = pipeline._chapter_local_quality_kwargs(spec, chapter, plan, [])
            self.assertFalse(kwargs["strict_length_gate"])
            self.assertLess(kwargs["length_extreme_multiplier"], 3.0)
            self.assertEqual(kwargs["recent_overlength_tail"], 0)
            self.assertEqual(kwargs["recent_severe_overlength_tail"], 0)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_chapter_local_quality_kwargs_track_recent_tomato_overlength_tail(self) -> None:
        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"chapter-length-gate-tomato-tail-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            pipeline = NovelPipeline(StubClient([], []), temp_dir)
            spec = ProjectSpec(
                title="番茄测试",
                genre="都市高武",
                audience="番茄大众男频",
                tone="白快狠",
                premise="主角接管神明税务局。",
                theme="活下来",
                hook="高考当天全城扣寿。",
                setting="现代都市",
                protagonist="林渊",
                outline_hint="前期追读优先",
                world_hint="术语别太重",
                ending_mode="series",
                pov="第三人称有限视角",
                target_total_chars=2_000_000,
                target_chars_per_chapter=2800,
                chapter_count=720,
                volume_count=60,
                chapters_per_volume=12,
                market_profile="tomato_mass",
                style_examples=["小白快节奏"],
                must_include=["黄金三章"],
                avoid=["慢热"],
                character_seeds=[CharacterSeed(name="林渊", role="主角")],
            )
            chapter = ChapterOutlineItem(4, 1, "第四章", "延续追读", "继续追税", "主角再压一层", "马上转下一个现场", "第三人称有限视角", "chapter_hook", ["神税线"])
            plan = ChapterPlan(
                4,
                "第四章",
                "延续追读",
                ["神税线"],
                "主角继续追税。",
                "主角压下一层。",
                "chapter_hook",
                [SceneCard(scene_index=1, location="街头", goal="追税", conflict="账主反扑", turn="主角再抬一层")],
            )
            prior = [
                ChapterResult(
                    index=1,
                    volume_index=1,
                    title="第一章",
                    outline_item=chapter,
                    draft="a",
                    plan=plan,
                    review=ReviewFeedback(True, 93, [], [], [], "通过。"),
                    local_quality=LocalQualityReport(True, 90, [], [], "通过。", {"length_over_ratio": 1.35}),
                    continuity=ContinuityUpdate(1, "通过", [], [], [], [], [], []),
                    attempts=1,
                    long_memory=LongRangeMemoryUpdate(chapter_index=1),
                ),
                ChapterResult(
                    index=2,
                    volume_index=1,
                    title="第二章",
                    outline_item=chapter,
                    draft="b",
                    plan=plan,
                    review=ReviewFeedback(True, 93, [], [], [], "通过。"),
                    local_quality=LocalQualityReport(True, 90, [], [], "通过。", {"length_over_ratio": 1.82}),
                    continuity=ContinuityUpdate(2, "通过", [], [], [], [], [], []),
                    attempts=1,
                    long_memory=LongRangeMemoryUpdate(chapter_index=2),
                ),
                ChapterResult(
                    index=3,
                    volume_index=1,
                    title="第三章",
                    outline_item=chapter,
                    draft="c",
                    plan=plan,
                    review=ReviewFeedback(True, 93, [], [], [], "通过。"),
                    local_quality=LocalQualityReport(True, 90, [], [], "通过。", {"length_over_ratio": 1.92}),
                    continuity=ContinuityUpdate(3, "通过", [], [], [], [], [], []),
                    attempts=1,
                    long_memory=LongRangeMemoryUpdate(chapter_index=3),
                ),
            ]

            kwargs = pipeline._chapter_local_quality_kwargs(spec, chapter, plan, prior)

            self.assertEqual(kwargs["recent_overlength_tail"], 3)
            self.assertEqual(kwargs["recent_severe_overlength_tail"], 2)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_should_attempt_length_compaction_for_tomato_length_debt_only(self) -> None:
        spec = ProjectSpec(
            title="番茄测试",
            genre="都市高武",
            audience="番茄大众男频",
            tone="白快狠",
            premise="主角追债。",
            theme="活下来",
            hook="开局冲突。",
            setting="现代都市",
            protagonist="林渊",
            outline_hint="前期追读优先",
            world_hint="术语别太重",
            ending_mode="series",
            pov="第三人称有限视角",
            target_total_chars=2_000_000,
            target_chars_per_chapter=2800,
            chapter_count=720,
            volume_count=60,
            chapters_per_volume=12,
            market_profile="tomato_mass",
            style_examples=["小白快节奏"],
            must_include=["黄金三章"],
            avoid=["慢热"],
            character_seeds=[CharacterSeed(name="林渊", role="主角")],
        )
        warning_quality = LocalQualityReport(
            True,
            90,
            [],
            [],
            "通过。",
            {"char_count": 3900, "target_chars_max": 3000, "length_signal_level": "warning"},
        )
        debt_quality = LocalQualityReport(
            True,
            84,
            [],
            [],
            "通过。",
            {"char_count": 5600, "target_chars_max": 3000, "length_signal_level": "debt"},
        )

        self.assertFalse(pipeline_module._should_attempt_length_compaction(spec, warning_quality))
        self.assertTrue(pipeline_module._should_attempt_length_compaction(spec, debt_quality))

    def test_project_spec_from_dict_infers_legacy_tomato_market_profile(self) -> None:
        spec = pipeline_module._project_spec_from_dict(
            {
                "title": "老番茄书",
                "genre": "都市异能",
                "audience": "番茄大众男频读者",
                "tone": "小白、快节奏、强钩子",
                "premise": "主角开局爆炸式入局。",
                "theme": "活下来",
                "hook": "黄金三章就要把钩子打满。",
                "setting": "现代都市",
                "protagonist": "林渊",
                "outline_hint": "前30章追读优先，别慢热。",
                "world_hint": "术语少一点。",
                "ending_mode": "series",
                "pov": "第三人称有限视角",
                "target_total_chars": 2_000_000,
                "target_chars_per_chapter": 0,
                "chapter_count": 700,
                "volume_count": 58,
                "style_examples": ["番茄爆款", "小白快节奏"],
                "must_include": ["强回报", "高频钩子"],
                "avoid": ["慢热", "术语堆叠"],
            }
        )

        self.assertEqual(spec.market_profile, "tomato_mass")

    def test_generate_chapter_skips_length_compaction_for_non_short_long_form(self) -> None:
        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"chapter-no-compaction-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        original_analyze = pipeline_module.analyze_chapter
        try:
            client = StubClient([], ["长稿" * 1600])
            pipeline = NovelPipeline(client, temp_dir, max_rewrites=0)
            pipeline._style_bible = StyleBible(tone_targets=["克制"])
            pipeline._voice_cards = []
            spec = ProjectSpec(
                title="长篇测试",
                genre="都市悬疑",
                audience="中文读者",
                tone="克制",
                premise="她要追回一份旧名单。",
                theme="承担",
                hook="名单重新浮出水面。",
                setting="旧港",
                protagonist="沈雾",
                outline_hint="长篇推进",
                world_hint="现实流程优先",
                ending_mode="serialized",
                pov="第三人称有限视角",
                target_total_chars=120000,
                target_chars_per_chapter=2000,
                chapter_count=40,
                volume_count=4,
                chapters_per_volume=10,
                style_examples=["克制"],
                must_include=["名单"],
                avoid=["作者总结腔"],
                character_seeds=[CharacterSeed(name="沈雾", role="主角")],
            )
            bible = WorldBible(
                title="长篇测试",
                logline="名单重新浮出水面。",
                setting_summary="旧港",
                core_conflict="追回旧名单",
                theme_statement="承担",
                narrative_voice=["克制"],
                world_rules=["规则一"],
                chapter_guardrails=["每章推进主线"],
                ending_contract=["持续推进"],
                major_threads=["名单线"],
                characters=[],
            )
            chapter = ChapterOutlineItem(1, 1, "第一章", "起手", "名单回潮", "她决定追下去", "次日回访旧站台", "第三人称有限视角", "chapter_hook", ["名单线"])
            plan = ChapterPlan(
                1,
                "第一章",
                "起手",
                ["名单线"],
                "她看见旧包。",
                "她记下旧站台时间。",
                "chapter_hook",
                [SceneCard(scene_index=1, location="旧港", goal="确认旧包", conflict="委托人施压", turn="她决定回访旧站台")],
            )
            continuity = ContinuityState(active_threads=["名单线"], must_remember=["旧包"], last_chapter_index=0)

            def fake_review(_spec, _bible, _chapter, _plan, draft, local_quality, *_args):
                if len(draft) > 2500:
                    return ReviewFeedback(False, 88, ["主线成立"], ["篇幅超标"], ["可略作收束"], "未通过。")
                return ReviewFeedback(True, 93, ["通过"], [], [], "通过。")

            pipeline._review_chapter = fake_review  # type: ignore[method-assign]
            pipeline._build_chapter_room = lambda *_args, **_kwargs: {}  # type: ignore[method-assign]
            pipeline_module.analyze_chapter = lambda draft, *_args, **_kwargs: LocalQualityReport(
                passed=len(draft) <= 2500,
                score=90 if len(draft) <= 2500 else 80,
                issues=[] if len(draft) <= 2500 else ["正文偏长。"],
                strengths=["通过。"],
                short_summary="通过。" if len(draft) <= 2500 else "偏长。",
                metrics={"char_count": len(draft), "target_chars_max": 2500},
            )

            with self.assertRaises(RuntimeError):
                pipeline._generate_chapter(spec, bible, chapter, plan, continuity, [])

            self.assertEqual(client.text_calls, 1)
        finally:
            pipeline_module.analyze_chapter = original_analyze
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_generate_chapter_runs_length_compaction_for_extreme_long_form_overflow(self) -> None:
        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"chapter-extreme-compaction-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        original_analyze = pipeline_module.analyze_chapter
        try:
            client = StubClient([], ["长稿" * 4000, "短稿" * 1200])
            pipeline = NovelPipeline(client, temp_dir, max_rewrites=0)
            pipeline._style_bible = StyleBible(tone_targets=["克制"])
            pipeline._voice_cards = []
            spec = ProjectSpec(
                title="长篇测试",
                genre="都市悬疑",
                audience="中文读者",
                tone="克制",
                premise="她要追回一份旧名单。",
                theme="承担",
                hook="名单重新浮出水面。",
                setting="旧港",
                protagonist="沈雾",
                outline_hint="长篇推进",
                world_hint="现实流程优先",
                ending_mode="serialized",
                pov="第三人称有限视角",
                target_total_chars=120000,
                target_chars_per_chapter=2000,
                chapter_count=40,
                volume_count=4,
                chapters_per_volume=10,
                style_examples=["克制"],
                must_include=["名单"],
                avoid=["作者总结腔"],
                character_seeds=[CharacterSeed(name="沈雾", role="主角")],
            )
            bible = WorldBible(
                title="长篇测试",
                logline="名单重新浮出水面。",
                setting_summary="旧港",
                core_conflict="追回旧名单",
                theme_statement="承担",
                narrative_voice=["克制"],
                world_rules=["规则一"],
                chapter_guardrails=["每章推进主线"],
                ending_contract=["持续推进"],
                major_threads=["名单线"],
                characters=[],
            )
            chapter = ChapterOutlineItem(1, 1, "第一章", "起手", "名单回潮", "她决定追下去", "次日回访旧站台", "第三人称有限视角", "chapter_hook", ["名单线"])
            plan = ChapterPlan(
                1,
                "第一章",
                "起手",
                ["名单线"],
                "她看见旧包。",
                "她记下旧站台时间。",
                "chapter_hook",
                [SceneCard(scene_index=1, location="旧港", goal="确认旧包", conflict="委托人施压", turn="她决定回访旧站台")],
            )
            continuity = ContinuityState(active_threads=["名单线"], must_remember=["旧包"], last_chapter_index=0)

            def fake_review(_spec, _bible, _chapter, _plan, draft, local_quality, *_args):
                if len(draft) > 2500:
                    return ReviewFeedback(False, 88, ["主线成立"], ["篇幅超标"], ["极端超长，需要压缩"], "未通过。")
                return ReviewFeedback(True, 93, ["通过"], [], [], "通过。")

            def fake_extract(*_args, **_kwargs):
                return ContinuityUpdate(1, "她决定回访旧站台。", ["名单线"], [], ["事件1"], [], ["回访站台"], ["旧站台时间已记下"])

            pipeline._review_chapter = fake_review  # type: ignore[method-assign]
            pipeline._extract_continuity = fake_extract  # type: ignore[method-assign]
            pipeline._extract_long_range_memory = lambda *_args, **_kwargs: LongRangeMemoryUpdate(chapter_index=1)  # type: ignore[method-assign]
            pipeline._build_chapter_room = lambda *_args, **_kwargs: {}  # type: ignore[method-assign]
            pipeline_module.analyze_chapter = lambda draft, *_args, **_kwargs: LocalQualityReport(
                passed=len(draft) <= 2500,
                score=90 if len(draft) <= 2500 else 80,
                issues=[] if len(draft) <= 2500 else ["正文偏长。"],
                strengths=["通过。"],
                short_summary="通过。" if len(draft) <= 2500 else "偏长。",
                metrics={"char_count": len(draft), "target_chars_max": 2500},
            )

            result = pipeline._generate_chapter(spec, bible, chapter, plan, continuity, [])

            self.assertTrue(result.review.passed)
            self.assertTrue(result.local_quality.passed)
            self.assertEqual(result.draft, "短稿" * 1200)
            self.assertEqual(client.text_calls, 2)
        finally:
            pipeline_module.analyze_chapter = original_analyze
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_generate_chapter_records_stagnation_warning(self) -> None:
        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"chapter-stagnation-warning-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        original_analyze = pipeline_module.analyze_chapter
        try:
            client = StubClient([], ["第一章正文。"])
            pipeline = NovelPipeline(client, temp_dir)
            pipeline._style_bible = StyleBible(tone_targets=["克制"])
            pipeline._voice_cards = []
            pipeline._build_chapter_room = lambda *_args, **_kwargs: {}  # type: ignore[method-assign]
            pipeline._select_story_memories = lambda *_args, **_kwargs: []  # type: ignore[method-assign]
            pipeline._select_style_memories = lambda *_args, **_kwargs: []  # type: ignore[method-assign]
            pipeline._select_promise_memories = lambda *_args, **_kwargs: []  # type: ignore[method-assign]
            pipeline._select_causality_memories = lambda *_args, **_kwargs: []  # type: ignore[method-assign]
            pipeline._latest_logic_audit_for_volume = lambda *_args, **_kwargs: None  # type: ignore[method-assign]
            spec = ProjectSpec(
                title="测试小说",
                genre="都市悬疑",
                audience="中文读者",
                tone="克制",
                premise="她要追回一份旧账。",
                theme="承担",
                hook="旧账本重新浮出水面。",
                setting="旧港",
                protagonist="沈雾",
                outline_hint="完整闭环",
                world_hint="现实流程优先",
                ending_mode="standalone",
                pov="第三人称有限视角",
                target_total_chars=9000,
                target_chars_per_chapter=1800,
                chapter_count=4,
                volume_count=1,
                chapters_per_volume=4,
                style_examples=["克制"],
                must_include=["账目线"],
                avoid=["作者总结腔"],
                character_seeds=[CharacterSeed(name="沈雾", role="主角")],
            )
            bible = WorldBible(
                title="测试小说",
                logline="旧账重新浮出水面。",
                setting_summary="旧港账房",
                core_conflict="追回被改写的旧账",
                theme_statement="承担",
                narrative_voice=["克制"],
                world_rules=["规则一"],
                chapter_guardrails=["每章推进主线"],
                ending_contract=["闭环"],
                major_threads=["账目线"],
                characters=[],
            )
            chapter = ChapterOutlineItem(1, 1, "第一章", "逼近旧账", "对方会拿程序压她", "她先试公开作证", "仍需推进", "第三人称有限视角", "chapter_hook", chapter_role="investigation")
            plan = ChapterPlan(
                1,
                "第一章",
                "逼近旧账",
                ["账目线"],
                "她带着账页站在人群边上。",
                "她决定明天再压一次程序。",
                "chapter_hook",
                [SceneCard(1, "港口公示栏", "公开作证", "围观施压", "她决定再抬一级", "evidence_push")],
                primary_propulsion="证据推进",
            )
            continuity = ContinuityState(active_threads=["账目线"], must_remember=["旧账页"], last_chapter_index=0)
            pipeline._review_chapter = lambda *_args, **_kwargs: ReviewFeedback(True, 93, ["通过"], [], [], "通过。")  # type: ignore[method-assign]
            pipeline._extract_continuity = lambda *_args, **_kwargs: ContinuityUpdate(1, "她继续逼近旧账。", ["账目线"], [], ["事件1"], [], ["继续逼问"], [])  # type: ignore[method-assign]
            pipeline._extract_long_range_memory = lambda *_args, **_kwargs: LongRangeMemoryUpdate(chapter_index=1)  # type: ignore[method-assign]

            pipeline_module.analyze_chapter = lambda *_args, **_kwargs: LocalQualityReport(
                True,
                91,
                ["最近几章仍在同一推进簇里，存在轻度空转风险。"],
                ["正文仍可读。"],
                "通过。",
                {
                    "stagnation_signal_level": "warning",
                    "stagnation_warning": True,
                    "stagnation_same_family_cluster": 4,
                    "stagnation_same_family_tail": 3,
                    "current_propulsion": "证据推进",
                    "recent_propulsion_history": ["证据推进", "证据推进", "程序拆解"],
                    "propulsion_hard_fail": False,
                },
            )

            result = pipeline._generate_chapter(spec, bible, chapter, plan, continuity, [])

            self.assertTrue(result.review.passed)
            self.assertTrue(result.local_quality.passed)
            self.assertTrue(any("长窗口告警" in note for note in result.continuity.must_remember))
            self.assertFalse((temp_dir / "data" / "latest-stagnation-report.json").exists())
            self.assertEqual(client.text_calls, 1)
        finally:
            pipeline_module.analyze_chapter = original_analyze
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_generate_chapter_records_stagnation_escalation_report(self) -> None:
        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"chapter-stagnation-escalation-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        original_analyze = pipeline_module.analyze_chapter
        try:
            client = StubClient([], ["第一章正文。"])
            pipeline = NovelPipeline(client, temp_dir)
            pipeline._style_bible = StyleBible(tone_targets=["克制"])
            pipeline._voice_cards = []
            pipeline._build_chapter_room = lambda *_args, **_kwargs: {}  # type: ignore[method-assign]
            pipeline._select_story_memories = lambda *_args, **_kwargs: []  # type: ignore[method-assign]
            pipeline._select_style_memories = lambda *_args, **_kwargs: []  # type: ignore[method-assign]
            pipeline._select_promise_memories = lambda *_args, **_kwargs: []  # type: ignore[method-assign]
            pipeline._select_causality_memories = lambda *_args, **_kwargs: []  # type: ignore[method-assign]
            pipeline._latest_logic_audit_for_volume = lambda *_args, **_kwargs: None  # type: ignore[method-assign]
            spec = ProjectSpec(
                title="测试小说",
                genre="都市悬疑",
                audience="中文读者",
                tone="克制",
                premise="她要追回一份旧账。",
                theme="承担",
                hook="旧账本重新浮出水面。",
                setting="旧港",
                protagonist="沈雾",
                outline_hint="完整闭环",
                world_hint="现实流程优先",
                ending_mode="standalone",
                pov="第三人称有限视角",
                target_total_chars=9000,
                target_chars_per_chapter=1800,
                chapter_count=4,
                volume_count=1,
                chapters_per_volume=4,
                style_examples=["克制"],
                must_include=["账目线"],
                avoid=["作者总结腔"],
                character_seeds=[CharacterSeed(name="沈雾", role="主角")],
            )
            bible = WorldBible(
                title="测试小说",
                logline="旧账重新浮出水面。",
                setting_summary="旧港账房",
                core_conflict="追回被改写的旧账",
                theme_statement="承担",
                narrative_voice=["克制"],
                world_rules=["规则一"],
                chapter_guardrails=["每章推进主线"],
                ending_contract=["闭环"],
                major_threads=["账目线"],
                characters=[],
            )
            chapter = ChapterOutlineItem(1, 1, "第一章", "逼近旧账", "对方会拿程序压她", "她先试公开作证", "仍需推进", "第三人称有限视角", "chapter_hook", chapter_role="investigation")
            plan = ChapterPlan(
                1,
                "第一章",
                "逼近旧账",
                ["账目线"],
                "她带着账页站在人群边上。",
                "她决定明天再压一次程序。",
                "chapter_hook",
                [SceneCard(1, "港口公示栏", "公开作证", "围观施压", "她决定再抬一级", "evidence_push")],
                primary_propulsion="证据推进",
            )
            continuity = ContinuityState(active_threads=["账目线"], must_remember=["旧账页"], last_chapter_index=0)
            pipeline._review_chapter = lambda *_args, **_kwargs: ReviewFeedback(True, 92, ["通过"], [], [], "通过。")  # type: ignore[method-assign]
            pipeline._extract_continuity = lambda *_args, **_kwargs: ContinuityUpdate(1, "她继续逼近旧账。", ["账目线"], [], ["事件1"], [], ["继续逼问"], [])  # type: ignore[method-assign]
            pipeline._extract_long_range_memory = lambda *_args, **_kwargs: LongRangeMemoryUpdate(chapter_index=1)  # type: ignore[method-assign]
            pipeline._run_stagnation_judge = lambda *_args, **_kwargs: StagnationJudgeReview(  # type: ignore[method-assign]
                chapter_index=1,
                verdict="stagnation_risk",
                recommended_action="forward_fix",
                confidence=82,
                reason="最近长窗口里公开施压升级方式高度重复，建议仅做前推修正。",
                scope_start_chapter=1,
                scope_end_chapter=1,
                next_chapter_constraints=["下一章引入新的代价与后果。"],
                repair_goal="后续两章明显换挡。",
            )

            pipeline_module.analyze_chapter = lambda *_args, **_kwargs: LocalQualityReport(
                True,
                89,
                ["最近长窗口存在明显空转风险。"],
                ["正文仍可读。"],
                "通过。",
                {
                    "stagnation_signal_level": "escalation",
                    "stagnation_escalation": True,
                    "stagnation_same_family_cluster": 10,
                    "stagnation_same_family_tail": 6,
                    "current_propulsion": "证据推进",
                    "recent_propulsion_history": ["证据推进"] * 9 + ["程序拆解"],
                    "propulsion_hard_fail": False,
                },
            )

            result = pipeline._generate_chapter(spec, bible, chapter, plan, continuity, [])

            self.assertTrue(result.local_quality.passed)
            self.assertTrue(any("长窗口空转升级" in note for note in result.continuity.must_remember))
            report_path = temp_dir / "data" / "latest-stagnation-report.json"
            self.assertTrue(report_path.exists())
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["signal_level"], "escalation")
            decision_path = temp_dir / "data" / "latest-stagnation-decision.json"
            self.assertTrue(decision_path.exists())
            decision = json.loads(decision_path.read_text(encoding="utf-8"))
            self.assertEqual(decision["decision"], "forward_fix")
            self.assertTrue(result.continuity.next_chapter_targets)
        finally:
            pipeline_module.analyze_chapter = original_analyze
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_generate_chapter_accepts_stagnation_escalation_when_variation_is_still_distinct(self) -> None:
        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"chapter-stagnation-accept-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        original_analyze = pipeline_module.analyze_chapter
        try:
            client = StubClient([], ["第一章正文。"])
            pipeline = NovelPipeline(client, temp_dir)
            pipeline._style_bible = StyleBible(tone_targets=["克制"])
            pipeline._voice_cards = []
            pipeline._build_chapter_room = lambda *_args, **_kwargs: {}  # type: ignore[method-assign]
            pipeline._select_story_memories = lambda *_args, **_kwargs: []  # type: ignore[method-assign]
            pipeline._select_style_memories = lambda *_args, **_kwargs: []  # type: ignore[method-assign]
            pipeline._select_promise_memories = lambda *_args, **_kwargs: []  # type: ignore[method-assign]
            pipeline._select_causality_memories = lambda *_args, **_kwargs: []  # type: ignore[method-assign]
            pipeline._latest_logic_audit_for_volume = lambda *_args, **_kwargs: None  # type: ignore[method-assign]
            spec = ProjectSpec(
                title="测试小说",
                genre="都市悬疑",
                audience="中文读者",
                tone="克制",
                premise="她要追回一份旧账。",
                theme="承担",
                hook="旧账本重新浮出水面。",
                setting="旧港",
                protagonist="沈雾",
                outline_hint="完整闭环",
                world_hint="现实流程优先",
                ending_mode="standalone",
                pov="第三人称有限视角",
                target_total_chars=9000,
                target_chars_per_chapter=1800,
                chapter_count=4,
                volume_count=1,
                chapters_per_volume=4,
                style_examples=["克制"],
                must_include=["账目线"],
                avoid=["作者总结腔"],
                character_seeds=[CharacterSeed(name="沈雾", role="主角")],
            )
            bible = WorldBible(
                title="测试小说",
                logline="旧账重新浮出水面。",
                setting_summary="旧港账房",
                core_conflict="追回被改写的旧账",
                theme_statement="承担",
                narrative_voice=["克制"],
                world_rules=["规则一"],
                chapter_guardrails=["每章推进主线"],
                ending_contract=["闭环"],
                major_threads=["账目线"],
                characters=[],
            )
            chapter = ChapterOutlineItem(1, 1, "第一章", "逼近旧账", "对方会拿程序压她", "她先试公开作证", "仍需推进", "第三人称有限视角", "chapter_hook", chapter_role="investigation")
            plan = ChapterPlan(
                1,
                "第一章",
                "逼近旧账",
                ["账目线"],
                "她带着账页站在人群边上。",
                "她决定明天再压一次程序。",
                "chapter_hook",
                [SceneCard(1, "港口公示栏", "公开作证", "围观施压", "她决定再抬一级", "evidence_push")],
                primary_propulsion="证据推进",
            )
            continuity = ContinuityState(active_threads=["账目线"], must_remember=["旧账页"], last_chapter_index=0)
            pipeline._review_chapter = lambda *_args, **_kwargs: ReviewFeedback(True, 93, ["通过"], [], [], "通过。")  # type: ignore[method-assign]
            pipeline._extract_continuity = lambda *_args, **_kwargs: ContinuityUpdate(1, "她继续逼近旧账。", ["账目线"], [], ["事件1"], [], ["继续逼问"], [])  # type: ignore[method-assign]
            pipeline._extract_long_range_memory = lambda *_args, **_kwargs: LongRangeMemoryUpdate(chapter_index=1)  # type: ignore[method-assign]
            pipeline._run_stagnation_judge = lambda *_args, **_kwargs: StagnationJudgeReview(  # type: ignore[method-assign]
                chapter_index=1,
                verdict="reasonable_cluster",
                recommended_action="accept",
                confidence=86,
                reason="这是合理的连续高潮簇，虽然同属调查/公开推进，但功能与后果仍在递进。",
                scope_start_chapter=1,
                scope_end_chapter=1,
                next_chapter_constraints=["继续观察是否产生新后果。"],
                repair_goal="",
            )

            pipeline_module.analyze_chapter = lambda *_args, **_kwargs: LocalQualityReport(
                True,
                90,
                ["最近长窗口存在明显空转风险。"],
                ["正文仍可读。"],
                "通过。",
                {
                    "stagnation_signal_level": "escalation",
                    "stagnation_escalation": True,
                    "stagnation_same_family_cluster": 10,
                    "stagnation_same_family_tail": 5,
                    "stagnation_same_role_tail": 2,
                    "stagnation_same_scene_tail": 1,
                    "stagnation_same_variation_tail": 1,
                    "current_propulsion": "证据推进",
                    "recent_propulsion_history": ["证据推进"] * 9 + ["程序拆解"],
                    "propulsion_hard_fail": False,
                },
            )

            result = pipeline._generate_chapter(spec, bible, chapter, plan, continuity, [])

            decision = json.loads((temp_dir / "data" / "latest-stagnation-decision.json").read_text(encoding="utf-8"))
            self.assertEqual(decision["decision"], "accept")
            self.assertTrue(any("合理连续高潮" in note or "继续观察" in note for note in result.continuity.must_remember))
        finally:
            pipeline_module.analyze_chapter = original_analyze
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_generate_chapter_runs_stagnation_local_repair_for_recent_cluster(self) -> None:
        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"chapter-stagnation-local-repair-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        original_analyze = pipeline_module.analyze_chapter
        try:
            client = StubClient([], ["第二章正文。"])
            pipeline = NovelPipeline(client, temp_dir)
            pipeline._style_bible = StyleBible(tone_targets=["克制"])
            pipeline._voice_cards = []
            pipeline._build_chapter_room = lambda *_args, **_kwargs: {}  # type: ignore[method-assign]
            pipeline._select_story_memories = lambda *_args, **_kwargs: []  # type: ignore[method-assign]
            pipeline._select_style_memories = lambda *_args, **_kwargs: []  # type: ignore[method-assign]
            pipeline._select_promise_memories = lambda *_args, **_kwargs: []  # type: ignore[method-assign]
            pipeline._select_causality_memories = lambda *_args, **_kwargs: []  # type: ignore[method-assign]
            pipeline._latest_logic_audit_for_volume = lambda *_args, **_kwargs: None  # type: ignore[method-assign]
            spec = ProjectSpec(
                title="测试小说",
                genre="都市悬疑",
                audience="中文读者",
                tone="克制",
                premise="她要追回一份旧账。",
                theme="承担",
                hook="旧账本重新浮出水面。",
                setting="旧港",
                protagonist="沈雾",
                outline_hint="完整闭环",
                world_hint="现实流程优先",
                ending_mode="standalone",
                pov="第三人称有限视角",
                target_total_chars=9000,
                target_chars_per_chapter=1800,
                chapter_count=4,
                volume_count=1,
                chapters_per_volume=4,
                style_examples=["克制"],
                must_include=["账目线"],
                avoid=["作者总结腔"],
                character_seeds=[CharacterSeed(name="沈雾", role="主角")],
            )
            bible = WorldBible(
                title="测试小说",
                logline="旧账重新浮出水面。",
                setting_summary="旧港账房",
                core_conflict="追回被改写的旧账",
                theme_statement="承担",
                narrative_voice=["克制"],
                world_rules=["规则一"],
                chapter_guardrails=["每章推进主线"],
                ending_contract=["闭环"],
                major_threads=["账目线"],
                characters=[],
            )
            book_outline = BookOutline(
                title="测试小说",
                one_line_summary="旧账浮出水面。",
                act_structure=["起", "承", "转", "合"],
                volumes=[VolumeBlueprint(1, 1, 4, "第一卷", "调查", "真账在哪", "公开局升级", "从围观到决断")],
            )
            volume_outline = VolumeOutline(
                volume_index=1,
                title="第一卷",
                goal="追回旧账",
                climax="公开局升级",
                carry_over_threads=["账目线"],
                chapter_targets=[
                    ChapterOutlineItem(1, 1, "第一章", "铺垫", "旧账浮出", "先找到线头", "继续推进", "第三人称有限视角", "chapter_hook", chapter_role="investigation"),
                    ChapterOutlineItem(2, 1, "第二章", "逼近", "对方会拿程序压她", "继续逼近旧账", "仍需推进", "第三人称有限视角", "chapter_hook", chapter_role="investigation"),
                ],
            )
            chapter = volume_outline.chapter_targets[1]
            plan = ChapterPlan(
                2,
                "第二章",
                "逼近旧账",
                ["账目线"],
                "她带着账页站在人群边上。",
                "她决定明天再压一次程序。",
                "chapter_hook",
                [SceneCard(1, "港口公示栏", "公开作证", "围观施压", "她决定再抬一级", "evidence_push")],
                primary_propulsion="证据推进",
            )
            prior = [
                ChapterResult(
                    index=1,
                    volume_index=1,
                    title="第一章",
                    outline_item=volume_outline.chapter_targets[0],
                    draft="第一章旧稿。",
                    plan=ChapterPlan(
                        1,
                        "第一章",
                        "铺垫",
                        ["账目线"],
                        "旧账浮出。",
                        "她决定继续查。",
                        "chapter_hook",
                        [SceneCard(1, "旧港", "找到线头", "有人盯梢", "她决定继续查", "evidence_push")],
                        primary_propulsion="证据推进",
                    ),
                    review=ReviewFeedback(True, 90, ["通过"], [], [], "通过。"),
                    local_quality=LocalQualityReport(True, 90, [], ["通过"], "通过。", {}),
                    continuity=ContinuityUpdate(1, "旧账浮出。", ["账目线"], [], ["事件1"], [], ["继续逼问"], []),
                    attempts=1,
                    long_memory=LongRangeMemoryUpdate(chapter_index=1),
                )
            ]
            continuity = pipeline._rebuild_continuity_state(bible, prior)
            pipeline._review_chapter = lambda *_args, **_kwargs: ReviewFeedback(True, 93, ["通过"], [], [], "通过。")  # type: ignore[method-assign]
            pipeline._extract_continuity = lambda *_args, **_kwargs: ContinuityUpdate(2, "她继续逼近旧账。", [], [], ["事件2"], [], ["继续逼问"], [])  # type: ignore[method-assign]
            pipeline._extract_long_range_memory = lambda *_args, **_kwargs: LongRangeMemoryUpdate(chapter_index=2)  # type: ignore[method-assign]
            pipeline._run_stagnation_judge = lambda *_args, **_kwargs: StagnationJudgeReview(  # type: ignore[method-assign]
                chapter_index=2,
                verdict="true_stagnation",
                recommended_action="local_repair",
                confidence=91,
                reason="最近章节簇在公开施压链上空转，应对最近局部章节做最小必要修复。",
                scope_start_chapter=1,
                scope_end_chapter=2,
                next_chapter_constraints=["修复后后续章节必须加入新代价。"],
                repair_goal="回修最近章节簇，避免空转。",
            )

            repaired_prior = copy.deepcopy(prior[0])
            repaired_prior.draft = "第一章修订稿。"
            repaired_current = ChapterResult(
                index=2,
                volume_index=1,
                title="第二章",
                outline_item=chapter,
                draft="第二章重排稿。",
                plan=plan,
                review=ReviewFeedback(True, 94, ["通过"], [], [], "通过。"),
                local_quality=LocalQualityReport(True, 92, [], ["通过"], "通过。", {}),
                continuity=ContinuityUpdate(2, "这次改成了余波与代价。", [], [], ["事件2"], [], ["下一章换打法"], []),
                attempts=2,
                long_memory=LongRangeMemoryUpdate(chapter_index=2),
            )
            pipeline._repair_chapter_cluster = lambda *_args, **_kwargs: [repaired_prior, repaired_current]  # type: ignore[method-assign]

            pipeline_module.analyze_chapter = lambda *_args, **_kwargs: LocalQualityReport(
                True,
                88,
                ["最近长窗口存在明显空转风险。"],
                ["正文仍可读。"],
                "通过。",
                {
                    "stagnation_signal_level": "escalation",
                    "stagnation_escalation": True,
                    "stagnation_same_family_cluster": 12,
                    "stagnation_same_family_tail": 9,
                    "stagnation_same_role_tail": 4,
                    "stagnation_same_scene_tail": 3,
                    "stagnation_same_variation_tail": 3,
                    "current_propulsion": "证据推进",
                    "recent_propulsion_history": ["证据推进"] * 10 + ["程序拆解"],
                    "propulsion_hard_fail": False,
                },
            )

            result = pipeline._generate_chapter(
                spec,
                bible,
                chapter,
                plan,
                continuity,
                prior,
                book_outline=book_outline,
                volume_outline=volume_outline,
            )

            self.assertEqual(result.draft, "第二章重排稿。")
            self.assertEqual(prior[0].draft, "第一章修订稿。")
            pending = pipeline._consume_pending_chapter_repair_state()
            self.assertIsNotNone(pending)
            decision = json.loads((temp_dir / "data" / "latest-stagnation-decision.json").read_text(encoding="utf-8"))
            self.assertEqual(decision["decision"], "local_repair")
            self.assertEqual((temp_dir / "chapters" / "chapter-02.md").read_text(encoding="utf-8"), "第二章重排稿。")
        finally:
            pipeline_module.analyze_chapter = original_analyze
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_generate_chapter_runs_stagnation_phase_repair_automatically(self) -> None:
        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"chapter-stagnation-phase-repair-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        original_analyze = pipeline_module.analyze_chapter
        try:
            client = StubClient([], ["第三章正文。"])
            pipeline = NovelPipeline(client, temp_dir)
            pipeline._style_bible = StyleBible(tone_targets=["克制"])
            pipeline._voice_cards = []
            pipeline._build_chapter_room = lambda *_args, **_kwargs: {}  # type: ignore[method-assign]
            pipeline._select_story_memories = lambda *_args, **_kwargs: []  # type: ignore[method-assign]
            pipeline._select_style_memories = lambda *_args, **_kwargs: []  # type: ignore[method-assign]
            pipeline._select_promise_memories = lambda *_args, **_kwargs: []  # type: ignore[method-assign]
            pipeline._select_causality_memories = lambda *_args, **_kwargs: []  # type: ignore[method-assign]
            pipeline._latest_logic_audit_for_volume = lambda *_args, **_kwargs: None  # type: ignore[method-assign]
            spec = ProjectSpec(
                title="测试小说",
                genre="都市悬疑",
                audience="中文读者",
                tone="克制",
                premise="她要追回一份旧账。",
                theme="承担",
                hook="旧账本重新浮出水面。",
                setting="旧港",
                protagonist="沈雾",
                outline_hint="完整闭环",
                world_hint="现实流程优先",
                ending_mode="standalone",
                pov="第三人称有限视角",
                target_total_chars=12000,
                target_chars_per_chapter=1800,
                chapter_count=6,
                volume_count=1,
                chapters_per_volume=6,
                style_examples=["克制"],
                must_include=["账目线"],
                avoid=["作者总结腔"],
                character_seeds=[CharacterSeed(name="沈雾", role="主角")],
            )
            bible = WorldBible(
                title="测试小说",
                logline="旧账重新浮出水面。",
                setting_summary="旧港账房",
                core_conflict="追回被改写的旧账",
                theme_statement="承担",
                narrative_voice=["克制"],
                world_rules=["规则一"],
                chapter_guardrails=["每章推进主线"],
                ending_contract=["闭环"],
                major_threads=["账目线"],
                characters=[],
            )
            book_outline = BookOutline(
                title="测试小说",
                one_line_summary="旧账浮出水面。",
                act_structure=["起", "承", "转", "合"],
                volumes=[VolumeBlueprint(1, 1, 6, "第一卷", "调查", "真账在哪", "公开局升级", "从围观到决断")],
            )
            volume_outline = VolumeOutline(
                volume_index=1,
                title="第一卷",
                goal="追回旧账",
                climax="公开局升级",
                carry_over_threads=["账目线"],
                chapter_targets=[
                    ChapterOutlineItem(1, 1, "第一章", "铺垫", "旧账浮出", "先找到线头", "继续推进", "第三人称有限视角", "chapter_hook", chapter_role="investigation"),
                    ChapterOutlineItem(2, 1, "第二章", "逼近", "对方会拿程序压她", "继续逼近旧账", "仍需推进", "第三人称有限视角", "chapter_hook", chapter_role="investigation"),
                    ChapterOutlineItem(3, 1, "第三章", "抬级", "公开局继续升级", "她需要强行换出新的后果", "仍需推进", "第三人称有限视角", "chapter_hook", chapter_role="investigation"),
                ],
            )
            chapter = volume_outline.chapter_targets[2]
            plan = ChapterPlan(
                3,
                "第三章",
                "抬级",
                ["账目线"],
                "她站在公示栏边上。",
                "她决定把局面推向更大的公开场合。",
                "chapter_hook",
                [SceneCard(1, "港口公示栏", "公开作证", "围观施压", "她决定再抬一级", "evidence_push")],
                primary_propulsion="证据推进",
            )
            prior = [
                ChapterResult(
                    index=1,
                    volume_index=1,
                    title="第一章",
                    outline_item=volume_outline.chapter_targets[0],
                    draft="第一章旧稿。",
                    plan=ChapterPlan(1, "第一章", "铺垫", ["账目线"], "旧账浮出。", "她决定继续查。", "chapter_hook", [SceneCard(1, "旧港", "找到线头", "有人盯梢", "她决定继续查", "evidence_push")], primary_propulsion="证据推进"),
                    review=ReviewFeedback(True, 90, ["通过"], [], [], "通过。"),
                    local_quality=LocalQualityReport(True, 90, [], ["通过"], "通过。", {}),
                    continuity=ContinuityUpdate(1, "旧账浮出。", ["账目线"], [], ["事件1"], [], ["继续逼问"], []),
                    attempts=1,
                    long_memory=LongRangeMemoryUpdate(chapter_index=1),
                ),
                ChapterResult(
                    index=2,
                    volume_index=1,
                    title="第二章",
                    outline_item=volume_outline.chapter_targets[1],
                    draft="第二章旧稿。",
                    plan=ChapterPlan(2, "第二章", "逼近", ["账目线"], "她继续逼近。", "她决定再压程序。", "chapter_hook", [SceneCard(1, "账房门口", "逼问", "程序卡口", "她决定再抬一级", "evidence_push")], primary_propulsion="证据推进"),
                    review=ReviewFeedback(True, 90, ["通过"], [], [], "通过。"),
                    local_quality=LocalQualityReport(True, 90, [], ["通过"], "通过。", {}),
                    continuity=ContinuityUpdate(2, "旧账逼近。", ["账目线"], [], ["事件2"], [], ["继续逼问"], []),
                    attempts=1,
                    long_memory=LongRangeMemoryUpdate(chapter_index=2),
                ),
            ]
            continuity = pipeline._rebuild_continuity_state(bible, prior)
            pipeline._review_chapter = lambda *_args, **_kwargs: ReviewFeedback(True, 92, ["通过"], [], [], "通过。")  # type: ignore[method-assign]
            pipeline._extract_continuity = lambda *_args, **_kwargs: ContinuityUpdate(3, "第三章仍有空转风险。", [], [], ["事件3"], [], ["后续必须换出新后果"], [])  # type: ignore[method-assign]
            pipeline._extract_long_range_memory = lambda *_args, **_kwargs: LongRangeMemoryUpdate(chapter_index=3)  # type: ignore[method-assign]
            pipeline._run_stagnation_judge = lambda *_args, **_kwargs: StagnationJudgeReview(  # type: ignore[method-assign]
                chapter_index=3,
                verdict="true_stagnation",
                recommended_action="phase_repair",
                confidence=90,
                reason="最近阶段内连续章节都在公开施压链上抬级，已经形成阶段性空转。",
                scope_start_chapter=1,
                scope_end_chapter=3,
                next_chapter_constraints=["修复后必须显式加入新的代价与后果。"],
                repair_goal="阶段级回修最近章节簇。",
            )
            repaired_prior_1 = copy.deepcopy(prior[0])
            repaired_prior_1.draft = "第一章阶段修订稿。"
            repaired_prior_2 = copy.deepcopy(prior[1])
            repaired_prior_2.draft = "第二章阶段修订稿。"
            repaired_current = ChapterResult(
                index=3,
                volume_index=1,
                title="第三章",
                outline_item=chapter,
                draft="第三章阶段重排稿。",
                plan=plan,
                review=ReviewFeedback(True, 94, ["通过"], [], [], "通过。"),
                local_quality=LocalQualityReport(True, 91, [], ["通过"], "通过。", {}),
                continuity=ContinuityUpdate(3, "第三章改成了代价与余波。", [], [], ["事件3"], [], ["后续换打法"], []),
                attempts=2,
                long_memory=LongRangeMemoryUpdate(chapter_index=3),
            )
            pipeline._repair_chapter_cluster = lambda *_args, **_kwargs: [repaired_prior_1, repaired_prior_2, repaired_current]  # type: ignore[method-assign]

            pipeline_module.analyze_chapter = lambda *_args, **_kwargs: LocalQualityReport(
                True,
                87,
                ["最近长窗口存在明显空转风险。"],
                ["正文仍可读。"],
                "通过。",
                {
                    "stagnation_signal_level": "escalation",
                    "stagnation_escalation": True,
                    "stagnation_same_family_cluster": 14,
                    "stagnation_same_family_tail": 10,
                    "stagnation_same_role_tail": 4,
                    "stagnation_same_scene_tail": 4,
                    "stagnation_same_variation_tail": 3,
                    "current_propulsion": "证据推进",
                    "recent_propulsion_history": ["证据推进"] * 12 + ["程序拆解"],
                    "propulsion_hard_fail": False,
                },
            )

            result = pipeline._generate_chapter(
                spec,
                bible,
                chapter,
                plan,
                continuity,
                prior,
                book_outline=book_outline,
                volume_outline=volume_outline,
            )

            self.assertEqual(result.draft, "第三章阶段重排稿。")
            self.assertEqual(prior[0].draft, "第一章阶段修订稿。")
            self.assertEqual(prior[1].draft, "第二章阶段修订稿。")
            self.assertTrue((temp_dir / "data" / "latest-stagnation-execution.json").exists())
            execution = json.loads((temp_dir / "data" / "latest-stagnation-execution.json").read_text(encoding="utf-8"))
            self.assertEqual(execution["executed_action"], "phase_repair")
            self.assertFalse((temp_dir / "data" / "pending-upper-decision.json").exists())
        finally:
            pipeline_module.analyze_chapter = original_analyze
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_generate_chapter_planning_priority_downgrades_heavy_stagnation_repair_in_climax_cluster(self) -> None:
        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"chapter-stagnation-planning-priority-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        original_analyze = pipeline_module.analyze_chapter
        try:
            client = StubClient([], ["第一章正文。"])
            pipeline = NovelPipeline(client, temp_dir)
            pipeline._style_bible = StyleBible(tone_targets=["克制"])
            pipeline._voice_cards = []
            pipeline._build_chapter_room = lambda *_args, **_kwargs: {}  # type: ignore[method-assign]
            pipeline._select_story_memories = lambda *_args, **_kwargs: []  # type: ignore[method-assign]
            pipeline._select_style_memories = lambda *_args, **_kwargs: []  # type: ignore[method-assign]
            pipeline._select_promise_memories = lambda *_args, **_kwargs: []  # type: ignore[method-assign]
            pipeline._select_causality_memories = lambda *_args, **_kwargs: []  # type: ignore[method-assign]
            pipeline._latest_logic_audit_for_volume = lambda *_args, **_kwargs: None  # type: ignore[method-assign]
            spec = ProjectSpec(
                title="测试小说",
                genre="热血玄幻",
                audience="中文读者",
                tone="凌厉",
                premise="她要在宗门大比里连打到底。",
                theme="代价",
                hook="决战开始。",
                setting="山门",
                protagonist="陆惊潮",
                outline_hint="连战高潮",
                world_hint="热血战斗优先",
                ending_mode="series",
                pov="第三人称有限视角",
                target_total_chars=12000,
                target_chars_per_chapter=2000,
                chapter_count=6,
                volume_count=1,
                chapters_per_volume=6,
                style_examples=["凌厉"],
                must_include=["大比"],
                avoid=["说教"],
                character_seeds=[CharacterSeed(name="陆惊潮", role="主角")],
            )
            bible = WorldBible(
                title="测试小说",
                logline="宗门大比连战到底。",
                setting_summary="山门",
                core_conflict="她必须连打到底。",
                theme_statement="代价",
                narrative_voice=["凌厉"],
                world_rules=["胜负要付代价。"],
                chapter_guardrails=["高潮段允许连续战斗推进。"],
                ending_contract=["保留后续空间。"],
                major_threads=["大比线"],
                characters=[],
            )
            book_outline = BookOutline(
                title="测试小说",
                one_line_summary="宗门大比连战到底。",
                act_structure=["起", "承", "转", "合"],
                volumes=[
                    VolumeBlueprint(
                        1,
                        1,
                        6,
                        "决战卷",
                        "高潮决战",
                        "她能否连战到底",
                        "连打升级",
                        "一路压到最后一战",
                        phase_type="climax",
                    )
                ],
            )
            volume_outline = VolumeOutline(
                volume_index=1,
                title="决战卷",
                goal="连战到底",
                climax="总决战",
                carry_over_threads=["大比线"],
                chapter_targets=[ChapterOutlineItem(1, 1, "第一章", "开战", "硬仗", "第一场决战", "仍有更大战斗", "第三人称有限视角", "chapter_hook", chapter_role="climax")],
            )
            chapter = volume_outline.chapter_targets[0]
            plan = ChapterPlan(
                1,
                "第一章",
                "开战",
                ["大比线"],
                "她踏上擂台。",
                "下一场更狠。",
                "chapter_hook",
                [SceneCard(1, "擂台", "连战", "正面对轰", "她压住第一轮", "setpiece")],
                primary_propulsion="动作压力",
                chapter_role="climax",
            )
            continuity = ContinuityState(active_threads=["大比线"], must_remember=["连打高潮"], last_chapter_index=0)
            pipeline._review_chapter = lambda *_args, **_kwargs: ReviewFeedback(True, 93, ["通过"], [], [], "通过。")  # type: ignore[method-assign]
            pipeline._extract_continuity = lambda *_args, **_kwargs: ContinuityUpdate(1, "决战继续升级。", ["大比线"], [], ["事件1"], [], ["继续推进"], [])  # type: ignore[method-assign]
            pipeline._extract_long_range_memory = lambda *_args, **_kwargs: LongRangeMemoryUpdate(chapter_index=1)  # type: ignore[method-assign]
            pipeline._run_stagnation_judge = lambda *_args, **_kwargs: StagnationJudgeReview(  # type: ignore[method-assign]
                chapter_index=1,
                verdict="stagnation_risk",
                recommended_action="phase_repair",
                confidence=82,
                reason="局部看推进家族重复，但这是高潮簇中的连续硬仗。",
                scope_start_chapter=1,
                scope_end_chapter=1,
                next_chapter_constraints=["继续保持硬仗，但要补新的代价。"],
                repair_goal="若非高潮簇则建议阶段回修。",
            )

            pipeline_module.analyze_chapter = lambda *_args, **_kwargs: LocalQualityReport(
                True,
                88,
                ["最近长窗口存在明显空转风险。"],
                ["正文仍可读。"],
                "通过。",
                {
                    "stagnation_signal_level": "escalation",
                    "stagnation_escalation": True,
                    "stagnation_same_family_cluster": 14,
                    "stagnation_same_family_tail": 10,
                    "stagnation_same_role_tail": 4,
                    "stagnation_same_scene_tail": 3,
                    "stagnation_same_variation_tail": 3,
                    "current_propulsion": "动作压力",
                    "recent_propulsion_history": ["动作压力"] * 12 + ["代价交换"],
                    "propulsion_hard_fail": False,
                },
            )

            result = pipeline._generate_chapter(
                spec,
                bible,
                chapter,
                plan,
                continuity,
                [],
                book_outline=book_outline,
                volume_outline=volume_outline,
            )

            decision = json.loads((temp_dir / "data" / "latest-stagnation-decision.json").read_text(encoding="utf-8"))
            self.assertEqual(decision["decision"], "forward_fix")
            self.assertTrue(any("代价" in item for item in result.continuity.next_chapter_targets))
        finally:
            pipeline_module.analyze_chapter = original_analyze
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_generate_chapter_downgrades_repeated_phase_repair_in_same_volume(self) -> None:
        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"chapter-stagnation-phase-guard-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        original_analyze = pipeline_module.analyze_chapter
        try:
            client = StubClient([], ["第四章正文。"])
            pipeline = NovelPipeline(client, temp_dir)
            pipeline._style_bible = StyleBible(tone_targets=["克制"])
            pipeline._voice_cards = []
            pipeline._build_chapter_room = lambda *_args, **_kwargs: {}  # type: ignore[method-assign]
            pipeline._select_story_memories = lambda *_args, **_kwargs: []  # type: ignore[method-assign]
            pipeline._select_style_memories = lambda *_args, **_kwargs: []  # type: ignore[method-assign]
            pipeline._select_promise_memories = lambda *_args, **_kwargs: []  # type: ignore[method-assign]
            pipeline._select_causality_memories = lambda *_args, **_kwargs: []  # type: ignore[method-assign]
            pipeline._latest_logic_audit_for_volume = lambda *_args, **_kwargs: None  # type: ignore[method-assign]
            spec = ProjectSpec(
                title="测试小说",
                genre="都市悬疑",
                audience="中文读者",
                tone="克制",
                premise="她要追回一份旧账。",
                theme="承担",
                hook="旧账本重新浮出水面。",
                setting="旧港",
                protagonist="沈雾",
                outline_hint="完整闭环",
                world_hint="现实流程优先",
                ending_mode="standalone",
                pov="第三人称有限视角",
                target_total_chars=12000,
                target_chars_per_chapter=1800,
                chapter_count=6,
                volume_count=1,
                chapters_per_volume=6,
                style_examples=["克制"],
                must_include=["账目线"],
                avoid=["作者总结腔"],
                character_seeds=[CharacterSeed(name="沈雾", role="主角")],
            )
            bible = WorldBible(
                title="测试小说",
                logline="旧账重新浮出水面。",
                setting_summary="旧港账房",
                core_conflict="追回被改写的旧账",
                theme_statement="承担",
                narrative_voice=["克制"],
                world_rules=["规则一"],
                chapter_guardrails=["每章推进主线"],
                ending_contract=["闭环"],
                major_threads=["账目线"],
                characters=[],
            )
            book_outline = BookOutline(
                title="测试小说",
                one_line_summary="旧账浮出水面。",
                act_structure=["起", "承", "转", "合"],
                volumes=[VolumeBlueprint(1, 1, 6, "第一卷", "调查", "真账在哪", "公开局升级", "从围观到决断")],
            )
            volume_outline = VolumeOutline(
                volume_index=1,
                title="第一卷",
                goal="追回旧账",
                climax="公开局升级",
                carry_over_threads=["账目线"],
                chapter_targets=[ChapterOutlineItem(4, 1, "第四章", "再逼近", "继续抬级", "她再次冲向公开场合", "仍需推进", "第三人称有限视角", "chapter_hook", chapter_role="investigation")],
            )
            chapter = volume_outline.chapter_targets[0]
            plan = ChapterPlan(
                4,
                "第四章",
                "再逼近",
                ["账目线"],
                "她又站到公示栏边上。",
                "她仍要把局面再推一级。",
                "chapter_hook",
                [SceneCard(1, "港口公示栏", "公开作证", "围观施压", "她决定再抬一级", "evidence_push")],
                primary_propulsion="证据推进",
            )
            continuity = ContinuityState(active_threads=["账目线"], must_remember=["旧账页"], last_chapter_index=3, last_volume_index=1)
            pipeline._review_chapter = lambda *_args, **_kwargs: ReviewFeedback(True, 92, ["通过"], [], [], "通过。")  # type: ignore[method-assign]
            pipeline._extract_continuity = lambda *_args, **_kwargs: ContinuityUpdate(4, "第四章继续推进。", [], [], ["事件4"], [], ["后续必须换出新后果"], [])  # type: ignore[method-assign]
            pipeline._extract_long_range_memory = lambda *_args, **_kwargs: LongRangeMemoryUpdate(chapter_index=4)  # type: ignore[method-assign]
            pipeline._run_stagnation_judge = lambda *_args, **_kwargs: StagnationJudgeReview(  # type: ignore[method-assign]
                chapter_index=4,
                verdict="true_stagnation",
                recommended_action="phase_repair",
                confidence=92,
                reason="最近阶段继续空转。",
                scope_start_chapter=1,
                scope_end_chapter=4,
                next_chapter_constraints=["后续必须改出新后果。"],
                repair_goal="建议再次阶段回修。",
            )
            repaired_current = ChapterResult(
                index=4,
                volume_index=1,
                title="第四章",
                outline_item=chapter,
                draft="第四章局部修订稿。",
                plan=plan,
                review=ReviewFeedback(True, 93, ["通过"], [], [], "通过。"),
                local_quality=LocalQualityReport(True, 90, [], ["通过"], "通过。", {}),
                continuity=ContinuityUpdate(4, "第四章局部修订。", [], [], ["事件4"], [], ["后续必须改出新后果"], []),
                attempts=2,
                long_memory=LongRangeMemoryUpdate(chapter_index=4),
            )
            pipeline._repair_chapter_cluster = lambda *_args, **_kwargs: [repaired_current]  # type: ignore[method-assign]
            (temp_dir / "data").mkdir(parents=True, exist_ok=True)
            (temp_dir / "data" / "stagnation-repair-history.json").write_text(
                json.dumps({"by_volume": {"1": {"phase_repair": 1, "arc_repair": 0}}, "records": []}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            pipeline._stagnation_repair_history = pipeline._load_stagnation_repair_history()

            pipeline_module.analyze_chapter = lambda *_args, **_kwargs: LocalQualityReport(
                True,
                87,
                ["最近长窗口存在明显空转风险。"],
                ["正文仍可读。"],
                "通过。",
                {
                    "stagnation_signal_level": "escalation",
                    "stagnation_escalation": True,
                    "stagnation_same_family_cluster": 14,
                    "stagnation_same_family_tail": 10,
                    "stagnation_same_role_tail": 4,
                    "stagnation_same_scene_tail": 4,
                    "stagnation_same_variation_tail": 3,
                    "current_propulsion": "证据推进",
                    "recent_propulsion_history": ["证据推进"] * 12 + ["程序拆解"],
                    "propulsion_hard_fail": False,
                },
            )

            result = pipeline._generate_chapter(
                spec,
                bible,
                chapter,
                plan,
                continuity,
                [],
                book_outline=book_outline,
                volume_outline=volume_outline,
            )

            decision = json.loads((temp_dir / "data" / "latest-stagnation-decision.json").read_text(encoding="utf-8"))
            self.assertEqual(decision["decision"], "local_repair")
            execution = json.loads((temp_dir / "data" / "latest-stagnation-execution.json").read_text(encoding="utf-8"))
            self.assertEqual(execution["executed_action"], "local_repair")
            self.assertTrue(result.continuity.next_chapter_targets)
        finally:
            pipeline_module.analyze_chapter = original_analyze
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_generate_chapter_arc_repair_requests_control_refresh(self) -> None:
        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"chapter-stagnation-arc-refresh-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        original_analyze = pipeline_module.analyze_chapter
        try:
            client = StubClient([], ["第五章正文。"])
            pipeline = NovelPipeline(client, temp_dir)
            pipeline._style_bible = StyleBible(tone_targets=["克制"])
            pipeline._voice_cards = []
            pipeline._build_chapter_room = lambda *_args, **_kwargs: {}  # type: ignore[method-assign]
            pipeline._select_story_memories = lambda *_args, **_kwargs: []  # type: ignore[method-assign]
            pipeline._select_style_memories = lambda *_args, **_kwargs: []  # type: ignore[method-assign]
            pipeline._select_promise_memories = lambda *_args, **_kwargs: []  # type: ignore[method-assign]
            pipeline._select_causality_memories = lambda *_args, **_kwargs: []  # type: ignore[method-assign]
            pipeline._latest_logic_audit_for_volume = lambda *_args, **_kwargs: None  # type: ignore[method-assign]
            spec = ProjectSpec(
                title="测试小说",
                genre="都市悬疑",
                audience="中文读者",
                tone="克制",
                premise="她要追回一份旧账。",
                theme="承担",
                hook="旧账本重新浮出水面。",
                setting="旧港",
                protagonist="沈雾",
                outline_hint="完整闭环",
                world_hint="现实流程优先",
                ending_mode="standalone",
                pov="第三人称有限视角",
                target_total_chars=16000,
                target_chars_per_chapter=1800,
                chapter_count=8,
                volume_count=1,
                chapters_per_volume=8,
                style_examples=["克制"],
                must_include=["账目线"],
                avoid=["作者总结腔"],
                character_seeds=[CharacterSeed(name="沈雾", role="主角")],
            )
            bible = WorldBible(
                title="测试小说",
                logline="旧账重新浮出水面。",
                setting_summary="旧港账房",
                core_conflict="追回被改写的旧账",
                theme_statement="承担",
                narrative_voice=["克制"],
                world_rules=["规则一"],
                chapter_guardrails=["每章推进主线"],
                ending_contract=["闭环"],
                major_threads=["账目线"],
                characters=[],
            )
            book_outline = BookOutline(
                title="测试小说",
                one_line_summary="旧账浮出水面。",
                act_structure=["起", "承", "转", "合"],
                volumes=[VolumeBlueprint(1, 1, 8, "第一卷", "调查", "真账在哪", "公开局升级", "从围观到决断")],
            )
            volume_outline = VolumeOutline(
                volume_index=1,
                title="第一卷",
                goal="追回旧账",
                climax="公开局升级",
                carry_over_threads=["账目线"],
                chapter_targets=[ChapterOutlineItem(5, 1, "第五章", "拖太久", "还是同一公开局", "她需要改变弧段结构", "仍需推进", "第三人称有限视角", "chapter_hook", chapter_role="investigation")],
            )
            chapter = volume_outline.chapter_targets[0]
            plan = ChapterPlan(
                5,
                "第五章",
                "拖太久",
                ["账目线"],
                "她又站在公示栏边上。",
                "她决定把局面再推一级。",
                "chapter_hook",
                [SceneCard(1, "港口公示栏", "公开作证", "围观施压", "她决定再抬一级", "evidence_push")],
                primary_propulsion="证据推进",
            )
            continuity = ContinuityState(active_threads=["账目线"], must_remember=["旧账页"], last_chapter_index=4, last_volume_index=1)
            pipeline._review_chapter = lambda *_args, **_kwargs: ReviewFeedback(True, 92, ["通过"], [], [], "通过。")  # type: ignore[method-assign]
            pipeline._extract_continuity = lambda *_args, **_kwargs: ContinuityUpdate(5, "第五章继续推进。", [], [], ["事件5"], [], ["后续必须改出新后果"], [])  # type: ignore[method-assign]
            pipeline._extract_long_range_memory = lambda *_args, **_kwargs: LongRangeMemoryUpdate(chapter_index=5)  # type: ignore[method-assign]
            pipeline._run_stagnation_judge = lambda *_args, **_kwargs: StagnationJudgeReview(  # type: ignore[method-assign]
                chapter_index=5,
                verdict="true_stagnation",
                recommended_action="arc_repair",
                confidence=93,
                reason="最近弧段长期空转。",
                scope_start_chapter=1,
                scope_end_chapter=5,
                next_chapter_constraints=["修复后必须引出新后果。"],
                repair_goal="弧段级自动回修。",
            )
            repaired_current = ChapterResult(
                index=5,
                volume_index=1,
                title="第五章",
                outline_item=chapter,
                draft="第五章弧段修订稿。",
                plan=plan,
                review=ReviewFeedback(True, 93, ["通过"], [], [], "通过。"),
                local_quality=LocalQualityReport(True, 90, [], ["通过"], "通过。", {}),
                continuity=ContinuityUpdate(5, "第五章弧段修订。", [], [], ["事件5"], [], ["后续必须改出新后果"], []),
                attempts=2,
                long_memory=LongRangeMemoryUpdate(chapter_index=5),
            )
            pipeline._repair_chapter_cluster = lambda *_args, **_kwargs: [repaired_current]  # type: ignore[method-assign]

            pipeline_module.analyze_chapter = lambda *_args, **_kwargs: LocalQualityReport(
                True,
                87,
                ["最近长窗口存在明显空转风险。"],
                ["正文仍可读。"],
                "通过。",
                {
                    "stagnation_signal_level": "escalation",
                    "stagnation_escalation": True,
                    "stagnation_same_family_cluster": 20,
                    "stagnation_same_family_tail": 12,
                    "stagnation_same_role_tail": 5,
                    "stagnation_same_scene_tail": 5,
                    "stagnation_same_variation_tail": 4,
                    "current_propulsion": "证据推进",
                    "recent_propulsion_history": ["证据推进"] * 18 + ["程序拆解"],
                    "propulsion_hard_fail": False,
                },
            )

            pipeline._generate_chapter(
                spec,
                bible,
                chapter,
                plan,
                continuity,
                [],
                book_outline=book_outline,
                volume_outline=volume_outline,
            )

            pending = pipeline._consume_pending_chapter_repair_state()
            self.assertIsNotNone(pending)
            self.assertTrue(pending.get("refresh_controls"))
            self.assertEqual(pending.get("through_volume"), 1)
        finally:
            pipeline_module.analyze_chapter = original_analyze
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_final_fix_retries_and_rebuilds_continuity_between_chapters(self) -> None:
        class FinalFixClient(StubClient):
            def __init__(self) -> None:
                super().__init__([], [])
                self.calls: dict[str, int] = {}

            def generate_text(
                self,
                system_prompt,
                user_prompt,
                *,
                model=None,
                temperature=0.3,
                max_output_tokens=None,
                json_mode=False,
                session_id=None,
                session_max_chars=None,
                provider_tier="flagship",
                stream=False,
                stream_observer=None,
            ):
                key = session_id or "unknown"
                self.calls[key] = self.calls.get(key, 0) + 1
                if key == "writer-final-fix-c2" and self.calls[key] == 1:
                    return "第二章失败稿"
                if key == "writer-final-fix-c2":
                    return "第二章成功稿"
                if key == "writer-final-fix-c3":
                    return "第三章成功稿"
                raise AssertionError(f"Unexpected session_id: {session_id}")

        client = FinalFixClient()
        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"final-fix-retry-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        original_analyze = pipeline_module.analyze_chapter
        try:
            pipeline = NovelPipeline(client, temp_dir)
            pipeline._style_bible = StyleBible(tone_targets=["克制"])
            spec = ProjectSpec(
                title="测试小说",
                genre="都市悬疑",
                audience="中文读者",
                tone="克制",
                premise="旧档案牵出旧案。",
                theme="承担代价",
                hook="名单被人改写。",
                setting="海边旧城",
                protagonist="沈雾",
                outline_hint="完整闭环",
                world_hint="设定服务剧情",
                ending_mode="standalone",
                pov="第三人称有限视角",
                target_total_chars=6000,
                target_chars_per_chapter=2000,
                chapter_count=3,
                volume_count=1,
                chapters_per_volume=3,
                style_examples=["克制"],
                must_include=["证据链"],
                avoid=["作者总结腔"],
                character_seeds=[CharacterSeed(name="沈雾", role="主角")],
            )
            bible = WorldBible(
                title="测试小说",
                logline="一句话卖点",
                setting_summary="设定摘要",
                core_conflict="核心冲突",
                theme_statement="主题表达",
                narrative_voice=["克制"],
                world_rules=["规则一"],
                chapter_guardrails=["每章推进主线"],
                ending_contract=["闭环"],
                major_threads=["名单线"],
                characters=[],
            )
            chapter2 = ChapterOutlineItem(2, 1, "第二章", "推进名单线", "证据将被封口", "保住名单", "名单还在", "第三人称有限视角", "chapter_hook", ["名单线"])
            chapter3 = ChapterOutlineItem(3, 1, "第三章", "卷末收束", "证据要转移", "带证人离开", "下一阶段开始", "第三人称有限视角", "volume_hook", ["名单线"])
            plan2 = ChapterPlan(2, "第二章", "推进名单线", ["名单线"], "她压住名单。", "她带着名单冲出去。", "chapter_hook", [])
            plan3 = ChapterPlan(3, "第三章", "卷末收束", ["名单线"], "她在夜里回头。", "她决定北上。", "volume_hook", [])
            chapters = [
                ChapterResult(
                    index=1,
                    volume_index=1,
                    title="第一章",
                    outline_item=ChapterOutlineItem(1, 1, "第一章", "开局", "旧案浮出", "查旧案", "她决定追下去", "第三人称有限视角", "chapter_hook", ["旧案"]),
                    draft="第一章正文",
                    plan=ChapterPlan(1, "第一章", "开局", ["旧案"], "开场", "收束", "chapter_hook", []),
                    review=ReviewFeedback(True, 92, [], [], [], "通过。"),
                    local_quality=LocalQualityReport(True, 92, [], [], "通过。", {}),
                    continuity=ContinuityUpdate(1, "第一章摘要", ["名单线"], [], ["事件1"], [], ["目标1"], ["第一章记忆"]),
                    attempts=1,
                    long_memory=LongRangeMemoryUpdate(chapter_index=1),
                ),
                ChapterResult(
                    index=2,
                    volume_index=1,
                    title="第二章",
                    outline_item=chapter2,
                    draft="第二章原稿",
                    plan=plan2,
                    review=ReviewFeedback(True, 93, [], [], [], "通过。"),
                    local_quality=LocalQualityReport(True, 93, [], [], "通过。", {}),
                    continuity=ContinuityUpdate(2, "第二章旧摘要", ["名单线"], [], ["事件2"], [], ["目标2"], ["第二章旧记忆"]),
                    attempts=1,
                    long_memory=LongRangeMemoryUpdate(chapter_index=2),
                ),
                ChapterResult(
                    index=3,
                    volume_index=1,
                    title="第三章",
                    outline_item=chapter3,
                    draft="第三章原稿",
                    plan=plan3,
                    review=ReviewFeedback(True, 93, [], [], [], "通过。"),
                    local_quality=LocalQualityReport(True, 93, [], [], "通过。", {}),
                    continuity=ContinuityUpdate(3, "第三章旧摘要", [], ["名单线"], ["事件3"], [], ["目标3"], ["第三章旧记忆"]),
                    attempts=1,
                    long_memory=LongRangeMemoryUpdate(chapter_index=3),
                ),
            ]
            book_outline = BookOutline(
                title="测试小说",
                one_line_summary="一句话简介",
                act_structure=["开端", "推进", "收束"],
                volumes=[VolumeBlueprint(1, 1, 3, "第一卷", "推进", "名单去哪了", "责任落地", "她决定承担", ["名单线"])],
            )

            review_calls: dict[int, int] = {}
            continuity_seen: list[tuple[int, list[str]]] = []

            def fake_review(_spec, _bible, chapter, _plan, draft, local_quality, continuity, *_args):
                review_calls[chapter.index] = review_calls.get(chapter.index, 0) + 1
                continuity_seen.append((chapter.index, list(continuity.must_remember)))
                if chapter.index == 2 and review_calls[chapter.index] == 1:
                    return ReviewFeedback(False, 80, [], ["收束发飘"], ["补实结尾"], "未通过。")
                return ReviewFeedback(True, 95, [], [], [], "通过。")

            def fake_extract(_spec, _bible, chapter, _draft, _previous_state):
                if chapter.index == 2:
                    return ContinuityUpdate(2, "第二章新摘要", ["名单线"], [], ["事件2-新"], [], ["目标2-新"], ["第二章新记忆"])
                return ContinuityUpdate(3, "第三章新摘要", [], ["名单线"], ["事件3-新"], [], ["目标3-新"], ["第二章新记忆", "第三章新记忆"])

            pipeline_module.analyze_chapter = lambda *_args, **_kwargs: LocalQualityReport(True, 94, [], [], "通过。", {})
            pipeline._review_chapter = fake_review  # type: ignore[method-assign]
            pipeline._extract_continuity = fake_extract  # type: ignore[method-assign]
            pipeline._extract_long_range_memory = lambda *_args, **_kwargs: LongRangeMemoryUpdate(chapter_index=0)  # type: ignore[method-assign]
            pipeline._select_story_memories = lambda *_args, **_kwargs: []  # type: ignore[method-assign]
            pipeline._select_style_memories = lambda *_args, **_kwargs: []  # type: ignore[method-assign]
            pipeline._select_promise_memories = lambda *_args, **_kwargs: []  # type: ignore[method-assign]
            pipeline._select_causality_memories = lambda *_args, **_kwargs: []  # type: ignore[method-assign]
            pipeline._latest_logic_audit_for_volume = lambda *_args, **_kwargs: None  # type: ignore[method-assign]
            pipeline._build_chapter_room = lambda *_args, **_kwargs: {}  # type: ignore[method-assign]
            pipeline._emit_progress = lambda *_args, **_kwargs: None  # type: ignore[method-assign]
            pipeline._reset_client_session = lambda *_args, **_kwargs: None  # type: ignore[method-assign]

            updated = pipeline._apply_final_fixes(
                spec,
                bible,
                book_outline,
                chapters,
                [
                    {"chapter_index": 2, "instruction": "补实结尾并删掉作者总结腔。"},
                    {"chapter_index": 3, "instruction": "补强卷末收束。"},
                ],
            )

            self.assertEqual(client.calls["writer-final-fix-c2"], 2)
            self.assertEqual(client.calls["writer-final-fix-c3"], 1)
            self.assertEqual(updated[1].draft, "第二章成功稿")
            self.assertEqual(updated[2].draft, "第三章成功稿")
            self.assertTrue(any(index == 3 and "第二章新记忆" in memories for index, memories in continuity_seen))
        finally:
            pipeline_module.analyze_chapter = original_analyze
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_final_fix_records_stagnation_warning(self) -> None:
        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"final-fix-reroute-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        original_analyze = pipeline_module.analyze_chapter
        try:
            client = StubClient([], ["第二章终修稿。"])
            pipeline = NovelPipeline(client, temp_dir)
            pipeline._style_bible = StyleBible(tone_targets=["克制"])
            pipeline._voice_cards = []
            pipeline._build_chapter_room = lambda *_args, **_kwargs: {}  # type: ignore[method-assign]
            pipeline._select_story_memories = lambda *_args, **_kwargs: []  # type: ignore[method-assign]
            pipeline._select_style_memories = lambda *_args, **_kwargs: []  # type: ignore[method-assign]
            pipeline._select_promise_memories = lambda *_args, **_kwargs: []  # type: ignore[method-assign]
            pipeline._select_causality_memories = lambda *_args, **_kwargs: []  # type: ignore[method-assign]
            pipeline._latest_logic_audit_for_volume = lambda *_args, **_kwargs: None  # type: ignore[method-assign]
            spec = ProjectSpec(
                title="测试小说",
                genre="都市悬疑",
                audience="中文读者",
                tone="克制",
                premise="名单牵出旧码头旧账。",
                theme="承担代价",
                hook="名单被人改写。",
                setting="海边旧城",
                protagonist="沈雾",
                outline_hint="完整闭环",
                world_hint="设定服务剧情",
                ending_mode="standalone",
                pov="第三人称有限视角",
                target_total_chars=6000,
                target_chars_per_chapter=2000,
                chapter_count=3,
                volume_count=1,
                chapters_per_volume=3,
                style_examples=["克制"],
                must_include=["名单线"],
                avoid=["作者总结腔"],
                character_seeds=[CharacterSeed(name="沈雾", role="主角")],
            )
            bible = WorldBible(
                title="测试小说",
                logline="一句话卖点",
                setting_summary="设定摘要",
                core_conflict="核心冲突",
                theme_statement="主题表达",
                narrative_voice=["克制"],
                world_rules=["规则一"],
                chapter_guardrails=["每章推进主线"],
                ending_contract=["闭环"],
                major_threads=["名单线"],
                characters=[],
            )
            chapter = ChapterOutlineItem(2, 1, "第二章", "推进名单线", "证据将被封口", "保住名单", "名单还在", "第三人称有限视角", "chapter_hook", ["名单线"])
            plan = ChapterPlan(
                2,
                "第二章",
                "推进名单线",
                ["名单线"],
                "她握紧名单。",
                "她决定再公开压一轮。",
                "chapter_hook",
                [SceneCard(1, "码头公示栏", "公开对证", "围观施压", "她准备再抬程序口径", "evidence_push")],
                primary_propulsion="证据推进",
            )
            chapter_result = ChapterResult(
                index=2,
                volume_index=1,
                title="第二章",
                outline_item=chapter,
                draft="第二章原稿",
                plan=plan,
                review=ReviewFeedback(True, 93, [], [], [], "通过。"),
                local_quality=LocalQualityReport(True, 93, [], [], "通过。", {}),
                continuity=ContinuityUpdate(2, "第二章旧摘要", ["名单线"], [], ["事件2"], [], ["目标2"], ["第二章旧记忆"]),
                attempts=1,
                long_memory=LongRangeMemoryUpdate(chapter_index=2),
            )
            prior_chapters = [
                ChapterResult(
                    index=1,
                    volume_index=1,
                    title="第一章",
                    outline_item=ChapterOutlineItem(1, 1, "第一章", "开局", "旧案浮出", "查旧案", "她决定追下去", "第三人称有限视角", "chapter_hook", ["旧案"]),
                    draft="第一章正文",
                    plan=ChapterPlan(1, "第一章", "开局", ["旧案"], "开场", "收束", "chapter_hook", []),
                    review=ReviewFeedback(True, 92, [], [], [], "通过。"),
                    local_quality=LocalQualityReport(True, 92, [], [], "通过。", {}),
                    continuity=ContinuityUpdate(1, "第一章摘要", ["名单线"], [], ["事件1"], [], ["目标1"], ["第一章记忆"]),
                    attempts=1,
                    long_memory=LongRangeMemoryUpdate(chapter_index=1),
                )
            ]
            pre_state = ContinuityState(active_threads=["名单线"], must_remember=["第一章记忆"], last_chapter_index=1)
            book_outline = BookOutline(
                title="测试小说",
                one_line_summary="一句话简介",
                act_structure=["开端", "推进", "收束"],
                volumes=[VolumeBlueprint(1, 1, 3, "第一卷", "推进", "名单去哪了", "责任落地", "她决定承担", ["名单线"])],
            )
            volume_outline = VolumeOutline(
                volume_index=1,
                title="第一卷",
                goal="推进名单线",
                climax="名单迟早会反咬",
                carry_over_threads=["名单线"],
                chapter_targets=[chapter],
            )
            pipeline._volume_outlines[1] = volume_outline

            pipeline._review_chapter = lambda *_args, **_kwargs: ReviewFeedback(True, 95, [], [], [], "通过。")  # type: ignore[method-assign]
            pipeline._extract_continuity = lambda *_args, **_kwargs: ContinuityUpdate(2, "第二章新摘要", ["名单线"], [], ["事件2-新"], [], ["目标2-新"], ["第二章新记忆"])  # type: ignore[method-assign]
            pipeline._extract_long_range_memory = lambda *_args, **_kwargs: LongRangeMemoryUpdate(chapter_index=2)  # type: ignore[method-assign]
            pipeline_module.analyze_chapter = lambda *_args, **_kwargs: LocalQualityReport(
                True,
                94,
                ["最近几章仍在同一推进簇，存在轻度空转风险。"],
                ["通过。"],
                "通过。",
                {
                    "stagnation_signal_level": "warning",
                    "stagnation_warning": True,
                    "stagnation_same_family_cluster": 4,
                    "stagnation_same_family_tail": 3,
                    "current_propulsion": "证据推进",
                    "recent_propulsion_history": ["证据推进", "证据推进", "关系推进"],
                    "propulsion_hard_fail": False,
                },
            )

            updated = pipeline._rewrite_final_fix_chapter(
                spec,
                bible,
                book_outline,
                chapter_result,
                pre_state,
                prior_chapters,
                "删掉重复的公开对证。",
                progress_message="终审修订第 2 章。",
                progress_step="final_fix",
                session_prefix="writer-final-fix",
                stage_label="final_fix",
            )

            self.assertTrue(updated.local_quality.passed)
            self.assertTrue(any("长窗口告警" in note for note in updated.continuity.must_remember))
            self.assertFalse((temp_dir / "data" / "latest-stagnation-report.json").exists())
            self.assertEqual(client.text_calls, 1)
        finally:
            pipeline_module.analyze_chapter = original_analyze
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_final_fix_stabilizes_neighbor_window(self) -> None:
        class NeighborFixClient(StubClient):
            def __init__(self) -> None:
                super().__init__([], [])
                self.calls: dict[str, int] = {}

            def generate_text(
                self,
                system_prompt,
                user_prompt,
                *,
                model=None,
                temperature=0.3,
                max_output_tokens=None,
                json_mode=False,
                session_id=None,
                session_max_chars=None,
                provider_tier="flagship",
                stream=False,
                stream_observer=None,
            ):
                key = session_id or "unknown"
                self.calls[key] = self.calls.get(key, 0) + 1
                if key == "writer-final-fix-c2":
                    return "第二章终审修订稿"
                if key == "writer-neighbor-fix-c3":
                    return "第三章邻章修订稿"
                raise AssertionError(f"Unexpected session_id: {session_id}")

        client = NeighborFixClient()
        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"neighbor-fix-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        original_analyze = pipeline_module.analyze_chapter
        try:
            pipeline = NovelPipeline(client, temp_dir)
            pipeline._style_bible = StyleBible(tone_targets=["克制"])
            spec = ProjectSpec(
                title="测试小说",
                genre="都市悬疑",
                audience="中文读者",
                tone="克制",
                premise="旧档案牵出旧案。",
                theme="承担代价",
                hook="名单被人改写。",
                setting="海边旧城",
                protagonist="沈雾",
                outline_hint="完整闭环",
                world_hint="设定服务剧情",
                ending_mode="standalone",
                pov="第三人称有限视角",
                target_total_chars=6000,
                target_chars_per_chapter=2000,
                chapter_count=3,
                volume_count=1,
                chapters_per_volume=3,
                style_examples=["克制"],
                must_include=["证据链"],
                avoid=["作者总结腔"],
                character_seeds=[CharacterSeed(name="沈雾", role="主角")],
            )
            bible = WorldBible(
                title="测试小说",
                logline="一句话卖点",
                setting_summary="设定摘要",
                core_conflict="核心冲突",
                theme_statement="主题表达",
                narrative_voice=["克制"],
                world_rules=["规则一"],
                chapter_guardrails=["每章推进主线"],
                ending_contract=["闭环"],
                major_threads=["名单线"],
                characters=[],
            )
            chapter1 = ChapterOutlineItem(1, 1, "第一章", "开局", "旧案浮出", "查旧案", "她决定追下去", "第三人称有限视角", "chapter_hook", ["旧案"])
            chapter2 = ChapterOutlineItem(2, 1, "第二章", "推进名单线", "证据将被封口", "保住名单", "名单还在", "第三人称有限视角", "chapter_hook", ["名单线"])
            chapter3 = ChapterOutlineItem(3, 1, "第三章", "卷末收束", "证据要转移", "带证人离开", "下一阶段开始", "第三人称有限视角", "volume_hook", ["名单线"])
            plan1 = ChapterPlan(1, "第一章", "开局", ["旧案"], "开场", "收束", "chapter_hook", [])
            plan2 = ChapterPlan(2, "第二章", "推进名单线", ["名单线"], "她压住名单。", "她带着名单冲出去。", "chapter_hook", [])
            plan3 = ChapterPlan(3, "第三章", "卷末收束", ["名单线"], "她在夜里回头。", "她决定北上。", "volume_hook", [])
            chapters = [
                ChapterResult(
                    index=1,
                    volume_index=1,
                    title="第一章",
                    outline_item=chapter1,
                    draft="第一章正文",
                    plan=plan1,
                    review=ReviewFeedback(True, 92, [], [], [], "通过。"),
                    local_quality=LocalQualityReport(True, 92, [], [], "通过。", {}),
                    continuity=ContinuityUpdate(1, "第一章摘要", ["名单线"], [], ["事件1"], [], ["目标1"], ["第一章记忆"]),
                    attempts=1,
                    long_memory=LongRangeMemoryUpdate(chapter_index=1),
                ),
                ChapterResult(
                    index=2,
                    volume_index=1,
                    title="第二章",
                    outline_item=chapter2,
                    draft="第二章原稿",
                    plan=plan2,
                    review=ReviewFeedback(True, 93, [], [], [], "通过。"),
                    local_quality=LocalQualityReport(True, 93, [], [], "通过。", {}),
                    continuity=ContinuityUpdate(2, "第二章旧摘要", ["名单线"], [], ["事件2"], [], ["目标2"], ["第二章旧记忆"]),
                    attempts=1,
                    long_memory=LongRangeMemoryUpdate(chapter_index=2),
                ),
                ChapterResult(
                    index=3,
                    volume_index=1,
                    title="第三章",
                    outline_item=chapter3,
                    draft="第三章原稿",
                    plan=plan3,
                    review=ReviewFeedback(True, 93, [], [], [], "通过。"),
                    local_quality=LocalQualityReport(True, 93, [], [], "通过。", {}),
                    continuity=ContinuityUpdate(3, "第三章旧摘要", [], ["名单线"], ["事件3"], [], ["目标3"], ["第三章旧记忆"]),
                    attempts=1,
                    long_memory=LongRangeMemoryUpdate(chapter_index=3),
                ),
            ]
            book_outline = BookOutline(
                title="测试小说",
                one_line_summary="一句话简介",
                act_structure=["开端", "推进", "收束"],
                volumes=[VolumeBlueprint(1, 1, 3, "第一卷", "推进", "名单去哪了", "责任落地", "她决定承担", ["名单线"])],
            )

            review_calls: list[tuple[int, str, list[str]]] = []

            def fake_review(_spec, _bible, chapter, _plan, draft, _local_quality, continuity, *_args):
                review_calls.append((chapter.index, draft, list(continuity.must_remember)))
                if chapter.index == 3 and draft == "第三章原稿" and "第二章新记忆" in continuity.must_remember:
                    return ReviewFeedback(False, 81, [], ["和上一章衔接不顺"], ["补齐承接动作"], "未通过。")
                return ReviewFeedback(True, 95, [], [], [], "通过。")

            def fake_extract(_spec, _bible, chapter, draft, _previous_state):
                if chapter.index == 2:
                    return ContinuityUpdate(2, "第二章新摘要", ["名单线"], [], ["事件2-新"], [], ["目标2-新"], ["第二章新记忆"])
                if chapter.index == 3 and draft == "第三章邻章修订稿":
                    return ContinuityUpdate(3, "第三章新摘要", [], ["名单线"], ["事件3-新"], [], ["目标3-新"], ["第二章新记忆", "第三章新记忆"])
                return ContinuityUpdate(3, "第三章旧摘要", [], ["名单线"], ["事件3"], [], ["目标3"], ["第三章旧记忆"])

            pipeline_module.analyze_chapter = lambda *_args, **_kwargs: LocalQualityReport(True, 94, [], [], "通过。", {})
            pipeline._review_chapter = fake_review  # type: ignore[method-assign]
            pipeline._extract_continuity = fake_extract  # type: ignore[method-assign]
            pipeline._extract_long_range_memory = lambda *_args, **_kwargs: LongRangeMemoryUpdate(chapter_index=0)  # type: ignore[method-assign]
            pipeline._select_story_memories = lambda *_args, **_kwargs: []  # type: ignore[method-assign]
            pipeline._select_style_memories = lambda *_args, **_kwargs: []  # type: ignore[method-assign]
            pipeline._select_promise_memories = lambda *_args, **_kwargs: []  # type: ignore[method-assign]
            pipeline._select_causality_memories = lambda *_args, **_kwargs: []  # type: ignore[method-assign]
            pipeline._latest_logic_audit_for_volume = lambda *_args, **_kwargs: None  # type: ignore[method-assign]
            pipeline._build_chapter_room = lambda *_args, **_kwargs: {}  # type: ignore[method-assign]
            pipeline._emit_progress = lambda *_args, **_kwargs: None  # type: ignore[method-assign]
            pipeline._reset_client_session = lambda *_args, **_kwargs: None  # type: ignore[method-assign]

            updated = pipeline._apply_final_fixes(
                spec,
                bible,
                book_outline,
                chapters,
                [{"chapter_index": 2, "instruction": "补实第二章结尾并删掉作者总结腔。"}],
            )

            self.assertEqual(client.calls["writer-final-fix-c2"], 1)
            self.assertEqual(client.calls["writer-neighbor-fix-c3"], 1)
            self.assertEqual(updated[1].draft, "第二章终审修订稿")
            self.assertEqual(updated[2].draft, "第三章邻章修订稿")
            self.assertTrue(any(index == 3 and "第二章新记忆" in memories for index, _draft, memories in review_calls))
        finally:
            pipeline_module.analyze_chapter = original_analyze
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_final_fix_falls_back_to_original_when_polish_cannot_improve(self) -> None:
        client = StubClient([], [])
        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"final-fix-fallback-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            pipeline = NovelPipeline(client, temp_dir)
            pipeline._emit_progress = lambda *_args, **_kwargs: None  # type: ignore[method-assign]
            spec = ProjectSpec(
                title="测试小说",
                genre="都市悬疑",
                audience="中文读者",
                tone="克制",
                premise="旧档案牵出旧案。",
                theme="承担代价",
                hook="名单被人改写。",
                setting="海边旧城",
                protagonist="沈雾",
                outline_hint="完整闭环",
                world_hint="设定服务剧情",
                ending_mode="standalone",
                pov="第三人称有限视角",
                target_total_chars=4000,
                target_chars_per_chapter=2000,
                chapter_count=2,
                volume_count=1,
                chapters_per_volume=2,
                style_examples=["克制"],
                must_include=["证据链"],
                avoid=["作者总结腔"],
                character_seeds=[CharacterSeed(name="沈雾", role="主角")],
            )
            bible = WorldBible(
                title="测试小说",
                logline="一句话卖点",
                setting_summary="设定摘要",
                core_conflict="核心冲突",
                theme_statement="主题表达",
                narrative_voice=["克制"],
                world_rules=["规则一"],
                chapter_guardrails=["每章推进主线"],
                ending_contract=["闭环"],
                major_threads=["名单线"],
                characters=[],
            )
            chapter1 = ChapterOutlineItem(1, 1, "第一章", "开局", "旧案浮出", "查旧案", "她决定追下去", "第三人称有限视角", "chapter_hook", ["旧案"])
            chapter2 = ChapterOutlineItem(2, 1, "第二章", "推进名单线", "证据将被封口", "保住名单", "名单还在", "第三人称有限视角", "chapter_hook", ["名单线"])
            plan = ChapterPlan(2, "第二章", "推进名单线", ["名单线"], "开场", "收束", "chapter_hook", [])
            chapters = [
                ChapterResult(
                    index=1,
                    volume_index=1,
                    title="第一章",
                    outline_item=chapter1,
                    draft="第一章正文",
                    plan=ChapterPlan(1, "第一章", "开局", ["旧案"], "开场", "收束", "chapter_hook", []),
                    review=ReviewFeedback(True, 92, [], [], [], "通过。"),
                    local_quality=LocalQualityReport(True, 92, [], [], "通过。", {}),
                    continuity=ContinuityUpdate(1, "第一章摘要", ["名单线"], [], ["事件1"], [], ["目标1"], ["第一章记忆"]),
                    attempts=1,
                    long_memory=LongRangeMemoryUpdate(chapter_index=1),
                ),
                ChapterResult(
                    index=2,
                    volume_index=1,
                    title="第二章",
                    outline_item=chapter2,
                    draft="第二章原稿",
                    plan=plan,
                    review=ReviewFeedback(True, 95, [], [], [], "通过。"),
                    local_quality=LocalQualityReport(True, 95, [], [], "通过。", {}),
                    continuity=ContinuityUpdate(2, "第二章摘要", [], ["名单线"], ["事件2"], [], ["目标2"], ["第二章记忆"]),
                    attempts=1,
                    long_memory=LongRangeMemoryUpdate(chapter_index=2),
                ),
            ]
            book_outline = BookOutline(
                title="测试小说",
                one_line_summary="一句话简介",
                act_structure=["开端", "推进", "收束"],
                volumes=[VolumeBlueprint(1, 1, 2, "第一卷", "推进", "名单去哪了", "责任落地", "她决定承担", ["名单线"])],
            )
            pipeline._rewrite_final_fix_chapter = lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom"))  # type: ignore[method-assign]

            updated = pipeline._apply_final_fixes(
                spec,
                bible,
                book_outline,
                chapters,
                [{"chapter_index": 2, "instruction": "删掉作者总结腔。"}],
            )

            self.assertEqual(updated[1].draft, "第二章原稿")
            self.assertEqual(updated[1].review.score, 95)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_volume_gate_repairs_before_next_volume(self) -> None:
        client = StubClient([], [])
        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"volume-gate-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            pipeline = NovelPipeline(client, temp_dir)
            spec = ProjectSpec(
                title="测试小说",
                genre="都市悬疑",
                audience="中文读者",
                tone="克制",
                premise="名单会牵出旧账。",
                theme="面对代价",
                hook="名单少了一页。",
                setting="海边旧城",
                protagonist="沈雾",
                outline_hint="卷末要过硬闸门",
                world_hint="设定服务剧情",
                ending_mode="standalone",
                pov="第三人称有限视角",
                target_total_chars=12000,
                target_chars_per_chapter=2000,
                chapter_count=6,
                volume_count=2,
                chapters_per_volume=3,
                style_examples=["克制"],
                must_include=["证据链"],
                avoid=["纯悬念不兑现"],
                character_seeds=[CharacterSeed(name="沈雾", role="主角")],
            )
            bible = WorldBible(
                title="测试小说",
                logline="一句话卖点",
                setting_summary="设定摘要",
                core_conflict="核心冲突",
                theme_statement="主题表达",
                narrative_voice=["克制"],
                world_rules=["规则一"],
                chapter_guardrails=["每章推进主线"],
                ending_contract=["闭环"],
                major_threads=["名单线"],
                characters=[],
            )
            volume_outline = VolumeOutline(
                volume_index=1,
                title="第一卷",
                goal="先保住名单线",
                climax="确认名单残页",
                carry_over_threads=["名单线"],
                chapter_targets=[
                    ChapterOutlineItem(1, 1, "第一章", "推进名单线", "有人抢先动手", "保住名单", "看见残页", "第三人称有限视角", "chapter_hook", ["名单线"]),
                    ChapterOutlineItem(2, 1, "第二章", "确认残页去向", "证据可能被毁", "追回残页", "她决定继续追", "第三人称有限视角", "chapter_hook", ["残页"]),
                    ChapterOutlineItem(3, 1, "第三章", "卷末收束", "名单会反咬回来", "保住卷末结果", "下一卷可开", "第三人称有限视角", "chapter_hook", ["名单线"]),
                ],
            )
            book_outline = BookOutline(
                title="测试小说",
                one_line_summary="一句话简介",
                act_structure=["开端", "推进", "收束"],
                volumes=[
                    VolumeBlueprint(1, 1, 3, "第一卷", "推进", "名单去哪了", "名单反咬", "从回避到行动", ["名单线"]),
                    VolumeBlueprint(2, 4, 6, "第二卷", "收束", "谁在改账", "责任落地", "从行动到承担", ["责任"]),
                ],
            )
            chapters = [
                ChapterResult(
                    index=1,
                    volume_index=1,
                    title="第一章",
                    outline_item=volume_outline.chapter_targets[0],
                    draft="第一章正文。",
                    plan=ChapterPlan(1, "第一章", "推进名单线", ["名单线"], "开场", "结尾", "chapter_hook", []),
                    review=ReviewFeedback(True, 90, [], [], [], "通过。"),
                    local_quality=LocalQualityReport(True, 91, [], [], "通过。", {}),
                    continuity=ContinuityUpdate(1, "第一章摘要", ["名单线"], [], ["事件1"], [], ["目标1"], ["记住1"]),
                    attempts=1,
                    long_memory=LongRangeMemoryUpdate(chapter_index=1),
                ),
                ChapterResult(
                    index=2,
                    volume_index=1,
                    title="第二章",
                    outline_item=volume_outline.chapter_targets[1],
                    draft="第二章正文。",
                    plan=ChapterPlan(2, "第二章", "确认残页去向", ["残页"], "开场", "结尾", "chapter_hook", []),
                    review=ReviewFeedback(True, 90, [], [], [], "通过。"),
                    local_quality=LocalQualityReport(True, 91, [], [], "通过。", {}),
                    continuity=ContinuityUpdate(2, "第二章摘要", ["残页"], [], ["事件2"], [], ["目标2"], ["记住2"]),
                    attempts=1,
                    long_memory=LongRangeMemoryUpdate(chapter_index=2),
                ),
                ChapterResult(
                    index=3,
                    volume_index=1,
                    title="第三章",
                    outline_item=volume_outline.chapter_targets[2],
                    draft="第三章正文。",
                    plan=ChapterPlan(3, "第三章", "卷末收束", ["名单线"], "开场", "结尾", "chapter_hook", []),
                    review=ReviewFeedback(True, 90, [], [], [], "通过。"),
                    local_quality=LocalQualityReport(True, 91, [], [], "通过。", {}),
                    continuity=ContinuityUpdate(3, "第三章摘要", [], ["残页"], ["事件3"], [], ["目标3"], ["记住3"]),
                    attempts=1,
                    long_memory=LongRangeMemoryUpdate(chapter_index=3),
                ),
            ]
            continuity = ContinuityState(last_volume_index=1, last_chapter_index=3, must_remember=["名单线还要闭环"])
            audits = [
                LogicAuditReport(
                    passed=False,
                    gate_passed=False,
                    gate_level="repair_cluster",
                    summary="卷末还没补齐因果。",
                    issues=["第二章的残页去向交代不够。"],
                    watch_items=[],
                    required_followups=["回修第二章并重收卷末。"],
                    flagged_chapters=[{"chapter_index": 2}],
                    repair_plan=[{"start_chapter": 2, "end_chapter": 3, "instruction": "补齐残页去向和卷末回收。"}],
                ),
                LogicAuditReport(
                    passed=True,
                    gate_passed=True,
                    summary="卷级闸门通过。",
                    issues=[],
                    watch_items=["下一卷继续追账本。"],
                    required_followups=[],
                    flagged_chapters=[],
                    repair_plan=[],
                ),
            ]
            audit_calls: list[int] = []
            repair_calls: list[tuple[int, int]] = []

            def fake_audit(*args, **kwargs):
                audit_calls.append(1)
                return audits.pop(0)

            def fake_repair(_spec, _bible, _book_outline, _volume_outline, all_chapters, _audit):
                repair_calls.append((_volume_outline.volume_index, len(all_chapters)))
                repaired = list(all_chapters)
                repaired[1] = ChapterResult(
                    index=2,
                    volume_index=1,
                    title="第二章",
                    outline_item=volume_outline.chapter_targets[1],
                    draft="第二章已回修，残页去向补实了。",
                    plan=chapters[1].plan,
                    review=chapters[1].review,
                    local_quality=chapters[1].local_quality,
                    continuity=chapters[1].continuity,
                    attempts=2,
                    long_memory=LongRangeMemoryUpdate(chapter_index=2),
                )
                return repaired

            pipeline._audit_volume_logic = fake_audit  # type: ignore[method-assign]
            pipeline._repair_chapter_cluster = fake_repair  # type: ignore[method-assign]

            updated_chapters, updated_continuity = pipeline._enforce_volume_gate(
                spec,
                bible,
                book_outline,
                volume_outline,
                chapters,
                chapters,
                continuity,
            )

            self.assertEqual(len(audit_calls), 2)
            self.assertEqual(repair_calls, [(1, 3)])
            self.assertEqual(updated_chapters[1].draft, "第二章已回修，残页去向补实了。")
            self.assertEqual(chapters[1].attempts, 2)
            self.assertEqual(updated_continuity.last_chapter_index, 3)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_volume_gate_escalates_to_large_window_repair_when_first_window_fails(self) -> None:
        client = StubClient([], [])
        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"volume-gate-escalate-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            pipeline = NovelPipeline(client, temp_dir)
            spec = ProjectSpec(
                title="测试小说",
                genre="都市悬疑",
                audience="中文读者",
                tone="克制",
                premise="名单会牵出旧账。",
                theme="面对代价",
                hook="名单少了一页。",
                setting="海边旧城",
                protagonist="沈雾",
                outline_hint="卷末要过硬闸门",
                world_hint="设定服务剧情",
                ending_mode="standalone",
                pov="第三人称有限视角",
                target_total_chars=24000,
                target_chars_per_chapter=2000,
                chapter_count=6,
                volume_count=1,
                chapters_per_volume=6,
                style_examples=["克制"],
                must_include=["证据链"],
                avoid=["纯悬念不兑现"],
                character_seeds=[CharacterSeed(name="沈雾", role="主角")],
            )
            bible = WorldBible(
                title="测试小说",
                logline="一句话卖点",
                setting_summary="设定摘要",
                core_conflict="核心冲突",
                theme_statement="主题表达",
                narrative_voice=["克制"],
                world_rules=["规则一"],
                chapter_guardrails=["每章推进主线"],
                ending_contract=["闭环"],
                major_threads=["名单线"],
                characters=[],
            )
            chapter_targets = [
                ChapterOutlineItem(index, 1, f"第{index}章", "推进名单线", "有人抢先动手", "保住名单", "看见残页", "第三人称有限视角", "chapter_hook", ["名单线"])
                for index in range(1, 7)
            ]
            volume_outline = VolumeOutline(
                volume_index=1,
                title="第一卷",
                goal="先保住名单线",
                climax="确认名单残页",
                carry_over_threads=["名单线"],
                chapter_targets=chapter_targets,
            )
            book_outline = BookOutline(
                title="测试小说",
                one_line_summary="一句话简介",
                act_structure=["开端", "推进", "收束"],
                volumes=[VolumeBlueprint(1, 1, 6, "第一卷", "推进", "名单去哪了", "名单反咬", "从回避到行动", ["名单线"])],
            )
            chapters = [
                ChapterResult(
                    index=index,
                    volume_index=1,
                    title=f"第{index}章",
                    outline_item=chapter_targets[index - 1],
                    draft=f"第{index}章正文。",
                    plan=ChapterPlan(index, f"第{index}章", "推进名单线", ["名单线"], "开场", "结尾", "chapter_hook", []),
                    review=ReviewFeedback(True, 90, [], [], [], "通过。"),
                    local_quality=LocalQualityReport(True, 91, [], [], "通过。", {}),
                    continuity=ContinuityUpdate(index, f"第{index}章摘要", ["名单线"], [], [f"事件{index}"], [], [f"目标{index}"], [f"记住{index}"]),
                    attempts=1,
                    long_memory=LongRangeMemoryUpdate(chapter_index=index),
                )
                for index in range(1, 7)
            ]
            continuity = ContinuityState(last_volume_index=1, last_chapter_index=6, must_remember=["名单线还要闭环"])
            audits = [
                LogicAuditReport(
                    passed=False,
                    gate_passed=False,
                    gate_level="repair_cluster",
                    summary="卷末还没补齐因果。",
                    issues=["第五章到第六章的卷末回收不够。"],
                    watch_items=[],
                    required_followups=["先回修第五到第六章。"],
                    flagged_chapters=[{"chapter_index": 5}, {"chapter_index": 6}],
                    repair_plan=[{"start_chapter": 5, "end_chapter": 6, "instruction": "补齐卷末回收。"}],
                ),
                LogicAuditReport(
                    passed=False,
                    gate_passed=False,
                    gate_level="repair_cluster",
                    summary="问题没有完全收住。",
                    issues=["最近整段推进仍然同构。"],
                    watch_items=[],
                    required_followups=["扩大到最近章节窗口。"],
                    flagged_chapters=[{"chapter_index": 6}],
                    repair_plan=[{"start_chapter": 6, "end_chapter": 6, "instruction": "继续补齐卷末回收。"}],
                ),
                LogicAuditReport(
                    passed=True,
                    gate_passed=True,
                    gate_level="pass",
                    summary="卷级闸门通过。",
                    issues=[],
                    watch_items=["下一卷继续追账本。"],
                    required_followups=[],
                    flagged_chapters=[],
                    repair_plan=[],
                ),
            ]
            audit_calls: list[int] = []
            repair_calls: list[tuple[int, int, str]] = []

            def fake_audit(*args, **kwargs):
                audit_calls.append(1)
                return audits.pop(0)

            def fake_repair(_spec, _bible, _book_outline, _volume_outline, all_chapters, _audit):
                plan = _audit.repair_plan[0]
                repair_calls.append((plan["start_chapter"], plan["end_chapter"], plan["instruction"]))
                return list(all_chapters)

            pipeline._audit_volume_logic = fake_audit  # type: ignore[method-assign]
            pipeline._repair_chapter_cluster = fake_repair  # type: ignore[method-assign]

            updated_chapters, updated_continuity = pipeline._enforce_volume_gate(
                spec,
                bible,
                book_outline,
                volume_outline,
                chapters,
                chapters,
                continuity,
            )

            self.assertEqual(len(audit_calls), 3)
            self.assertEqual(repair_calls[0][:2], (5, 6))
            self.assertEqual(repair_calls[1][:2], (1, 6))
            self.assertIn("大窗口回修", repair_calls[1][2])
            self.assertEqual([chapter.index for chapter in updated_chapters], [1, 2, 3, 4, 5, 6])
            self.assertEqual(updated_continuity.last_chapter_index, 6)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_resume_logic_audit_force_refresh_bypasses_stale_cache(self) -> None:
        client = StubClient(
            [
                {
                    "passed": True,
                    "gate_passed": True,
                    "summary": "重新审计后卷级闸门通过。",
                    "issues": [],
                    "watch_items": ["下一卷继续盯住名单线。"],
                    "required_followups": [],
                    "flagged_chapters": [],
                    "repair_plan": [],
                    "structure_risks": [],
                    "voice_risks": [],
                    "density_risks": [],
                    "pressure_risks": [],
                    "grounding_risks": [],
                }
            ],
            [],
        )
        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"logic-audit-refresh-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            pipeline = NovelPipeline(client, temp_dir, resume=True)
            spec = ProjectSpec(
                title="测试小说",
                genre="都市悬疑",
                audience="中文读者",
                tone="克制",
                premise="名单会牵出旧账。",
                theme="面对代价",
                hook="名单少了一页。",
                setting="海边旧城",
                protagonist="沈雾",
                outline_hint="卷末要过硬闸门",
                world_hint="设定服务剧情",
                ending_mode="standalone",
                pov="第三人称有限视角",
                target_total_chars=12000,
                target_chars_per_chapter=2000,
                chapter_count=6,
                volume_count=2,
                chapters_per_volume=3,
                style_examples=["克制"],
                must_include=["证据链"],
                avoid=["纯悬念不兑现"],
                character_seeds=[CharacterSeed(name="沈雾", role="主角")],
            )
            bible = WorldBible(
                title="测试小说",
                logline="一句话卖点",
                setting_summary="设定摘要",
                core_conflict="核心冲突",
                theme_statement="主题表达",
                narrative_voice=["克制"],
                world_rules=["规则一"],
                chapter_guardrails=["每章推进主线"],
                ending_contract=["闭环"],
                major_threads=["名单线"],
                characters=[],
            )
            book_outline = BookOutline(
                title="测试小说",
                one_line_summary="一句话简介",
                act_structure=["开端", "推进", "收束"],
                volumes=[VolumeBlueprint(1, 1, 3, "第一卷", "推进", "名单去哪了", "名单反咬", "从回避到行动", ["名单线"])],
            )
            volume_outline = VolumeOutline(
                volume_index=1,
                title="第一卷",
                goal="先保住名单线",
                climax="确认名单残页",
                carry_over_threads=["名单线"],
                chapter_targets=[
                    ChapterOutlineItem(1, 1, "第一章", "推进名单线", "有人抢先动手", "保住名单", "看见残页", "第三人称有限视角", "chapter_hook", ["名单线"])
                ],
            )
            chapter = ChapterResult(
                index=1,
                volume_index=1,
                title="第一章",
                outline_item=volume_outline.chapter_targets[0],
                draft="第一章正文。",
                plan=ChapterPlan(1, "第一章", "推进名单线", ["名单线"], "开场", "结尾", "chapter_hook", []),
                review=ReviewFeedback(True, 90, [], [], [], "通过。"),
                local_quality=LocalQualityReport(True, 91, [], [], "通过。", {}),
                continuity=ContinuityUpdate(1, "第一章摘要", ["名单线"], [], ["事件1"], [], ["目标1"], ["记住1"]),
                attempts=1,
                long_memory=LongRangeMemoryUpdate(chapter_index=1),
            )
            continuity = ContinuityState(last_volume_index=1, last_chapter_index=1, must_remember=["名单线还要闭环"])
            stale = LogicAuditReport(
                passed=False,
                gate_passed=False,
                summary="旧缓存仍判定卷级闸门失败。",
                issues=["残页去向交代不够。"],
                watch_items=[],
                required_followups=["回修第二章并重收卷末。"],
                flagged_chapters=[{"chapter_index": 1}],
                repair_plan=[{"start_chapter": 1, "end_chapter": 1, "instruction": "补齐残页去向。"}],
            )
            relative_path = str(pipeline.store.logic_audit_path(1).relative_to(pipeline.store.root))
            pipeline.store.write_json(relative_path, stale)

            cached = pipeline._audit_volume_logic(spec, bible, book_outline, volume_outline, [chapter], continuity)
            refreshed = pipeline._audit_volume_logic(
                spec,
                bible,
                book_outline,
                volume_outline,
                [chapter],
                continuity,
                force_refresh=True,
            )

            self.assertFalse(cached.gate_passed)
            self.assertEqual(cached.summary, "旧缓存仍判定卷级闸门失败。")
            self.assertTrue(refreshed.gate_passed)
            self.assertEqual(refreshed.summary, "重新审计后卷级闸门通过。")
            self.assertEqual(client.json_calls, 1)
            stored = json.loads(pipeline.store.logic_audit_path(1).read_text(encoding="utf-8"))
            self.assertTrue(stored["gate_passed"])
            self.assertEqual(stored["summary"], "重新审计后卷级闸门通过。")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_logic_audit_retries_when_payload_is_semantically_contradictory(self) -> None:
        client = StubClient(
            [
                {
                    "passed": False,
                    "gate_passed": False,
                    "gate_level": "repair",
                    "summary": "本卷推进完整、清楚、成立。",
                    "issues": ["结构稳定，推进自然。"],
                    "watch_items": ["继续保持当前推进。"],
                    "required_followups": ["维持现有兑现节奏。"],
                    "flagged_chapters": [],
                    "repair_plan": [],
                },
                {
                    "passed": True,
                    "gate_passed": True,
                    "gate_level": "pass",
                    "summary": "卷级闸门通过。",
                    "issues": [],
                    "watch_items": ["下一卷继续盯住名单线。"],
                    "required_followups": [],
                    "flagged_chapters": [],
                    "repair_plan": [],
                },
            ],
            [],
        )
        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"logic-audit-semantic-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            pipeline = NovelPipeline(client, temp_dir, flagship_model="gpt-flagship", light_model="gpt-light")
            spec = ProjectSpec(
                title="测试小说",
                genre="都市悬疑",
                audience="中文读者",
                tone="克制",
                premise="名单会牵出旧账。",
                theme="面对代价",
                hook="名单少了一页。",
                setting="海边旧城",
                protagonist="沈雾",
                outline_hint="卷末要过硬闸门",
                world_hint="设定服务剧情",
                ending_mode="standalone",
                pov="第三人称有限视角",
                target_total_chars=12000,
                target_chars_per_chapter=2000,
                chapter_count=6,
                volume_count=2,
                chapters_per_volume=3,
            )
            bible = WorldBible(
                title="测试小说",
                logline="一句话卖点",
                setting_summary="设定摘要",
                core_conflict="核心冲突",
                theme_statement="主题表达",
                narrative_voice=["克制"],
                world_rules=["规则一"],
                chapter_guardrails=["每章推进主线"],
                ending_contract=["闭环"],
                major_threads=["名单线"],
                characters=[],
            )
            book_outline = BookOutline(
                title="测试小说",
                one_line_summary="一句话简介",
                act_structure=["开端", "推进", "收束"],
                volumes=[VolumeBlueprint(1, 1, 3, "第一卷", "推进", "名单去哪了", "名单反咬", "从回避到行动", ["名单线"])],
            )
            volume_outline = VolumeOutline(
                volume_index=1,
                title="第一卷",
                goal="先保住名单线",
                climax="确认名单残页",
                carry_over_threads=["名单线"],
                chapter_targets=[
                    ChapterOutlineItem(1, 1, "第一章", "推进名单线", "有人抢先动手", "保住名单", "看见残页", "第三人称有限视角", "chapter_hook", ["名单线"])
                ],
            )
            chapter = ChapterResult(
                index=1,
                volume_index=1,
                title="第一章",
                outline_item=volume_outline.chapter_targets[0],
                draft="第一章正文。",
                plan=ChapterPlan(1, "第一章", "推进名单线", ["名单线"], "开场", "结尾", "chapter_hook", []),
                review=ReviewFeedback(True, 90, [], [], [], "通过。"),
                local_quality=LocalQualityReport(True, 91, [], [], "通过。", {}),
                continuity=ContinuityUpdate(1, "第一章摘要", ["名单线"], [], ["事件1"], [], ["目标1"], ["记住1"]),
                attempts=1,
                long_memory=LongRangeMemoryUpdate(chapter_index=1),
            )

            audit = pipeline._audit_volume_logic(
                spec,
                bible,
                book_outline,
                volume_outline,
                [chapter],
                ContinuityState(last_volume_index=1, last_chapter_index=1),
                force_refresh=True,
            )

            self.assertTrue(audit is not None and audit.gate_passed)
            self.assertEqual(len(client.models_by_session["logic-audit"]), 2)
            self.assertEqual(client.models_by_session["logic-audit"][-1], "gpt-light")
            self.assertIn("语义异常", client.user_prompts_by_session["logic-audit"][-1])
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_cluster_repair_rewrites_multiple_chapters(self) -> None:
        client = StubClient([], [])
        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"cluster-repair-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        original_analyze = pipeline_module.analyze_chapter
        try:
            pipeline = NovelPipeline(client, temp_dir)
            pipeline._style_bible = StyleBible(
                sample_passages=[StylePassage(label="压紧推进", use_case="chapter_hook", text="先推进证据，再落情绪。")]
            )
            spec = ProjectSpec(
                title="测试小说",
                genre="都市悬疑",
                audience="中文读者",
                tone="克制",
                premise="旧账会反咬人。",
                theme="承担代价",
                hook="一份名单少了最关键的一行。",
                setting="海边旧城",
                protagonist="沈雾",
                outline_hint="卷中要保持因果闭合",
                world_hint="设定服务剧情",
                ending_mode="standalone",
                pov="第三人称有限视角",
                target_total_chars=16000,
                target_chars_per_chapter=300,
                chapter_count=8,
                volume_count=2,
                chapters_per_volume=4,
                style_examples=["克制"],
                must_include=["证据链"],
                avoid=["拖延主线"],
                character_seeds=[CharacterSeed(name="沈雾", role="主角")],
            )
            bible = WorldBible(
                title="测试小说",
                logline="一句话卖点",
                setting_summary="设定摘要",
                core_conflict="核心冲突",
                theme_statement="主题表达",
                narrative_voice=["克制"],
                world_rules=["规则一"],
                chapter_guardrails=["每章推进主线"],
                ending_contract=["闭环"],
                major_threads=["名单线"],
                characters=[],
            )
            volume_outline = VolumeOutline(
                volume_index=1,
                title="第一卷",
                goal="推进名单线",
                climax="确认谁改了名单",
                carry_over_threads=["名单线"],
                chapter_targets=[
                    ChapterOutlineItem(1, 1, "第一章", "起线", "名单出现", "发现名单", "她开始查", "第三人称有限视角", "chapter_hook", ["名单"]),
                    ChapterOutlineItem(2, 1, "第二章", "查残页", "残页会丢", "她压着情绪追残页", "发现缺口", "第三人称有限视角", "chapter_hook", ["残页"]),
                    ChapterOutlineItem(3, 1, "第三章", "补因果", "线索会断", "她把证据和人串起来", "卷末反咬", "第三人称有限视角", "chapter_hook", ["证据链"]),
                ],
            )
            book_outline = BookOutline(
                title="测试小说",
                one_line_summary="一句话简介",
                act_structure=["开端", "推进", "收束"],
                volumes=[VolumeBlueprint(1, 1, 3, "第一卷", "推进", "名单去哪了", "卷末反咬", "她决定继续查", ["名单线"])],
            )
            base_plan = lambda idx, title: ChapterPlan(
                idx,
                title,
                "推进主线",
                ["名单线", "证据链"],
                "开场",
                "结尾",
                "chapter_hook",
                [SceneCard(1, "旧档案室", "核账", "会被人看见", "她先拿到账本", ["名单"])],
            )
            chapters = [
                ChapterResult(
                    index=1,
                    volume_index=1,
                    title="第一章",
                    outline_item=volume_outline.chapter_targets[0],
                    draft="第一章旧稿。",
                    plan=base_plan(1, "第一章"),
                    review=ReviewFeedback(True, 90, [], [], [], "通过。"),
                    local_quality=LocalQualityReport(True, 90, [], [], "通过。", {}),
                    continuity=ContinuityUpdate(1, "第一章摘要", ["名单线"], [], ["事件1"], [], ["目标1"], ["记住1"]),
                    attempts=1,
                    long_memory=LongRangeMemoryUpdate(chapter_index=1),
                ),
                ChapterResult(
                    index=2,
                    volume_index=1,
                    title="第二章",
                    outline_item=volume_outline.chapter_targets[1],
                    draft="第二章旧稿。",
                    plan=base_plan(2, "第二章"),
                    review=ReviewFeedback(True, 89, [], [], [], "通过。"),
                    local_quality=LocalQualityReport(True, 89, [], [], "通过。", {}),
                    continuity=ContinuityUpdate(2, "第二章摘要", ["残页"], [], ["事件2"], [], ["目标2"], ["记住2"]),
                    attempts=1,
                    long_memory=LongRangeMemoryUpdate(chapter_index=2),
                ),
                ChapterResult(
                    index=3,
                    volume_index=1,
                    title="第三章",
                    outline_item=volume_outline.chapter_targets[2],
                    draft="第三章旧稿。",
                    plan=base_plan(3, "第三章"),
                    review=ReviewFeedback(True, 88, [], [], [], "通过。"),
                    local_quality=LocalQualityReport(True, 88, [], [], "通过。", {}),
                    continuity=ContinuityUpdate(3, "第三章摘要", [], ["残页"], ["事件3"], [], ["目标3"], ["记住3"]),
                    attempts=1,
                    long_memory=LongRangeMemoryUpdate(chapter_index=3),
                ),
            ]
            audit = LogicAuditReport(
                passed=False,
                gate_passed=False,
                summary="第二至三章的因果链断了一截。",
                issues=["第二章残页去向和第三章卷末回收没有扣紧。"],
                watch_items=[],
                required_followups=["连续回修第二章和第三章。"],
                flagged_chapters=[{"chapter_index": 2}, {"chapter_index": 3}],
                repair_plan=[{"start_chapter": 2, "end_chapter": 3, "instruction": "补齐残页去向和卷末回收。"}],
            )
            rewritten_texts = iter(
                [
                    (
                        "第二章回修稿。沈雾没有再绕开那份残页，而是顺着旧档案室的缺口把证据链一格一格核回去。"
                        "她压着气息，把每个名字和缺页编号都钉在同一条线上。"
                    ),
                    (
                        "第三章回修稿。卷末反咬不再凭空发生，沈雾先把第二章留下的缺页编号拿去对照账本，再让结果落回到具体责任上。"
                        "她因此看见真正改账的人已经提前封住了退路。"
                    ),
                ]
            )

            pipeline_module.analyze_chapter = lambda *args, **kwargs: LocalQualityReport(True, 95, [], [], "通过。", {})
            pipeline._build_chapter_room = lambda *args, **kwargs: {"shared_mandates": ["补齐因果链"]}  # type: ignore[method-assign]
            pipeline._generate_text_with_progress = lambda *args, **kwargs: next(rewritten_texts)  # type: ignore[method-assign]
            pipeline._review_chapter = lambda *args, **kwargs: ReviewFeedback(True, 95, [], [], [], "通过。")  # type: ignore[method-assign]
            pipeline._extract_continuity = (  # type: ignore[method-assign]
                lambda _spec, _bible, chapter, _draft, _state: ContinuityUpdate(
                    chapter.index,
                    f"{chapter.title}已回修。",
                    [f"线程{chapter.index}"],
                    [],
                    [f"事件{chapter.index}"],
                    [],
                    [f"下一步{chapter.index}"],
                    [f"记住{chapter.index}"],
                )
            )
            pipeline._extract_long_range_memory = (  # type: ignore[method-assign]
                lambda _spec, _bible, chapter, _plan, _draft: LongRangeMemoryUpdate(
                    chapter_index=chapter.index,
                    promise_updates=[],
                    causality_updates=[],
                )
            )

            repaired = pipeline._repair_chapter_cluster(spec, bible, book_outline, volume_outline, chapters, audit)

            self.assertEqual(repaired[0].draft, "第一章旧稿。")
            self.assertTrue(repaired[1].draft.startswith("第二章回修稿。"))
            self.assertTrue(repaired[2].draft.startswith("第三章回修稿。"))
            self.assertEqual(repaired[1].attempts, 2)
            self.assertEqual(repaired[2].attempts, 2)
            self.assertTrue((temp_dir / "chapters" / "chapter-02.md").exists())
            self.assertTrue((temp_dir / "state" / "chapter-03.memory.json").exists())
        finally:
            pipeline_module.analyze_chapter = original_analyze
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_cluster_repair_retries_when_first_revision_still_fails(self) -> None:
        client = StubClient([], [])
        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"cluster-repair-retry-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        original_analyze = pipeline_module.analyze_chapter
        try:
            pipeline = NovelPipeline(client, temp_dir)
            pipeline._style_bible = StyleBible()
            spec = ProjectSpec(
                title="测试小说",
                genre="都市悬疑",
                audience="中文读者",
                tone="克制",
                premise="旧账会反咬人。",
                theme="承担代价",
                hook="一份名单少了最关键的一行。",
                setting="海边旧城",
                protagonist="沈雾",
                outline_hint="卷中要保持因果闭合",
                world_hint="设定服务剧情",
                ending_mode="standalone",
                pov="第三人称有限视角",
                target_total_chars=16000,
                target_chars_per_chapter=300,
                chapter_count=8,
                volume_count=2,
                chapters_per_volume=4,
                style_examples=["克制"],
                must_include=["证据链"],
                avoid=["拖延主线"],
                character_seeds=[CharacterSeed(name="沈雾", role="主角")],
            )
            bible = WorldBible(
                title="测试小说",
                logline="一句话卖点",
                setting_summary="设定摘要",
                core_conflict="核心冲突",
                theme_statement="主题表达",
                narrative_voice=["克制"],
                world_rules=["规则一"],
                chapter_guardrails=["每章推进主线"],
                ending_contract=["闭环"],
                major_threads=["名单线"],
                characters=[],
            )
            volume_outline = VolumeOutline(
                volume_index=1,
                title="第一卷",
                goal="推进名单线",
                climax="确认谁改了名单",
                carry_over_threads=["名单线"],
                chapter_targets=[
                    ChapterOutlineItem(1, 1, "第一章", "起线", "名单出现", "发现名单", "她开始查", "第三人称有限视角", "chapter_hook", ["名单"]),
                    ChapterOutlineItem(2, 1, "第二章", "查残页", "残页会丢", "她压着情绪追残页", "发现缺口", "第三人称有限视角", "chapter_hook", ["残页"]),
                ],
            )
            book_outline = BookOutline(
                title="测试小说",
                one_line_summary="一句话简介",
                act_structure=["开端", "推进", "收束"],
                volumes=[VolumeBlueprint(1, 1, 2, "第一卷", "推进", "名单去哪了", "她得把决定写实", "她决定承担", ["名单线"])],
            )
            plan = ChapterPlan(
                2,
                "第二章",
                "推进主线",
                ["名单线", "证据链"],
                "开场",
                "结尾",
                "chapter_hook",
                [SceneCard(1, "旧档案室", "核账", "会被人看见", "她先拿到账本", ["名单"])],
            )
            chapters = [
                ChapterResult(
                    index=1,
                    volume_index=1,
                    title="第一章",
                    outline_item=volume_outline.chapter_targets[0],
                    draft="第一章旧稿。",
                    plan=plan,
                    review=ReviewFeedback(True, 90, [], [], [], "通过。"),
                    local_quality=LocalQualityReport(True, 90, [], [], "通过。", {}),
                    continuity=ContinuityUpdate(1, "第一章摘要", ["名单线"], [], ["事件1"], [], ["目标1"], ["记住1"]),
                    attempts=1,
                    long_memory=LongRangeMemoryUpdate(chapter_index=1),
                ),
                ChapterResult(
                    index=2,
                    volume_index=1,
                    title="第二章",
                    outline_item=volume_outline.chapter_targets[1],
                    draft="第二章旧稿。",
                    plan=plan,
                    review=ReviewFeedback(True, 89, [], [], [], "通过。"),
                    local_quality=LocalQualityReport(True, 89, [], [], "通过。", {}),
                    continuity=ContinuityUpdate(2, "第二章摘要", ["残页"], [], ["事件2"], [], ["目标2"], ["记住2"]),
                    attempts=1,
                    long_memory=LongRangeMemoryUpdate(chapter_index=2),
                ),
            ]
            audit = LogicAuditReport(
                passed=False,
                gate_passed=False,
                summary="第二章卷末动作偏软。",
                issues=["第二章需要把决定写实。"],
                watch_items=[],
                required_followups=["把卷末决定写实。"],
                flagged_chapters=[{"chapter_index": 2}],
                repair_plan=[{"start_chapter": 2, "end_chapter": 2, "instruction": "把卷末决定写实。"}],
            )

            rewritten_texts = iter(
                [
                    "第二章第一次回修稿，卷末仍然停在犹豫。",
                    "第二章第二次回修稿，卷末她明确决定第二天就递交说明。",
                ]
            )
            reviews = iter(
                [
                    ReviewFeedback(False, 84, [], ["卷末动作偏软。"], ["把决定写实。"], "未通过。"),
                    ReviewFeedback(True, 93, [], [], [], "通过。"),
                ]
            )

            pipeline_module.analyze_chapter = lambda *args, **kwargs: LocalQualityReport(True, 95, [], [], "通过。", {})
            pipeline._build_chapter_room = lambda *args, **kwargs: {"shared_mandates": ["把卷末决定写实"]}  # type: ignore[method-assign]
            pipeline._generate_text_with_progress = lambda *args, **kwargs: next(rewritten_texts)  # type: ignore[method-assign]
            pipeline._review_chapter = lambda *args, **kwargs: next(reviews)  # type: ignore[method-assign]
            pipeline._extract_continuity = (  # type: ignore[method-assign]
                lambda _spec, _bible, chapter, _draft, _state: ContinuityUpdate(
                    chapter.index,
                    f"{chapter.title}已回修。",
                    [f"线程{chapter.index}"],
                    [],
                    [f"事件{chapter.index}"],
                    [],
                    [f"下一步{chapter.index}"],
                    [f"记住{chapter.index}"],
                )
            )
            pipeline._extract_long_range_memory = (  # type: ignore[method-assign]
                lambda _spec, _bible, chapter, _plan, _draft: LongRangeMemoryUpdate(
                    chapter_index=chapter.index,
                    promise_updates=[],
                    causality_updates=[],
                )
            )

            repaired = pipeline._repair_chapter_cluster(spec, bible, book_outline, volume_outline, chapters, audit)

            self.assertEqual(repaired[1].draft, "第二章第二次回修稿，卷末她明确决定第二天就递交说明。")
            self.assertEqual(repaired[1].attempts, 3)
        finally:
            pipeline_module.analyze_chapter = original_analyze
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_cluster_repair_records_stagnation_warning(self) -> None:
        client = StubClient([], ["第二章回修稿。"])
        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"cluster-repair-reroute-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        original_analyze = pipeline_module.analyze_chapter
        try:
            pipeline = NovelPipeline(client, temp_dir)
            pipeline._style_bible = StyleBible()
            pipeline._voice_cards = []
            pipeline._build_chapter_room = lambda *_args, **_kwargs: {}  # type: ignore[method-assign]
            pipeline._select_story_memories = lambda *_args, **_kwargs: []  # type: ignore[method-assign]
            pipeline._select_style_memories = lambda *_args, **_kwargs: []  # type: ignore[method-assign]
            pipeline._select_promise_memories = lambda *_args, **_kwargs: []  # type: ignore[method-assign]
            pipeline._select_causality_memories = lambda *_args, **_kwargs: []  # type: ignore[method-assign]
            pipeline._latest_logic_audit_for_volume = lambda *_args, **_kwargs: None  # type: ignore[method-assign]
            spec = ProjectSpec(
                title="测试小说",
                genre="都市悬疑",
                audience="中文读者",
                tone="克制",
                premise="旧账会反咬人。",
                theme="承担代价",
                hook="一份名单少了最关键的一行。",
                setting="海边旧城",
                protagonist="沈雾",
                outline_hint="卷中要保持因果闭合",
                world_hint="设定服务剧情",
                ending_mode="standalone",
                pov="第三人称有限视角",
                target_total_chars=16000,
                target_chars_per_chapter=1600,
                chapter_count=8,
                volume_count=2,
                chapters_per_volume=4,
                style_examples=["克制"],
                must_include=["证据链"],
                avoid=["拖延主线"],
                character_seeds=[CharacterSeed(name="沈雾", role="主角")],
            )
            bible = WorldBible(
                title="测试小说",
                logline="一句话卖点",
                setting_summary="设定摘要",
                core_conflict="核心冲突",
                theme_statement="主题表达",
                narrative_voice=["克制"],
                world_rules=["规则一"],
                chapter_guardrails=["每章推进主线"],
                ending_contract=["闭环"],
                major_threads=["名单线"],
                characters=[],
            )
            book_outline = BookOutline(
                title="测试小说",
                one_line_summary="一句话简介",
                act_structure=["开端", "推进", "收束"],
                volumes=[VolumeBlueprint(1, 1, 2, "第一卷", "推进", "名单去哪了", "卷末反咬", "她决定继续查", ["名单线"])],
            )
            volume_outline = VolumeOutline(
                volume_index=1,
                title="第一卷",
                goal="推进名单线",
                climax="确认谁改了名单",
                carry_over_threads=["名单线"],
                chapter_targets=[
                    ChapterOutlineItem(1, 1, "第一章", "起线", "名单出现", "发现名单", "她开始查", "第三人称有限视角", "chapter_hook", ["名单"]),
                    ChapterOutlineItem(2, 1, "第二章", "查残页", "残页会丢", "她压着情绪追残页", "发现缺口", "第三人称有限视角", "chapter_hook", ["残页"]),
                ],
            )
            plan = ChapterPlan(
                2,
                "第二章",
                "推进主线",
                ["名单线", "证据链"],
                "开场",
                "结尾",
                "chapter_hook",
                [SceneCard(1, "公示栏", "公开作证", "围观施压", "她继续抬程序", "evidence_push")],
                primary_propulsion="证据推进",
            )
            chapters = [
                ChapterResult(
                    index=1,
                    volume_index=1,
                    title="第一章",
                    outline_item=volume_outline.chapter_targets[0],
                    draft="第一章旧稿。",
                    plan=ChapterPlan(1, "第一章", "起线", ["名单线"], "开场", "结尾", "chapter_hook", []),
                    review=ReviewFeedback(True, 90, [], [], [], "通过。"),
                    local_quality=LocalQualityReport(True, 90, [], [], "通过。", {}),
                    continuity=ContinuityUpdate(1, "第一章摘要", ["名单线"], [], ["事件1"], [], ["目标1"], ["记住1"]),
                    attempts=1,
                    long_memory=LongRangeMemoryUpdate(chapter_index=1),
                ),
                ChapterResult(
                    index=2,
                    volume_index=1,
                    title="第二章",
                    outline_item=volume_outline.chapter_targets[1],
                    draft="第二章旧稿。",
                    plan=plan,
                    review=ReviewFeedback(True, 89, [], [], [], "通过。"),
                    local_quality=LocalQualityReport(True, 89, [], [], "通过。", {}),
                    continuity=ContinuityUpdate(2, "第二章摘要", ["残页"], [], ["事件2"], [], ["目标2"], ["记住2"]),
                    attempts=1,
                    long_memory=LongRangeMemoryUpdate(chapter_index=2),
                ),
            ]
            audit = LogicAuditReport(
                passed=False,
                gate_passed=False,
                summary="第二章需要换挡。",
                issues=["第二章推进方式和前章太像。"],
                watch_items=[],
                required_followups=["把第二章改成另一种推进。"],
                flagged_chapters=[{"chapter_index": 2}],
                repair_plan=[{"start_chapter": 2, "end_chapter": 2, "instruction": "不要再写公开作证。"}],
            )

            pipeline._review_chapter = lambda *_args, **_kwargs: ReviewFeedback(True, 94, [], [], [], "通过。")  # type: ignore[method-assign]
            pipeline._extract_continuity = lambda _spec, _bible, chapter, _draft, _state: ContinuityUpdate(chapter.index, f"{chapter.title}已回修。", [f"线程{chapter.index}"], [], [f"事件{chapter.index}"], [], [f"下一步{chapter.index}"], [f"记住{chapter.index}"])  # type: ignore[method-assign]
            pipeline._extract_long_range_memory = lambda _spec, _bible, chapter, _plan, _draft: LongRangeMemoryUpdate(chapter_index=chapter.index)  # type: ignore[method-assign]
            pipeline_module.analyze_chapter = lambda *_args, **_kwargs: LocalQualityReport(
                True,
                95,
                ["最近几章仍在同一推进簇，存在轻度空转风险。"],
                [],
                "通过。",
                {
                    "stagnation_signal_level": "warning",
                    "stagnation_warning": True,
                    "stagnation_same_family_cluster": 5,
                    "stagnation_same_family_tail": 4,
                    "current_propulsion": "证据推进",
                    "recent_propulsion_history": ["证据推进", "程序拆解", "证据推进"],
                    "propulsion_hard_fail": False,
                },
            )

            repaired = pipeline._repair_chapter_cluster(spec, bible, book_outline, volume_outline, chapters, audit)

            self.assertTrue(repaired[1].local_quality.passed)
            self.assertTrue(any("长窗口告警" in note for note in repaired[1].continuity.must_remember))
            self.assertFalse((temp_dir / "data" / "latest-stagnation-report.json").exists())
            self.assertEqual(client.text_calls, 1)
        finally:
            pipeline_module.analyze_chapter = original_analyze
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_enforce_volume_gate_repairs_metadata_before_cluster(self) -> None:
        client = StubClient([], [])
        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"volume-gate-metadata-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            pipeline = NovelPipeline(client, temp_dir)
            spec = ProjectSpec(
                title="测试小说",
                genre="都市悬疑",
                audience="中文读者",
                tone="克制",
                premise="旧账会反咬人。",
                theme="承担代价",
                hook="一份名单缺了关键编号。",
                setting="海边旧城",
                protagonist="沈雾",
                outline_hint="卷中要保持因果闭合",
                world_hint="设定服务剧情",
                ending_mode="standalone",
                pov="第三人称有限视角",
                target_total_chars=16000,
                target_chars_per_chapter=2000,
                chapter_count=8,
                volume_count=4,
                chapters_per_volume=2,
                style_examples=["克制"],
                must_include=["证据链"],
                avoid=["拖延主线"],
                character_seeds=[CharacterSeed(name="沈雾", role="主角")],
            )
            bible = WorldBible(
                title="测试小说",
                logline="一句话卖点",
                setting_summary="设定摘要",
                core_conflict="核心冲突",
                theme_statement="主题表达",
                narrative_voice=["克制"],
                world_rules=["规则一"],
                chapter_guardrails=["每章推进主线"],
                ending_contract=["闭环"],
                major_threads=["名单线"],
                characters=[],
            )
            book_outline = BookOutline(
                title="测试小说",
                one_line_summary="一句话简介",
                act_structure=["起", "承", "转", "合"],
                volumes=[
                    VolumeBlueprint(1, 1, 2, "第一卷", "起线", "名单出现", "她决定查", "从旁观到入局", ["名单线"]),
                    VolumeBlueprint(2, 3, 4, "第二卷", "扩线", "账页缺口", "她追到旧港", "开始承担风险", ["账页线"]),
                    VolumeBlueprint(3, 5, 6, "第三卷", "并证", "旧编号回浮", "拿到旧档案", "愿意压上名声", ["旧编号"]),
                    VolumeBlueprint(4, 7, 8, "第四卷", "收束", "程序反咬", "稳住局面", "准备直扑前线", ["卷末闭环"]),
                ],
            )
            volume_outline = VolumeOutline(
                volume_index=4,
                title="第四卷",
                goal="稳住局面",
                climax="确认卷末闭环",
                carry_over_threads=["名单线", "旧编号"],
                chapter_targets=[
                    ChapterOutlineItem(7, 4, "第七章", "承上", "账本会反咬", "拿稳旧账页", "继续并证", "第三人称有限视角", "chapter_hook", ["账页"]),
                    ChapterOutlineItem(8, 4, "第八章", "卷末", "程序会反咬", "确认旧编号", "下卷直扑前线", "第三人称有限视角", "chapter_hook", ["旧编号"]),
                ],
            )
            chapters = [
                ChapterResult(
                    index=7,
                    volume_index=4,
                    title="第七章",
                    outline_item=volume_outline.chapter_targets[0],
                    draft="第七章正文。",
                    plan=ChapterPlan(7, "第七章", "并证推进", ["名单线"], "开场", "结尾", "chapter_hook", []),
                    review=ReviewFeedback(True, 91, [], [], [], "通过。"),
                    local_quality=LocalQualityReport(True, 92, [], [], "通过。", {}),
                    continuity=ContinuityUpdate(7, "第七章摘要", ["名单线"], [], ["事件7"], [], ["目标7"], ["记住7"]),
                    attempts=1,
                    long_memory=LongRangeMemoryUpdate(
                        chapter_index=7,
                        promise_updates=[
                            PromiseLedgerItem(
                        promise_id="p-ledger-1",
                        label="名单线",
                        thread="名单线",
                        target_volume=3,
                        chapter_opened=5,
                        current_status="advanced",
                        last_touched_chapter=7,
                                overdue=True,
                            )
                        ],
                        causality_updates=[],
                    ),
                ),
                ChapterResult(
                    index=8,
                    volume_index=4,
                    title="第八章",
                    outline_item=volume_outline.chapter_targets[1],
                    draft="第八章正文。",
                    plan=ChapterPlan(8, "第八章", "卷末收束", ["名单线"], "开场", "结尾", "chapter_hook", []),
                    review=ReviewFeedback(True, 92, [], [], [], "通过。"),
                    local_quality=LocalQualityReport(True, 93, [], [], "通过。", {}),
                    continuity=ContinuityUpdate(8, "第八章摘要", ["名单线"], [], ["事件8"], [], ["目标8"], ["记住8"]),
                    attempts=1,
                    long_memory=LongRangeMemoryUpdate(
                        chapter_index=8,
                        promise_updates=[
                            PromiseLedgerItem(
                        promise_id="p-ledger-1",
                        label="名单线",
                        thread="名单线",
                        target_volume=3,
                        chapter_opened=5,
                        current_status="advanced",
                        last_touched_chapter=8,
                                overdue=True,
                            )
                        ],
                        causality_updates=[],
                    ),
                ),
            ]
            continuity = ContinuityState(last_volume_index=4, last_chapter_index=8, must_remember=["名单线"])
            pipeline._promise_ledger = [
                PromiseLedgerItem(
                    promise_id="p-ledger-1",
                    label="名单线",
                    thread="名单线",
                    target_volume=3,
                    chapter_opened=5,
                    current_status="advanced",
                    last_touched_chapter=8,
                    overdue=True,
                    deadline_state="overdue",
                )
            ]

            audits = iter(
                [
                    LogicAuditReport(
                        passed=False,
                        gate_passed=False,
                        gate_level="repair_metadata",
                        summary="承诺账本记录失真，先修正元数据。",
                        issues=["名单线明明仍在推进，却被长期标记成逾期。"],
                        watch_items=[],
                        required_followups=["先修账本，再重新审卷。"],
                        flagged_chapters=[],
                        repair_plan=[],
                    ),
                    LogicAuditReport(
                        passed=True,
                        gate_passed=True,
                        gate_level="pass",
                        summary="账本修正后卷级闸门通过。",
                        issues=[],
                        watch_items=["下卷继续收名单线。"],
                        required_followups=[],
                        flagged_chapters=[],
                        repair_plan=[],
                    ),
                ]
            )

            def fake_audit(*args, **kwargs):
                return next(audits)

            def fail_cluster(*args, **kwargs):
                raise AssertionError("metadata drift should not escalate to cluster repair")

            pipeline._audit_volume_logic = fake_audit  # type: ignore[method-assign]
            pipeline._repair_chapter_cluster = fail_cluster  # type: ignore[method-assign]

            updated_chapters, updated_continuity = pipeline._enforce_volume_gate(
                spec,
                bible,
                book_outline,
                volume_outline,
                chapters,
                chapters,
                continuity,
            )

            self.assertEqual([chapter.index for chapter in updated_chapters], [7, 8])
            self.assertEqual(updated_continuity.last_chapter_index, 8)
            self.assertEqual(len(pipeline._promise_ledger), 1)
            self.assertFalse(pipeline._promise_ledger[0].overdue)
            self.assertEqual(pipeline._promise_ledger[0].deadline_state, "on_track")
            ledger_sanity = json.loads((temp_dir / "data" / "ledger-sanity.json").read_text(encoding="utf-8"))
            self.assertEqual(ledger_sanity["after"]["overdue"], 0)
            self.assertGreaterEqual(ledger_sanity["after"]["advanced"], 1)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_world_generation_uses_streaming_json(self) -> None:
        class RecordingClient:
            def __init__(self) -> None:
                self.calls: list[dict[str, object]] = []

            def generate_json(
                self,
                system_prompt,
                user_prompt,
                *,
                model=None,
                temperature=0.2,
                max_output_tokens=None,
                session_id=None,
                session_max_chars=None,
                provider_tier="flagship",
                stream=False,
                stream_observer=None,
            ):
                self.calls.append(
                    {
                        "stream": stream,
                        "stream_observer": stream_observer,
                        "session_id": session_id,
                        "max_output_tokens": max_output_tokens,
                    }
                )
                return {
                    "title": "测试小说",
                    "logline": "一句话卖点",
                    "setting_summary": "设定摘要",
                    "core_conflict": "核心冲突",
                    "theme_statement": "主题表达",
                    "narrative_voice": ["克制"],
                    "world_rules": ["规则一", "规则二", "规则三", "规则四"],
                    "chapter_guardrails": ["章节约束"],
                    "ending_contract": ["结局约束"],
                    "major_threads": ["主线"],
                    "characters": [
                        {
                            "name": "沈雾",
                            "role": "主角",
                            "goal": "查真相",
                            "fear": "失去家人",
                            "contradiction": "想知道又害怕知道",
                            "arc": "从回避到面对",
                            "public_image": "冷淡",
                            "private_truth": "自责",
                            "speaking_style": "简短",
                            "signature_image": "潮湿玻璃",
                            "relationship_tensions": [],
                            "do_not_break": ["不能突然话痨"],
                        }
                    ],
                }

            def generate_text(self, *args, **kwargs):
                raise AssertionError("generate_text should not be called in this test.")

            def reset_session(self, session_id: str) -> None:
                return

        client = RecordingClient()
        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"pipeline-world-stream-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            pipeline = NovelPipeline(client, temp_dir)
            pipeline._story_room = {"shared_contract": ["主线闭环"]}
            spec = ProjectSpec(
                title="测试小说",
                genre="都市奇谭",
                audience="中文读者",
                tone="克制",
                premise="旧物里有记忆。",
                theme="选择",
                hook="一句话钩子",
                setting="海雾城市",
                protagonist="沈雾",
                outline_hint="完整闭环",
                world_hint="设定服务剧情",
                ending_mode="standalone",
                pov="第三人称有限视角",
                target_total_chars=4000,
                target_chars_per_chapter=2000,
                chapter_count=2,
                volume_count=1,
                chapters_per_volume=2,
                style_examples=["克制"],
                must_include=["主线闭环"],
                avoid=["最后一段另起新案"],
                character_seeds=[CharacterSeed(name="沈雾", role="主角")],
            )

            bible = pipeline._build_world(spec)

            self.assertEqual(bible.title, "测试小说")
            self.assertEqual(client.calls[0]["session_id"], "planner-world")
            self.assertEqual(client.calls[0]["stream"], True)
            self.assertIsNotNone(client.calls[0]["stream_observer"])
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_world_generation_accepts_named_block_list_payload(self) -> None:
        class RecordingClient:
            def generate_json(
                self,
                system_prompt,
                user_prompt,
                *,
                model=None,
                temperature=0.2,
                max_output_tokens=None,
                session_id=None,
                session_max_chars=None,
                provider_tier="flagship",
                stream=False,
                stream_observer=None,
            ):
                return [
                    {"title": "测试小说"},
                    {"setting_summary": "设定摘要"},
                    {"core_conflict": "核心冲突"},
                    {"world_rules": ["规则一", "规则二", "规则三", "规则四"]},
                    {"chapter_guardrails": ["章节约束"]},
                    {"major_threads": ["主线"]},
                    {"characters": [{"name": "沈雾", "role": "主角", "goal": "查真相"}]},
                ]

            def generate_text(self, *args, **kwargs):
                raise AssertionError("generate_text should not be called in this test.")

            def reset_session(self, session_id: str) -> None:
                return

        client = RecordingClient()
        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"pipeline-world-list-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            pipeline = NovelPipeline(client, temp_dir)
            pipeline._story_room = {"shared_contract": ["主线闭环"]}
            spec = ProjectSpec(
                title="测试小说",
                genre="都市奇谭",
                audience="中文读者",
                tone="克制",
                premise="旧物里有记忆。",
                theme="选择",
                hook="一句话钩子",
                setting="海雾城市",
                protagonist="沈雾",
                outline_hint="完整闭环",
                world_hint="设定服务剧情",
                ending_mode="standalone",
                pov="第三人称有限视角",
                target_total_chars=4000,
                target_chars_per_chapter=2000,
                chapter_count=2,
                volume_count=1,
                chapters_per_volume=2,
                style_examples=["克制"],
                must_include=["主线闭环"],
                avoid=["最后一段另起新案"],
                character_seeds=[CharacterSeed(name="沈雾", role="主角")],
            )

            bible = pipeline._build_world(spec)

            self.assertEqual(bible.title, "测试小说")
            self.assertEqual(bible.core_conflict, "核心冲突")
            self.assertEqual(len(bible.world_rules), 4)
            self.assertEqual(bible.characters[0].name, "沈雾")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_world_generation_regenerates_when_content_is_missing(self) -> None:
        class RecordingClient:
            def __init__(self) -> None:
                self.calls: list[dict[str, object]] = []

            def generate_json(
                self,
                system_prompt,
                user_prompt,
                *,
                model=None,
                temperature=0.2,
                max_output_tokens=None,
                session_id=None,
                session_max_chars=None,
                provider_tier="flagship",
                stream=False,
                stream_observer=None,
            ):
                self.calls.append({"session_id": session_id, "provider_tier": provider_tier, "user_prompt": user_prompt})
                if len(self.calls) == 1:
                    return ["必须有设定规则", "必须有角色", "不能只写概念"]
                return {
                    "title": "测试小说",
                    "logline": "一句话卖点",
                    "setting_summary": "设定摘要",
                    "core_conflict": "核心冲突",
                    "theme_statement": "主题表达",
                    "world_rules": ["规则一", "规则二", "规则三", "规则四"],
                    "chapter_guardrails": ["章节约束"],
                    "major_threads": ["主线"],
                    "characters": [{"name": "沈雾", "role": "主角", "goal": "查真相"}],
                }

            def generate_text(self, *args, **kwargs):
                raise AssertionError("generate_text should not be called in this test.")

            def reset_session(self, session_id: str) -> None:
                return

        client = RecordingClient()
        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"pipeline-world-regenerate-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            pipeline = NovelPipeline(client, temp_dir)
            pipeline._story_room = {"shared_contract": ["主线闭环"]}
            spec = ProjectSpec(
                title="测试小说",
                genre="都市奇谭",
                audience="中文读者",
                tone="克制",
                premise="旧物里有记忆。",
                theme="选择",
                hook="一句话钩子",
                setting="海雾城市",
                protagonist="沈雾",
                outline_hint="完整闭环",
                world_hint="设定服务剧情",
                ending_mode="standalone",
                pov="第三人称有限视角",
                target_total_chars=4000,
                target_chars_per_chapter=2000,
                chapter_count=2,
                volume_count=1,
                chapters_per_volume=2,
                style_examples=["克制"],
                must_include=["主线闭环"],
                avoid=["最后一段另起新案"],
                character_seeds=[CharacterSeed(name="沈雾", role="主角")],
            )

            bible = pipeline._build_world(spec)

            self.assertEqual(len(client.calls), 2)
            self.assertIn("缺少有效设定圣经内容", client.calls[1]["user_prompt"])
            self.assertEqual(bible.characters[0].name, "沈雾")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_book_outline_generation_uses_streaming_json(self) -> None:
        class RecordingClient:
            def __init__(self) -> None:
                self.calls: list[dict[str, object]] = []

            def generate_json(
                self,
                system_prompt,
                user_prompt,
                *,
                model=None,
                temperature=0.2,
                max_output_tokens=None,
                session_id=None,
                session_max_chars=None,
                provider_tier="flagship",
                stream=False,
                stream_observer=None,
            ):
                self.calls.append(
                    {
                        "stream": stream,
                        "stream_observer": stream_observer,
                        "session_id": session_id,
                        "max_output_tokens": max_output_tokens,
                    }
                )
                return {
                    "title": "测试小说",
                    "one_line_summary": "一句话简介",
                    "act_structure": ["开端", "推进", "收束"],
                    "volumes": [
                        {
                            "index": 1,
                            "title": "第一卷",
                            "role": "推进主线",
                            "central_question": "真相是什么",
                            "escalation": "局势升级",
                            "emotional_shift": "从迟疑到行动",
                            "must_payoff": ["主线闭环"],
                        }
                    ],
                }

            def generate_text(self, *args, **kwargs):
                raise AssertionError("generate_text should not be called in this test.")

            def reset_session(self, session_id: str) -> None:
                return

        client = RecordingClient()
        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"pipeline-book-stream-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            pipeline = NovelPipeline(client, temp_dir)
            pipeline._story_room = {"shared_contract": ["主线闭环"]}
            spec = ProjectSpec(
                title="测试小说",
                genre="都市奇谭",
                audience="中文读者",
                tone="克制",
                premise="旧物里有记忆。",
                theme="选择",
                hook="一句话钩子",
                setting="海雾城市",
                protagonist="沈雾",
                outline_hint="完整闭环",
                world_hint="设定服务剧情",
                ending_mode="standalone",
                pov="第三人称有限视角",
                target_total_chars=4000,
                target_chars_per_chapter=2000,
                chapter_count=2,
                volume_count=1,
                chapters_per_volume=2,
                style_examples=["克制"],
                must_include=["主线闭环"],
                avoid=["最后一段另起新案"],
                character_seeds=[CharacterSeed(name="沈雾", role="主角")],
            )
            bible = WorldBible(
                title="测试小说",
                logline="一句话卖点",
                setting_summary="设定摘要",
                core_conflict="核心冲突",
                theme_statement="主题表达",
                narrative_voice=["克制"],
                world_rules=["规则一"],
                chapter_guardrails=["章节约束"],
                ending_contract=["结局约束"],
                major_threads=["主线"],
                characters=[],
            )

            outline = pipeline._build_book_outline(spec, bible)

            self.assertEqual(outline.title, "测试小说")
            self.assertEqual(client.calls[0]["session_id"], "planner-book")
            self.assertEqual(client.calls[0]["stream"], True)
            self.assertIsNotNone(client.calls[0]["stream_observer"])
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_book_outline_generation_accepts_named_block_list_payload(self) -> None:
        class RecordingClient:
            def generate_json(
                self,
                system_prompt,
                user_prompt,
                *,
                model=None,
                temperature=0.2,
                max_output_tokens=None,
                session_id=None,
                session_max_chars=None,
                provider_tier="flagship",
                stream=False,
                stream_observer=None,
            ):
                return [
                    {"title": "测试小说"},
                    {"one_line_summary": "一句话简介"},
                    {"act_structure": ["开端", "推进", "收束"]},
                    {
                        "volumes": [
                            {
                                "index": 1,
                                "title": "第一卷",
                                "role": "推进主线",
                                "central_question": "真相是什么",
                                "escalation": "局势升级",
                                "emotional_shift": "从迟疑到行动",
                                "must_payoff": ["主线闭环"],
                            }
                        ]
                    },
                ]

            def generate_text(self, *args, **kwargs):
                raise AssertionError("generate_text should not be called in this test.")

            def reset_session(self, session_id: str) -> None:
                return

        client = RecordingClient()
        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"pipeline-book-normalize-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            pipeline = NovelPipeline(client, temp_dir)
            pipeline._story_room = {"shared_contract": ["主线闭环"]}
            spec = ProjectSpec(
                title="测试小说",
                genre="都市奇谭",
                audience="中文读者",
                tone="克制",
                premise="旧物里有记忆。",
                theme="选择",
                hook="一句话钩子",
                setting="海雾城市",
                protagonist="沈雾",
                outline_hint="完整闭环",
                world_hint="设定服务剧情",
                ending_mode="standalone",
                pov="第三人称有限视角",
                target_total_chars=4000,
                target_chars_per_chapter=2000,
                chapter_count=2,
                volume_count=1,
                chapters_per_volume=2,
                style_examples=["克制"],
                must_include=["主线闭环"],
                avoid=["最后一段另起新案"],
                character_seeds=[CharacterSeed(name="沈雾", role="主角")],
            )
            bible = WorldBible(
                title="测试小说",
                logline="一句话卖点",
                setting_summary="设定摘要",
                core_conflict="核心冲突",
                theme_statement="主题表达",
                narrative_voice=["克制"],
                world_rules=["规则一"],
                chapter_guardrails=["章节约束"],
                ending_contract=["结局约束"],
                major_threads=["主线"],
                characters=[],
            )

            outline = pipeline._build_book_outline(spec, bible)

            self.assertEqual(outline.title, "测试小说")
            self.assertEqual(len(outline.volumes), 1)
            self.assertEqual(outline.volumes[0].title, "第一卷")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_book_outline_generation_repairs_outline_payload_via_normalizer(self) -> None:
        class RecordingClient:
            def __init__(self) -> None:
                self.calls: list[dict[str, object]] = []

            def generate_json(
                self,
                system_prompt,
                user_prompt,
                *,
                model=None,
                temperature=0.2,
                max_output_tokens=None,
                session_id=None,
                session_max_chars=None,
                provider_tier="flagship",
                stream=False,
                stream_observer=None,
            ):
                self.calls.append(
                    {
                        "session_id": session_id,
                        "model": model,
                        "provider_tier": provider_tier,
                    }
                )
                if session_id == "planner-book":
                    return {
                        "outline_blocks": {
                            "sections": [
                                {"headline": "测试小说"},
                                {"volume_items": [{"index": 1, "title": "第一卷", "role": "起势"}]},
                            ]
                        }
                    }
                if session_id == "planner-book-normalizer":
                    return {
                        "title": "测试小说",
                        "one_line_summary": "一句话简介",
                        "act_structure": ["开端", "推进", "收束"],
                        "volumes": [
                            {
                                "index": 1,
                                "title": "第一卷",
                                "role": "推进主线",
                                "central_question": "真相是什么",
                                "escalation": "局势升级",
                                "emotional_shift": "从迟疑到行动",
                                "must_payoff": ["主线闭环"],
                            }
                        ],
                    }
                raise AssertionError(f"unexpected session: {session_id}")

            def generate_text(self, *args, **kwargs):
                raise AssertionError("generate_text should not be called in this test.")

            def reset_session(self, session_id: str) -> None:
                return

        client = RecordingClient()
        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"pipeline-book-repair-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            pipeline = NovelPipeline(client, temp_dir, flagship_model="gpt-flagship", light_model="gpt-light")
            pipeline._story_room = {"shared_contract": ["主线闭环"]}
            spec = ProjectSpec(
                title="测试小说",
                genre="都市奇谭",
                audience="中文读者",
                tone="克制",
                premise="旧物里有记忆。",
                theme="选择",
                hook="一句话钩子",
                setting="海雾城市",
                protagonist="沈雾",
                outline_hint="完整闭环",
                world_hint="设定服务剧情",
                ending_mode="standalone",
                pov="第三人称有限视角",
                target_total_chars=4000,
                target_chars_per_chapter=2000,
                chapter_count=2,
                volume_count=1,
                chapters_per_volume=2,
                style_examples=["克制"],
                must_include=["主线闭环"],
                avoid=["最后一段另起新案"],
                character_seeds=[CharacterSeed(name="沈雾", role="主角")],
            )
            bible = WorldBible(
                title="测试小说",
                logline="一句话卖点",
                setting_summary="设定摘要",
                core_conflict="核心冲突",
                theme_statement="主题表达",
                narrative_voice=["克制"],
                world_rules=["规则一"],
                chapter_guardrails=["章节约束"],
                ending_contract=["结局约束"],
                major_threads=["主线"],
                characters=[],
            )

            outline = pipeline._build_book_outline(spec, bible)

            self.assertEqual(outline.title, "测试小说")
            self.assertEqual(len(outline.volumes), 1)
            self.assertTrue(any(call["session_id"] == "planner-book-normalizer" for call in client.calls))
            self.assertTrue(any(call["provider_tier"] == "light" for call in client.calls if call["session_id"] == "planner-book-normalizer"))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_volume_outline_generation_repairs_outline_payload_via_normalizer(self) -> None:
        class RecordingClient:
            def __init__(self) -> None:
                self.calls: list[dict[str, object]] = []

            def generate_json(
                self,
                system_prompt,
                user_prompt,
                *,
                model=None,
                temperature=0.2,
                max_output_tokens=None,
                session_id=None,
                session_max_chars=None,
                provider_tier="flagship",
                stream=False,
                stream_observer=None,
            ):
                self.calls.append(
                    {
                        "session_id": session_id,
                        "model": model,
                        "provider_tier": provider_tier,
                    }
                )
                if session_id == "planner-volume-1":
                    return {
                        "outline_sections": {
                            "blocks": [
                                {"goal_text": "先立住业务流程和神明规则。"},
                                {"chapter_items": [{"index": 1, "title": "第一章", "purpose": "开局接单"}]},
                            ]
                        }
                    }
                if session_id == "planner-volume-normalizer-1":
                    return {
                        "volume_index": 1,
                        "title": "第一卷",
                        "goal": "先立住业务流程和神明规则。",
                        "climax": "回收链第一次露头。",
                        "carry_over_threads": ["旧账线"],
                        "chapter_targets": [
                            {
                                "index": 1,
                                "title": "第一章",
                                "purpose": "开局接单",
                                "conflict": "现场反常",
                                "beat_summary": "寄存处开门",
                                "ending_note": "留下编号异常",
                                "chapter_role": "opening",
                            }
                        ],
                    }
                raise AssertionError(f"unexpected session: {session_id}")

            def generate_text(self, *args, **kwargs):
                raise AssertionError("generate_text should not be called in this test.")

            def reset_session(self, session_id: str) -> None:
                return

        client = RecordingClient()
        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"pipeline-volume-repair-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            pipeline = NovelPipeline(client, temp_dir, flagship_model="gpt-flagship", light_model="gpt-light")
            spec = ProjectSpec(
                title="测试小说",
                genre="都市奇谭",
                audience="中文读者",
                tone="克制",
                premise="旧物里有记忆。",
                theme="选择",
                hook="一句话钩子",
                setting="海雾城市",
                protagonist="沈雾",
                outline_hint="完整闭环",
                world_hint="设定服务剧情",
                ending_mode="standalone",
                pov="第三人称有限视角",
                target_total_chars=4000,
                target_chars_per_chapter=2000,
                chapter_count=2,
                volume_count=1,
                chapters_per_volume=2,
                style_examples=["克制"],
                must_include=["主线闭环"],
                avoid=["最后一段另起新案"],
                character_seeds=[CharacterSeed(name="沈雾", role="主角")],
            )
            bible = WorldBible(
                title="测试小说",
                logline="一句话卖点",
                setting_summary="设定摘要",
                core_conflict="核心冲突",
                theme_statement="主题表达",
                narrative_voice=["克制"],
                world_rules=["规则一"],
                chapter_guardrails=["章节约束"],
                ending_contract=["结局约束"],
                major_threads=["主线"],
                characters=[],
            )
            volume = VolumeBlueprint(
                index=1,
                start_chapter=1,
                end_chapter=2,
                title="第一卷",
                role="推进主线",
                central_question="真相是什么",
                escalation="局势升级",
                emotional_shift="从迟疑到行动",
            )
            book_outline = BookOutline(title="测试小说", one_line_summary="一句话", act_structure=["开端"], volumes=[volume])

            outline = pipeline._build_volume_outline(spec, bible, book_outline, volume, ContinuityState())

            self.assertEqual(outline.title, "第一卷")
            self.assertEqual(len(outline.chapter_targets), 2)
            self.assertEqual(outline.chapter_targets[0].title, "第一章")
            self.assertTrue(any(call["session_id"] == "planner-volume-normalizer-1" for call in client.calls))
            self.assertTrue(any(call["provider_tier"] == "light" for call in client.calls if call["session_id"] == "planner-volume-normalizer-1"))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_text_generation_uses_streaming_progress(self) -> None:
        class RecordingClient:
            def __init__(self) -> None:
                self.calls: list[dict[str, object]] = []

            def generate_json(self, *args, **kwargs):
                raise AssertionError("generate_json should not be called in this test.")

            def generate_text(
                self,
                system_prompt,
                user_prompt,
                *,
                model=None,
                temperature=0.3,
                max_output_tokens=None,
                json_mode=False,
                session_id=None,
                session_max_chars=None,
                provider_tier="flagship",
                stream=False,
                stream_observer=None,
            ):
                self.calls.append(
                    {
                        "stream": stream,
                        "stream_observer": stream_observer,
                        "session_id": session_id,
                        "max_output_tokens": max_output_tokens,
                    }
                )
                return "第一段。\n\n第二段。"

            def reset_session(self, session_id: str) -> None:
                return

        client = RecordingClient()
        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"pipeline-text-stream-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            pipeline = NovelPipeline(client, temp_dir)

            text = pipeline._generate_text_with_progress(
                "chapter_draft",
                "生成第 1 章正文。",
                "第1章初稿",
                "system",
                "user",
                session_id="writer-v1",
                session_max_chars=60000,
                max_output_tokens=1800,
            )

            self.assertEqual(text, "第一段。\n\n第二段。")
            self.assertEqual(client.calls[0]["session_id"], "writer-v1")
            self.assertEqual(client.calls[0]["stream"], True)
            self.assertIsNotNone(client.calls[0]["stream_observer"])
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_pipeline_cleans_duplicate_paragraphs_before_quality_gate(self) -> None:
        class ChapterClient:
            def __init__(self) -> None:
                self.json_payloads = [
                    {
                        "notes": [
                            {
                                "agent": "continuity_guard",
                                "must_land": ["主角必须做出决定"],
                                "risks": ["重复兜圈"],
                                "summary": "动作要推进。"
                            }
                        ],
                        "shared_mandates": ["只写本章必要动作"],
                        "blocking_issues": ["不要重复段落"],
                    },
                    {
                        "passed": True,
                        "score": 90,
                        "strengths": ["冲突成立"],
                        "issues": [],
                        "required_fixes": [],
                        "short_summary": "本章合格。",
                        "chapter_fixes": [],
                    },
                    {
                        "chapter_index": 1,
                        "chapter_summary": "沈雾决定带着旧表去旧影院。",
                        "new_threads": ["旧影院线索"],
                        "resolved_threads": [],
                        "timeline_events": ["她决定去旧影院"],
                        "character_states": [
                            {
                                "name": "沈雾",
                                "current_goal": "去旧影院",
                                "emotional_state": "警惕",
                                "relationship_shift": "更主动",
                                "risk": "旧案逼近",
                                "unresolved": "真相未明",
                            }
                        ],
                        "next_chapter_targets": ["旧影院"],
                        "must_remember": ["旧表划痕"],
                    },
                ]

            def generate_json(self, *args, **kwargs):
                if kwargs.get("session_id") == "long-memory":
                    return {"chapter_index": 1, "promise_updates": [], "causality_updates": []}
                if not self.json_payloads:
                    raise AssertionError("No JSON payload left for test.")
                return self.json_payloads.pop(0)

            def generate_text(self, *args, **kwargs):
                return (
                    "沈雾把旧表翻到背面，指腹停在那道熟悉的划痕上，像在确认半年前留下的伤口并没有自己愈合。她没有立刻去碰秒针，只先把呼吸压平，免得手指发抖把那点冷硬的金属错认成别的东西。\n\n"
                    "她没再装作看不见，只把登记簿拖到灯下，一项项核对旧案编号和今夜送来的招领记录。屋里的灯泡轻轻嗡响，纸页边角被潮气泡得发软，每翻一页都像在把旧账重新摊回自己眼前。\n\n"
                    "沈雾把旧表翻到背面，指腹停在那道熟悉的划痕上，像在确认半年前留下的伤口并没有自己愈合。她没有立刻去碰秒针，只先把呼吸压平，免得手指发抖把那点冷硬的金属错认成别的东西。\n\n"
                    "窗外的潮声一阵紧过一阵，拍着铁皮和旧广告牌，把本该熄掉的夜色敲得发空。她抬头看见玻璃里自己的影子，终于承认这条线今晚如果不追，往后只会越来越像借口。\n\n"
                    "她把钥匙收进口袋，又把登记簿按回柜台最里侧，确认锁扣和编号都没有乱。等她推门出去时，旧表已经贴在掌心发凉，路尽头那条通往旧影院的小街像一根被潮雾浸透的线，正等她亲手拽紧。"
                )

            def reset_session(self, session_id: str) -> None:
                return

        client = ChapterClient()
        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"pipeline-dedupe-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            pipeline = NovelPipeline(client, temp_dir, max_rewrites=0, max_final_polish_rounds=0)
            spec = ProjectSpec(
                title="测试小说",
                genre="都市奇谭",
                audience="中文读者",
                tone="克制",
                premise="旧物会牵出旧案。",
                theme="面对过去",
                hook="旧表重新出现。",
                setting="海边旧城",
                protagonist="沈雾",
                outline_hint="完整闭环",
                world_hint="设定服务剧情",
                ending_mode="standalone",
                pov="第三人称有限视角",
                target_total_chars=1200,
                target_chars_per_chapter=600,
                chapter_count=1,
                volume_count=1,
                chapters_per_volume=1,
                style_examples=["克制"],
                must_include=["主线推进"],
                avoid=["最后一段另起新案"],
                character_seeds=[CharacterSeed(name="沈雾", role="主角")],
            )
            bible = WorldBible(
                title="测试小说",
                logline="旧表逼主角回到旧案。",
                setting_summary="海边旧城。",
                core_conflict="沈雾必须决定是否再次进入旧案。",
                theme_statement="面对过去需要代价。",
                narrative_voice=["克制"],
                world_rules=["旧物会保留残留信息。"],
                chapter_guardrails=["每章都要推进主线。"],
                ending_contract=["主线闭环。"],
                major_threads=["旧案"],
                characters=[],
            )
            chapter = ChapterOutlineItem(
                index=1,
                volume_index=1,
                title="旧表回来了",
                purpose="推动主角行动",
                conflict="她不想再碰旧案",
                beat_summary="旧表再次出现，逼她做决定。",
                ending_note="她去旧影院。",
                pov="第三人称有限视角",
                closing_mode="chapter_hook",
                must_payoff=["旧表"],
            )
            plan = ChapterPlan(
                chapter_index=1,
                chapter_title="旧表回来了",
                purpose="推动主角行动",
                continuity_targets=["旧案线索推进"],
                opening_image="招领室里的旧表",
                closing_image="通往旧影院的路",
                closing_mode="chapter_hook",
                scenes=[
                    SceneCard(
                        scene_index=1,
                        location="招领室",
                        goal="确认旧表来自旧案",
                        conflict="主角不想再碰",
                        turn="决定前往旧影院",
                        must_include=["旧表"],
                    )
                ],
            )

            result = pipeline._generate_chapter(spec, bible, chapter, plan, ContinuityState())

            self.assertTrue(result.local_quality.passed)
            self.assertEqual(result.local_quality.metrics["duplicate_paragraphs"], 0)
            self.assertEqual(result.review.passed, True)
            self.assertEqual(result.draft.count("沈雾把旧表翻到背面"), 1)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_pipeline_accepts_sparse_input_and_finishes_with_closure(self) -> None:
        project_input = ProjectInput(
            title="测试小说",
            structure_mode="legacy",
            target_total_chars=900,
            target_chars_per_chapter=450,
            chapter_count=2,
            volume_count=1,
            chapter_char_tolerance=0.25,
        )
        client = StubClient(
            json_payloads=[
                {
                    "title": "测试小说",
                    "genre": "都市奇谭",
                    "audience": "中文读者",
                    "tone": "克制",
                    "structure_mode": "legacy",
                    "target_total_chars": 900,
                    "target_chars_per_chapter": 450,
                    "chapter_count": 2,
                    "volume_count": 1,
                    "volume_chapter_targets": [2],
                    "chapter_char_tolerance": 0.25,
                    "premise": "招领员能看见遗失物里的回忆。",
                    "theme": "选择",
                    "hook": "她离弟弟失踪案更近一步。",
                    "setting": "海雾城市",
                    "protagonist": "沈雾",
                    "outline_hint": "完整闭环，不留半截。",
                    "world_hint": "奇异能力只作为情节杠杆。",
                    "style_examples": ["潮湿", "细节推动"],
                    "must_include": ["完整结局"],
                    "avoid": ["最后一段另起新案"],
                    "character_seeds": [
                        {"name": "沈雾", "role": "主角", "goal": "查弟弟下落", "conflict": "真相会击穿她的秩序", "notes": "克制寡言"},
                        {"name": "周既明", "role": "协助者", "goal": "保住项目", "conflict": "利益与良知冲突", "notes": "嘴硬"}
                    ],
                },
                {
                    "notes": [
                        {
                            "agent": "world_architect",
                            "focus": "能力与现实边界",
                            "must_hold": ["奇异能力只作为剧情杠杆", "旧城更新冲突必须落地"],
                            "risks": ["设定炫技盖过人物"],
                            "opportunities": ["失物记忆可反向推动真相"],
                            "summary": "世界规则要克制。"
                        },
                        {
                            "agent": "character_director",
                            "focus": "人物弧线",
                            "must_hold": ["沈雾必须从回避走向面对", "周既明不能脸谱化"],
                            "risks": ["主角只查案不变化"],
                            "opportunities": ["搭档关系可以制造张力"],
                            "summary": "人物要带动主线。"
                        },
                        {
                            "agent": "plot_architect",
                            "focus": "结构推进",
                            "must_hold": ["最终章闭环", "每章都推进真相"],
                            "risks": ["结尾另起新案"],
                            "opportunities": ["旧表和旧堤岸形成首尾呼应"],
                            "summary": "结构必须强推进。"
                        }
                    ],
                    "shared_contract": ["主线闭环", "人物要变化", "连续性不能打架", "文风克制"],
                    "global_risks": ["结尾偷换成下一案"]
                },
                {
                    "title": "测试小说",
                    "logline": "一句话卖点",
                    "setting_summary": "海雾城市里，失物带着未散的记忆。",
                    "core_conflict": "沈雾必须在追查真相和保护幸存者之间做选择。",
                    "theme_statement": "勇气来自重新选择。",
                    "narrative_voice": ["冷静", "具体"],
                    "world_rules": ["旧物会保留失主最后一分钟的感知。"],
                    "chapter_guardrails": ["每章都要推进真相。"],
                    "ending_contract": ["最终章必须解决弟弟失踪主线。"],
                    "major_threads": ["弟弟失踪案", "旧城更新冲突"],
                    "characters": [
                        {
                            "name": "沈雾",
                            "role": "主角",
                            "goal": "查弟弟下落",
                            "fear": "再次失去家人",
                            "contradiction": "想靠近真相又怕真相太重",
                            "arc": "从回避过去到主动面对",
                            "public_image": "冷淡",
                            "private_truth": "内心一直自责",
                            "speaking_style": "简短克制",
                            "signature_image": "潮湿玻璃后的影子",
                            "relationship_tensions": ["与周既明互相试探"],
                            "do_not_break": ["不能突然外放成话痨"],
                        }
                    ],
                },
                {
                    "title": "测试小说",
                    "one_line_summary": "沈雾从一块旧表找到真相入口。",
                    "act_structure": ["开端", "推进", "收束"],
                    "volumes": [
                        {
                            "index": 1,
                            "title": "旧表与堤岸",
                            "role": "推进主线",
                            "central_question": "沈舟到底为何失踪",
                            "escalation": "线索越来越逼近旧城改造黑幕",
                            "emotional_shift": "沈雾从逃避走向面对",
                            "must_payoff": ["弟弟失踪真相"],
                        }
                    ],
                },
                {
                    "volume_index": 1,
                    "title": "旧表与堤岸",
                    "goal": "查明沈舟失踪真相",
                    "climax": "沈雾确认弟弟并非主动离开",
                    "carry_over_threads": ["弟弟失踪案"],
                    "chapter_targets": [
                        {
                            "index": 1,
                            "title": "旧表响了一下",
                            "purpose": "建立能力并抛出线索",
                            "conflict": "她不愿碰弟弟相关线索",
                            "beat_summary": "沈雾在招领室收到一块旧表，触发回忆，看见弟弟失踪前经过旧影院。",
                            "ending_note": "她决定夜里去旧影院。",
                            "pov": "第三人称有限视角",
                            "must_payoff": ["旧表", "旧影院"],
                        },
                        {
                            "index": 2,
                            "title": "堤岸把真相吐出来",
                            "purpose": "完成主线真相与人物选择",
                            "conflict": "她必须接受自己和弟弟最后一夜的真正关系",
                            "beat_summary": "沈雾在海边旧堤岸确认弟弟失踪真相，并正式把证据交回现实流程。",
                            "ending_note": "主线闭环，沈雾选择继续守住招领处。",
                            "pov": "第三人称有限视角",
                            "must_payoff": ["弟弟失踪真相", "主角最终选择"],
                        },
                    ],
                },
                {
                    "chapter_index": 1,
                    "chapter_title": "旧表响了一下",
                    "purpose": "建立主角能力并抛出线索",
                    "continuity_targets": ["引出弟弟失踪案"],
                    "opening_image": "潮湿的招领室",
                    "closing_image": "旧影院门口亮起一盏灯",
                    "closing_mode": "chapter_hook",
                    "scenes": [
                        {
                            "scene_index": 1,
                            "location": "招领室",
                            "goal": "辨认旧表主人",
                            "conflict": "旧表带来弟弟相关记忆",
                            "turn": "她决定不再逃避",
                            "must_include": ["海雾", "旧表", "弟弟"],
                        }
                    ],
                },
                {
                    "notes": [
                        {
                            "agent": "continuity_guard",
                            "must_land": ["引出弟弟失踪案", "旧表与旧影院建立硬连接"],
                            "risks": ["只写氛围不写决定"],
                            "summary": "第一章必须让主角真正迈出去。"
                        },
                        {
                            "agent": "drama_editor",
                            "must_land": ["主角被迫做决定", "章末形成夜探旧影院的牵引"],
                            "risks": ["冲突不落地"],
                            "summary": "戏剧动作要明确。"
                        },
                        {
                            "agent": "style_guard",
                            "must_land": ["保持潮湿克制", "不要解释能力机制"],
                            "risks": ["写成说明文"],
                            "summary": "文风要收着写。"
                        }
                    ],
                    "shared_mandates": ["用动作推进", "章末必须去旧影院"],
                    "blocking_issues": ["不能停在知道线索却不行动"]
                },
                {
                    "passed": False,
                    "score": 55,
                    "strengths": ["有氛围"],
                    "issues": ["正文过短", "冲突没有落地"],
                    "required_fixes": ["补足场景动作和决断", "让旧影院线索更具体"],
                    "short_summary": "沈雾碰到旧表，却还没有真正迈出去。",
                    "chapter_fixes": [],
                },
                {
                    "passed": True,
                    "score": 88,
                    "strengths": ["场景完整", "冲突成立"],
                    "issues": [],
                    "required_fixes": [],
                    "short_summary": "沈雾从旧表的回忆里看见弟弟最后经过旧影院，终于决定当夜过去。",
                    "chapter_fixes": [],
                },
                {
                    "chapter_index": 1,
                    "chapter_summary": "沈雾从旧表回忆里确认弟弟与旧影院有关，决定连夜追查。",
                    "new_threads": ["旧影院线索"],
                    "resolved_threads": [],
                    "timeline_events": ["沈雾接触旧表并看见回忆", "她决定夜查旧影院"],
                    "character_states": [
                        {
                            "name": "沈雾",
                            "current_goal": "去旧影院",
                            "emotional_state": "被迫重新面对过去",
                            "relationship_shift": "与弟弟旧案重新绑在一起",
                            "risk": "旧伤口被再次掀开",
                            "unresolved": "沈舟到底去了哪里"
                        }
                    ],
                    "next_chapter_targets": ["旧影院", "弟弟失踪真相"],
                    "must_remember": ["旧表触发了与弟弟相关的回忆"],
                },
                {
                    "chapter_index": 2,
                    "chapter_title": "堤岸把真相吐出来",
                    "purpose": "完成主线闭环",
                    "continuity_targets": ["兑现弟弟失踪真相", "完成主角选择"],
                    "opening_image": "风雨里的旧堤岸",
                    "closing_image": "重新亮起的招领室灯",
                    "closing_mode": "book_closure",
                    "scenes": [
                        {
                            "scene_index": 1,
                            "location": "旧堤岸",
                            "goal": "找到铁盒与真相",
                            "conflict": "真相会逼她承认自己的误解",
                            "turn": "她确认弟弟是为救人而失踪",
                            "must_include": ["铁盒", "旧堤岸", "选择"],
                        }
                    ],
                },
                {
                    "notes": [
                        {
                            "agent": "continuity_guard",
                            "must_land": ["兑现弟弟失踪真相", "回收旧影院与旧表线索"],
                            "risks": ["解释不完整"],
                            "summary": "所有线索都要回收。"
                        },
                        {
                            "agent": "drama_editor",
                            "must_land": ["真相揭晓", "主角做最终选择"],
                            "risks": ["只交代事实没有情绪落点"],
                            "summary": "闭环必须有人物决断。"
                        },
                        {
                            "agent": "style_guard",
                            "must_land": ["结尾留余韵但不能留半截"],
                            "risks": ["最后另起新案"],
                            "summary": "结尾要稳收。"
                        }
                    ],
                    "shared_mandates": ["主线闭环", "结尾回到招领处现实流程"],
                    "blocking_issues": ["不能只揭谜不落地"]
                },
                {
                    "passed": True,
                    "score": 91,
                    "strengths": ["完整闭环", "情绪成立"],
                    "issues": [],
                    "required_fixes": [],
                    "short_summary": "沈雾确认弟弟为救人而失踪，并将证物正式移交，主线完成收束。",
                    "chapter_fixes": [],
                },
                {
                    "chapter_index": 2,
                    "chapter_summary": "沈雾在旧堤岸确认弟弟为救人而失踪，并把铁盒登记移交，决定继续守住招领处。",
                    "new_threads": [],
                    "resolved_threads": ["弟弟失踪案", "旧影院线索"],
                    "timeline_events": ["沈雾确认弟弟失踪真相", "她把铁盒正式移交留档"],
                    "character_states": [
                        {
                            "name": "沈雾",
                            "current_goal": "继续守住招领处",
                            "emotional_state": "悲伤但稳定",
                            "relationship_shift": "与弟弟的告别终于完成",
                            "risk": "仍要面对现实余波",
                            "unresolved": "没有主线悬案残留"
                        }
                    ],
                    "next_chapter_targets": [],
                    "must_remember": ["主线已经闭环，结尾不能再另起新案"],
                },
                {
                    "passed": True,
                    "score": 93,
                    "strengths": ["故事完整", "结尾闭环"],
                    "issues": [],
                    "required_fixes": [],
                    "short_summary": "整部作品完成了主线收束和人物弧线闭合。",
                    "chapter_fixes": [],
                },
                {
                    "factual_summary": (
                        "沈雾在海雾城市的招领处收到一块会回放旧记忆的怀表，被迫重新面对弟弟沈川的失踪旧案。"
                        "她顺着怀表里的碎片回忆追到即将拆除的旧影院，又从后场的名单、堤岸上的铁盒和残存证物里，一步步拼出当年那场事故的真实经过。"
                        "随着真相逼近，沈雾不仅要确认弟弟最后去过哪里，更要承认自己这些年一直误解了他的离开。"
                        "最终她在旧堤岸确认，沈川是为了先救落海的孩子才被暗流卷走。"
                        "她没有再把真相困在私人执念里，而是带着证据回到现实流程，补录、归档、移交，让失踪案真正落档，也让自己完成告别。"
                    ),
                    "marketing_blurb": (
                        "一块停走多年的旧表，让招领员沈雾重新看见弟弟失踪前最后一晚。"
                        "旧影院、旧堤岸、被海雾吞没的证物和迟到了多年的真相一起逼近。"
                        "她要找到的，不只是答案，也是终于能继续活下去的那一步。"
                    ),
                },
            ],
            text_payloads=[
                "TODO 这里略去关键剧情。",
                (
                    "海雾从旧窗缝里挤进来时，沈雾刚把那只旧表从失物篮里拎出来。黄铜表壳冰得扎手，像刚从海里捞起。她先看编号，又看背面的旧划痕，越看越确定这东西不该出现在今天的招领处。\n\n"
                    "她把表盖掀开的一瞬，秒针猛地跳了两下。耳边先是电车刹车的尖响，接着是一声熟得让她肩背发紧的笑。那是弟弟沈川十七岁那年的笑，轻，快，像随时会被风吹散。她听见雨点打在旧影院铁棚上的空响，也看见他把什么东西往怀里一塞，转身钻进海报后的偏门。\n\n"
                    "回忆不是画面，是一阵潮湿的眩晕。她看见旧影院门口褪色的海报，看见沈川回头朝谁招手，又忽然被人群和雾一起吞没。最后留下的，只有影院屋檐下那盏坏了半年的绿灯，竟在雨里亮了一下。等她再去追那盏灯，眼前只剩一块歪斜的告示牌，上面写着后场通道暂停使用。\n\n"
                    "沈雾猛地合上表盖，掌心全是冷汗。她原本以为自己早就学会把弟弟的名字锁进抽屉，可旧表像一把钝刀，把那道缝又撬开。她把登记簿推回柜台最里侧，抬头时声音比海风还低：“旧影院那边，现在还能进去吗？”老周先看她，又看那只旧表，半天才说，拆迁队白天围上了铁皮，可夜里值守松，若真要去，只能走堤岸后面的旧闸道。\n\n"
                    "沈雾没立刻起身。她先把今天的失物登记补齐，把值班钥匙、手电和旧表一起装进防水袋，又把弟弟当年留下的那页笔记从抽屉最下层翻出来。笔记边角早就起毛，唯独“绿灯亮时，别走正门”这几个字还很清楚。她盯着那行字看了很久，终于承认自己这些年不是没查过，而是每次走到旧影院附近都会退回去。\n\n"
                    "值夜的老周又劝了一句，说拆迁队前两天才围上铁皮，今晚再不去，明天未必还有路。沈雾把旧表塞进外套口袋，关掉屋里最后一盏灯。她知道自己不是去找一个失主，她是去追那盏迟到了半年的绿灯，也是去追那个她一直不敢确认的答案：沈川最后一晚，到底为什么独自进了旧影院。"
                ),
                (
                    "旧堤岸上的风像刀一样横着刮过来，铁盒壳面全是盐霜。沈雾把它放在膝头，手指只碰到那块停走的表，记忆就像暗潮一样兜头压了下来。她看见那晚的岸灯忽明忽暗，看见沈川把一叠票据塞进铁盒，又转头去扶那个跌坐在堤边的小孩。\n\n"
                    "她终于看清，那晚沈川不是在逃，也不是在抛下她。他把铁盒掷回岸上，是因为堤岸塌下去时有个孩子先落了海。他跳下去救人，最后被废弃排水道的暗流卷走。那孩子后来被船工拖上来，只剩一只鞋留在原地，而沈川最后一次回头，是朝岸上那只铁盒看了一眼，像是怕证物也跟着被海水卷走。\n\n"
                    "沈雾站在风里很久，直到耳边的海浪重新变回现实的声音。她没有再把铁盒抱回自己怀里，而是先把里面那页名单、旧影院票根和码头值班条一件件拍照留档，再按顺序重新装回去。她知道这一次不能只带着真相回家哭一场就算结束，沈川拼命丢回岸上的东西，本来就是留给后来的人去交代清楚的。\n\n"
                    "回到招领处以后，她先补登记，再附证据说明，又联系辖区档案室和值班民警，把旧影院和堤岸两条线上的物证一起移交流程。许阿岚帮她核对编号时没有多问，只把空白页压平，提醒她把“失踪旧案补录”那一栏写完整。沈雾写到弟弟名字的时候手还是抖了一下，但这一次她没停笔。\n\n"
                    "灯重新亮起来时，许阿岚把空白登记簿推到她手边。沈雾写下编号，字很稳。她知道自己没有忘记弟弟，只是不再靠反复撕开伤口证明他存在。窗外旧电车叮地一响，雾还没散，可她终于能把门推开，继续接住后来人的遗失。那只旧表被她放回了玻璃柜最里面，旁边压着补录完成的回执，她知道从今以后，想起沈川时，先浮上来的不会再只有失踪两个字。"
                ),
            ],
        )

        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"pipeline-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            pipeline = NovelPipeline(client, temp_dir, max_rewrites=1, max_final_polish_rounds=0)
            summary = pipeline.run(project_input)

            self.assertTrue(summary.final_passed)
            self.assertEqual(summary.chapter_count, 2)
            self.assertEqual(summary.volume_count, 1)
            self.assertEqual(client.text_calls, 3)
            self.assertEqual(client.json_calls, 21)

            novel_text = (temp_dir / "novel.md").read_text(encoding="utf-8")
            plain_text = (temp_dir / "novel.txt").read_text(encoding="utf-8")
            book_summary = (temp_dir / "book-summary.md").read_text(encoding="utf-8")
            package_payload = json.loads((temp_dir / "data" / "book-package.json").read_text(encoding="utf-8"))
            self.assertIn("旧堤岸", novel_text)
            self.assertNotIn("终审摘要", novel_text)
            self.assertIn("继续接住后来人的遗失", novel_text)
            self.assertTrue(plain_text.startswith("测试小说"))
            self.assertIn("第1章 旧表响了一下", plain_text)
            self.assertIn("## 实际剧情简介", book_summary)
            self.assertIn("## 目录", book_summary)
            self.assertEqual(package_payload["chapter_count"], 2)
            self.assertIn("沈雾在海雾城市的招领处收到一块会回放旧记忆的怀表", package_payload["factual_summary"])
            self.assertLessEqual(len(package_payload["marketing_blurb"]), 200)
            delivery_manifest = json.loads((temp_dir / "delivery" / "delivery-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(delivery_manifest["title"], "测试小说")
            self.assertTrue((temp_dir / "delivery" / "table-of-contents.md").exists())
            self.assertTrue((temp_dir / "delivery" / "submission-guide.md").exists())
            self.assertEqual(len(list((temp_dir / "delivery" / "volumes").glob("volume-01-*.md"))), 1)
            self.assertEqual(len(list((temp_dir / "delivery" / "epub").glob("*.epub"))), 1)
            self.assertTrue(delivery_manifest["files"]["epub"].startswith("epub/"))
            self.assertTrue(delivery_manifest["files"]["epub"].endswith(".epub"))
            self.assertEqual(len(delivery_manifest["files"]["volumes"]), 1)
            self.assertTrue(delivery_manifest["files"]["volumes"][0].startswith("volumes/volume-01-"))
            run_summary = json.loads((temp_dir / "data" / "run-summary.json").read_text(encoding="utf-8"))
            self.assertEqual(run_summary["delivery_manifest_path"], "delivery/delivery-manifest.json")
            self.assertTrue((temp_dir / "data" / "story-room.json").exists())
            self.assertTrue((temp_dir / "state" / "chapter-01.room.json").exists())
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_pipeline_can_resume_from_saved_chapters(self) -> None:
        project_input = ProjectInput(
            title="恢复测试",
            structure_mode="legacy",
            target_total_chars=160,
            target_chars_per_chapter=80,
            chapter_count=2,
            volume_count=1,
        )
        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"pipeline-resume-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            partial_client = StubClient(
                json_payloads=[
                    {
                        "title": "恢复测试",
                        "genre": "都市奇谭",
                        "audience": "中文读者",
                        "tone": "克制",
                        "structure_mode": "legacy",
                        "target_total_chars": 160,
                        "target_chars_per_chapter": 80,
                        "chapter_count": 2,
                        "volume_count": 1,
                        "volume_chapter_targets": [2],
                        "premise": "旧物里残留着记忆。",
                        "theme": "选择",
                        "hook": "一块旧表把主角拖回旧案。",
                        "setting": "临海旧城",
                        "protagonist": "沈雾",
                        "outline_hint": "完整闭环。",
                        "world_hint": "设定服务剧情。",
                        "style_examples": ["潮湿", "克制"],
                        "must_include": ["结局闭环"],
                        "avoid": ["结尾另起新案"],
                        "character_seeds": [{"name": "沈雾", "role": "主角"}],
                    },
                    {
                        "notes": [
                            {
                                "agent": "world_architect",
                                "focus": "规则克制",
                                "must_hold": ["旧物能力服务剧情", "必须完整闭环"],
                                "risks": ["设定盖过人物"],
                                "opportunities": ["旧表可以串联真相"],
                                "summary": "世界观只做杠杆。"
                            },
                            {
                                "agent": "character_director",
                                "focus": "人物变化",
                                "must_hold": ["沈雾必须从回避到面对"],
                                "risks": ["人物只查案不成长"],
                                "opportunities": ["真相可以逼出决断"],
                                "summary": "人物弧线要落地。"
                            },
                            {
                                "agent": "plot_architect",
                                "focus": "结构闭环",
                                "must_hold": ["最后必须归档落地"],
                                "risks": ["结尾偷换成下一案"],
                                "opportunities": ["旧表首尾呼应"],
                                "summary": "结构必须完成回收。"
                            }
                        ],
                        "shared_contract": ["主线闭环", "人物有变化", "连续性不打架", "文风克制"],
                        "global_risks": ["结尾悬空"]
                    },
                    {
                        "title": "恢复测试",
                        "logline": "旧表牵出旧案。",
                        "setting_summary": "临海旧城",
                        "core_conflict": "沈雾要决定是否揭开旧案真相。",
                        "theme_statement": "人要为真相负责。",
                        "narrative_voice": ["克制"],
                        "world_rules": ["旧物会保留最后感知。"],
                        "chapter_guardrails": ["每章推进主线。"],
                        "ending_contract": ["必须闭环。"],
                        "major_threads": ["旧案"],
                        "characters": [
                            {
                                "name": "沈雾",
                                "role": "主角",
                                "goal": "查旧案",
                                "fear": "真相太重",
                                "contradiction": "想知道又不敢知道",
                                "arc": "从回避到面对",
                                "public_image": "冷淡",
                                "private_truth": "自责",
                                "speaking_style": "简短",
                                "signature_image": "潮湿玻璃",
                                "relationship_tensions": [],
                                "do_not_break": ["不能突然话痨"],
                            }
                        ],
                    },
                    {
                        "title": "恢复测试",
                        "one_line_summary": "沈雾顺着旧表找到真相。",
                        "act_structure": ["开端", "收束"],
                        "volumes": [
                            {
                                "index": 1,
                                "start_chapter": 1,
                                "end_chapter": 2,
                                "title": "旧表",
                                "role": "单卷闭环",
                                "central_question": "真相是什么",
                                "escalation": "线索逼近真相",
                                "emotional_shift": "从逃避到面对",
                                "must_payoff": ["真相"],
                            }
                        ],
                    },
                    {
                        "volume_index": 1,
                        "title": "旧表",
                        "goal": "找出真相",
                        "climax": "确认真相并归档",
                        "carry_over_threads": ["旧案"],
                        "chapter_targets": [
                            {
                                "index": 1,
                                "title": "表针跳了一下",
                                "purpose": "抛出线索",
                                "conflict": "她不想再碰旧案",
                                "beat_summary": "旧表触发记忆。",
                                "ending_note": "她决定追查。",
                                "pov": "第三人称有限视角",
                                "closing_mode": "chapter_hook",
                                "must_payoff": ["旧表"],
                            },
                            {
                                "index": 2,
                                "title": "归档",
                                "purpose": "完成闭环",
                                "conflict": "她必须接受真相",
                                "beat_summary": "她确认真相并归档。",
                                "ending_note": "主线闭环。",
                                "pov": "第三人称有限视角",
                                "closing_mode": "book_closure",
                                "must_payoff": ["真相"],
                            },
                        ],
                    },
                    {
                        "chapter_index": 1,
                        "chapter_title": "表针跳了一下",
                        "purpose": "抛出线索",
                        "continuity_targets": ["旧案"],
                        "opening_image": "招领室",
                        "closing_image": "旧码头",
                        "closing_mode": "chapter_hook",
                        "scenes": [
                            {
                                "scene_index": 1,
                                "location": "招领室",
                                "goal": "认出旧表",
                                "conflict": "旧案记忆压回来",
                                "turn": "决定追查",
                                "must_include": ["旧表"],
                            }
                        ],
                    },
                    {
                        "notes": [
                            {
                                "agent": "continuity_guard",
                                "must_land": ["旧表触发旧案", "主角做出追查决定"],
                                "risks": ["只写氛围不写行动"],
                                "summary": "第一章必须迈出去。"
                            },
                            {
                                "agent": "drama_editor",
                                "must_land": ["章末形成去旧码头的牵引"],
                                "risks": ["冲突不够硬"],
                                "summary": "要有明确决断。"
                            },
                            {
                                "agent": "style_guard",
                                "must_land": ["克制具体"],
                                "risks": ["写成解释"],
                                "summary": "文风要收住。"
                            }
                        ],
                        "shared_mandates": ["用动作推进", "章末必须行动"],
                        "blocking_issues": ["不能只是想一想"]
                    },
                    {
                        "passed": True,
                        "score": 88,
                        "strengths": ["完整"],
                        "issues": [],
                        "required_fixes": [],
                        "short_summary": "第一章合格。",
                        "chapter_fixes": [],
                    },
                    {
                        "chapter_index": 1,
                        "chapter_summary": "沈雾决定追查旧案。",
                        "new_threads": ["旧案"],
                        "resolved_threads": [],
                        "timeline_events": ["她决定追查"],
                        "character_states": [
                            {
                                "name": "沈雾",
                                "current_goal": "追查旧案",
                                "emotional_state": "不安",
                                "relationship_shift": "重新面对过去",
                                "risk": "旧伤口被揭开",
                                "unresolved": "真相未明"
                            }
                        ],
                        "next_chapter_targets": ["真相"],
                        "must_remember": ["不能烂尾"],
                    },
                ],
                text_payloads=[
                    (
                        "沈雾在招领室碰到旧表，记忆一下子倒灌回来。秒针猛地跳动，像有人隔着很多年敲了她一下。\n\n"
                        "她原本想把它重新塞回抽屉，可窗外的海风正把旧码头方向的铁皮吹得乱响。\n\n"
                        "柜台上的登记簿摊开着，墨迹还没干。她盯着那页空白，忽然意识到自己不能再假装什么都没发生。\n\n"
                        "她终于没有再躲，带着旧表离开招领室，沿着被潮气泡软的石阶朝旧码头走去。"
                    ),
                ],
            )

            with self.assertRaises(AssertionError):
                NovelPipeline(partial_client, temp_dir, max_rewrites=0, max_final_polish_rounds=0).run(project_input)

            resumed_client = StubClient(
                json_payloads=[
                    {
                        "chapter_index": 2,
                        "chapter_title": "归档",
                        "purpose": "完成闭环",
                        "continuity_targets": ["真相", "归档"],
                        "opening_image": "旧码头的风",
                        "closing_image": "重新亮起的灯",
                        "closing_mode": "book_closure",
                        "scenes": [
                            {
                                "scene_index": 1,
                                "location": "旧码头",
                                "goal": "确认真相",
                                "conflict": "她得接受弟弟真正的离开",
                                "turn": "带证据回去归档",
                                "must_include": ["真相", "归档"],
                            }
                        ],
                    },
                    {
                        "notes": [
                            {
                                "agent": "continuity_guard",
                                "must_land": ["回收旧案", "让证据进入现实流程"],
                                "risks": ["真相说清了但没有落档"],
                                "summary": "第二章必须完成现实落地。"
                            },
                            {
                                "agent": "drama_editor",
                                "must_land": ["人物完成告别"],
                                "risks": ["只有说明没有情绪落点"],
                                "summary": "闭环要有情绪落点。"
                            },
                            {
                                "agent": "style_guard",
                                "must_land": ["结尾收稳，不另起新案"],
                                "risks": ["尾声发散"],
                                "summary": "结尾留余韵即可。"
                            }
                        ],
                        "shared_mandates": ["主线闭环", "证据归档", "人物继续生活"],
                        "blocking_issues": ["不能只停在知道真相"]
                    },
                    {
                        "passed": True,
                        "score": 91,
                        "strengths": ["闭环"],
                        "issues": [],
                        "required_fixes": [],
                        "short_summary": "第二章合格。",
                        "chapter_fixes": [],
                    },
                    {
                        "chapter_index": 2,
                        "chapter_summary": "沈雾确认真相并完成归档。",
                        "new_threads": [],
                        "resolved_threads": ["旧案"],
                        "timeline_events": ["她完成归档"],
                        "character_states": [
                            {
                                "name": "沈雾",
                                "current_goal": "继续生活",
                                "emotional_state": "平静",
                                "relationship_shift": "完成告别",
                                "risk": "仍要面对余波",
                                "unresolved": "没有主线悬案"
                            }
                        ],
                        "next_chapter_targets": [],
                        "must_remember": ["主线已经闭环"],
                    },
                    {
                        "passed": True,
                        "score": 92,
                        "strengths": ["完整闭环"],
                        "issues": [],
                        "required_fixes": [],
                        "short_summary": "整本完成闭环。",
                        "chapter_fixes": [],
                    },
                ],
                text_payloads=[
                    (
                        "旧码头的风很冷。沈雾在那里确认了真相，也终于明白自己这些年一直误会了那个人。\n\n"
                        "潮水拍在木桩上，声音空而稳，像替一个迟到太久的答案慢慢落印。\n\n"
                        "她把找到的证据带回招领处，按登记流程补录归档，一项一项写清。\n\n"
                        "灯重新亮起来时，她没有再靠反复撕开伤口证明谁存在，只是把门推开，让生活继续往前。"
                    ),
                ],
            )

            summary = NovelPipeline(
                resumed_client,
                temp_dir,
                max_rewrites=0,
                max_final_polish_rounds=0,
                resume=True,
            ).run(project_input)

            self.assertTrue(summary.final_passed)
            self.assertEqual(summary.chapter_count, 2)
            self.assertEqual(resumed_client.text_calls, 1)
            self.assertEqual(resumed_client.json_calls, 7)

            novel_text = (temp_dir / "novel.md").read_text(encoding="utf-8")
            self.assertIn("补录归档", novel_text)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_resume_returns_existing_delivery_for_completed_run(self) -> None:
        client = StubClient([], [])
        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"resume-completed-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            spec = ProjectSpec(
                title="已完结测试",
                genre="都市悬疑",
                audience="中文读者",
                tone="克制",
                premise="旧账被重新翻出。",
                theme="承担代价",
                hook="一页旧档改变了去向。",
                setting="海边旧城",
                protagonist="沈雾",
                outline_hint="完整闭环",
                world_hint="设定服务剧情",
                ending_mode="standalone",
                pov="第三人称有限视角",
                target_total_chars=4000,
                target_chars_per_chapter=2000,
                chapter_count=2,
                volume_count=1,
                chapters_per_volume=2,
                style_examples=["克制"],
                must_include=["证据链"],
                avoid=["假钩子"],
                character_seeds=[CharacterSeed(name="沈雾", role="主角")],
            )
            project_input = ProjectInput(
                title="已完结测试",
                target_total_chars=4000,
                target_chars_per_chapter=2000,
                chapter_count=2,
                volume_count=1,
            )
            store = NovelPipeline(client, temp_dir, resume=True).store
            store.write_json("data/project-input.json", project_input)
            store.write_json("data/project-spec.json", spec)
            store.write_text("novel.md", "# 已完结测试\n\n正文")
            store.write_text("novel.txt", "正文")
            store.write_json(
                "data/final-review.json",
                FinalReview(
                    passed=True,
                    score=94,
                    strengths=["闭环完成。"],
                    issues=[],
                    required_fixes=[],
                    short_summary="主线闭环，已成书。",
                    chapter_fixes=[],
                ),
            )
            store.write_json(
                "data/run-summary.json",
                {
                    "title": "已完结测试",
                    "chapter_count": 2,
                    "volume_count": 1,
                    "total_chars": 4321,
                    "final_score": 94,
                    "final_passed": True,
                    "final_summary": "主线闭环，已成书。",
                },
            )

            summary = NovelPipeline(client, temp_dir, resume=True).run(project_input)

            self.assertTrue(summary.final_passed)
            self.assertEqual(summary.chapter_count, 2)
            self.assertEqual(summary.total_chars, 4321)
            self.assertEqual(client.json_calls, 0)
            self.assertEqual(client.text_calls, 0)
            progress = json.loads((temp_dir / "data" / "progress.json").read_text(encoding="utf-8"))
            self.assertEqual(progress["step"], "completed")
            self.assertIn("直接返回现有交付结果", progress["message"])
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_resume_scrubs_incomplete_chapter_and_rolls_back_to_last_complete(self) -> None:
        client = StubClient([], [])
        temp_dir = Path.cwd() / "runs" / "test-artifacts" / f"resume-scrub-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            pipeline = NovelPipeline(client, temp_dir, resume=True)
            spec = ProjectSpec(
                title="测试小说",
                genre="都市悬疑",
                audience="中文读者",
                tone="克制",
                premise="旧物牵出旧账。",
                theme="承担代价",
                hook="一份名单会改写真相。",
                setting="海边旧城",
                protagonist="沈雾",
                outline_hint="完整闭环",
                world_hint="设定服务剧情",
                ending_mode="standalone",
                pov="第三人称有限视角",
                target_total_chars=4000,
                target_chars_per_chapter=2000,
                chapter_count=2,
                volume_count=1,
                chapters_per_volume=2,
                style_examples=["克制"],
                must_include=["证据链"],
                avoid=["假钩子"],
                character_seeds=[CharacterSeed(name="沈雾", role="主角")],
            )
            bible = WorldBible(
                title="测试小说",
                logline="一句话卖点",
                setting_summary="设定摘要",
                core_conflict="核心冲突",
                theme_statement="主题表达",
                narrative_voice=["克制"],
                world_rules=["规则一"],
                chapter_guardrails=["每章推进主线"],
                ending_contract=["闭环"],
                major_threads=["名单线"],
                characters=[],
            )
            chapter_1 = ChapterOutlineItem(1, 1, "第一章", "起线", "名单出现", "发现名单", "继续追", "第三人称有限视角", "chapter_hook", ["名单"])
            chapter_2 = ChapterOutlineItem(2, 1, "第二章", "推进", "证据会丢", "追回残页", "卷末回收", "第三人称有限视角", "chapter_hook", ["残页"])
            book_outline = BookOutline(
                title="测试小说",
                one_line_summary="一句话简介",
                act_structure=["开端", "收束"],
                volumes=[VolumeBlueprint(1, 1, 2, "第一卷", "推进主线", "名单去哪了", "局势升级", "从回避到行动", ["名单"])],
            )
            volume_outline = VolumeOutline(
                volume_index=1,
                title="第一卷",
                goal="推进名单线",
                climax="名单到手",
                carry_over_threads=["名单线"],
                chapter_targets=[chapter_1, chapter_2],
            )
            plan_1 = ChapterPlan(1, "第一章", "起线", ["名单"], "开场", "结尾", "chapter_hook", [])
            review_1 = ReviewFeedback(True, 90, [], [], [], "通过。")
            local_1 = LocalQualityReport(True, 91, [], [], "通过。", {})
            continuity_1 = ContinuityUpdate(1, "第一章摘要", ["名单线"], [], ["事件1"], [], ["目标1"], ["记住1"])

            pipeline.store.write_json("volumes/volume-01.outline.json", volume_outline)
            pipeline.store.write_json("plans/chapter-01.plan.json", plan_1)
            pipeline.store.write_text("chapters/chapter-01.md", "第一章完整正文。")
            pipeline.store.write_json("reviews/chapter-01.review.json", {"model": review_1, "local": local_1, "attempts": 1})
            pipeline.store.write_json("state/chapter-01.continuity.json", continuity_1)
            pipeline.store.write_json("state/chapter-01.memory.json", LongRangeMemoryUpdate(chapter_index=1))

            pipeline.store.write_json("plans/chapter-02.plan.json", ChapterPlan(2, "第二章", "推进", ["残页"], "开场", "结尾", "chapter_hook", []))
            pipeline.store.write_text("chapters/chapter-02.md", "第二章半成品。")
            pipeline.store.write_json("state/chapter-02.room.json", {"shared_mandates": ["半成品"]})

            completed, continuity, volume_outlines = pipeline._load_resume_state(spec, bible, book_outline)

            self.assertEqual(sorted(completed), [1])
            self.assertEqual(continuity.last_chapter_index, 1)
            self.assertIn(1, volume_outlines)
            self.assertFalse((temp_dir / "chapters" / "chapter-02.md").exists())
            self.assertFalse((temp_dir / "plans" / "chapter-02.plan.json").exists())
            self.assertFalse((temp_dir / "state" / "chapter-02.room.json").exists())
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
