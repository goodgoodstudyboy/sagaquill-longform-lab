from __future__ import annotations

import math
from typing import Any

from .models import (
    BookOutline,
    BreakthroughRequirement,
    CausalityEdge,
    ChapterOutlineItem,
    ChapterPlan,
    CharacterProfile,
    CharacterState,
    CharacterVoiceCard,
    ContinuityUpdate,
    EnemyLadderBand,
    LocalQualityReport,
    LogicAuditReport,
    LongRangeMemoryUpdate,
    PowerSystemBible,
    ProgressionLedgerItem,
    ProgressionMilestone,
    ProjectSpec,
    PromiseLedgerItem,
    RealmTier,
    ResourceAxis,
    ReviewFeedback,
    SceneCard,
    StyleBible,
    StylePassage,
    VolumeBlueprint,
    VolumeOutline,
    WorldBible,
)
from .normalize import best_text, character_seed_list, string_list
from .projectio import default_pov_for_language, is_chinese_output_language, localized_pov, normalized_output_language


def _project_language_defaults(language: object) -> dict[str, str]:
    if is_chinese_output_language(language):
        return {
            "genre": "中文强剧情小说",
            "audience": "中文读者",
            "tone": "紧凑、具体、可读",
            "pov": default_pov_for_language(language),
        }
    return {
        "genre": "high-concept commercial fiction",
        "audience": "online fiction readers",
        "tone": "fast, concrete, readable",
        "pov": default_pov_for_language(language),
    }


def _chapter_fix_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    fixes: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        chapter_index = item.get("chapter_index")
        instruction = best_text(item.get("instruction"), "")
        if chapter_index is None or not instruction:
            continue
        fixes.append({"chapter_index": int(chapter_index), "instruction": instruction})
    return fixes


def _character_from_dict(payload: dict[str, Any]) -> CharacterProfile:
    return CharacterProfile(
        name=best_text(payload.get("name"), ""),
        role=best_text(payload.get("role"), ""),
        goal=best_text(payload.get("goal"), ""),
        fear=best_text(payload.get("fear"), ""),
        contradiction=best_text(payload.get("contradiction"), ""),
        arc=best_text(payload.get("arc"), ""),
        public_image=best_text(payload.get("public_image"), ""),
        private_truth=best_text(payload.get("private_truth"), ""),
        speaking_style=best_text(payload.get("speaking_style"), ""),
        signature_image=best_text(payload.get("signature_image"), ""),
        relationship_tensions=string_list(payload.get("relationship_tensions")),
        do_not_break=string_list(payload.get("do_not_break")),
    )


def _normalized_chapter_char_tolerance(value: float | None) -> float:
    if value is None:
        return 0.25
    try:
        tolerance = float(value)
    except (TypeError, ValueError):
        return 0.25
    return max(0.05, min(0.4, tolerance))


def _normalized_volume_chapter_targets(
    payload: list[int] | tuple[int, ...] | None,
    *,
    chapter_count: int,
    volume_count: int,
) -> list[int]:
    if not payload:
        return []
    try:
        targets = [max(int(item), 1) for item in payload]
    except (TypeError, ValueError):
        return []
    if len(targets) != volume_count:
        return []
    if sum(targets) != chapter_count:
        total = sum(targets) or volume_count
        raw = [(item / total) * chapter_count for item in targets]
        floors = [int(math.floor(item)) for item in raw]
        adjusted = [max(1, item) for item in floors]
        delta = chapter_count - sum(adjusted)
        order = sorted(range(volume_count), key=lambda index: raw[index] - math.floor(raw[index]), reverse=True)
        for index in order[:max(delta, 0)]:
            adjusted[index] += 1
        targets = adjusted
    return targets


