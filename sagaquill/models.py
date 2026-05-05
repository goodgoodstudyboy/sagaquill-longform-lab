from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ProviderConfig:
    base_url: str
    wire_api: str
    api_key: str
    model: str
    review_model: str
    light_model: str | None = None
    gateway_profile: str | None = None
    flagship_reasoning_effort: str | None = None
    flagship_service_tier: str | None = None
    light_reasoning_effort: str | None = None
    light_service_tier: str | None = None
    reasoning_effort: str | None = None
    service_tier: str | None = None
    continuation_mode: str = "replay"
    default_headers: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class CharacterSeed:
    name: str
    role: str = ""
    goal: str = ""
    conflict: str = ""
    notes: str = ""


@dataclass(slots=True)
class ProjectInput:
    title: str
    output_language: str = "zh-Hans"
    genre: str | None = None
    audience: str | None = None
    tone: str | None = None
    premise: str | None = None
    theme: str | None = None
    hook: str | None = None
    setting: str | None = None
    protagonist: str | None = None
    outline_hint: str | None = None
    world_hint: str | None = None
    ending_mode: str = "standalone"
    pov: str = "第三人称有限视角"
    target_total_chars: int | None = None
    target_chars_per_chapter: int | None = None
    chapter_count: int | None = None
    volume_count: int | None = None
    chapter_char_tolerance: float | None = None
    structure_mode: str | None = None
    market_profile: str = "qidian_longform"
    progression_mode: str = "soft_progression"
    progression_flavor: str = ""
    progression_pacing: str = "steady"
    power_system_hint: str | None = None
    style_examples: list[str] = field(default_factory=list)
    must_include: list[str] = field(default_factory=list)
    avoid: list[str] = field(default_factory=list)
    character_seeds: list[CharacterSeed] = field(default_factory=list)
    seed: int | None = None


@dataclass(slots=True)
class ProjectSpec:
    title: str
    genre: str
    audience: str
    tone: str
    premise: str
    theme: str
    hook: str
    setting: str
    protagonist: str
    outline_hint: str
    world_hint: str
    ending_mode: str
    pov: str
    target_total_chars: int
    target_chars_per_chapter: int
    chapter_count: int
    volume_count: int
    chapters_per_volume: int
    volume_chapter_targets: list[int] = field(default_factory=list)
    chapter_char_tolerance: float = 0.25
    structure_mode: str = "legacy"
    market_profile: str = "qidian_longform"
    progression_mode: str = "soft_progression"
    progression_flavor: str = ""
    progression_pacing: str = "steady"
    power_system_hint: str = ""
    style_examples: list[str] = field(default_factory=list)
    must_include: list[str] = field(default_factory=list)
    avoid: list[str] = field(default_factory=list)
    character_seeds: list[CharacterSeed] = field(default_factory=list)
    seed: int | None = None
    output_language: str = "zh-Hans"


@dataclass(slots=True)
class CharacterProfile:
    name: str
    role: str
    goal: str
    fear: str
    contradiction: str
    arc: str
    public_image: str
    private_truth: str
    speaking_style: str
    signature_image: str
    relationship_tensions: list[str] = field(default_factory=list)
    do_not_break: list[str] = field(default_factory=list)


@dataclass(slots=True)
class WorldBible:
    title: str
    logline: str
    setting_summary: str
    core_conflict: str
    theme_statement: str
    narrative_voice: list[str]
    world_rules: list[str]
    chapter_guardrails: list[str]
    ending_contract: list[str]
    major_threads: list[str]
    characters: list[CharacterProfile]


@dataclass(slots=True)
class BreakthroughRequirement:
    kind: str
    label: str
    details: str
    mandatory: bool = True


@dataclass(slots=True)
class RealmTier:
    rank: int
    name: str
    summary: str
    signature_gains: list[str] = field(default_factory=list)
    bottlenecks: list[str] = field(default_factory=list)
    typical_resources: list[str] = field(default_factory=list)
    danger_band: str = ""
    breakthrough_requirements: list[BreakthroughRequirement] = field(default_factory=list)


@dataclass(slots=True)
class ResourceAxis:
    name: str
    purpose: str
    acquisition_modes: list[str] = field(default_factory=list)
    scarcity_curve: str = ""


