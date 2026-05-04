from __future__ import annotations

import re
from collections import Counter

from .models import CharacterVoiceCard, LocalQualityReport


PLACEHOLDER_PATTERN = re.compile(
    r"TODO|TBD|placeholder|作者按|这里略去|(?<![\u4e00-\u9fffA-Za-z0-9])(?:待补|占位)(?![\u4e00-\u9fffA-Za-z0-9])",
    re.IGNORECASE,
)
ENDING_TEASER_PATTERN = re.compile(
    r"待续|这只是开始|新的(?:委托|案子|来客|客人)|门外[^。！？\n]{0,24}(站着|响起|传来)|标签上写着",
    re.IGNORECASE,
)
ENDING_RESOLUTION_PATTERN = re.compile(r"终于|决定|不再|登记|归档|交给|回到|继续|放下|结束", re.IGNORECASE)
LONG_DUPLICATE_PARAGRAPH_MIN_LENGTH = 24
SHORT_DUPLICATE_PARAGRAPH_WARN_THRESHOLD = 3
PROCEDURAL_TERMS = (
    "账",
    "账目",
    "账页",
    "账册",
    "账单",
    "账房",
    "票据",
    "凭证",
    "清单",
    "名单",
    "编号",
    "字段",
    "口供",
    "证词",
    "证据",
    "台账",
    "流程",
    "条款",
    "核算",
    "核对",
    "核验",
    "对单",
    "改单",
    "停单",
    "赔付",
    "回补",
    "索引",
    "归档",
    "留档",
    "档案",
    "报备",
    "递送链",
    "口径",
    "总赔单",
)
PROPULSION_KEYWORDS = (
    ("证据推进", ("证", "账", "索引", "票", "口供", "清单", "凭证", "字段", "名单")),
    ("程序拆解", ("流程", "条款", "核算", "核验", "对单", "改单", "停单", "留档", "报备", "口径")),
    ("关系对撞", ("对质", "争执", "试探", "谈判", "翻脸", "逼问", "交易", "拉拢")),
    ("潜伏渗透", ("潜入", "暗访", "尾随", "卧底", "渗透", "伪装", "摸排")),
    ("动作压力", ("追", "逃", "拦", "冲", "伏击", "追击", "厮杀", "搏命")),
    ("代价交换", ("代价", "交换", "让步", "妥协", "赔", "抵押", "签下")),
    ("生活落地", ("吃", "睡", "药", "伤", "热", "街", "家", "饭", "灯", "病")),
)


def _normalized_market_profile(value: str | None) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_")
    return "tomato_mass" if normalized in {"tomato_mass", "tomato", "番茄", "番茄爆款"} else "qidian_longform"


def _normalized_progression_mode(value: str | None) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_")
    return "hard_realm_progression" if normalized in {"hard_realm_progression", "hard_realm", "realm", "硬升级", "硬境界升级"} else "soft_progression"


def _normalized_progression_flavor(value: str | None) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_")
    if normalized in {"xuanhuan_fast", "xianxia_steady", "sci_fi_evolution"}:
        return normalized
    return ""


def chapter_length_grace(target_chars: int) -> int:
    target = max(1, int(target_chars or 0))
    return max(30, min(80, int(round(target * 0.02))))


def _safe_overlength_ratio(char_count: int, target_max: int) -> float:
    if target_max <= 0:
        return 0.0
    return float(char_count) / float(target_max)


def _safe_underlength_ratio(char_count: int, target_min: int) -> float:
    if target_min <= 0:
        return 1.0
    return float(char_count) / float(target_min)