def _project_spec_from_dict(payload: dict[str, Any]) -> ProjectSpec:
    chapter_count = int(payload.get("chapter_count", 1) or 1)
    volume_count = int(payload.get("volume_count", 1) or 1)
    chapters_per_volume = int(payload.get("chapters_per_volume", math.ceil(chapter_count / max(volume_count, 1))) or 1)
    output_language = normalized_output_language(payload.get("output_language"))
    defaults = _project_language_defaults(output_language)
    volume_chapter_targets = _normalized_volume_chapter_targets(
        payload.get("volume_chapter_targets"),
        chapter_count=chapter_count,
        volume_count=volume_count,
    )
    return ProjectSpec(
        title=best_text(payload.get("title"), ""),
        output_language=output_language,
        genre=best_text(payload.get("genre"), defaults["genre"]),
        audience=best_text(payload.get("audience"), defaults["audience"]),
        tone=best_text(payload.get("tone"), defaults["tone"]),
        premise=best_text(payload.get("premise"), ""),
        theme=best_text(payload.get("theme"), ""),
        hook=best_text(payload.get("hook"), ""),
        setting=best_text(payload.get("setting"), ""),
        protagonist=best_text(payload.get("protagonist"), ""),
        outline_hint=best_text(payload.get("outline_hint"), ""),
        world_hint=best_text(payload.get("world_hint"), ""),
        ending_mode=best_text(payload.get("ending_mode"), "standalone"),
        pov=localized_pov(payload.get("pov"), output_language),
        target_total_chars=int(payload.get("target_total_chars", 0) or 0),
        target_chars_per_chapter=int(payload.get("target_chars_per_chapter", 0) or 0),
        chapter_count=chapter_count,
        volume_count=volume_count,
        chapters_per_volume=chapters_per_volume,
        volume_chapter_targets=volume_chapter_targets,
        chapter_char_tolerance=_normalized_chapter_char_tolerance(payload.get("chapter_char_tolerance")),
        structure_mode=best_text(payload.get("structure_mode"), "legacy"),
        market_profile=best_text(payload.get("market_profile"), "qidian_longform"),
        progression_mode=best_text(payload.get("progression_mode"), "soft_progression"),
        progression_flavor=best_text(payload.get("progression_flavor"), ""),
        progression_pacing=best_text(payload.get("progression_pacing"), "steady"),
        power_system_hint=best_text(payload.get("power_system_hint"), ""),
        style_examples=string_list(payload.get("style_examples")),
        must_include=string_list(payload.get("must_include")),
        avoid=string_list(payload.get("avoid")),
        character_seeds=character_seed_list(payload.get("character_seeds"), allow_strings=True),
        seed=int(payload["seed"]) if payload.get("seed") is not None else None,
    )


def _breakthrough_requirement_from_dict(payload: dict[str, Any]) -> BreakthroughRequirement:
    return BreakthroughRequirement(
        kind=best_text(payload.get("kind"), ""),
        label=best_text(payload.get("label"), ""),
        details=best_text(payload.get("details"), ""),
        mandatory=bool(payload.get("mandatory", True)),
    )


def _realm_tier_from_dict(payload: dict[str, Any]) -> RealmTier:
    return RealmTier(
        rank=int(payload.get("rank", 0) or 0),
        name=best_text(payload.get("name"), ""),
        summary=best_text(payload.get("summary"), ""),
        signature_gains=string_list(payload.get("signature_gains")),
        bottlenecks=string_list(payload.get("bottlenecks")),
        typical_resources=string_list(payload.get("typical_resources")),
        danger_band=best_text(payload.get("danger_band"), ""),
        breakthrough_requirements=[
            _breakthrough_requirement_from_dict(item)
            for item in payload.get("breakthrough_requirements", [])
            if isinstance(item, dict)
        ],
    )


def _resource_axis_from_dict(payload: dict[str, Any]) -> ResourceAxis:
    return ResourceAxis(
        name=best_text(payload.get("name"), ""),
        purpose=best_text(payload.get("purpose"), ""),
        acquisition_modes=string_list(payload.get("acquisition_modes")),
        scarcity_curve=best_text(payload.get("scarcity_curve"), ""),
    )