@dataclass(slots=True)
class EnemyLadderBand:
    name: str
    floor_tier: str
    ceiling_tier: str
    pressure_sources: list[str] = field(default_factory=list)
    expected_payoffs: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ProgressionMilestone:
    label: str
    chapter_window: str
    current_tier: str
    target_tier: str
    objective: str
    required_resources: list[str] = field(default_factory=list)
    key_trial: str = ""
    payoff: str = ""


@dataclass(slots=True)
class PowerSystemBible:
    progression_mode: str = "soft_progression"
    progression_flavor: str = ""
    progression_pacing: str = "steady"
    core_axis: str = ""
    secondary_axes: list[str] = field(default_factory=list)
    progression_contract: list[str] = field(default_factory=list)
    realm_ladder: list[RealmTier] = field(default_factory=list)
    resource_axes: list[ResourceAxis] = field(default_factory=list)
    enemy_ladder: list[EnemyLadderBand] = field(default_factory=list)
    milestone_plan: list[ProgressionMilestone] = field(default_factory=list)
    forbidden_shortcuts: list[str] = field(default_factory=list)


@dataclass(slots=True)
class StylePassage:
    label: str
    use_case: str
    text: str


@dataclass(slots=True)
class StyleBible:
    audience_contract: list[str] = field(default_factory=list)
    tone_targets: list[str] = field(default_factory=list)
    pacing_rules: list[str] = field(default_factory=list)
    propulsion_rules: list[str] = field(default_factory=list)
    clarity_rules: list[str] = field(default_factory=list)
    dialogue_rules: list[str] = field(default_factory=list)
    prose_rules: list[str] = field(default_factory=list)
    sensory_rules: list[str] = field(default_factory=list)
    thematic_subtext_rules: list[str] = field(default_factory=list)
    pressure_curve_rules: list[str] = field(default_factory=list)
    grounding_rules: list[str] = field(default_factory=list)
    taboo_phrases: list[str] = field(default_factory=list)
    sample_passages: list[StylePassage] = field(default_factory=list)


@dataclass(slots=True)
class CharacterVoiceCard:
    name: str
    speech_rhythm: str
    emotional_expression: str
    sentence_shape: str
    social_register: str = ""
    humor_style: str = ""
    silence_pattern: str = ""
    contrast_anchor: str = ""
    common_words: list[str] = field(default_factory=list)
    tension_triggers: list[str] = field(default_factory=list)
    forbidden_drifts: list[str] = field(default_factory=list)


@dataclass(slots=True)
class PromiseLedgerItem:
    promise_id: str
    label: str
    thread: str
    chapter_opened: int
    target_volume: int
    current_status: str
    last_touched_chapter: int
    payoff_requirements: list[str] = field(default_factory=list)
    overdue: bool = False
    deadline_state: str = "on_track"


@dataclass(slots=True)
class ProgressionLedgerItem:
    milestone_label: str
    current_tier: str
    target_tier: str
    status: str = "pending"
    opened_chapter: int = 0
    last_touched_chapter: int = 0
    objective: str = ""
    required_resources: list[str] = field(default_factory=list)
    unlocked_rewards: list[str] = field(default_factory=list)
    bottleneck: str = ""


@dataclass(slots=True)
class CausalityEdge:
    effect_label: str
    cause: str
    prerequisites: list[str]
    required_consequences: list[str]
    introduced_chapter: int
    last_verified_chapter: int


@dataclass(slots=True)
class LongRangeMemoryUpdate:
    chapter_index: int
    promise_updates: list[PromiseLedgerItem] = field(default_factory=list)
    causality_updates: list[CausalityEdge] = field(default_factory=list)
    progression_updates: list[ProgressionLedgerItem] = field(default_factory=list)


@dataclass(slots=True)
class VolumeBlueprint:
    index: int
    start_chapter: int
    end_chapter: int
    title: str
    role: str
    central_question: str
    escalation: str
    emotional_shift: str
    phase_type: str = ""
    volume_importance: str = ""
    beat_count: int = 0
    new_setting_load: str = ""
    new_cast_load: str = ""
    payoff_load: str = ""
    expected_chapter_range: str = ""
    target_chapter_count: int = 0
    chapter_count_min: int = 0
    chapter_count_max: int = 0
    target_chars: int = 0
    target_chars_min: int = 0
    target_chars_max: int = 0
    density_mode: str = ""
    tier_floor: str = ""
    tier_target: str = ""
    required_breakthrough: str = ""
    resource_goal: str = ""
    enemy_band: str = ""
    progression_payoff: str = ""
    must_payoff: list[str] = field(default_factory=list)


