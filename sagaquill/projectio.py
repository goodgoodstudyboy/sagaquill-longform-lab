from __future__ import annotations

from typing import Any

from .models import ProjectInput
from .normalize import character_seed_list, float_or_none, int_or_none, optional_text, string_list, text


_TOMATO_MARKET_PROFILE_HINTS = (
    "番茄",
    "小白",
    "爽文",
    "爽感",
    "爽点",
    "快节奏",
    "追读",
    "黄金三章",
    "低门槛",
    "大众男频",
    "大众向",
    "番茄爆款",
)

_OUTPUT_LANGUAGE_ALIASES = {
    "zh": "zh-Hans",
    "zh_cn": "zh-Hans",
    "zh-cn": "zh-Hans",
    "zh_hans": "zh-Hans",
    "zh-hans": "zh-Hans",
    "zh_tw": "zh-Hant",
    "zh-tw": "zh-Hant",
    "zh_hant": "zh-Hant",
    "zh-hant": "zh-Hant",
    "chinese": "zh-Hans",
    "simplified_chinese": "zh-Hans",
    "traditional_chinese": "zh-Hant",
    "简体中文": "zh-Hans",
    "繁体中文": "zh-Hant",
    "中文": "zh-Hans",
    "en": "en",
    "en_us": "en",
    "en-us": "en",
    "english": "en",
    "英语": "en",
    "ja": "ja",
    "japanese": "ja",
    "日语": "ja",
    "日本語": "ja",
    "ko": "ko",
    "korean": "ko",
    "韩语": "ko",
    "한국어": "ko",
    "es": "es",
    "spanish": "es",
    "西班牙语": "es",
    "fr": "fr",
    "french": "fr",
    "法语": "fr",
    "de": "de",
    "german": "de",
    "德语": "de",
}


def normalized_market_profile(value: object) -> str:
    text_value = optional_text(value)
    normalized = text_value.strip().lower().replace("-", "_") if text_value else ""
    if normalized in {"tomato_mass", "tomato", "番茄爆款", "番茄"}:
        return "tomato_mass"
    if normalized in {"qidian_longform", "qidian", "起点长篇", "起点"}:
        return "qidian_longform"
    return "qidian_longform"


def normalized_output_language(value: object) -> str:
    text_value = optional_text(value)
    normalized = text_value.strip().lower().replace(" ", "_") if text_value else ""
    if not normalized:
        return "zh-Hans"
    return _OUTPUT_LANGUAGE_ALIASES.get(normalized, text_value.strip())


def is_chinese_output_language(value: object) -> bool:
    normalized = normalized_output_language(value)
    return normalized in {"zh", "zh-Hans", "zh-CN", "zh-Hant", "zh-TW"} or normalized.startswith("zh-")


def default_pov_for_language(value: object) -> str:
    return "第三人称有限视角" if is_chinese_output_language(value) else "third person limited"


def localized_pov(value: object, language: object) -> str:
    pov = optional_text(value)
    if pov and not (not is_chinese_output_language(language) and pov == "第三人称有限视角"):
        return pov
    return default_pov_for_language(language)


def normalized_progression_mode(value: object) -> str:
    text_value = optional_text(value)
    normalized = text_value.strip().lower().replace("-", "_") if text_value else ""
    if normalized in {"hard_realm_progression", "hard_realm", "hard_progression", "硬境界升级"}:
        return "hard_realm_progression"
    return "soft_progression"


def normalized_progression_flavor(value: object) -> str:
    text_value = optional_text(value)
    normalized = text_value.strip().lower().replace("-", "_") if text_value else ""
    if normalized in {"xuanhuan_fast", "玄幻快升流"}:
        return "xuanhuan_fast"
    if normalized in {"xianxia_steady", "仙侠稳升流"}:
        return "xianxia_steady"
    if normalized in {"sci_fi_evolution", "科幻进化流"}:
        return "sci_fi_evolution"
    return ""


def normalized_progression_pacing(value: object) -> str:
    text_value = optional_text(value)
    normalized = text_value.strip().lower().replace("-", "_") if text_value else ""
    if normalized in {"fast", "快"}:
        return "fast"
    if normalized in {"slow", "慢"}:
        return "slow"
    return "steady"