def _enemy_ladder_band_from_dict(payload: dict[str, Any]) -> EnemyLadderBand:
    return EnemyLadderBand(
        name=best_text(payload.get("name"), ""),
        floor_tier=best_text(payload.get("floor_tier"), ""),
        ceiling_tier=best_text(payload.get("ceiling_tier"), ""),
        pressure_sources=string_list(payload.get("pressure_sources")),
        expected_payoffs=string_list(payload.get("expected_payoffs")),
    )


def _progression_milestone_from_dict(payload: dict[str, Any]) -> ProgressionMilestone:
    return ProgressionMilestone(
        label=best_text(payload.get("label"), ""),
        chapter_window=best_text(payload.get("chapter_window"), ""),
        current_tier=best_text(payload.get("current_tier"), ""),
        target_tier=best_text(payload.get("target_tier"), ""),
        objective=best_text(payload.get("objective"), ""),
        required_resources=string_list(payload.get("required_resources")),
        key_trial=best_text(payload.get("key_trial"), ""),
        payoff=best_text(payload.get("payoff"), ""),
    )


def _power_system_bible_from_dict(payload: dict[str, Any]) -> PowerSystemBible:
    return PowerSystemBible(
        progression_mode=best_text(payload.get("progression_mode"), "soft_progression"),
        progression_flavor=best_text(payload.get("progression_flavor"), ""),
        progression_pacing=best_text(payload.get("progression_pacing"), "steady"),
        core_axis=best_text(payload.get("core_axis"), ""),
        secondary_axes=string_list(payload.get("secondary_axes")),
        progression_contract=string_list(payload.get("progression_contract")),
        realm_ladder=[_realm_tier_from_dict(item) for item in payload.get("realm_ladder", []) if isinstance(item, dict)],
        resource_axes=[_resource_axis_from_dict(item) for item in payload.get("resource_axes", []) if isinstance(item, dict)],
        enemy_ladder=[_enemy_ladder_band_from_dict(item) for item in payload.get("enemy_ladder", []) if isinstance(item, dict)],
        milestone_plan=[_progression_milestone_from_dict(item) for item in payload.get("milestone_plan", []) if isinstance(item, dict)],
        forbidden_shortcuts=string_list(payload.get("forbidden_shortcuts")),
    )


def _progression_ledger_item_from_dict(payload: dict[str, Any]) -> ProgressionLedgerItem:
    return ProgressionLedgerItem(
        milestone_label=best_text(payload.get("milestone_label"), ""),
        current_tier=best_text(payload.get("current_tier"), ""),
        target_tier=best_text(payload.get("target_tier"), ""),
        status=best_text(payload.get("status"), "pending"),
        opened_chapter=int(payload.get("opened_chapter", 0) or 0),
        last_touched_chapter=int(payload.get("last_touched_chapter", 0) or 0),
        objective=best_text(payload.get("objective"), ""),
        required_resources=string_list(payload.get("required_resources")),
        unlocked_rewards=string_list(payload.get("unlocked_rewards")),
        bottleneck=best_text(payload.get("bottleneck"), ""),
    )


def _world_bible_from_dict(payload: dict[str, Any]) -> WorldBible:
    return WorldBible(
        title=best_text(payload.get("title"), ""),
        logline=best_text(payload.get("logline"), ""),
        setting_summary=best_text(payload.get("setting_summary"), ""),
        core_conflict=best_text(payload.get("core_conflict"), ""),
        theme_statement=best_text(payload.get("theme_statement"), ""),
        narrative_voice=string_list(payload.get("narrative_voice")),
        world_rules=string_list(payload.get("world_rules")),
        chapter_guardrails=string_list(payload.get("chapter_guardrails")),
        ending_contract=string_list(payload.get("ending_contract")),
        major_threads=string_list(payload.get("major_threads")),
        characters=[_character_from_dict(item) for item in payload.get("characters", []) if isinstance(item, dict)],
    )