@dataclass(slots=True)
class BookOutline:
    title: str
    one_line_summary: str
    act_structure: list[str]
    volumes: list[VolumeBlueprint]


@dataclass(slots=True)
class ChapterOutlineItem:
    index: int
    volume_index: int
    title: str
    purpose: str
    conflict: str
    beat_summary: str
    ending_note: str
    pov: str
    closing_mode: str
    chapter_role: str = ""
    scene_load_score: float = 0.0
    target_chars: int = 0
    target_chars_min: int = 0
    target_chars_max: int = 0
    split_allowed: bool = False
    merge_allowed: bool = False
    progression_step_type: str = ""
    progression_reward: str = ""
    progression_cost: str = ""
    current_tier: str = ""
    target_tier: str = ""
    enemy_band: str = ""
    resource_focus: str = ""
    must_payoff: list[str] = field(default_factory=list)


@dataclass(slots=True)
class VolumeOutline:
    volume_index: int
    title: str
    goal: str
    climax: str
    carry_over_threads: list[str]
    tier_floor: str = ""
    tier_target: str = ""
    required_breakthrough: str = ""
    resource_goal: str = ""
    enemy_band: str = ""
    progression_payoff: str = ""
    chapter_targets: list[ChapterOutlineItem] = field(default_factory=list)


@dataclass(slots=True)
class SceneCard:
    scene_index: int
    location: str
    goal: str
    conflict: str
    turn: str
    scene_type: str = ""
    load_weight: float = 1.0
    must_include: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ChapterPlan:
    chapter_index: int
    chapter_title: str
    purpose: str
    continuity_targets: list[str]
    opening_image: str
    closing_image: str
    closing_mode: str
    scenes: list[SceneCard]
    primary_propulsion: str = ""
    variation_goal: str = ""
    term_budget: str = ""
    theme_visibility: str = ""
    grounding_beat: str = ""
    chapter_role: str = ""
    scene_load_score: float = 0.0
    target_chars: int = 0
    target_chars_min: int = 0
    target_chars_max: int = 0
    split_allowed: bool = False
    merge_allowed: bool = False
    progression_step_type: str = ""
    progression_reward: str = ""
    progression_cost: str = ""
    current_tier: str = ""
    target_tier: str = ""
    enemy_band: str = ""
    resource_focus: str = ""


@dataclass(slots=True)
class CharacterState:
    name: str
    current_goal: str
    emotional_state: str
    relationship_shift: str
    risk: str
    unresolved: str


@dataclass(slots=True)
class ContinuityState:
    recent_summaries: list[str] = field(default_factory=list)
    active_threads: list[str] = field(default_factory=list)
    resolved_threads: list[str] = field(default_factory=list)
    timeline: list[str] = field(default_factory=list)
    character_states: list[CharacterState] = field(default_factory=list)
    must_remember: list[str] = field(default_factory=list)
    progression_notes: list[str] = field(default_factory=list)
    current_tier: str = ""
    next_breakthrough: str = ""
    last_volume_index: int = 0
    last_chapter_index: int = 0


@dataclass(slots=True)
class ContinuityUpdate:
    chapter_index: int
    chapter_summary: str
    new_threads: list[str]
    resolved_threads: list[str]
    timeline_events: list[str]
    character_states: list[CharacterState]
    next_chapter_targets: list[str]
    must_remember: list[str]
    progression_updates: list[str] = field(default_factory=list)
    current_tier: str = ""
    next_breakthrough: str = ""


@dataclass(slots=True)
class LocalQualityReport:
    passed: bool
    score: int
    issues: list[str]
    strengths: list[str]
    short_summary: str
    metrics: dict[str, Any]


@dataclass(slots=True)
class ReviewFeedback:
    passed: bool
    score: int
    strengths: list[str]
    issues: list[str]
    required_fixes: list[str]
    short_summary: str
    chapter_fixes: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class StagnationDecision:
    chapter_index: int
    signal_level: str
    decision: str
    confidence: int
    reason: str
    scope_start_chapter: int
    scope_end_chapter: int
    next_chapter_constraints: list[str] = field(default_factory=list)
    repair_goal: str = ""