def analyze_chapter(
    text: str,
    target_chars: int,
    character_names: list[str] | None = None,
    *,
    market_profile: str = "qidian_longform",
    progression_mode: str = "soft_progression",
    progression_flavor: str = "",
    length_tolerance: float = 0.25,
    target_chars_min: int | None = None,
    target_chars_max: int | None = None,
    strict_length_gate: bool = True,
    length_extreme_multiplier: float = 3.0,
    term_budget: str = "",
    current_propulsion: str = "",
    recent_propulsion_history: list[str] | None = None,
    chapter_role: str = "",
    scene_types: list[str] | None = None,
    variation_goal: str = "",
    recent_stagnation_history: list[dict[str, object]] | None = None,
    recent_overlength_tail: int = 0,
    recent_severe_overlength_tail: int = 0,
    progression_step_type: str = "",
    progression_reward: str = "",
    progression_cost: str = "",
    current_tier: str = "",
    target_tier: str = "",
    recent_progression_history: list[dict[str, object]] | None = None,
    apply_progression_gate: bool = True,
    voice_cards: list[CharacterVoiceCard] | None = None,
    ending_window: bool = False,
) -> LocalQualityReport:
    profile = _normalized_market_profile(market_profile)
    progression_mode = _normalized_progression_mode(progression_mode)
    progression_flavor = _normalized_progression_flavor(progression_flavor)
    if profile == "tomato_mass":
        length_extreme_multiplier = min(max(1.0, float(length_extreme_multiplier or 2.2)), 2.2)
    char_count = len(re.sub(r"\s+", "", text))
    paragraphs = [chunk.strip() for chunk in re.split(r"\n\s*\n", text) if chunk.strip()]
    normalized_paragraphs = [_normalize_paragraph(item) for item in paragraphs if item.strip()]
    duplicate_paragraphs, duplicate_short_paragraphs = _duplicate_paragraph_counts(normalized_paragraphs)
    sentence_counter = Counter(_split_sentences(text))
    duplicate_sentences = sum(count - 1 for count in sentence_counter.values() if count > 1)
    placeholder_hits = PLACEHOLDER_PATTERN.findall(text)
    average_paragraph_length = int(char_count / max(len(paragraphs), 1))

    issues: list[str] = []
    strengths: list[str] = []
    score = 100
    tolerance = max(0.05, min(0.4, float(length_tolerance or 0.25)))
    default_min = int(target_chars * (1.0 - tolerance))
    default_max = int(target_chars * (1.0 + tolerance))
    min_chars = (
        max(1, int(target_chars_min))
        if target_chars_min not in {None, ""}
        else default_min
    )
    max_chars = (
        max(min_chars, int(target_chars_max))
        if target_chars_max not in {None, ""}
        else default_max
    )
    hard_max = max_chars + chapter_length_grace(target_chars)
    extreme_max = max(hard_max, int(max_chars * max(1.0, float(length_extreme_multiplier or 3.0))))
    over_ratio = _safe_overlength_ratio(char_count, max_chars)
    under_ratio = _safe_underlength_ratio(char_count, min_chars)
    tomato_soft_gate = profile == "tomato_mass" and not strict_length_gate and target_chars >= 1500
    recent_over_tail = max(0, int(recent_overlength_tail or 0))
    recent_severe_tail = max(0, int(recent_severe_overlength_tail or 0))
    length_signal_level = "ok"
    length_warning = False
    length_debt = False
    length_hard_fail = False

    if char_count < min_chars:
        if tomato_soft_gate:
            if under_ratio < 0.55:
                length_signal_level = "hard_fail"
                length_hard_fail = True
                issues.append(
                    f"正文严重偏短，当前约 {char_count} 字，明显低于番茄模式容忍带下限 {min_chars} 字。"
                )
                score -= 12
            elif under_ratio < 0.70:
                length_signal_level = "debt"
                length_debt = True
                issues.append(
                    f"正文偏短，当前约 {char_count} 字；番茄模式建议补一层动作后果、情绪回弹或章尾钩子，但不必因此直接判死。"
                )
                score -= 7
            elif under_ratio < 0.85:
                length_signal_level = "debt"
                length_debt = True
                issues.append(
                    f"正文略短，当前约 {char_count} 字；可放行，但后续几章应尽快回补信息量和兑现密度。"
                )
                score -= 5
            else:
                length_signal_level = "warning"
                length_warning = True
                issues.append(
                    f"正文略短，当前约 {char_count} 字；番茄模式允许这种紧章，但建议补强余波、回报或章尾牵引。"
                )
                score -= 3
        else:
            issues.append(f"正文偏短，当前约 {char_count} 字，低于目标区间下限 {min_chars} 字。")
            score -= 18
    else:
        strengths.append("篇幅达到基本阅读长度。")

    soft_over_penalty = 6 if profile == "tomato_mass" else 4
    moderate_over_penalty = 14 if profile == "tomato_mass" else 12
    if tomato_soft_gate:
        if char_count > extreme_max or over_ratio > 2.2:
            length_signal_level = "hard_fail"
            length_hard_fail = True
            issues.append(
                f"正文严重超长，当前约 {char_count} 字，已明显超过番茄模式容忍带 {extreme_max} 字。"
            )
            score -= 16
        elif over_ratio > 1.7:
            if recent_severe_tail >= 3:
                length_signal_level = "hard_fail"
                length_hard_fail = True
                issues.append(
                    f"正文连续重度偏长，当前约 {char_count} 字；最近多章已连续超过番茄长度债务线，需强制收束。"
                )
                score -= 14
            else:
                length_signal_level = "debt"
                length_debt = True
                issues.append(
                    f"正文明显偏长，当前约 {char_count} 字；番茄模式建议做一次轻压缩并在后续几章回收篇幅。"
                )
                score -= 8
        elif over_ratio > 1.3:
            if recent_over_tail >= 2:
                length_signal_level = "debt"
                length_debt = True
                issues.append(
                    f"正文连续偏长，当前约 {char_count} 字；最近几章都在拉长，建议立刻压缩解释与铺垫。"
                )
                score -= 7
            else:
                length_signal_level = "warning"
                length_warning = True
                issues.append(
                    f"正文偏长，当前约 {char_count} 字；仍可放行，但番茄模式建议下一章压节奏、提早兑现回报。"
                )
                score -= 4
        elif char_count > max_chars:
            strengths.append("篇幅略高于目标上限，但仍在番茄弹性带内。")
        if char_count < min_chars:
            length_ok = not length_hard_fail if target_chars >= 1500 else True
        else:
            length_ok = True if target_chars < 1500 else not length_hard_fail
        if length_hard_fail:
            length_ok = False
    elif strict_length_gate:
        if char_count > extreme_max:
            issues.append(
                f"正文严重超长，当前约 {char_count} 字，已超过异常阈值 {extreme_max} 字。"
            )
            score -= 16
        elif char_count > hard_max:
            issues.append(f"正文偏长，当前约 {char_count} 字，高于目标区间上限 {max_chars} 字。")
            score -= moderate_over_penalty
        elif char_count > max_chars:
            issues.append(
                f"正文略高于目标区间上限，当前约 {char_count} 字，超出 {max_chars} 字上限不多，发行前建议再压字。"
            )
            score -= soft_over_penalty
        length_ok = (min_chars <= char_count <= hard_max) if target_chars >= 1500 else True
    else:
        if char_count > extreme_max:
            issues.append(
                f"正文严重超长，当前约 {char_count} 字，已超过异常阈值 {extreme_max} 字。"
            )
            score -= 16
        elif char_count > hard_max:
            issues.append(
                f"正文明显高于目标区间上限，当前约 {char_count} 字；中长篇默认不因此单独判失败，但建议优先通过前置规划控制篇幅。"
            )
            score -= soft_over_penalty
        elif char_count > max_chars:
            issues.append(
                f"正文略高于目标区间上限，当前约 {char_count} 字，超出 {max_chars} 字上限不多，发行前建议再压字。"
            )
            score -= soft_over_penalty
        length_ok = (min_chars <= char_count <= extreme_max) if target_chars >= 1500 else True

    if char_count > hard_max:
        if strict_length_gate and not tomato_soft_gate:
            pass
        elif char_count <= extreme_max:
            strengths.append("篇幅虽偏重，但仍在中长篇可接受的异常容忍带内。")
    elif char_count > max_chars:
        strengths.append("篇幅接近上限，但仍在可控范围内。")

    if len(paragraphs) < 4:
        issues.append("段落过少，阅读节奏可能发闷。")
        score -= 14
    else:
        strengths.append("段落层次基本成立。")

    if duplicate_paragraphs > 0:
        issues.append("存在重复段落，像是生成时打转。")
        score -= 20
    elif duplicate_short_paragraphs > SHORT_DUPLICATE_PARAGRAPH_WARN_THRESHOLD:
        issues.append("存在少量短段重复，局部节奏略显发涩。")
        score -= 6

    if duplicate_sentences > 1:
        issues.append("存在重复句式或重复句子。")
        score -= 10

    if placeholder_hits:
        issues.append("出现占位词或未完成痕迹。")
        score -= 25

    paragraph_length_limit = 220 if profile == "tomato_mass" else 260
    if average_paragraph_length > paragraph_length_limit:
        issues.append("单段过长，说明段落控制不够。")
        score -= 10 if profile == "tomato_mass" else 8

    density_issue = _procedural_density_issue(text, char_count, term_budget)
    density_hard_fail = _procedural_density_hard_fail(text, char_count, term_budget)
    if density_issue is not None:
        issues.append(density_issue)
        base_penalty = 8 if str(term_budget or "").lower() in {"low", "very_low"} else 5
        if profile == "tomato_mass":
            base_penalty += 3
        score -= base_penalty
    else:
        strengths.append("术语与流程密度基本受控。")

    stagnation_signal = _propulsion_stagnation_signal(
        current_propulsion,
        recent_propulsion_history or [],
        chapter_role=chapter_role,
        scene_types=scene_types or [],
        variation_goal=variation_goal,
        recent_stagnation_history=recent_stagnation_history or [],
    )
    if stagnation_signal["issue"] is not None:
        issues.append(str(stagnation_signal["issue"]))
        level = str(stagnation_signal["level"])
        if level == "warning":
            score -= 2
        elif level == "debt":
            score -= 4
        elif level == "escalation":
            score -= 6

    voice_issue = _ending_voice_convergence_issue(text, voice_cards or [], ending_window=ending_window)
    voice_hard_fail = _ending_voice_convergence_hard_fail(text, voice_cards or [], ending_window=ending_window)
    if voice_issue is not None:
        issues.append(voice_issue)
        score -= 5

    progression_step = str(progression_step_type or "").strip().lower()
    progression_reward_text = str(progression_reward or "").strip()
    progression_cost_text = str(progression_cost or "").strip()
    current_tier_text = str(current_tier or "").strip()
    target_tier_text = str(target_tier or "").strip()
    progression_signal_level = "ok"
    progression_warning = False
    progression_debt = False
    progression_hard_fail = False
    progression_fake_payoff = False
    progression_stall = False
    progression_recent_same_tier_tail = 0

    if progression_mode == "hard_realm_progression" and apply_progression_gate:
        if not progression_step:
            issues.append("硬升级模式下本章没有明确 progression_step_type，升级推进容易失焦。")
            score -= 5
            progression_signal_level = "warning"
            progression_warning = True
        else:
            strengths.append("本章升级步骤已显式标注。")

        if progression_step in {"acquire", "trial", "breakthrough", "challenge", "payoff"} and not (
            progression_reward_text or progression_cost_text
        ):
            issues.append("硬升级模式下关键升级章缺少明确回报或代价，容易写成假升级。")
            score -= 6
            progression_signal_level = "debt"
            progression_debt = True
            progression_fake_payoff = True

        if progression_step == "breakthrough" and not target_tier_text:
            issues.append("突破章没有写明目标台阶，升级结果不够清楚。")
            score -= 5
            progression_signal_level = "debt"
            progression_debt = True

        if progression_step == "breakthrough" and current_tier_text and target_tier_text and current_tier_text == target_tier_text:
            issues.append("突破章的 current_tier 与 target_tier 相同，升级结果失真。")
            score -= 6
            progression_signal_level = "debt"
            progression_debt = True

        history = list(recent_progression_history or [])
        combined_history = history + [
            {
                "progression_step_type": progression_step,
                "current_tier": current_tier_text,
                "target_tier": target_tier_text,
                "progression_reward": progression_reward_text,
                "progression_cost": progression_cost_text,
            }
        ]
        for item in reversed(combined_history):
            step = str(item.get("progression_step_type") or "").strip().lower()
            reward = str(item.get("progression_reward") or "").strip()
            cost = str(item.get("progression_cost") or "").strip()
            cur = str(item.get("current_tier") or "").strip()
            tgt = str(item.get("target_tier") or "").strip()
            if reward or cost:
                break
            if step not in {"", "train", "consolidate", "investigation", "bridge", "transition"}:
                break
            if cur and tgt and cur != tgt:
                break
            progression_recent_same_tier_tail += 1
        if progression_recent_same_tier_tail >= 5:
            issues.append("最近多章都停留在同一升级台阶，且缺少明确回报或代价，升级推进开始停滞。")
            score -= 7
            progression_signal_level = "debt"
            progression_debt = True
            progression_stall = True
        elif progression_recent_same_tier_tail >= 3:
            issues.append("最近几章升级推进偏慢，建议尽快兑现资源、突破条件或阶段回报。")
            score -= 3
            progression_signal_level = "warning"
            progression_warning = True

    if character_names:
        present = [name for name in character_names if name and name in text]
        if not present:
            issues.append("正文里没有出现核心角色名，可能偏离设定。")
            score -= 15
        else:
            strengths.append("核心角色被明确写入正文。")

    score = max(0, min(100, score))
    passed = (
        score >= 70
        and length_ok
        and not placeholder_hits
        and duplicate_paragraphs == 0
        and not density_hard_fail
        and not voice_hard_fail
        and not progression_hard_fail
    )
    summary = "本地检查通过。" if passed else "本地检查发现可读性风险。"

    return LocalQualityReport(
        passed=passed,
        score=score,
        issues=issues,
        strengths=strengths,
        short_summary=summary,
        metrics={
            "char_count": char_count,
            "paragraph_count": len(paragraphs),
            "duplicate_paragraphs": duplicate_paragraphs,
            "duplicate_short_paragraphs": duplicate_short_paragraphs,
            "duplicate_sentences": duplicate_sentences,
            "average_paragraph_length": average_paragraph_length,
            "placeholder_hits": placeholder_hits,
            "duplicate_paragraph_min_length": LONG_DUPLICATE_PARAGRAPH_MIN_LENGTH,
            "target_chars_min": min_chars,
            "target_chars_max": max_chars,
            "target_chars_hard_max": hard_max,
            "target_chars_extreme_max": extreme_max,
            "length_over_ratio": round(over_ratio, 4),
            "length_under_ratio": round(under_ratio, 4),
            "length_signal_level": length_signal_level,
            "length_warning": length_warning,
            "length_debt": length_debt,
            "length_hard_fail": length_hard_fail,
            "recent_overlength_tail": recent_over_tail,
            "recent_severe_overlength_tail": recent_severe_tail,
            "strict_length_gate": strict_length_gate,
            "procedural_term_hits": _procedural_density_metrics(text, char_count)["hits"],
            "procedural_term_distinct": _procedural_density_metrics(text, char_count)["distinct"],
            "current_propulsion": _canonical_propulsion_label(current_propulsion),
            "recent_propulsion_history": [_canonical_propulsion_label(item) for item in (recent_propulsion_history or [])],
            "chapter_role": _normalize_story_memory_text(chapter_role),
            "scene_types": [_normalize_story_memory_text(item) for item in (scene_types or []) if _normalize_story_memory_text(item)],
            "variation_goal": _normalize_story_memory_text(variation_goal),
            "stagnation_signal_level": stagnation_signal["level"],
            "stagnation_warning": stagnation_signal["level"] == "warning",
            "stagnation_debt": stagnation_signal["level"] == "debt",
            "stagnation_escalation": stagnation_signal["level"] == "escalation",
            "stagnation_same_family_cluster": stagnation_signal["same_family_cluster"],
            "stagnation_same_family_tail": stagnation_signal["same_family_tail"],
            "stagnation_same_role_tail": stagnation_signal["same_role_tail"],
            "stagnation_same_scene_tail": stagnation_signal["same_scene_tail"],
            "stagnation_same_variation_tail": stagnation_signal["same_variation_tail"],
            "ending_window": ending_window,
            "market_profile": profile,
            "progression_mode": progression_mode,
            "progression_flavor": progression_flavor,
            "progression_step_type": progression_step,
            "progression_reward": progression_reward_text,
            "progression_cost": progression_cost_text,
            "current_tier": current_tier_text,
            "target_tier": target_tier_text,
            "progression_signal_level": progression_signal_level,
            "progression_warning": progression_warning,
            "progression_debt": progression_debt,
            "progression_hard_fail": progression_hard_fail,
            "progression_fake_payoff": progression_fake_payoff,
            "progression_stall": progression_stall,
            "progression_recent_same_tier_tail": progression_recent_same_tier_tail,
            "procedural_density_hard_fail": density_hard_fail,
            "propulsion_hard_fail": False,
            "ending_voice_hard_fail": voice_hard_fail,
        }
    )