def _style_passage_from_dict(payload: dict[str, Any]) -> StylePassage:
    return StylePassage(
        label=best_text(payload.get("label"), ""),
        use_case=best_text(payload.get("use_case"), ""),
        text=best_text(payload.get("text"), ""),
    )


def _style_bible_from_dict(payload: dict[str, Any]) -> StyleBible:
    return StyleBible(
        audience_contract=string_list(payload.get("audience_contract")),
        tone_targets=string_list(payload.get("tone_targets")),
        pacing_rules=string_list(payload.get("pacing_rules")),
        propulsion_rules=string_list(payload.get("propulsion_rules")),
        clarity_rules=string_list(payload.get("clarity_rules")),
        dialogue_rules=string_list(payload.get("dialogue_rules")),
        prose_rules=string_list(payload.get("prose_rules")),
        sensory_rules=string_list(payload.get("sensory_rules")),
        thematic_subtext_rules=string_list(payload.get("thematic_subtext_rules")),
        pressure_curve_rules=string_list(payload.get("pressure_curve_rules")),
        grounding_rules=string_list(payload.get("grounding_rules")),
        taboo_phrases=string_list(payload.get("taboo_phrases")),
        sample_passages=[_style_passage_from_dict(item) for item in payload.get("sample_passages", []) if isinstance(item, dict)],
    )


def _voice_card_from_dict(payload: dict[str, Any]) -> CharacterVoiceCard:
    return CharacterVoiceCard(
        name=best_text(payload.get("name"), ""),
        speech_rhythm=best_text(payload.get("speech_rhythm"), "简洁"),
        emotional_expression=best_text(payload.get("emotional_expression"), ""),
        sentence_shape=best_text(payload.get("sentence_shape"), ""),
        social_register=best_text(payload.get("social_register"), ""),
        humor_style=best_text(payload.get("humor_style"), ""),
        silence_pattern=best_text(payload.get("silence_pattern"), ""),
        contrast_anchor=best_text(payload.get("contrast_anchor"), ""),
        common_words=string_list(payload.get("common_words")),
        tension_triggers=string_list(payload.get("tension_triggers")),
        forbidden_drifts=string_list(payload.get("forbidden_drifts")),
    )


def _promise_ledger_item_from_dict(payload: dict[str, Any]) -> PromiseLedgerItem:
    return PromiseLedgerItem(
        promise_id=best_text(payload.get("promise_id"), ""),
        label=best_text(payload.get("label"), ""),
        thread=best_text(payload.get("thread"), ""),
        chapter_opened=int(payload.get("chapter_opened", 0) or 0),
        target_volume=int(payload.get("target_volume", 0) or 0),
        current_status=best_text(payload.get("current_status"), "open"),
        last_touched_chapter=int(payload.get("last_touched_chapter", 0) or 0),
        payoff_requirements=string_list(payload.get("payoff_requirements")),
        overdue=bool(payload.get("overdue")),
        deadline_state=best_text(payload.get("deadline_state"), "on_track"),
    )


def _causality_edge_from_dict(payload: dict[str, Any]) -> CausalityEdge:
    return CausalityEdge(
        effect_label=best_text(payload.get("effect_label"), ""),
        cause=best_text(payload.get("cause"), ""),
        prerequisites=string_list(payload.get("prerequisites")),
        required_consequences=string_list(payload.get("required_consequences")),
        introduced_chapter=int(payload.get("introduced_chapter", 0) or 0),
        last_verified_chapter=int(payload.get("last_verified_chapter", 0) or 0),
    )


