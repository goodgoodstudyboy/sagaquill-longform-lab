from __future__ import annotations

import math

from .models import (
    BookOutline,
    ChapterOutlineItem,
    ChapterPlan,
    ChapterResult,
    CausalityEdge,
    CharacterVoiceCard,
    ContinuityState,
    PromiseLedgerItem,
    ProjectInput,
    ProjectSpec,
    ProgressionLedgerItem,
    PowerSystemBible,
    StyleBible,
    VolumeBlueprint,
    VolumeOutline,
    WorldBible,
)
from .normalize import best_text as _best_text
from .quality import chapter_length_grace
from .runtime_views import (
    chapter_room_runtime_view,
    continuity_runtime_view,
    execution_packet as build_execution_packet_view,
    logic_audit_runtime_view,
    style_bible_runtime_view,
    voice_cards_runtime_view,
)
from .util import compact_json


def intake_system_prompt() -> str:
    return (
        "你是中文小说项目总策划。"
        "你的任务是把用户稀疏、含糊甚至只有标题的输入，补全成一个可以直接进入长篇生产流程的项目 brief。"
        "必须优先保证故事可读性、商业可执行性和完整闭环。"
        "只返回 JSON。"
    )


def intake_user_prompt(project_input: ProjectInput, structure: dict[str, int]) -> str:
    shape = {
        "title": project_input.title,
        "genre": "题材定位",
        "audience": "目标读者",
        "tone": "叙事气质",
        "premise": "故事前提",
        "theme": "核心主题",
        "hook": "一句话钩子",
        "setting": "时空和环境设定",
        "protagonist": "主角简介",
        "outline_hint": "如果用户没给，就补成一句可执行的总纲",
        "world_hint": "如果用户没给，就补成一句世界观约束",
        "progression_mode": "soft_progression 或 hard_realm_progression",
        "progression_flavor": "xuanhuan_fast / xianxia_steady / sci_fi_evolution / 空",
        "progression_pacing": "fast / steady / slow",
        "power_system_hint": "升级体系约束，非硬升级可留空",
        "style_examples": ["3到5条具体风格要求"],
        "must_include": ["必须写到的关键元素"],
        "avoid": ["明确禁止出现的问题"],
        "character_seeds": [
            {
                "name": "角色名",
                "role": "功能定位",
                "goal": "显性目标",
                "conflict": "核心矛盾",
                "notes": "补充说明"
            }
        ]
    }
    return (
        "请把用户输入补全成一个能直接用于生成完整小说的项目 brief。\n"
        "硬要求：\n"
        "1. 必须保留用户已明确给出的设定，不得随意改动。\n"
        "2. 如果用户只给标题，请推导出一个最稳、最好读、适合完整成书的中文故事方案。\n"
        "3. 这是单次任务启动的长篇工程，不是试玩短片。必须考虑后续持续推进和最终收束。\n"
        f"{_market_profile_guidance(project_input.market_profile, stage='planning')}\n"
        f"{_progression_guidance(project_input.progression_mode, project_input.progression_flavor, project_input.progression_pacing, stage='planning')}\n"
        "4. 默认 ending_mode 是 standalone，必须倾向完整闭环，不允许把主线故意留成半截。\n"
        "5. 人物种子至少给出主角和一个关键对手或辅助角色。\n"
        "6. 只返回一个 JSON 对象。\n\n"
        f"用户输入：\n{compact_json(project_input)}\n\n"
        f"固定结构参数：\n{compact_json(structure)}\n\n"
        f"输出 JSON 结构：\n{compact_json(shape)}"
    )


def world_system_prompt() -> str:
    return (
        "你是资深中文长篇小说编辑。"
        "你负责把项目 brief 转成可持续写作的设定圣经。"
        "必须让人物、世界规则和最终收束要求都落到可执行层。"
        "只返回 JSON。"
    )


def story_room_system_prompt() -> str:
    return (
        "你是中文长篇小说策划会议记录员。"
        "你要模拟多位资深 agent 对同一项目进行短会讨论，并整理成结构化纪要。"
        "讨论必须具体，不能空喊口号。"
        "只返回 JSON。"
    )


def story_room_user_prompt(spec: ProjectSpec) -> str:
    shape = {
        "notes": [
            {
                "agent": "world_architect",
                "focus": "该 agent 的职责焦点",
                "must_hold": ["后续必须坚持的规则"],
                "risks": ["当前最大风险"],
                "opportunities": ["可以放大的亮点"],
                "summary": "该 agent 的简短立场"
            },
            {
                "agent": "character_director",
                "focus": "人物驱动与关系弧线",
                "must_hold": ["人物层面的硬约束"],
                "risks": ["人物写崩风险"],
                "opportunities": ["可放大的角色张力"],
                "summary": "该 agent 的简短立场"
            },
            {
                "agent": "plot_architect",
                "focus": "结构推进与 payoff",
                "must_hold": ["结构层面的硬约束"],
                "risks": ["节奏和逻辑风险"],
                "opportunities": ["可放大的剧情引擎"],
                "summary": "该 agent 的简短立场"
            }
        ],
        "shared_contract": ["会议共识，后续所有 agent 都必须遵守"],
        "global_risks": ["如果不控制，整本会出问题的总风险"]
    }
    return (
        "请为这个小说项目生成一份策划会纪要。\n"
        "要求：\n"
        "1. notes 必须至少包含 world_architect、character_director、plot_architect 三位 agent。\n"
        "2. must_hold 必须具体，可被后续提示词直接引用。\n"
        "3. shared_contract 必须覆盖：主线闭环、人物弧线、连续性、文风边界。\n"
        "4. 不要互相重复，要像同一项目组内部真实分工。\n"
        f"{_market_profile_guidance(spec.market_profile, stage='planning')}\n"
        f"{_progression_guidance(spec.progression_mode, spec.progression_flavor, spec.progression_pacing, stage='planning')}\n"
        "5. 只返回 JSON。\n\n"
        f"项目 brief：\n{compact_json(spec)}\n\n"
        f"输出 JSON 结构：\n{compact_json(shape)}"
    )


def style_system_prompt() -> str:
    return (
        "你是中文小说风格总监。"
        "你负责把项目气质、平台目标和文风约束整理成可长期检索的风格圣经。"
        "不要空泛形容词，只返回 JSON。"
    )


def style_user_prompt(
    spec: ProjectSpec,
    story_room: dict | None = None,
    recent_chapter_samples: list[dict[str, object]] | None = None,
    anchor_style_bible: StyleBible | None = None,
) -> str:
    shape = {
        "audience_contract": ["读者期待和阅读耐受边界"],
        "tone_targets": ["整体气质目标"],
        "pacing_rules": ["节奏硬规则"],
        "propulsion_rules": ["推进变化规则，避免长期同构发动机"],
        "clarity_rules": ["术语密度和说明负担规则"],
        "dialogue_rules": ["对白规则"],
        "prose_rules": ["叙述规则"],
        "sensory_rules": ["场景和感官表现规则"],
        "thematic_subtext_rules": ["主题呈现规则，避免把意义讲透"],
        "pressure_curve_rules": ["压力曲线规则，避免长期同频高压"],
        "grounding_rules": ["地面生活和落地质感规则"],
        "taboo_phrases": ["绝对避免的表达腔调或套路"],
        "sample_passages": [
            {
                "label": "样例标签",
                "use_case": "适用场景",
                "text": "80到180字的示例文风片段，不涉及本书具体剧情。"
            }
        ],
    }
    return (
        "请为这个项目生成一份可长期检索的文风圣经。\n"
        "要求：\n"
        "1. sample_passages 必须像可复用的语气范文，不要写成立项说明。\n"
        "2. taboo_phrases 要明确指出该项目不该出现的油滑口吻、套路句式或跑偏方向。\n"
        "3. 节奏、推进、术语密度、对白、叙述、感官表现都要能直接影响后续章节写作。\n"
        "3.1 propulsion_rules 必须明确怎样避免长期重复“发现旧证/进入节点/看到更深机制/再开新节点”这一类同构推进。\n"
        "3.2 clarity_rules 必须明确前段如何控制世界词、制度词、流程词密度，避免读者一开始被术语压住。\n"
        "3.3 thematic_subtext_rules 必须明确主题主要靠选择、代价、关系和动作显形，不要在情节已经成立后再补一段理念说明。\n"
        "3.4 pressure_curve_rules 必须明确高压章节之间如何安排缓冲、生活落地、关系换气和节奏松紧变化。\n"
        "3.5 grounding_rules 必须明确何时加入饮食、金钱、路程、体力、住处、天气、职业流程、人情往来等落地细节。\n"
        "4. 必须吸收项目 brief、策划会纪要和 style_examples 的共识。\n"
        "4.1 如果给了已写章节样本，必须优先尊重这些样本里已经形成的实际语气、节奏和叙述密度，不能把旧文风改写成另一种书。\n"
        "4.2 如果给了文风基线锚点，只能在不破坏 audience_contract、tone_targets、taboo_phrases 核心边界的前提下做局部校准。\n"
        "4.3 如果近期样本和文风基线冲突，优先保持基线，只输出能够解释这种冲突的微调建议，不要推翻基线。\n"
        f"{_market_profile_guidance(spec.market_profile, stage='planning')}\n"
        "5. 只返回 JSON。\n\n"
        f"项目 brief：\n{compact_json(spec)}\n\n"
        f"策划会纪要：\n{compact_json(story_room or {})}\n\n"
        f"文风基线锚点：\n{compact_json(anchor_style_bible or {})}\n\n"
        f"已写章节样本：\n{compact_json(recent_chapter_samples or [])}\n\n"
        f"输出 JSON 结构：\n{compact_json(shape)}"
    )


def voice_system_prompt() -> str:
    return (
        "你是人物声线编辑。"
        "你要为核心角色建立长期稳定的说话和情绪表达边界。"
        "只返回 JSON。"
    )


def voice_user_prompt(
    spec: ProjectSpec,
    bible: WorldBible,
    style_bible: StyleBible,
    recent_voice_samples: list[dict[str, object]] | None = None,
) -> str:
    shape = {
        "voice_cards": [
            {
                "name": "角色名",
                "speech_rhythm": "说话节奏",
                "emotional_expression": "情绪表达方式",
                "sentence_shape": "句式特征",
                "social_register": "社交场合和身份位置带来的措辞层级",
                "humor_style": "是否会开玩笑、如何开玩笑",
                "silence_pattern": "沉默、停顿、岔开话题的习惯",
                "contrast_anchor": "和其他核心角色最明显的声口差异锚点",
                "common_words": ["常用词或口头偏好"],
                "tension_triggers": ["哪些压力会改变他说话方式"],
                "forbidden_drifts": ["绝对不能跑偏的声线问题"],
            }
        ]
    }
    return (
        "请为主要角色生成声线卡。\n"
        "要求：\n"
        "1. 每个角色都要和其功能、欲望、恐惧一致。\n"
        "2. forbidden_drifts 必须能直接用于审校和重写。\n"
        "3. 角色之间要有辨识度，不能同腔同调。\n"
        "3.1 必须明确区分人物的社会位置、幽默感、沉默方式和话锋转向，避免所有人都用一种冷硬高压口吻说话。\n"
        "3.1 如果给了已写章节中的人物样本，必须优先总结他们已经写出来的说话习惯、情绪表达方式和句式，不要重设人物。\n"
        f"{_market_profile_guidance(spec.market_profile, stage='planning')}\n"
        "4. 只返回 JSON。\n\n"
        f"项目 brief：\n{compact_json(spec)}\n\n"
        f"设定圣经：\n{compact_json(bible)}\n\n"
        f"文风圣经：\n{compact_json(style_bible)}\n\n"
        f"已写人物样本：\n{compact_json(recent_voice_samples or [])}\n\n"
        f"输出 JSON 结构：\n{compact_json(shape)}"
    )


def world_user_prompt(spec: ProjectSpec, story_room: dict | None = None) -> str:
    shape = {
        "title": spec.title,
        "logline": "一句话卖点",
        "setting_summary": "150到260字",
        "core_conflict": "主冲突",
        "theme_statement": "主题表达",
        "narrative_voice": ["3到6条文风要求"],
        "world_rules": ["4到8条硬规则"],
        "chapter_guardrails": ["4到8条章节级约束"],
        "ending_contract": ["最终章必须兑现的承诺"],
        "major_threads": ["会贯穿全书的主要线索"],
        "characters": [
            {
                "name": "角色名",
                "role": "功能定位",
                "goal": "显性目标",
                "fear": "核心恐惧",
                "contradiction": "内在矛盾",
                "arc": "成长变化",
                "public_image": "外在形象",
                "private_truth": "真实内心",
                "speaking_style": "说话方式",
                "signature_image": "标志性意象",
                "relationship_tensions": ["关系张力"],
                "do_not_break": ["写作禁区"]
            }
        ]
    }
    return (
        "请生成小说设定圣经。\n"
        "要求：\n"
        "1. 世界规则必须服务剧情，不准设定炫技。\n"
        "2. 角色必须能长期驱动剧情，而不是信息工具人。\n"
        "3. ending_contract 必须明确告诉后续生成器：最终章要兑现什么，什么不能留成半截。\n"
        "4. major_threads 必须覆盖主线、情感线、权力/现实冲突线。\n"
        "4.1 必须尊重策划会纪要里的 shared_contract 和各 agent 提出的 must_hold。\n"
        f"{_market_profile_guidance(spec.market_profile, stage='planning')}\n"
        f"{_progression_guidance(spec.progression_mode, spec.progression_flavor, spec.progression_pacing, stage='planning')}\n"
        "5. 只返回 JSON。\n\n"
        f"项目 brief：\n{compact_json(spec)}\n\n"
        f"策划会纪要：\n{compact_json(story_room or {})}\n\n"
        f"输出 JSON 结构：\n{compact_json(shape)}"
    )


def power_system_system_prompt() -> str:
    return (
        "你是中文长篇升级体系总设计师。"
        "你的任务是把项目题材、世界观和平台打法，整理成可长期执行的升级体系圣经。"
        "必须让台阶、代价、资源、强敌和回报都能被后续大纲直接使用。"
        "只返回 JSON。"
    )