def resolved_market_profile(value: object, payload: dict[str, Any] | None = None) -> str:
    text_value = optional_text(value)
    if text_value:
        return normalized_market_profile(text_value)
    if not payload:
        return "qidian_longform"
    candidates: list[str] = []
    for key in (
        "audience",
        "tone",
        "premise",
        "hook",
        "outline_hint",
        "world_hint",
        "market_profile",
    ):
        candidates.append(optional_text(payload.get(key)))
    for key in ("style_examples", "must_include", "avoid"):
        candidates.extend(string_list(payload.get(key)))
    joined = "\n".join(part for part in candidates if part).lower()
    if any(marker in joined for marker in _TOMATO_MARKET_PROFILE_HINTS):
        return "tomato_mass"
    return "qidian_longform"


def project_input_from_dict(payload: dict[str, Any]) -> ProjectInput:
    title = text(payload.get("title"))
    if not title:
        raise ValueError("Project input must include a title.")
    output_language = normalized_output_language(payload.get("output_language") or payload.get("language"))
    return ProjectInput(
        title=title,
        genre=optional_text(payload.get("genre")),
        audience=optional_text(payload.get("audience")),
        tone=optional_text(payload.get("tone")),
        premise=optional_text(payload.get("premise")),
        theme=optional_text(payload.get("theme")),
        hook=optional_text(payload.get("hook")),
        setting=optional_text(payload.get("setting")),
        protagonist=optional_text(payload.get("protagonist")),
        outline_hint=optional_text(payload.get("outline_hint")),
        world_hint=optional_text(payload.get("world_hint")),
        ending_mode=optional_text(payload.get("ending_mode")) or "standalone",
        pov=localized_pov(payload.get("pov"), output_language),
        target_total_chars=int_or_none(payload.get("target_total_chars")),
        target_chars_per_chapter=int_or_none(payload.get("target_chars_per_chapter")),
        chapter_count=int_or_none(payload.get("chapter_count")),
        volume_count=int_or_none(payload.get("volume_count")),
        chapter_char_tolerance=float_or_none(payload.get("chapter_char_tolerance")),
        structure_mode=optional_text(payload.get("structure_mode")) or "story_driven",
        market_profile=resolved_market_profile(payload.get("market_profile"), payload),
        progression_mode=normalized_progression_mode(payload.get("progression_mode")),
        progression_flavor=normalized_progression_flavor(payload.get("progression_flavor")),
        progression_pacing=normalized_progression_pacing(payload.get("progression_pacing")),
        power_system_hint=optional_text(payload.get("power_system_hint")),
        style_examples=string_list(payload.get("style_examples")),
        must_include=string_list(payload.get("must_include")),
        avoid=string_list(payload.get("avoid")),
        character_seeds=character_seed_list(payload.get("character_seeds"), allow_strings=True),
        seed=int_or_none(payload.get("seed")),
        output_language=output_language,
    )


def starter_project_input() -> dict[str, object]:
    return {
        "title": "雾港回声",
        "output_language": "zh-Hans",
        "genre": "都市奇谭",
        "audience": "喜欢悬疑与情感推进的中文读者",
        "tone": "克制、冷峻、带一点潮湿的温柔",
        "premise": "一名失物招领员发现每件无人认领的旧物都残留着失踪者最后一段记忆。",
        "theme": "人会被过去困住，但真正救人的不是记忆，而是重新做选择的勇气。",
        "hook": "每次替别人找回遗失之物，她都离自己失踪的弟弟更近一步。",
        "setting": "常年有海雾的沿海旧城，码头、旧电车、废弃影院和不断扩建的新城区并存。",
        "protagonist": "沈雾，一名沉默寡言的失物招领员，擅长整理物品，却不擅长整理自己的伤口。",
        "outline_hint": "希望是完整单本，不留半截。前中段持续升级，最终章必须闭环。",
        "world_hint": "现实底色强，奇异能力只作为情节杠杆，不要炫技。",
        "ending_mode": "standalone",
        "pov": "第三人称有限视角",
        "target_total_chars": 18000,
        "target_chars_per_chapter": 2200,
        "chapter_count": 8,
        "volume_count": 1,
        "chapter_char_tolerance": 0.25,
        "structure_mode": "story_driven",
        "market_profile": "qidian_longform",
        "progression_mode": "soft_progression",
        "progression_flavor": "",
        "progression_pacing": "steady",
        "power_system_hint": "",
        "style_examples": [
            "潮湿、克制、细节密集",
            "对白短，动作和决定推动剧情",
            "最终章必须解决主线，而不是只留新悬念"
        ],
        "must_include": [
            "旧城区与新城区的矛盾",
            "一件会引发关键回忆的旧物",
            "主角与弟弟失踪案的个人关联",
            "结尾形成完整闭环"
        ],
        "avoid": [
            "说教式总结",
            "纯设定炫技",
            "脸谱化反派",
            "最后一段只用新事件起悬念"
        ],
        "character_seeds": [
            {
                "name": "沈雾",
                "role": "主角",
                "goal": "找回失踪弟弟的真相",
                "conflict": "越靠近真相，越会击穿她这些年维持的秩序",
                "notes": "冷静寡言，不爱解释"
            }
        ],
        "seed": 7
    }