def _volume_blueprint_from_dict(payload: dict[str, Any]) -> VolumeBlueprint:
    return VolumeBlueprint(
        index=int(payload.get("index", 0)),
        start_chapter=int(payload.get("start_chapter", 1)),
        end_chapter=int(payload.get("end_chapter", 1)),
        title=best_text(payload.get("title"), ""),
        role=best_text(payload.get("role"), ""),
        central_question=best_text(payload.get("central_question"), ""),
        escalation=best_text(payload.get("escalation"), ""),
        emotional_shift=best_text(payload.get("emotional_shift"), ""),
        phase_type=best_text(payload.get("phase_type"), ""),
        volume_importance=best_text(payload.get("volume_importance"), ""),
        beat_count=int(payload.get("beat_count", 0) or 0),
        new_setting_load=best_text(payload.get("new_setting_load"), ""),
        new_cast_load=best_text(payload.get("new_cast_load"), ""),
        payoff_load=best_text(payload.get("payoff_load"), ""),
        expected_chapter_range=best_text(payload.get("expected_chapter_range"), ""),
        target_chapter_count=int(payload.get("target_chapter_count", 0) or 0),
        chapter_count_min=int(payload.get("chapter_count_min", 0) or 0),
        chapter_count_max=int(payload.get("chapter_count_max", 0) or 0),
        target_chars=int(payload.get("target_chars", 0) or 0),
        target_chars_min=int(payload.get("target_chars_min", 0) or 0),
        target_chars_max=int(payload.get("target_chars_max", 0) or 0),
        density_mode=best_text(payload.get("density_mode"), ""),
        tier_floor=best_text(payload.get("tier_floor"), ""),
        tier_target=best_text(payload.get("tier_target"), ""),
        required_breakthrough=best_text(payload.get("required_breakthrough"), ""),
        resource_goal=best_text(payload.get("resource_goal"), ""),
        enemy_band=best_text(payload.get("enemy_band"), ""),
        progression_payoff=best_text(payload.get("progression_payoff"), ""),
        must_payoff=string_list(payload.get("must_payoff")),
    )


def _book_outline_from_dict(payload: dict[str, Any]) -> BookOutline:
    return BookOutline(
        title=best_text(payload.get("title"), ""),
        one_line_summary=best_text(payload.get("one_line_summary"), ""),
        act_structure=string_list(payload.get("act_structure")),
        volumes=[_volume_blueprint_from_dict(item) for item in payload.get("volumes", []) if isinstance(item, dict)],
    )


def _chapter_outline_item_from_dict(payload: dict[str, Any], volume_index: int) -> ChapterOutlineItem:
    return ChapterOutlineItem(
        index=int(payload.get("index", 0)),
        volume_index=int(payload.get("volume_index", volume_index) or volume_index),
        title=best_text(payload.get("title"), ""),
        purpose=best_text(payload.get("purpose"), ""),
        conflict=best_text(payload.get("conflict"), ""),
        beat_summary=best_text(payload.get("beat_summary"), ""),
        ending_note=best_text(payload.get("ending_note"), ""),
        pov=best_text(payload.get("pov"), "第三人称有限视角"),
        closing_mode=best_text(payload.get("closing_mode"), "chapter_hook"),
        chapter_role=best_text(payload.get("chapter_role"), ""),
        scene_load_score=float(payload.get("scene_load_score", 0.0) or 0.0),
        target_chars=int(payload.get("target_chars", 0) or 0),
        target_chars_min=int(payload.get("target_chars_min", 0) or 0),
        target_chars_max=int(payload.get("target_chars_max", 0) or 0),
        split_allowed=bool(payload.get("split_allowed")),
        merge_allowed=bool(payload.get("merge_allowed")),
        progression_step_type=best_text(payload.get("progression_step_type"), ""),
        progression_reward=best_text(payload.get("progression_reward"), ""),
        progression_cost=best_text(payload.get("progression_cost"), ""),
        current_tier=best_text(payload.get("current_tier"), ""),
        target_tier=best_text(payload.get("target_tier"), ""),
        enemy_band=best_text(payload.get("enemy_band"), ""),
        resource_focus=best_text(payload.get("resource_focus"), ""),
        must_payoff=string_list(payload.get("must_payoff")),
    )