def power_system_user_prompt(
    spec: ProjectSpec,
    bible: WorldBible,
    story_room: dict | None = None,
) -> str:
    shape = {
        "progression_mode": spec.progression_mode,
        "progression_flavor": spec.progression_flavor,
        "progression_pacing": spec.progression_pacing,
        "core_axis": "主升级轴，例如境界/生命层级/职业等级",
        "secondary_axes": ["副升级轴，例如功法、法器、权柄、血脉、势力、资源权限"],
        "progression_contract": ["整个升级体系必须遵守的硬约束"],
        "realm_ladder": [
            {
                "rank": 1,
                "name": "境界名",
                "summary": "这一层的核心变化",
                "signature_gains": ["这一层会获得什么"],
                "bottlenecks": ["卡点和代价"],
                "typical_resources": ["典型资源"],
                "danger_band": "这一层典型会遇到什么危险",
                "breakthrough_requirements": [
                    {
                        "kind": "resource / trial / insight / lineage / technique",
                        "label": "突破条件名",
                        "details": "突破条件说明",
                        "mandatory": True
                    }
                ]
            }
        ],
        "resource_axes": [
            {
                "name": "资源轴名称",
                "purpose": "为什么重要",
                "acquisition_modes": ["获得方式"],
                "scarcity_curve": "越往后越稀缺还是逐步放开"
            }
        ],
        "enemy_ladder": [
            {
                "name": "敌人带宽名",
                "floor_tier": "下限层级",
                "ceiling_tier": "上限层级",
                "pressure_sources": ["压迫来源"],
                "expected_payoffs": ["打赢后应拿到的回报"]
            }
        ],
        "milestone_plan": [
            {
                "label": "阶段名",
                "chapter_window": "1-30",
                "current_tier": "当前层级",
                "target_tier": "目标层级",
                "objective": "阶段目标",
                "required_resources": ["这一阶段必拿资源"],
                "key_trial": "必须经历的关键试炼",
                "payoff": "阶段回报"
            }
        ],
        "forbidden_shortcuts": ["绝对不能出现的升级偷渡方式"]
    }
    return (
        "请为这个项目生成升级体系圣经。\n"
        "要求：\n"
        "1. 如果 progression_mode 是 hard_realm_progression，必须给出清晰可执行的 realm_ladder，不能只写空泛成长感。\n"
        "2. realm_ladder 必须体现真实台阶，每一层的能力变化、瓶颈、资源与敌人带宽都要不同。\n"
        "3. milestone_plan 必须体现阶段目标、关键资源、关键试炼和回报，不能只写“继续变强”。\n"
        "4. forbidden_shortcuts 必须明确指出哪些无代价突破、越级碾压、资源白送、强敌失真是不能出现的。\n"
        "5. 若 progression_mode 是 soft_progression，也要给出主副升级轴和阶段里程碑，但可以减少硬境界数量。\n"
        f"{_market_profile_guidance(spec.market_profile, stage='planning')}\n"
        f"{_progression_guidance(spec.progression_mode, spec.progression_flavor, spec.progression_pacing, stage='planning')}\n"
        "6. 只返回 JSON。\n\n"
        f"项目 brief（运行态摘要）：\n{compact_json(_project_runtime_payload(spec))}\n\n"
        f"设定圣经（运行态摘要）：\n{compact_json(_world_runtime_payload(bible))}\n\n"
        f"策划会纪要：\n{compact_json(story_room or {})}\n\n"
        f"输出 JSON 结构：\n{compact_json(shape)}"
    )


def book_outline_system_prompt() -> str:
    return "你是长篇小说总编。你负责把全书拆成分卷蓝图，只返回 JSON。"


def book_outline_user_prompt(
    spec: ProjectSpec,
    bible: WorldBible,
    volume_skeleton: list[dict],
    story_room: dict | None = None,
    power_system: PowerSystemBible | None = None,
) -> str:
    shape = {
        "title": spec.title,
        "one_line_summary": "一句话简介",
        "act_structure": ["三幕或四幕结构关键节点"],
        "volumes": volume_skeleton
    }
    return (
        "请生成全书分卷蓝图。\n"
        "要求：\n"
        "1. 必须严格使用给定的分卷范围，不增删卷数。每卷章节目标可以按该卷故事任务、高潮级别和负载自然浮动，不要把所有卷写成同章数同密度。\n"
        "2. 每一卷都要有清楚的任务、升级点和情绪变化。\n"
        "2.0 如果本书启用了硬境界升级，分卷必须明确写出本卷的台阶推进、关键资源、关键试炼和阶段性回报。\n"
        "2.1 opening / bridge / investigation / escalation / climax / fallout / closure 等不同阶段，章节负载、信息密度和高潮体量应有明显差异。\n"
        "2.2 expected_chapter_range、target_chapter_count、target_chars 这些字段必须体现该卷故事任务，而不是全书平均切块。\n"
        "3. 最后一卷必须以完整收束主线为目标；如果 ending_mode 是 standalone，不允许把主要问题拖成下本再说。\n"
        "4. must_payoff 必须写具体，不要空泛。\n"
        "4.1 必须吸收策划会纪要里的 shared_contract、global_risks 和 plot_architect / character_director 的约束。\n"
        f"{_market_profile_guidance(spec.market_profile, stage='planning')}\n"
        f"{_progression_guidance(spec.progression_mode, spec.progression_flavor, spec.progression_pacing, stage='planning')}\n"
        "5. 只返回 JSON。\n\n"
        f"项目 brief：\n{compact_json(spec)}\n\n"
        f"设定圣经：\n{compact_json(bible)}\n\n"
        f"升级体系圣经（摘要）：\n{compact_json(_power_system_runtime_payload(power_system))}\n\n"
        f"策划会纪要：\n{compact_json(story_room or {})}\n\n"
        f"固定分卷骨架：\n{compact_json(volume_skeleton)}\n\n"
        f"输出 JSON 结构：\n{compact_json(shape)}"
    )


def book_outline_normalizer_system_prompt() -> str:
    return (
        "你是全书分卷蓝图 JSON 结构规范化器。"
        "你的任务只是在不改写故事内容的前提下，把已有分卷蓝图整理成规范 JSON。"
        "不得新增剧情、不得删改卷任务、不得改写事实。"
        "顶层必须是一个 JSON 对象。"
        "只返回 JSON。"
    )


def book_outline_normalizer_user_prompt(
    spec: ProjectSpec,
    volume_skeleton: list[dict],
    raw_payload: object,
) -> str:
    shape = {
        "title": spec.title,
        "one_line_summary": "一句话简介",
        "act_structure": ["三幕或四幕结构关键节点"],
        "volumes": volume_skeleton,
    }
    return (
        "请把下面已有的全书分卷蓝图 JSON 规范化为正式结构。\n"
        "硬要求：\n"
        "1. 顶层必须是一个 JSON 对象，不允许返回数组。\n"
        "2. 只做结构规范化，不要改写故事内容，不要新增剧情，不要补造不存在的卷。\n"
        "3. 正式分卷字段名必须是 volumes；如果源数据用了 volume_outlines、volume_targets、outline_volumes 或 items，请统一映射成 volumes。\n"
        "4. 如果源数据被拆成多个命名块，请合并成一个对象。\n"
        "5. 如果看到形如 __NF_TOKEN_0000__ 的占位符，必须原样保留，不允许改动、不允许翻译、不允许重新编号。\n"
        "6. 如果源数据里确实提取不到有效卷信息，就返回 volumes: []，不要编造。\n\n"
        f"项目 brief：\n{compact_json(spec)}\n\n"
        f"固定分卷骨架：\n{compact_json(volume_skeleton)}\n\n"
        f"待规范化 JSON：\n{compact_json(raw_payload)}\n\n"
        f"输出 JSON 结构：\n{compact_json(shape)}"
    )


def volume_outline_system_prompt() -> str:
    return "你是连载结构编辑。你负责把当前分卷拆成章节目标，只返回 JSON。"


def volume_outline_user_prompt(
    spec: ProjectSpec,
    bible: WorldBible,
    book_outline: BookOutline,
    volume: VolumeBlueprint,
    continuity: ContinuityState,
    chapter_skeleton: list[dict],
    power_system: PowerSystemBible | None = None,
) -> str:
    shape = {
        "volume_index": volume.index,
        "title": volume.title,
        "goal": "本卷总体任务",
        "climax": "本卷高潮",
        "carry_over_threads": ["本卷必须承接的线索"],
        "tier_floor": "本卷起始台阶",
        "tier_target": "本卷目标台阶",
        "required_breakthrough": "本卷关键突破门槛",
        "resource_goal": "本卷必须拿到的核心资源",
        "enemy_band": "本卷主要敌人层级",
        "progression_payoff": "本卷升级回报",
        "chapter_targets": chapter_skeleton
    }
    return (
        "请把当前分卷拆成章节目标。\n"
        "要求：\n"
        "1. 必须严格使用给定章节编号、章节角色和 closing_mode，不得把本卷强行均分成和别卷相同的节奏。\n"
        "2. 每章都要推进局势，不能只做设定说明。\n"
        "2.0 如果本书启用了硬境界升级，每章都要知道自己是在训练、拿资源、过试炼、突破、巩固、挑战还是兑现回报，不能把升级写成一团含混的“继续变强”。\n"
        "2.1 chapter_targets 中每章的 target_chars / min / max / chapter_role / split_allowed / merge_allowed 都要被尊重，章节体量应服务故事，不要把所有章写成一样长。\n"
        "3. 非最终章的 closing_mode 如果是 chapter_hook 或 volume_hook，章末必须制造明确的未决动作或决定。\n"
        "4. 如果 closing_mode 是 book_closure，本章必须完成主线闭环和人物关键选择，不允许最后一段只拿“新案子/新来客/新秘密”当终句。\n"
        f"{_market_profile_guidance(spec.market_profile, stage='planning')}\n"
        f"{_progression_guidance(spec.progression_mode, spec.progression_flavor, spec.progression_pacing, stage='planning')}\n"
        "5. 只返回 JSON。\n\n"
        f"项目 brief：\n{compact_json(spec)}\n\n"
        f"设定圣经：\n{compact_json(bible)}\n\n"
        f"升级体系圣经（摘要）：\n{compact_json(_power_system_runtime_payload(power_system))}\n\n"
        f"全书分卷蓝图：\n{compact_json(book_outline)}\n\n"
        f"当前连续性状态：\n{compact_json(continuity)}\n\n"
        f"当前分卷：\n{compact_json(volume)}\n\n"
        f"固定章节骨架：\n{compact_json(chapter_skeleton)}\n\n"
        f"输出 JSON 结构：\n{compact_json(shape)}"
    )


def volume_outline_normalizer_system_prompt() -> str:
    return (
        "你是分卷章节蓝图 JSON 结构规范化器。"
        "你的任务只是在不改写故事内容的前提下，把已有分卷蓝图整理成规范 JSON。"
        "不得新增剧情、不得删改章节任务、不得改写事实。"
        "顶层必须是一个 JSON 对象。"
        "只返回 JSON。"
    )


def volume_outline_normalizer_user_prompt(
    volume: VolumeBlueprint,
    chapter_skeleton: list[dict],
    raw_payload: object,
) -> str:
    shape = {
        "volume_index": volume.index,
        "title": volume.title,
        "goal": "本卷总体任务",
        "climax": "本卷高潮",
        "carry_over_threads": ["本卷必须承接的线索"],
        "chapter_targets": chapter_skeleton,
    }
    return (
        "请把下面已有的分卷章节蓝图 JSON 规范化为正式结构。\n"
        "硬要求：\n"
        "1. 顶层必须是一个 JSON 对象，不允许返回数组。\n"
        "2. 只做结构规范化，不要改写故事内容，不要新增剧情，不要补造不存在的章节。\n"
        "3. 正式章节字段名必须是 chapter_targets；如果源数据用了 chapters、chapter_outlines、chapter_items、targets 或 items，请统一映射成 chapter_targets。\n"
        "4. 如果源数据被拆成多个命名块，请合并成一个对象。\n"
        "5. 如果看到形如 __NF_TOKEN_0000__ 的占位符，必须原样保留，不允许改动、不允许翻译、不允许重新编号。\n"
        "6. 如果源数据里确实提取不到有效章节目标，就返回 chapter_targets: []，不要编造。\n\n"
        f"当前分卷：\n{compact_json(volume)}\n\n"
        f"固定章节骨架：\n{compact_json(chapter_skeleton)}\n\n"
        f"待规范化 JSON：\n{compact_json(raw_payload)}\n\n"
        f"输出 JSON 结构：\n{compact_json(shape)}"
    )


def structured_mapping_normalizer_system_prompt() -> str:
    return (
        "你是结构化 JSON 规范化器。"
        "你的任务只是在不编造新内容的前提下，把已有结构化返回整理成规范 JSON 对象。"
        "不得新增剧情、不得虚构不存在的信息、不得删改已明确给出的事实。"
        "顶层必须是一个 JSON 对象。"
        "只返回 JSON。"
    )


def structured_mapping_normalizer_user_prompt(
    step_label: str,
    shape: object,
    raw_payload: object,
    rules: list[str] | None = None,
) -> str:
    rule_lines = "\n".join(f"{idx}. {rule}" for idx, rule in enumerate(rules or [], start=1))
    if not rule_lines:
        rule_lines = "1. 只做结构规范化，不要编造不存在的信息。"
    return (
        f"请把下面已有的 {step_label} JSON 规范化为正式结构。\n"
        "硬要求：\n"
        f"{rule_lines}\n\n"
        f"待规范化 JSON：\n{compact_json(raw_payload)}\n\n"
        f"输出 JSON 结构：\n{compact_json(shape)}"
    )


def chapter_plan_system_prompt() -> str:
    return "你是剧情拆解编辑。你把章节目标拆成可直接写作的场景卡，只返回 JSON。"


def _normalized_market_profile(value: str | None) -> str:
    normalized = _best_text(value, "").strip().lower().replace("-", "_")
    return "tomato_mass" if normalized in {"tomato_mass", "tomato", "番茄", "番茄爆款"} else "qidian_longform"


def _market_profile_label(value: str | None) -> str:
    return "番茄爆款" if _normalized_market_profile(value) == "tomato_mass" else "起点长篇"