@dataclass(slots=True)
class StagnationJudgeReview:
    chapter_index: int
    verdict: str
    recommended_action: str
    confidence: int
    reason: str
    scope_start_chapter: int
    scope_end_chapter: int
    next_chapter_constraints: list[str] = field(default_factory=list)
    repair_goal: str = ""


@dataclass(slots=True)
class ChapterResult:
    index: int
    volume_index: int
    title: str
    outline_item: ChapterOutlineItem
    draft: str
    plan: ChapterPlan
    review: ReviewFeedback
    local_quality: LocalQualityReport
    continuity: ContinuityUpdate
    attempts: int
    long_memory: LongRangeMemoryUpdate | None = None


@dataclass(slots=True)
class FinalReview:
    passed: bool
    score: int
    strengths: list[str]
    issues: list[str]
    required_fixes: list[str]
    short_summary: str
    chapter_fixes: list[dict[str, Any]] = field(default_factory=list)
    local_quality: LocalQualityReport | None = None


@dataclass(slots=True)
class LogicAuditReport:
    passed: bool
    gate_passed: bool
    summary: str
    issues: list[str]
    watch_items: list[str]
    required_followups: list[str]
    structure_risks: list[str] = field(default_factory=list)
    voice_risks: list[str] = field(default_factory=list)
    density_risks: list[str] = field(default_factory=list)
    pressure_risks: list[str] = field(default_factory=list)
    grounding_risks: list[str] = field(default_factory=list)
    progression_risks: list[str] = field(default_factory=list)
    flagged_chapters: list[dict[str, Any]] = field(default_factory=list)
    repair_plan: list[dict[str, Any]] = field(default_factory=list)
    gate_level: str = "pass"
    ledger_sanity: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class BookPackage:
    title: str
    genre: str
    audience: str
    tone: str
    protagonist: str
    total_chars: int
    chapter_count: int
    volume_count: int
    final_score: int
    final_passed: bool
    factual_summary: str
    marketing_blurb: str
    catalog: list[dict[str, Any]] = field(default_factory=list)
    output_language: str = "zh-Hans"


@dataclass(slots=True)
class GenerationSummary:
    output_dir: str
    title: str
    chapter_count: int
    volume_count: int
    total_chars: int
    final_score: int
    final_passed: bool
    final_summary: str


@dataclass(slots=True)
class BatchConfig:
    output_language: str = "zh-Hans"
    target_total_chars: int | None = None
    target_chars_per_chapter: int | None = None
    chapter_count: int | None = None
    volume_count: int | None = None
    chapter_char_tolerance: float | None = 0.25
    structure_mode: str = "story_driven"
    market_profile: str = "qidian_longform"
    progression_mode: str = "soft_progression"
    progression_flavor: str = ""
    progression_pacing: str = "steady"
    power_system_hint: str | None = None
    ending_mode: str | None = None
    pov: str = "第三人称有限视角"
    run_to_completion: bool = True
    pause_at_chars: int = 300000


@dataclass(slots=True)
class ProposalRecord:
    proposal_id: str
    row_index: int
    source_batch_id: str
    title: str
    track: str = ""
    platform_fit: str = ""
    reference_requirements: str = ""
    hook: str = ""
    platform_blurb: str = ""
    core_story: str = ""
    theme: str = ""
    world_scene: str = ""
    world_seed: str = ""
    style_seed: str = ""
    chapter_seed: str = ""
    volume_seed: str = ""
    character_seed: str = ""
    notes: str = ""
    status: str = "draft"
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class BatchItemState:
    batch_id: str
    proposal_id: str
    title: str
    status: str = "draft"
    selected: bool = True
    priority: int = 0
    job_id: str | None = None
    output_dir: str | None = None
    last_error: str | None = None
    pause_reason: str | None = None
    written_chars: int = 0
    created_at: float = 0.0
    updated_at: float = 0.0


@dataclass(slots=True)
class BatchRecord:
    batch_id: str
    name: str
    source_name: str
    created_at: float
    updated_at: float
    status: str = "draft"
    max_concurrent: int = 2
    paused: bool = False
    hidden: bool = False
    provider_snapshot: dict[str, Any] = field(default_factory=dict)
    config: BatchConfig = field(default_factory=BatchConfig)