def preset_catalog() -> dict[str, list[dict[str, object]]]:
    return {
        "audience_presets": [
            _preset_entry(
                "qidian_male",
                "起点男频",
                "更看重升级、反制、强敌投影和阶段性回报。",
                audience="喜欢强剧情推进、升级回报和高压对抗的男频读者。",
                style_examples=[
                    "主角目标要明确，最好开篇 1 到 3 章就露出核心卖点。",
                    "每 3 到 5 章给一次明确回报、反咬或赢点。",
                    "更高层敌人或秩序机器的影子要尽早出现。",
                ],
                must_include=[
                    "阶段性胜利或反制回报",
                    "更高层敌人或秩序机器的早期投影",
                    "章尾明确钩子",
                ],
                avoid=[
                    "连续多章只有吃瘪没有回报",
                    "卖点露出过晚",
                    "长期停在基层摩擦不升级",
                ],
                outline_hint="前期必须尽快露出卖点、强敌影子和阶段性回报。",
            ),
            _preset_entry(
                "tomato_mass",
                "番茄大众",
                "句子更白更快，情绪直给，适合大盘读者快速进入。",
                audience="喜欢快节奏、强代入、情绪直给和门槛低的大众读者。",
                style_examples=[
                    "句子尽量白，信息第一次出现就让人看懂。",
                    "每章至少推进一件实事，不要空转。",
                    "情绪和事件要同步到位，不要只做氛围。",
                ],
                must_include=[
                    "快节奏事件推进",
                    "明显的情绪落点",
                    "读者一眼能懂的冲突关系",
                ],
                avoid=[
                    "连续长段术语解释",
                    "只写气氛不写结果",
                    "前期铺垫过厚",
                ],
                outline_hint="按大众阅读习惯控制门槛，前几章就让读者知道主角要干什么、为什么现在就得干。",
            ),
            _preset_entry(
                "jj_emotion",
                "晋江情感",
                "强调人物关系、心理变化和情感推进。",
                audience="喜欢人物关系、情绪拉扯、成长弧线和情感推进的女性向读者。",
                style_examples=[
                    "人物关系变化必须带动主线，而不是单独存在。",
                    "心理变化要可见，不能只写结果。",
                    "重要关系节点要有清晰前后状态差异。",
                ],
                must_include=[
                    "关键关系的阶段性变化",
                    "人物内心选择",
                    "能让读者记住的关系场面",
                ],
                avoid=[
                    "感情线只做附庸",
                    "人物只剩功能没有欲望",
                    "冲突只靠误会硬拖",
                ],
                outline_hint="关系推进和主线推进要并行，重要人物之间必须不断重写彼此的位置。",
            ),
            _preset_entry(
                "literary_blend",
                "口碑风格向",
                "更看重质感、人物弧线和主题回响，但仍保留类型推进。",
                audience="喜欢质感、人物弧线、主题回响和中高密度表达的口碑向读者。",
                style_examples=[
                    "语言允许更克制、更有意象，但每章仍要有局势变化。",
                    "爽点以结构性回响、翻案或情感落点来兑现。",
                    "主题表达要落在人物选择和后果上。",
                ],
                must_include=[
                    "主题回响",
                    "人物弧线闭合",
                    "结尾的现实落点或制度落点",
                ],
                avoid=[
                    "只有文气没有推进",
                    "过度卖弄修辞",
                    "主线长期让位给散文式描写",
                ],
                outline_hint="允许文学感，但不能拿文学感替代节奏和兑现。",
            ),
            _preset_entry(
                "light_novel_youth",
                "轻小说 / 年轻向",
                "人物更鲜明，节奏更轻快，场景感和记忆点更强。",
                audience="喜欢轻快节奏、强人设、名场面和视觉感的年轻读者。",
                style_examples=[
                    "角色出场要有鲜明标签和记忆点。",
                    "对话和互动承担更多推进功能。",
                    "场景要有画面感和名场面意识。",
                ],
                must_include=[
                    "鲜明人设",
                    "角色互动名场面",
                    "轻快而清晰的推进",
                ],
                avoid=[
                    "连续沉重压抑不松口",
                    "人设辨识度不足",
                    "设定说明过多",
                ],
                outline_hint="保持轻快和鲜明，重要桥段要尽量具备动画镜头感或名场面感。",
            ),
        ],
        "style_presets": [
            _preset_entry(
                "commercial_hook",
                "爆款强钩子",
                "强产品化节奏，爽点密集，章尾明确挂钩。",
                tone="快节奏、强钩子、爽点密集、回报明确。",
                style_examples=[
                    "开篇前几章必须尽快露出最大卖点。",
                    "每章至少推进一件实事，每 3 到 5 章给一次明确赢点。",
                    "章尾要留下下一步动作、危机或更大诱惑。",
                ],
                must_include=[
                    "阶段性赢点",
                    "短周期反转或爆点",
                    "主角主动反制",
                ],
                avoid=[
                    "连续压抑没有翻盘",
                    "大段抒情不推进",
                    "卖点藏得太久",
                ],
                outline_hint="整体按强产品节奏推进，前中段持续给回报、反制和升级。",
            ),
            _preset_entry(
                "literary_cold",
                "文学感克制",
                "语言更克制冷峻，强调结构回响和后劲。",
                tone="克制、冷峻、意象收束、缓压推进。",
                style_examples=[
                    "对白短，情绪尽量落在动作和细节上。",
                    "重要情绪靠反复出现的意象和动作回响，而不是直接喊出来。",
                    "爽点可以延后，但每章仍要有明确变化。",
                ],
                must_include=[
                    "结构回响",
                    "主题回声",
                    "人物决断后的现实后果",
                ],
                avoid=[
                    "廉价口号式热血",
                    "脸谱化打脸",
                    "只有气质没有推进",
                ],
                outline_hint="允许慢压和余韵，但不能失去章节级推进。",
            ),
            _preset_entry(
                "literary_product_mix",
                "文学感 + 起点节奏",
                "保留质感和主题，同时显著增强追读钩子与回报节拍。",
                tone="有质感但不拖，克制中带强推进，兼顾文学感和商业节奏。",
                style_examples=[
                    "语言可以有质感，但章尾钩子和阶段性回报不能弱。",
                    "3 到 5 章一个钩，10 章一个阶段兑现。",
                    "大敌、证物、反制和情绪落点要交替出现。",
                ],
                must_include=[
                    "早期卖点露出",
                    "阶段性兑现",
                    "人物弧线和商业节奏并行",
                ],
                avoid=[
                    "前期连续压迫没有回报",
                    "中段重复同一种推进动作",
                    "只靠文气支撑阅读",
                ],
                outline_hint="用文学骨架承载更强追读节拍，前期必须更早放出异常、证物、强敌影子和第一次赢。",
            ),
            _preset_entry(
                "suspense_evidence",
                "悬疑证据链",
                "靠线索、真相和证据推进，要求逻辑咬合更紧。",
                tone="悬疑推进、证据链驱动、层层剥离。",
                style_examples=[
                    "每章都要推进调查、判断或证据位置。",
                    "线索的出现、转义和兑现都要有前因后果。",
                    "章尾优先挂未决证据、未完成决定或新口实。",
                ],
                must_include=[
                    "证据链",
                    "错误判断与纠偏",
                    "关键线索回收",
                ],
                avoid=[
                    "故弄玄虚不解释",
                    "线索突然天降",
                    "主角一直被动跟着信息走",
                ],
                outline_hint="要让调查链可复述、可回看、可闭环，不能只靠氛围装成悬疑。",
            ),
            _preset_entry(
                "emotional_pull",
                "情感拉扯",
                "关系、欲望和情绪牵引要显著增强。",
                tone="情绪浓烈、关系驱动、拉扯感强。",
                style_examples=[
                    "重大推进尽量和人物关系变化绑定。",
                    "每个关键人物都要有显性欲望和不愿说出口的真心。",
                    "场面不仅要推进事，也要重写关系。",
                ],
                must_include=[
                    "关系节点",
                    "情绪爆点",
                    "有代价的选择",
                ],
                avoid=[
                    "只有事件没有情绪余波",
                    "关系只停在嘴上",
                    "人物情绪反应失真",
                ],
                outline_hint="把人物之间的拉扯写成真正能改变主线走向的力量。",
            ),
            _preset_entry(
                "hotblooded_upgrade",
                "热血升级",
                "强调成长、强敌、门槛突破和高燃场面。",
                tone="热血、昂扬、强对抗、持续升级。",
                style_examples=[
                    "主角要不断突破更高门槛，而不是原地证明自己。",
                    "强敌要一层比一层高，代价也要升级。",
                    "高燃场面前要先压足失败风险和资源缺口。",
                ],
                must_include=[
                    "升级节点",
                    "强敌压迫",
                    "高燃名场面",
                ],
                avoid=[
                    "口号很多但代价很轻",
                    "升级没有前置困难",
                    "打完没有地位变化",
                ],
                outline_hint="用更明确的台阶感和代价感来支撑热血与升级。",
            ),
        ],
    }