def _market_profile_guidance(value: str | None, *, stage: str) -> str:
    profile = _normalized_market_profile(value)
    if stage == "planning":
        if profile == "tomato_mass":
            return (
                "平台模式补充要求（番茄爆款）：\n"
                "1. 前 30 到 100 章追读优先，黄金三章必须尽快露出卖点、危机、回报路径和下一步钩子。\n"
                "2. 优先低门槛、强反馈、快兑现，少堆制度词和抽象概念词。\n"
                "3. 前中段要主动安排换气、生活感、关系张力和短周期赢点，避免长时间只靠体系程序推进。\n"
                "4. 章节目标和卷目标应优先服务追读，不要把所有精彩内容都押到远端长线回收。"
            )
        return (
            "平台模式补充要求（起点长篇）：\n"
            "1. 更强调长线升级、体系自洽、阶段递进和后期不崩。\n"
            "2. 可以容忍更强设定密度与制度细节，但必须保持回报链、升级链和长弧闭环。\n"
            "3. 分卷和章节应优先服务长期结构，不要为了短期爆点破坏后续承重。 "
        )
    if stage == "prose":
        if profile == "tomato_mass":
            return (
                "平台模式补充要求（番茄爆款）：\n"
                "1. 句子更白更快，信息第一次出现就尽量让人读懂。\n"
                "2. 强化情绪反馈、关系刺激、现实代价和章尾钩子，减少术语堆叠和流程复述。\n"
                "3. 同样的制度推进只保留最有爽感或最有代价的一刀，不要连续程序化走单。"
            )
        return (
            "平台模式补充要求（起点长篇）：\n"
            "1. 允许更稳的铺垫、更强的体系细节和更长的长线回收，但每章仍要有明确推进。\n"
            "2. 可以写制度、规则和层级，但要保持可复述、可兑现，避免空转解释。"
        )
    if profile == "tomato_mass":
        return (
            "平台模式补充要求（番茄爆款）：\n"
            "1. 对重复开场、程序词过密、长期高压不换气、回报不足和章节偏长要更严格。\n"
            "2. 优先判断追读抓力、可读性和爽点兑现，不要只看整书工整。"
        )
    return (
        "平台模式补充要求（起点长篇）：\n"
        "1. 更重长弧闭环、体系稳定、阶段递进和后期逻辑完整。\n"
        "2. 允许适度长章和体系细节，但不能接受后期失控重复或逻辑漂移。"
    )


def _normalized_progression_mode(value: str | None) -> str:
    normalized = _best_text(value, "").strip().lower().replace("-", "_")
    return "hard_realm_progression" if normalized in {"hard_realm_progression", "hard_realm", "hard_progression"} else "soft_progression"


def _progression_mode_label(value: str | None) -> str:
    return "硬境界升级" if _normalized_progression_mode(value) == "hard_realm_progression" else "叙事升级"


def _normalized_progression_flavor(value: str | None) -> str:
    normalized = _best_text(value, "").strip().lower().replace("-", "_")
    if normalized == "xuanhuan_fast":
        return "xuanhuan_fast"
    if normalized == "xianxia_steady":
        return "xianxia_steady"
    if normalized == "sci_fi_evolution":
        return "sci_fi_evolution"
    return ""


def _progression_flavor_label(value: str | None) -> str:
    flavor = _normalized_progression_flavor(value)
    if flavor == "xuanhuan_fast":
        return "玄幻快升流"
    if flavor == "xianxia_steady":
        return "仙侠稳升流"
    if flavor == "sci_fi_evolution":
        return "科幻进化流"
    return "自动"


def _normalized_progression_pacing(value: str | None) -> str:
    normalized = _best_text(value, "").strip().lower().replace("-", "_")
    if normalized in {"fast", "slow"}:
        return normalized
    return "steady"


def _progression_guidance(mode: str | None, flavor: str | None, pacing: str | None, *, stage: str) -> str:
    normalized_mode = _normalized_progression_mode(mode)
    normalized_flavor = _normalized_progression_flavor(flavor)
    normalized_pacing = _normalized_progression_pacing(pacing)
    if normalized_mode != "hard_realm_progression":
        return (
            "升级模式补充要求（叙事升级）：\n"
            "1. 允许主角通过资源、关系、权限、规则掌握、势力位置和副技能持续变强，不强制每卷都显式突破大境界。\n"
            "2. 仍需保持阶段目标、阶段回报和更高层压迫的清晰递进，不能只写模糊成长感。"
        )
    flavor_line = {
        "xuanhuan_fast": "优先短周期突破、强敌抬阶和显式层级跨越。",
        "xianxia_steady": "允许大境界提升更慢，但丹药、法器、洞府、秘境、人脉和副轴进展必须持续。",
        "sci_fi_evolution": "要把生命层级、资源层级和区域层级一起做成清楚台阶。",
    }.get(normalized_flavor, "按题材自动选择最稳的硬升级写法。")
    pacing_line = {
        "fast": "突破和阶段回报要更密，不能长期蓄而不发。",
        "steady": "突破、资源和强敌梯度要均衡递进。",
        "slow": "突破可以更慢，但准备、卡点、资源和副轴增长必须持续可见。",
    }[normalized_pacing]
    return (
        "升级模式补充要求（硬境界升级）：\n"
        "1. 必须明确主升级轴、突破条件、资源梯度和强敌梯度，不能只写模糊的“继续变强”。\n"
        "2. 每一卷和每个阶段都要知道主角当前处于哪一层、要冲哪一层、卡点是什么、要拿什么资源、要打什么门槛。\n"
        f"3. {flavor_line}\n"
        f"4. {pacing_line}\n"
        f"5. 在 {stage} 阶段，必须把升级体系当成结构骨架，而不是可有可无的背景纹理。"
    )


def _project_runtime_payload(spec: ProjectSpec) -> dict:
    return {
        "title": spec.title,
        "genre": spec.genre,
        "audience": spec.audience,
        "tone": spec.tone,
        "premise": spec.premise,
        "theme": spec.theme,
        "hook": spec.hook,
        "ending_mode": spec.ending_mode,
        "pov": spec.pov,
        "structure_mode": spec.structure_mode,
        "market_profile": spec.market_profile,
        "market_profile_label": _market_profile_label(spec.market_profile),
        "progression_mode": spec.progression_mode,
        "progression_mode_label": _progression_mode_label(spec.progression_mode),
        "progression_flavor": spec.progression_flavor,
        "progression_flavor_label": _progression_flavor_label(spec.progression_flavor),
        "progression_pacing": _normalized_progression_pacing(spec.progression_pacing),
        "power_system_hint": spec.power_system_hint,
        "target_chars_per_chapter": spec.target_chars_per_chapter,
        "chapter_char_tolerance": spec.chapter_char_tolerance,
    }


def _power_system_runtime_payload(power_system: PowerSystemBible | None) -> dict:
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
                "bottlenecks": item.bottlenecks[:2],
                "typical_resources": item.typical_resources[:3],
            }
            for item in power_system.realm_ladder[:8]
        ],
        "resource_axes": [
            {
                "name": item.name,
                "purpose": item.purpose,
                "acquisition_modes": item.acquisition_modes[:3],
            }
            for item in power_system.resource_axes[:5]
        ],
        "enemy_ladder": [
            {
                "name": item.name,
                "floor_tier": item.floor_tier,
                "ceiling_tier": item.ceiling_tier,
                "pressure_sources": item.pressure_sources[:3],
                "expected_payoffs": item.expected_payoffs[:3],
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
                "required_resources": item.required_resources[:3],
                "key_trial": item.key_trial,
                "payoff": item.payoff,
            }
            for item in power_system.milestone_plan[:8]
        ],
        "forbidden_shortcuts": power_system.forbidden_shortcuts[:6],
    }


def _chapter_length_range(spec: ProjectSpec, *, target_chars: int | None = None) -> tuple[int, int]:
    tolerance = max(0.05, min(0.4, float(spec.chapter_char_tolerance or 0.25)))
    target = max(1, int(target_chars or spec.target_chars_per_chapter or 2000))
    return int(math.floor(target * (1.0 - tolerance))), int(math.ceil(target * (1.0 + tolerance)))


def _chapter_length_hard_max(spec: ProjectSpec, *, target_chars: int | None = None) -> int:
    resolved_target = max(1, int(target_chars or spec.target_chars_per_chapter or 2000))
    _, chapter_max_chars = _chapter_length_range(spec, target_chars=resolved_target)
    return chapter_max_chars + chapter_length_grace(resolved_target)


def _chapter_length_extreme_max(spec: ProjectSpec, *, target_chars: int | None = None, multiplier: float = 3.0) -> int:
    resolved_target = max(1, int(target_chars or spec.target_chars_per_chapter or 2000))
    _, chapter_max_chars = _chapter_length_range(spec, target_chars=resolved_target)
    return max(_chapter_length_hard_max(spec, target_chars=resolved_target), int(chapter_max_chars * max(1.0, float(multiplier or 3.0))))


def _strict_short_length_spec(spec: ProjectSpec) -> bool:
    target_total_chars = int(spec.target_total_chars or 0)
    return 0 < target_total_chars < 20000


def _chapter_length_targets(
    spec: ProjectSpec,
    *,
    chapter: ChapterOutlineItem | None = None,
    plan: ChapterPlan | None = None,
) -> tuple[int, int, int, int]:
    target = max(
        1,
        int(
            (plan.target_chars if plan and plan.target_chars else None)
            or (chapter.target_chars if chapter and chapter.target_chars else None)
            or spec.target_chars_per_chapter
            or 2000
        ),
    )
    lower = (
        int(plan.target_chars_min)
        if plan and plan.target_chars_min
        else int(chapter.target_chars_min)
        if chapter and chapter.target_chars_min
        else _chapter_length_range(spec, target_chars=target)[0]
    )
    upper = (
        int(plan.target_chars_max)
        if plan and plan.target_chars_max
        else int(chapter.target_chars_max)
        if chapter and chapter.target_chars_max
        else _chapter_length_range(spec, target_chars=target)[1]
    )
    hard_max = max(upper, _chapter_length_hard_max(spec, target_chars=target))
    return target, lower, upper, hard_max


def _world_runtime_payload(bible: WorldBible) -> dict:
    return {
        "title": bible.title,
        "logline": bible.logline,
        "setting_summary": bible.setting_summary,
        "core_conflict": bible.core_conflict,
        "theme_statement": bible.theme_statement,
        "world_rules": bible.world_rules[:6],
        "chapter_guardrails": bible.chapter_guardrails[:6],
        "ending_contract": bible.ending_contract[:6],
        "major_threads": bible.major_threads[:8],
        "characters": [
            {
                "name": character.name,
                "role": character.role,
                "goal": character.goal,
                "arc": character.arc,
                "speaking_style": character.speaking_style,
                "do_not_break": character.do_not_break[:2],
            }
            for character in bible.characters[:6]
        ],
    }


def _book_outline_runtime_payload(book_outline: BookOutline) -> dict:
    return {
        "title": book_outline.title,
        "one_line_summary": book_outline.one_line_summary,
        "act_structure": book_outline.act_structure[:4],
        "volumes": [
            {
                "index": volume.index,
                "title": volume.title,
                "role": volume.role,
                "central_question": volume.central_question,
                "emotional_shift": volume.emotional_shift,
                "tier_floor": volume.tier_floor,
                "tier_target": volume.tier_target,
                "required_breakthrough": volume.required_breakthrough,
                "resource_goal": volume.resource_goal,
                "enemy_band": volume.enemy_band,
                "progression_payoff": volume.progression_payoff,
                "must_payoff": volume.must_payoff[:4],
            }
            for volume in book_outline.volumes[:6]
        ],
    }


def _volume_outline_runtime_payload(volume_outline: VolumeOutline) -> dict:
    return {
        "volume_index": volume_outline.volume_index,
        "title": volume_outline.title,
        "goal": volume_outline.goal,
        "climax": volume_outline.climax,
        "carry_over_threads": volume_outline.carry_over_threads[:6],
        "tier_floor": volume_outline.tier_floor,
        "tier_target": volume_outline.tier_target,
        "required_breakthrough": volume_outline.required_breakthrough,
        "resource_goal": volume_outline.resource_goal,
        "enemy_band": volume_outline.enemy_band,
        "progression_payoff": volume_outline.progression_payoff,
        "chapter_targets": [
            {
                "index": item.index,
                "title": item.title,
                "purpose": item.purpose,
                "conflict": item.conflict,
                "closing_mode": item.closing_mode,
                "progression_step_type": item.progression_step_type,
                "current_tier": item.current_tier,
                "target_tier": item.target_tier,
                "resource_focus": item.resource_focus,
                "enemy_band": item.enemy_band,
                "progression_reward": item.progression_reward,
                "progression_cost": item.progression_cost,
                "must_payoff": item.must_payoff[:4],
            }
            for item in volume_outline.chapter_targets
        ],
    }


def _chapter_runtime_payload(chapter: ChapterOutlineItem) -> dict[str, object]:
    return {
        "index": chapter.index,
        "volume_index": chapter.volume_index,
        "title": chapter.title,
        "purpose": chapter.purpose,
        "conflict": chapter.conflict,
        "beat_summary": chapter.beat_summary,
        "ending_note": chapter.ending_note,
        "chapter_role": chapter.chapter_role,
        "closing_mode": chapter.closing_mode,
        "target_chars": chapter.target_chars,
        "target_chars_min": chapter.target_chars_min,
        "target_chars_max": chapter.target_chars_max,
        "scene_load_score": chapter.scene_load_score,
        "progression_step_type": chapter.progression_step_type,
        "progression_reward": chapter.progression_reward,
        "progression_cost": chapter.progression_cost,
        "current_tier": chapter.current_tier,
        "target_tier": chapter.target_tier,
        "enemy_band": chapter.enemy_band,
        "resource_focus": chapter.resource_focus,
        "must_payoff": chapter.must_payoff[:6],
    }


