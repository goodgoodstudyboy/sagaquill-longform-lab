from __future__ import annotations

from typing import Any

from .models import (
    ChapterOutlineItem,
    ChapterPlan,
    CharacterVoiceCard,
    ContinuityState,
    LogicAuditReport,
    PowerSystemBible,
    ProgressionLedgerItem,
    StyleBible,
)


def style_bible_runtime_view(style_bible: StyleBible) -> dict[str, Any]:
    return {
        "audience_contract": style_bible.audience_contract[:3],
        "tone_targets": style_bible.tone_targets[:4],
        "pacing_rules": style_bible.pacing_rules[:2],
        "propulsion_rules": style_bible.propulsion_rules[:2],
        "clarity_rules": style_bible.clarity_rules[:2],
        "dialogue_rules": style_bible.dialogue_rules[:2],
        "prose_rules": style_bible.prose_rules[:2],
        "thematic_subtext_rules": style_bible.thematic_subtext_rules[:2],
        "pressure_curve_rules": style_bible.pressure_curve_rules[:2],
        "grounding_rules": style_bible.grounding_rules[:2],
        "taboo_phrases": style_bible.taboo_phrases[:4],
        "sample_passages": [
            {
                "label": sample.label,
                "use_case": sample.use_case,
                "text": _trim_text(sample.text, 160),
            }
            for sample in style_bible.sample_passages[:2]
        ],
    }


def voice_cards_runtime_view(cards: list[CharacterVoiceCard], *, limit: int = 6) -> list[dict[str, Any]]:
    runtime_cards: list[dict[str, Any]] = []
    for card in cards[:limit]:
        runtime_cards.append(
            {
                "name": card.name,
                "speech_rhythm": card.speech_rhythm,
                "emotional_expression": card.emotional_expression,
                "sentence_shape": card.sentence_shape,
                "social_register": card.social_register,
                "contrast_anchor": card.contrast_anchor,
                "common_words": card.common_words[:4],
                "tension_triggers": card.tension_triggers[:3],
                "forbidden_drifts": card.forbidden_drifts[:3],
            }
        )
    return runtime_cards


def continuity_runtime_view(state: ContinuityState) -> dict[str, Any]:
    return {
        "last_volume_index": state.last_volume_index,
        "last_chapter_index": state.last_chapter_index,
        "current_tier": state.current_tier,
        "next_breakthrough": state.next_breakthrough,
        "recent_summaries": state.recent_summaries[-4:],
        "active_threads": state.active_threads[:8],
        "resolved_threads": state.resolved_threads[-4:],
        "timeline": state.timeline[-6:],
        "must_remember": state.must_remember[:8],
        "progression_notes": state.progression_notes[:8],
        "character_states": [
            {
                "name": item.name,
                "current_goal": item.current_goal,
                "emotional_state": item.emotional_state,
                "relationship_shift": item.relationship_shift,
                "risk": item.risk,
                "unresolved": item.unresolved,
            }
            for item in state.character_states[:6]
        ],
    }


def execution_packet(
    chapter: ChapterOutlineItem,
    plan: ChapterPlan,
    continuity_runtime: dict[str, Any],
    style_runtime: dict[str, Any],
    voice_runtime: list[dict[str, Any]],
    *,
    power_system_runtime: dict[str, Any] | None = None,
    progression_memory: list[dict[str, Any]] | None = None,
    story_memory: list[dict[str, Any]] | None = None,
    style_memory: list[dict[str, Any]] | None = None,
    promise_memory: list[dict[str, Any]] | None = None,
    causality_memory: list[dict[str, Any]] | None = None,
    recent_propulsion_history: list[dict[str, Any]] | None = None,
    logic_audit: LogicAuditReport | dict[str, Any] | None = None,
    chapter_room: dict[str, Any] | None = None,
) -> dict[str, Any]:
    packet = {
        "chapter": {
            "index": chapter.index,
            "volume_index": chapter.volume_index,
            "title": chapter.title,
            "purpose": plan.purpose or chapter.purpose,
            "conflict": chapter.conflict,
            "pov": chapter.pov,
            "closing_mode": plan.closing_mode or chapter.closing_mode,
            "chapter_role": plan.chapter_role or chapter.chapter_role,
            "scene_load_score": plan.scene_load_score or chapter.scene_load_score,
            "target_chars": plan.target_chars or chapter.target_chars,
            "target_chars_min": plan.target_chars_min or chapter.target_chars_min,
            "target_chars_max": plan.target_chars_max or chapter.target_chars_max,
            "split_allowed": plan.split_allowed if plan.split_allowed is not None else chapter.split_allowed,
            "merge_allowed": plan.merge_allowed if plan.merge_allowed is not None else chapter.merge_allowed,
            "progression_step_type": plan.progression_step_type or chapter.progression_step_type,
            "progression_reward": plan.progression_reward or chapter.progression_reward,
            "progression_cost": plan.progression_cost or chapter.progression_cost,
            "current_tier": plan.current_tier or chapter.current_tier,
            "target_tier": plan.target_tier or chapter.target_tier,
            "enemy_band": plan.enemy_band or chapter.enemy_band,
            "resource_focus": plan.resource_focus or chapter.resource_focus,
            "primary_propulsion": plan.primary_propulsion,
            "variation_goal": plan.variation_goal,
            "term_budget": plan.term_budget,
            "theme_visibility": plan.theme_visibility,
            "grounding_beat": plan.grounding_beat,
            "continuity_targets": plan.continuity_targets[:8],
            "must_payoff": list(dict.fromkeys([*chapter.must_payoff, *plan.continuity_targets]))[:8],
            "opening_image": plan.opening_image,
            "closing_image": plan.closing_image,
            "scenes": [
                {
                    "scene_index": scene.scene_index,
                    "scene_type": scene.scene_type,
                    "load_weight": scene.load_weight,
                    "location": scene.location,
                    "goal": scene.goal,
                    "conflict": scene.conflict,
                    "turn": scene.turn,
                    "must_include": scene.must_include[:4],
                }
                for scene in plan.scenes
            ],
        },
        "continuity": continuity_runtime,
        "power_system": power_system_runtime or {},
        "style": style_runtime,
        "voices": voice_runtime,
        "progression_memory": (progression_memory or [])[:6],
        "story_memory": (story_memory or [])[:6],
        "style_memory": (style_memory or [])[:4],
        "promise_memory": (promise_memory or [])[:6],
        "causality_memory": (causality_memory or [])[:4],
        "recent_propulsion_history": (recent_propulsion_history or [])[:4],
        "logic_audit": logic_audit_runtime_view(logic_audit),
        "chapter_room": chapter_room_runtime_view(chapter_room),
    }
    return packet