def panel_template_payload() -> dict[str, object]:
    payload = dict(starter_project_input())
    payload["preset_catalog"] = preset_catalog()
    payload["market_profile_options"] = [
        {
            "id": "qidian_longform",
            "label": "起点长篇",
            "description": "更强调长线结构、体系自洽和后期不崩，容忍更强系统细节与长弧推进。",
        },
        {
            "id": "tomato_mass",
            "label": "番茄爆款",
            "description": "更强调黄金三章、低门槛强钩子、回报密度、换气和追读表现。",
        },
    ]
    payload["output_language_options"] = [
        {
            "id": "zh-Hans",
            "label": "简体中文",
            "description": "默认模式，适合中文网文、长篇连载和中文平台交付。",
        },
        {
            "id": "en",
            "label": "English",
            "description": "Novel prose, chapter drafts, summaries, and delivery copy target English readers.",
        },
        {
            "id": "ja",
            "label": "日本語",
            "description": "日本語の小説本文と紹介文を生成します。ライトノベル寄りの企画にも使えます。",
        },
        {
            "id": "ko",
            "label": "한국어",
            "description": "한국어 웹소설 본문과 소개문을 생성합니다.",
        },
        {
            "id": "es",
            "label": "Español",
            "description": "Genera prosa, capítulos y textos de entrega en español.",
        },
        {
            "id": "fr",
            "label": "Français",
            "description": "Génère le roman, les résumés et les textes de livraison en français.",
        },
        {
            "id": "de",
            "label": "Deutsch",
            "description": "Erzeugt Romantext, Zusammenfassungen und Lieferdokumente auf Deutsch.",
        },
    ]
    payload["progression_mode_options"] = [
        {
            "id": "soft_progression",
            "label": "叙事升级",
            "description": "靠权限、资源、关系、规则掌握和阶段回报推进，适合怪谈、体制、现实向长篇。",
        },
        {
            "id": "hard_realm_progression",
            "label": "硬境界升级",
            "description": "把境界台阶、突破条件、资源梯度和强敌带宽做成显式结构，适合斗破/凡人/吞噬这类。",
        },
    ]
    payload["progression_flavor_options"] = [
        {
            "id": "",
            "label": "自动（按题材）",
            "description": "默认按题材自动偏向最稳的升级写法。",
        },
        {
            "id": "xuanhuan_fast",
            "label": "玄幻快升流",
            "description": "更密的境界台阶、更频繁的突破和更强的短周期回报。",
        },
        {
            "id": "xianxia_steady",
            "label": "仙侠稳升流",
            "description": "大境界提升更慢，但丹药、法器、洞府、秘境和副进展持续累加。",
        },
        {
            "id": "sci_fi_evolution",
            "label": "科幻进化流",
            "description": "生命层级、资源层级和区域层级更明确，适合吞噬/进化类。",
        },
    ]
    payload["progression_pacing_options"] = [
        {
            "id": "fast",
            "label": "快",
            "description": "更强调短周期突破和立竿见影的层级变化。",
        },
        {
            "id": "steady",
            "label": "稳",
            "description": "兼顾升级、资源、敌人梯度和长期结构。",
        },
        {
            "id": "slow",
            "label": "慢",
            "description": "突破更稀疏，但准备、资源和副轴推进必须持续。",
        },
    ]
    return payload

def _preset_entry(
    preset_id: str,
    label: str,
    description: str,
    **fields: object,
) -> dict[str, object]:
    return {
        "id": preset_id,
        "label": label,
        "description": description,
        "fields": fields,
    }