def _plan_runtime_payload(plan: ChapterPlan) -> dict[str, object]:
    return {
        "chapter_index": plan.chapter_index,
        "chapter_title": plan.chapter_title,
        "purpose": plan.purpose,
        "continuity_targets": plan.continuity_targets[:6],
        "closing_mode": plan.closing_mode,
        "primary_propulsion": plan.primary_propulsion,
        "variation_goal": plan.variation_goal,
        "term_budget": plan.term_budget,
        "theme_visibility": plan.theme_visibility,
        "grounding_beat": plan.grounding_beat,
        "chapter_role": plan.chapter_role,
        "progression_step_type": plan.progression_step_type,
        "progression_reward": plan.progression_reward,
        "progression_cost": plan.progression_cost,
        "current_tier": plan.current_tier,
        "target_tier": plan.target_tier,
        "enemy_band": plan.enemy_band,
        "resource_focus": plan.resource_focus,
        "target_chars": plan.target_chars,
        "target_chars_min": plan.target_chars_min,
        "target_chars_max": plan.target_chars_max,
        "scenes": [
            {
                "scene_index": scene.scene_index,
                "scene_type": scene.scene_type,
                "location": scene.location,
                "goal": scene.goal,
                "conflict": scene.conflict,
                "turn": scene.turn,
                "must_include": scene.must_include[:3],
            }
            for scene in plan.scenes[:6]
        ],
    }


def _excerpt_trim_text(text: str, limit: int) -> str:
    stripped = (text or "").strip()
    if len(stripped) <= limit:
        return stripped
    if limit <= 3:
        return stripped[:limit]
    return stripped[: limit - 3].rstrip() + "..."


def _payload_value(item: object, key: str, default: object = "") -> object:
    if isinstance(item, dict):
        value = item.get(key, default)
    else:
        value = getattr(item, key, default)
    return default if value is None else value


def _payload_list(item: object, key: str) -> list[object]:
    value = _payload_value(item, key, [])
    return value if isinstance(value, list) else []


def _draft_excerpt_payload(
    draft: str,
    *,
    max_passages: int = 8,
    passage_chars: int = 360,
    edge_chars: int = 520,
) -> dict[str, object]:
    stripped = (draft or "").strip()
    if not stripped:
        return {
            "char_count": 0,
            "paragraph_count": 0,
            "opening_excerpt": "",
            "closing_excerpt": "",
            "sampled_passages": [],
        }
    paragraphs = [item.strip() for item in draft.split("\n\n") if item.strip()]
    if not paragraphs:
        paragraphs = [stripped]
    if len(paragraphs) <= max_passages:
        selected_indices = list(range(len(paragraphs)))
    else:
        span = max(1, max_passages - 1)
        selected_indices: list[int] = []
        for offset in range(max_passages):
            index = int(round(offset * (len(paragraphs) - 1) / span))
            if index not in selected_indices:
                selected_indices.append(index)
    return {
        "char_count": len(stripped),
        "paragraph_count": len(paragraphs),
        "opening_excerpt": _excerpt_trim_text("\n".join(paragraphs[:2]), edge_chars),
        "closing_excerpt": _excerpt_trim_text("\n".join(paragraphs[-2:]), edge_chars),
        "sampled_passages": [
            {
                "paragraph_index": index + 1,
                "text": _excerpt_trim_text(paragraphs[index], passage_chars),
            }
            for index in selected_indices
        ],
    }


def _continuity_runtime_payload(previous_state: ContinuityState) -> dict[str, object]:
    runtime = continuity_runtime_view(previous_state)
    runtime["counts"] = {
        "recent_summary_count": len(previous_state.recent_summaries),
        "active_thread_count": len(previous_state.active_threads),
        "resolved_thread_count": len(previous_state.resolved_threads),
        "timeline_count": len(previous_state.timeline),
        "must_remember_count": len(previous_state.must_remember),
        "character_state_count": len(previous_state.character_states),
        "progression_note_count": len(previous_state.progression_notes),
    }
    return runtime


def _progression_subset_payload(
    ledger: list[ProgressionLedgerItem],
    *,
    limit: int = 8,
) -> dict[str, object]:
    status_counts: dict[str, int] = {}
    for item in ledger:
        status = _best_text(_payload_value(item, "status", "pending"), "pending")
        status_counts[status] = status_counts.get(status, 0) + 1
    return {
        "count": len(ledger),
        "status_counts": status_counts,
        "focused_items": [
            {
                "milestone_label": _payload_value(item, "milestone_label", ""),
                "current_tier": _payload_value(item, "current_tier", ""),
                "target_tier": _payload_value(item, "target_tier", ""),
                "status": _payload_value(item, "status", "pending"),
                "last_touched_chapter": _payload_value(item, "last_touched_chapter", 0),
                "objective": _payload_value(item, "objective", ""),
                "required_resources": _payload_list(item, "required_resources")[:3],
                "unlocked_rewards": _payload_list(item, "unlocked_rewards")[:3],
                "bottleneck": _payload_value(item, "bottleneck", ""),
            }
            for item in ledger[:limit]
        ],
    }


def _promise_subset_payload(previous_promises: list[PromiseLedgerItem], *, limit: int = 10) -> dict[str, object]:
    status_counts: dict[str, int] = {}
    deadline_counts: dict[str, int] = {}
    for item in previous_promises:
        current_status = str(_payload_value(item, "current_status", "open") or "open")
        deadline_state = str(_payload_value(item, "deadline_state", "on_track") or "on_track")
        status_counts[current_status] = status_counts.get(current_status, 0) + 1
        deadline_counts[deadline_state] = deadline_counts.get(deadline_state, 0) + 1
    return {
        "count": len(previous_promises),
        "status_counts": status_counts,
        "deadline_counts": deadline_counts,
        "focused_items": [
            {
                "promise_id": _payload_value(item, "promise_id", ""),
                "label": _payload_value(item, "label", ""),
                "thread": _payload_value(item, "thread", ""),
                "current_status": _payload_value(item, "current_status", "open"),
                "last_touched_chapter": _payload_value(item, "last_touched_chapter", 0),
                "target_volume": _payload_value(item, "target_volume", 0),
                "overdue": bool(_payload_value(item, "overdue", False)),
                "payoff_requirements": _payload_list(item, "payoff_requirements")[:2],
            }
            for item in previous_promises[:limit]
        ],
    }


def _causality_subset_payload(previous_causality: list[CausalityEdge], *, limit: int = 8) -> dict[str, object]:
    return {
        "count": len(previous_causality),
        "focused_edges": [
            {
                "effect_label": _payload_value(item, "effect_label", ""),
                "cause": _payload_value(item, "cause", ""),
                "prerequisites": _payload_list(item, "prerequisites")[:2],
                "required_consequences": _payload_list(item, "required_consequences")[:2],
                "introduced_chapter": _payload_value(item, "introduced_chapter", 0),
                "last_verified_chapter": _payload_value(item, "last_verified_chapter", 0),
            }
            for item in previous_causality[:limit]
        ],
    }


def chapter_plan_user_prompt(
    spec: ProjectSpec,
    bible: WorldBible,
    book_outline: BookOutline,
    volume_outline: VolumeOutline,
    chapter: ChapterOutlineItem,
    continuity: ContinuityState,
    continuity_runtime: dict | None = None,
    retrieved_memory: list[dict[str, object]] | None = None,
    style_memory: list[dict[str, object]] | None = None,
    promise_memory: list[dict[str, object]] | None = None,
    causality_memory: list[dict[str, object]] | None = None,
    phase_brief: dict[str, object] | None = None,
    recent_propulsion_history: list[dict[str, object]] | None = None,
    logic_audit: object | None = None,
    restructure_notes: list[str] | None = None,
    previous_plan: object | None = None,
    power_system: PowerSystemBible | None = None,
) -> str:
    continuity_payload = continuity_runtime or continuity_runtime_view(continuity)
    shape = _chapter_plan_shape(chapter)
    return (
        "请为当前章节生成场景卡。\n"
        "要求：\n"
        "1. 3到6个场景。\n"
        "2. 每个场景都必须改变局势，而不是重复解释。\n"
        "2.1 必须输出 chapter_role、scene_load_score、target_chars、target_chars_min、target_chars_max、split_allowed、merge_allowed。\n"
        "2.2 scene_type 和 load_weight 要真实反映这一场的功能和负载，不要全写成同一种。\n"
        "3. continuity_targets 必须引用当前连续性状态里的线索、人物状态或未决问题。\n"
        "3.1 必须考虑承诺账本里即将兑现或已经逾期的事项，以及因果图里必须落地的后果。\n"
        "3.2 primary_propulsion 和 variation_goal 必须主动避免与最近几章重复同一发动机，不能连续多章都靠“发现线索 -> 进入节点 -> 得到更深解释”推进。\n"
        "3.3 如果 phase_brief 提示前段减脂，term_budget 必须偏低，且新术语必须绑定即时动作、代价或用途，不能连着空讲规则。\n"
        "3.4 theme_visibility 默认优先 subtext 或 edge，除非这一章本身就是公开立场碰撞，否则不要选 explicit-light 以上的外露方式。\n"
        "3.5 grounding_beat 必须具体，可直接写进正文，优先是食宿、伤势、钱、路程、天气、职业流程、人情往来、身体疲惫等落地信息。\n"
        "3.6 如果本章场景负载明显超出 target_chars_max，必须通过 split_allowed / merge_allowed 给出更保守的结构建议，而不是硬塞满一章。\n"
        "3.7 如果本书启用了硬境界升级，本章必须知道自己承担的是训练、拿资源、过试炼、突破、巩固、挑战还是兑现回报中的哪一种，不允许升级推进失焦。\n"
        "4. closing_mode 必须保留原样。\n"
        "4.1 如果下方给了【计划重排硬约束】，你必须先修正这些硬问题，再输出新的章节计划；不要只是换个说法，把同样的负载重新塞回一章。\n"
        f"{_market_profile_guidance(spec.market_profile, stage='planning')}\n"
        f"{_progression_guidance(spec.progression_mode, spec.progression_flavor, spec.progression_pacing, stage='planning')}\n"
        "5. 只返回 JSON。\n"
        "5.1 顶层必须是一个 JSON 对象，不允许返回数组。\n"
        "5.2 场景字段名必须是 scenes，不允许改名成 scene_cards、chapter_scenes、scene_list 或其他别名。\n"
        "5.3 不允许把计划拆成多个命名块数组；所有字段必须合并在同一个 JSON 对象里。\n\n"
        f"项目 brief（运行态摘要）：\n{compact_json(_project_runtime_payload(spec))}\n\n"
        f"设定圣经（运行态摘要）：\n{compact_json(_world_runtime_payload(bible))}\n\n"
        f"升级体系圣经（摘要）：\n{compact_json(_power_system_runtime_payload(power_system))}\n\n"
        f"全书分卷蓝图（摘要）：\n{compact_json(_book_outline_runtime_payload(book_outline))}\n\n"
        f"当前分卷章节表（摘要）：\n{compact_json(_volume_outline_runtime_payload(volume_outline))}\n\n"
        f"当前章节：\n{compact_json(chapter)}\n\n"
        f"当前连续性运行态摘要：\n{compact_json(continuity_payload)}\n\n"
        f"章节阶段约束：\n{compact_json(phase_brief or {})}\n\n"
        f"最近推进发动机历史：\n{compact_json(recent_propulsion_history or [])}\n\n"
        f"相关历史记忆：\n{compact_json(retrieved_memory or [])}\n\n"
        f"相关文风记忆：\n{compact_json(style_memory or [])}\n\n"
        f"相关承诺账本：\n{compact_json(promise_memory or [])}\n\n"
        f"相关因果约束：\n{compact_json(causality_memory or [])}\n\n"
        f"最新逻辑审计摘要：\n{compact_json(logic_audit_runtime_view(logic_audit))}\n\n"
        + (
            f"计划重排硬约束：\n{compact_json(restructure_notes or [])}\n\n"
            if restructure_notes
            else ""
        )
        + (
            f"上一版章节计划/返回（仅供纠偏，不能原样照抄）：\n{compact_json(previous_plan or {})}\n\n"
            if previous_plan
            else ""
        )
        +
        f"输出 JSON 结构：\n{compact_json(shape)}"
    )


def _chapter_plan_shape(chapter: ChapterOutlineItem) -> dict[str, object]:
    return {
        "chapter_index": chapter.index,
        "chapter_title": chapter.title,
        "purpose": chapter.purpose,
        "chapter_role": chapter.chapter_role,
        "scene_load_score": chapter.scene_load_score,
        "target_chars": chapter.target_chars,
        "target_chars_min": chapter.target_chars_min,
        "target_chars_max": chapter.target_chars_max,
        "split_allowed": chapter.split_allowed,
        "merge_allowed": chapter.merge_allowed,
        "progression_step_type": chapter.progression_step_type or "train|acquire|trial|breakthrough|consolidate|challenge|payoff",
        "progression_reward": chapter.progression_reward or "本章升级回报",
        "progression_cost": chapter.progression_cost or "本章升级代价",
        "current_tier": chapter.current_tier or "当前台阶",
        "target_tier": chapter.target_tier or "目标台阶",
        "enemy_band": chapter.enemy_band or "敌人层级",
        "resource_focus": chapter.resource_focus or "资源焦点",
        "continuity_targets": ["本章必须延续或兑现的内容"],
        "opening_image": "开场画面",
        "closing_image": "结尾画面",
        "closing_mode": chapter.closing_mode,
        "primary_propulsion": "本章主要靠什么发动剧情，例如关系推进/潜伏渗透/代价交换/动作压力/生活沉降/证据推进",
        "variation_goal": "相对于最近几章，本章刻意换什么推进手感",
        "term_budget": "术语预算，建议 low|medium|high，并说明理由",
        "theme_visibility": "主题显形方式，建议 subtext|edge|explicit-light",
        "grounding_beat": "本章必须落地的一处生活性、身体性或现实性细节",
        "scenes": [
            {
                "scene_index": 1,
                "scene_type": "grounding / investigation / conflict / reveal / setpiece / climax / afterglow / transition / dialogue",
                "load_weight": 1.0,
                "location": "地点",
                "goal": "角色意图",
                "conflict": "阻力",
                "turn": "局势变化",
                "must_include": ["必要元素"]
            }
        ]
    }


def chapter_plan_normalizer_system_prompt() -> str:
    return (
        "你是章节计划 JSON 结构规范化器。"
        "你的任务只是在不改写故事内容的前提下，把已有章节计划整理成规范 JSON。"
        "不得新增剧情、不得删除已有场景、不得改写事实。"
        "顶层必须是一个 JSON 对象。"
        "只返回 JSON。"
    )