def progression_ledger_runtime_view(items: list[ProgressionLedgerItem], *, limit: int = 8) -> dict[str, Any]:
    status_counts: dict[str, int] = {}
    for item in items:
        status_counts[item.status] = status_counts.get(item.status, 0) + 1
    return {
        "count": len(items),
        "status_counts": status_counts,
        "focused_items": [
            {
                "milestone_label": item.milestone_label,
                "current_tier": item.current_tier,
                "target_tier": item.target_tier,
                "status": item.status,
                "last_touched_chapter": item.last_touched_chapter,
                "objective": item.objective,
                "required_resources": item.required_resources[:3],
                "unlocked_rewards": item.unlocked_rewards[:3],
                "bottleneck": item.bottleneck,
            }
            for item in items[:limit]
        ],
    }


def power_system_runtime_view(power_system: PowerSystemBible | None) -> dict[str, Any]:
    if power_system is None:
        return {}
    return {
        "progression_mode": power_system.progression_mode,
        "progression_flavor": power_system.progression_flavor,
        "progression_pacing": power_system.progression_pacing,
        "core_axis": power_system.core_axis,
        "secondary_axes": power_system.secondary_axes[:4],
        "progression_contract": power_system.progression_contract[:6],
        "realm_ladder": [
            {
                "rank": item.rank,
                "name": item.name,
                "summary": item.summary,
                "signature_gains": item.signature_gains[:3],
                "typical_resources": item.typical_resources[:3],
                "bottlenecks": item.bottlenecks[:2],
            }
            for item in power_system.realm_ladder[:8]
        ],
        "enemy_ladder": [
            {
                "name": item.name,
                "floor_tier": item.floor_tier,
                "ceiling_tier": item.ceiling_tier,
                "pressure_sources": item.pressure_sources[:3],
            }
            for item in power_system.enemy_ladder[:5]
        ],
        "milestone_plan": [
            {
                "label": item.label,
                "chapter_window": item.chapter_window,
                "current_tier": item.current_tier,
                "target_tier": item.target_tier,
                "objective": item.objective,
                "key_trial": item.key_trial,
                "payoff": item.payoff,
            }
            for item in power_system.milestone_plan[:8]
        ],
    }


def logic_audit_runtime_view(logic_audit: LogicAuditReport | dict[str, Any] | None) -> dict[str, Any]:
    if logic_audit is None:
        return {}
    if isinstance(logic_audit, LogicAuditReport):
        return {
            "summary": logic_audit.summary,
            "gate_level": logic_audit.gate_level,
            "watch_items": logic_audit.watch_items[:4],
            "required_followups": logic_audit.required_followups[:4],
            "structure_risks": logic_audit.structure_risks[:2],
            "voice_risks": logic_audit.voice_risks[:2],
            "density_risks": logic_audit.density_risks[:2],
            "pressure_risks": logic_audit.pressure_risks[:2],
            "grounding_risks": logic_audit.grounding_risks[:2],
            "progression_risks": logic_audit.progression_risks[:2],
            "flagged_chapters": logic_audit.flagged_chapters[:2],
        }
    if isinstance(logic_audit, dict):
        return {
            "summary": logic_audit.get("summary", ""),
            "gate_level": logic_audit.get("gate_level", ""),
            "watch_items": _as_list(logic_audit.get("watch_items"))[:4],
            "required_followups": _as_list(logic_audit.get("required_followups"))[:4],
            "structure_risks": _as_list(logic_audit.get("structure_risks"))[:2],
            "voice_risks": _as_list(logic_audit.get("voice_risks"))[:2],
            "density_risks": _as_list(logic_audit.get("density_risks"))[:2],
            "pressure_risks": _as_list(logic_audit.get("pressure_risks"))[:2],
            "grounding_risks": _as_list(logic_audit.get("grounding_risks"))[:2],
            "progression_risks": _as_list(logic_audit.get("progression_risks"))[:2],
            "flagged_chapters": logic_audit.get("flagged_chapters", [])[:2],
        }
    return {}


def chapter_room_runtime_view(room: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(room, dict):
        return {}
    notes = room.get("notes")
    return {
        "shared_mandates": _as_list(room.get("shared_mandates"))[:8],
        "blocking_issues": _as_list(room.get("blocking_issues"))[:4],
        "notes": [
            {
                "agent": item.get("agent", ""),
                "must_land": _as_list(item.get("must_land"))[:3],
                "risks": _as_list(item.get("risks"))[:2],
                "summary": item.get("summary", ""),
            }
            for item in notes[:3]
            if isinstance(item, dict)
        ]
        if isinstance(notes, list)
        else [],
    }


def _trim_text(text: str, limit: int) -> str:
    stripped = (text or "").strip()
    if len(stripped) <= limit:
        return stripped
    return stripped[: limit - 1].rstrip() + "…"


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    return []