def _volume_outline_from_dict(payload: dict[str, Any]) -> VolumeOutline:
    volume_index = int(payload.get("volume_index", 0))
    return VolumeOutline(
        volume_index=volume_index,
        title=best_text(payload.get("title"), ""),
        goal=best_text(payload.get("goal"), ""),
        climax=best_text(payload.get("climax"), ""),
        carry_over_threads=string_list(payload.get("carry_over_threads")),
        tier_floor=best_text(payload.get("tier_floor"), ""),
        tier_target=best_text(payload.get("tier_target"), ""),
        required_breakthrough=best_text(payload.get("required_breakthrough"), ""),
        resource_goal=best_text(payload.get("resource_goal"), ""),
        enemy_band=best_text(payload.get("enemy_band"), ""),
        progression_payoff=best_text(payload.get("progression_payoff"), ""),
        chapter_targets=[
            _chapter_outline_item_from_dict(item, volume_index)
            for item in payload.get("chapter_targets", [])
            if isinstance(item, dict)
        ],
    )


def _scene_from_dict(payload: dict[str, Any]) -> SceneCard:
    return SceneCard(
        scene_index=int(payload.get("scene_index", 0)),
        location=best_text(payload.get("location"), ""),
        goal=best_text(payload.get("goal"), ""),
        conflict=best_text(payload.get("conflict"), ""),
        turn=best_text(payload.get("turn"), ""),
        scene_type=best_text(payload.get("scene_type"), ""),
        load_weight=float(payload.get("load_weight", 1.0) or 1.0),
        must_include=string_list(payload.get("must_include")),
    )


def _chapter_plan_from_dict(payload: dict[str, Any]) -> ChapterPlan:
    return ChapterPlan(
        chapter_index=int(payload.get("chapter_index", 0)),
        chapter_title=best_text(payload.get("chapter_title"), ""),
        purpose=best_text(payload.get("purpose"), ""),
        continuity_targets=string_list(payload.get("continuity_targets")),
        opening_image=best_text(payload.get("opening_image"), ""),
        closing_image=best_text(payload.get("closing_image"), ""),
        closing_mode=best_text(payload.get("closing_mode"), "chapter_hook"),
        scenes=[_scene_from_dict(item) for item in payload.get("scenes", []) if isinstance(item, dict)],
        primary_propulsion=best_text(payload.get("primary_propulsion"), ""),
        variation_goal=best_text(payload.get("variation_goal"), ""),
        term_budget=best_text(payload.get("term_budget"), ""),
        theme_visibility=best_text(payload.get("theme_visibility"), ""),
        grounding_beat=best_text(payload.get("grounding_beat"), ""),
        chapter_role=best_text(payload.get("chapter_role"), ""),
        scene_load_score=float(payload.get("scene_load_score", 0.0) or 0.0),
        target_chars=int(payload.get("target_chars", 0) or 0),
        target_chars_min=int(payload.get("target_chars_min", 0) or 0),
        target_chars_max=int(payload.get("target_chars_max", 0) or 0),
        split_allowed=bool(payload.get("split_allowed")),
        merge_allowed=bool(payload.get("merge_allowed")),
    )


def _local_quality_from_dict(payload: dict[str, Any]) -> LocalQualityReport:
    return LocalQualityReport(
        passed=bool(payload.get("passed")),
        score=int(payload.get("score", 0)),
        issues=string_list(payload.get("issues")),
        strengths=string_list(payload.get("strengths")),
        short_summary=best_text(payload.get("short_summary"), ""),
        metrics=payload.get("metrics") if isinstance(payload.get("metrics"), dict) else {},
    )


def _review_feedback_from_dict(payload: dict[str, Any]) -> ReviewFeedback:
    return ReviewFeedback(
        passed=bool(payload.get("passed")),
        score=int(payload.get("score", 0)),
        strengths=string_list(payload.get("strengths")),
        issues=string_list(payload.get("issues")),
        required_fixes=string_list(payload.get("required_fixes")),
        short_summary=best_text(payload.get("short_summary"), ""),
        chapter_fixes=_chapter_fix_list(payload.get("chapter_fixes")),
    )