def chapter_plan_normalizer_user_prompt(
    chapter: ChapterOutlineItem,
    raw_payload: object,
) -> str:
    shape = _chapter_plan_shape(chapter)
    return (
        "请把下面已有的章节计划 JSON 规范化为正式结构。\n"
        "硬要求：\n"
        "1. 顶层必须是一个 JSON 对象，不允许返回数组。\n"
        "2. 只做结构规范化，不要改写故事内容，不要新增剧情，不要补造不存在的场景。\n"
        "3. 正式场景字段名必须是 scenes；如果源数据用了 scene_cards、chapter_scenes、scene_list、scene_items 或 items，请统一映射成 scenes。\n"
        "4. scenes 里的每一项都必须是一个场景对象，不允许是字符串、数组或半结构文本块。\n"
        "5. 如果源数据被拆成多个命名块，请合并成一个对象。\n"
        "6. 如果看到形如 __NF_TOKEN_0000__ 的占位符，必须原样保留，不允许改动、不允许翻译、不允许重新编号。\n"
        "7. 如果源数据里确实提取不到有效场景，就返回 scenes: []，不要编造。\n\n"
        f"当前章节：\n{compact_json(chapter)}\n\n"
        f"待规范化 JSON：\n{compact_json(raw_payload)}\n\n"
        f"输出 JSON 结构：\n{compact_json(shape)}"
    )


def chapter_room_system_prompt() -> str:
    return (
        "你是章节写前会议记录员。"
        "你要把多个 agent 对当前章节的不同关注点整理成统一的会前纪要。"
        "只返回 JSON。"
    )


def chapter_room_user_prompt(
    spec: ProjectSpec,
    bible: WorldBible,
    chapter: ChapterOutlineItem,
    plan: ChapterPlan,
    style_bible: StyleBible | None = None,
    continuity: ContinuityState | None = None,
    voice_cards: list[CharacterVoiceCard] | None = None,
    retrieved_memory: list[dict[str, object]] | None = None,
    style_memory: list[dict[str, object]] | None = None,
    promise_memory: list[dict[str, object]] | None = None,
    causality_memory: list[dict[str, object]] | None = None,
    logic_audit: object | None = None,
    execution_packet: dict[str, object] | None = None,
) -> str:
    packet = execution_packet or build_execution_packet_view(
        chapter,
        plan,
        continuity_runtime_view(continuity or ContinuityState()),
        style_bible_runtime_view(style_bible or StyleBible()),
        voice_cards_runtime_view(voice_cards or []),
        story_memory=retrieved_memory,
        style_memory=style_memory,
        promise_memory=promise_memory,
        causality_memory=causality_memory,
        logic_audit=logic_audit,
    )
    shape = {
        "notes": [
            {
                "agent": "continuity_guard",
                "must_land": ["本章必须接住的连续性点"],
                "risks": ["最容易打架的地方"],
                "summary": "连续性视角总结"
            },
            {
                "agent": "drama_editor",
                "must_land": ["必须落地的冲突与转折"],
                "risks": ["节奏或戏剧张力风险"],
                "summary": "戏剧视角总结"
            },
            {
                "agent": "style_guard",
                "must_land": ["文风和表达边界"],
                "risks": ["容易写散或写浮的点"],
                "summary": "文风视角总结"
            }
        ],
        "shared_mandates": ["写手本章必须共同遵守的执行要求"],
        "blocking_issues": ["如果不解决，本章会出硬伤的问题"]
    }
    return (
        "请为当前章节生成写前会纪要。\n"
        "要求：\n"
        "1. notes 必须至少包含 continuity_guard、drama_editor、style_guard 三位 agent。\n"
        "2. shared_mandates 必须可以直接交给正文生成器执行。\n"
        "3. blocking_issues 只写真正会让本章不成立的风险。\n"
        "4. 不要重复章节计划原文，要指出重点和风险。\n"
        "4.1 必须明确提醒本章的术语预算、推进手感变化、主题外露等级和地面落点。\n"
        "4.2 若最新逻辑审计指出同构推进、人物同腔、长期高压或生活落地不足，本次纪要必须把对应矫正动作写进 shared_mandates。\n"
        f"{_market_profile_guidance(spec.market_profile, stage='planning')}\n"
        "5. 只返回 JSON。\n\n"
        f"项目 brief（运行态摘要）：\n{compact_json(_project_runtime_payload(spec))}\n\n"
        f"设定圣经（运行态摘要）：\n{compact_json(_world_runtime_payload(bible))}\n\n"
        f"章节执行包：\n{compact_json(packet)}\n\n"
        f"输出 JSON 结构：\n{compact_json(shape)}"
    )


def draft_system_prompt() -> str:
    return (
        "你是成熟的中文小说作者。"
        "正文必须好读、具体、克制、有画面，不准解释自己在写什么。"
        "只输出小说正文，不要标题、提纲、分点、注释。"
    )


def draft_user_prompt(
    spec: ProjectSpec,
    bible: WorldBible,
    style_bible: StyleBible,
    chapter: ChapterOutlineItem,
    plan: ChapterPlan,
    continuity: ContinuityState,
    voice_cards: list[CharacterVoiceCard],
    chapter_room: dict | None = None,
    retrieved_memory: list[dict[str, object]] | None = None,
    style_memory: list[dict[str, object]] | None = None,
    promise_memory: list[dict[str, object]] | None = None,
    causality_memory: list[dict[str, object]] | None = None,
    logic_audit: object | None = None,
    execution_packet: dict[str, object] | None = None,
) -> str:
    target_chars, chapter_min_chars, chapter_max_chars, chapter_hard_max = _chapter_length_targets(
        spec,
        chapter=chapter,
        plan=plan,
    )
    chapter_extreme_max = _chapter_length_extreme_max(spec, target_chars=target_chars)
    strict_length = _strict_short_length_spec(spec)
    packet = execution_packet or build_execution_packet_view(
        chapter,
        plan,
        continuity_runtime_view(continuity),
        style_bible_runtime_view(style_bible),
        voice_cards_runtime_view(voice_cards),
        story_memory=retrieved_memory,
        style_memory=style_memory,
        promise_memory=promise_memory,
        causality_memory=causality_memory,
        logic_audit=logic_audit,
        chapter_room=chapter_room,
    )
    length_rule = (
        f"1.1 低于下限会显得不够成立，高于上限会稀释节奏；若只比上限高出很少，最多也只能落在 {chapter_hard_max} 字以内。\n"
        if strict_length
        else f"1.1 中长篇优先保证情节与细节成立，高于上限只算节奏偏重，不应为了压字砍掉必要内容；只有超过异常阈值 {chapter_extreme_max} 字才算失控超长。\n"
    )
    return (
        "请根据以下资料写出本章正文。\n"
        "硬要求：\n"
        f"1. 使用简体中文，目标篇幅约 {target_chars} 字，允许区间是 {chapter_min_chars} 到 {chapter_max_chars} 字。\n"
        f"{length_rule}"
        "2. 按场景卡推进，不能漏掉关键转折。\n"
        "3. 人物行为必须符合设定与当前连续性状态。\n"
        "3.1 人物对白和情绪爆发方式必须遵守角色声线卡。\n"
        "4. 少讲道理，多用动作、细节、决定来表现冲突。\n"
        "4.1 文风优先遵守文风圣经和相关文风记忆，不要每章像换了作者。\n"
        "4.2 严格执行章节计划里的 primary_propulsion、variation_goal、term_budget、theme_visibility、grounding_beat。\n"
        "4.3 如果 term_budget 偏低，新术语必须立刻绑定用途、风险或代价，不能连续抛概念名词；若本章已接近术语预算上限，就优先复用既有叫法，不准再开新名词坑。\n"
        "4.4 如果 theme_visibility 是 subtext 或 edge，不要在情节成立后补一段理念说明，把主题压进动作、代价、对视、停顿和后果里。\n"
        "4.5 grounding_beat 必须真实落进正文，不要只剩悬空设定、节点和制度词；如果连续两章都高压推进，本章必须给出一次现实落地的换气。\n"
        "4.6 若最近几章已连续高压，本章要保留换气和生活质感，不能从头到尾都用同一强度顶着走。\n"
        "4.7 如果章节执行包里的 recent_propulsion_history 显示最近几章仍在同一推进簇，本章可以继续围绕同一核心问题推进，但必须带来新的后果、代价、站位变化或不同 scene 功能，不能只是“拿新证物/再抬一级”式原地打转。\n"
        "4.8 若本章已进入全书最后两章，至少两位核心角色的对白和情绪反应要保留可辨识的个人声口，不能一起收成同一种硬句式。\n"
        f"{_market_profile_guidance(spec.market_profile, stage='prose')}\n"
        "5. 不得出现“作者按”“待续”“这里略去”等占位词。\n"
        "5.1 若原始章节目标与章节计划或当前连续性状态冲突，以章节计划和当前连续性状态为准。\n"
        "5.2 若 closing_mode 是 chapter_hook，结尾必须把下一步压力或抉择顶到最前，不能在本章里把下一章动作先执行完。\n"
        "5.3 章节计划里每个 scene 的 must_include 都要真正落到正文里，不能只写出大意。\n"
        f"6. 结尾规则：{_closing_rule(chapter.closing_mode, spec.ending_mode)}\n\n"
        f"项目 brief（运行态摘要）：\n{compact_json(_project_runtime_payload(spec))}\n\n"
        f"设定圣经（运行态摘要）：\n{compact_json(_world_runtime_payload(bible))}\n\n"
        f"章节执行包：\n{compact_json(packet)}"
    )


def chapter_review_system_prompt() -> str:
    return "你是严苛的中文小说审校编辑。你必须挑出真实问题，只返回 JSON。"


def chapter_review_user_prompt(
    spec: ProjectSpec,
    bible: WorldBible,
    style_bible: StyleBible,
    chapter: ChapterOutlineItem,
    plan: ChapterPlan,
    draft: str,
    local_quality: dict,
    continuity: ContinuityState | None = None,
    voice_cards: list[CharacterVoiceCard] | None = None,
    retrieved_memory: list[dict[str, object]] | None = None,
    style_memory: list[dict[str, object]] | None = None,
    promise_memory: list[dict[str, object]] | None = None,
    causality_memory: list[dict[str, object]] | None = None,
    logic_audit: object | None = None,
    execution_packet: dict[str, object] | None = None,
) -> str:
    _, chapter_min_chars, chapter_max_chars, chapter_hard_max = _chapter_length_targets(
        spec,
        chapter=chapter,
        plan=plan,
    )
    chapter_extreme_max = _chapter_length_extreme_max(spec, target_chars=(plan.target_chars if plan and plan.target_chars else chapter.target_chars if chapter and chapter.target_chars else spec.target_chars_per_chapter))
    strict_length = _strict_short_length_spec(spec)
    packet = execution_packet or build_execution_packet_view(
        chapter,
        plan,
        continuity_runtime_view(continuity or ContinuityState()),
        style_bible_runtime_view(style_bible),
        voice_cards_runtime_view(voice_cards or []),
        story_memory=retrieved_memory,
        style_memory=style_memory,
        promise_memory=promise_memory,
        causality_memory=causality_memory,
        logic_audit=logic_audit,
    )
    shape = {
        "passed": True,
        "score": 88,
        "strengths": ["优点"],
        "issues": ["问题"],
        "required_fixes": ["如果不通过，需要怎样改"],
        "short_summary": "80字以内，概括本章发生了什么以及人物状态",
        "chapter_fixes": []
    }
    length_rule = (
        f"5.3 要检查章节实际篇幅是否落在 {chapter_min_chars} 到 {chapter_max_chars} 字之间；若只高出上限一点点但仍不超过 {chapter_hard_max} 字，可记为轻微问题但不应单独据此判失败。超过 {chapter_hard_max} 字仍算硬性超长。同时检查术语密度是否超出章节计划预算、最近几章是否在同一推进簇里出现明显空转、人物是否同腔同调、主题是否讲得过透、压力是否长期同频且缺少落地感。\n"
        if strict_length
        else f"5.3 要检查章节实际篇幅是否落在 {chapter_min_chars} 到 {chapter_max_chars} 字之间；中长篇若只是高于上限，应作为节奏和密度问题记录，不应单独据此判失败，只有超过异常阈值 {chapter_extreme_max} 字才算异常超长。同时检查术语密度是否超出章节计划预算、最近几章是否在同一推进簇里出现明显空转、人物是否同腔同调、主题是否讲得过透、压力是否长期同频且缺少落地感。\n"
    )
    return (
        "请审查下面的章节正文。\n"
        "通过标准：\n"
        "1. 故事清晰，冲突成立。\n"
        "2. 人物不崩，行动有动机。\n"
        "3. 与设定、文风圣经、角色声线卡和当前执行基准不冲突。\n"
        "4. 如果 closing_mode 是 book_closure，必须完成主线收束，不能用新事件当终句偷换成“下一本再说”。\n"
        "5. 如果 closing_mode 是 chapter_hook 或 volume_hook，章末必须形成明确牵引力。\n"
        "5.1 若原始章节目标中的 beat_summary 与章节计划或当前连续性状态冲突，以章节计划和当前连续性状态为准。\n"
        "5.2 要检查承诺账本是否被无故遗忘、因果链是否断裂。\n"
        f"{length_rule}"
        "5.4 如果本章已经把必须留给后续章节的接口、决定和现实动作铺好，而问题主要属于后续卷仍需继续推进的长线风险，这类内容写进 issues 即可，不应单独据此判定本章不通过。\n"
        "5.5 若章节执行包里的 recent_propulsion_history 显示最近几章仍在同一推进簇，要检查是否出现功能重复、升级方式重复、只是把同一结论再抬半级的空转；若本章位于最后两章，还要检查多名核心角色是否被写成同一种收束语气。\n"
        f"{_market_profile_guidance(spec.market_profile, stage='review')}\n"
        "6. 只返回 JSON。\n\n"
        f"项目 brief（运行态摘要）：\n{compact_json(_project_runtime_payload(spec))}\n\n"
        f"设定圣经（运行态摘要）：\n{compact_json(_world_runtime_payload(bible))}\n\n"
        f"章节执行包：\n{compact_json(packet)}\n\n"
        f"本地质量报告：\n{compact_json(local_quality)}\n\n"
        f"正文：\n{draft}\n\n"
        f"输出 JSON 结构：\n{compact_json(shape)}"
    )