def analyze_novel(
    chapters: list[str],
    target_total_chars: int,
    ending_mode: str = "standalone",
    *,
    market_profile: str = "qidian_longform",
    progression_mode: str = "soft_progression",
    progression_flavor: str = "",
    progression_ledger: list[object] | None = None,
    length_tolerance: float = 0.25,
) -> LocalQualityReport:
    profile = _normalized_market_profile(market_profile)
    progression_mode = _normalized_progression_mode(progression_mode)
    progression_flavor = _normalized_progression_flavor(progression_flavor)
    joined = "\n\n".join(chapters)
    report = analyze_chapter(
        joined,
        max(int(target_total_chars or 0), 1),
        character_names=None,
        market_profile=profile,
        progression_mode=progression_mode,
        progression_flavor=progression_flavor,
        length_tolerance=length_tolerance,
        strict_length_gate=False if profile == "tomato_mass" else True,
        length_extreme_multiplier=2.2 if profile == "tomato_mass" else 3.0,
        apply_progression_gate=False,
    )
    chapter_count = max(len(chapters), 1)
    chapter_openings = [_normalize_paragraph(_first_paragraph(chapter)) for chapter in chapters if chapter.strip()]
    duplicate_openings = sum(count - 1 for count in Counter(chapter_openings).values() if count > 1)
    duplicate_paragraphs = int(report.metrics.get("duplicate_paragraphs", 0))
    duplicate_sentences = int(report.metrics.get("duplicate_sentences", 0))
    total_chars = int(report.metrics.get("char_count", 0) or 0)
    target_max = int(report.metrics.get("target_chars_max", 0) or 0)
    total_over_ratio = _safe_overlength_ratio(total_chars, target_max)
    novel_length_signal_level = "ok"
    novel_length_warning = False
    novel_length_debt = False
    novel_length_hard_fail = False
    progression_length_warning = False
    if profile == "tomato_mass":
        allowed_duplicate_paragraphs = chapter_count // 300
        allowed_duplicate_sentences = max(1, chapter_count // 28)
        allowed_duplicate_openings = chapter_count // 300
    else:
        allowed_duplicate_paragraphs = chapter_count // 200
        allowed_duplicate_sentences = max(2, chapter_count // 18)
        allowed_duplicate_openings = chapter_count // 200
    issues = [
        issue
        for issue in report.issues
        if "重复段落" not in issue
        and "重复句式或重复句子" not in issue
        and not (profile == "tomato_mass" and ("正文偏长" in issue or "正文严重超长" in issue or "正文略高于目标区间上限" in issue))
    ]
    strengths = list(report.strengths)
    score = report.score
    final_excerpt = chapters[-1][-360:] if chapters else ""

    if profile == "tomato_mass" and target_max > 0:
        if total_over_ratio > 1.6:
            novel_length_signal_level = "hard_fail"
            novel_length_hard_fail = True
            issues.append(
                f"整书总字数严重超量，当前约 {total_chars} 字，已明显偏离番茄长篇目标上限 {target_max} 字。"
            )
            score -= 16
        elif total_over_ratio > 1.3:
            novel_length_signal_level = "debt"
            novel_length_debt = True
            issues.append(
                f"整书总字数明显超量，当前约 {total_chars} 字；番茄模式建议通过删重、压程序推进和收束支线回收篇幅。"
            )
            score -= 8
        elif total_over_ratio > 1.15:
            novel_length_signal_level = "warning"
            novel_length_warning = True
            issues.append(
                f"整书总字数偏高，当前约 {total_chars} 字；番茄模式建议在终盘压缩重复推进和说明性段落。"
            )
            score -= 4

    if duplicate_paragraphs > allowed_duplicate_paragraphs:
        issues.append("存在重复段落，像是生成时打转。")
    elif duplicate_paragraphs > 0:
        issues.append("存在极少量重复段落，超长篇幅下仍建议做全文压重。")
        score += 14
    else:
        strengths.append("长段重复控制在可接受范围内。")

    if duplicate_sentences > allowed_duplicate_sentences:
        issues.append("存在重复句式或重复句子。")
    elif duplicate_sentences > 0:
        issues.append("存在少量重复句式，建议做发行前压重。")
        score += 7
    else:
        strengths.append("重复句式控制在可接受范围内。")

    if duplicate_openings > allowed_duplicate_openings:
        issues.append("不同章节用了重复开场，整体感较弱。")
        score -= 10
    elif duplicate_openings > 0:
        issues.append("有少量章节开场趋同，发行前可再做差异化整理。")
        score += 7
    else:
        strengths.append("章节开场有区分度。")

    if (
        ending_mode == "standalone"
        and final_excerpt
        and ENDING_TEASER_PATTERN.search(final_excerpt)
        and not ENDING_RESOLUTION_PATTERN.search(final_excerpt)
    ):
        issues.append("结尾更像下一段故事的引子，主线收束感不足。")
        score -= 15

    progression_ledgers = list(progression_ledger or [])
    progression_stall = False
    progression_hard_fail = False
    if progression_mode == "hard_realm_progression":
        meaningful = 0
        paid_off = 0
        for item in progression_ledgers:
            status = str(getattr(item, "status", None) if not isinstance(item, dict) else item.get("status") or "").strip().lower()
            if status in {"advanced", "ready", "paid_off"}:
                meaningful += 1
            if status == "paid_off":
                paid_off += 1
        if chapter_count >= 40 and meaningful == 0:
            issues.append("硬升级模式下整书几乎没有清晰的升级里程碑推进，升级系统像挂件。")
            score -= 12
            progression_stall = True
            progression_hard_fail = True
        elif chapter_count >= 20 and meaningful <= 1:
            issues.append("硬升级模式下整书升级里程碑推进偏弱，后续需要更明确地兑现突破、资源和敌人梯度。")
            score -= 6
            progression_stall = True
        elif meaningful:
            strengths.append("升级里程碑有持续推进。")
        if ending_mode == "standalone" and chapter_count >= 40 and paid_off == 0:
            issues.append("硬升级模式下结尾缺少已兑现的阶段回报，成长链收束不足。")
            score -= 8
            progression_hard_fail = True
    score = max(0, min(100, score))
    teaser_risk = (
        ending_mode == "standalone"
        and final_excerpt
        and ENDING_TEASER_PATTERN.search(final_excerpt)
        and not ENDING_RESOLUTION_PATTERN.search(final_excerpt)
    )
    return LocalQualityReport(
        passed=(
            score >= 70
            and not report.metrics.get("placeholder_hits")
            and not novel_length_hard_fail
            and not progression_hard_fail
            and duplicate_paragraphs <= allowed_duplicate_paragraphs
            and duplicate_sentences <= allowed_duplicate_sentences
            and duplicate_openings <= allowed_duplicate_openings
            and not teaser_risk
        ),
        score=score,
        issues=issues,
        strengths=strengths,
        short_summary=(
            "整本本地检查通过。"
            if (
                score >= 70
                and not report.metrics.get("placeholder_hits")
                and not novel_length_hard_fail
                and not progression_hard_fail
                and duplicate_paragraphs <= allowed_duplicate_paragraphs
                and duplicate_sentences <= allowed_duplicate_sentences
                and duplicate_openings <= allowed_duplicate_openings
                and not teaser_risk
            )
            else "整本本地检查发现风险。"
        ),
        metrics={
            **report.metrics,
            "duplicate_openings": duplicate_openings,
            "allowed_duplicate_paragraphs": allowed_duplicate_paragraphs,
            "allowed_duplicate_sentences": allowed_duplicate_sentences,
            "allowed_duplicate_openings": allowed_duplicate_openings,
            "novel_total_chars": total_chars,
            "novel_length_over_ratio": round(total_over_ratio, 4),
            "novel_length_signal_level": novel_length_signal_level,
            "novel_length_warning": novel_length_warning,
            "novel_length_debt": novel_length_debt,
            "novel_length_hard_fail": novel_length_hard_fail,
            "progression_mode": progression_mode,
            "progression_flavor": progression_flavor,
            "progression_stall": progression_stall,
            "progression_hard_fail": progression_hard_fail,
            "progression_ledger_size": len(progression_ledgers),
            "market_profile": profile,
        }
    )


def _normalize_paragraph(text: str) -> str:
    return re.sub(r"\s+", "", text).strip()


def _normalize_story_memory_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def dedupe_repeated_paragraphs(
    text: str,
    *,
    min_normalized_length: int = LONG_DUPLICATE_PARAGRAPH_MIN_LENGTH,
) -> tuple[str, int]:
    paragraphs = [chunk.strip() for chunk in re.split(r"\n\s*\n", text) if chunk.strip()]
    if not paragraphs:
        return text, 0

    seen: set[str] = set()
    kept: list[str] = []
    removed = 0
    for paragraph in paragraphs:
        normalized = _normalize_paragraph(paragraph)
        if len(normalized) >= min_normalized_length and normalized in seen:
            removed += 1
            continue
        if len(normalized) >= min_normalized_length:
            seen.add(normalized)
        kept.append(paragraph)

    if removed == 0:
        return text, 0
    return "\n\n".join(kept).strip(), removed


def _split_sentences(text: str) -> list[str]:
    parts = [item.strip() for item in re.split(r"[。！？!?]", text) if item.strip()]
    return [part for part in parts if len(part) > 10]


def _first_paragraph(text: str) -> str:
    for chunk in re.split(r"\n\s*\n", text):
        if chunk.strip():
            return chunk.strip()
    return ""


def _duplicate_paragraph_counts(paragraphs: list[str]) -> tuple[int, int]:
    paragraph_counter = Counter(paragraphs)
    duplicate_paragraphs = 0
    duplicate_short_paragraphs = 0
    for paragraph, count in paragraph_counter.items():
        extra = count - 1
        if extra <= 0:
            continue
        if len(paragraph) >= LONG_DUPLICATE_PARAGRAPH_MIN_LENGTH:
            duplicate_paragraphs += extra
        else:
            duplicate_short_paragraphs += extra
    return duplicate_paragraphs, duplicate_short_paragraphs


def _procedural_density_issue(text: str, char_count: int, term_budget: str) -> str | None:
    if char_count <= 0:
        return None
    metrics = _procedural_density_metrics(text, char_count)
    density_per_1000 = metrics["density_per_1000"]
    distinct = metrics["distinct"]
    hits = metrics["hits"]
    budget = str(term_budget or "").strip().lower()
    if budget in {"low", "very_low"}:
        limit = 12.0
        min_hits = 14
    elif budget in {"medium", "mid"}:
        limit = 16.0
        min_hits = 18
    else:
        limit = 21.0
        min_hits = 24
    if density_per_1000 < limit or hits < min_hits or distinct < 6:
        return None
    return "术语和流程信息偏密，读者需要连续拆解程序名词，阅读阻力偏高。"


def _procedural_density_hard_fail(text: str, char_count: int, term_budget: str) -> bool:
    if char_count <= 0:
        return False
    metrics = _procedural_density_metrics(text, char_count)
    density_per_1000 = float(metrics["density_per_1000"])
    distinct = int(metrics["distinct"])
    hits = int(metrics["hits"])
    budget = str(term_budget or "").strip().lower()
    if budget in {"low", "very_low"}:
        return density_per_1000 >= 16.0 and hits >= 18 and distinct >= 7
    if budget in {"medium", "mid"}:
        return density_per_1000 >= 21.0 and hits >= 24 and distinct >= 8
    return density_per_1000 >= 26.0 and hits >= 30 and distinct >= 10


def _procedural_density_metrics(text: str, char_count: int) -> dict[str, float | int]:
    hits = 0
    distinct_terms: set[str] = set()
    for term in PROCEDURAL_TERMS:
        count = text.count(term)
        if count <= 0:
            continue
        hits += count
        distinct_terms.add(term)
    density_per_1000 = round((hits / max(char_count, 1)) * 1000, 2)
    return {
        "hits": hits,
        "distinct": len(distinct_terms),
        "density_per_1000": density_per_1000,
    }


def _propulsion_repetition_issue(current_propulsion: str, recent_history: list[str]) -> str | None:
    return _propulsion_stagnation_signal(current_propulsion, recent_history)["issue"]


def _propulsion_stagnation_signal(
    current_propulsion: str,
    recent_history: list[str],
    *,
    chapter_role: str = "",
    scene_types: list[str] | None = None,
    variation_goal: str = "",
    recent_stagnation_history: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    current = _canonical_propulsion_label(current_propulsion)
    if not current:
        return {
            "level": "",
            "issue": None,
            "same_family_tail": 0,
            "same_family_cluster": 0,
            "same_role_tail": 0,
            "same_scene_tail": 0,
            "same_variation_tail": 0,
        }
    recent = [_canonical_propulsion_label(item) for item in recent_history if _canonical_propulsion_label(item)]
    same_family_tail = _contiguous_same_family_count(recent, current)
    same_family_cluster = same_family_tail + 1 if same_family_tail else 0
    current_role = _stagnation_role_signature(chapter_role)
    current_scene_signature = _scene_type_signature(scene_types or [])
    current_variation_signature = _variation_signature(variation_goal)
    stagnation_block = _matching_stagnation_block(recent_stagnation_history or [], current)
    same_role_tail = 0
    same_scene_tail = 0
    same_variation_tail = 0
    for item in stagnation_block:
        if current_role and _stagnation_role_signature(str(item.get("chapter_role", ""))) == current_role:
            same_role_tail += 1
        item_scene_signature = _scene_type_signature(item.get("scene_types"))
        if current_scene_signature and item_scene_signature and item_scene_signature == current_scene_signature:
            same_scene_tail += 1
        item_variation_signature = _variation_signature(str(item.get("variation_goal", "")))
        if current_variation_signature and item_variation_signature and item_variation_signature == current_variation_signature:
            same_variation_tail += 1
    repetition_evidence = sum(
        1
        for count in (
            same_role_tail,
            same_scene_tail,
            same_variation_tail,
        )
        if count >= 2
    )
    level = ""
    issue: str | None = None
    if same_family_cluster >= 10 and repetition_evidence >= 2:
        level = "escalation"
        issue = "最近十章左右持续围绕同一推进簇推进，而且章功能、scene 组合或升级方式也在重复；应升级到上层做阶段判断，而不是继续用章节门硬杀。"
    elif same_family_cluster >= 5 and repetition_evidence >= 2:
        level = "debt"
        issue = "最近数章仍在同一推进簇内推进，而且章功能或升级方式开始重复，已积累空转债务；后续章节应尽量给出新的后果、代价或站位变化。"
    elif same_family_cluster >= 3 and repetition_evidence >= 2:
        level = "warning"
        issue = "最近几章仍在同一推进簇内推进，而且章功能或 scene 组合开始趋同，存在轻度空转风险；只要后果持续变化可以继续，但要避免重复确认同一结论或只把局面再抬半级。"
    return {
        "level": level,
        "issue": issue,
        "same_family_tail": same_family_tail,
        "same_family_cluster": same_family_cluster,
        "same_role_tail": same_role_tail,
        "same_scene_tail": same_scene_tail,
        "same_variation_tail": same_variation_tail,
    }


def _stagnation_role_signature(text: str) -> str:
    normalized = _normalize_story_memory_text(text)
    return normalized[:32]


def _scene_type_signature(scene_types: object) -> tuple[str, ...]:
    values: list[str] = []
    if isinstance(scene_types, (list, tuple)):
        for item in scene_types:
            normalized = _normalize_story_memory_text(str(item))
            if normalized:
                values.append(normalized[:24])
    return tuple(sorted(dict.fromkeys(values)))


def _variation_signature(text: str) -> str:
    normalized = _normalize_story_memory_text(text)
    return normalized[:48]


def _contiguous_same_family_count(history: list[str], current: str) -> int:
    if not history:
        return 0
    suffix = 0
    for item in reversed(history):
        if item != current:
            break
        suffix += 1
    prefix = 0
    for item in history:
        if item != current:
            break
        prefix += 1
    return max(prefix, suffix)


def _matching_stagnation_block(
    history: list[dict[str, object]],
    current: str,
) -> list[dict[str, object]]:
    if not history:
        return []
    suffix: list[dict[str, object]] = []
    for item in reversed(history):
        item_propulsion = _canonical_propulsion_label(str(item.get("primary_propulsion", "")))
        if item_propulsion != current:
            break
        suffix.append(item)
    prefix: list[dict[str, object]] = []
    for item in history:
        item_propulsion = _canonical_propulsion_label(str(item.get("primary_propulsion", "")))
        if item_propulsion != current:
            break
        prefix.append(item)
    return list(reversed(suffix)) if len(suffix) >= len(prefix) else prefix


def _canonical_propulsion_label(text: str) -> str:
    normalized = _normalize_paragraph(text)
    if not normalized:
        return ""
    for label, keywords in PROPULSION_KEYWORDS:
        if any(keyword in normalized for keyword in keywords):
            return label
    return normalized[:18]


def _ending_voice_convergence_issue(
    text: str,
    voice_cards: list[CharacterVoiceCard],
    *,
    ending_window: bool,
) -> str | None:
    if not ending_window:
        return None
    present_cards = [card for card in voice_cards if card.name and card.name in text]
    signal_cards = [card for card in present_cards if _voice_anchor_phrases(card)]
    if len(signal_cards) < 2:
        return None
    anchored = 0
    for card in signal_cards:
        if any(anchor and anchor in text for anchor in _voice_anchor_phrases(card)):
            anchored += 1
    if anchored * 2 >= len(signal_cards):
        return None
    return "结尾阶段多名核心角色同场时，声口差异不够明显，容易收成同一种硬句式。"


def _ending_voice_convergence_hard_fail(
    text: str,
    voice_cards: list[CharacterVoiceCard],
    *,
    ending_window: bool,
) -> bool:
    if not ending_window:
        return False
    present_cards = [card for card in voice_cards if card.name and card.name in text]
    signal_cards = [card for card in present_cards if _voice_anchor_phrases(card)]
    if len(signal_cards) < 2:
        return False
    anchored = 0
    for card in signal_cards:
        if any(anchor and anchor in text for anchor in _voice_anchor_phrases(card)):
            anchored += 1
    return anchored == 0 and len(signal_cards) >= 2


def _voice_anchor_phrases(card: CharacterVoiceCard) -> list[str]:
    phrases = [item.strip() for item in card.common_words if item and item.strip()]
    anchor_text = re.split(r"[，、；;。|/]", card.contrast_anchor or "")
    for item in anchor_text:
        stripped = item.strip()
        if len(stripped) >= 2:
            phrases.append(stripped)
    return list(dict.fromkeys(phrases))[:6]