def _character_state_from_dict(payload: dict[str, Any]) -> CharacterState:
    return CharacterState(
        name=best_text(payload.get("name"), ""),
        current_goal=best_text(payload.get("current_goal"), ""),
        emotional_state=best_text(payload.get("emotional_state"), ""),
        relationship_shift=best_text(payload.get("relationship_shift"), ""),
        risk=best_text(payload.get("risk"), ""),
        unresolved=best_text(payload.get("unresolved"), ""),
    )


def _continuity_update_from_dict(payload: dict[str, Any]) -> ContinuityUpdate:
    return ContinuityUpdate(
        chapter_index=int(payload.get("chapter_index", 0)),
        chapter_summary=best_text(payload.get("chapter_summary"), ""),
        new_threads=string_list(payload.get("new_threads")),
        resolved_threads=string_list(payload.get("resolved_threads")),
        timeline_events=string_list(payload.get("timeline_events")),
        character_states=[_character_state_from_dict(item) for item in payload.get("character_states", []) if isinstance(item, dict)],
        next_chapter_targets=string_list(payload.get("next_chapter_targets")),
        must_remember=string_list(payload.get("must_remember")),
        progression_updates=string_list(payload.get("progression_updates")),
        current_tier=best_text(payload.get("current_tier"), ""),
        next_breakthrough=best_text(payload.get("next_breakthrough"), ""),
    )


def _long_memory_update_from_dict(payload: dict[str, Any]) -> LongRangeMemoryUpdate:
    return LongRangeMemoryUpdate(
        chapter_index=int(payload.get("chapter_index", 0) or 0),
        promise_updates=[
            _promise_ledger_item_from_dict(item)
            for item in payload.get("promise_updates", [])
            if isinstance(item, dict)
        ],
        causality_updates=[
            _causality_edge_from_dict(item)
            for item in payload.get("causality_updates", [])
            if isinstance(item, dict)
        ],
        progression_updates=[
            _progression_ledger_item_from_dict(item)
            for item in payload.get("progression_updates", [])
            if isinstance(item, dict)
        ],
    )


def _logic_audit_from_dict(payload: dict[str, Any]) -> LogicAuditReport:
    gate_passed = bool(payload.get("gate_passed", payload.get("passed", False)))
    gate_level = best_text(payload.get("gate_level"), "")
    if not gate_level:
        text = "\n".join(string_list(payload.get("issues"))) + "\n" + best_text(payload.get("summary"), "")
        if gate_passed:
            gate_level = "pass"
        elif any(token in text for token in ("账本", "资料污染", "metadata", "状态失真")):
            gate_level = "repair_metadata"
        else:
            gate_level = "repair_cluster"
    return LogicAuditReport(
        passed=bool(payload.get("passed", payload.get("gate_passed", False))),
        gate_passed=gate_passed,
        summary=best_text(payload.get("summary"), ""),
        issues=string_list(payload.get("issues")),
        watch_items=string_list(payload.get("watch_items")),
        required_followups=string_list(payload.get("required_followups")),
        structure_risks=string_list(payload.get("structure_risks")),
        voice_risks=string_list(payload.get("voice_risks")),
        density_risks=string_list(payload.get("density_risks")),
        pressure_risks=string_list(payload.get("pressure_risks")),
        grounding_risks=string_list(payload.get("grounding_risks")),
        progression_risks=string_list(payload.get("progression_risks")),
        flagged_chapters=[
            item
            for item in payload.get("flagged_chapters", [])
            if isinstance(item, dict) and item.get("chapter_index") is not None
        ],
        repair_plan=[item for item in payload.get("repair_plan", []) if isinstance(item, dict)],
        gate_level=gate_level,
        ledger_sanity=payload.get("ledger_sanity", {}) if isinstance(payload.get("ledger_sanity"), dict) else {},
    )