def rewrite_user_prompt(
    spec: ProjectSpec,
    bible: WorldBible,
    style_bible: StyleBible,
    chapter: ChapterOutlineItem,
    plan: ChapterPlan,
    previous_draft: str,
    review: dict,
    continuity: ContinuityState,
    voice_cards: list[CharacterVoiceCard],
    execution_packet: dict[str, object] | None = None,
    chapter_room: dict | None = None,
    retrieved_memory: list[dict[str, object]] | None = None,
    style_memory: list[dict[str, object]] | None = None,
    promise_memory: list[dict[str, object]] | None = None,
    causality_memory: list[dict[str, object]] | None = None,
    logic_audit: object | None = None,
) -> str:
    target_chars, chapter_min_chars, chapter_max_chars, chapter_hard_max = _chapter_length_targets(
        spec,
        chapter=chapter,
        plan=plan,
    )
    chapter_extreme_max = _chapter_length_extreme_max(spec, target_chars=target_chars)
    strict_length = _strict_short_length_spec(spec)
    packet = execution_packet or build_execution_packet_view(
        chapter,
        plan,
        continuity_runtime_view(continuity),
        style_bible_runtime_view(style_bible),
        voice_cards_runtime_view(voice_cards),
        story_memory=retrieved_memory,
        style_memory=style_memory,
        promise_memory=promise_memory,
        causality_memory=causality_memory,
        logic_audit=logic_audit,
        chapter_room=chapter_room,
    )
    review_digest = _rewrite_review_digest(review, previous_draft)
    final_fix = review.get("final_fix") if isinstance(review, dict) else None
    is_final_fix = isinstance(final_fix, str) and final_fix.strip()
    length_rule = (
        f"1.1 重写时也必须遵守篇幅区间，不要靠无关扩写来掩盖问题；若确实无法完全压进常规区间，最高也不能超过 {chapter_hard_max} 字。\n"
        if strict_length
        else f"1.1 中长篇重写时优先修结构、节奏和信息分配，不要为了压字删掉必要细节；若未超过异常阈值 {chapter_extreme_max} 字，长度本身不应成为单独失败理由。\n"
    )
    polish_rules = (
        "2.0 若这是终审修订，优先做微创改稿：保留已成立的段落顺序、动作逻辑、有效台词和章末牵引，只修改被点名的问题。\n"
        "2.1 若上一稿已有成立段落，允许只重写相关段落后再接回，但最终仍要输出完整正文；不要为了修一个问题把其他已通过的部分改坏。\n"
        "2.2 若这是终审修订，除非 required_fixes 明确要求，否则不要额外扩写新支线、不要重排整章结构、不要把结尾改成作者总结腔。\n"
        if is_final_fix
        else ""
    )
    return (
        "请基于审校意见重写本章，不要局部修补，要直接给出新的完整正文。\n"
        "硬要求：\n"
        f"1. 保持约 {target_chars} 字，允许区间是 {chapter_min_chars} 到 {chapter_max_chars} 字。\n"
        f"{length_rule}"
        "2. 优先解决 required_fixes。\n"
        f"{polish_rules}"
        f"{_market_profile_guidance(spec.market_profile, stage='prose')}\n"
        "3. 保住原章节的核心剧情目的。\n"
        "3.0 文风、声线、承诺兑现、因果后果都必须和当前约束重新对齐。\n"
        "3.1 若原始章节目标与章节计划或当前连续性状态冲突，以章节计划和当前连续性状态为准。\n"
        "3.2 chapter_hook 结尾不能把下一章的关键动作提前执行完，要停在更强的未决压力上。\n"
        "3.3 章节计划里每个 scene 的 must_include 都要转成正文里的具体细节、动作或信息，而不是只写个结论。\n"
        f"4. 结尾规则：{_closing_rule(chapter.closing_mode, spec.ending_mode)}\n"
        "5. 只输出正文。\n\n"
        f"项目 brief（运行态摘要）：\n{compact_json(_project_runtime_payload(spec))}\n\n"
        f"设定圣经（运行态摘要）：\n{compact_json(_world_runtime_payload(bible))}\n\n"
        f"章节执行包：\n{compact_json(packet)}\n\n"
        f"上一稿摘要与修订边界：\n{compact_json(review_digest)}\n\n"
        f"审校意见：\n{compact_json(review)}"
    )


def compression_user_prompt(
    spec: ProjectSpec,
    bible: WorldBible,
    style_bible: StyleBible,
    chapter: ChapterOutlineItem,
    plan: ChapterPlan,
    previous_draft: str,
    review: dict,
    continuity: ContinuityState,
    voice_cards: list[CharacterVoiceCard],
    execution_packet: dict[str, object] | None = None,
    chapter_room: dict | None = None,
    retrieved_memory: list[dict[str, object]] | None = None,
    style_memory: list[dict[str, object]] | None = None,
    promise_memory: list[dict[str, object]] | None = None,
    causality_memory: list[dict[str, object]] | None = None,
    logic_audit: object | None = None,
) -> str:
    _, chapter_min_chars, chapter_max_chars, chapter_hard_max = _chapter_length_targets(
        spec,
        chapter=chapter,
        plan=plan,
    )
    chapter_extreme_max = _chapter_length_extreme_max(
        spec,
        target_chars=(plan.target_chars if plan and plan.target_chars else chapter.target_chars if chapter and chapter.target_chars else spec.target_chars_per_chapter),
    )
    strict_length = _strict_short_length_spec(spec)
    packet = execution_packet or build_execution_packet_view(
        chapter,
        plan,
        continuity_runtime_view(continuity),
        style_bible_runtime_view(style_bible),
        voice_cards_runtime_view(voice_cards),
        story_memory=retrieved_memory,
        style_memory=style_memory,
        promise_memory=promise_memory,
        causality_memory=causality_memory,
        logic_audit=logic_audit,
        chapter_room=chapter_room,
    )
    length_rule = (
        f"1. 最终正文优先落在 {chapter_min_chars} 到 {chapter_max_chars} 字之间；若只剩极小超额，绝不能超过 {chapter_hard_max} 字。\n"
        if strict_length
        else f"1. 这是异常超长修订。只有因为正文已超过异常阈值 {chapter_extreme_max} 字才会进入这一步；压缩时仍要优先保住必要细节与节奏。\n"
    )
    review_digest = _rewrite_review_digest(review, previous_draft)
    return (
        "请在不改变本章核心剧情、人物立场、线索结论和结尾牵引的前提下，把上一稿压缩到目标篇幅内。\n"
        "硬要求：\n"
        f"{length_rule}"
        "2. 优先删除或合并这些内容：重复环境描写、同一信息的换说、流程术语的重复解释、主题总结句、已经由动作表达过的心理说明。\n"
        "3. 保留章节计划里的所有关键 scene、must_include、closing_mode 和核心因果，不准把关键转折压没。\n"
        "4. 如果需要收缩，请优先把长段解释改成更短的动作、对白或具体现实判断。\n"
        f"{_market_profile_guidance(spec.market_profile, stage='prose')}\n"
        "5. 若本章是短篇或 standalone，结尾必须保留闭环/钩子强度，但不能靠新增信息扩字。\n"
        "6. 只输出完整正文。\n\n"
        f"项目 brief（运行态摘要）：\n{compact_json(_project_runtime_payload(spec))}\n\n"
        f"设定圣经（运行态摘要）：\n{compact_json(_world_runtime_payload(bible))}\n\n"
        f"章节执行包：\n{compact_json(packet)}\n\n"
        f"上一稿摘要与压缩重点：\n{compact_json(review_digest)}\n\n"
        f"原正文：\n{previous_draft}\n\n"
        f"审校意见：\n{compact_json(review)}"
    )


def _chapter_execution_reference(chapter: ChapterOutlineItem, plan: ChapterPlan) -> dict:
    return {
        "index": chapter.index,
        "volume_index": chapter.volume_index,
        "title": chapter.title,
        "purpose": plan.purpose or chapter.purpose,
        "conflict": chapter.conflict,
        "beat_summary": " / ".join(
            f"{scene.goal} -> {scene.turn}" for scene in plan.scenes
        ) or chapter.beat_summary,
        "ending_note": plan.closing_image or chapter.ending_note,
        "pov": chapter.pov,
        "closing_mode": plan.closing_mode or chapter.closing_mode,
        "primary_propulsion": plan.primary_propulsion,
        "variation_goal": plan.variation_goal,
        "term_budget": plan.term_budget,
        "theme_visibility": plan.theme_visibility,
        "grounding_beat": plan.grounding_beat,
        "must_payoff": list(dict.fromkeys([*chapter.must_payoff, *plan.continuity_targets])),
    }


def _rewrite_review_digest(review: dict, previous_draft: str) -> dict:
    model_review = review.get("model_review") if isinstance(review, dict) else {}
    local_review = review.get("local_review") if isinstance(review, dict) else {}
    keep = []
    must_fix = []
    if isinstance(model_review, dict):
        keep.extend(item for item in model_review.get("strengths", []) if isinstance(item, str))
        must_fix.extend(item for item in model_review.get("required_fixes", []) if isinstance(item, str))
        must_fix.extend(item for item in model_review.get("issues", []) if isinstance(item, str))
    if isinstance(local_review, dict):
        must_fix.extend(item for item in local_review.get("issues", []) if isinstance(item, str))
    final_fix = review.get("final_fix") if isinstance(review, dict) else None
    if isinstance(final_fix, str) and final_fix.strip():
        must_fix.append(final_fix.strip())
    summary = ""
    if isinstance(model_review, dict):
        summary = str(model_review.get("short_summary") or "").strip()
    if not summary and isinstance(local_review, dict):
        summary = str(local_review.get("short_summary") or "").strip()
    if not summary:
        summary = previous_draft.strip().replace("\n", " ")[:220]
    return {
        "previous_summary": summary,
        "keep": list(dict.fromkeys(keep))[:8],
        "must_fix": list(dict.fromkeys(must_fix))[:12],
    }


def continuity_system_prompt() -> str:
    return "你是连续性编辑。你负责从章节正文提取长期记忆更新，只返回 JSON。"


def continuity_user_prompt(
    spec: ProjectSpec,
    bible: WorldBible,
    chapter: ChapterOutlineItem,
    draft: str,
    previous_state: ContinuityState,
    *,
    power_system: PowerSystemBible | None = None,
    progression_ledger: list[ProgressionLedgerItem] | None = None,
) -> str:
    shape = {
        "chapter_index": chapter.index,
        "chapter_summary": "80字以内摘要",
        "new_threads": ["新引入但尚未解决的线索"],
        "resolved_threads": ["本章完成或关闭的线索"],
        "timeline_events": ["按时间顺序记录的关键事实"],
        "character_states": [
            {
                "name": "角色名",
                "current_goal": "当前目标",
                "emotional_state": "情绪状态",
                "relationship_shift": "关系变化",
                "risk": "当前风险",
                "unresolved": "仍未解决的问题"
            }
        ],
        "next_chapter_targets": ["下一章必须记住的推进点"],
        "must_remember": ["后文绝不能忘的事实或伏笔"],
        "progression_updates": ["本章推进了哪些升级约束、资源卡点或阶段回报"],
        "current_tier": "当前实际台阶",
        "next_breakthrough": "下一次突破门槛",
    }
    return (
        "请从章节正文中提取连续性更新。\n"
        "要求：\n"
        "1. chapter_summary 必须具体到人物决定和局势变化。\n"
        "2. new_threads 和 resolved_threads 不能重复堆空话。\n"
        "3. timeline_events 只写真实发生的事实，不写推测。\n"
        "4. must_remember 只保留后文必须继续尊重的内容。\n"
        "4.1 如果本书启用了硬境界升级，必须补充 progression_updates、current_tier、next_breakthrough，用来记录本章实际推进到的台阶、卡点和下一步突破门槛。\n"
        "4.1 你拿到的是正文摘录而不是全文；如果摘录不足以支撑某个字段，请留空或从章节目标中提炼，不要编造正文里没有发生的事实。\n"
        f"{_progression_guidance(spec.progression_mode, spec.progression_flavor, spec.progression_pacing, stage='review')}\n"
        "5. 只返回 JSON。\n\n"
        f"项目 brief（运行态摘要）：\n{compact_json(_project_runtime_payload(spec))}\n\n"
        f"设定圣经（运行态摘要）：\n{compact_json(_world_runtime_payload(bible))}\n\n"
        f"升级体系圣经（摘要）：\n{compact_json(_power_system_runtime_payload(power_system))}\n\n"
        f"升级账本（聚焦摘要）：\n{compact_json(_progression_subset_payload(progression_ledger or []))}\n\n"
        f"上一版连续性状态（运行态摘要）：\n{compact_json(_continuity_runtime_payload(previous_state))}\n\n"
        f"当前章节目标（运行态摘要）：\n{compact_json(_chapter_runtime_payload(chapter))}\n\n"
        f"正文摘录（开头/中段/结尾抽样，不是全文）：\n{compact_json(_draft_excerpt_payload(draft))}\n\n"
        f"输出 JSON 结构：\n{compact_json(shape)}"
    )


def long_memory_system_prompt() -> str:
    return (
        "你是长线记忆编辑。"
        "你负责从章节结果中更新伏笔承诺账本和因果图。"
        "只返回 JSON。"
    )


def long_memory_user_prompt(
    spec: ProjectSpec,
    bible: WorldBible,
    chapter: ChapterOutlineItem,
    plan: ChapterPlan,
    draft: str,
    previous_promises: list[PromiseLedgerItem],
    previous_causality: list[CausalityEdge],
    *,
    power_system: PowerSystemBible | None = None,
    previous_progression: list[ProgressionLedgerItem] | None = None,
) -> str:
    shape = {
        "chapter_index": chapter.index,
        "promise_updates": [
            {
                "promise_id": "promise-001",
                "label": "本章新种下或推进的承诺",
                "thread": "归属主线/人物线/情感线",
                "chapter_opened": chapter.index,
                "target_volume": chapter.volume_index,
                "current_status": "open|advanced|paid_off|stalled",
                "last_touched_chapter": chapter.index,
                "payoff_requirements": ["后续兑现条件"],
                "overdue": False,
            }
        ],
        "causality_updates": [
            {
                "effect_label": "本章形成的结果",
                "cause": "触发原因",
                "prerequisites": ["成立前置条件"],
                "required_consequences": ["后续必须发生的结果"],
                "introduced_chapter": chapter.index,
                "last_verified_chapter": chapter.index,
            }
        ],
        "progression_updates": [
            {
                "milestone_label": "当前推进到的升级里程碑",
                "current_tier": "当前台阶",
                "target_tier": "目标台阶",
                "status": "pending|ready|advanced|paid_off",
                "opened_chapter": chapter.index,
                "last_touched_chapter": chapter.index,
                "objective": "本阶段核心目标",
                "required_resources": ["仍缺的资源/条件"],
                "unlocked_rewards": ["本章拿到的回报"],
                "bottleneck": "当前卡点",
            }
        ],
    }
    return (
        "请更新这本书的承诺账本和因果图。\n"
        "要求：\n"
        "1. promise_updates 只记录真的会影响后文兑现的承诺、伏笔、任务或关系债务。\n"
        "2. current_status 只能是 open、advanced、paid_off、stalled。\n"
        "3. 如果本章兑现了旧承诺，必须优先在给定的相关承诺账本子集里复用原 promise_id，并把 current_status 设为 paid_off。\n"
        "3.1 overdue 只在承诺已经明显超过应兑现窗口、且本章没有形成真实推进时才标 true。对已经推进到 advanced 的承诺，不要仅因仍未最终兑付就标 overdue。\n"
        "4. causality_updates 只记录可追溯的因果，不写空泛感想。\n"
        "4.3 如果本书启用了硬境界升级，必须同步更新 progression_updates，记录本章推进了哪个阶段目标、拿到了哪些回报、还缺什么条件，不要让升级系统只活在大纲里。\n"
        "4.1 给你的账本和因果图只是相关子集，不是全量旧档案；请基于相关上下文输出本章需要新增或修正的 delta，不要试图重写整本旧账。\n"
        "4.2 你拿到的是正文摘录而不是全文；若摘录不足以支撑某个更新，请留空，不要编造新的承诺或因果。\n"
        f"{_progression_guidance(spec.progression_mode, spec.progression_flavor, spec.progression_pacing, stage='review')}\n"
        "5. 只返回 JSON。\n\n"
        f"项目 brief（运行态摘要）：\n{compact_json(_project_runtime_payload(spec))}\n\n"
        f"设定圣经（运行态摘要）：\n{compact_json(_world_runtime_payload(bible))}\n\n"
        f"升级体系圣经（摘要）：\n{compact_json(_power_system_runtime_payload(power_system))}\n\n"
        f"当前章节目标（运行态摘要）：\n{compact_json(_chapter_runtime_payload(chapter))}\n\n"
        f"章节计划（运行态摘要）：\n{compact_json(_plan_runtime_payload(plan))}\n\n"
        f"相关承诺账本摘要：\n{compact_json(_promise_subset_payload(previous_promises))}\n\n"
        f"相关因果图摘要：\n{compact_json(_causality_subset_payload(previous_causality))}\n\n"
        f"相关升级账本摘要：\n{compact_json(_progression_subset_payload(previous_progression or []))}\n\n"
        f"正文摘录（开头/中段/结尾抽样，不是全文）：\n{compact_json(_draft_excerpt_payload(draft))}\n\n"
        f"输出 JSON 结构：\n{compact_json(shape)}"
    )


def _logic_audit_book_outline_payload(
    book_outline: BookOutline,
    *,
    current_volume_index: int,
) -> dict[str, object]:
    focus_window = [
        {
            "index": volume.index,
            "title": volume.title,
            "role": volume.role,
            "chapter_range": [volume.start_chapter, volume.end_chapter],
            "central_question": volume.central_question,
            "emotional_shift": volume.emotional_shift,
            "tier_floor": volume.tier_floor,
            "tier_target": volume.tier_target,
            "required_breakthrough": volume.required_breakthrough,
            "resource_goal": volume.resource_goal,
            "enemy_band": volume.enemy_band,
            "progression_payoff": volume.progression_payoff,
            "must_payoff": volume.must_payoff[:4],
        }
        for volume in book_outline.volumes
        if abs(volume.index - current_volume_index) <= 2
    ]
    return {
        "title": book_outline.title,
        "one_line_summary": book_outline.one_line_summary,
        "act_structure": book_outline.act_structure[:4],
        "volume_count": len(book_outline.volumes),
        "focus_window": focus_window,
    }


def _logic_audit_chapter_payload(chapter: ChapterResult) -> dict[str, object]:
    return {
        "index": chapter.index,
        "title": chapter.title,
        "purpose": chapter.plan.purpose,
        "summary": chapter.continuity.chapter_summary,
        "primary_propulsion": chapter.plan.primary_propulsion,
        "variation_goal": chapter.plan.variation_goal,
        "term_budget": chapter.plan.term_budget,
        "theme_visibility": chapter.plan.theme_visibility,
        "grounding_beat": chapter.plan.grounding_beat,
        "progression_step_type": chapter.plan.progression_step_type,
        "current_tier": chapter.plan.current_tier,
        "target_tier": chapter.plan.target_tier,
        "progression_reward": chapter.plan.progression_reward,
        "progression_cost": chapter.plan.progression_cost,
        "new_threads": chapter.continuity.new_threads[:4],
        "resolved_threads": chapter.continuity.resolved_threads[:4],
        "must_remember": chapter.continuity.must_remember[:4],
    }


def _logic_audit_section_digests(
    chapters: list[ChapterResult],
    *,
    section_size: int = 10,
    recent_keep: int = 8,
) -> dict[str, object]:
    ordered = sorted(chapters, key=lambda item: item.index)
    recent = [_logic_audit_chapter_payload(item) for item in ordered[-recent_keep:]]
    earlier = ordered[:-recent_keep] if len(ordered) > recent_keep else []
    sections: list[dict[str, object]] = []
    for offset in range(0, len(earlier), section_size):
        chunk = earlier[offset : offset + section_size]
        if not chunk:
            continue
        propulsion_mix = list(
            dict.fromkeys(
                _best_text(item.plan.primary_propulsion)
                for item in chunk
                if _best_text(item.plan.primary_propulsion)
            )
        )[:4]
        watch_threads = list(
            dict.fromkeys(
                thread
                for item in chunk
                for thread in (
                    item.continuity.new_threads[:2]
                    + item.continuity.must_remember[:2]
                )
                if _best_text(thread)
            )
        )[:6]
        summary_points = [
            _best_text(chunk[0].continuity.chapter_summary),
            _best_text(chunk[len(chunk) // 2].continuity.chapter_summary),
            _best_text(chunk[-1].continuity.chapter_summary),
        ]
        sections.append(
            {
                "chapter_range": [chunk[0].index, chunk[-1].index],
                "summary": "；".join(item for item in summary_points if item)[:280],
                "propulsion_mix": propulsion_mix,
                "watch_threads": watch_threads,
            }
        )
    return {
        "recent_chapters": recent,
        "earlier_section_digests": sections,
    }


def _logic_audit_continuity_payload(continuity: ContinuityState) -> dict[str, object]:
    return {
        "last_volume_index": continuity.last_volume_index,
        "last_chapter_index": continuity.last_chapter_index,
        "recent_summaries": continuity.recent_summaries[-6:],
        "active_threads": continuity.active_threads[:10],
        "resolved_threads": continuity.resolved_threads[:8],
        "must_remember": continuity.must_remember[:10],
        "progression_notes": continuity.progression_notes[-8:],
        "current_tier": continuity.current_tier,
        "next_breakthrough": continuity.next_breakthrough,
        "character_states": [
            {
                "name": state.name,
                "current_goal": state.current_goal,
                "emotional_state": state.emotional_state,
                "relationship_shift": state.relationship_shift,
                "risk": state.risk,
                "unresolved": state.unresolved,
            }
            for state in continuity.character_states[:6]
        ],
    }


def _logic_audit_promise_payload(
    promise_ledger: list[PromiseLedgerItem],
    *,
    limit: int = 12,
) -> dict[str, object]:
    counts = {
        "total": len(promise_ledger),
        "open": 0,
        "advanced": 0,
        "paid_off": 0,
        "stalled": 0,
        "at_risk": 0,
        "overdue": 0,
    }
    for item in promise_ledger:
        counts[item.current_status if item.current_status in counts else "open"] += 1
        if item.deadline_state == "at_risk":
            counts["at_risk"] += 1
        if item.deadline_state == "overdue" or item.overdue:
            counts["overdue"] += 1
    focused = sorted(
        promise_ledger,
        key=lambda item: (
            item.deadline_state == "overdue" or item.overdue,
            item.deadline_state == "at_risk",
            item.current_status != "paid_off",
            item.last_touched_chapter,
        ),
        reverse=True,
    )
    return {
        "counts": counts,
        "focused_items": [
            {
                "promise_id": item.promise_id,
                "label": item.label,
                "thread": item.thread,
                "current_status": item.current_status,
                "deadline_state": item.deadline_state,
                "last_touched_chapter": item.last_touched_chapter,
                "target_volume": item.target_volume,
                "payoff_requirements": item.payoff_requirements[:3],
            }
            for item in focused[:limit]
        ],
    }


def _logic_audit_causality_payload(
    causality_graph: list[CausalityEdge],
    *,
    limit: int = 10,
) -> dict[str, object]:
    focused = sorted(
        causality_graph,
        key=lambda item: (item.last_verified_chapter, item.introduced_chapter),
        reverse=True,
    )
    return {
        "edge_count": len(causality_graph),
        "focused_edges": [
            {
                "effect_label": item.effect_label,
                "cause": item.cause,
                "prerequisites": item.prerequisites[:3],
                "required_consequences": item.required_consequences[:4],
                "introduced_chapter": item.introduced_chapter,
                "last_verified_chapter": item.last_verified_chapter,
            }
            for item in focused[:limit]
        ],
    }


def _logic_audit_previous_audit_payload(previous_audit: object | None) -> dict[str, object]:
    if not isinstance(previous_audit, dict):
        return {}
    return {
        "gate_passed": previous_audit.get("gate_passed", previous_audit.get("passed", True)),
        "gate_level": previous_audit.get("gate_level"),
        "summary": previous_audit.get("summary"),
        "issues": list(previous_audit.get("issues") or [])[:4],
        "progression_risks": list(previous_audit.get("progression_risks") or [])[:4],
        "watch_items": list(previous_audit.get("watch_items") or [])[:4],
        "required_followups": list(previous_audit.get("required_followups") or [])[:4],
    }


def _final_review_logic_audits_payload(logic_audits: list[object] | None) -> list[dict[str, object]]:
    payloads: list[dict[str, object]] = []
    for item in list(logic_audits or [])[-4:]:
        if not isinstance(item, dict):
            continue
        payloads.append(
            {
                "gate_passed": item.get("gate_passed", item.get("passed", True)),
                "gate_level": item.get("gate_level"),
                "summary": item.get("summary"),
                "issues": list(item.get("issues") or [])[:4],
                "progression_risks": list(item.get("progression_risks") or [])[:4],
                "watch_items": list(item.get("watch_items") or [])[:4],
                "required_followups": list(item.get("required_followups") or [])[:4],
            }
        )
    return payloads


def logic_audit_system_prompt() -> str:
    return (
        "你是长篇逻辑审计编辑。"
        "你负责检查跨章节主线、人物状态、证据链和承诺兑现是否稳定。"
        "不要给文学赞美，只返回 JSON。"
    )


def logic_audit_user_prompt(
    spec: ProjectSpec,
    bible: WorldBible,
    book_outline: BookOutline,
    volume_outline: VolumeOutline,
    chapters: list[ChapterResult],
    continuity: ContinuityState,
    promise_ledger: list[PromiseLedgerItem],
    causality_graph: list[CausalityEdge],
    previous_audit: object | None = None,
    ledger_sanity: dict[str, object] | None = None,
    *,
    power_system: PowerSystemBible | None = None,
    progression_ledger: list[ProgressionLedgerItem] | None = None,
) -> str:
    shape = {
        "passed": True,
        "gate_passed": True,
        "gate_level": "pass|warn|repair_metadata|repair_cluster|hard_fail",
        "summary": "60字以内，概括当前长线状态",
        "issues": ["已出现或即将出现的跨章节逻辑问题"],
        "watch_items": ["后续必须持续盯住的长线约束"],
        "required_followups": ["下一卷或后续章节必须兑现的事项"],
        "structure_risks": ["是否出现同构推进或章节发动机单一"],
        "voice_risks": ["人物说话是否越来越同频"],
        "density_risks": ["术语、制度、流程说明是否压住阅读"],
        "pressure_risks": ["压力曲线是否长期同频高压"],
        "grounding_risks": ["生活落地感、现实代价、身体感是否不足"],
        "progression_risks": ["升级系统是否失真、消失、跳级或无代价突破"],
        "flagged_chapters": [{"chapter_index": chapters[-1].index if chapters else 1, "reason": "需要重点回看"}],
        "repair_plan": [
            {
                "start_chapter": chapters[-1].index if chapters else 1,
                "end_chapter": chapters[-1].index if chapters else 1,
                "instruction": "若 gate_passed 为 false，需要怎样成片回修",
            }
        ],
    }
    chapter_payload = _logic_audit_section_digests(chapters)
    continuity_payload = _logic_audit_continuity_payload(continuity)
    promise_payload = _logic_audit_promise_payload(promise_ledger)
    causality_payload = _logic_audit_causality_payload(causality_graph)
    previous_payload = _logic_audit_previous_audit_payload(previous_audit)
    return (
        "请对当前长篇进度做逻辑审计。\n"
        "要求：\n"
        f"{_market_profile_guidance(spec.market_profile, stage='review')}\n"
        f"{_progression_guidance(spec.progression_mode, spec.progression_flavor, spec.progression_pacing, stage='review')}\n"
        "1. 只检查长线逻辑，不评价文采。\n"
        "2. 重点看人物状态是否回退、线索是否失踪、目标是否跳变、承诺是否未兑现。\n"
        "3. 必须结合承诺账本和因果图判断有没有逾期、断裂或无后果推进。\n"
        "3.4 如果本书启用了硬境界升级，还要检查升级台阶有没有消失、突破是否无代价、敌人层级是否失真、长期只换名词不换能力和回报。\n"
        "3.1 对承诺账本要区分“已推进但尚未完全兑付”和“真正逾期”。如果账本本身失真、把大量 advanced 项误记成逾期，应该把 gate_level 设为 repair_metadata，而不是直接 hard_fail。\n"
        "3.1 还要检查最近长窗口里是否出现明显空转：可以允许同一推进簇连续存在，但不能连续多章都只靠同一种确认命门、公开施压或节点升级在原地打转。\n"
        "3.2 还要检查人物声口是否逐渐同腔同调，尤其核心人物之间是否失去辨识度。\n"
        "3.3 还要检查前中段术语负担是否过高、主题是否讲得太透、压力曲线是否长期同频高压、地面生活是否明显不足。\n"
        "4. watch_items 要写成后续章节可直接遵守的约束。\n"
        "5. 如果问题严重到不该直接进入下一卷，gate_passed 必须设为 false，并给出 repair_plan。\n"
        "5.1 gate_level 只能是 pass、warn、repair_metadata、repair_cluster、hard_fail。\n"
        "5.2 资料层/账本层失真优先用 repair_metadata；只有正文结构本身需要成片回修，才用 repair_cluster 或 hard_fail。\n"
        "5.1 structure_risks、voice_risks、density_risks、pressure_risks、grounding_risks 都要具体，不要只写空泛评价。\n"
        "6. flagged_chapters 只标真正需要回看的章节。\n"
        "6.1 给你的章节上下文分成两层：近期章节保留原始摘要，更早部分只给分段摘要；不要因为缺少更早原文就胡编细节。\n"
        "6.2 承诺账本和因果图只给焦点子集与统计摘要；请根据这些焦点信号判断，不要要求全量旧档案。\n"
        "7. 只返回 JSON。\n\n"
        f"项目 brief（运行态摘要）：\n{compact_json(_project_runtime_payload(spec))}\n\n"
        f"设定圣经（运行态摘要）：\n{compact_json(_world_runtime_payload(bible))}\n\n"
        f"升级体系圣经（运行态摘要）：\n{compact_json(_power_system_runtime_payload(power_system))}\n\n"
        f"全书分卷蓝图（焦点窗口）：\n{compact_json(_logic_audit_book_outline_payload(book_outline, current_volume_index=volume_outline.volume_index))}\n\n"
        f"当前分卷蓝图（运行态摘要）：\n{compact_json(_volume_outline_runtime_payload(volume_outline) if volume_outline is not None else {})}\n\n"
        f"本卷章节摘要：\n{compact_json(chapter_payload)}\n\n"
        f"当前连续性状态（压缩视图）：\n{compact_json(continuity_payload)}\n\n"
        f"账本卫生检查：\n{compact_json(ledger_sanity or {})}\n\n"
        f"承诺账本（聚焦摘要）：\n{compact_json(promise_payload)}\n\n"
        f"因果图（聚焦摘要）：\n{compact_json(causality_payload)}\n\n"
        f"升级账本（聚焦摘要）：\n{compact_json(_progression_subset_payload(progression_ledger or []))}\n\n"
        f"上一轮逻辑审计（摘要）：\n{compact_json(previous_payload)}\n\n"
        f"输出 JSON 结构：\n{compact_json(shape)}"
    )


def final_review_system_prompt() -> str:
    return "你是总审读编辑。你负责判断这部长篇项目是否完整、顺畅、能读，只返回 JSON。"


def stagnation_judge_system_prompt() -> str:
    return (
        "你是长篇结构裁判。"
        "你只负责判断最近章节簇是合理的连续推进，还是已经出现长期空转。"
        "你不是文学评论家，不要点评文采，不要改写正文。"
        "你必须只返回一个 JSON 对象。"
    )


def stagnation_judge_user_prompt(
    spec: ProjectSpec,
    bible: WorldBible,
    volume_outline: VolumeOutline | None,
    stagnation_report: dict[str, object],
    recent_chapters: list[dict[str, object]],
    continuity_runtime: dict[str, object],
    current_plan: dict[str, object],
    *,
    power_system: PowerSystemBible | None = None,
    progression_ledger: list[ProgressionLedgerItem] | None = None,
) -> str:
    shape = {
        "verdict": "reasonable_cluster | stagnation_risk | true_stagnation",
        "recommended_action": "accept | forward_fix | local_repair | phase_repair | arc_repair",
        "confidence": 0,
        "reason": "150字以内，解释为何这样判断",
        "scope_start_chapter": 0,
        "scope_end_chapter": 0,
        "next_chapter_constraints": ["如果继续写，后续章节必须遵守的约束"],
        "repair_goal": "如果要修，最小修复目标是什么",
    }
    return (
        "请判断最近这一段是否真的长期空转。\n"
        "判断原则：\n"
        f"{_market_profile_guidance(spec.market_profile, stage='review')}\n"
        f"{_progression_guidance(spec.progression_mode, spec.progression_flavor, spec.progression_pacing, stage='review')}\n"
        "1. 允许同一事件、同一高潮簇、同一公开局连续很多章推进。\n"
        "2. 只有在“章功能重复 + scene 组合重复 + 升级方式重复 + 缺少新的后果/代价/站位变化”同时成立时，才算长期空转。\n"
        "2.1 如果本书启用了硬境界升级，要把修炼、蓄力、拿资源、试炼、巩固、突破视为合法推进；不能因为暂时没跳大境界就误判空转。\n"
        "3. 优先信任上层规划；不要因为同一件事连续推进就轻率判空转。\n"
        "4. 若内容仍合理，应给 reasonable_cluster，并尽量用 accept 或 forward_fix。\n"
        "5. 若确实有问题，优先给最小修复范围，不要默认大修。\n"
        "6. 只返回一个 JSON 对象；顶层不允许数组。\n\n"
        f"项目 brief（运行态摘要）：\n{compact_json(_project_runtime_payload(spec))}\n\n"
        f"设定圣经（运行态摘要）：\n{compact_json(_world_runtime_payload(bible))}\n\n"
        f"升级体系圣经（运行态摘要）：\n{compact_json(_power_system_runtime_payload(power_system))}\n\n"
        f"当前分卷蓝图（运行态摘要）：\n{compact_json(_volume_outline_runtime_payload(volume_outline) if volume_outline is not None else {})}\n\n"
        f"空转探测报告：\n{compact_json(stagnation_report)}\n\n"
        f"最近章节簇摘要：\n{compact_json(recent_chapters)}\n\n"
        f"升级账本（聚焦摘要）：\n{compact_json(_progression_subset_payload(progression_ledger or [], limit=8))}\n\n"
        f"当前连续性运行态摘要：\n{compact_json(continuity_runtime)}\n\n"
        f"当前章计划摘要：\n{compact_json(current_plan)}\n\n"
        f"输出 JSON 结构：\n{compact_json(shape)}"
    )


def book_package_system_prompt() -> str:
    return (
        "你是中文小说发行编辑。"
        "你要根据已经写完的实际成书内容，生成一个事实型剧情简介和一个平台首屏简介。"
        "不许胡编，不许拿立项文案冒充成书简介。"
        "只返回 JSON。"
    )


def book_package_user_prompt(
    spec: ProjectSpec,
    bible: WorldBible,
    book_outline: BookOutline,
    volume_digests: list[dict[str, object]],
    continuity: ContinuityState,
    final_review: dict,
    total_chars: int,
) -> str:
    shape = {
        "factual_summary": "450到550字，基于实际完成剧情的浓缩简介",
        "marketing_blurb": "200字以内，面向小说网站首屏，抓人但不能和正文冲突",
    }
    bible_payload = {
        "title": bible.title,
        "logline": bible.logline,
        "setting_summary": bible.setting_summary,
        "core_conflict": bible.core_conflict,
        "theme_statement": bible.theme_statement,
        "ending_contract": bible.ending_contract,
        "major_threads": bible.major_threads,
        "characters": [
            {
                "name": character.name,
                "role": character.role,
                "goal": character.goal,
                "arc": character.arc,
            }
            for character in bible.characters[:8]
        ],
    }
    outline_payload = {
        "title": book_outline.title,
        "one_line_summary": book_outline.one_line_summary,
        "act_structure": book_outline.act_structure,
        "volumes": [
            {
                "index": volume.index,
                "title": volume.title,
                "role": volume.role,
                "central_question": volume.central_question,
                "emotional_shift": volume.emotional_shift,
                "must_payoff": volume.must_payoff,
            }
            for volume in book_outline.volumes
        ],
    }
    project_payload = {
        "title": spec.title,
        "genre": spec.genre,
        "audience": spec.audience,
        "tone": spec.tone,
        "premise": spec.premise,
        "hook": spec.hook,
        "ending_mode": spec.ending_mode,
        "chapter_count": spec.chapter_count,
        "volume_count": spec.volume_count,
        "total_chars": total_chars,
    }
    return (
        "请为这部已经完稿的小说生成两段简介。\n"
        "要求：\n"
        "1. factual_summary 必须是实打实的剧情浓缩，基于已完成的实际推进和收束，不能只复述最初设定。\n"
        "2. factual_summary 要覆盖主角、核心冲突、关键升级和最终落点，长度控制在 450 到 550 个中文字符。\n"
        "3. marketing_blurb 用于小说网站首屏，200 字以内，可以更抓人，但不能编造正文不存在的设定或结局。\n"
        "4. 两段简介都必须和已完成主线一致，不能写成预告片口吻。\n"
        "5. 只返回 JSON。\n\n"
        f"作品信息：\n{compact_json(project_payload)}\n\n"
        f"设定圣经摘要：\n{compact_json(bible_payload)}\n\n"
        f"全书蓝图摘要：\n{compact_json(outline_payload)}\n\n"
        f"分卷实际推进摘要：\n{compact_json(volume_digests)}\n\n"
        f"最终连续性状态：\n{compact_json(continuity)}\n\n"
        f"终审结果：\n{compact_json(final_review)}\n\n"
        f"输出 JSON 结构：\n{compact_json(shape)}"
    )


def final_review_user_prompt(
    spec: ProjectSpec,
    bible: WorldBible,
    book_outline: BookOutline,
    chapters: list[ChapterResult],
    continuity: ContinuityState,
    local_quality: dict,
    promise_ledger: list[PromiseLedgerItem],
    causality_graph: list[CausalityEdge],
    logic_audits: list[object] | None = None,
    *,
    power_system: PowerSystemBible | None = None,
    progression_ledger: list[ProgressionLedgerItem] | None = None,
) -> str:
    shape = {
        "passed": True,
        "score": 90,
        "strengths": ["全书优点"],
        "issues": ["全书问题"],
        "required_fixes": ["若不通过，需要修哪里"],
        "short_summary": "60字以内，概括整部作品完成度",
        "chapter_fixes": [
            {"chapter_index": chapters[-1].index if chapters else 1, "instruction": "指出具体修改方向"}
        ]
    }
    chapter_payload = _logic_audit_section_digests(chapters, recent_keep=10)
    current_volume_index = chapters[-1].volume_index if chapters else 1
    logic_audit_payload = _final_review_logic_audits_payload(logic_audits)
    final_chapter_text = chapters[-1].draft if chapters else ""
    return (
        "请对整部作品做终审。\n"
        "通过标准：\n"
        "1. 故事有完整开端、推进、转折、收束。\n"
        "2. 主角变化成立。\n"
        "3. 章节之间连续，不打架。\n"
        "4. 文风统一，能顺畅读完。\n"
        "4.1 还要看有没有明显术语负担、同构推进、人物同腔、主题外露过度、长期高压缺少换气和地面感的问题。\n"
        "4.2 如果本书启用了硬境界升级，还要检查升级体系有没有贯彻到结尾：台阶是否清楚、突破是否有代价、资源链与强敌梯度是否成立、后期升级系统是否消失。\n"
        "5. 如果 ending_mode 是 standalone，而最终章主要功能只是引出下一案/下一部，则必须判定不通过。\n"
        "6. 如果不通过，chapter_fixes 必须给出明确的章节级修订指令。\n"
        "6.1 如果问题主要来自连续性档案、承诺账本、因果图、active_threads 等资料池污染，而正文主线已闭环，则可以 passed=true；这类问题写进 issues/required_fixes，不要开 chapter_fixes。\n"
        "6.2 chapter_fixes 只能用于真正需要改正文的章节，每一条都必须能靠修改该章正文本身解决。\n"
        f"{_market_profile_guidance(spec.market_profile, stage='review')}\n"
        f"{_progression_guidance(spec.progression_mode, spec.progression_flavor, spec.progression_pacing, stage='review')}\n"
        "7. 只返回 JSON。\n\n"
        f"项目 brief（运行态摘要）：\n{compact_json(_project_runtime_payload(spec))}\n\n"
        f"设定圣经（运行态摘要）：\n{compact_json(_world_runtime_payload(bible))}\n\n"
        f"升级体系圣经（运行态摘要）：\n{compact_json(_power_system_runtime_payload(power_system))}\n\n"
        f"全书分卷蓝图（焦点窗口）：\n{compact_json(_logic_audit_book_outline_payload(book_outline, current_volume_index=current_volume_index))}\n\n"
        f"最终连续性状态（压缩视图）：\n{compact_json(_logic_audit_continuity_payload(continuity))}\n\n"
        f"承诺账本（聚焦摘要）：\n{compact_json(_logic_audit_promise_payload(promise_ledger))}\n\n"
        f"因果图（聚焦摘要）：\n{compact_json(_logic_audit_causality_payload(causality_graph))}\n\n"
        f"升级账本（聚焦摘要）：\n{compact_json(_progression_subset_payload(progression_ledger or [], limit=12))}\n\n"
        f"阶段性逻辑审计（压缩视图）：\n{compact_json(logic_audit_payload)}\n\n"
        f"本地终审：\n{compact_json(local_quality)}\n\n"
        f"章节级摘要（近期原始 + 更早分段摘要）：\n{compact_json(chapter_payload)}\n\n"
        f"最终章全文：\n{final_chapter_text}\n\n"
        f"输出 JSON 结构：\n{compact_json(shape)}"
    )


def _closing_rule(closing_mode: str, ending_mode: str) -> str:
    if closing_mode == "book_closure" and ending_mode == "standalone":
        return "必须完成主线闭环和主角关键选择，允许余韵，但最后一段不能只拿新事件起悬念。"
    if closing_mode == "series_hook":
        return "要收束当期主要冲突，同时留下可持续展开的余波。"
    if closing_mode == "volume_hook":
        return "要形成分卷级转折，让读者明确下一卷面临什么升级。"
    return "章末必须形成明确的未决动作、决定或局势变化。"
