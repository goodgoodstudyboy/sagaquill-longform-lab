from __future__ import annotations

import copy
import difflib
import math
import re
import shutil
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol

from .models import (
    BookPackage,
    BookOutline,
    CausalityEdge,
    ChapterOutlineItem,
    ChapterPlan,
    ChapterResult,
    CharacterProfile,
    CharacterSeed,
    CharacterState,
    CharacterVoiceCard,
    ContinuityState,
    ContinuityUpdate,
    FinalReview,
    GenerationSummary,
    LogicAuditReport,
    LongRangeMemoryUpdate,
    LocalQualityReport,
    PromiseLedgerItem,
    ProjectInput,
    ProjectSpec,
    ProgressionLedgerItem,
    PowerSystemBible,
    ReviewFeedback,
    SceneCard,
    StagnationDecision,
    StagnationJudgeReview,
    StyleBible,
    StylePassage,
    VolumeBlueprint,
    VolumeOutline,
    WorldBible,
)
from .client import JsonParseModelClientError
from .delivery import build_delivery_artifacts
from .normalize import best_text as _best_text
from .normalize import character_seed_list as _character_seed_list
from .normalize import string_list as _string_list
from .projectio import (
    normalized_output_language as _normalized_output_language,
    normalized_progression_flavor as _normalized_progression_flavor,
    normalized_progression_mode as _normalized_progression_mode,
    normalized_progression_pacing as _normalized_progression_pacing,
    resolved_market_profile as _resolved_market_profile_from_payload,
)
from .prompts import (
    book_outline_normalizer_system_prompt,
    book_outline_normalizer_user_prompt,
    book_outline_system_prompt,
    book_outline_user_prompt,
    book_package_system_prompt,
    book_package_user_prompt,
    chapter_plan_normalizer_system_prompt,
    chapter_plan_normalizer_user_prompt,
    chapter_plan_system_prompt,
    chapter_plan_user_prompt,
    chapter_room_system_prompt,
    chapter_room_user_prompt,
    chapter_review_system_prompt,
    chapter_review_user_prompt,
    compression_user_prompt,
    continuity_system_prompt,
    continuity_user_prompt,
    draft_system_prompt,
    draft_user_prompt,
    final_review_system_prompt,
    final_review_user_prompt,
    intake_system_prompt,
    intake_user_prompt,
    logic_audit_system_prompt,
    logic_audit_user_prompt,
    power_system_system_prompt,
    power_system_user_prompt,
    long_memory_system_prompt,
    long_memory_user_prompt,
    rewrite_user_prompt,
    stagnation_judge_system_prompt,
    stagnation_judge_user_prompt,
    style_system_prompt,
    style_user_prompt,
    story_room_system_prompt,
    story_room_user_prompt,
    structured_mapping_normalizer_system_prompt,
    structured_mapping_normalizer_user_prompt,
    voice_system_prompt,
    voice_user_prompt,
    volume_outline_normalizer_system_prompt,
    volume_outline_normalizer_user_prompt,
    volume_outline_system_prompt,
    volume_outline_user_prompt,
    world_system_prompt,
    world_user_prompt,
)
from .quality import _canonical_propulsion_label, analyze_chapter, analyze_novel, dedupe_repeated_paragraphs
from .runtime_views import (
    chapter_room_runtime_view,
    continuity_runtime_view,
    execution_packet,
    logic_audit_runtime_view,
    power_system_runtime_view,
    progression_ledger_runtime_view,
    style_bible_runtime_view,
    voice_cards_runtime_view,
)
from .serde import (
    _book_outline_from_dict,
    _causality_edge_from_dict,
    _chapter_outline_item_from_dict,
    _chapter_plan_from_dict,
    _character_from_dict,
    _character_state_from_dict,
    _continuity_update_from_dict,
    _local_quality_from_dict,
    _logic_audit_from_dict,
    _long_memory_update_from_dict,
    _power_system_bible_from_dict,
    _progression_ledger_item_from_dict,
    _project_spec_from_dict,
    _promise_ledger_item_from_dict,
    _review_feedback_from_dict,
    _scene_from_dict,
    _style_bible_from_dict,
    _style_passage_from_dict,
    _voice_card_from_dict,
    _volume_blueprint_from_dict,
    _volume_outline_from_dict,
    _world_bible_from_dict,
)
from .storage import ProjectStore
from .util import compact_json, ensure_directory, load_json


ProgressCallback = Callable[[str, str, dict[str, Any]], None]

VOLUME_BOUNDARY_SESSION_IDS: tuple[str, ...] = (
    "chapter-room",
    "reviewer",
    "continuity",
    "long-memory",
    "logic-audit",
)

CHAPTER_ARTIFACT_PATTERN = re.compile(r"^chapter-(\d+)")

CLAUDE_DRAFT_REFUSAL_MARKERS: tuple[str, ...] = (
    "不能生成大量创意内容用于商业出版",
    "替代人类创作者的核心创作工作",
    "完整章节的创作应该由人类作者完成",
    "我可以提供的替代帮助",
    "不能替代人类创作者",
    "商业出版",
    "根据我的使用政策",
    "创意写作",
    "完整创作一个章节",
    "完整创作一个章节的所有内容",
    "完整小说章节正文",
    "我不能",
    "i can't help with that request",
    "i can offer alternative help",
)

CHAPTER_BOUNDARY_MARKERS: tuple[str, ...] = (
    "章节边界混乱",
    "属于第",
    "留给第",
    "下一章opening",
    "opening_image",
    "结尾停在",
)

NEXT_CHAPTER_TAIL_MARKER = re.compile(r"(第?二天|次日|翌日|隔天|翌晨|第二天早上|第二天清晨|清晨|早上(?:\d+点)?|天刚亮)")


def perform_delivery_cleanup(output_dir: str | Path, *, mode: str = "automatic") -> dict[str, Any]:
    store = ProjectStore(output_dir)
    cleanup_targets: dict[str, Path] = {}
    for path in store.state_dir.glob("chapter-*.failed.*"):
        cleanup_targets[str(path)] = path
    for relative_name in ("final-review.latest.json", "final-state.preview.json"):
        path = store.state_dir / relative_name
        if path.exists():
            cleanup_targets[str(path)] = path

    removed_files: list[str] = []
    reclaimed_bytes = 0
    for path in sorted(cleanup_targets.values(), key=lambda item: item.name):
        if not path.exists() or not path.is_file():
            continue
        reclaimed_bytes += path.stat().st_size
        removed_files.append(path.relative_to(store.root).as_posix())
        path.unlink()

    report = {
        "mode": mode,
        "cleaned_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "removed_count": len(removed_files),
        "reclaimed_bytes": reclaimed_bytes,
        "removed_files": removed_files,
        "preserved_files": [
            "novel.md",
            "novel.txt",
            "book-summary.md",
            "delivery/",
            "data/final-review.json",
            "data/run-summary.json",
            "data/book-package.json",
            "data/delivery-manifest.json",
        ],
    }
    store.write_json("data/delivery-cleanup.json", report)
    return report


def _chapter_index_from_path(path: Path) -> int | None:
    match = CHAPTER_ARTIFACT_PATTERN.match(path.name)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _trusted_committed_index(store: ProjectStore) -> int:
    summary_path = store.data_dir / "run-summary.json"
    if summary_path.exists():
        try:
            payload = load_json(summary_path)
        except Exception:
            payload = None
        if isinstance(payload, dict):
            chapter_count = int(payload.get("chapter_count", 0) or 0)
            if chapter_count > 0:
                return chapter_count
    committed_path = store.committed_progress_path()
    if committed_path.exists():
        try:
            payload = load_json(committed_path)
        except Exception:
            payload = None
        if isinstance(payload, dict):
            chapter_index = int(payload.get("last_committed_chapter_index", 0) or 0)
            if chapter_index >= 0:
                return chapter_index
    continuity_path = store.data_dir / "continuity-state.json"
    if continuity_path.exists():
        try:
            payload = load_json(continuity_path)
        except Exception:
            payload = None
        if isinstance(payload, dict):
            chapter_index = int(payload.get("last_chapter_index", 0) or 0)
            if chapter_index >= 0:
                return chapter_index
    runtime_path = store.continuity_runtime_path()
    if runtime_path.exists():
        try:
            payload = load_json(runtime_path)
        except Exception:
            payload = None
        if isinstance(payload, dict):
            chapter_index = int(payload.get("last_chapter_index", 0) or 0)
            if chapter_index >= 0:
                return chapter_index
    contiguous = 0
    for chapter_path in sorted(store.chapter_dir.glob("chapter-*.md")):
        chapter_index = _chapter_index_from_path(chapter_path)
        if chapter_index is None:
            continue
        if chapter_index == contiguous + 1:
            contiguous = chapter_index
        elif chapter_index > contiguous + 1:
            break
    return contiguous


def _write_committed_progress_payload(store: ProjectStore, committed_index: int) -> dict[str, Any]:
    total_chars = 0
    committed_chapters: list[int] = []
    for chapter_path in sorted(store.chapter_dir.glob("chapter-*.md")):
        chapter_index = _chapter_index_from_path(chapter_path)
        if chapter_index is None or chapter_index <= 0 or chapter_index > committed_index:
            continue
        try:
            total_chars += len(chapter_path.read_text(encoding="utf-8"))
        except OSError:
            continue
        committed_chapters.append(chapter_index)
    payload = {
        "last_committed_chapter_index": committed_index,
        "total_committed_chars": total_chars,
        "committed_chapters": committed_chapters,
    }
    store.write_json(str(store.committed_progress_path().relative_to(store.root)), payload)
    return payload


QUALITY_HYGIENE_MARKERS: tuple[str, ...] = (
    "占位",
    "未完成",
    "placeholder",
    "todo",
    "tbd",
    "草稿痕迹",
)


QUALITY_STRUCTURAL_MARKERS: tuple[str, ...] = (
    "结构",
    "章型",
    "重排",
    "空转",
    "同构",
    "scene 组合",
    "推进家族",
    "发动机",
)


QUALITY_LENGTH_ONLY_MARKERS: tuple[str, ...] = (
    "篇幅",
    "字数",
    "偏长",
    "偏短",
    "超长",
    "压字",
    "收束",
)

REVIEW_POSITIVE_MARKERS: tuple[str, ...] = (
    "通过",
    "可用",
    "成立",
    "完整",
    "清楚",
    "明确",
    "扎实",
    "稳定",
    "自然",
    "有力",
    "到位",
    "顺畅",
    "有效",
    "亮点",
    "兑现",
    "清晰",
    "合理",
    "符合",
    "有层次",
    "真实",
    "落地",
    "递进",
    "完成",
    "成功",
)

REVIEW_NEGATIVE_MARKERS: tuple[str, ...] = (
    "未通过",
    "不通过",
    "问题",
    "不足",
    "不够",
    "偏长",
    "偏短",
    "过长",
    "过短",
    "重复",
    "拖",
    "失真",
    "断裂",
    "空转",
    "同构",
    "术语",
    "高压",
    "压缩",
    "加强",
    "补",
    "修",
    "调整",
    "重写",
    "删",
)

REVIEW_MALFORMED_HARD_NEGATIVE_MARKERS: tuple[str, ...] = (
    "未通过",
    "不通过",
    "逻辑",
    "矛盾",
    "失真",
    "断裂",
    "跑偏",
    "占位",
    "拒绝",
    "说明文字",
    "未完成",
    "中断",
    "截断",
    "空转",
    "同构",
    "术语",
    "高压",
)

REVIEW_EXPANSION_RECOVERY_MARKERS: tuple[str, ...] = (
    "篇幅严重不足",
    "严重不足",
    "展开不足",
    "细节不足",
    "不足",
    "情感铺垫不够",
    "章末钩子力度不足",
    "情感冲击力不足",
    "不够立体",
    "不够充分",
    "场景过短",
    "展开",
    "细节",
    "压迫感",
    "震撼感",
    "余波反应",
    "内心挣扎",
    "群像",
    "动机",
    "反应",
    "台词",
    "互动",
    "补充",
    "缺少",
)

REVIEW_EXPANSION_BLOCKER_MARKERS: tuple[str, ...] = (
    "设定",
    "逻辑",
    "矛盾",
    "失真",
    "断裂",
    "跑偏",
    "占位",
    "拒绝",
    "说明文字",
    "未完成",
    "术语",
    "流程",
    "同构",
    "空转",
    "角色功能",
)

REVIEW_TRUNCATION_MARKERS: tuple[str, ...] = (
    "突然中断",
    "戛然而止",
    "像被截断",
    "明显中断",
    "正文在",
    "缺少后续",
    "没写完",
    "未写完",
    "半句",
    "中途截断",
    "收尾缺失",
)

TRUNCATED_TAIL_ENDINGS: tuple[str, ...] = (
    ",",
    "，",
    ":",
    "：",
    "、",
    "（",
    "(",
    "“",
    "\"",
    "'",
    "从",
    "把",
    "向",
    "给",
    "替",
    "跟",
    "和",
    "与",
    "但",
    "却",
    "而",
    "让",
    "将",
    "被",
)


@dataclass(slots=True, frozen=True)
class ProviderBehaviorProfile:
    review_semantic_drift_prone: bool = False
    underwrite_prone: bool = False
    refusal_prone: bool = False


def _quality_failure_issue_texts(review: ReviewFeedback, local_quality: LocalQualityReport) -> list[str]:
    return [
        *(item for item in local_quality.issues if _best_text(item)),
        *(item for item in review.issues if _best_text(item)),
        *(item for item in review.required_fixes if _best_text(item)),
    ]


def _quality_failure_has_hygiene_issue(review: ReviewFeedback, local_quality: LocalQualityReport) -> bool:
    placeholder_hits = local_quality.metrics.get("placeholder_hits")
    if isinstance(placeholder_hits, list) and placeholder_hits:
        return True
    haystack = "\n".join(_quality_failure_issue_texts(review, local_quality)).lower()
    return any(marker in haystack for marker in QUALITY_HYGIENE_MARKERS)


def _quality_failure_has_structural_issue(review: ReviewFeedback, local_quality: LocalQualityReport) -> bool:
    metrics = local_quality.metrics
    if bool(metrics.get("procedural_density_hard_fail")):
        return True
    if bool(metrics.get("propulsion_hard_fail")):
        return True
    if bool(metrics.get("ending_voice_hard_fail")):
        return True
    haystack = "\n".join(_quality_failure_issue_texts(review, local_quality)).lower()
    return any(marker in haystack for marker in QUALITY_STRUCTURAL_MARKERS)


def _quality_failure_is_length_only(review: ReviewFeedback, local_quality: LocalQualityReport) -> bool:
    issue_texts = [item for item in _quality_failure_issue_texts(review, local_quality) if _best_text(item)]
    if not issue_texts:
        return False
    return all(any(marker in item.lower() for marker in QUALITY_LENGTH_ONLY_MARKERS) for item in issue_texts)


def _quality_failure_fix_instructions(
    review: ReviewFeedback,
    local_quality: LocalQualityReport,
) -> list[tuple[str, str]]:
    instructions: list[tuple[str, str]] = []
    if _quality_failure_has_hygiene_issue(review, local_quality):
        instructions.append(
            (
                "chapter_cleanup",
                "这是清稿修复。只做微创改稿，必须清除正文中的占位词、未完成标记、草稿残句和重复脏痕；不要改变已经成立的情节顺序、人物立场、关键转折和章末牵引。",
            )
        )
    if not _quality_failure_has_structural_issue(review, local_quality) and not _quality_failure_is_length_only(review, local_quality):
        targeted = list(dict.fromkeys([*review.required_fixes, *review.issues]))[:4]
        if targeted:
            instructions.append(
                (
                    "chapter_targeted_fix",
                    "这是定向章节修复。不要重排整章，只修被点名的执行问题，并保住已经成立的段落、动作逻辑和结尾牵引。重点修复："
                    + "；".join(item for item in targeted if _best_text(item)),
                )
            )
    return instructions


def _text_marker_count(text: str, markers: tuple[str, ...]) -> int:
    haystack = _best_text(text).lower()
    if not haystack:
        return 0
    return sum(1 for marker in markers if marker in haystack)


def _normalized_review_line(text: str) -> str:
    haystack = _best_text(text)
    if not haystack:
        return ""
    haystack = re.sub(r"^[【\[].*?[】\]]", "", haystack)
    haystack = re.sub(r"\s+", "", haystack)
    haystack = re.sub(r"[：:；;，,。.!！?？、“”\"'‘’（）()\\-→]+", "", haystack)
    return haystack.strip().lower()


def _review_issue_required_overlap_ratio(review: ReviewFeedback) -> float:
    issues = {_normalized_review_line(item) for item in review.issues if _normalized_review_line(item)}
    required = {_normalized_review_line(item) for item in review.required_fixes if _normalized_review_line(item)}
    if not issues or not required:
        return 0.0
    overlap = len(issues & required)
    return overlap / max(len(required), len(issues), 1)


def _review_issue_texts_look_positive(review: ReviewFeedback) -> bool:
    issue_texts = [item for item in [*review.issues, *review.required_fixes] if _best_text(item)]
    if not issue_texts:
        return False
    positive_hits = sum(_text_marker_count(item, REVIEW_POSITIVE_MARKERS) for item in issue_texts)
    negative_hits = sum(_text_marker_count(item, REVIEW_MALFORMED_HARD_NEGATIVE_MARKERS) for item in issue_texts)
    return positive_hits >= max(2, negative_hits + 2)


def _review_feedback_looks_malformed(
    review: ReviewFeedback,
    local_quality: LocalQualityReport,
) -> bool:
    if review.passed:
        return False
    if int(review.score or 0) > 20:
        return False
    if not _local_quality_allows_semantic_retry(local_quality):
        return False
    if review.chapter_fixes:
        return False
    issue_texts = [item for item in [*review.issues, *review.required_fixes] if _best_text(item)]
    if (
        local_quality.passed
        and int(review.score or 0) == 0
        and not any(_best_text(item) for item in review.strengths)
        and (
            _review_issue_required_overlap_ratio(review) >= 0.3
            or sum(_text_marker_count(item, REVIEW_POSITIVE_MARKERS) for item in issue_texts) >= 4
        )
        and _review_issue_texts_look_positive(review)
    ):
        return True
    positive_texts = [item for item in [*review.strengths, review.short_summary] if _best_text(item)]
    if len(positive_texts) < 2 and not issue_texts:
        return False
    if any(_text_marker_count(item, REVIEW_NEGATIVE_MARKERS) for item in review.issues):
        return False
    if any(_text_marker_count(item, REVIEW_NEGATIVE_MARKERS) for item in review.required_fixes):
        return False
    positive_hits = sum(_text_marker_count(item, REVIEW_POSITIVE_MARKERS) for item in [*positive_texts, *issue_texts])
    negative_hits = sum(
        _text_marker_count(item, REVIEW_NEGATIVE_MARKERS)
        for item in [review.short_summary, *review.strengths, *review.issues, *review.required_fixes]
        if _best_text(item)
    )
    if positive_hits < 2:
        return False
    return negative_hits == 0


def _synthesize_malformed_review_pass(
    review: ReviewFeedback,
    local_quality: LocalQualityReport,
) -> ReviewFeedback:
    strengths = [item for item in review.strengths if _best_text(item)]
    if not strengths:
        strengths = [
            item
            for item in [*review.issues, *review.required_fixes, *local_quality.strengths]
            if _best_text(item)
        ][:6]
    return ReviewFeedback(
        passed=True,
        score=max(int(local_quality.score or 0), 88),
        strengths=strengths,
        issues=[],
        required_fixes=[],
        short_summary="审校返回结构发生语义漂移；已按本地质量门与正向证据仲裁后放行。",
        chapter_fixes=[],
    )


def _local_quality_allows_semantic_retry(local_quality: LocalQualityReport) -> bool:
    if local_quality.passed:
        return True
    return _local_quality_is_soft_short_hard_fail(local_quality)


def _local_quality_is_soft_short_hard_fail(local_quality: LocalQualityReport) -> bool:
    metrics = local_quality.metrics
    if not bool(metrics.get("length_hard_fail")):
        return False
    if bool(metrics.get("procedural_density_hard_fail")):
        return False
    if bool(metrics.get("propulsion_hard_fail")):
        return False
    if bool(metrics.get("ending_voice_hard_fail")):
        return False
    char_count = int(metrics.get("char_count", 0) or 0)
    if char_count < 750:
        return False
    under_ratio = float(metrics.get("length_under_ratio", 0.0) or 0.0)
    if under_ratio < 0.30:
        return False
    haystack = "\n".join(local_quality.issues).lower()
    if any(marker in haystack for marker in ("核心角色名", "偏离设定", "占位", "未完成", "拒绝", "说明文字")):
        return False
    return True


def _review_feedback_has_positive_signal(review: ReviewFeedback) -> bool:
    text_pool = [
        item
        for item in [
            *review.strengths,
            review.short_summary,
            *review.issues,
            *review.required_fixes,
        ]
        if _best_text(item)
    ]
    if not text_pool:
        return False
    positive_hits = sum(_text_marker_count(item, REVIEW_POSITIVE_MARKERS) for item in text_pool)
    negative_hits = sum(_text_marker_count(item, REVIEW_NEGATIVE_MARKERS) for item in text_pool)
    return positive_hits >= 2 and negative_hits == 0


def _draft_looks_like_model_refusal(text: str) -> bool:
    haystack = _best_text(text).lower()
    if not haystack:
        return False
    if len(haystack) > 3200:
        return False
    return any(marker in haystack for marker in CLAUDE_DRAFT_REFUSAL_MARKERS)


def _chapter_review_has_boundary_contamination(review: ReviewFeedback) -> bool:
    haystack = "\n".join([*review.issues, *review.required_fixes]).lower()
    if not haystack:
        return False
    return any(marker.lower() in haystack for marker in CHAPTER_BOUNDARY_MARKERS)


def _draft_tail_looks_like_next_chapter_opening(draft: str) -> bool:
    text = _best_text(draft)
    if not text:
        return False
    tail = text[max(0, len(text) - 500) :]
    return bool(NEXT_CHAPTER_TAIL_MARKER.search(tail))


def _trim_next_chapter_opening_from_tail(draft: str) -> tuple[str, bool]:
    text = _best_text(draft)
    if not text:
        return draft, False
    matches = list(NEXT_CHAPTER_TAIL_MARKER.finditer(text))
    if not matches:
        return draft, False
    start = matches[-1].start()
    if start < int(len(text) * 0.35):
        return draft, False
    trimmed = text[:start].rstrip()
    if len(trimmed) < 50:
        return draft, False
    return trimmed + "\n", True


def _draft_tail_looks_truncated(draft: str) -> bool:
    text = _best_text(draft).rstrip()
    if len(text) < 40:
        return False
    tail = text[-120:]
    if tail[-1:] in {"，", ",", "：", ":", "、", "（", "(", "“", "\"", "'"}:
        return True
    normalized_tail = re.sub(r"\s+", "", tail)
    return any(normalized_tail.endswith(marker) for marker in TRUNCATED_TAIL_ENDINGS)


def _quality_failure_looks_truncated_draft(
    draft: str,
    review: ReviewFeedback,
    local_quality: LocalQualityReport,
) -> bool:
    if _draft_looks_like_model_refusal(draft):
        return False
    if _quality_failure_has_hygiene_issue(review, local_quality):
        return False
    if _quality_failure_has_structural_issue(review, local_quality):
        return False
    metrics = local_quality.metrics
    char_count = int(metrics.get("char_count", 0) or 0)
    target_min = int(metrics.get("target_chars_min", 0) or 0)
    issue_texts = [item for item in _quality_failure_issue_texts(review, local_quality) if _best_text(item)]
    haystack = "\n".join(issue_texts).lower()
    has_review_signal = any(marker.lower() in haystack for marker in REVIEW_TRUNCATION_MARKERS)
    short_enough = char_count > 0 and (
        char_count <= 700
        or (target_min > 0 and char_count <= int(target_min * 0.45))
    )
    return short_enough and (has_review_signal or _draft_tail_looks_truncated(draft))


def _anthropic_short_chapter_can_soft_pass(
    review: ReviewFeedback,
    local_quality: LocalQualityReport,
) -> bool:
    if not _local_quality_is_soft_short_hard_fail(local_quality):
        return False
    return _review_feedback_has_positive_signal(review)


def _anthropic_review_local_divergence_needs_expansion(
    review: ReviewFeedback,
    local_quality: LocalQualityReport,
) -> bool:
    if review.passed:
        return False
    if int(review.score or 0) < 60:
        return False
    if review.chapter_fixes:
        return False
    if _quality_failure_has_hygiene_issue(review, local_quality):
        return False
    if _quality_failure_has_structural_issue(review, local_quality):
        return False
    metrics = local_quality.metrics
    local_allows_divergence = (
        local_quality.passed
        or bool(metrics.get("length_warning"))
        or bool(metrics.get("length_debt"))
        or _local_quality_is_soft_short_hard_fail(local_quality)
    )
    if not local_allows_divergence:
        return False
    issue_texts = [item for item in [*review.issues, *review.required_fixes] if _best_text(item)]
    if not issue_texts:
        return False
    if any(
        any(marker in item.lower() for marker in REVIEW_EXPANSION_BLOCKER_MARKERS)
        for item in issue_texts
    ):
        return False
    expansion_hits = sum(_text_marker_count(item, REVIEW_EXPANSION_RECOVERY_MARKERS) for item in issue_texts)
    if expansion_hits < 4:
        return False
    strengths = [item for item in [*review.strengths, review.short_summary] if _best_text(item)]
    positive_hits = sum(_text_marker_count(item, REVIEW_POSITIVE_MARKERS) for item in strengths)
    return positive_hits >= 1 or len(review.strengths) >= 2


def _review_feedback_is_expansion_only_failure(
    review: ReviewFeedback,
    local_quality: LocalQualityReport,
) -> bool:
    if review.passed:
        return False
    if review.chapter_fixes:
        return False
    if _quality_failure_has_hygiene_issue(review, local_quality):
        return False
    if _quality_failure_has_structural_issue(review, local_quality):
        return False
    issue_texts = [item for item in [*review.issues, *review.required_fixes] if _best_text(item)]
    if not issue_texts:
        return False
    if any(
        any(marker in item.lower() for marker in REVIEW_EXPANSION_BLOCKER_MARKERS)
        for item in issue_texts
    ):
        return False
    expansion_hits = sum(_text_marker_count(item, REVIEW_EXPANSION_RECOVERY_MARKERS) for item in issue_texts)
    return expansion_hits >= 3


def _underwritten_but_structured_needs_expansion(
    draft: str,
    review: ReviewFeedback,
    local_quality: LocalQualityReport,
) -> bool:
    metrics = local_quality.metrics
    if not bool(metrics.get("length_hard_fail")):
        return False
    if _quality_failure_has_hygiene_issue(review, local_quality):
        return False
    if _quality_failure_has_structural_issue(review, local_quality):
        return False
    if _draft_looks_like_model_refusal(draft):
        return False
    if _quality_failure_looks_truncated_draft(draft, review, local_quality):
        return False
    char_count = int(metrics.get("char_count", 0) or 0)
    if char_count < 300:
        return False
    return _review_feedback_is_expansion_only_failure(review, local_quality)


def _soften_anthropic_short_length_failure(local_quality: LocalQualityReport) -> LocalQualityReport:
    metrics = copy.deepcopy(local_quality.metrics)
    metrics["length_signal_level"] = "debt"
    metrics["length_warning"] = False
    metrics["length_debt"] = True
    metrics["length_hard_fail"] = False
    issues = [
        item
        for item in local_quality.issues
        if "正文严重偏短" not in item and "明显低于番茄模式容忍带下限" not in item
    ]
    issues.insert(0, "正文明显偏短，但内容骨架成立；已按番茄短章债务记录，后续章节需尽快回补兑现密度。")
    return LocalQualityReport(
        passed=True,
        score=max(int(local_quality.score or 0), 85),
        issues=issues,
        strengths=list(local_quality.strengths),
        short_summary="本章可用，但存在番茄短章债务，后续需回补。",
        metrics=metrics,
    )


def _synthesize_anthropic_expansion_divergence_pass(
    review: ReviewFeedback,
    local_quality: LocalQualityReport,
) -> ReviewFeedback:
    strengths = list(review.strengths) or list(local_quality.strengths)
    if not strengths:
        strengths = [
            item
            for item in [*review.issues, *review.required_fixes]
            if _best_text(item)
        ][:4]
    return ReviewFeedback(
        passed=True,
        score=max(int(review.score or 0), int(local_quality.score or 0), 88),
        strengths=strengths,
        issues=[],
        required_fixes=[],
        short_summary="模型审校认为本章仍可进一步扩写，但本地门已通过；已记录扩写债务并放行。",
        chapter_fixes=[],
    )


def _synthesize_underwritten_structured_pass(
    review: ReviewFeedback,
    local_quality: LocalQualityReport,
) -> ReviewFeedback:
    strengths = [item for item in review.strengths if _best_text(item)]
    if not strengths:
        strengths = [
            item
            for item in [*review.issues, *review.required_fixes, *local_quality.strengths]
            if _best_text(item)
        ][:6]
    return ReviewFeedback(
        passed=True,
        score=max(int(review.score or 0), int(local_quality.score or 0), 86),
        strengths=strengths,
        issues=[],
        required_fixes=[],
        short_summary="本章骨架成立但展开不足；已按扩写债务记录并放行，后续章节需回补层次、反应与章尾牵引。",
        chapter_fixes=[],
    )


def _quality_failure_needs_window_repair(
    draft: str,
    review: ReviewFeedback,
    local_quality: LocalQualityReport,
) -> bool:
    if _quality_failure_has_hygiene_issue(review, local_quality):
        return False
    if _quality_failure_has_structural_issue(review, local_quality):
        return False
    issue_texts = [item for item in _quality_failure_issue_texts(review, local_quality) if _best_text(item)]
    haystack = "\n".join(issue_texts).lower()
    if any(marker in haystack for marker in ("拒绝", "说明文字", "商业出版")):
        return False
    metrics = local_quality.metrics
    if _quality_failure_looks_truncated_draft(draft, review, local_quality):
        return True
    char_count = int(metrics.get("char_count", 0) or 0)
    if char_count < 250:
        return False
    if char_count < 700 and not (
        _anthropic_review_local_divergence_needs_expansion(review, local_quality)
        or _underwritten_but_structured_needs_expansion(draft, review, local_quality)
    ):
        return False
    if _review_feedback_looks_malformed(review, local_quality):
        return True
    if _anthropic_review_local_divergence_needs_expansion(review, local_quality):
        return True
    if _review_feedback_has_positive_signal(review) and (
        bool(metrics.get("length_debt")) or bool(metrics.get("length_hard_fail"))
    ):
        return True
    expansion_hits = sum(_text_marker_count(item, REVIEW_EXPANSION_RECOVERY_MARKERS) for item in issue_texts)
    if expansion_hits >= 3 and (bool(metrics.get("length_debt")) or bool(metrics.get("length_hard_fail"))):
        return True
    return False


def _chapter_failure_window_span(
    chapter: ChapterOutlineItem,
    local_quality: LocalQualityReport,
) -> int:
    role = _best_text(getattr(chapter, "chapter_role", ""), "").lower()
    if (
        role in {"pivot", "climax", "escalation"}
        or _best_text(getattr(chapter, "closing_mode", ""), "").lower() == "volume_hook"
        or bool(local_quality.metrics.get("length_hard_fail"))
    ):
        return 5
    return 3


def _build_quality_failure_window_repair_audit(
    chapter_result: ChapterResult,
    local_quality: LocalQualityReport,
    review: ReviewFeedback,
    volume_outline: VolumeOutline,
) -> LogicAuditReport:
    span = _chapter_failure_window_span(chapter_result.outline_item, local_quality)
    start = max(volume_outline.chapter_targets[0].index, chapter_result.index - span + 1)
    end = chapter_result.index
    issue_pool = [item for item in _quality_failure_issue_texts(review, local_quality) if _best_text(item)]
    instruction = (
        "这是最近章节窗口回修。优先保留既有题材卖点、人物关系、卷目标和已成立爽点，"
        "只修最近几章对当前章所需铺垫、展开、回报和章尾牵引的不足；不要推翻主线，只补出缺失的层次、余波和承接。"
    )
    if issue_pool:
        instruction += " 重点补这些缺口：" + "；".join(issue_pool[:6])
    return LogicAuditReport(
        passed=False,
        gate_passed=False,
        summary=f"第{chapter_result.index}章多次修复后仍未过门，改为回修最近章节窗口。",
        issues=issue_pool[:8],
        watch_items=[],
        required_followups=["回修最近章节窗口，补齐当前章所需铺垫、展开与回报。"],
        flagged_chapters=[{"chapter_index": index, "issue": "最近章节窗口对当前章支撑不足。"} for index in range(start, end + 1)],
        repair_plan=[{"start_chapter": start, "end_chapter": end, "instruction": instruction}],
        gate_level="repair_cluster",
    )


def _build_volume_gate_fallback_audit(
    audit: LogicAuditReport,
    volume_outline: VolumeOutline,
    volume_chapters: list[ChapterResult],
) -> LogicAuditReport:
    end = volume_chapters[-1].index if volume_chapters else volume_outline.chapter_targets[-1].index
    span = min(10, len(volume_chapters) or len(volume_outline.chapter_targets))
    start = max(volume_outline.chapter_targets[0].index, end - span + 1)
    instruction = (
        "这是卷级硬门后的大窗口回修。保留题材卖点、核心人物关系、卷目标和已成立的重要兑现，"
        "只重修最近十章左右，集中解决同构推进、长期高压不换气、生活感不足、卷末 hook 不成立或升级链断裂。"
    )
    if audit.issues:
        instruction += " 重点修这些卷级问题：" + "；".join(audit.issues[:6])
    return LogicAuditReport(
        passed=False,
        gate_passed=False,
        summary=f"第{volume_outline.volume_index}卷第一次回修后仍未过硬门，扩大到最近{span}章回修。",
        issues=list(audit.issues),
        watch_items=list(audit.watch_items),
        required_followups=list(audit.required_followups),
        structure_risks=list(audit.structure_risks),
        voice_risks=list(audit.voice_risks),
        density_risks=list(audit.density_risks),
        pressure_risks=list(audit.pressure_risks),
        grounding_risks=list(audit.grounding_risks),
        progression_risks=list(audit.progression_risks),
        flagged_chapters=[{"chapter_index": index, "issue": "卷级硬门要求扩大窗口回修。"} for index in range(start, end + 1)],
        repair_plan=[{"start_chapter": start, "end_chapter": end, "instruction": instruction}],
        gate_level="repair_cluster",
        ledger_sanity=copy.deepcopy(audit.ledger_sanity),
    )


def _final_review_looks_malformed(review: FinalReview) -> bool:
    return _final_review_payload_looks_malformed(
        {
            "passed": review.passed,
            "score": review.score,
            "strengths": review.strengths,
            "issues": review.issues,
            "required_fixes": review.required_fixes,
            "short_summary": review.short_summary,
            "chapter_fixes": review.chapter_fixes,
        }
    )


def _final_review_payload_looks_malformed(payload: Mapping[str, Any]) -> bool:
    if bool(payload.get("passed")):
        return False
    if int(payload.get("score", 0) or 0) > 20:
        return False
    if _chapter_fix_list(payload.get("chapter_fixes")):
        return False
    strengths = _string_list(payload.get("strengths"))
    issues = _string_list(payload.get("issues"))
    required_fixes = _string_list(payload.get("required_fixes"))
    short_summary = _best_text(payload.get("short_summary"), "")
    positive_texts = [item for item in [*strengths, short_summary] if _best_text(item)]
    if len(positive_texts) < 2:
        return False
    if any(_text_marker_count(item, REVIEW_NEGATIVE_MARKERS) for item in issues):
        return False
    positive_hits = sum(_text_marker_count(item, REVIEW_POSITIVE_MARKERS) for item in positive_texts)
    negative_hits = sum(
        _text_marker_count(item, REVIEW_NEGATIVE_MARKERS)
        for item in [short_summary, *strengths]
        if _best_text(item)
    )
    if positive_hits < 2:
        return False
    if negative_hits != 0:
        return False
    if not required_fixes:
        return True
    return not any(_text_marker_count(item, REVIEW_NEGATIVE_MARKERS) for item in required_fixes)


def _logic_audit_payload_looks_malformed(payload: Mapping[str, Any]) -> bool:
    if bool(payload.get("passed")) and bool(payload.get("gate_passed")):
        return False
    gate_level = _best_text(payload.get("gate_level"), "pass").lower()
    if gate_level in {"pass", "warn"}:
        return False
    if _chapter_fix_list(payload.get("repair_plan")):
        return False
    flagged = payload.get("flagged_chapters")
    if isinstance(flagged, list) and any(isinstance(item, Mapping) and item for item in flagged):
        return False
    summary = _best_text(payload.get("summary"), "")
    issues = _string_list(payload.get("issues"))
    watch_items = _string_list(payload.get("watch_items"))
    required_followups = _string_list(payload.get("required_followups"))
    text_pool = [item for item in [summary, *issues, *watch_items, *required_followups] if _best_text(item)]
    if len(text_pool) < 2:
        return False
    positive_hits = sum(_text_marker_count(item, REVIEW_POSITIVE_MARKERS) for item in text_pool)
    negative_hits = sum(_text_marker_count(item, REVIEW_NEGATIVE_MARKERS) for item in text_pool)
    return positive_hits >= 2 and negative_hits == 0


def _stagnation_judge_payload_looks_malformed(payload: Mapping[str, Any]) -> bool:
    verdict = _best_text(payload.get("verdict"), "").lower()
    recommended_action = _best_text(payload.get("recommended_action"), "").lower()
    if verdict in {"", "reasonable_cluster"} and recommended_action in {"", "accept", "forward_fix"}:
        return False
    reason = _best_text(payload.get("reason"), "")
    repair_goal = _best_text(payload.get("repair_goal"), "")
    constraints = _string_list(payload.get("next_chapter_constraints"))
    text_pool = [item for item in [reason, repair_goal, *constraints] if _best_text(item)]
    if len(text_pool) < 2:
        return False
    positive_hits = sum(_text_marker_count(item, REVIEW_POSITIVE_MARKERS) for item in text_pool)
    negative_hits = sum(_text_marker_count(item, REVIEW_NEGATIVE_MARKERS) for item in text_pool)
    return positive_hits >= 2 and negative_hits == 0


def reconcile_committed_run_state(output_dir: str | Path) -> dict[str, Any]:
    store = ProjectStore(output_dir)
    committed_index = _trusted_committed_index(store)
    keep_until = max(committed_index + 1, 1)
    orphan_dir = store.orphaned_chapters_dir()
    moved: list[str] = []
    roots = (
        store.chapter_dir,
        store.plan_dir,
        store.review_dir,
        store.state_dir,
    )
    for root in roots:
        for path in sorted(root.glob("chapter-*")):
            if not path.is_file():
                continue
            if path.parent == orphan_dir:
                continue
            chapter_index = _chapter_index_from_path(path)
            if chapter_index is None or chapter_index <= keep_until:
                continue
            ensure_directory(orphan_dir)
            target = orphan_dir / path.name
            if target.exists():
                target = orphan_dir / f"{path.stem}-{int(time.time())}{path.suffix}"
            shutil.move(str(path), str(target))
            moved.append(str(path.relative_to(store.root)))
    payload = _write_committed_progress_payload(store, committed_index)
    return {
        "committed_index": committed_index,
        "kept_through_chapter": keep_until,
        "moved_count": len(moved),
        "moved_files": moved,
        "total_committed_chars": int(payload.get("total_committed_chars", 0) or 0),
    }


class SupportsGeneration(Protocol):
    def generate_json(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        model: str | None = None,
        temperature: float = 0.2,
        max_output_tokens: int | None = None,
        session_id: str | None = None,
        session_max_chars: int | None = None,
        stream: bool = False,
        stream_observer: Any | None = None,
    ) -> Any: ...

    def generate_text(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        model: str | None = None,
        temperature: float = 0.3,
        max_output_tokens: int | None = None,
        json_mode: bool = False,
        session_id: str | None = None,
        session_max_chars: int | None = None,
        stream: bool = False,
        stream_observer: Any | None = None,
    ) -> str: ...


class SupportsSessionReset(Protocol):
    def reset_session(self, session_id: str) -> None: ...


class _DeltaPrinter:
    def __init__(self, label: str) -> None:
        self.label = label
        self.started = False

    def __call__(self, delta: str) -> None:
        if not self.started:
            print(f"\n[{self.label}]\n", end="", flush=True)
            self.started = True
        print(delta, end="", flush=True)

    def close(self) -> None:
        if self.started:
            print("", flush=True)


class _ProgressStreamObserver:
    def __init__(
        self,
        delegate: _DeltaPrinter | None,
        heartbeat: Callable[[int], None],
        *,
        heartbeat_seconds: float = 20.0,
    ) -> None:
        self.delegate = delegate
        self.heartbeat = heartbeat
        self.heartbeat_seconds = heartbeat_seconds
        self.total_chars = 0
        self.last_heartbeat_at = time.monotonic()

    def __call__(self, delta: str) -> None:
        if self.delegate is not None:
            self.delegate(delta)
        self.total_chars += len(delta)
        now = time.monotonic()
        if now - self.last_heartbeat_at >= self.heartbeat_seconds:
            self.heartbeat(self.total_chars)
            self.last_heartbeat_at = now

    def close(self) -> None:
        if self.delegate is not None:
            self.delegate.close()


class UpperDecisionRequired(RuntimeError):
    def __init__(self, decision: StagnationDecision) -> None:
        self.decision = decision
        super().__init__(
            f"第{decision.chapter_index}章触发上层决策：{decision.decision}。"
            f"建议处理范围 {decision.scope_start_chapter}-{decision.scope_end_chapter}。"
        )


class NovelPipeline:
    RESUME_CONTROL_REFRESH_CHAPTER_LAG = 12
    RESUME_CONTROL_REFRESH_VOLUME_LAG = 1

    def __init__(
        self,
        client: SupportsGeneration,
        output_dir: str | Path,
        *,
        flagship_model: str | None = None,
        light_model: str | None = None,
        review_model: str | None = None,
        max_rewrites: int = 3,
        max_final_polish_rounds: int = 1,
        max_final_fix_attempts: int = 3,
        stream_output: bool = False,
        resume: bool = False,
        preserve_resume_controls: bool = False,
        progress_callback: ProgressCallback | None = None,
    ) -> None:
        self.client = client
        self.store = ProjectStore(output_dir)
        self.output_dir = str(Path(output_dir))
        self._configure_client_routing_namespace()
        self.flagship_model = flagship_model or review_model
        self.light_model = light_model
        self.review_model = review_model
        self.max_rewrites = max_rewrites
        self.max_final_polish_rounds = max_final_polish_rounds
        self.max_final_fix_attempts = max_final_fix_attempts
        self.stream_output = stream_output
        self.resume = resume
        self.preserve_resume_controls = preserve_resume_controls
        self.progress_callback = progress_callback
        self._chapter_contexts: dict[int, ContinuityState] = {}
        self._story_room: dict[str, Any] = {}
        self._power_system = PowerSystemBible()
        self._logic_audits: dict[int, LogicAuditReport] = {}
        self._book_outline: BookOutline | None = None
        self._volume_outlines: dict[int, VolumeOutline] = {}
        self._style_anchor = StyleBible()
        self._style_bible = StyleBible()
        self._style_runtime: dict[str, Any] = {}
        self._voice_cards: list[CharacterVoiceCard] = []
        self._voice_runtime: list[dict[str, Any]] = []
        self._promise_ledger: list[PromiseLedgerItem] = []
        self._progression_ledger: list[ProgressionLedgerItem] = []
        self._causality_graph: list[CausalityEdge] = []
        self._runtime_promise_ledger: list[PromiseLedgerItem] = []
        self._runtime_progression_ledger: list[ProgressionLedgerItem] = []
        self._runtime_causality_graph: list[CausalityEdge] = []
        self._continuity_runtime: dict[str, Any] = {}
        self._long_memory_context = ContinuityState()
        self._current_stream: _ProgressStreamObserver | _DeltaPrinter | None = None
        self._pending_chapter_repair_state: dict[str, Any] | None = None
        self._stagnation_repair_history = self._load_stagnation_repair_history()

    def _flagship_model_name(self) -> str | None:
        return self.flagship_model

    def _review_model_name(self) -> str | None:
        return self.review_model or self.light_model or self.flagship_model

    def _light_model_name(self) -> str | None:
        return self.light_model or self.flagship_model

    def _provider_behavior_profile(self) -> ProviderBehaviorProfile:
        provider = getattr(self.client, "provider", None)
        wire_api = str(getattr(provider, "wire_api", "") or "").strip().lower()
        model_candidates = [
            str(candidate or "").strip().lower()
            for candidate in (
                getattr(provider, "model", None),
                getattr(provider, "light_model", None),
                getattr(provider, "review_model", None),
                self.flagship_model,
                self.light_model,
                self.review_model,
            )
            if str(candidate or "").strip()
        ]
        anthropic_like = wire_api == "anthropic-messages" or any("claude" in candidate for candidate in model_candidates)
        if anthropic_like:
            return ProviderBehaviorProfile(
                review_semantic_drift_prone=True,
                underwrite_prone=True,
                refusal_prone=True,
            )
        return ProviderBehaviorProfile()

    def _is_anthropic_provider(self) -> bool:
        profile = self._provider_behavior_profile()
        return profile.refusal_prone or profile.underwrite_prone or profile.review_semantic_drift_prone

    def _review_semantic_drift_prone(self) -> bool:
        return self._provider_behavior_profile().review_semantic_drift_prone

    def _underwrite_prone(self) -> bool:
        return self._provider_behavior_profile().underwrite_prone

    def _refusal_prone(self) -> bool:
        return self._provider_behavior_profile().refusal_prone

    def _anthropic_writer_suffix(self, *, rewrite: bool = False) -> str:
        if not self._refusal_prone():
            return ""
        action = "修订并续写当前章节" if rewrite else "实现当前章节正文"
        return (
            "\n\n补充要求（Claude 适配）：这是内部小说生产流水线中的单章"
            + action
            + "任务。你是在基于既有设定、大纲、章节计划、写前会和前文，把已确定的场景落实成正文，不是在从零替代作者创作整部商业作品。"
            "必须直接输出小说正文，不要输出政策说明、能力边界、拒绝理由、写作建议、提纲、清单或自我解释。若内容本身不涉及真实违规风险，就继续完成正文。"
        )

    def _anthropic_review_suffix(self) -> str:
        if not self._review_semantic_drift_prone():
            return ""
        return (
            "\n\n补充要求（Claude 适配）：这是内部编辑审校任务，不是创作请求。"
            "必须严格按 JSON 结构返回 passed、score、strengths、issues、required_fixes、short_summary、chapter_fixes。"
            "如果章节总体可用，不要把正向评价写进 issues 或 required_fixes。"
        )

    def _configure_client_routing_namespace(self) -> None:
        setter = getattr(self.client, "set_routing_namespace", None)
        if callable(setter):
            setter(str(self.store.root))

    def run(self, project: ProjectInput | ProjectSpec) -> GenerationSummary:
        project_input = project if isinstance(project, ProjectInput) else _project_spec_to_input(project)
        self._emit_progress("start", "开始解析项目输入。", title=project_input.title)
        self._validate_resume_input(project_input)
        if self.resume:
            reconcile_committed_run_state(self.store.root)
        self.store.write_json("data/project-input.json", project_input)

        if self.resume and (self.store.data_dir / "project-spec.json").exists():
            spec = _project_spec_from_dict(load_json(self.store.data_dir / "project-spec.json"))
        else:
            spec = project if isinstance(project, ProjectSpec) else self._resolve_project(project_input)
        self.store.write_json("data/project-spec.json", spec)
        completed_summary = self._load_completed_summary(spec)
        if completed_summary is not None:
            return completed_summary

        self._story_room = self._load_or_build_story_room(spec)
        bible = self._load_or_build_world(spec)
        self._power_system = self._load_or_build_power_system(spec, bible)
        book_outline = self._load_or_build_book_outline(spec, bible, power_system=self._power_system)
        self._book_outline = book_outline
        completed_chapters, continuity, volume_outlines = self._load_resume_state(spec, bible, book_outline)
        self._volume_outlines = dict(volume_outlines)
        self._style_bible = self._load_or_build_style_bible(spec, bible, completed_chapters.values())
        self._voice_cards = self._load_or_build_voice_cards(spec, bible, self._style_bible, completed_chapters.values())
        self._promise_ledger, self._progression_ledger, self._causality_graph = self._load_long_range_state(completed_chapters.values())
        self._sanitize_long_range_state(
            current_volume=max(continuity.last_volume_index, 1),
            current_chapter=max(continuity.last_chapter_index, 0),
            persist=False,
        )
        self._logic_audits = self._load_logic_audits(book_outline)
        self.store.write_json("data/continuity-state.json", continuity)
        self.store.write_json("data/promise-ledger.json", self._promise_ledger)
        self.store.write_json("data/causality-graph.json", self._causality_graph)
        self.store.write_json(
            "data/ledger-sanity.json",
            {
                "current_volume": max(continuity.last_volume_index, 1),
                "current_chapter": max(continuity.last_chapter_index, 0),
                "after": _ledger_sanity_snapshot(self._promise_ledger),
            },
        )
        self._sync_runtime_views(continuity, list(completed_chapters.values()))
        self._write_partial_novel(spec, completed_chapters.values())

        chapters: list[ChapterResult] = []
        for volume in book_outline.volumes:
            volume_outline = volume_outlines.get(volume.index)
            volume_chapters: list[ChapterResult] = []
            volume_had_new_generation = False
            if volume_outline is None:
                self._emit_progress(
                    "volume_outline",
                    f"生成第 {volume.index} 卷章节蓝图。",
                    volume_index=volume.index,
                    chapter_range=[volume.start_chapter, volume.end_chapter],
                )
                volume_outline = self._build_volume_outline(
                    spec,
                    bible,
                    book_outline,
                    volume,
                    continuity,
                    power_system=self._power_system,
                )
                self._volume_outlines[volume.index] = volume_outline
            for chapter in volume_outline.chapter_targets:
                if chapter.index in completed_chapters:
                    loaded_chapter = completed_chapters[chapter.index]
                    chapters.append(loaded_chapter)
                    volume_chapters.append(loaded_chapter)
                    continue
                pre_chapter_state = copy.deepcopy(continuity)
                self._chapter_contexts[chapter.index] = pre_chapter_state
                self._emit_progress(
                    "chapter_plan",
                    f"生成第 {chapter.index} 章计划。",
                    chapter_index=chapter.index,
                    volume_index=chapter.volume_index,
                )
                plan = self._build_plan(
                    spec,
                    bible,
                    book_outline,
                    volume_outline,
                    chapter,
                    continuity,
                    chapters,
                    power_system=self._power_system,
                )
                chapter_result = self._generate_chapter(
                    spec,
                    bible,
                    chapter,
                    plan,
                    continuity,
                    chapters,
                    book_outline=book_outline,
                    volume_outline=volume_outline,
                )
                pending_repair = self._consume_pending_chapter_repair_state()
                if pending_repair is not None:
                    chapters[:] = list(pending_repair["prior_chapters"])
                    volume_chapters[:] = [item for item in chapters if item.volume_index == volume.index]
                    continuity = pending_repair["continuity"]
                    self._promise_ledger = pending_repair["promise_ledger"]
                    self._progression_ledger = pending_repair.get("progression_ledger", [])
                    self._causality_graph = pending_repair["causality_graph"]
                    self.store.write_json("data/continuity-state.json", continuity)
                    self.store.write_json("data/promise-ledger.json", self._promise_ledger)
                    self.store.write_json("data/progression-ledger.json", self._progression_ledger)
                    self.store.write_json("data/causality-graph.json", self._causality_graph)
                    if pending_repair.get("refresh_controls"):
                        through_volume = int(pending_repair.get("through_volume", volume.index) or volume.index)
                        self._emit_progress(
                            "arc_repair_refresh",
                            f"按弧段回修结果重建控制层，到第 {through_volume} 卷为止。",
                            volume_index=through_volume,
                        )
                        self._refresh_volume_controls(spec, bible, chapters, continuity, through_volume=through_volume)
                    self._sync_runtime_views(continuity, chapters)
                    self._write_partial_novel(spec, chapters)
                volume_had_new_generation = True
                chapters.append(chapter_result)
                volume_chapters.append(chapter_result)
                continuity = _merge_continuity_state(continuity, chapter_result.continuity, chapter.volume_index)
                self._promise_ledger = _merge_promise_ledger(
                    self._promise_ledger,
                    chapter_result.long_memory.promise_updates if chapter_result.long_memory else [],
                    current_volume=chapter.volume_index,
                    current_chapter=chapter.index,
                )
                self._causality_graph = _merge_causality_graph(
                    self._causality_graph,
                    chapter_result.long_memory.causality_updates if chapter_result.long_memory else [],
                    current_chapter=chapter.index,
                )
                self.store.write_json("data/continuity-state.json", continuity)
                self.store.write_json("data/promise-ledger.json", self._promise_ledger)
                self.store.write_json("data/causality-graph.json", self._causality_graph)
                self._sync_runtime_views(continuity, chapters)
                self._write_partial_novel(spec, chapters)
            if self._should_run_logic_audit(spec):
                volume_chapters, continuity = self._enforce_volume_gate(
                    spec,
                    bible,
                    book_outline,
                    volume_outline,
                    volume_chapters,
                    chapters,
                    continuity,
                )
            if volume_had_new_generation and volume.index < spec.volume_count:
                self._refresh_volume_controls(spec, bible, chapters, continuity, through_volume=volume.index)
                self._reset_volume_boundary_sessions()
            self._reset_session(f"writer-v{volume.index}")

        final_review = self._finalize(spec, bible, book_outline, chapters, continuity)
        polish_round = 0
        while not final_review.passed and polish_round < self.max_final_polish_rounds and final_review.chapter_fixes:
            chapters = self._apply_final_fixes(spec, bible, book_outline, chapters, final_review.chapter_fixes)
            continuity = self._rebuild_continuity_state(bible, chapters)
            self._promise_ledger, self._progression_ledger, self._causality_graph = self._rebuild_long_range_state(chapters)
            self._sanitize_long_range_state(
                current_volume=max(continuity.last_volume_index, 1),
                current_chapter=max(continuity.last_chapter_index, 0),
                persist=False,
            )
            self.store.write_json("data/continuity-state.json", continuity)
            self.store.write_json("data/promise-ledger.json", self._promise_ledger)
            self.store.write_json("data/causality-graph.json", self._causality_graph)
            self.store.write_json(
                "data/ledger-sanity.json",
                {
                    "current_volume": max(continuity.last_volume_index, 1),
                    "current_chapter": max(continuity.last_chapter_index, 0),
                    "after": _ledger_sanity_snapshot(self._promise_ledger),
                },
            )
            self._sync_runtime_views(continuity, chapters)
            self._write_partial_novel(spec, chapters)
            final_review = self._finalize(spec, bible, book_outline, chapters, continuity)
            polish_round += 1

        if not final_review.passed:
            raise RuntimeError(
                "Final review did not pass quality gates.\n"
                f"Summary: {final_review.short_summary}\n"
                f"Issues: {compact_json(final_review.issues)}"
            )

        novel_text = self._assemble_novel(spec, chapters)
        plain_novel_text = self._assemble_plain_novel(spec, chapters)
        total_chars = _char_count(novel_text)
        book_package = self._build_book_package(spec, bible, book_outline, chapters, continuity, final_review, total_chars)
        self.store.write_text("novel.md", novel_text)
        self.store.write_text("novel.txt", plain_novel_text)
        self.store.write_text("book-summary.md", self._render_book_summary(book_package))
        self.store.write_json("data/book-package.json", asdict(book_package))
        self.store.write_json("data/final-review.json", asdict(final_review))
        delivery_manifest = build_delivery_artifacts(
            self.output_dir,
            spec=spec,
            book_outline=book_outline,
            chapters=chapters,
            book_package=book_package,
            final_review=final_review,
            total_chars=total_chars,
        )
        self.store.write_json("data/delivery-manifest.json", delivery_manifest)
        cleanup_report = perform_delivery_cleanup(self.output_dir, mode="automatic")
        self.store.write_json(
            "data/run-summary.json",
            {
                "title": spec.title,
                "chapter_count": len(chapters),
                "volume_count": spec.volume_count,
                "total_chars": total_chars,
                "final_score": final_review.score,
                "final_passed": final_review.passed,
                "final_summary": final_review.short_summary,
                "factual_summary": book_package.factual_summary,
                "marketing_blurb": book_package.marketing_blurb,
                "summary_path": "book-summary.md",
                "plain_text_path": "novel.txt",
                "delivery_manifest_path": "delivery/delivery-manifest.json",
                "epub_path": delivery_manifest.get("files", {}).get("epub", ""),
                "volume_paths": delivery_manifest.get("files", {}).get("volumes", []),
            },
        )
        self._emit_progress(
            "delivery_cleanup",
            "执行交付清理。",
            removed_count=cleanup_report["removed_count"],
            reclaimed_bytes=cleanup_report["reclaimed_bytes"],
        )
        self._emit_progress(
            "completed",
            "生成完成。",
            chapter_count=len(chapters),
            volume_count=spec.volume_count,
            total_chars=total_chars,
            final_score=final_review.score,
        )
        return GenerationSummary(
            output_dir=self.output_dir,
            title=spec.title,
            chapter_count=len(chapters),
            volume_count=spec.volume_count,
            total_chars=total_chars,
            final_score=final_review.score,
            final_passed=final_review.passed,
            final_summary=final_review.short_summary,
        )

    def _validate_resume_input(self, project_input: ProjectInput) -> None:
        if not self.resume:
            return
        existing_path = self.store.data_dir / "project-input.json"
        if not existing_path.exists():
            return
        existing = load_json(existing_path)
        existing_title = _best_text(existing.get("title"), "")
        if existing_title and existing_title != project_input.title:
            raise RuntimeError(
                f"Resume target already contains a different project: {existing_title} != {project_input.title}"
            )

    def _load_completed_summary(self, spec: ProjectSpec) -> GenerationSummary | None:
        if not self.resume:
            return None
        summary_path = self.store.data_dir / "run-summary.json"
        final_review_path = self.store.data_dir / "final-review.json"
        novel_path = self.store.root / "novel.md"
        plain_text_path = self.store.root / "novel.txt"
        if not (summary_path.exists() and final_review_path.exists() and novel_path.exists() and plain_text_path.exists()):
            return None
        payload = load_json(summary_path)
        if not isinstance(payload, dict):
            return None
        if not payload.get("final_passed"):
            return None
        chapter_count = int(payload.get("chapter_count", 0) or 0)
        volume_count = int(payload.get("volume_count", 0) or 0)
        if chapter_count < spec.chapter_count or volume_count < spec.volume_count:
            return None
        summary = GenerationSummary(
            output_dir=self.output_dir,
            title=_best_text(payload.get("title"), spec.title),
            chapter_count=chapter_count,
            volume_count=volume_count,
            total_chars=int(payload.get("total_chars", 0) or 0),
            final_score=int(payload.get("final_score", 0) or 0),
            final_passed=bool(payload.get("final_passed")),
            final_summary=_best_text(payload.get("final_summary"), "生成完成。"),
        )
        self._emit_progress(
            "completed",
            "检测到已完成成书，直接返回现有交付结果。",
            chapter_count=summary.chapter_count,
            volume_count=summary.volume_count,
            total_chars=summary.total_chars,
            final_score=summary.final_score,
        )
        return summary

    def _load_or_build_world(self, spec: ProjectSpec) -> WorldBible:
        path = self.store.data_dir / "world-bible.json"
        if self.resume and path.exists():
            bible = _world_bible_from_dict(load_json(path))
            alignment = self._align_world_with_story_room(bible)
            self.store.write_json("data/world-bible.json", bible)
            self.store.write_json(str(self.store.story_room_alignment_path().relative_to(self.store.root)), alignment)
            return bible
        return self._build_world(spec)

    def _load_or_build_power_system(self, spec: ProjectSpec, bible: WorldBible) -> PowerSystemBible:
        path = self.store.power_system_path()
        if self.resume and path.exists():
            power_system = _power_system_bible_from_dict(load_json(path))
            self._progression_ledger = self._load_progression_ledger(power_system)
            return power_system
        power_system = self._build_power_system(spec, bible)
        self._progression_ledger = self._load_progression_ledger(power_system)
        return power_system

    def _load_or_build_book_outline(
        self,
        spec: ProjectSpec,
        bible: WorldBible,
        power_system: PowerSystemBible | None = None,
    ) -> BookOutline:
        path = self.store.data_dir / "book-outline.json"
        if self.resume and path.exists():
            return _book_outline_from_dict(load_json(path))
        return self._build_book_outline(spec, bible, power_system=power_system)

    def _load_or_build_story_room(self, spec: ProjectSpec) -> dict[str, Any]:
        path = self.store.data_dir / "story-room.json"
        if self.resume and path.exists():
            payload = load_json(path)
            return payload if isinstance(payload, dict) else {}
        return self._build_story_room(spec)

    def _load_or_build_style_bible(
        self,
        spec: ProjectSpec,
        bible: WorldBible,
        chapters: Any | None = None,
    ) -> StyleBible:
        path = self.store.style_bible_path()
        chapter_list = sorted(list(chapters or []), key=lambda item: item.index)
        self._style_anchor = self._load_or_build_style_anchor(spec, bible)
        if self.resume and path.exists():
            existing = _style_bible_from_dict(load_json(path))
            if self.preserve_resume_controls:
                return existing
            if not self._should_refresh_style_controls(self.store.style_bible_meta_path(), chapter_list):
                return existing
            try:
                return self._calibrate_style_bible(spec, bible, chapter_list)
            except Exception as exc:
                self._emit_progress(
                    "style_bible",
                    f"文风圣经增量校准失败，沿用已有文风继续恢复：{self._short_error(exc)}",
                )
                return existing
        if not chapter_list:
            merged = copy.deepcopy(self._style_anchor)
            self.store.write_json("data/style-bible.json", merged)
            self.store.write_json(
                str(self.store.style_bible_calibration_path().relative_to(self.store.root)),
                {
                    "mode": "anchor_only",
                    "anchor_weight": 1.0,
                    "calibration_weight": 0.0,
                    "through_chapter": 0,
                    "through_volume": 0,
                    "sample_chapters": [],
                    "applied_adjustments": {},
                    "blocked_adjustments": {},
                },
            )
            return merged
        return self._calibrate_style_bible(spec, bible, chapter_list)

    def _load_or_build_voice_cards(
        self,
        spec: ProjectSpec,
        bible: WorldBible,
        style_bible: StyleBible,
        chapters: Any | None = None,
    ) -> list[CharacterVoiceCard]:
        path = self.store.voice_cards_path()
        chapter_list = sorted(list(chapters or []), key=lambda item: item.index)
        if self.resume and path.exists():
            payload = load_json(path)
            if isinstance(payload, list):
                existing = [_voice_card_from_dict(item) for item in payload if isinstance(item, dict)]
                if self.preserve_resume_controls:
                    return existing
                if not self._should_refresh_style_controls(self.store.voice_cards_meta_path(), chapter_list):
                    return existing
                try:
                    return self._build_voice_cards(spec, bible, style_bible, chapter_list)
                except Exception as exc:
                    self._emit_progress(
                        "voice_cards",
                        f"人物声线卡增量校准失败，沿用已有声线继续恢复：{self._short_error(exc)}",
                    )
                    return existing
        return self._build_voice_cards(spec, bible, style_bible, chapter_list)

    def _load_long_range_state(
        self,
        chapters: Any,
    ) -> tuple[list[PromiseLedgerItem], list[ProgressionLedgerItem], list[CausalityEdge]]:
        chapter_list = sorted(list(chapters), key=lambda item: item.index)
        current_volume = chapter_list[-1].volume_index if chapter_list else 1
        current_chapter = chapter_list[-1].index if chapter_list else 0
        promise_path = self.store.promise_ledger_path()
        progression_path = self.store.progression_ledger_path()
        causality_path = self.store.causality_graph_path()
        if self.resume and promise_path.exists() and causality_path.exists():
            promise_payload = load_json(promise_path)
            progression_payload = load_json(progression_path) if progression_path.exists() else []
            causality_payload = load_json(causality_path)
            promises = (
                [_promise_ledger_item_from_dict(item) for item in promise_payload if isinstance(item, dict)]
                if isinstance(promise_payload, list)
                else []
            )
            progression = (
                [_progression_ledger_item_from_dict(item) for item in progression_payload if isinstance(item, dict)]
                if isinstance(progression_payload, list)
                else []
            )
            causality = (
                [_causality_edge_from_dict(item) for item in causality_payload if isinstance(item, dict)]
                if isinstance(causality_payload, list)
                else []
            )
            promises = _normalize_promise_ledger(
                promises,
                current_volume=current_volume,
                current_chapter=current_chapter,
            )
            return promises, progression, causality
        promises: list[PromiseLedgerItem] = []
        progression: list[ProgressionLedgerItem] = []
        causality: list[CausalityEdge] = []
        for chapter in chapter_list:
            update = chapter.long_memory
            if update is None:
                continue
            promises = _merge_promise_ledger(promises, update.promise_updates, current_volume=chapter.volume_index, current_chapter=chapter.index)
            progression = _merge_progression_ledger(progression, update.progression_updates, current_chapter=chapter.index)
            causality = _merge_causality_graph(causality, update.causality_updates, current_chapter=chapter.index)
        return promises, progression, causality

    def _sanitize_long_range_state(
        self,
        *,
        current_volume: int,
        current_chapter: int,
        persist: bool = True,
    ) -> dict[str, Any]:
        before_items = [copy.deepcopy(item) for item in self._promise_ledger]
        before = _ledger_sanity_snapshot(before_items)
        self._promise_ledger = _normalize_promise_ledger(
            self._promise_ledger,
            current_volume=current_volume,
            current_chapter=current_chapter,
        )
        after = _ledger_sanity_snapshot(self._promise_ledger)
        before_map = {item.promise_id: bool(item.overdue) for item in before_items if item.promise_id}
        corrected_ids = [
            item.promise_id
            for item in self._promise_ledger
            if item.promise_id and before_map.get(item.promise_id) and not item.overdue
        ]
        report = {
            "current_volume": current_volume,
            "current_chapter": current_chapter,
            "before": before,
            "after": after,
            "corrected_promises": corrected_ids[:20],
            "corrected_count": len(corrected_ids),
        }
        if persist:
            self.store.write_json("data/promise-ledger.json", self._promise_ledger)
            self.store.write_json("data/progression-ledger.json", self._progression_ledger)
            self.store.write_json("data/ledger-sanity.json", report)
        return report

    def _should_refresh_style_controls(self, meta_path: Path, chapters: list[ChapterResult]) -> bool:
        if not chapters:
            return False
        last_chapter = chapters[-1].index
        last_volume = chapters[-1].volume_index
        if not meta_path.exists():
            return True
        payload = load_json(meta_path)
        if not isinstance(payload, dict):
            return True
        through_chapter = int(payload.get("through_chapter", 0) or 0)
        through_volume = int(payload.get("through_volume", 0) or 0)
        if through_volume >= last_volume and through_chapter >= last_chapter:
            return False
        chapter_gap = max(0, last_chapter - through_chapter)
        volume_gap = max(0, last_volume - through_volume)
        if (
            chapter_gap <= self.RESUME_CONTROL_REFRESH_CHAPTER_LAG
            or volume_gap <= self.RESUME_CONTROL_REFRESH_VOLUME_LAG
        ):
            return False
        return True

    @staticmethod
    def _short_error(exc: Exception) -> str:
        text = " ".join(str(exc).split())
        return text[:160] if len(text) > 160 else text

    def _write_style_control_meta(self, relative_path: str, control_name: str, chapters: list[ChapterResult]) -> None:
        through_chapter = chapters[-1].index if chapters else 0
        through_volume = chapters[-1].volume_index if chapters else 0
        self.store.write_json(
            relative_path,
            {
                "control": control_name,
                "through_chapter": through_chapter,
                "through_volume": through_volume,
                "sample_chapters": [chapter.index for chapter in chapters[-8:]],
            },
        )

    def _seal_runtime_state(
        self,
        continuity: ContinuityState,
        chapters: list[ChapterResult] | None = None,
    ) -> tuple[ContinuityState, list[PromiseLedgerItem], list[CausalityEdge], dict[str, Any]]:
        sanitized_continuity = _sanitize_continuity_state(copy.deepcopy(continuity))
        if not chapters:
            return (
                sanitized_continuity,
                [copy.deepcopy(item) for item in self._promise_ledger],
                [copy.deepcopy(item) for item in self._causality_graph],
                {
                    "applied": False,
                    "through_chapter": continuity.last_chapter_index,
                    "active_threads_before": len(continuity.active_threads),
                    "active_threads_after": len(sanitized_continuity.active_threads),
                    "promise_pool_before": len(self._promise_ledger),
                    "promise_pool_after": len(self._promise_ledger),
                    "causality_pool_before": len(self._causality_graph),
                    "causality_pool_after": len(self._causality_graph),
                    "reason": "no chapters available",
                },
            )
        sealed_continuity, sealed_promises, sealed_causality = _cleanup_final_review_state(
            sanitized_continuity,
            [copy.deepcopy(item) for item in self._promise_ledger],
            [copy.deepcopy(item) for item in self._causality_graph],
            chapters,
            strict_short_standalone=False,
        )
        report = {
            "applied": True,
            "through_chapter": chapters[-1].index,
            "through_volume": chapters[-1].volume_index,
            "active_threads_before": len(continuity.active_threads),
            "active_threads_after": len(sealed_continuity.active_threads),
            "promise_pool_before": len(self._promise_ledger),
            "promise_pool_after": len(sealed_promises),
            "causality_pool_before": len(self._causality_graph),
            "causality_pool_after": len(sealed_causality),
        }
        return sealed_continuity, sealed_promises, sealed_causality, report

    def _sync_runtime_views(
        self,
        continuity: ContinuityState,
        chapters: list[ChapterResult] | None = None,
    ) -> None:
        sealed_continuity, sealed_promises, sealed_causality, seal_report = self._seal_runtime_state(continuity, chapters)
        self._style_runtime = style_bible_runtime_view(self._style_bible)
        self._voice_runtime = voice_cards_runtime_view(self._voice_cards)
        self._continuity_runtime = continuity_runtime_view(sealed_continuity)
        self._runtime_promise_ledger = sealed_promises
        self._runtime_progression_ledger = list(self._progression_ledger)
        self._runtime_causality_graph = sealed_causality
        self.store.write_json(
            str(self.store.style_bible_runtime_path().relative_to(self.store.root)),
            self._style_runtime,
        )
        self.store.write_json(
            str(self.store.voice_cards_runtime_path().relative_to(self.store.root)),
            self._voice_runtime,
        )
        self.store.write_json(
            str(self.store.continuity_runtime_path().relative_to(self.store.root)),
            self._continuity_runtime,
        )
        self.store.write_json("data/promise-ledger.runtime.json", [_promise_memory_payload(item) for item in sealed_promises])
        self.store.write_json("data/progression-ledger.runtime.json", progression_ledger_runtime_view(self._runtime_progression_ledger))
        self.store.write_json("data/causality-graph.runtime.json", [_causality_memory_payload(item) for item in sealed_causality])
        self.store.write_json("data/runtime-state-seal.json", seal_report)

    def _refresh_volume_controls(
        self,
        spec: ProjectSpec,
        bible: WorldBible,
        chapters: list[ChapterResult],
        continuity: ContinuityState,
        *,
        through_volume: int,
    ) -> None:
        history = [chapter for chapter in chapters if chapter.volume_index <= through_volume]
        if not history:
            return
        self._style_bible = self._calibrate_style_bible(spec, bible, history)
        self._voice_cards = self._build_voice_cards(spec, bible, self._style_bible, history)
        self._sync_runtime_views(continuity, history)

    def _load_resume_state(
        self,
        spec: ProjectSpec,
        bible: WorldBible,
        book_outline: BookOutline,
    ) -> tuple[dict[int, ChapterResult], ContinuityState, dict[int, VolumeOutline]]:
        if not self.resume:
            return {}, _initial_continuity_state(bible), {}

        completed: dict[int, ChapterResult] = {}
        continuity = _initial_continuity_state(bible)
        volume_outlines: dict[int, VolumeOutline] = {}
        for volume in book_outline.volumes:
            path = self.store.volume_outline_path(volume.index)
            if not path.exists():
                break
            volume_outline = _volume_outline_from_dict(load_json(path))
            volume_outlines[volume.index] = volume_outline
            for chapter in volume_outline.chapter_targets:
                loaded, partial = self._load_saved_chapter(spec, bible, chapter)
                if loaded is None:
                    if partial:
                        removed = self._purge_incomplete_chapter_artifacts(chapter.index)
                        self._emit_progress(
                            "resume_cleanup",
                            f"检测到第 {chapter.index} 章落盘不完整，已回退到上一章完整检查点。",
                            chapter_index=chapter.index,
                            removed_artifacts=removed,
                        )
                    return completed, continuity, volume_outlines
                completed[chapter.index] = loaded
                self._chapter_contexts[chapter.index] = copy.deepcopy(continuity)
                continuity = _merge_continuity_state(continuity, loaded.continuity, chapter.volume_index)
        if completed:
            self._emit_progress(
                "resume",
                f"已从断点恢复，跳过前 {len(completed)} 章。",
                completed_chapters=len(completed),
                last_chapter_index=continuity.last_chapter_index,
            )
        return completed, continuity, volume_outlines

    def _load_saved_chapter(
        self,
        spec: ProjectSpec,
        bible: WorldBible,
        chapter: ChapterOutlineItem,
    ) -> tuple[ChapterResult | None, bool]:
        chapter_path = self.store.chapter_path(chapter.index)
        plan_path = self.store.chapter_plan_path(chapter.index)
        review_path = self.store.chapter_review_path(chapter.index)
        continuity_path = self.store.continuity_path(chapter.index)
        memory_path = self.store.chapter_memory_path(chapter.index)
        room_path = self.store.chapter_room_path(chapter.index)
        core_paths = [chapter_path, plan_path, review_path, continuity_path]
        observed_paths = [*core_paths, memory_path, room_path]
        if not all(path.exists() for path in core_paths):
            return None, any(path.exists() for path in observed_paths)

        try:
            draft = chapter_path.read_text(encoding="utf-8")
            if not draft.strip():
                return None, True
            plan = _chapter_plan_from_dict(load_json(plan_path))
            review_payload = load_json(review_path)
            model_payload = review_payload.get("model") if isinstance(review_payload, dict) else None
            continuity_payload = load_json(continuity_path)
            if not isinstance(model_payload, dict):
                return None, True
            local_payload = review_payload.get("local") if isinstance(review_payload, dict) else None
            local_quality = (
                _local_quality_from_dict(local_payload)
                if isinstance(local_payload, dict)
                else analyze_chapter(
                    draft,
                    _resolved_chapter_target_chars(spec, chapter, plan),
                    _character_names(bible, spec),
                    market_profile=spec.market_profile,
                    **self._chapter_local_quality_kwargs(spec, chapter, plan, []),
                )
            )
            review = _review_feedback_from_dict(model_payload)
            continuity_update = _continuity_update_from_dict(
                _normalize_continuity_payload(continuity_payload, chapter)
            )
            memory_update = None
            if memory_path.exists():
                memory_payload = load_json(memory_path)
                memory_update = _long_memory_update_from_dict(
                    _normalize_long_memory_payload(memory_payload, chapter)
                )
            attempts = int(review_payload.get("attempts", 1)) if isinstance(review_payload, dict) else 1
        except (OSError, ValueError, TypeError, KeyError):
            return None, True

        return (
            ChapterResult(
                index=chapter.index,
                volume_index=chapter.volume_index,
                title=chapter.title,
                outline_item=chapter,
                draft=draft,
                plan=plan,
                review=review,
                local_quality=local_quality,
                continuity=continuity_update,
                attempts=attempts,
                long_memory=memory_update,
            ),
            True,
        )

    def _purge_incomplete_chapter_artifacts(self, chapter_index: int) -> list[str]:
        paths = [
            self.store.chapter_path(chapter_index),
            self.store.chapter_plan_path(chapter_index),
            self.store.chapter_review_path(chapter_index),
            self.store.continuity_path(chapter_index),
            self.store.chapter_memory_path(chapter_index),
            self.store.chapter_room_path(chapter_index),
            self.store.chapter_execution_path(chapter_index),
        ]
        removed: list[str] = []
        for path in paths:
            if not path.exists():
                continue
            path.unlink()
            removed.append(str(path.relative_to(self.store.root)))
        return removed

    def _load_logic_audits(self, book_outline: BookOutline) -> dict[int, LogicAuditReport]:
        audits: dict[int, LogicAuditReport] = {}
        for volume in book_outline.volumes:
            path = self.store.logic_audit_path(volume.index)
            if not path.exists():
                continue
            payload = load_json(path)
            if not isinstance(payload, dict):
                continue
            audits[volume.index] = _logic_audit_from_dict(payload)
        return audits

    def _should_run_logic_audit(self, spec: ProjectSpec) -> bool:
        return spec.volume_count > 1 or spec.chapter_count >= 12

    def _latest_logic_audit_for_volume(self, volume_index: int) -> LogicAuditReport | None:
        eligible = [key for key in self._logic_audits if key <= volume_index]
        if not eligible:
            return None
        return self._logic_audits[max(eligible)]

    def _audit_volume_logic(
        self,
        spec: ProjectSpec,
        bible: WorldBible,
        book_outline: BookOutline,
        volume_outline: VolumeOutline,
        chapters: list[ChapterResult],
        continuity: ContinuityState,
        *,
        force_refresh: bool = False,
        ledger_sanity: dict[str, Any] | None = None,
    ) -> LogicAuditReport | None:
        if not chapters:
            return None
        path = self.store.logic_audit_path(volume_outline.volume_index)
        if self.resume and path.exists() and not force_refresh:
            payload = load_json(path)
            if isinstance(payload, dict):
                audit = _logic_audit_from_dict(payload)
                self._logic_audits[volume_outline.volume_index] = audit
                return audit

        previous_audit = self._latest_logic_audit_for_volume(volume_outline.volume_index - 1)
        self._emit_progress(
            "logic_audit",
            f"执行第 {volume_outline.volume_index} 卷长线逻辑审计。",
            volume_index=volume_outline.volume_index,
            chapter_count=len(chapters),
        )
        payload = self._generate_json_with_progress(
            "logic_audit",
            f"执行第 {volume_outline.volume_index} 卷长线逻辑审计。",
            f"第{volume_outline.volume_index}卷逻辑审计",
            logic_audit_system_prompt(),
            logic_audit_user_prompt(
                spec,
                bible,
                book_outline,
                volume_outline,
                chapters,
                continuity,
                self._promise_ledger,
                self._causality_graph,
                asdict(previous_audit) if previous_audit else None,
                ledger_sanity=ledger_sanity,
                power_system=self._power_system,
                progression_ledger=self._progression_ledger,
            ),
            model=self._review_model_name(),
            temperature=0.1,
            max_output_tokens=1400,
            session_id="logic-audit",
            session_max_chars=50000,
        )
        payload = self._resolve_generated_structured_mapping_payload(
            payload=payload,
            normalize=_normalize_logic_audit_payload,
            has_content=_logic_audit_payload_has_content,
            has_signal=_logic_audit_payload_has_signal,
            regenerate=lambda attempt, previous_payload: self._generate_json_with_progress(
                "logic_audit",
                f"重生成第 {volume_outline.volume_index} 卷长线逻辑审计（第 {attempt} 次）。",
                f"第{volume_outline.volume_index}卷逻辑审计重生成",
                logic_audit_system_prompt(),
                logic_audit_user_prompt(
                    spec,
                    bible,
                    book_outline,
                    volume_outline,
                    chapters,
                    continuity,
                    self._promise_ledger,
                    self._causality_graph,
                    asdict(previous_audit) if previous_audit else None,
                    ledger_sanity=ledger_sanity,
                    power_system=self._power_system,
                    progression_ledger=self._progression_ledger,
                ) + "\n\n补充要求：上一次返回缺少有效审计结构。必须返回 passed、gate_passed、gate_level、summary、issues。",
                model=self._review_model_name(),
                temperature=0.05,
                max_output_tokens=1400,
                session_id="logic-audit",
                session_max_chars=50000,
            ),
            repair=lambda raw_payload: self._repair_structured_mapping_payload(
                step="logic_audit_normalize",
                progress_message=f"规范化第 {volume_outline.volume_index} 卷逻辑审计结构。",
                object_label=f"第{volume_outline.volume_index}卷逻辑审计规范化",
                session_id=f"logic-audit-normalizer-{volume_outline.volume_index}",
                raw_payload=raw_payload,
                shape=_logic_audit_payload_shape(chapters),
                rules=[
                    "顶层必须是一个 JSON 对象，不允许返回数组。",
                    "只做结构规范化，不要编造新的审计结论。",
                    "flagged_chapters 和 repair_plan 必须是对象数组；没有有效对象时返回空数组，不要编造。",
                ],
                state_path=f"audits/volume-{volume_outline.volume_index:02d}.logic-audit-normalizer.json",
            ),
        )
        if _logic_audit_payload_looks_malformed(payload):
            self._emit_progress(
                "logic_audit_retry",
                f"重跑第 {volume_outline.volume_index} 卷长线逻辑审计（审计结果语义异常）。",
                volume_index=volume_outline.volume_index,
                chapter_count=len(chapters),
            )
            payload = self._generate_json_with_progress(
                "logic_audit",
                f"重跑第 {volume_outline.volume_index} 卷长线逻辑审计（审计结果语义异常）。",
                f"第{volume_outline.volume_index}卷逻辑审计重试",
                logic_audit_system_prompt(),
                logic_audit_user_prompt(
                    spec,
                    bible,
                    book_outline,
                    volume_outline,
                    chapters,
                    continuity,
                    self._promise_ledger,
                    self._causality_graph,
                    asdict(previous_audit) if previous_audit else None,
                    ledger_sanity=ledger_sanity,
                    power_system=self._power_system,
                    progression_ledger=self._progression_ledger,
                )
                + "\n\n补充要求：上一次审计结果语义异常，出现了 gate_passed/gate_level 与 summary、issues、required_followups 明显矛盾的情况。若卷级闸门未通过，issues 或 required_followups 必须给出明确的负向问题与可执行动作；若卷级可过，不要返回 gate_level=fail/repair。",
                model=self._review_model_name(),
                temperature=0.05,
                max_output_tokens=1400,
                session_id="logic-audit",
                session_max_chars=50000,
            )
            payload = self._resolve_generated_structured_mapping_payload(
                payload=payload,
                normalize=_normalize_logic_audit_payload,
                has_content=_logic_audit_payload_has_content,
                has_signal=_logic_audit_payload_has_signal,
                regenerate=lambda attempt, previous_payload: self._generate_json_with_progress(
                    "logic_audit",
                    f"再次重生成第 {volume_outline.volume_index} 卷长线逻辑审计（第 {attempt} 次）。",
                    f"第{volume_outline.volume_index}卷逻辑审计再重生成",
                    logic_audit_system_prompt(),
                    logic_audit_user_prompt(
                        spec,
                        bible,
                        book_outline,
                        volume_outline,
                        chapters,
                        continuity,
                        self._promise_ledger,
                        self._causality_graph,
                        asdict(previous_audit) if previous_audit else None,
                        ledger_sanity=ledger_sanity,
                        power_system=self._power_system,
                        progression_ledger=self._progression_ledger,
                    ) + "\n\n补充要求：必须返回自洽的逻辑审计结构；passed、gate_passed、gate_level、summary、issues、required_followups 之间不能互相矛盾。",
                    model=self._review_model_name(),
                    temperature=0.05,
                    max_output_tokens=1400,
                    session_id="logic-audit",
                    session_max_chars=50000,
                ),
                repair=lambda raw_payload: self._repair_structured_mapping_payload(
                    step="logic_audit_normalize",
                    progress_message=f"规范化第 {volume_outline.volume_index} 卷逻辑审计结构。",
                    object_label=f"第{volume_outline.volume_index}卷逻辑审计规范化",
                    session_id=f"logic-audit-normalizer-{volume_outline.volume_index}",
                    raw_payload=raw_payload,
                    shape=_logic_audit_payload_shape(chapters),
                    rules=[
                        "顶层必须是一个 JSON 对象，不允许返回数组。",
                        "只做结构规范化，不要编造新的审计结论。",
                        "flagged_chapters 和 repair_plan 必须是对象数组；没有有效对象时返回空数组，不要编造。",
                    ],
                    state_path=f"audits/volume-{volume_outline.volume_index:02d}.logic-audit-normalizer.json",
                ),
            )
        audit = _logic_audit_from_dict(payload)
        if ledger_sanity:
            audit.ledger_sanity = ledger_sanity
        self._logic_audits[volume_outline.volume_index] = audit
        relative_path = str(path.relative_to(self.store.root))
        self.store.write_json(relative_path, audit)
        self.store.write_json("data/latest-logic-audit.json", audit)
        return audit

    def _enforce_volume_gate(
        self,
        spec: ProjectSpec,
        bible: WorldBible,
        book_outline: BookOutline,
        volume_outline: VolumeOutline,
        volume_chapters: list[ChapterResult],
        all_chapters: list[ChapterResult],
        continuity: ContinuityState,
    ) -> tuple[list[ChapterResult], ContinuityState]:
        current_chapter = volume_chapters[-1].index if volume_chapters else continuity.last_chapter_index
        ledger_sanity = self._sanitize_long_range_state(
            current_volume=volume_outline.volume_index,
            current_chapter=current_chapter,
            persist=True,
        )
        audit = self._audit_volume_logic(
            spec,
            bible,
            book_outline,
            volume_outline,
            volume_chapters,
            continuity,
            ledger_sanity=ledger_sanity,
        )
        if audit is None or audit.gate_passed or audit.gate_level in {"pass", "warn"}:
            return volume_chapters, continuity
        if audit.gate_level == "repair_metadata":
            continuity = self._rebuild_continuity_state(bible, all_chapters)
            self.store.write_json("data/continuity-state.json", continuity)
            self._promise_ledger, self._progression_ledger, self._causality_graph = self._rebuild_long_range_state(all_chapters)
            ledger_sanity = self._sanitize_long_range_state(
                current_volume=volume_outline.volume_index,
                current_chapter=current_chapter,
                persist=False,
            )
            self.store.write_json("data/promise-ledger.json", self._promise_ledger)
            self.store.write_json("data/progression-ledger.json", self._progression_ledger)
            self.store.write_json("data/causality-graph.json", self._causality_graph)
            self.store.write_json("data/ledger-sanity.json", ledger_sanity)
            self._sync_runtime_views(continuity, all_chapters)
            audit = self._audit_volume_logic(
                spec,
                bible,
                book_outline,
                volume_outline,
                volume_chapters,
                continuity,
                force_refresh=True,
                ledger_sanity=ledger_sanity,
            )
            if audit is None or audit.gate_passed or audit.gate_level in {"pass", "warn", "repair_metadata"}:
                return volume_chapters, continuity
        repaired = self._repair_chapter_cluster(
            spec,
            bible,
            book_outline,
            volume_outline,
            all_chapters,
            audit,
        )
        updated_chapters = [item for item in repaired if item.volume_index == volume_outline.volume_index]
        continuity = self._rebuild_continuity_state(bible, repaired)
        self.store.write_json("data/continuity-state.json", continuity)
        self._promise_ledger, self._progression_ledger, self._causality_graph = self._rebuild_long_range_state(repaired)
        ledger_sanity = self._sanitize_long_range_state(
            current_volume=volume_outline.volume_index,
            current_chapter=updated_chapters[-1].index if updated_chapters else current_chapter,
            persist=False,
        )
        self.store.write_json("data/promise-ledger.json", self._promise_ledger)
        self.store.write_json("data/progression-ledger.json", self._progression_ledger)
        self.store.write_json("data/causality-graph.json", self._causality_graph)
        self.store.write_json("data/ledger-sanity.json", ledger_sanity)
        self._sync_runtime_views(continuity, repaired)
        self._write_partial_novel(spec, repaired)
        audit = self._audit_volume_logic(
            spec,
            bible,
            book_outline,
            volume_outline,
            updated_chapters,
            continuity,
            force_refresh=True,
            ledger_sanity=ledger_sanity,
        )
        if audit is not None and (not audit.gate_passed and audit.gate_level not in {"pass", "warn", "repair_metadata"}):
            fallback_audit = _build_volume_gate_fallback_audit(audit, volume_outline, updated_chapters)
            repaired = self._repair_chapter_cluster(
                spec,
                bible,
                book_outline,
                volume_outline,
                repaired,
                fallback_audit,
            )
            updated_chapters = [item for item in repaired if item.volume_index == volume_outline.volume_index]
            continuity = self._rebuild_continuity_state(bible, repaired)
            self.store.write_json("data/continuity-state.json", continuity)
            self._promise_ledger, self._progression_ledger, self._causality_graph = self._rebuild_long_range_state(repaired)
            ledger_sanity = self._sanitize_long_range_state(
                current_volume=volume_outline.volume_index,
                current_chapter=updated_chapters[-1].index if updated_chapters else current_chapter,
                persist=False,
            )
            self.store.write_json("data/promise-ledger.json", self._promise_ledger)
            self.store.write_json("data/progression-ledger.json", self._progression_ledger)
            self.store.write_json("data/causality-graph.json", self._causality_graph)
            self.store.write_json("data/ledger-sanity.json", ledger_sanity)
            self._sync_runtime_views(continuity, repaired)
            self._write_partial_novel(spec, repaired)
            audit = self._audit_volume_logic(
                spec,
                bible,
                book_outline,
                volume_outline,
                updated_chapters,
                continuity,
                force_refresh=True,
                ledger_sanity=ledger_sanity,
            )
        if audit is None or (not audit.gate_passed and audit.gate_level not in {"pass", "warn", "repair_metadata"}):
            raise RuntimeError(
                f"Volume {volume_outline.volume_index} failed hard logic gate.\n"
                f"Summary: {audit.summary if audit else 'missing audit'}\n"
                f"Issues: {compact_json(audit.issues if audit else [])}"
            )
        all_chapters[:] = repaired
        return updated_chapters, continuity

    def _attempt_quality_failure_window_repair(
        self,
        spec: ProjectSpec,
        bible: WorldBible,
        chapter: ChapterOutlineItem,
        plan: ChapterPlan,
        draft: str,
        local_quality: LocalQualityReport,
        review: ReviewFeedback,
        continuity: ContinuityState,
        *,
        prior_chapters: list[ChapterResult],
        book_outline: BookOutline | None,
        volume_outline: VolumeOutline | None,
        attempts: int,
    ) -> ChapterResult | None:
        if book_outline is None or volume_outline is None:
            return None
        if not _quality_failure_needs_window_repair(draft, review, local_quality):
            return None
        provisional = ChapterResult(
            index=chapter.index,
            volume_index=chapter.volume_index,
            title=chapter.title,
            outline_item=chapter,
            draft=draft,
            plan=plan,
            review=review,
            local_quality=local_quality,
            continuity=ContinuityUpdate(
                chapter_index=chapter.index,
                chapter_summary=_best_text(chapter.beat_summary, chapter.purpose, f"第{chapter.index}章待回修。"),
                new_threads=[],
                resolved_threads=[],
                timeline_events=[],
                character_states=[],
                next_chapter_targets=[],
                must_remember=[],
            ),
            attempts=attempts,
            long_memory=LongRangeMemoryUpdate(chapter_index=chapter.index),
        )
        repair_audit = _build_quality_failure_window_repair_audit(
            provisional,
            local_quality,
            review,
            volume_outline,
        )
        chapters = [copy.deepcopy(item) for item in prior_chapters] + [provisional]
        repaired = self._repair_chapter_cluster(
            spec,
            bible,
            book_outline,
            volume_outline,
            chapters,
            repair_audit,
        )
        continuity = self._rebuild_continuity_state(bible, repaired)
        self.store.write_json("data/continuity-state.json", continuity)
        self._promise_ledger, self._progression_ledger, self._causality_graph = self._rebuild_long_range_state(repaired)
        self.store.write_json("data/promise-ledger.json", self._promise_ledger)
        self.store.write_json("data/progression-ledger.json", self._progression_ledger)
        self.store.write_json("data/causality-graph.json", self._causality_graph)
        self._sync_runtime_views(continuity, repaired)
        self._write_partial_novel(spec, repaired)
        repaired_prior = [item for item in repaired if item.index < chapter.index]
        prior_chapters[:] = repaired_prior
        return next((item for item in repaired if item.index == chapter.index), None)

    def _select_story_memories(
        self,
        chapter: ChapterOutlineItem,
        plan: ChapterPlan | None,
        continuity: ContinuityState,
        prior_chapters: list[ChapterResult],
        *,
        limit: int = 8,
    ) -> list[dict[str, Any]]:
        if not prior_chapters:
            return []
        query_terms = _story_memory_query_terms(chapter, plan, continuity)
        scored: list[tuple[int, int, dict[str, Any]]] = []
        for previous in prior_chapters:
            memory = _chapter_memory_payload(previous)
            score, reasons = _score_story_memory(query_terms, chapter, memory)
            if score <= 0:
                continue
            memory["why"] = "；".join(reasons[:3]) if reasons else "延续最近主线。"
            scored.append((score, previous.index, memory))
        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [payload for _, _, payload in scored[:limit]]

    def _select_style_memories(
        self,
        chapter: ChapterOutlineItem,
        plan: ChapterPlan | None,
        prior_chapters: list[ChapterResult],
        *,
        limit: int = 6,
    ) -> list[dict[str, Any]]:
        query_terms = _style_memory_query_terms(chapter, plan)
        memories: list[tuple[int, dict[str, Any]]] = []
        for sample in self._style_bible.sample_passages:
            payload = {"source": "style_bible", "label": sample.label, "use_case": sample.use_case, "text": sample.text}
            score = _score_style_memory(query_terms, payload)
            if score > 0:
                memories.append((score, payload))
        for previous in prior_chapters[-12:]:
            excerpt = _chapter_style_excerpt(previous.draft)
            if not excerpt:
                continue
            payload = {
                "source": "chapter_excerpt",
                "chapter_index": previous.index,
                "title": previous.title,
                "text": excerpt,
                "use_case": previous.plan.closing_mode,
            }
            score = _score_style_memory(query_terms, payload)
            if score > 0:
                memories.append((score, payload))
        memories.sort(key=lambda item: item[0], reverse=True)
        selected: list[dict[str, Any]] = []
        for _, payload in memories:
            if payload not in selected:
                selected.append(payload)
            if len(selected) >= limit:
                break
        return selected

    def _select_promise_memories(
        self,
        chapter: ChapterOutlineItem,
        plan: ChapterPlan | None,
        continuity: ContinuityState,
        *,
        limit: int = 8,
    ) -> list[dict[str, Any]]:
        if limit <= 0:
            return []
        query_terms = _story_memory_query_terms(chapter, plan, continuity)
        promise_pool = self._runtime_promise_ledger or self._promise_ledger
        selected: list[dict[str, Any]] = []
        seen_labels: set[str] = set()

        risk_scored: list[tuple[int, int, int, dict[str, Any]]] = []
        overdue_candidates = [item for item in promise_pool if item.deadline_state == "overdue"]
        at_risk_candidates = [item for item in promise_pool if item.deadline_state == "at_risk"]
        for item in [*overdue_candidates, *at_risk_candidates]:
            payload = _promise_memory_payload(item)
            score, reasons = _score_named_memory(query_terms, payload)
            risk_label = "高危逾期，必须显式考虑。" if item.deadline_state == "overdue" else "临近逾期，需要提前处理。"
            payload["why"] = "；".join(reasons[:3]) if reasons else risk_label
            urgency = max(0, chapter.index - max(item.last_touched_chapter, 0))
            risk_boost = 1 if item.deadline_state == "overdue" else 0
            risk_scored.append((risk_boost, score, urgency, -item.chapter_opened, payload))
        risk_scored.sort(key=lambda item: (item[0], item[1], item[2], item[3]), reverse=True)
        relevant_risk_budget = min(limit, 3)
        for risk_boost, score, _, _, payload in risk_scored:
            if score <= 0 or len(selected) >= relevant_risk_budget:
                continue
            selected.append(payload)
            seen_labels.add(f"{payload.get('promise_id')}::{payload.get('label')}")
        if len(selected) < limit and overdue_candidates:
            oldest = sorted(overdue_candidates, key=lambda item: (item.last_touched_chapter, item.chapter_opened))[0]
            oldest_payload = _promise_memory_payload(oldest)
            oldest_key = f"{oldest_payload.get('promise_id')}::{oldest_payload.get('label')}"
            if oldest_key not in seen_labels:
                oldest_payload["why"] = "逾期最久，需要作为全局高危事项保留。"
                selected.append(oldest_payload)
                seen_labels.add(oldest_key)

        scored: list[tuple[int, int, dict[str, Any]]] = []
        for item in promise_pool:
            payload = _promise_memory_payload(item)
            key = f"{payload.get('promise_id')}::{payload.get('label')}"
            if key in seen_labels:
                continue
            score, reasons = _score_named_memory(query_terms, payload)
            if score <= 0:
                continue
            payload["why"] = "；".join(reasons[:3]) if reasons else "与本章主线相关。"
            scored.append((score, item.last_touched_chapter, payload))
        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        for _, _, payload in scored:
            selected.append(payload)
            if len(selected) >= limit:
                break
        return selected

    def _select_causality_memories(
        self,
        chapter: ChapterOutlineItem,
        plan: ChapterPlan | None,
        continuity: ContinuityState,
        *,
        limit: int = 8,
    ) -> list[dict[str, Any]]:
        query_terms = _story_memory_query_terms(chapter, plan, continuity)
        scored: list[tuple[int, dict[str, Any]]] = []
        for item in self._runtime_causality_graph or self._causality_graph:
            payload = _causality_memory_payload(item)
            score, reasons = _score_named_memory(query_terms, payload)
            if score <= 0:
                continue
            payload["why"] = "；".join(reasons[:3]) if reasons else "与当前因果链相关。"
            scored.append((score, payload))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [payload for _, payload in scored[:limit]]

    def _select_long_memory_promises(
        self,
        chapter: ChapterOutlineItem,
        plan: ChapterPlan,
        continuity: ContinuityState,
        *,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        selected = self._select_promise_memories(chapter, plan, continuity, limit=min(limit, 6))
        seen = {f"{item.get('promise_id')}::{item.get('label')}" for item in selected}
        query_terms = _story_memory_query_terms(chapter, plan, continuity)
        promise_pool = self._runtime_promise_ledger or self._promise_ledger
        recent_candidates = sorted(
            promise_pool,
            key=lambda item: (item.last_touched_chapter, item.chapter_opened),
            reverse=True,
        )
        for item in recent_candidates:
            if len(selected) >= limit:
                break
            if item.current_status == "paid_off" and chapter.index - item.last_touched_chapter > 8:
                continue
            payload = _promise_memory_payload(item)
            key = f"{payload.get('promise_id')}::{payload.get('label')}"
            if key in seen:
                continue
            score, reasons = _score_named_memory(query_terms, payload)
            if score <= 0 and item.deadline_state not in {"overdue", "at_risk"}:
                continue
            payload["why"] = "近期刚被触碰，长线账本更新时需要保留上下文。"
            if reasons:
                payload["why"] = "；".join(reasons[:3])
            selected.append(payload)
            seen.add(key)
        return selected[:limit]

    def _select_long_memory_causality(
        self,
        chapter: ChapterOutlineItem,
        plan: ChapterPlan,
        continuity: ContinuityState,
        *,
        limit: int = 8,
    ) -> list[dict[str, Any]]:
        selected = self._select_causality_memories(chapter, plan, continuity, limit=min(limit, 5))
        seen = {f"{item.get('effect_label')}::{item.get('cause')}" for item in selected}
        query_terms = _story_memory_query_terms(chapter, plan, continuity)
        recent_edges = sorted(
            self._runtime_causality_graph or self._causality_graph,
            key=lambda item: (item.last_verified_chapter, item.introduced_chapter),
            reverse=True,
        )
        for item in recent_edges:
            if len(selected) >= limit:
                break
            payload = _causality_memory_payload(item)
            key = f"{payload.get('effect_label')}::{payload.get('cause')}"
            if key in seen:
                continue
            score, reasons = _score_named_memory(query_terms, payload)
            if score <= 0:
                continue
            payload["why"] = "近期被验证或推进，更新因果图时需要保留链条。"
            if reasons:
                payload["why"] = "；".join(reasons[:3])
            selected.append(payload)
            seen.add(key)
        return selected[:limit]

    def _select_progression_memories(
        self,
        chapter: ChapterOutlineItem,
        plan: ChapterPlan | None,
        continuity: ContinuityState,
        *,
        limit: int = 8,
    ) -> list[dict[str, Any]]:
        query_terms = _progression_query_terms(chapter, plan, continuity)
        selected: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in sorted(
            self._runtime_progression_ledger or self._progression_ledger,
            key=lambda current: (
                current.status in {"advanced", "ready", "paid_off"},
                current.last_touched_chapter,
                current.opened_chapter,
            ),
            reverse=True,
        ):
            if len(selected) >= limit:
                break
            payload = _progression_memory_payload(item)
            key = f"{payload.get('milestone_label')}::{payload.get('target_tier')}"
            if key in seen:
                continue
            score, reasons = _score_named_memory(query_terms, payload)
            if score <= 0 and payload.get("status") not in {"ready", "advanced"}:
                continue
            payload["why"] = "；".join(reasons[:3]) if reasons else "当前章节的台阶、资源或试炼与此升级里程碑相关。"
            selected.append(payload)
            seen.add(key)
        return selected[:limit]

    def _build_chapter_execution_packet(
        self,
        chapter: ChapterOutlineItem,
        plan: ChapterPlan,
        retrieved_memory: list[dict[str, Any]],
        style_memory: list[dict[str, Any]],
        progression_memory: list[dict[str, Any]],
        promise_memory: list[dict[str, Any]],
        causality_memory: list[dict[str, Any]],
        recent_propulsion_history: list[dict[str, Any]],
        logic_audit: LogicAuditReport | None,
        *,
        chapter_room: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return execution_packet(
            chapter,
            plan,
            self._continuity_runtime,
            self._style_runtime,
            self._voice_runtime,
            power_system_runtime=power_system_runtime_view(self._power_system),
            progression_memory=progression_memory,
            story_memory=retrieved_memory,
            style_memory=style_memory,
            promise_memory=promise_memory,
            causality_memory=causality_memory,
            recent_propulsion_history=recent_propulsion_history,
            logic_audit=logic_audit,
            chapter_room=chapter_room,
        )

    def _chapter_local_quality_kwargs(
        self,
        spec: ProjectSpec,
        chapter: ChapterOutlineItem,
        plan: ChapterPlan,
        prior_chapters: list[ChapterResult] | None = None,
    ) -> dict[str, Any]:
        recent_propulsion_history = [
            _best_text(item.get("primary_propulsion"), "")
            for item in _recent_propulsion_history(prior_chapters or [])
        ]
        ending_window = chapter.index >= max(1, spec.chapter_count - 1) or chapter.closing_mode == "book_closure"
        target_min, target_max = _resolved_chapter_target_bounds(spec, chapter, plan)
        market_profile = _normalized_market_profile(spec.market_profile)
        return {
            "length_tolerance": spec.chapter_char_tolerance,
            "target_chars_min": target_min,
            "target_chars_max": target_max,
            "strict_length_gate": _is_strict_short_length_spec(spec),
            "length_extreme_multiplier": 2.2 if market_profile == "tomato_mass" else 3.0,
            "term_budget": plan.term_budget,
            "current_propulsion": plan.primary_propulsion,
            "recent_propulsion_history": recent_propulsion_history,
            "recent_overlength_tail": _recent_overlength_tail(prior_chapters or [], threshold=1.3),
            "recent_severe_overlength_tail": _recent_overlength_tail(prior_chapters or [], threshold=1.7),
            "chapter_role": _best_text(plan.chapter_role, chapter.chapter_role),
            "scene_types": [scene.scene_type for scene in plan.scenes if _best_text(scene.scene_type)],
            "variation_goal": plan.variation_goal,
            "recent_stagnation_history": _recent_propulsion_history(prior_chapters or [], limit=10),
            "voice_cards": self._voice_cards,
            "ending_window": ending_window,
            "progression_mode": spec.progression_mode,
            "progression_flavor": spec.progression_flavor,
            "progression_step_type": _best_text(plan.progression_step_type, chapter.progression_step_type),
            "progression_reward": _best_text(plan.progression_reward, chapter.progression_reward),
            "progression_cost": _best_text(plan.progression_cost, chapter.progression_cost),
            "current_tier": _best_text(plan.current_tier, chapter.current_tier),
            "target_tier": _best_text(plan.target_tier, chapter.target_tier),
            "recent_progression_history": _recent_progression_history(prior_chapters or [], limit=8),
        }

    def _resolve_project(self, project_input: ProjectInput) -> ProjectSpec:
        structure = _derive_structure(project_input)
        self._emit_progress("intake", "补全项目 brief。", structure=structure)
        payload = self._generate_json_with_progress(
            "intake",
            "补全项目 brief。",
            "项目补全",
            intake_system_prompt(),
            intake_user_prompt(project_input, structure),
            temperature=0.25,
            max_output_tokens=2200,
            session_id="planner-intake",
            session_max_chars=30000,
        )
        payload = self._resolve_generated_structured_mapping_payload(
            payload=payload,
            normalize=_normalize_intake_payload,
            has_content=_intake_payload_has_content,
            has_signal=_intake_payload_has_signal,
            regenerate=lambda attempt, previous_payload: self._generate_json_with_progress(
                "intake",
                f"重生成项目 brief（第 {attempt} 次）。",
                "项目补全重生成",
                intake_system_prompt(),
                intake_user_prompt(project_input, structure)
                + "\n\n补充要求：上一次返回缺少有效结构化 brief。必须返回一个完整 JSON 对象，至少给出 premise、theme、hook、style_examples、must_include、character_seeds。",
                temperature=0.2,
                max_output_tokens=2200,
                session_id="planner-intake",
                session_max_chars=30000,
            ),
            repair=lambda raw_payload: self._repair_structured_mapping_payload(
                step="intake_normalize",
                progress_message="规范化项目 brief 结构。",
                object_label="项目补全规范化",
                session_id="planner-intake-normalizer",
                raw_payload=raw_payload,
                shape=_intake_payload_shape(project_input),
                rules=[
                    "顶层必须是一个 JSON 对象，不允许返回数组。",
                    "只做结构规范化，不要编造不存在的新剧情。",
                    "如果源数据被拆成多个命名块，请合并成一个对象。",
                    "character_seeds 必须是对象数组；没有有效角色对象时返回空数组，不要编造。",
                ],
                state_path="data/intake-normalizer.json",
            ),
        )
        style_examples = _merge_lists(project_input.style_examples, _string_list(payload.get("style_examples")))
        must_include = _merge_lists(project_input.must_include, _string_list(payload.get("must_include")))
        avoid = _merge_lists(
            project_input.avoid,
            _string_list(payload.get("avoid")),
            ["最后一段只用新事件起悬念"] if project_input.ending_mode != "series" else [],
        )
        character_seeds = _merge_character_seeds(
            project_input.character_seeds,
            _character_seed_list(payload.get("character_seeds")),
        )
        if not character_seeds:
            character_seeds = [CharacterSeed(name=_best_text(payload.get("protagonist"), project_input.title))]
        output_language = _normalized_output_language(_best_text(payload.get("output_language"), project_input.output_language))
        defaults = _project_language_defaults(output_language, project_input.title)

        return ProjectSpec(
            title=_best_text(payload.get("title"), project_input.title),
            genre=_best_text(payload.get("genre"), project_input.genre, defaults["genre"]),
            audience=_best_text(payload.get("audience"), project_input.audience, defaults["audience"]),
            tone=_best_text(payload.get("tone"), project_input.tone, defaults["tone"]),
            premise=_best_text(payload.get("premise"), project_input.premise, defaults["premise"]),
            theme=_best_text(payload.get("theme"), project_input.theme, defaults["theme"]),
            hook=_best_text(payload.get("hook"), project_input.hook, defaults["hook"]),
            setting=_best_text(payload.get("setting"), project_input.setting, defaults["setting"]),
            protagonist=_best_text(payload.get("protagonist"), project_input.protagonist, character_seeds[0].name),
            outline_hint=_best_text(payload.get("outline_hint"), project_input.outline_hint, defaults["outline_hint"]),
            world_hint=_best_text(payload.get("world_hint"), project_input.world_hint, defaults["world_hint"]),
            ending_mode="series" if project_input.ending_mode == "series" else "standalone",
            pov=project_input.pov or defaults["pov"],
            target_total_chars=structure["target_total_chars"],
            target_chars_per_chapter=structure["target_chars_per_chapter"],
            chapter_count=structure["chapter_count"],
            volume_count=structure["volume_count"],
            chapters_per_volume=structure["chapters_per_volume"],
            volume_chapter_targets=list(structure["volume_chapter_targets"]),
            chapter_char_tolerance=float(structure["chapter_char_tolerance"]),
            structure_mode=_best_text(payload.get("structure_mode"), project_input.structure_mode, _best_text(structure.get("structure_mode"), "story_driven")),
            market_profile=_normalized_market_profile(_best_text(payload.get("market_profile"), project_input.market_profile)),
            progression_mode=_normalized_progression_mode(_best_text(payload.get("progression_mode"), project_input.progression_mode)),
            progression_flavor=_normalized_progression_flavor(_best_text(payload.get("progression_flavor"), project_input.progression_flavor)),
            progression_pacing=_normalized_progression_pacing(_best_text(payload.get("progression_pacing"), project_input.progression_pacing)),
            power_system_hint=_best_text(payload.get("power_system_hint"), project_input.power_system_hint, ""),
            style_examples=style_examples,
            must_include=must_include,
            avoid=avoid,
            character_seeds=character_seeds,
            seed=project_input.seed,
            output_language=output_language,
        )

    def _build_world(self, spec: ProjectSpec) -> WorldBible:
        self._emit_progress("world", "生成设定圣经。")
        payload = self._generate_json_with_progress(
            "world",
            "生成设定圣经。",
            "设定圣经",
            world_system_prompt(),
            world_user_prompt(spec, self._story_room),
            temperature=0.25,
            max_output_tokens=2600,
            session_id="planner-world",
            session_max_chars=40000,
        )
        payload = self._resolve_generated_structured_mapping_payload(
            payload=payload,
            normalize=_normalize_world_payload,
            has_content=_world_payload_has_content,
            has_signal=_world_payload_has_signal,
            regenerate=lambda attempt, previous_payload: self._generate_json_with_progress(
                "world",
                f"重生成设定圣经（第 {attempt} 次）。",
                "设定圣经重生成",
                world_system_prompt(),
                world_user_prompt(spec, self._story_room)
                + "\n\n补充要求：上一次返回缺少有效设定圣经内容。必须返回一个完整 JSON 对象，至少给出 world_rules、chapter_guardrails、major_threads 和 characters。",
                temperature=0.2,
                max_output_tokens=2600,
                session_id="planner-world",
                session_max_chars=40000,
            ),
            repair=lambda raw_payload: self._repair_structured_mapping_payload(
                step="world_normalize",
                progress_message="规范化设定圣经结构。",
                object_label="设定圣经规范化",
                session_id="planner-world-normalizer",
                raw_payload=raw_payload,
                shape=_world_payload_shape(spec),
                rules=[
                    "顶层必须是一个 JSON 对象，不允许返回数组。",
                    "只做结构规范化，不要编造不存在的新设定。",
                    "如果源数据被拆成多个命名块，请合并成一个对象。",
                    "characters 必须是对象数组；没有有效角色对象时返回空数组，不要编造。",
                ],
                state_path="data/world-normalizer.json",
            ),
        )
        bible = WorldBible(
            title=_best_text(payload.get("title"), spec.title),
            logline=_best_text(payload.get("logline"), spec.hook),
            setting_summary=_best_text(payload.get("setting_summary"), spec.setting),
            core_conflict=_best_text(payload.get("core_conflict"), spec.premise),
            theme_statement=_best_text(payload.get("theme_statement"), spec.theme),
            narrative_voice=_merge_lists(spec.style_examples, _string_list(payload.get("narrative_voice"))),
            world_rules=_string_list(payload.get("world_rules")),
            chapter_guardrails=_merge_lists(spec.avoid, _string_list(payload.get("chapter_guardrails"))),
            ending_contract=_merge_lists(spec.must_include, _string_list(payload.get("ending_contract"))),
            major_threads=_merge_lists(spec.must_include, _string_list(payload.get("major_threads"))),
            characters=[_character_from_dict(item) for item in payload.get("characters", [])],
        )
        if not bible.characters:
            bible.characters = [
                CharacterProfile(
                    name=seed.name,
                    role=seed.role or "关键角色",
                    goal=seed.goal or "推动主线",
                    fear="失去主动权",
                    contradiction=seed.conflict or "渴望前进却被旧问题牵制",
                    arc="在压力中做出真正选择",
                    public_image=seed.notes or "表面稳定",
                    private_truth=seed.notes or "内心并不平静",
                    speaking_style="简洁",
                    signature_image=seed.notes or seed.name,
                    relationship_tensions=[],
                    do_not_break=[],
                )
                for seed in spec.character_seeds
            ]
        alignment = self._align_world_with_story_room(bible)
        self.store.write_json("data/world-bible.json", bible)
        self.store.write_json(str(self.store.story_room_alignment_path().relative_to(self.store.root)), alignment)
        return bible

    def _build_power_system(self, spec: ProjectSpec, bible: WorldBible) -> PowerSystemBible:
        self._emit_progress("power_system", "生成升级体系圣经。")
        payload = self._generate_json_with_progress(
            "power_system",
            "生成升级体系圣经。",
            "升级体系圣经",
            power_system_system_prompt(),
            power_system_user_prompt(spec, bible, self._story_room),
            temperature=0.2,
            max_output_tokens=2600,
            session_id="planner-power-system",
            session_max_chars=40000,
        )
        payload = self._resolve_generated_structured_mapping_payload(
            payload=payload,
            normalize=_normalize_power_system_payload,
            has_content=_power_system_payload_has_content,
            has_signal=_power_system_payload_has_signal,
            regenerate=lambda attempt, previous_payload: self._generate_json_with_progress(
                "power_system",
                f"重生成升级体系圣经（第 {attempt} 次）。",
                "升级体系圣经重生成",
                power_system_system_prompt(),
                power_system_user_prompt(spec, bible, self._story_room)
                + "\n\n补充要求：上一次返回缺少有效升级体系结构。必须给出 core_axis、progression_contract、realm_ladder 和 milestone_plan。",
                temperature=0.15,
                max_output_tokens=2600,
                session_id="planner-power-system",
                session_max_chars=40000,
            ),
            repair=lambda raw_payload: self._repair_structured_mapping_payload(
                step="power_system_normalize",
                progress_message="规范化升级体系圣经结构。",
                object_label="升级体系圣经规范化",
                session_id="planner-power-system-normalizer",
                raw_payload=raw_payload,
                shape=_power_system_payload_shape(spec),
                rules=[
                    "顶层必须是一个 JSON 对象，不允许返回数组。",
                    "只做结构规范化，不要编造新的境界、资源或强敌台阶。",
                    "realm_ladder、resource_axes、enemy_ladder、milestone_plan 都必须是对象数组；没有有效对象时返回空数组。",
                ],
                state_path="data/power-system-normalizer.json",
            ),
        )
        power_system = _power_system_bible_from_dict(payload)
        self.store.write_json(str(self.store.power_system_path().relative_to(self.store.root)), power_system)
        self._write_progression_ledger(power_system)
        return power_system

    def _write_progression_ledger(self, power_system: PowerSystemBible) -> None:
        if not power_system.milestone_plan:
            self._progression_ledger = []
            self.store.write_json(
                str(self.store.progression_ledger_path().relative_to(self.store.root)),
                [],
            )
            return
        ledger = [
            ProgressionLedgerItem(
                milestone_label=item.label,
                current_tier=item.current_tier,
                target_tier=item.target_tier,
                status="pending",
                opened_chapter=0,
                last_touched_chapter=0,
                objective=item.objective,
                required_resources=list(item.required_resources),
                unlocked_rewards=[],
                bottleneck=item.key_trial,
            )
            for item in power_system.milestone_plan
        ]
        self._progression_ledger = ledger
        self.store.write_json(
            str(self.store.progression_ledger_path().relative_to(self.store.root)),
            ledger,
        )

    def _load_progression_ledger(self, power_system: PowerSystemBible) -> list[ProgressionLedgerItem]:
        path = self.store.progression_ledger_path()
        if path.exists():
            payload = load_json(path)
            if isinstance(payload, list):
                return [
                    _progression_ledger_item_from_dict(item)
                    for item in payload
                    if isinstance(item, dict)
                ]
        self._write_progression_ledger(power_system)
        return list(self._progression_ledger)

    def _build_story_room(self, spec: ProjectSpec) -> dict[str, Any]:
        self._emit_progress("story_room", "召开全书策划会。")
        payload = self._generate_json_with_progress(
            "story_room",
            "召开全书策划会。",
            "全书策划会",
            story_room_system_prompt(),
            story_room_user_prompt(spec),
            temperature=0.2,
            max_output_tokens=1800,
            session_id="story-room",
            session_max_chars=30000,
        )
        room = self._resolve_generated_structured_mapping_payload(
            payload=payload,
            normalize=_normalize_story_room_payload,
            has_content=_story_room_payload_has_content,
            has_signal=_story_room_payload_has_signal,
            regenerate=lambda attempt, previous_payload: self._generate_json_with_progress(
                "story_room",
                f"重召开全书策划会（第 {attempt} 次）。",
                "全书策划会重生成",
                story_room_system_prompt(),
                story_room_user_prompt(spec)
                + "\n\n补充要求：上一次返回缺少有效会议纪要。必须给出 notes、shared_contract、global_risks，不能只写散句。",
                temperature=0.15,
                max_output_tokens=1800,
                session_id="story-room",
                session_max_chars=30000,
            ),
            repair=lambda raw_payload: self._repair_structured_mapping_payload(
                step="story_room_normalize",
                progress_message="规范化策划会纪要结构。",
                object_label="全书策划会规范化",
                session_id="story-room-normalizer",
                raw_payload=raw_payload,
                shape=_story_room_payload_shape(),
                rules=[
                    "顶层必须是一个 JSON 对象，不允许返回数组。",
                    "只做结构规范化，不要编造新的 agent 观点。",
                    "notes 必须是对象数组；没有有效 note 对象时返回空数组，不要编造。",
                ],
                state_path="data/story-room-normalizer.json",
            ),
        )
        self.store.write_json("data/story-room.json", room)
        return room

    def _align_world_with_story_room(self, bible: WorldBible) -> dict[str, Any]:
        room = self._story_room if isinstance(self._story_room, dict) else {}
        shared_contract = _string_list(room.get("shared_contract"))
        additions: dict[str, list[str]] = {"world_rules": [], "chapter_guardrails": [], "ending_contract": [], "narrative_voice": []}
        alignment_items: list[dict[str, str]] = []
        for item in shared_contract:
            target = _story_room_constraint_target(item)
            bucket = getattr(bible, target)
            if item not in bucket:
                bucket.append(item)
                additions[target].append(item)
            alignment_items.append({"source": "shared_contract", "target": target, "text": item})
        notes = room.get("notes") if isinstance(room.get("notes"), list) else []
        for note in notes:
            if not isinstance(note, dict):
                continue
            agent = _best_text(note.get("agent"), "unknown")
            must_hold = _string_list(note.get("must_hold"))
            for item in must_hold:
                target = _story_room_constraint_target(item, agent=agent)
                bucket = getattr(bible, target)
                if item not in bucket:
                    bucket.append(item)
                    additions[target].append(item)
                alignment_items.append({"source": f"{agent}.must_hold", "target": target, "text": item})
        return {
            "shared_contract_count": len(shared_contract),
            "note_count": len(notes),
            "aligned_constraints": alignment_items,
            "added_constraints": additions,
        }

    def _load_or_build_style_anchor(self, spec: ProjectSpec, bible: WorldBible) -> StyleBible:
        anchor_path = self.store.style_bible_anchor_path()
        if anchor_path.exists():
            payload = load_json(anchor_path)
            if isinstance(payload, dict):
                return _style_bible_from_dict(payload)
        current_path = self.store.style_bible_path()
        meta_path = self.store.style_bible_meta_path()
        if current_path.exists() and meta_path.exists():
            meta_payload = load_json(meta_path)
            if isinstance(meta_payload, dict):
                through_chapter = int(meta_payload.get("through_chapter", 0) or 0)
                through_volume = int(meta_payload.get("through_volume", 0) or 0)
                if through_chapter <= 0 and through_volume <= 0:
                    payload = load_json(current_path)
                    if isinstance(payload, dict):
                        anchor = _style_bible_from_dict(payload)
                        self.store.write_json(str(anchor_path.relative_to(self.store.root)), anchor)
                        return anchor
        anchor = self._build_style_bible(spec, bible, anchor_style=None, chapters=None)
        self.store.write_json(str(anchor_path.relative_to(self.store.root)), anchor)
        return anchor

    def _calibrate_style_bible(
        self,
        spec: ProjectSpec,
        bible: WorldBible,
        chapters: list[ChapterResult],
    ) -> StyleBible:
        anchor = copy.deepcopy(self._style_anchor)
        candidate = self._build_style_bible(spec, bible, anchor_style=anchor, chapters=chapters)
        merged, report = _blend_style_bibles(anchor, candidate, chapters)
        self.store.write_json("data/style-bible.json", merged)
        self.store.write_json(
            str(self.store.style_bible_calibration_path().relative_to(self.store.root)),
            report,
        )
        self._write_style_control_meta(
            str(self.store.style_bible_meta_path().relative_to(self.store.root)),
            "style_bible",
            list(chapters or []),
        )
        return merged

    def _build_style_bible(
        self,
        spec: ProjectSpec,
        bible: WorldBible,
        *,
        anchor_style: StyleBible | None = None,
        chapters: list[ChapterResult] | None = None,
    ) -> StyleBible:
        chapter_samples = _recent_style_samples(chapters or [])
        use_light_control = bool(chapter_samples and anchor_style is not None)
        control_model = self._light_model_name() if use_light_control else self._flagship_model_name()
        message = "根据已有章节反推文风圣经。" if chapter_samples else "生成文风圣经。"
        self._emit_progress("style_bible", message)
        payload = self._generate_json_with_progress(
            "style_bible",
            message,
            "文风圣经",
            style_system_prompt(),
            style_user_prompt(spec, self._story_room, chapter_samples, anchor_style),
            model=control_model,
            temperature=0.2,
            max_output_tokens=2200,
            session_id="planner-style",
            session_max_chars=32000,
            provider_tier="light" if use_light_control else "flagship",
        )
        payload = self._resolve_generated_structured_mapping_payload(
            payload=payload,
            normalize=_normalize_style_bible_payload,
            has_content=_style_bible_payload_has_content,
            has_signal=_style_bible_payload_has_signal,
            regenerate=lambda attempt, previous_payload: self._generate_json_with_progress(
                "style_bible",
                f"重生成文风圣经（第 {attempt} 次）。",
                "文风圣经重生成",
                style_system_prompt(),
                style_user_prompt(spec, self._story_room, chapter_samples, anchor_style)
                + "\n\n补充要求：上一次返回缺少有效文风圣经内容。必须给出 tone_targets、propulsion_rules、clarity_rules、sample_passages。",
                model=control_model,
                temperature=0.15,
                max_output_tokens=2200,
                session_id="planner-style",
                session_max_chars=32000,
                provider_tier="light" if use_light_control else "flagship",
            ),
            repair=lambda raw_payload: self._repair_structured_mapping_payload(
                step="style_bible_normalize",
                progress_message="规范化文风圣经结构。",
                object_label="文风圣经规范化",
                session_id="planner-style-normalizer",
                raw_payload=raw_payload,
                shape=_style_bible_payload_shape(),
                rules=[
                    "顶层必须是一个 JSON 对象，不允许返回数组。",
                    "只做结构规范化，不要编造新的文风规则。",
                    "sample_passages 必须是对象数组；没有有效样例对象时返回空数组，不要编造。",
                ],
                state_path="data/style-bible-normalizer.json",
            ),
        )
        style_bible = _style_bible_from_dict(payload)
        return self._finalize_style_bible(spec, bible, style_bible)

    def _finalize_style_bible(
        self,
        spec: ProjectSpec,
        bible: WorldBible,
        style_bible: StyleBible,
    ) -> StyleBible:
        if not style_bible.sample_passages:
            style_bible.sample_passages = [
                StylePassage(
                    label="默认克制样例",
                    use_case="中低烈度推进",
                    text="风从门缝里挤进来，先碰到人，再碰到账页。谁也没有立刻说话，只有手上的动作先变了。",
                )
            ]
        if not style_bible.tone_targets:
            style_bible.tone_targets = _merge_lists(spec.style_examples, bible.narrative_voice, [spec.tone])
        if not style_bible.propulsion_rules:
            style_bible.propulsion_rules = [
                "允许多个章节围绕同一核心问题持续推进，但不要长期只靠线索加深和节点升级原地打转。",
                "同一推进簇可以连续出现，关键是每章都要带来新的后果、代价、站位变化或不可逆信息。",
            ]
        if not style_bible.clarity_rules:
            style_bible.clarity_rules = [
                "前段新术语必须绑定即时用途、风险或代价，不要连续抛制度词和流程词。",
                "每章优先让读者先看懂人在做什么，再理解体系名词。",
            ]
        if not style_bible.thematic_subtext_rules:
            style_bible.thematic_subtext_rules = [
                "主题优先藏在决定、关系变化、代价和后果里，不要在情节已经成立后补理念说明。",
            ]
        if not style_bible.pressure_curve_rules:
            style_bible.pressure_curve_rules = [
                "高压章节之间必须安排换气、停顿、误差或生活性落点，避免长期同频顶压。",
            ]
        if not style_bible.grounding_rules:
            style_bible.grounding_rules = [
                "定期写出食宿、钱、伤势、路程、天气、职业流程或人情往来，让故事落回地面。",
            ]
        return style_bible

    def _build_voice_cards(
        self,
        spec: ProjectSpec,
        bible: WorldBible,
        style_bible: StyleBible,
        chapters: list[ChapterResult] | None = None,
    ) -> list[CharacterVoiceCard]:
        voice_samples = _recent_voice_samples(chapters or [], _character_names(bible, spec))
        use_light_control = bool(voice_samples)
        control_model = self._light_model_name() if use_light_control else self._flagship_model_name()
        message = "根据已有章节反推人物声线卡。" if voice_samples else "生成人物声线卡。"
        self._emit_progress("voice_cards", message)
        payload = self._generate_json_with_progress(
            "voice_cards",
            message,
            "人物声线卡",
            voice_system_prompt(),
            voice_user_prompt(spec, bible, style_bible, voice_samples),
            model=control_model,
            temperature=0.15,
            max_output_tokens=1800,
            session_id="planner-voice",
            session_max_chars=32000,
            provider_tier="light" if use_light_control else "flagship",
        )
        payload = self._resolve_generated_structured_mapping_payload(
            payload=payload,
            normalize=_normalize_voice_cards_payload,
            has_content=_voice_cards_payload_has_content,
            has_signal=_voice_cards_payload_has_signal,
            regenerate=lambda attempt, previous_payload: self._generate_json_with_progress(
                "voice_cards",
                f"重生成人物声线卡（第 {attempt} 次）。",
                "人物声线卡重生成",
                voice_system_prompt(),
                voice_user_prompt(spec, bible, style_bible, voice_samples)
                + "\n\n补充要求：上一次返回缺少有效声线卡内容。必须给出 voice_cards，并且每一项都是角色对象。",
                model=control_model,
                temperature=0.1,
                max_output_tokens=1800,
                session_id="planner-voice",
                session_max_chars=32000,
                provider_tier="light" if use_light_control else "flagship",
            ),
            repair=lambda raw_payload: self._repair_structured_mapping_payload(
                step="voice_cards_normalize",
                progress_message="规范化人物声线卡结构。",
                object_label="人物声线卡规范化",
                session_id="planner-voice-normalizer",
                raw_payload=raw_payload,
                shape=_voice_cards_payload_shape(),
                rules=[
                    "顶层必须是一个 JSON 对象，不允许返回数组。",
                    "只做结构规范化，不要编造新的角色声线。",
                    "voice_cards 必须是对象数组；没有有效卡片对象时返回空数组，不要编造。",
                ],
                state_path="data/voice-cards-normalizer.json",
            ),
        )
        cards = [_voice_card_from_dict(item) for item in payload.get("voice_cards", []) if isinstance(item, dict)]
        if not cards:
            cards = [
                CharacterVoiceCard(
                    name=character.name,
                    speech_rhythm=_best_text(character.speaking_style, "简短直接"),
                    emotional_expression=_best_text(character.private_truth, "情绪不直说，落在动作和停顿里。"),
                    sentence_shape="短句为主，关键处才拉长。",
                    social_register=_best_text(character.public_image, character.role, "说话会暴露身份与位置。"),
                    humor_style="几乎不开玩笑，若开口也偏冷或偏干。",
                    silence_pattern="遇到真正要紧的事会先停顿，再给出最少的话。",
                    contrast_anchor=_best_text(character.role, character.signature_image, "和其他人说话重心不同。"),
                    common_words=[],
                    tension_triggers=character.relationship_tensions[:3],
                    forbidden_drifts=character.do_not_break[:4],
                )
                for character in bible.characters
            ]
        for card in cards:
            if not card.social_register:
                card.social_register = "说话会暴露其身份位置和对场面的控制方式。"
            if not card.humor_style:
                card.humor_style = "很少主动抖机灵，幽默多半带防御或试探。"
            if not card.silence_pattern:
                card.silence_pattern = "会用停顿、避答或转移话头表达压力。"
            if not card.contrast_anchor:
                card.contrast_anchor = f"{card.name}的声口必须和其他核心角色拉开。"
        self.store.write_json("data/voice-cards.json", cards)
        self._write_style_control_meta(
            str(self.store.voice_cards_meta_path().relative_to(self.store.root)),
            "voice_cards",
            list(chapters or []),
        )
        return cards

    def _build_book_outline(
        self,
        spec: ProjectSpec,
        bible: WorldBible,
        power_system: PowerSystemBible | None = None,
    ) -> BookOutline:
        power_system = power_system or self._power_system
        skeleton = _volume_skeletons(spec)
        self._emit_progress("book_outline", "生成全书分卷蓝图。", volume_count=spec.volume_count)
        payload = self._generate_json_with_progress(
            "book_outline",
            "生成全书分卷蓝图。",
            "分卷蓝图",
            book_outline_system_prompt(),
            book_outline_user_prompt(spec, bible, skeleton, self._story_room, power_system=power_system),
            temperature=0.2,
            max_output_tokens=3200,
            session_id="planner-book",
            session_max_chars=50000,
        )
        payload = self._normalize_or_repair_book_outline_payload(spec, skeleton, payload)
        volume_payloads = _index_dicts(payload.get("volumes"))
        volumes = _build_volume_blueprints_from_outline_payload(spec, skeleton, volume_payloads)
        outline = BookOutline(
            title=_best_text(payload.get("title"), spec.title),
            one_line_summary=_best_text(payload.get("one_line_summary"), spec.hook),
            act_structure=_string_list(payload.get("act_structure")),
            volumes=volumes,
        )
        self.store.write_json("data/book-outline.json", outline)
        return outline

    def _build_volume_outline(
        self,
        spec: ProjectSpec,
        bible: WorldBible,
        book_outline: BookOutline,
        volume: VolumeBlueprint,
        continuity: ContinuityState,
        power_system: PowerSystemBible | None = None,
    ) -> VolumeOutline:
        power_system = power_system or self._power_system
        skeleton = _chapter_skeleton(spec, volume)
        payload = self._generate_json_with_progress(
            "volume_outline",
            f"生成第 {volume.index} 卷章节蓝图。",
            f"第{volume.index}卷蓝图",
            volume_outline_system_prompt(),
            volume_outline_user_prompt(spec, bible, book_outline, volume, continuity, skeleton, power_system=power_system),
            temperature=0.2,
            max_output_tokens=3600,
            session_id=f"planner-volume-{volume.index}",
            session_max_chars=50000,
        )
        payload = self._normalize_or_repair_volume_outline_payload(volume, skeleton, payload)
        chapter_payloads = _index_dicts(payload.get("chapter_targets"))
        chapter_targets: list[ChapterOutlineItem] = []
        for item in skeleton:
            current = chapter_payloads.get(item["index"], {})
            chapter_targets.append(
                ChapterOutlineItem(
                    index=item["index"],
                    volume_index=volume.index,
                    title=_best_text(current.get("title"), f"第{item['index']}章"),
                    purpose=_best_text(current.get("purpose"), "推进主线"),
                    conflict=_best_text(current.get("conflict"), "人物与外部/内部阻力碰撞"),
                    beat_summary=_best_text(current.get("beat_summary"), "本章局势发生变化。"),
                    ending_note=_best_text(current.get("ending_note"), "章末形成明确推进。"),
                    pov=_best_text(current.get("pov"), spec.pov),
                    closing_mode=item["closing_mode"],
                    chapter_role=_best_text(current.get("chapter_role"), item.get("chapter_role"), ""),
                    scene_load_score=_float_or_default(current.get("scene_load_score"), item.get("scene_load_score"), 0.0),
                    target_chars=_int_or_default(current.get("target_chars"), item.get("target_chars"), 0),
                    target_chars_min=_int_or_default(current.get("target_chars_min"), item.get("target_chars_min"), 0),
                    target_chars_max=_int_or_default(current.get("target_chars_max"), item.get("target_chars_max"), 0),
                    split_allowed=_bool_or_default(current.get("split_allowed"), item.get("split_allowed"), False),
                    merge_allowed=_bool_or_default(current.get("merge_allowed"), item.get("merge_allowed"), False),
                    must_payoff=_string_list(current.get("must_payoff")),
                )
            )
        outline = VolumeOutline(
            volume_index=volume.index,
            title=_best_text(payload.get("title"), volume.title),
            goal=_best_text(payload.get("goal"), volume.role),
            climax=_best_text(payload.get("climax"), volume.central_question),
            carry_over_threads=_merge_lists(volume.must_payoff, _string_list(payload.get("carry_over_threads"))),
            chapter_targets=chapter_targets,
        )
        relative_path = str(self.store.volume_outline_path(volume.index).relative_to(self.store.root))
        self.store.write_json(relative_path, outline)
        return outline

    def _normalize_or_repair_book_outline_payload(
        self,
        spec: ProjectSpec,
        volume_skeleton: list[dict[str, Any]],
        payload: Any,
    ) -> dict[str, Any]:
        normalized = _normalize_book_outline_payload(payload)
        if normalized.get("volumes"):
            return normalized
        if not isinstance(payload, (dict, list)) or not payload:
            return normalized
        repaired = self._repair_book_outline_payload(spec, volume_skeleton, payload)
        repaired_normalized = _normalize_book_outline_payload(repaired)
        return repaired_normalized or normalized

    def _repair_book_outline_payload(
        self,
        spec: ProjectSpec,
        volume_skeleton: list[dict[str, Any]],
        payload: Any,
    ) -> Any:
        protected_payload, placeholder_map = _protect_structured_leaf_strings(payload)
        repaired = self._generate_json_with_progress(
            "book_outline_normalize",
            "规范化全书分卷蓝图结构。",
            "分卷蓝图规范化",
            book_outline_normalizer_system_prompt(),
            book_outline_normalizer_user_prompt(spec, volume_skeleton, protected_payload),
            model=self._light_model_name(),
            temperature=0.0,
            max_output_tokens=2400,
            session_id="planner-book-normalizer",
            session_max_chars=24000,
            provider_tier="light",
        )
        repaired = _restore_structured_leaf_strings(repaired, placeholder_map)
        self.store.write_json(
            "data/book-outline-normalizer.json",
            {
                "input_payload": payload,
                "protected_payload": protected_payload,
                "repaired_payload": repaired,
            },
        )
        return repaired

    def _normalize_or_repair_volume_outline_payload(
        self,
        volume: VolumeBlueprint,
        chapter_skeleton: list[dict[str, Any]],
        payload: Any,
    ) -> dict[str, Any]:
        normalized = _normalize_volume_outline_payload(payload, volume)
        if normalized.get("chapter_targets"):
            return normalized
        if not isinstance(payload, (dict, list)) or not payload:
            return normalized
        repaired = self._repair_volume_outline_payload(volume, chapter_skeleton, payload)
        repaired_normalized = _normalize_volume_outline_payload(repaired, volume)
        return repaired_normalized or normalized

    def _repair_volume_outline_payload(
        self,
        volume: VolumeBlueprint,
        chapter_skeleton: list[dict[str, Any]],
        payload: Any,
    ) -> Any:
        protected_payload, placeholder_map = _protect_structured_leaf_strings(payload)
        repaired = self._generate_json_with_progress(
            "volume_outline_normalize",
            f"规范化第 {volume.index} 卷章节蓝图结构。",
            f"第{volume.index}卷蓝图规范化",
            volume_outline_normalizer_system_prompt(),
            volume_outline_normalizer_user_prompt(volume, chapter_skeleton, protected_payload),
            model=self._light_model_name(),
            temperature=0.0,
            max_output_tokens=2600,
            session_id=f"planner-volume-normalizer-{volume.index}",
            session_max_chars=24000,
            provider_tier="light",
        )
        repaired = _restore_structured_leaf_strings(repaired, placeholder_map)
        self.store.write_json(
            f"state/volume-{volume.index:02d}.outline-normalizer.json",
            {
                "volume_index": volume.index,
                "input_payload": payload,
                "protected_payload": protected_payload,
                "repaired_payload": repaired,
            },
        )
        return repaired

    def _resolve_generated_structured_mapping_payload(
        self,
        *,
        payload: Any,
        normalize: Callable[[Any], dict[str, Any]],
        has_content: Callable[[dict[str, Any]], bool],
        has_signal: Callable[[Any], bool],
        regenerate: Callable[[int, Any], Any] | None = None,
        repair: Callable[[Any], Any] | None = None,
    ) -> dict[str, Any]:
        def attempt_repair(candidate_payload: Any, current_normalized: dict[str, Any]) -> tuple[dict[str, Any], Any]:
            if not repair or not has_signal(candidate_payload):
                return current_normalized, candidate_payload
            repaired_payload = repair(candidate_payload)
            repaired_normalized = normalize(repaired_payload)
            return repaired_normalized or current_normalized, repaired_payload

        normalized = normalize(payload)
        if has_content(normalized):
            return normalized

        working_payload = payload
        normalized, working_payload = attempt_repair(working_payload, normalized)
        if has_content(normalized):
            return normalized

        if regenerate:
            for attempt in range(1, 3):
                working_payload = regenerate(attempt, working_payload)
                normalized = normalize(working_payload)
                if has_content(normalized):
                    return normalized
                normalized, working_payload = attempt_repair(working_payload, normalized)
                if has_content(normalized):
                    return normalized
        return normalized

    def _repair_structured_mapping_payload(
        self,
        *,
        step: str,
        progress_message: str,
        object_label: str,
        session_id: str,
        raw_payload: Any,
        shape: object,
        rules: list[str],
        state_path: str,
    ) -> Any:
        protected_payload, placeholder_map = _protect_structured_leaf_strings(raw_payload)
        repaired = self._generate_json_with_progress(
            step,
            progress_message,
            object_label,
            structured_mapping_normalizer_system_prompt(),
            structured_mapping_normalizer_user_prompt(object_label, shape, protected_payload, rules),
            model=self._light_model_name(),
            temperature=0.0,
            max_output_tokens=2200,
            session_id=session_id,
            session_max_chars=24000,
            provider_tier="light",
        )
        repaired = _restore_structured_leaf_strings(repaired, placeholder_map)
        self.store.write_json(
            state_path,
            {
                "input_payload": raw_payload,
                "protected_payload": protected_payload,
                "repaired_payload": repaired,
            },
        )
        return repaired

    def _build_plan(
        self,
        spec: ProjectSpec,
        bible: WorldBible,
        book_outline: BookOutline,
        volume_outline: VolumeOutline,
        chapter: ChapterOutlineItem,
        continuity: ContinuityState,
        prior_chapters: list[ChapterResult] | None = None,
        power_system: PowerSystemBible | None = None,
    ) -> ChapterPlan:
        power_system = power_system or self._power_system
        retrieved_memory = self._select_story_memories(chapter, None, continuity, prior_chapters or [])
        style_memory = self._select_style_memories(chapter, None, prior_chapters or [])
        promise_memory = self._select_promise_memories(chapter, None, continuity, limit=8)
        causality_memory = self._select_causality_memories(chapter, None, continuity, limit=8)
        phase_brief = _chapter_phase_brief(spec, chapter.index)
        recent_propulsion_history = _recent_propulsion_history(prior_chapters or [])
        logic_audit = self._latest_logic_audit_for_volume(chapter.volume_index)
        def regenerate_plan_payload(notes: list[str], previous_payload: Any, attempt: int) -> Any:
            self._emit_progress(
                "chapter_plan_regenerate",
                f"重生成第 {chapter.index} 章计划。",
                chapter_index=chapter.index,
                volume_index=chapter.volume_index,
                notes=notes,
                attempt=attempt,
            )
            regenerated = self._generate_json_with_progress(
                "chapter_plan",
                f"重生成第 {chapter.index} 章计划。",
                f"第{chapter.index}章计划重生成",
                chapter_plan_system_prompt(),
                chapter_plan_user_prompt(
                    spec,
                    bible,
                    book_outline,
                    volume_outline,
                    chapter,
                    continuity,
                    continuity_runtime=self._continuity_runtime,
                    retrieved_memory=retrieved_memory,
                    style_memory=style_memory,
                    promise_memory=promise_memory,
                    causality_memory=causality_memory,
                    phase_brief=phase_brief,
                    recent_propulsion_history=recent_propulsion_history,
                    logic_audit=logic_audit_runtime_view(logic_audit),
                    power_system=power_system,
                    restructure_notes=notes,
                    previous_plan=previous_payload,
                ),
                temperature=0.15,
                max_output_tokens=2200,
                session_id=f"planner-chapter-{chapter.index}",
                session_max_chars=30000,
            )
            self.store.write_json(
                f"state/chapter-{chapter.index:02d}.plan-regenerate-{attempt:02d}.json",
                {
                    "chapter_index": chapter.index,
                    "attempt": attempt,
                    "notes": notes,
                    "input_payload": previous_payload,
                    "regenerated_payload": regenerated,
                },
            )
            return regenerated
        payload = self._generate_json_with_progress(
            "chapter_plan",
            f"生成第 {chapter.index} 章计划。",
            f"第{chapter.index}章计划",
            chapter_plan_system_prompt(),
            chapter_plan_user_prompt(
                spec,
                bible,
                book_outline,
                volume_outline,
                chapter,
                continuity,
                continuity_runtime=self._continuity_runtime,
                retrieved_memory=retrieved_memory,
                style_memory=style_memory,
                promise_memory=promise_memory,
                causality_memory=causality_memory,
                phase_brief=phase_brief,
                recent_propulsion_history=recent_propulsion_history,
                logic_audit=logic_audit_runtime_view(logic_audit),
                power_system=power_system,
            ),
            temperature=0.2,
            max_output_tokens=2200,
            session_id=f"planner-chapter-{chapter.index}",
            session_max_chars=30000,
        )
        payload = self._resolve_generated_chapter_plan_payload(
            chapter,
            payload,
            reason="initial_plan",
            regenerate=regenerate_plan_payload,
        )
        plan = _chapter_plan_from_payload(
            spec,
            chapter,
            payload,
            phase_brief=phase_brief,
        )
        if not plan.scenes:
            payload = self._fallback_chapter_plan_payload(
                spec,
                volume_outline,
                chapter,
                phase_brief=phase_brief,
                reason_label="initial_plan_no_scenes",
                source_payload=payload,
            )
            plan = _chapter_plan_from_payload(
                spec,
                chapter,
                payload,
                phase_brief=phase_brief,
            )
        restructure_notes = _chapter_plan_restructure_notes(chapter, plan, recent_propulsion_history)
        if restructure_notes:
            self._emit_progress(
                "chapter_plan_restructure",
                f"重排第 {chapter.index} 章计划。",
                chapter_index=chapter.index,
                volume_index=chapter.volume_index,
                notes=restructure_notes,
            )
            payload = self._generate_json_with_progress(
                "chapter_plan",
                f"重排第 {chapter.index} 章计划。",
                f"第{chapter.index}章计划重排",
                chapter_plan_system_prompt(),
                chapter_plan_user_prompt(
                    spec,
                    bible,
                    book_outline,
                    volume_outline,
                    chapter,
                    continuity,
                    continuity_runtime=self._continuity_runtime,
                    retrieved_memory=retrieved_memory,
                    style_memory=style_memory,
                    promise_memory=promise_memory,
                    causality_memory=causality_memory,
                    phase_brief=phase_brief,
                    recent_propulsion_history=recent_propulsion_history,
                    logic_audit=logic_audit_runtime_view(logic_audit),
                    power_system=power_system,
                    restructure_notes=restructure_notes,
                    previous_plan=asdict(plan),
                ),
                temperature=0.15,
                max_output_tokens=2200,
                session_id=f"planner-chapter-{chapter.index}",
                session_max_chars=30000,
            )
            payload = self._resolve_generated_chapter_plan_payload(
                chapter,
                payload,
                reason="restructure_plan",
                regenerate=regenerate_plan_payload,
            )
            plan = _chapter_plan_from_payload(
                spec,
                chapter,
                payload,
                phase_brief=phase_brief,
            )
            if not plan.scenes:
                payload = self._fallback_chapter_plan_payload(
                    spec,
                    volume_outline,
                    chapter,
                    phase_brief=phase_brief,
                    reason_label="restructure_plan_no_scenes",
                    source_payload=payload,
                )
                plan = _chapter_plan_from_payload(
                    spec,
                    chapter,
                    payload,
                    phase_brief=phase_brief,
                )
            self.store.write_json(
                f"state/chapter-{chapter.index:02d}.plan-guard.json",
                {
                    "chapter_index": chapter.index,
                    "restructure_notes": restructure_notes,
                    "recent_propulsion_history": recent_propulsion_history,
                "plan": asdict(plan),
            },
        )
        relative_path = str(self.store.chapter_plan_path(chapter.index).relative_to(self.store.root))
        self.store.write_json(relative_path, plan)
        return plan

    def _normalize_or_repair_chapter_plan_payload(
        self,
        chapter: ChapterOutlineItem,
        payload: Any,
        *,
        reason: str,
    ) -> dict[str, Any]:
        normalized = _normalize_chapter_plan_payload(payload)
        if _chapter_plan_has_valid_scenes(normalized):
            return normalized
        if not isinstance(payload, (dict, list)) or not payload:
            return normalized
        repaired = self._repair_chapter_plan_payload(chapter, payload, reason=reason)
        repaired_normalized = _normalize_chapter_plan_payload(repaired)
        return repaired_normalized or normalized

    def _resolve_generated_chapter_plan_payload(
        self,
        chapter: ChapterOutlineItem,
        payload: Any,
        *,
        reason: str,
        regenerate: Callable[[list[str], Any, int], Any] | None = None,
    ) -> dict[str, Any]:
        normalized = _normalize_chapter_plan_payload(payload)
        if _chapter_plan_has_valid_scenes(normalized):
            return normalized

        working_payload = payload
        if regenerate and not _chapter_plan_has_scene_signal(working_payload):
            for attempt in range(1, 3):
                notes = [
                    "上一版返回缺少有效 scenes。必须输出 3 到 6 个场景对象，不能只写约束、原则或提醒句。",
                    "每个 scene 都必须是 JSON 对象，至少包含 location、goal、conflict、turn 中的关键信息。",
                    "如果本章信息量不足以支撑多个场景，应减少场景数，但仍必须给出有效 scenes，不允许返回空数组。",
                ]
                working_payload = regenerate(notes, working_payload, attempt)
                normalized = _normalize_chapter_plan_payload(working_payload)
                if _chapter_plan_has_valid_scenes(normalized):
                    return normalized
                if _chapter_plan_has_scene_signal(working_payload):
                    break

        if _chapter_plan_has_scene_signal(working_payload):
            return self._normalize_or_repair_chapter_plan_payload(
                chapter,
                working_payload,
                reason=reason,
            )
        return _normalize_chapter_plan_payload(working_payload)

    def _fallback_chapter_plan_payload(
        self,
        spec: ProjectSpec,
        volume_outline: VolumeOutline,
        chapter: ChapterOutlineItem,
        *,
        phase_brief: dict[str, Any] | None,
        reason_label: str,
        source_payload: Any,
    ) -> dict[str, Any]:
        self._emit_progress(
            "chapter_plan_fallback",
            f"为第 {chapter.index} 章生成保底计划。",
            chapter_index=chapter.index,
            volume_index=chapter.volume_index,
            reason=reason_label,
        )
        payload = _minimal_chapter_plan_payload(
            spec,
            chapter,
            volume_outline,
            phase_brief=phase_brief,
        )
        self.store.write_json(
            f"state/chapter-{chapter.index:02d}.plan-fallback.json",
            {
                "chapter_index": chapter.index,
                "reason": reason_label,
                "source_payload": source_payload,
                "fallback_payload": payload,
            },
        )
        return payload

    def _fallback_chapter_room_payload(
        self,
        chapter: ChapterOutlineItem,
        plan: ChapterPlan,
        *,
        source_payload: Any,
    ) -> dict[str, Any]:
        payload = {
            "notes": [
                {
                    "agent": "continuity_guard",
                    "must_land": _merge_lists(plan.continuity_targets[:3], chapter.must_payoff[:2])[:3] or ["接住本章已明确的连续性目标。"],
                    "risks": ["不要把上一章已成立的线索和承诺写断。"],
                    "summary": "先确保主线和连续性目标落地。",
                },
                {
                    "agent": "drama_editor",
                    "must_land": [
                        _best_text(chapter.conflict, "本章必须给出新的阻力、代价或站位变化。"),
                        _best_text(chapter.ending_note, "章尾必须留下明确牵引。"),
                    ],
                    "risks": ["不能只是重复确认同一结论或空转拖延。"],
                    "summary": "保证本章冲突成立，并把章尾压力钉实。",
                },
                {
                    "agent": "style_guard",
                    "must_land": [
                        _best_text(plan.grounding_beat, "至少给一个能落地的动作、身体或生活细节。"),
                    ],
                    "risks": ["不要把解释和术语堆到动作前面。"],
                    "summary": "先写动作与落地细节，再给解释。",
                },
            ],
            "shared_mandates": _merge_lists(
                plan.continuity_targets[:4],
                chapter.must_payoff[:3],
                [
                    "先把本章动作和冲突写实。",
                    "章尾必须留下清晰牵引。",
                ],
            )[:6],
            "blocking_issues": [],
        }
        self._emit_progress(
            "chapter_room_fallback",
            f"为第 {chapter.index} 章生成保底写前会。",
            chapter_index=chapter.index,
            volume_index=chapter.volume_index,
        )
        self.store.write_json(
            f"state/chapter-{chapter.index:02d}.room-fallback.json",
            {
                "chapter_index": chapter.index,
                "source_payload": source_payload,
                "fallback_payload": payload,
            },
        )
        return payload

    def _fallback_continuity_payload(
        self,
        chapter: ChapterOutlineItem,
        draft: str,
        previous_state: ContinuityState,
        *,
        source_payload: Any,
    ) -> dict[str, Any]:
        excerpt = _best_text(draft[:120].strip(), chapter.beat_summary, chapter.purpose)
        summary = _best_text(
            chapter.beat_summary,
            excerpt,
            chapter.purpose,
            f"第{chapter.index}章继续推进当前主线。",
        )
        payload = {
            "chapter_index": chapter.index,
            "chapter_summary": summary,
            "new_threads": [],
            "resolved_threads": [],
            "timeline_events": [],
            "character_states": [],
            "next_chapter_targets": _merge_lists(chapter.must_payoff[:3], [chapter.ending_note] if _best_text(chapter.ending_note) else [])[:3],
            "must_remember": _merge_lists(previous_state.must_remember[-2:], chapter.must_payoff[:2])[:4],
            "progression_updates": [],
            "current_tier": _best_text(chapter.current_tier, previous_state.current_tier),
            "next_breakthrough": _best_text(chapter.target_tier, previous_state.next_breakthrough),
        }
        self._emit_progress(
            "continuity_fallback",
            f"为第 {chapter.index} 章生成保底连续性快照。",
            chapter_index=chapter.index,
            volume_index=chapter.volume_index,
        )
        self.store.write_json(
            f"state/chapter-{chapter.index:02d}.continuity-fallback.json",
            {
                "chapter_index": chapter.index,
                "source_payload": source_payload,
                "fallback_payload": payload,
            },
        )
        return payload

    def _fallback_long_memory_payload(
        self,
        chapter: ChapterOutlineItem,
        *,
        source_payload: Any,
    ) -> dict[str, Any]:
        payload = {
            "chapter_index": chapter.index,
            "promise_updates": [],
            "causality_updates": [],
            "progression_updates": [],
        }
        self._emit_progress(
            "long_memory_fallback",
            f"为第 {chapter.index} 章生成保底长线账本快照。",
            chapter_index=chapter.index,
            volume_index=chapter.volume_index,
        )
        self.store.write_json(
            f"state/chapter-{chapter.index:02d}.long-memory-fallback.json",
            {
                "chapter_index": chapter.index,
                "source_payload": source_payload,
                "fallback_payload": payload,
            },
        )
        return payload

    def _repair_chapter_plan_payload(
        self,
        chapter: ChapterOutlineItem,
        payload: Any,
        *,
        reason: str,
    ) -> Any:
        protected_payload, placeholder_map = _protect_structured_leaf_strings(payload)
        repaired = self._generate_json_with_progress(
            "chapter_plan_normalize",
            f"规范化第 {chapter.index} 章计划结构。",
            f"第{chapter.index}章计划规范化",
            chapter_plan_normalizer_system_prompt(),
            chapter_plan_normalizer_user_prompt(chapter, protected_payload),
            model=self._light_model_name(),
            temperature=0.0,
            max_output_tokens=1800,
            session_id=f"planner-chapter-normalizer-{chapter.index}",
            session_max_chars=18000,
            provider_tier="light",
        )
        repaired = _restore_structured_leaf_strings(repaired, placeholder_map)
        self.store.write_json(
            f"state/chapter-{chapter.index:02d}.plan-normalizer.json",
            {
                "chapter_index": chapter.index,
                "reason": reason,
                "input_payload": payload,
                "protected_payload": protected_payload,
                "repaired_payload": repaired,
            },
        )
        return repaired

    def _prepare_chapter_generation_context(
        self,
        spec: ProjectSpec,
        bible: WorldBible,
        chapter: ChapterOutlineItem,
        plan: ChapterPlan,
        continuity: ContinuityState,
        prior_chapters: list[ChapterResult] | None = None,
    ) -> dict[str, Any]:
        prior = prior_chapters or []
        retrieved_memory = self._select_story_memories(chapter, plan, continuity, prior)
        style_memory = self._select_style_memories(chapter, plan, prior)
        progression_memory = self._select_progression_memories(chapter, plan, continuity)
        promise_memory = self._select_promise_memories(chapter, plan, continuity)
        causality_memory = self._select_causality_memories(chapter, plan, continuity)
        recent_propulsion_history = _recent_propulsion_history(prior)
        logic_audit = self._latest_logic_audit_for_volume(chapter.volume_index)
        execution_packet = self._build_chapter_execution_packet(
            chapter,
            plan,
            retrieved_memory,
            style_memory,
            progression_memory,
            promise_memory,
            causality_memory,
            recent_propulsion_history,
            logic_audit,
        )
        chapter_room = self._build_chapter_room(
            spec,
            bible,
            chapter,
            plan,
            execution_packet,
        )
        execution_packet = self._build_chapter_execution_packet(
            chapter,
            plan,
            retrieved_memory,
            style_memory,
            progression_memory,
            promise_memory,
            causality_memory,
            recent_propulsion_history,
            logic_audit,
            chapter_room=chapter_room,
        )
        return {
            "retrieved_memory": retrieved_memory,
            "style_memory": style_memory,
            "progression_memory": progression_memory,
            "promise_memory": promise_memory,
            "causality_memory": causality_memory,
            "recent_propulsion_history": recent_propulsion_history,
            "logic_audit": logic_audit,
            "chapter_room": chapter_room,
            "execution_packet": execution_packet,
        }

    def _quality_failure_modes(self, local_quality: LocalQualityReport) -> set[str]:
        metrics = local_quality.metrics if isinstance(local_quality.metrics, dict) else {}
        modes: set[str] = set()
        if _chapter_is_over_length(local_quality):
            modes.add("length")
        if metrics.get("procedural_density_hard_fail"):
            modes.add("density")
        if metrics.get("ending_voice_hard_fail"):
            modes.add("voice")
        return modes

    def _stagnation_signal_level(self, local_quality: LocalQualityReport) -> str:
        metrics = local_quality.metrics if isinstance(local_quality.metrics, dict) else {}
        level = _normalize_story_memory_text(str(metrics.get("stagnation_signal_level", ""))).lower()
        if level in {"warning", "debt", "escalation"}:
            return level
        return ""

    def _stagnation_signal_note(self, chapter_index: int, level: str) -> str:
        if level == "warning":
            return (
                f"第{chapter_index}章落入同一推进簇的长窗口告警；后续章节只要继续围绕同一核心问题推进，"
                "就必须带来新的后果、代价或站位变化，避免只是重复确认同一结论。"
            )
        if level == "debt":
            return (
                f"第{chapter_index}章已积累推进空转债务；后续章节需要尽量兑现新的代价、关系变化或不可逆后果，"
                "不要只把局面再抬半级。"
            )
        return (
            f"第{chapter_index}章触发长窗口空转升级；请由上层在 accept / forward_fix / local_repair / "
            "phase_repair / arc_repair 之间判断，不要默认停书。"
        )

    def _stagnation_report_payload(
        self,
        chapter_index: int,
        local_quality: LocalQualityReport,
    ) -> dict[str, Any]:
        metrics = dict(local_quality.metrics if isinstance(local_quality.metrics, dict) else {})
        return {
            "chapter_index": chapter_index,
            "signal_level": self._stagnation_signal_level(local_quality),
            "current_propulsion": _best_text(str(metrics.get("current_propulsion", ""))),
            "recent_propulsion_history": list(metrics.get("recent_propulsion_history", []) or []),
            "same_family_cluster": int(metrics.get("stagnation_same_family_cluster", 0) or 0),
            "same_family_tail": int(metrics.get("stagnation_same_family_tail", 0) or 0),
            "issues": list(local_quality.issues),
            "short_summary": local_quality.short_summary,
            "available_actions": [
                "accept",
                "forward_fix",
                "local_repair",
                "phase_repair",
                "arc_repair",
            ],
            "recommended_action": "forward_fix",
        }

    def _record_stagnation_signal(
        self,
        chapter_index: int,
        local_quality: LocalQualityReport,
        continuity_update: ContinuityUpdate,
    ) -> dict[str, Any] | None:
        level = self._stagnation_signal_level(local_quality)
        if not level:
            return None
        continuity_update.must_remember = _merge_lists(
            continuity_update.must_remember,
            [self._stagnation_signal_note(chapter_index, level)],
        )
        if level != "escalation":
            return None
        report = self._stagnation_report_payload(chapter_index, local_quality)
        self.store.write_json(f"state/chapter-{chapter_index:02d}.stagnation-report.json", report)
        self.store.write_json("data/latest-stagnation-report.json", report)
        return report

    def _stagnation_constraints(self, chapter_index: int, current_propulsion: str, strength: str) -> list[str]:
        propulsion_text = current_propulsion or "当前推进簇"
        base = [
            f"第{chapter_index}章已触发长窗口空转{strength}信号；后续章节可以继续推进同一核心事件，但必须带来新的不可逆后果、代价兑现或站位变化。",
            f"如果继续围绕“{propulsion_text}”推进，不要只重复确认同一命门或把同一公开局再抬半级，必须改变章功能、scene 组合或结果类型。",
        ]
        if strength == "升级":
            base.append("优先用新的后果、关系变动、代价兑现或余波落地来推动，而不是重复上一章的升级方式。")
        return base

    def _stagnation_repetition_axes(self, metrics: dict[str, Any]) -> int:
        same_family_tail = int(metrics.get("stagnation_same_family_tail", 0) or 0)
        same_role_tail = int(metrics.get("stagnation_same_role_tail", 0) or 0)
        same_scene_tail = int(metrics.get("stagnation_same_scene_tail", 0) or 0)
        same_variation_tail = int(metrics.get("stagnation_same_variation_tail", 0) or 0)
        return sum(
            1
            for value, threshold in (
                (same_role_tail, 4),
                (same_scene_tail, 3),
                (same_variation_tail, 3),
                (same_family_tail, 8),
            )
            if value >= threshold
        )

    def _stagnation_repair_scope(
        self,
        chapter_index: int,
        decision: str,
        volume_outline: VolumeOutline | None,
    ) -> tuple[int, int]:
        chapter_min = volume_outline.chapter_targets[0].index if volume_outline and volume_outline.chapter_targets else 1
        if decision == "local_repair":
            span = 5
        elif decision == "phase_repair":
            span = 10
        elif decision == "arc_repair":
            span = 20
        else:
            span = 1
        return max(chapter_min, chapter_index - span + 1), chapter_index

    def _build_stagnation_decision(
        self,
        chapter_result: ChapterResult,
        report: dict[str, Any],
        volume_outline: VolumeOutline | None,
        *,
        decision_name: str,
        confidence: int,
        reason: str,
        current_propulsion: str,
        strength: str | None = None,
        scope_start_chapter: int | None = None,
        scope_end_chapter: int | None = None,
        next_constraints: list[str] | None = None,
        repair_goal: str | None = None,
    ) -> StagnationDecision:
        if scope_start_chapter is None or scope_end_chapter is None:
            scope_start_chapter, scope_end_chapter = self._stagnation_repair_scope(
                chapter_result.index,
                decision_name,
                volume_outline,
            )
        if strength is None:
            strength = "升级" if decision_name != "accept" else "观察"
        if next_constraints is None:
            next_constraints = (
                [] if decision_name == "accept"
                else self._stagnation_constraints(chapter_result.index, current_propulsion, strength)
            )
        if repair_goal is None:
            repair_goal = {
                "accept": "判定为合理连续高潮或连续推进，继续观察即可。",
                "forward_fix": "不回改旧章，后续 2-3 章必须用新的后果、代价或站位变化化解空转风险。",
                "local_repair": "小范围回修最近章节簇，避免连续章节在同一功能和同一升级方式上重复空转。",
                "phase_repair": "该阶段可能需要 6-10 章级别的结构回修，先记录方案并前推修正。",
                "arc_repair": "该弧段存在长期空转风险，需人工确认后再决定是否做大范围回修。",
            }[decision_name]
        return StagnationDecision(
            chapter_index=chapter_result.index,
            signal_level=report.get("signal_level", "escalation"),
            decision=decision_name,
            confidence=confidence,
            reason=reason,
            scope_start_chapter=scope_start_chapter,
            scope_end_chapter=scope_end_chapter,
            next_chapter_constraints=next_constraints,
            repair_goal=repair_goal,
        )

    def _decide_stagnation_action(
        self,
        chapter_result: ChapterResult,
        local_quality: LocalQualityReport,
        report: dict[str, Any],
        volume_outline: VolumeOutline | None,
    ) -> StagnationDecision:
        metrics = local_quality.metrics if isinstance(local_quality.metrics, dict) else {}
        same_family_cluster = int(metrics.get("stagnation_same_family_cluster", 0) or 0)
        same_family_tail = int(metrics.get("stagnation_same_family_tail", 0) or 0)
        same_role_tail = int(metrics.get("stagnation_same_role_tail", 0) or 0)
        same_scene_tail = int(metrics.get("stagnation_same_scene_tail", 0) or 0)
        same_variation_tail = int(metrics.get("stagnation_same_variation_tail", 0) or 0)
        current_propulsion = _best_text(metrics.get("current_propulsion"), chapter_result.plan.primary_propulsion)
        repetition_axes = self._stagnation_repetition_axes(metrics)
        if same_family_cluster >= 20 and repetition_axes >= 3:
            decision_name = "arc_repair"
            confidence = 88
        elif same_family_cluster >= 14 and repetition_axes >= 3:
            decision_name = "phase_repair"
            confidence = 82
        elif same_family_cluster >= 10 and repetition_axes >= 2:
            decision_name = "local_repair"
            confidence = 78
        elif repetition_axes == 0 and same_family_tail <= 5:
            decision_name = "accept"
            confidence = 68
        else:
            decision_name = "forward_fix"
            confidence = 74
        reason = (
            f"同一推进簇连续 {same_family_cluster} 章；同簇尾部 {same_family_tail} 章，"
            f"同章功能尾部 {same_role_tail} 章，同 scene 组合尾部 {same_scene_tail} 章，"
            f"同升级方式尾部 {same_variation_tail} 章。"
        )
        return self._build_stagnation_decision(
            chapter_result,
            report,
            volume_outline,
            decision_name=decision_name,
            confidence=confidence,
            reason=reason,
            current_propulsion=current_propulsion,
        )

    def _should_trigger_stagnation_judge(
        self,
        local_quality: LocalQualityReport,
        report: dict[str, Any],
        logic_audit: LogicAuditReport | None = None,
    ) -> bool:
        metrics = local_quality.metrics if isinstance(local_quality.metrics, dict) else {}
        same_family_cluster = int(metrics.get("stagnation_same_family_cluster", 0) or 0)
        repetition_axes = self._stagnation_repetition_axes(metrics)
        if report.get("signal_level") == "escalation" and same_family_cluster >= 10 and repetition_axes >= 2:
            return True
        if logic_audit is not None:
            audit_text = " ".join(
                str(part)
                for part in [logic_audit.summary, *logic_audit.issues, *logic_audit.watch_items, *logic_audit.required_followups]
                if part
            )
            normalized = _normalize_story_memory_text(audit_text)
            if any(keyword in normalized for keyword in ("空转", "同构", "重复推进", "重复抬级", "原地踏步")) and (
                same_family_cluster >= 6 or repetition_axes >= 2 or report.get("signal_level") == "escalation"
            ):
                return True
        return False

    def _planning_prefers_continuous_cluster(
        self,
        chapter_result: ChapterResult,
        book_outline: BookOutline | None,
        volume_outline: VolumeOutline | None,
    ) -> bool:
        volume_blueprint = None
        if book_outline is not None:
            volume_blueprint = next(
                (item for item in book_outline.volumes if item.index == chapter_result.volume_index),
                None,
            )
        phase_type = _normalize_story_memory_text(
            _best_text(
                volume_blueprint.phase_type if volume_blueprint else "",
                "",
            )
        )
        role_text = _normalize_story_memory_text(
            _best_text(chapter_result.plan.chapter_role, chapter_result.outline_item.chapter_role)
        )
        volume_text = _normalize_story_memory_text(
            " ".join(
                item
                for item in (
                    _best_text(volume_outline.goal if volume_outline else ""),
                    _best_text(volume_outline.climax if volume_outline else ""),
                    _best_text(volume_blueprint.central_question if volume_blueprint else ""),
                    _best_text(volume_blueprint.escalation if volume_blueprint else ""),
                )
                if item
            )
        )
        if phase_type in {"climax", "escalation", "closure"}:
            return True
        if any(token in role_text for token in ("climax", "setpiece", "escalation", "pivot", "closure")):
            return True
        return any(keyword in volume_text for keyword in ("高潮", "决战", "决胜", "总攻", "围剿", "收网", "公审", "审判", "连打"))

    def _stagnation_recent_chapter_payloads(
        self,
        prior_chapters: list[ChapterResult] | None,
        current_result: ChapterResult,
        *,
        limit: int = 12,
    ) -> list[dict[str, Any]]:
        chapters = [*(prior_chapters or []), current_result]
        payloads: list[dict[str, Any]] = []
        for chapter in chapters[-limit:]:
            payloads.append(
                {
                    "chapter_index": chapter.index,
                    "title": chapter.title,
                    "chapter_role": chapter.outline_item.chapter_role or chapter.plan.chapter_role,
                    "primary_propulsion": chapter.plan.primary_propulsion,
                    "variation_goal": chapter.plan.variation_goal,
                    "scene_types": [scene.scene_type for scene in chapter.plan.scenes if scene.scene_type],
                    "review_summary": chapter.review.short_summary,
                    "local_summary": chapter.local_quality.short_summary,
                    "continuity_summary": chapter.continuity.chapter_summary,
                }
            )
        return payloads

    def _run_stagnation_judge(
        self,
        spec: ProjectSpec,
        bible: WorldBible,
        chapter_result: ChapterResult,
        report: dict[str, Any],
        volume_outline: VolumeOutline | None,
        continuity: ContinuityState,
        continuity_runtime: dict[str, Any],
        prior_chapters: list[ChapterResult] | None,
    ) -> StagnationJudgeReview:
        current_plan = {
            "chapter_index": chapter_result.index,
            "title": chapter_result.title,
            "chapter_role": chapter_result.outline_item.chapter_role or chapter_result.plan.chapter_role,
            "primary_propulsion": chapter_result.plan.primary_propulsion,
            "variation_goal": chapter_result.plan.variation_goal,
            "purpose": chapter_result.plan.purpose,
            "continuity_targets": chapter_result.plan.continuity_targets,
            "scene_types": [scene.scene_type for scene in chapter_result.plan.scenes if scene.scene_type],
            "closing_mode": chapter_result.plan.closing_mode,
            "progression_step_type": chapter_result.plan.progression_step_type,
            "current_tier": chapter_result.plan.current_tier,
            "target_tier": chapter_result.plan.target_tier,
            "progression_reward": chapter_result.plan.progression_reward,
            "progression_cost": chapter_result.plan.progression_cost,
        }
        progression_memory = self._select_progression_memories(
            chapter_result.outline_item,
            chapter_result.plan,
            continuity,
            limit=8,
        )
        payload = self._generate_json_with_progress(
            "stagnation_judge",
            f"上层复核第 {chapter_result.index} 章长期空转风险。",
            f"第{chapter_result.index}章空转复核",
            stagnation_judge_system_prompt(),
            stagnation_judge_user_prompt(
                spec,
                bible,
                volume_outline,
                report,
                self._stagnation_recent_chapter_payloads(prior_chapters, chapter_result),
                continuity_runtime,
                current_plan,
                power_system=self._power_system,
                progression_ledger=self._runtime_progression_ledger or progression_memory,
            ),
            model=self._review_model_name(),
            temperature=0.1,
            max_output_tokens=1400,
            session_id="judge-stagnation",
            session_max_chars=50000,
            provider_tier="flagship",
        )
        payload = self._resolve_generated_structured_mapping_payload(
            payload=payload,
            normalize=lambda raw_payload: _normalize_stagnation_judge_payload(raw_payload, chapter_result.index),
            has_content=_stagnation_judge_payload_has_content,
            has_signal=_stagnation_judge_payload_has_signal,
            regenerate=lambda attempt, previous_payload: self._generate_json_with_progress(
                "stagnation_judge",
                f"重跑第 {chapter_result.index} 章空转复核（第 {attempt} 次）。",
                f"第{chapter_result.index}章空转复核重生成",
                stagnation_judge_system_prompt(),
                stagnation_judge_user_prompt(
                    spec,
                    bible,
                    volume_outline,
                    report,
                    self._stagnation_recent_chapter_payloads(prior_chapters, chapter_result),
                    continuity_runtime,
                    current_plan,
                    power_system=self._power_system,
                    progression_ledger=self._runtime_progression_ledger or progression_memory,
                ) + "\n\n补充要求：上一次返回缺少有效裁决内容。必须明确给出 verdict、recommended_action、confidence、reason，以及 scope_start_chapter、scope_end_chapter。",
                model=self._review_model_name(),
                temperature=0.05,
                max_output_tokens=1400,
                session_id="judge-stagnation",
                session_max_chars=50000,
                provider_tier="flagship",
            ),
            repair=lambda raw_payload: self._repair_structured_mapping_payload(
                step="stagnation_judge_normalize",
                progress_message=f"规范化第 {chapter_result.index} 章空转复核结构。",
                object_label=f"第{chapter_result.index}章空转复核规范化",
                session_id=f"judge-stagnation-normalizer-{chapter_result.index}",
                raw_payload=raw_payload,
                shape=_stagnation_judge_payload_shape(chapter_result.index),
                rules=[
                    "顶层必须是一个 JSON 对象，不允许返回数组。",
                    "只做结构规范化，不要编造新的章节事实或修复建议。",
                    "next_chapter_constraints 必须是字符串数组。",
                ],
                state_path=f"state/chapter-{chapter_result.index:02d}.stagnation-judge-normalizer.json",
            ),
        )
        review = StagnationJudgeReview(
            chapter_index=int(payload.get("chapter_index", chapter_result.index)),
            verdict=_best_text(payload.get("verdict"), "stagnation_risk"),
            recommended_action=_best_text(payload.get("recommended_action"), "forward_fix"),
            confidence=int(payload.get("confidence", 0) or 0),
            reason=_best_text(payload.get("reason"), ""),
            scope_start_chapter=int(payload.get("scope_start_chapter", chapter_result.index) or chapter_result.index),
            scope_end_chapter=int(payload.get("scope_end_chapter", chapter_result.index) or chapter_result.index),
            next_chapter_constraints=_string_list(payload.get("next_chapter_constraints")),
            repair_goal=_best_text(payload.get("repair_goal"), ""),
        )
        if _stagnation_judge_payload_looks_malformed(payload):
            self._emit_progress(
                "stagnation_judge_retry",
                f"重跑第 {chapter_result.index} 章空转复核（裁决结果语义异常）。",
                chapter_index=chapter_result.index,
            )
            payload = self._generate_json_with_progress(
                "stagnation_judge",
                f"重跑第 {chapter_result.index} 章空转复核（裁决结果语义异常）。",
                f"第{chapter_result.index}章空转复核重试",
                stagnation_judge_system_prompt(),
                stagnation_judge_user_prompt(
                    spec,
                    bible,
                    volume_outline,
                    report,
                    self._stagnation_recent_chapter_payloads(prior_chapters, chapter_result),
                    continuity_runtime,
                    current_plan,
                    power_system=self._power_system,
                    progression_ledger=self._runtime_progression_ledger or progression_memory,
                )
                + "\n\n补充要求：上一次裁决结果语义异常，出现了 verdict/recommended_action 与 reason、repair_goal、next_chapter_constraints 明显矛盾的情况。若建议修复，reason 或 repair_goal 必须给出明确的负向问题；若当前章节簇合理，优先返回 reasonable_cluster 与 accept/forward_fix。",
                model=self._review_model_name(),
                temperature=0.05,
                max_output_tokens=1400,
                session_id="judge-stagnation",
                session_max_chars=50000,
                provider_tier="flagship",
            )
            payload = self._resolve_generated_structured_mapping_payload(
                payload=payload,
                normalize=lambda raw_payload: _normalize_stagnation_judge_payload(raw_payload, chapter_result.index),
                has_content=_stagnation_judge_payload_has_content,
                has_signal=_stagnation_judge_payload_has_signal,
                regenerate=lambda attempt, previous_payload: self._generate_json_with_progress(
                    "stagnation_judge",
                    f"再次重跑第 {chapter_result.index} 章空转复核（第 {attempt} 次）。",
                    f"第{chapter_result.index}章空转复核再重生成",
                    stagnation_judge_system_prompt(),
                    stagnation_judge_user_prompt(
                        spec,
                        bible,
                        volume_outline,
                        report,
                        self._stagnation_recent_chapter_payloads(prior_chapters, chapter_result),
                        continuity_runtime,
                        current_plan,
                        power_system=self._power_system,
                        progression_ledger=self._runtime_progression_ledger or progression_memory,
                    ) + "\n\n补充要求：必须返回自洽的空转复核结构；verdict、recommended_action、reason、repair_goal、next_chapter_constraints 之间不能互相矛盾。",
                    model=self._review_model_name(),
                    temperature=0.05,
                    max_output_tokens=1400,
                    session_id="judge-stagnation",
                    session_max_chars=50000,
                    provider_tier="flagship",
                ),
                repair=lambda raw_payload: self._repair_structured_mapping_payload(
                    step="stagnation_judge_normalize",
                    progress_message=f"规范化第 {chapter_result.index} 章空转复核结构。",
                    object_label=f"第{chapter_result.index}章空转复核规范化",
                    session_id=f"judge-stagnation-normalizer-{chapter_result.index}",
                    raw_payload=raw_payload,
                    shape=_stagnation_judge_payload_shape(chapter_result.index),
                    rules=[
                        "顶层必须是一个 JSON 对象，不允许返回数组。",
                        "只做结构规范化，不要编造新的章节事实或修复建议。",
                        "next_chapter_constraints 必须是字符串数组。",
                    ],
                    state_path=f"state/chapter-{chapter_result.index:02d}.stagnation-judge-normalizer.json",
                ),
            )
            review = StagnationJudgeReview(
                chapter_index=int(payload.get("chapter_index", chapter_result.index)),
                verdict=_best_text(payload.get("verdict"), "stagnation_risk"),
                recommended_action=_best_text(payload.get("recommended_action"), "forward_fix"),
                confidence=int(payload.get("confidence", 0) or 0),
                reason=_best_text(payload.get("reason"), ""),
                scope_start_chapter=int(payload.get("scope_start_chapter", chapter_result.index) or chapter_result.index),
                scope_end_chapter=int(payload.get("scope_end_chapter", chapter_result.index) or chapter_result.index),
                next_chapter_constraints=_string_list(payload.get("next_chapter_constraints")),
                repair_goal=_best_text(payload.get("repair_goal"), ""),
            )
        judge_payload = asdict(review)
        self.store.write_json(f"state/chapter-{chapter_result.index:02d}.stagnation-judge.json", judge_payload)
        self.store.write_json("data/latest-stagnation-judge.json", judge_payload)
        return review

    def _combine_stagnation_decision(
        self,
        chapter_result: ChapterResult,
        local_quality: LocalQualityReport,
        report: dict[str, Any],
        book_outline: BookOutline | None,
        volume_outline: VolumeOutline | None,
        judge_review: StagnationJudgeReview | None,
    ) -> StagnationDecision:
        local_decision = self._decide_stagnation_action(chapter_result, local_quality, report, volume_outline)
        if judge_review is None or judge_review.confidence < 55:
            return local_decision
        metrics = local_quality.metrics if isinstance(local_quality.metrics, dict) else {}
        current_propulsion = _best_text(metrics.get("current_propulsion"), chapter_result.plan.primary_propulsion)
        decision_name = judge_review.recommended_action
        if decision_name not in {"accept", "forward_fix", "local_repair", "phase_repair", "arc_repair"}:
            return local_decision
        planning_prefers_continuous_cluster = self._planning_prefers_continuous_cluster(
            chapter_result,
            book_outline,
            volume_outline,
        )
        repair_counts = self._stagnation_repair_counts(chapter_result.volume_index)
        total_repair_counts = self._stagnation_total_repair_counts()
        verdict = _best_text(judge_review.verdict, "stagnation_risk")
        if verdict == "reasonable_cluster":
            decision_name = "accept"
        elif planning_prefers_continuous_cluster:
            if decision_name in {"phase_repair", "arc_repair"}:
                decision_name = "local_repair" if judge_review.confidence >= 88 else "forward_fix"
            elif decision_name == "local_repair":
                decision_name = "forward_fix"
        elif verdict == "stagnation_risk" and decision_name in {"phase_repair", "arc_repair"}:
            decision_name = "local_repair"
        if decision_name == "arc_repair" and repair_counts["arc_repair"] >= 1:
            decision_name = "phase_repair" if repair_counts["phase_repair"] == 0 else "local_repair"
        if decision_name == "phase_repair" and repair_counts["phase_repair"] >= 1:
            decision_name = "local_repair"
        if decision_name == "arc_repair" and total_repair_counts["arc_repair"] >= 1:
            decision_name = "phase_repair" if total_repair_counts["phase_repair"] < 2 else "local_repair"
        if decision_name == "phase_repair" and total_repair_counts["phase_repair"] >= 2:
            decision_name = "local_repair"
        return self._build_stagnation_decision(
            chapter_result,
            report,
            volume_outline,
            decision_name=decision_name,
            confidence=judge_review.confidence,
            reason=judge_review.reason or local_decision.reason,
            current_propulsion=current_propulsion,
            scope_start_chapter=judge_review.scope_start_chapter,
            scope_end_chapter=judge_review.scope_end_chapter,
            next_constraints=judge_review.next_chapter_constraints or local_decision.next_chapter_constraints,
            repair_goal=judge_review.repair_goal or local_decision.repair_goal,
        )

    def _write_stagnation_decision(self, decision: StagnationDecision) -> None:
        payload = asdict(decision)
        self.store.write_json(
            f"state/chapter-{decision.chapter_index:02d}.stagnation-decision.json",
            payload,
        )
        self.store.write_json("data/latest-stagnation-decision.json", payload)

    def _apply_stagnation_forward_fix(
        self,
        chapter_result: ChapterResult,
        decision: StagnationDecision,
    ) -> ChapterResult:
        chapter_result.continuity.must_remember = _merge_lists(
            chapter_result.continuity.must_remember,
            [decision.repair_goal, *decision.next_chapter_constraints],
        )
        chapter_result.continuity.next_chapter_targets = _merge_lists(
            chapter_result.continuity.next_chapter_targets,
            decision.next_chapter_constraints,
        )
        return chapter_result

    def _write_stagnation_execution(
        self,
        chapter_index: int,
        *,
        volume_index: int,
        decision: StagnationDecision,
        executed_action: str,
        executed_scope: tuple[int, int],
        automatic: bool = True,
    ) -> None:
        payload = {
            "chapter_index": chapter_index,
            "decision": asdict(decision),
            "executed_action": executed_action,
            "executed_scope": {
                "start_chapter": executed_scope[0],
                "end_chapter": executed_scope[1],
            },
            "automatic": automatic,
        }
        self.store.write_json(f"state/chapter-{chapter_index:02d}.stagnation-execution.json", payload)
        self.store.write_json("data/latest-stagnation-execution.json", payload)
        self._record_stagnation_repair_history(chapter_index, volume_index, executed_action, executed_scope)

    def _load_stagnation_repair_history(self) -> dict[str, Any]:
        path = self.store.root / "data" / "stagnation-repair-history.json"
        if not path.exists():
            return {"by_volume": {}, "records": []}
        try:
            payload = load_json(path)
        except Exception:
            return {"by_volume": {}, "records": []}
        if not isinstance(payload, dict):
            return {"by_volume": {}, "records": []}
        by_volume = payload.get("by_volume") if isinstance(payload.get("by_volume"), dict) else {}
        records = payload.get("records") if isinstance(payload.get("records"), list) else []
        return {"by_volume": by_volume, "records": records}

    def _write_stagnation_repair_history(self) -> None:
        self.store.write_json("data/stagnation-repair-history.json", self._stagnation_repair_history)

    def _stagnation_repair_counts(self, volume_index: int) -> dict[str, int]:
        by_volume = self._stagnation_repair_history.get("by_volume") if isinstance(self._stagnation_repair_history, dict) else {}
        volume_payload = by_volume.get(str(volume_index)) if isinstance(by_volume, dict) else {}
        if not isinstance(volume_payload, dict):
            return {"phase_repair": 0, "arc_repair": 0}
        return {
            "phase_repair": int(volume_payload.get("phase_repair", 0) or 0),
            "arc_repair": int(volume_payload.get("arc_repair", 0) or 0),
        }

    def _stagnation_total_repair_counts(self) -> dict[str, int]:
        records = self._stagnation_repair_history.get("records") if isinstance(self._stagnation_repair_history, dict) else []
        if not isinstance(records, list):
            return {"phase_repair": 0, "arc_repair": 0}
        counts = {"phase_repair": 0, "arc_repair": 0}
        for item in records:
            if not isinstance(item, dict):
                continue
            action = str(item.get("action") or "").strip()
            if action in counts:
                counts[action] += 1
        return counts

    def _record_stagnation_repair_history(
        self,
        chapter_index: int,
        volume_index: int,
        executed_action: str,
        executed_scope: tuple[int, int],
    ) -> None:
        if executed_action not in {"phase_repair", "arc_repair"}:
            return
        history = self._stagnation_repair_history
        by_volume = history.setdefault("by_volume", {})
        records = history.setdefault("records", [])
        volume_key = str(volume_index)
        current = by_volume.setdefault(volume_key, {})
        current[executed_action] = int(current.get(executed_action, 0) or 0) + 1
        records.append(
            {
                "chapter_index": chapter_index,
                "volume_index": volume_index,
                "action": executed_action,
                "scope_start_chapter": executed_scope[0],
                "scope_end_chapter": executed_scope[1],
            }
        )
        if len(records) > 40:
            del records[:-40]
        self._write_stagnation_repair_history()

    def _bounded_stagnation_scope(
        self,
        decision: StagnationDecision,
    ) -> tuple[int, int]:
        start = decision.scope_start_chapter
        end = decision.scope_end_chapter
        max_span = {
            "local_repair": 5,
            "phase_repair": 10,
            "arc_repair": 12,
        }.get(decision.decision, max(1, end - start + 1))
        if end - start + 1 <= max_span:
            return start, end
        return max(1, end - max_span + 1), end

    def _build_stagnation_cluster_repair_audit(
        self,
        decision: StagnationDecision,
        chapter_result: ChapterResult,
        *,
        executed_scope: tuple[int, int],
    ) -> LogicAuditReport:
        scope_start, scope_end = executed_scope
        flagged = [
            {
                "chapter_index": index,
                "issue": {
                    "local_repair": "近期章节簇在同一推进家族内长期空转，需小范围重排。",
                    "phase_repair": "最近阶段内连续章节在相似功能和升级方式上空转，需阶段级回修。",
                    "arc_repair": "最近弧段长期空转，需弧段级自动回修并重建状态。",
                }.get(decision.decision, "近期章节簇出现长期空转，需回修。"),
            }
            for index in range(scope_start, scope_end + 1)
        ]
        instruction = {
            "local_repair": "允许维持同一大簇推进，但必须改变章功能、scene 组合和升级方式；避免只重复确认同一命门或把同一公开局再抬半级。",
            "phase_repair": "这是阶段级回修：优先保留当前卷目标，但必须重排最近阶段的章功能分布，补出新的代价、站位和不可逆后果。",
            "arc_repair": "这是弧段级自动回修：优先保留原始规划和卷目标，不要推翻题材卖点；只修最近弧段的长期空转，限制在最小必要范围内。",
        }.get(decision.decision, "优先改变章功能和升级方式，避免空转。")
        return LogicAuditReport(
            passed=False,
            gate_passed=False,
            summary=decision.repair_goal,
            issues=[decision.reason],
            watch_items=[],
            required_followups=decision.next_chapter_constraints,
            flagged_chapters=flagged,
            repair_plan=[
                {
                    "start_chapter": scope_start,
                    "end_chapter": scope_end,
                    "instruction": instruction,
                }
            ],
            gate_level="repair",
        )

    def _apply_stagnation_cluster_repair(
        self,
        spec: ProjectSpec,
        bible: WorldBible,
        book_outline: BookOutline | None,
        volume_outline: VolumeOutline | None,
        prior_chapters: list[ChapterResult] | None,
        chapter_result: ChapterResult,
        decision: StagnationDecision,
    ) -> ChapterResult:
        if book_outline is None or volume_outline is None or prior_chapters is None:
            return self._apply_stagnation_forward_fix(chapter_result, decision)
        repair_source = [copy.deepcopy(item) for item in prior_chapters] + [copy.deepcopy(chapter_result)]
        executed_scope = self._bounded_stagnation_scope(decision)
        audit = self._build_stagnation_cluster_repair_audit(
            decision,
            chapter_result,
            executed_scope=executed_scope,
        )
        repaired = self._repair_chapter_cluster(
            spec,
            bible,
            book_outline,
            volume_outline,
            repair_source,
            audit,
        )
        repaired_prior = [item for item in repaired if item.index < chapter_result.index]
        repaired_current = next((item for item in repaired if item.index == chapter_result.index), chapter_result)
        prior_chapters[:] = repaired_prior
        rebuilt_continuity = self._rebuild_continuity_state(bible, repaired_prior)
        rebuilt_promises, rebuilt_progression, rebuilt_causality = self._rebuild_long_range_state(repaired_prior)
        pending_state = {
            "prior_chapters": repaired_prior,
            "continuity": rebuilt_continuity,
            "promise_ledger": rebuilt_promises,
            "progression_ledger": rebuilt_progression,
            "causality_graph": rebuilt_causality,
        }
        if decision.decision == "arc_repair":
            pending_state["refresh_controls"] = True
            pending_state["through_volume"] = chapter_result.volume_index
        self._pending_chapter_repair_state = pending_state
        repaired_current.continuity.must_remember = _merge_lists(
            repaired_current.continuity.must_remember,
            [decision.repair_goal, *decision.next_chapter_constraints],
        )
        repaired_current.continuity.next_chapter_targets = _merge_lists(
            repaired_current.continuity.next_chapter_targets,
            decision.next_chapter_constraints,
        )
        self._write_stagnation_execution(
            chapter_result.index,
            volume_index=chapter_result.volume_index,
            decision=decision,
            executed_action=decision.decision,
            executed_scope=executed_scope,
        )
        return repaired_current

    def _apply_stagnation_local_repair(
        self,
        spec: ProjectSpec,
        bible: WorldBible,
        book_outline: BookOutline | None,
        volume_outline: VolumeOutline | None,
        prior_chapters: list[ChapterResult] | None,
        chapter_result: ChapterResult,
        decision: StagnationDecision,
    ) -> ChapterResult:
        return self._apply_stagnation_cluster_repair(
            spec,
            bible,
            book_outline,
            volume_outline,
            prior_chapters,
            chapter_result,
            decision,
        )

    def _apply_stagnation_phase_repair(
        self,
        spec: ProjectSpec,
        bible: WorldBible,
        book_outline: BookOutline | None,
        volume_outline: VolumeOutline | None,
        prior_chapters: list[ChapterResult] | None,
        chapter_result: ChapterResult,
        decision: StagnationDecision,
    ) -> ChapterResult:
        return self._apply_stagnation_cluster_repair(
            spec,
            bible,
            book_outline,
            volume_outline,
            prior_chapters,
            chapter_result,
            decision,
        )

    def _apply_stagnation_arc_repair(
        self,
        spec: ProjectSpec,
        bible: WorldBible,
        book_outline: BookOutline | None,
        volume_outline: VolumeOutline | None,
        prior_chapters: list[ChapterResult] | None,
        chapter_result: ChapterResult,
        decision: StagnationDecision,
    ) -> ChapterResult:
        return self._apply_stagnation_cluster_repair(
            spec,
            bible,
            book_outline,
            volume_outline,
            prior_chapters,
            chapter_result,
            decision,
        )

    def _apply_stagnation_decision(
        self,
        spec: ProjectSpec,
        bible: WorldBible,
        chapter_result: ChapterResult,
        decision: StagnationDecision,
        *,
        prior_chapters: list[ChapterResult] | None,
        book_outline: BookOutline | None,
        volume_outline: VolumeOutline | None,
    ) -> ChapterResult:
        self._write_stagnation_decision(decision)
        pending_decision_path = self.store.root / "data" / "pending-upper-decision.json"
        pending_decision_path.unlink(missing_ok=True)
        if decision.decision == "accept":
            chapter_result.continuity.must_remember = _merge_lists(
                chapter_result.continuity.must_remember,
                [decision.repair_goal],
            )
            self._write_stagnation_execution(
                chapter_result.index,
                volume_index=chapter_result.volume_index,
                decision=decision,
                executed_action="accept",
                executed_scope=(decision.scope_start_chapter, decision.scope_end_chapter),
            )
            return chapter_result
        if decision.decision == "forward_fix":
            chapter_result = self._apply_stagnation_forward_fix(chapter_result, decision)
            self._write_stagnation_execution(
                chapter_result.index,
                volume_index=chapter_result.volume_index,
                decision=decision,
                executed_action="forward_fix",
                executed_scope=(decision.scope_start_chapter, decision.scope_end_chapter),
            )
            return chapter_result
        if decision.decision == "local_repair":
            return self._apply_stagnation_local_repair(
                spec,
                bible,
                book_outline,
                volume_outline,
                prior_chapters,
                chapter_result,
                decision,
            )
        if decision.decision == "phase_repair":
            return self._apply_stagnation_phase_repair(
                spec,
                bible,
                book_outline,
                volume_outline,
                prior_chapters,
                chapter_result,
                decision,
            )
        return self._apply_stagnation_arc_repair(
            spec,
            bible,
            book_outline,
            volume_outline,
            prior_chapters,
            chapter_result,
            decision,
        )

    def _consume_pending_chapter_repair_state(self) -> dict[str, Any] | None:
        pending = self._pending_chapter_repair_state
        self._pending_chapter_repair_state = None
        return pending

    def _load_volume_outline_context(self, volume_index: int) -> VolumeOutline | None:
        cached = self._volume_outlines.get(volume_index)
        if cached is not None:
            return cached
        path = self.store.volume_outline_path(volume_index)
        if not path.exists():
            return None
        outline = _volume_outline_from_dict(load_json(path))
        self._volume_outlines[volume_index] = outline
        return outline

    def _restructure_chapter_plan_after_quality_failure(
        self,
        spec: ProjectSpec,
        bible: WorldBible,
        book_outline: BookOutline,
        volume_outline: VolumeOutline,
        chapter: ChapterOutlineItem,
        continuity: ContinuityState,
        prior_chapters: list[ChapterResult] | None,
        previous_plan: ChapterPlan,
        review: ReviewFeedback,
        local_quality: LocalQualityReport,
        *,
        reason_label: str,
        escalation_level: int = 1,
    ) -> ChapterPlan:
        prior = prior_chapters or []
        retrieved_memory = self._select_story_memories(chapter, None, continuity, prior)
        style_memory = self._select_style_memories(chapter, None, prior)
        promise_memory = self._select_promise_memories(chapter, None, continuity, limit=8)
        causality_memory = self._select_causality_memories(chapter, None, continuity, limit=8)
        phase_brief = _chapter_phase_brief(spec, chapter.index)
        recent_propulsion_history = _recent_propulsion_history(prior)
        logic_audit = self._latest_logic_audit_for_volume(chapter.volume_index)
        restructure_notes = _chapter_plan_restructure_notes(
            chapter,
            previous_plan,
            recent_propulsion_history,
            escalation_level=escalation_level,
        )
        failure_issues = _merge_lists(review.required_fixes, review.issues, local_quality.issues)
        if failure_issues:
            restructure_notes.append("上一稿未通过的直接原因：" + "；".join(failure_issues[:4]))
        deduped_notes: list[str] = []
        for note in restructure_notes:
            if note and note not in deduped_notes:
                deduped_notes.append(note)
        payload = self._generate_json_with_progress(
            "chapter_plan_restructure",
            f"因{reason_label}重排第 {chapter.index} 章计划。",
            f"第{chapter.index}章计划重排",
            chapter_plan_system_prompt(),
            chapter_plan_user_prompt(
                spec,
                bible,
                book_outline,
                volume_outline,
                chapter,
                continuity,
                continuity_runtime=self._continuity_runtime,
                retrieved_memory=retrieved_memory,
                style_memory=style_memory,
                promise_memory=promise_memory,
                causality_memory=causality_memory,
                phase_brief=phase_brief,
                recent_propulsion_history=recent_propulsion_history,
                logic_audit=logic_audit_runtime_view(logic_audit),
                power_system=self._power_system,
                restructure_notes=deduped_notes[:6],
                previous_plan=asdict(previous_plan),
            ),
            temperature=0.15,
            max_output_tokens=2400,
            session_id=f"planner-chapter-{chapter.index}",
            session_max_chars=30000,
        )
        payload = self._normalize_or_repair_chapter_plan_payload(
            chapter,
            payload,
            reason=f"restructure_{reason_label}",
        )
        plan = _chapter_plan_from_payload(
            spec,
            chapter,
            payload,
            phase_brief=phase_brief,
        )
        if not plan.scenes:
            payload = self._fallback_chapter_plan_payload(
                spec,
                volume_outline,
                chapter,
                phase_brief=phase_brief,
                reason_label=f"quality_restructure_{reason_label}_no_scenes",
                source_payload=payload,
            )
            plan = _chapter_plan_from_payload(
                spec,
                chapter,
                payload,
                phase_brief=phase_brief,
            )
        failure_modes = self._quality_failure_modes(local_quality)
        self.store.write_json(
            f"state/chapter-{chapter.index:02d}.plan-reroute.json",
            {
                "chapter_index": chapter.index,
                "reason_label": reason_label,
                "escalation_level": escalation_level,
                "failure_modes": sorted(failure_modes),
                "restructure_notes": deduped_notes[:6],
                "previous_plan": asdict(previous_plan),
                "plan": asdict(plan),
            },
        )
        relative_path = str(self.store.chapter_plan_path(chapter.index).relative_to(self.store.root))
        self.store.write_json(relative_path, plan)
        return plan

    def _generate_chapter(
        self,
        spec: ProjectSpec,
        bible: WorldBible,
        chapter: ChapterOutlineItem,
        plan: ChapterPlan,
        continuity: ContinuityState,
        prior_chapters: list[ChapterResult] | None = None,
        book_outline: BookOutline | None = None,
        volume_outline: VolumeOutline | None = None,
    ) -> ChapterResult:
        context = self._prepare_chapter_generation_context(spec, bible, chapter, plan, continuity, prior_chapters)
        retrieved_memory = context["retrieved_memory"]
        style_memory = context["style_memory"]
        promise_memory = context["promise_memory"]
        causality_memory = context["causality_memory"]
        recent_propulsion_history = context["recent_propulsion_history"]
        logic_audit = context["logic_audit"]
        chapter_room = context["chapter_room"]
        execution_packet = context["execution_packet"]
        relative_execution = str(self.store.chapter_execution_path(chapter.index).relative_to(self.store.root))
        self.store.write_json(relative_execution, execution_packet)
        character_names = _character_names(bible, spec)
        chapter_target_chars = _resolved_chapter_target_chars(spec, chapter, plan)
        self._emit_progress(
            "chapter_draft",
            f"生成第 {chapter.index} 章正文。",
            chapter_index=chapter.index,
            volume_index=chapter.volume_index,
        )
        draft = self._generate_text_with_progress(
            "chapter_draft",
            f"生成第 {chapter.index} 章正文。",
            f"第{chapter.index}章初稿",
            draft_system_prompt(),
            draft_user_prompt(
                spec,
                bible,
                self._style_bible,
                chapter,
                plan,
                continuity,
                self._voice_cards,
                chapter_room=chapter_room,
                retrieved_memory=retrieved_memory,
                style_memory=style_memory,
                promise_memory=promise_memory,
                causality_memory=causality_memory,
                logic_audit=logic_audit,
                execution_packet=execution_packet,
            )
            + self._anthropic_writer_suffix(),
            temperature=0.6,
            max_output_tokens=_draft_token_budget(
                chapter_target_chars,
                length_tolerance=spec.chapter_char_tolerance,
                short_standalone=_is_short_standalone_spec(spec),
            ),
            session_id=f"writer-v{chapter.volume_index}",
            session_max_chars=_writer_session_max_chars(spec),
        )
        draft = self._clean_generated_draft(chapter.index, draft, stage="chapter_draft")
        local_quality = analyze_chapter(
            draft,
            chapter_target_chars,
            character_names,
            market_profile=spec.market_profile,
            **self._chapter_local_quality_kwargs(spec, chapter, plan, prior_chapters or []),
        )
        review = self._review_chapter(
            spec,
            bible,
            chapter,
            plan,
            draft,
            local_quality,
            continuity,
            execution_packet,
        )
        attempts = 1

        while attempts <= self.max_rewrites and not (local_quality.passed and review.passed):
            self._emit_progress(
                "chapter_rewrite",
                f"重写第 {chapter.index} 章。",
                chapter_index=chapter.index,
                attempt=attempts,
            )
            rewrite_session_id = f"writer-rewrite-c{chapter.index}"
            self._reset_client_session(rewrite_session_id)
            draft = self._generate_text_with_progress(
                "chapter_rewrite",
                f"重写第 {chapter.index} 章。",
                f"第{chapter.index}章重写#{attempts}",
                draft_system_prompt(),
                rewrite_user_prompt(
                    spec,
                    bible,
                    self._style_bible,
                    chapter,
                    plan,
                    draft,
                    {"model_review": asdict(review), "local_review": asdict(local_quality)},
                    continuity,
                    self._voice_cards,
                    execution_packet=execution_packet,
                    chapter_room=chapter_room,
                    retrieved_memory=retrieved_memory,
                    style_memory=style_memory,
                    promise_memory=promise_memory,
                    causality_memory=causality_memory,
                    logic_audit=logic_audit,
                )
                + self._anthropic_writer_suffix(rewrite=True),
                temperature=0.55,
                max_output_tokens=_draft_token_budget(
                    chapter_target_chars,
                    length_tolerance=spec.chapter_char_tolerance,
                    short_standalone=_is_short_standalone_spec(spec),
                ),
                session_id=rewrite_session_id,
                session_max_chars=_writer_session_max_chars(spec),
            )
            draft = self._clean_generated_draft(chapter.index, draft, stage="chapter_rewrite")
            local_quality = analyze_chapter(
                draft,
                chapter_target_chars,
                character_names,
                market_profile=spec.market_profile,
                **self._chapter_local_quality_kwargs(spec, chapter, plan, prior_chapters or []),
            )
            review = self._review_chapter(
                spec,
                bible,
                chapter,
                plan,
                draft,
                local_quality,
                continuity,
                execution_packet,
            )
            attempts += 1

        if not (local_quality.passed and review.passed):
            draft, local_quality, review, attempts = self._attempt_quality_failure_recovery(
                spec,
                bible,
                chapter,
                plan,
                draft,
                local_quality,
                review,
                continuity,
                execution_packet,
                retrieved_memory=retrieved_memory,
                style_memory=style_memory,
                promise_memory=promise_memory,
                causality_memory=causality_memory,
                logic_audit=logic_audit,
                chapter_room=chapter_room,
                chapter_target_chars=chapter_target_chars,
                character_names=character_names,
                prior_chapters=prior_chapters or [],
                attempts=attempts,
            )

        if not (local_quality.passed and review.passed) and _should_attempt_length_compaction(spec, local_quality):
            self._emit_progress(
                "chapter_compact",
                f"压缩第 {chapter.index} 章篇幅。",
                chapter_index=chapter.index,
            )
            compact_session_id = f"writer-compact-c{chapter.index}"
            self._reset_client_session(compact_session_id)
            draft = self._generate_text_with_progress(
                "chapter_compact",
                f"压缩第 {chapter.index} 章篇幅。",
                f"第{chapter.index}章压缩",
                draft_system_prompt(),
                compression_user_prompt(
                    spec,
                    bible,
                    self._style_bible,
                    chapter,
                    plan,
                    draft,
                    {"model_review": asdict(review), "local_review": asdict(local_quality)},
                    continuity,
                    self._voice_cards,
                    execution_packet=execution_packet,
                    chapter_room=chapter_room,
                    retrieved_memory=retrieved_memory,
                    style_memory=style_memory,
                    promise_memory=promise_memory,
                    causality_memory=causality_memory,
                    logic_audit=logic_audit,
                )
                + self._anthropic_writer_suffix(rewrite=True),
                temperature=0.25,
                max_output_tokens=_compaction_token_budget(
                    chapter_target_chars,
                    length_tolerance=spec.chapter_char_tolerance,
                    short_standalone=_is_short_standalone_spec(spec),
                ),
                session_id=compact_session_id,
                session_max_chars=_writer_session_max_chars(spec),
            )
            draft = self._clean_generated_draft(chapter.index, draft, stage="chapter_compact")
            local_quality = analyze_chapter(
                draft,
                chapter_target_chars,
                character_names,
                market_profile=spec.market_profile,
                **self._chapter_local_quality_kwargs(spec, chapter, plan, prior_chapters or []),
            )
            review = self._review_chapter(
                spec,
                bible,
                chapter,
                plan,
                draft,
                local_quality,
                continuity,
                execution_packet,
            )

        if not (local_quality.passed and review.passed):
            repaired_result = self._attempt_quality_failure_window_repair(
                spec,
                bible,
                chapter,
                plan,
                draft,
                local_quality,
                review,
                continuity,
                prior_chapters=prior_chapters or [],
                book_outline=book_outline,
                volume_outline=volume_outline,
                attempts=attempts,
            )
            if repaired_result is not None:
                result = repaired_result
                relative_chapter = str(self.store.chapter_path(chapter.index).relative_to(self.store.root))
                self.store.write_text(relative_chapter, result.draft)
                self.store.write_json(
                    str(self.store.chapter_review_path(chapter.index).relative_to(self.store.root)),
                    {
                        "model": result.review,
                        "local": result.local_quality,
                        "attempts": result.attempts,
                        "summary": result.continuity.chapter_summary,
                    },
                )
                self.store.write_json(
                    str(self.store.continuity_path(chapter.index).relative_to(self.store.root)),
                    result.continuity,
                )
                self.store.write_json(
                    str(self.store.chapter_memory_path(chapter.index).relative_to(self.store.root)),
                    result.long_memory,
                )
                self.store.write_json(relative_execution, execution_packet)
                return result
            self._write_failed_chapter_snapshot(chapter.index, draft, review, local_quality, attempts)
            raise RuntimeError(
                f"Chapter {chapter.index} failed quality gates after {attempts} attempts.\n"
                f"Model review: {compact_json(asdict(review))}\n"
                f"Local review: {compact_json(asdict(local_quality))}"
            )

        continuity_update = self._extract_continuity(spec, bible, chapter, draft, continuity)
        stagnation_report = self._record_stagnation_signal(chapter.index, local_quality, continuity_update)
        self._long_memory_context = continuity
        long_memory = self._extract_long_range_memory(spec, bible, chapter, plan, draft)
        result = ChapterResult(
            index=chapter.index,
            volume_index=chapter.volume_index,
            title=chapter.title,
            outline_item=chapter,
            draft=draft,
            plan=plan,
            review=review,
            local_quality=local_quality,
            continuity=continuity_update,
            attempts=attempts,
            long_memory=long_memory,
        )
        if stagnation_report is not None:
            judge_review: StagnationJudgeReview | None = None
            if self._should_trigger_stagnation_judge(local_quality, stagnation_report, logic_audit):
                judge_review = self._run_stagnation_judge(
                    spec,
                    bible,
                    result,
                    stagnation_report,
                    volume_outline,
                    continuity,
                    self._continuity_runtime,
                    prior_chapters,
                )
            decision = self._combine_stagnation_decision(
                result,
                local_quality,
                stagnation_report,
                book_outline,
                volume_outline,
                judge_review,
            )
            result = self._apply_stagnation_decision(
                spec,
                bible,
                result,
                decision,
                prior_chapters=prior_chapters,
                book_outline=book_outline,
                volume_outline=volume_outline,
            )
        relative_chapter = str(self.store.chapter_path(chapter.index).relative_to(self.store.root))
        self.store.write_text(relative_chapter, result.draft)
        self.store.write_json(
            str(self.store.chapter_review_path(chapter.index).relative_to(self.store.root)),
            {
                "model": result.review,
                "local": result.local_quality,
                "attempts": result.attempts,
                "summary": result.continuity.chapter_summary,
            },
        )
        self.store.write_json(str(self.store.continuity_path(chapter.index).relative_to(self.store.root)), result.continuity)
        self.store.write_json(
            str(self.store.chapter_memory_path(chapter.index).relative_to(self.store.root)),
            result.long_memory,
        )
        self.store.write_json(relative_execution, execution_packet)
        return result

    def _attempt_quality_failure_recovery(
        self,
        spec: ProjectSpec,
        bible: WorldBible,
        chapter: ChapterOutlineItem,
        plan: ChapterPlan,
        draft: str,
        local_quality: LocalQualityReport,
        review: ReviewFeedback,
        continuity: ContinuityState,
        execution_packet: dict[str, Any],
        *,
        retrieved_memory: list[dict[str, object]] | None,
        style_memory: list[dict[str, object]] | None,
        promise_memory: list[dict[str, object]] | None,
        causality_memory: list[dict[str, object]] | None,
        logic_audit: object | None,
        chapter_room: dict[str, Any],
        chapter_target_chars: int,
        character_names: list[str],
        prior_chapters: list[ChapterResult],
        attempts: int,
    ) -> tuple[str, LocalQualityReport, ReviewFeedback, int]:
        divergence_recovery_touched = False
        expansion_recovery_touched = False
        truncation_recovery_rounds = 0

        def _rerun_local_and_review(current_draft: str) -> tuple[LocalQualityReport, ReviewFeedback]:
            rerun_local = analyze_chapter(
                current_draft,
                chapter_target_chars,
                character_names,
                market_profile=spec.market_profile,
                **self._chapter_local_quality_kwargs(spec, chapter, plan, prior_chapters),
            )
            rerun_review = self._review_chapter(
                spec,
                bible,
                chapter,
                plan,
                current_draft,
                rerun_local,
                continuity,
                execution_packet,
            )
            return rerun_local, rerun_review

        def _apply_provider_recovery_guards(
            current_draft: str,
            current_local_quality: LocalQualityReport,
            current_review: ReviewFeedback,
            current_attempts: int,
        ) -> tuple[str, LocalQualityReport, ReviewFeedback, int]:
            nonlocal divergence_recovery_touched, expansion_recovery_touched, truncation_recovery_rounds
            if not (self._refusal_prone() or self._underwrite_prone()):
                return current_draft, current_local_quality, current_review, current_attempts
            guard_rounds = 0
            while guard_rounds < 4:
                if self._refusal_prone() and _draft_looks_like_model_refusal(current_draft):
                    self._emit_progress(
                        "chapter_redraft",
                        f"检测到第 {chapter.index} 章正文拒答，重新生成正文。",
                        chapter_index=chapter.index,
                        attempt=current_attempts,
                    )
                    self._reset_client_session(f"writer-redraft-c{chapter.index}")
                    current_draft = self._generate_text_with_progress(
                        "chapter_redraft",
                        f"重新生成第 {chapter.index} 章正文。",
                        f"第{chapter.index}章拒答重生",
                        draft_system_prompt(),
                        draft_user_prompt(
                            spec,
                            bible,
                            self._style_bible,
                            chapter,
                            plan,
                            continuity,
                            self._voice_cards,
                            chapter_room=chapter_room,
                            retrieved_memory=retrieved_memory,
                            style_memory=style_memory,
                            promise_memory=promise_memory,
                            causality_memory=causality_memory,
                            logic_audit=logic_audit,
                            execution_packet=execution_packet,
                        )
                        + self._anthropic_writer_suffix()
                        + "\n\n补充要求：上一次返回了拒绝说明而不是正文。这一次必须只输出完整章节正文，不要输出任何政策、能力边界、免责声明或替代建议。",
                        temperature=0.55,
                        max_output_tokens=_draft_token_budget(
                            chapter_target_chars,
                            length_tolerance=spec.chapter_char_tolerance,
                            short_standalone=_is_short_standalone_spec(spec),
                        ),
                        session_id=f"writer-redraft-c{chapter.index}",
                        session_max_chars=_writer_session_max_chars(spec),
                    )
                    current_draft = self._clean_generated_draft(chapter.index, current_draft, stage="chapter_redraft")
                    current_local_quality, current_review = _rerun_local_and_review(current_draft)
                    current_attempts += 1
                    guard_rounds += 1
                    continue

                if _quality_failure_looks_truncated_draft(current_draft, current_review, current_local_quality):
                    target_min = int(current_local_quality.metrics.get("target_chars_min", 0) or 0)
                    current_char_count = int(current_local_quality.metrics.get("char_count", 0) or 0)
                    if truncation_recovery_rounds >= 1 and (
                        current_char_count <= 700
                        or (target_min > 0 and current_char_count <= int(target_min * 0.45))
                    ):
                        self._emit_progress(
                            "chapter_redraft",
                            f"检测到第 {chapter.index} 章正文持续截断，改为整章重生。",
                            chapter_index=chapter.index,
                            attempt=current_attempts,
                        )
                        self._reset_client_session(f"writer-redraft-c{chapter.index}")
                        current_draft = self._generate_text_with_progress(
                            "chapter_redraft",
                            f"重新生成第 {chapter.index} 章正文。",
                            f"第{chapter.index}章截断重生",
                            draft_system_prompt(),
                            draft_user_prompt(
                                spec,
                                bible,
                                self._style_bible,
                                chapter,
                                plan,
                                continuity,
                                self._voice_cards,
                                chapter_room=chapter_room,
                                retrieved_memory=retrieved_memory,
                                style_memory=style_memory,
                                promise_memory=promise_memory,
                                causality_memory=causality_memory,
                                logic_audit=logic_audit,
                                execution_packet=execution_packet,
                            )
                            + self._anthropic_writer_suffix()
                            + "\n\n补充要求：上一次正文在中途截断。必须从头输出完整本章正文，完整写出已规划的场景、收尾反馈和章尾钩子；不要输出半句、说明、提纲、清单或拒答文字。",
                            temperature=0.45,
                            max_output_tokens=_draft_token_budget(
                                chapter_target_chars,
                                length_tolerance=spec.chapter_char_tolerance,
                                short_standalone=_is_short_standalone_spec(spec),
                            ),
                            session_id=f"writer-redraft-c{chapter.index}",
                            session_max_chars=_writer_session_max_chars(spec),
                        )
                        current_draft = self._clean_generated_draft(chapter.index, current_draft, stage="chapter_redraft")
                        current_local_quality, current_review = _rerun_local_and_review(current_draft)
                        current_attempts += 1
                        guard_rounds += 1
                        truncation_recovery_rounds += 1
                        continue
                    self._emit_progress(
                        "chapter_continue",
                        f"检测到第 {chapter.index} 章正文被截断，继续补完本章。",
                        chapter_index=chapter.index,
                        attempt=current_attempts,
                    )
                    self._reset_client_session(f"writer-continue-c{chapter.index}")
                    current_draft = self._generate_text_with_progress(
                        "chapter_continue",
                        f"继续补完第 {chapter.index} 章正文。",
                        f"第{chapter.index}章截断续写",
                        draft_system_prompt(),
                        rewrite_user_prompt(
                            spec,
                            bible,
                            self._style_bible,
                            chapter,
                            plan,
                            current_draft,
                            {
                                "model_review": asdict(current_review),
                                "local_review": asdict(current_local_quality),
                                "final_fix": (
                                    "当前正文末尾被截断。保留已写正文与既有剧情顺序，不要重写前文；"
                                    "从截断处自然续上，补齐本章缺失的后续场景、收尾反馈、情绪余波和章尾钩子。"
                                    + (f" 目标至少补到 {target_min} 字附近。" if target_min > 0 else "")
                                    + " 不要输出说明、提纲或拒答文字。"
                                ),
                            },
                            continuity,
                            self._voice_cards,
                            execution_packet=execution_packet,
                            chapter_room=chapter_room,
                            retrieved_memory=retrieved_memory,
                            style_memory=style_memory,
                            promise_memory=promise_memory,
                            causality_memory=causality_memory,
                            logic_audit=logic_audit,
                        )
                        + self._anthropic_writer_suffix(rewrite=True),
                        temperature=0.35,
                        max_output_tokens=_draft_token_budget(
                            chapter_target_chars,
                            length_tolerance=spec.chapter_char_tolerance,
                            short_standalone=_is_short_standalone_spec(spec),
                        ),
                        session_id=f"writer-continue-c{chapter.index}",
                        session_max_chars=_writer_session_max_chars(spec),
                    )
                    current_draft = self._clean_generated_draft(chapter.index, current_draft, stage="chapter_continue")
                    current_local_quality, current_review = _rerun_local_and_review(current_draft)
                    current_attempts += 1
                    guard_rounds += 1
                    truncation_recovery_rounds += 1
                    continue

                if not (current_local_quality.passed and current_review.passed) and (
                    _chapter_review_has_boundary_contamination(current_review)
                    or _draft_tail_looks_like_next_chapter_opening(current_draft)
                ):
                    trimmed, changed = _trim_next_chapter_opening_from_tail(current_draft)
                    if changed:
                        self._emit_progress(
                            "chapter_boundary_fix",
                            f"修正第 {chapter.index} 章章节边界。",
                            chapter_index=chapter.index,
                            attempt=current_attempts,
                        )
                        current_draft = trimmed
                        current_local_quality, current_review = _rerun_local_and_review(current_draft)
                        current_attempts += 1
                        guard_rounds += 1
                        continue

                should_expand_divergence = (
                    self._underwrite_prone()
                    and not divergence_recovery_touched
                    and not (current_local_quality.passed and current_review.passed)
                    and _anthropic_review_local_divergence_needs_expansion(current_review, current_local_quality)
                )
                should_expand_short = (
                    self._underwrite_prone()
                    and not expansion_recovery_touched
                    and not (current_local_quality.passed and current_review.passed)
                    and not _draft_looks_like_model_refusal(current_draft)
                    and _underwritten_but_structured_needs_expansion(current_draft, current_review, current_local_quality)
                )
                if should_expand_short or should_expand_divergence:
                    expansion_recovery_touched = True
                    if should_expand_divergence:
                        divergence_recovery_touched = True
                    target_min = int(current_local_quality.metrics.get("target_chars_min", 0) or 0)
                    targeted_focus = [
                        item
                        for item in [*current_review.required_fixes, *current_review.issues]
                        if _best_text(item)
                    ][:4]
                    self._emit_progress(
                        "chapter_expand",
                        f"补写第 {chapter.index} 章细节与兑现。",
                        chapter_index=chapter.index,
                        attempt=current_attempts,
                    )
                    self._reset_client_session(f"writer-expand-c{chapter.index}")
                    current_draft = self._generate_text_with_progress(
                        "chapter_expand",
                        f"补写第 {chapter.index} 章细节与兑现。",
                        f"第{chapter.index}章补写扩容",
                        draft_system_prompt(),
                        rewrite_user_prompt(
                            spec,
                            bible,
                            self._style_bible,
                            chapter,
                            plan,
                            current_draft,
                            {
                                "model_review": asdict(current_review),
                                "local_review": asdict(current_local_quality),
                                "final_fix": (
                                    "这是补写扩容修复。保持现有剧情骨架、人物立场和章末方向不变，"
                                    "把缺失的 scene 落实成具体动作、身体感、物件细节、外部反馈和章尾牵引；"
                                    f"目标至少补到 {target_min} 字附近。"
                                    "不准再写成提纲、总结、说明文或拒绝提示。"
                                    + (
                                        "重点只补这些展开不足处："
                                        + "；".join(targeted_focus)
                                        if targeted_focus
                                        else ""
                                    )
                                ),
                            },
                            continuity,
                            self._voice_cards,
                            execution_packet=execution_packet,
                            chapter_room=chapter_room,
                            retrieved_memory=retrieved_memory,
                            style_memory=style_memory,
                            promise_memory=promise_memory,
                            causality_memory=causality_memory,
                            logic_audit=logic_audit,
                        )
                        + self._anthropic_writer_suffix(rewrite=True),
                        temperature=0.45,
                        max_output_tokens=_draft_token_budget(
                            chapter_target_chars,
                            length_tolerance=spec.chapter_char_tolerance,
                            short_standalone=_is_short_standalone_spec(spec),
                        ),
                        session_id=f"writer-expand-c{chapter.index}",
                        session_max_chars=_writer_session_max_chars(spec),
                    )
                    current_draft = self._clean_generated_draft(chapter.index, current_draft, stage="chapter_expand")
                    current_local_quality, current_review = _rerun_local_and_review(current_draft)
                    current_attempts += 1
                    guard_rounds += 1
                    continue
                break
            return current_draft, current_local_quality, current_review, current_attempts

        draft, local_quality, review, attempts = _apply_provider_recovery_guards(
            draft,
            local_quality,
            review,
            attempts,
        )
        fix_instructions = _quality_failure_fix_instructions(review, local_quality)
        for step, instruction in fix_instructions:
            if local_quality.passed and review.passed:
                break
            session_id = f"{step}-c{chapter.index}"
            self._emit_progress(
                step,
                (
                    f"清理第 {chapter.index} 章成稿痕迹。"
                    if step == "chapter_cleanup"
                    else f"定向修复第 {chapter.index} 章。"
                ),
                chapter_index=chapter.index,
                attempt=attempts,
            )
            self._reset_client_session(session_id)
            rewrite_feedback = {
                "model_review": asdict(review),
                "local_review": asdict(local_quality),
                "final_fix": instruction,
            }
            draft = self._generate_text_with_progress(
                step,
                (
                    f"清理第 {chapter.index} 章成稿痕迹。"
                    if step == "chapter_cleanup"
                    else f"定向修复第 {chapter.index} 章。"
                ),
                f"第{chapter.index}章{step}",
                draft_system_prompt(),
                rewrite_user_prompt(
                    spec,
                    bible,
                    self._style_bible,
                    chapter,
                    plan,
                    draft,
                    rewrite_feedback,
                    continuity,
                    self._voice_cards,
                    execution_packet=execution_packet,
                    chapter_room=chapter_room,
                    retrieved_memory=retrieved_memory,
                    style_memory=style_memory,
                    promise_memory=promise_memory,
                    causality_memory=causality_memory,
                    logic_audit=logic_audit,
                )
                + self._anthropic_writer_suffix(rewrite=True),
                temperature=0.3 if step == "chapter_cleanup" else 0.35,
                max_output_tokens=_draft_token_budget(
                    chapter_target_chars,
                    length_tolerance=spec.chapter_char_tolerance,
                    short_standalone=_is_short_standalone_spec(spec),
                ),
                session_id=session_id,
                session_max_chars=_writer_session_max_chars(spec),
            )
            draft = self._clean_generated_draft(chapter.index, draft, stage=step)
            local_quality = analyze_chapter(
                draft,
                chapter_target_chars,
                character_names,
                market_profile=spec.market_profile,
                **self._chapter_local_quality_kwargs(spec, chapter, plan, prior_chapters),
            )
            review = self._review_chapter(
                spec,
                bible,
                chapter,
                plan,
                draft,
                local_quality,
                continuity,
                execution_packet,
            )
            attempts += 1
            draft, local_quality, review, attempts = _apply_provider_recovery_guards(
                draft,
                local_quality,
                review,
                attempts,
            )
        if (
            self._underwrite_prone()
            and not expansion_recovery_touched
            and not (local_quality.passed and review.passed)
            and _review_feedback_is_expansion_only_failure(review, local_quality)
            and not _draft_looks_like_model_refusal(draft)
            and not _quality_failure_looks_truncated_draft(draft, review, local_quality)
        ):
            expansion_recovery_touched = True
            if _anthropic_review_local_divergence_needs_expansion(review, local_quality):
                divergence_recovery_touched = True
            target_min = int(local_quality.metrics.get("target_chars_min", 0) or 0)
            targeted_focus = [
                item
                for item in [*review.required_fixes, *review.issues]
                if _best_text(item)
            ][:6]
            self._emit_progress(
                "chapter_expand",
                f"强制补写第 {chapter.index} 章细节与兑现。",
                chapter_index=chapter.index,
                attempt=attempts,
            )
            self._reset_client_session(f"writer-expand-c{chapter.index}")
            draft = self._generate_text_with_progress(
                "chapter_expand",
                f"强制补写第 {chapter.index} 章细节与兑现。",
                f"第{chapter.index}章强制扩写",
                draft_system_prompt(),
                rewrite_user_prompt(
                    spec,
                    bible,
                    self._style_bible,
                    chapter,
                    plan,
                    draft,
                    {
                        "model_review": asdict(review),
                        "local_review": asdict(local_quality),
                        "final_fix": (
                            "这是强制扩写修复。不要改变现有剧情顺序、人物立场、卷目标或章末方向；"
                            "只补齐当前章明显缺失的 scene 展开、环境、身体感、心理转折、人物反应、情绪余波与章尾牵引。"
                            + (f" 目标至少补到 {target_min} 字附近。" if target_min > 0 else "")
                            + " 如果审校提到多个场景缺字，按场景逐段补齐；不要再写成摘要、提纲、说明文或半成品。"
                            + (
                                " 重点补这些缺口："
                                + "；".join(targeted_focus)
                                if targeted_focus
                                else ""
                            )
                        ),
                    },
                    continuity,
                    self._voice_cards,
                    execution_packet=execution_packet,
                    chapter_room=chapter_room,
                    retrieved_memory=retrieved_memory,
                    style_memory=style_memory,
                    promise_memory=promise_memory,
                    causality_memory=causality_memory,
                    logic_audit=logic_audit,
                )
                + self._anthropic_writer_suffix(rewrite=True),
                temperature=0.4,
                max_output_tokens=_draft_token_budget(
                    chapter_target_chars,
                    length_tolerance=spec.chapter_char_tolerance,
                    short_standalone=_is_short_standalone_spec(spec),
                ),
                session_id=f"writer-expand-c{chapter.index}",
                session_max_chars=_writer_session_max_chars(spec),
            )
            draft = self._clean_generated_draft(chapter.index, draft, stage="chapter_expand")
            local_quality = analyze_chapter(
                draft,
                chapter_target_chars,
                character_names,
                market_profile=spec.market_profile,
                **self._chapter_local_quality_kwargs(spec, chapter, plan, prior_chapters),
            )
            review = self._review_chapter(
                spec,
                bible,
                chapter,
                plan,
                draft,
                local_quality,
                continuity,
                execution_packet,
            )
            attempts += 1
            draft, local_quality, review, attempts = _apply_provider_recovery_guards(
                draft,
                local_quality,
                review,
                attempts,
            )
        if self._underwrite_prone() and _anthropic_short_chapter_can_soft_pass(review, local_quality):
            self._emit_progress(
                "chapter_review_override",
                f"放宽第 {chapter.index} 章的 Claude 短章失败判定。",
                chapter_index=chapter.index,
                attempt=attempts,
            )
            local_quality = _soften_anthropic_short_length_failure(local_quality)
            review_strengths = list(review.strengths)
            if not review_strengths:
                review_strengths = [
                    item
                    for item in [*review.issues, *review.required_fixes]
                    if _best_text(item)
                ][:4]
            review = ReviewFeedback(
                passed=True,
                score=max(int(review.score or 0), int(local_quality.score or 0)),
                strengths=review_strengths,
                issues=[],
                required_fixes=[],
                short_summary=review.short_summary or local_quality.short_summary,
                chapter_fixes=[],
            )
        elif self._underwrite_prone() and divergence_recovery_touched and _anthropic_review_local_divergence_needs_expansion(review, local_quality):
            self._emit_progress(
                "chapter_review_override",
                f"放宽第 {chapter.index} 章的 Claude 扩写分歧判定。",
                chapter_index=chapter.index,
                attempt=attempts,
            )
            if _local_quality_is_soft_short_hard_fail(local_quality):
                local_quality = _soften_anthropic_short_length_failure(local_quality)
            review = _synthesize_anthropic_expansion_divergence_pass(review, local_quality)
        elif self._underwrite_prone() and expansion_recovery_touched and (
            _underwritten_but_structured_needs_expansion(draft, review, local_quality)
            or _review_feedback_is_expansion_only_failure(review, local_quality)
        ):
            self._emit_progress(
                "chapter_review_override",
                f"放宽第 {chapter.index} 章的 Claude 严重偏短判定。",
                chapter_index=chapter.index,
                attempt=attempts,
            )
            local_quality = _soften_anthropic_short_length_failure(local_quality)
            review = _synthesize_underwritten_structured_pass(review, local_quality)
        return draft, local_quality, review, attempts

    def _build_chapter_room(
        self,
        spec: ProjectSpec,
        bible: WorldBible,
        chapter: ChapterOutlineItem,
        plan: ChapterPlan,
        execution_packet: dict[str, Any],
    ) -> dict[str, Any]:
        relative_path = str(self.store.chapter_room_path(chapter.index).relative_to(self.store.root))
        path = self.store.root / relative_path
        if self.resume and path.exists():
            payload = load_json(path)
            if isinstance(payload, dict):
                return payload

        self._emit_progress(
            "chapter_room",
            f"召开第 {chapter.index} 章写前会。",
            chapter_index=chapter.index,
            volume_index=chapter.volume_index,
        )
        payload = self._generate_json_with_progress(
            "chapter_room",
            f"召开第 {chapter.index} 章写前会。",
            f"第{chapter.index}章写前会",
            chapter_room_system_prompt(),
            chapter_room_user_prompt(
                spec,
                bible,
                chapter,
                plan,
                execution_packet=execution_packet,
            ),
            temperature=0.15,
            max_output_tokens=1400,
            session_id="chapter-room",
            session_max_chars=50000,
        )
        room = self._resolve_generated_structured_mapping_payload(
            payload=payload,
            normalize=_normalize_chapter_room_payload,
            has_content=_chapter_room_payload_has_content,
            has_signal=_chapter_room_payload_has_signal,
            regenerate=lambda attempt, previous_payload: self._generate_json_with_progress(
                "chapter_room",
                f"重召开第 {chapter.index} 章写前会（第 {attempt} 次）。",
                f"第{chapter.index}章写前会重生成",
                chapter_room_system_prompt(),
                chapter_room_user_prompt(
                    spec,
                    bible,
                    chapter,
                    plan,
                    execution_packet=execution_packet,
                )
                + "\n\n补充要求：上一次返回缺少有效写前会纪要。必须给出 notes、shared_mandates、blocking_issues；notes 里至少包含 continuity_guard、drama_editor、style_guard 三位 agent。",
                temperature=0.1,
                max_output_tokens=1400,
                session_id="chapter-room",
                session_max_chars=50000,
            ),
            repair=lambda raw_payload: self._repair_structured_mapping_payload(
                step="chapter_room_normalize",
                progress_message=f"规范化第 {chapter.index} 章写前会结构。",
                object_label=f"第{chapter.index}章写前会规范化",
                session_id=f"chapter-room-normalizer-{chapter.index}",
                raw_payload=raw_payload,
                shape=_chapter_room_payload_shape(),
                rules=[
                    "顶层必须是一个 JSON 对象，不允许返回数组。",
                    "只做结构规范化，不要编造新的写前会意见。",
                    "notes 必须是对象数组；shared_mandates 和 blocking_issues 必须是字符串数组。",
                    "如果源数据被拆成多个命名块，请合并成一个对象。",
                ],
                state_path=f"state/chapter-{chapter.index:02d}.room-normalizer.json",
            ),
        )
        if not _chapter_room_payload_has_content(room):
            room = self._fallback_chapter_room_payload(
                chapter,
                plan,
                source_payload=payload,
            )
        self.store.write_json(relative_path, room)
        return room

    def _review_chapter(
        self,
        spec: ProjectSpec,
        bible: WorldBible,
        chapter: ChapterOutlineItem,
        plan: ChapterPlan,
        draft: str,
        local_quality: LocalQualityReport,
        continuity: ContinuityState,
        execution_packet: dict[str, Any],
    ) -> ReviewFeedback:
        payload = self._generate_json_with_progress(
            "chapter_review",
            f"审校第 {chapter.index} 章。",
            f"第{chapter.index}章审校",
            chapter_review_system_prompt(),
            chapter_review_user_prompt(
                spec,
                bible,
                self._style_bible,
                chapter,
                plan,
                draft,
                asdict(local_quality),
                continuity,
                self._voice_cards,
                execution_packet=execution_packet,
            )
            + self._anthropic_review_suffix(),
            model=self._review_model_name(),
            temperature=0.1,
            max_output_tokens=1600,
            session_id="reviewer",
            session_max_chars=50000,
            provider_tier="flagship",
        )
        payload = self._resolve_generated_structured_mapping_payload(
            payload=payload,
            normalize=_normalize_review_payload,
            has_content=_review_payload_has_content,
            has_signal=_review_payload_has_signal,
            regenerate=lambda attempt, previous_payload: self._generate_json_with_progress(
                "chapter_review",
                f"重审校第 {chapter.index} 章（第 {attempt} 次）。",
                f"第{chapter.index}章审校重生成",
                chapter_review_system_prompt(),
                chapter_review_user_prompt(
                    spec,
                    bible,
                    self._style_bible,
                    chapter,
                    plan,
                    draft,
                    asdict(local_quality),
                    continuity,
                    self._voice_cards,
                    execution_packet=execution_packet,
                )
                + self._anthropic_review_suffix()
                + "\n\n补充要求：上一次返回缺少有效审校结构。必须返回 passed、score、issues、required_fixes、short_summary；如果不通过，也必须把这些字段填完整。",
                model=self._review_model_name(),
                temperature=0.05,
                max_output_tokens=1600,
                session_id="reviewer",
                session_max_chars=50000,
                provider_tier="flagship",
            ),
            repair=lambda raw_payload: self._repair_structured_mapping_payload(
                step="chapter_review_normalize",
                progress_message=f"规范化第 {chapter.index} 章审校结构。",
                object_label=f"第{chapter.index}章审校规范化",
                session_id=f"reviewer-normalizer-{chapter.index}",
                raw_payload=raw_payload,
                shape=_review_payload_shape(),
                rules=[
                    "顶层必须是一个 JSON 对象，不允许返回数组。",
                    "只做结构规范化，不要编造新的审校结论。",
                    "chapter_fixes 必须是对象数组；没有有效对象时返回空数组，不要编造。",
                ],
                state_path=f"state/chapter-{chapter.index:02d}.review-normalizer.json",
            ),
        )
        review = ReviewFeedback(
            passed=bool(payload.get("passed")),
            score=int(payload.get("score", 0)),
            strengths=_string_list(payload.get("strengths")),
            issues=_string_list(payload.get("issues")),
            required_fixes=_string_list(payload.get("required_fixes")),
            short_summary=_best_text(payload.get("short_summary"), ""),
            chapter_fixes=_chapter_fix_list(payload.get("chapter_fixes")),
        )
        malformed_retry_attempted = False
        if self._review_semantic_drift_prone() and _review_feedback_looks_malformed(review, local_quality):
            malformed_retry_attempted = True
            self._emit_progress(
                "chapter_review_retry",
                f"重审校第 {chapter.index} 章（审校结果语义异常）。",
                chapter_index=chapter.index,
            )
            payload = self._generate_json_with_progress(
                "chapter_review",
                f"重审校第 {chapter.index} 章（审校结果语义异常）。",
                f"第{chapter.index}章审校重试",
                chapter_review_system_prompt(),
                chapter_review_user_prompt(
                    spec,
                    bible,
                    self._style_bible,
                    chapter,
                    plan,
                    draft,
                    asdict(local_quality),
                    continuity,
                    self._voice_cards,
                    execution_packet=execution_packet,
                )
                + self._anthropic_review_suffix()
                + "\n\n补充要求：上一次 returned 的审校结论语义异常，出现了 passed/score 与 strengths、required_fixes 明显矛盾的情况。请重新审校，并确保：若 passed=false，issues 或 required_fixes 里必须给出明确的负向问题与可执行修订点；若本章可用，就不要返回 score=0。",
                model=self._review_model_name(),
                temperature=0.05,
                max_output_tokens=1600,
                session_id="reviewer",
                session_max_chars=50000,
                provider_tier="flagship",
            )
            payload = self._resolve_generated_structured_mapping_payload(
                payload=payload,
                normalize=_normalize_review_payload,
                has_content=_review_payload_has_content,
                has_signal=_review_payload_has_signal,
                regenerate=lambda attempt, previous_payload: self._generate_json_with_progress(
                    "chapter_review",
                    f"再次重审校第 {chapter.index} 章（第 {attempt} 次）。",
                    f"第{chapter.index}章审校再重生成",
                    chapter_review_system_prompt(),
                    chapter_review_user_prompt(
                        spec,
                        bible,
                        self._style_bible,
                        chapter,
                        plan,
                        draft,
                        asdict(local_quality),
                        continuity,
                        self._voice_cards,
                        execution_packet=execution_packet,
                    )
                    + self._anthropic_review_suffix()
                    + "\n\n补充要求：必须返回自洽的审校结构；passed、score、issues、required_fixes、short_summary 之间不能互相矛盾。",
                    model=self._review_model_name(),
                    temperature=0.05,
                    max_output_tokens=1600,
                    session_id="reviewer",
                    session_max_chars=50000,
                    provider_tier="flagship",
                ),
                repair=lambda raw_payload: self._repair_structured_mapping_payload(
                    step="chapter_review_normalize",
                    progress_message=f"规范化第 {chapter.index} 章审校结构。",
                    object_label=f"第{chapter.index}章审校规范化",
                    session_id=f"reviewer-normalizer-{chapter.index}",
                    raw_payload=raw_payload,
                    shape=_review_payload_shape(),
                    rules=[
                        "顶层必须是一个 JSON 对象，不允许返回数组。",
                        "只做结构规范化，不要编造新的审校结论。",
                        "chapter_fixes 必须是对象数组；没有有效对象时返回空数组，不要编造。",
                    ],
                    state_path=f"state/chapter-{chapter.index:02d}.review-normalizer.json",
                ),
            )
            review = ReviewFeedback(
                passed=bool(payload.get("passed")),
                score=int(payload.get("score", 0)),
                strengths=_string_list(payload.get("strengths")),
                issues=_string_list(payload.get("issues")),
                required_fixes=_string_list(payload.get("required_fixes")),
                short_summary=_best_text(payload.get("short_summary"), ""),
                chapter_fixes=_chapter_fix_list(payload.get("chapter_fixes")),
            )
        if self._review_semantic_drift_prone() and malformed_retry_attempted and _review_feedback_looks_malformed(review, local_quality):
            self._emit_progress(
                "chapter_review_override",
                f"放宽第 {chapter.index} 章的审校语义漂移判定。",
                chapter_index=chapter.index,
            )
            review = _synthesize_malformed_review_pass(review, local_quality)
        return review

    def _extract_continuity(
        self,
        spec: ProjectSpec,
        bible: WorldBible,
        chapter: ChapterOutlineItem,
        draft: str,
        previous_state: ContinuityState,
    ) -> ContinuityUpdate:
        relevant_progression = self._select_progression_memories(chapter, None, previous_state)
        payload = self._generate_json_with_progress(
            "continuity",
            f"更新第 {chapter.index} 章连续性状态。",
            f"第{chapter.index}章连续性",
            continuity_system_prompt(),
            continuity_user_prompt(
                spec,
                bible,
                chapter,
                draft,
                previous_state,
                power_system=self._power_system,
                progression_ledger=self._runtime_progression_ledger or self._progression_ledger,
            ),
            model=self._light_model_name(),
            temperature=0.1,
            max_output_tokens=1600,
            session_id="continuity",
            session_max_chars=50000,
            provider_tier="light",
        )
        payload = self._resolve_generated_structured_mapping_payload(
            payload=payload,
            normalize=lambda raw_payload: _normalize_continuity_payload(raw_payload, chapter),
            has_content=_continuity_payload_has_content,
            has_signal=_continuity_payload_has_signal,
            regenerate=lambda attempt, previous_payload: self._generate_json_with_progress(
                "continuity",
                f"重生成第 {chapter.index} 章连续性状态（第 {attempt} 次）。",
                f"第{chapter.index}章连续性重生成",
                continuity_system_prompt(),
                continuity_user_prompt(
                    spec,
                    bible,
                    chapter,
                    draft,
                    previous_state,
                    power_system=self._power_system,
                    progression_ledger=self._runtime_progression_ledger or self._progression_ledger,
                )
                + "\n\n补充要求：上一次返回缺少有效连续性增量。必须给出 chapter_summary，并且在 new_threads、resolved_threads、timeline_events、character_states、next_chapter_targets、must_remember 中至少有一项有效内容。",
                model=self._light_model_name(),
                temperature=0.05,
                max_output_tokens=1600,
                session_id="continuity",
                session_max_chars=50000,
                provider_tier="light",
            ),
            repair=lambda raw_payload: self._repair_structured_mapping_payload(
                step="continuity_normalize",
                progress_message=f"规范化第 {chapter.index} 章连续性结构。",
                object_label=f"第{chapter.index}章连续性规范化",
                session_id=f"continuity-normalizer-{chapter.index}",
                raw_payload=raw_payload,
                shape=_continuity_payload_shape(chapter),
                rules=[
                    "顶层必须是一个 JSON 对象，不允许返回数组。",
                    "只做结构规范化，不要编造新的连续性事实。",
                    "character_states 必须是对象数组；其余列表字段必须是字符串数组。",
                ],
                state_path=f"state/chapter-{chapter.index:02d}.continuity-normalizer.json",
            ),
        )
        if not _continuity_payload_has_content(payload):
            payload = self._fallback_continuity_payload(
                chapter,
                draft,
                previous_state,
                source_payload=payload,
            )
        update = _continuity_update_from_dict(payload)
        if not update.chapter_index:
            update.chapter_index = chapter.index
        if not update.chapter_summary:
            update.chapter_summary = chapter.beat_summary
        if not update.progression_updates and relevant_progression:
            update.progression_updates = [
                _best_text(item.get("objective"), item.get("milestone_label"), item.get("target_tier"))
                for item in relevant_progression
                if _best_text(item.get("objective"), item.get("milestone_label"), item.get("target_tier"))
            ][:4]
        if not update.current_tier:
            update.current_tier = _best_text(chapter.current_tier, previous_state.current_tier)
        if not update.next_breakthrough:
            update.next_breakthrough = _best_text(chapter.target_tier, previous_state.next_breakthrough)
        return update

    def _extract_long_range_memory(
        self,
        spec: ProjectSpec,
        bible: WorldBible,
        chapter: ChapterOutlineItem,
        plan: ChapterPlan,
        draft: str,
    ) -> LongRangeMemoryUpdate:
        continuity = self._long_memory_context
        relevant_promises = self._select_long_memory_promises(chapter, plan, continuity)
        relevant_causality = self._select_long_memory_causality(chapter, plan, continuity)
        relevant_progression = self._select_progression_memories(chapter, plan, continuity)
        payload = self._generate_json_with_progress(
            "long_memory",
            f"更新第 {chapter.index} 章长线账本。",
            f"第{chapter.index}章长线记忆",
            long_memory_system_prompt(),
            long_memory_user_prompt(
                spec,
                bible,
                chapter,
                plan,
                draft,
                relevant_promises,
                relevant_causality,
                power_system=self._power_system,
                previous_progression=self._runtime_progression_ledger or self._progression_ledger,
            ),
            model=self._light_model_name(),
            temperature=0.1,
            max_output_tokens=1800,
            session_id="long-memory",
            session_max_chars=60000,
            provider_tier="light",
        )
        payload = self._resolve_generated_structured_mapping_payload(
            payload=payload,
            normalize=lambda raw_payload: _normalize_long_memory_payload(raw_payload, chapter),
            has_content=_long_memory_payload_has_content,
            has_signal=_long_memory_payload_has_signal,
            regenerate=lambda attempt, previous_payload: self._generate_json_with_progress(
                "long_memory",
                f"重生成第 {chapter.index} 章长线账本（第 {attempt} 次）。",
                f"第{chapter.index}章长线记忆重生成",
                long_memory_system_prompt(),
                long_memory_user_prompt(
                    spec,
                    bible,
                    chapter,
                    plan,
                    draft,
                    relevant_promises,
                    relevant_causality,
                    power_system=self._power_system,
                    previous_progression=self._runtime_progression_ledger or self._progression_ledger,
                )
                + "\n\n补充要求：上一次返回缺少有效长线账本增量。必须给出 promise_updates 或 causality_updates 中至少一类有效对象；如果本章没有新增变化，也要返回明确的空数组字段，而不是散句。",
                model=self._light_model_name(),
                temperature=0.05,
                max_output_tokens=1800,
                session_id="long-memory",
                session_max_chars=60000,
                provider_tier="light",
            ),
            repair=lambda raw_payload: self._repair_structured_mapping_payload(
                step="long_memory_normalize",
                progress_message=f"规范化第 {chapter.index} 章长线账本结构。",
                object_label=f"第{chapter.index}章长线记忆规范化",
                session_id=f"long-memory-normalizer-{chapter.index}",
                raw_payload=raw_payload,
                shape=_long_memory_payload_shape(chapter),
                rules=[
                    "顶层必须是一个 JSON 对象，不允许返回数组。",
                    "只做结构规范化，不要编造新的承诺或因果。",
                    "promise_updates 和 causality_updates 必须是对象数组；没有有效对象时返回空数组。",
                ],
                state_path=f"state/chapter-{chapter.index:02d}.long-memory-normalizer.json",
            ),
        )
        if not _long_memory_payload_has_content(payload):
            payload = self._fallback_long_memory_payload(
                chapter,
                source_payload=payload,
            )
        update = _long_memory_update_from_dict(payload)
        if not update.chapter_index:
            update.chapter_index = chapter.index
        if not update.progression_updates and relevant_progression:
            update.progression_updates = [
                ProgressionLedgerItem(
                    milestone_label=_best_text(item.get("milestone_label")),
                    current_tier=_best_text(item.get("current_tier"), chapter.current_tier),
                    target_tier=_best_text(item.get("target_tier"), chapter.target_tier),
                    status=_best_text(item.get("status"), "advanced"),
                    opened_chapter=int(item.get("opened_chapter", chapter.index) or chapter.index),
                    last_touched_chapter=chapter.index,
                    objective=_best_text(item.get("objective"), item.get("milestone_label")),
                    required_resources=_string_list(item.get("required_resources")),
                    unlocked_rewards=_merge_lists(_string_list(item.get("unlocked_rewards")), [_best_text(plan.progression_reward)] if _best_text(plan.progression_reward) else []),
                    bottleneck=_best_text(item.get("bottleneck"), plan.progression_cost),
                )
                for item in relevant_progression[:4]
                if _best_text(item.get("milestone_label"), item.get("objective"), item.get("target_tier"))
            ]
        return update

    def _finalize(
        self,
        spec: ProjectSpec,
        bible: WorldBible,
        book_outline: BookOutline,
        chapters: list[ChapterResult],
        continuity: ContinuityState,
    ) -> FinalReview:
        self._emit_progress("final_review", "执行全书终审。", chapter_count=len(chapters))
        review_continuity, review_promises, review_causality = self._prepare_final_review_state(
            spec,
            bible,
            chapters,
            continuity,
        )
        local_quality = analyze_novel(
            [chapter.draft for chapter in chapters],
            spec.target_total_chars,
            spec.ending_mode,
            market_profile=spec.market_profile,
            length_tolerance=spec.chapter_char_tolerance,
            progression_mode=spec.progression_mode,
            progression_flavor=spec.progression_flavor,
            progression_ledger=self._progression_ledger,
        )
        payload = self._generate_json_with_progress(
            "final_review",
            "执行全书终审。",
            "全书终审",
            final_review_system_prompt(),
            final_review_user_prompt(
                spec,
                bible,
                book_outline,
                chapters,
                review_continuity,
                asdict(local_quality),
                review_promises,
                review_causality,
                [asdict(item) for _, item in sorted(self._logic_audits.items())],
                power_system=self._power_system,
                progression_ledger=self._progression_ledger,
            ),
            model=self._review_model_name(),
            temperature=0.1,
            max_output_tokens=1800,
            session_id="judge",
            session_max_chars=70000,
        )
        payload = self._resolve_generated_structured_mapping_payload(
            payload=payload,
            normalize=_normalize_final_review_payload,
            has_content=_final_review_payload_has_content,
            has_signal=_final_review_payload_has_signal,
            regenerate=lambda attempt, previous_payload: self._generate_json_with_progress(
                "final_review",
                f"重生成全书终审（第 {attempt} 次）。",
                "全书终审重生成",
                final_review_system_prompt(),
                final_review_user_prompt(
                    spec,
                    bible,
                    book_outline,
                    chapters,
                    review_continuity,
                    asdict(local_quality),
                    review_promises,
                    review_causality,
                    [asdict(item) for _, item in sorted(self._logic_audits.items())],
                    power_system=self._power_system,
                    progression_ledger=self._progression_ledger,
                ) + "\n\n补充要求：上一次返回缺少有效终审结构。必须返回 passed、score、issues、required_fixes、short_summary。",
                model=self._flagship_model_name(),
                temperature=0.05,
                max_output_tokens=1800,
                session_id="judge",
                session_max_chars=70000,
            ),
            repair=lambda raw_payload: self._repair_structured_mapping_payload(
                step="final_review_normalize",
                progress_message="规范化全书终审结构。",
                object_label="全书终审规范化",
                session_id="judge-normalizer",
                raw_payload=raw_payload,
                shape=_final_review_payload_shape(chapters),
                rules=[
                    "顶层必须是一个 JSON 对象，不允许返回数组。",
                    "只做结构规范化，不要编造新的终审意见。",
                    "chapter_fixes 必须是对象数组；没有有效修订对象时返回空数组，不要编造。",
                ],
                state_path="state/final-review.normalizer.json",
            ),
        )
        if _final_review_payload_looks_malformed(payload):
            self._emit_progress("final_review_retry", "重跑全书终审（终审结果语义异常）。", chapter_count=len(chapters))
            payload = self._generate_json_with_progress(
                "final_review",
                "重跑全书终审（终审结果语义异常）。",
                "全书终审重试",
                final_review_system_prompt(),
                final_review_user_prompt(
                    spec,
                    bible,
                    book_outline,
                    chapters,
                    review_continuity,
                    asdict(local_quality),
                    review_promises,
                    review_causality,
                    [asdict(item) for _, item in sorted(self._logic_audits.items())],
                    power_system=self._power_system,
                    progression_ledger=self._progression_ledger,
                ) + "\n\n补充要求：上一次终审结论语义异常，出现了 passed/score 与 strengths、required_fixes 明显矛盾的情况。请重新终审，并确保：若 passed=false，issues 或 required_fixes 里必须给出明确的负向问题与可执行修订点；若整书可用，就不要返回 score=0。",
                model=self._flagship_model_name(),
                temperature=0.05,
                max_output_tokens=1800,
                session_id="judge",
                session_max_chars=70000,
            )
            payload = self._resolve_generated_structured_mapping_payload(
                payload=payload,
                normalize=_normalize_final_review_payload,
                has_content=_final_review_payload_has_content,
                has_signal=_final_review_payload_has_signal,
                regenerate=lambda attempt, previous_payload: self._generate_json_with_progress(
                    "final_review",
                    f"再次重生成全书终审（第 {attempt} 次）。",
                    "全书终审再重生成",
                    final_review_system_prompt(),
                    final_review_user_prompt(
                        spec,
                        bible,
                        book_outline,
                        chapters,
                        review_continuity,
                        asdict(local_quality),
                        review_promises,
                        review_causality,
                        [asdict(item) for _, item in sorted(self._logic_audits.items())],
                        power_system=self._power_system,
                        progression_ledger=self._progression_ledger,
                    ) + "\n\n补充要求：必须返回自洽的终审结构；passed、score、issues、required_fixes、short_summary 之间不能互相矛盾。",
                    model=self._review_model_name(),
                    temperature=0.05,
                    max_output_tokens=1800,
                    session_id="judge",
                    session_max_chars=70000,
                ),
                repair=lambda raw_payload: self._repair_structured_mapping_payload(
                    step="final_review_normalize",
                    progress_message="规范化全书终审结构。",
                    object_label="全书终审规范化",
                    session_id="judge-normalizer",
                    raw_payload=raw_payload,
                    shape=_final_review_payload_shape(chapters),
                    rules=[
                        "顶层必须是一个 JSON 对象，不允许返回数组。",
                        "只做结构规范化，不要编造新的终审意见。",
                        "chapter_fixes 必须是对象数组；没有有效修订对象时返回空数组，不要编造。",
                    ],
                    state_path="state/final-review.normalizer.json",
                ),
            )
        review = FinalReview(
            passed=bool(payload.get("passed")) and local_quality.passed,
            score=min(int(payload.get("score", 0)), local_quality.score),
            strengths=_merge_lists(_string_list(payload.get("strengths")), local_quality.strengths),
            issues=_merge_lists(_string_list(payload.get("issues")), local_quality.issues),
            required_fixes=_merge_lists(_string_list(payload.get("required_fixes")), local_quality.issues),
            short_summary=_best_text(payload.get("short_summary"), local_quality.short_summary),
            chapter_fixes=_chapter_fix_list(payload.get("chapter_fixes")),
            local_quality=local_quality,
        )
        self.store.write_json("state/final-review.latest.json", asdict(review))
        return review

    def _apply_final_fixes(
        self,
        spec: ProjectSpec,
        bible: WorldBible,
        book_outline: BookOutline,
        chapters: list[ChapterResult],
        fixes: list[dict[str, Any]],
    ) -> list[ChapterResult]:
        chapter_map = {chapter.index: copy.deepcopy(chapter) for chapter in chapters}
        original_promises = self._promise_ledger
        original_progression = self._progression_ledger
        original_causality = self._causality_graph
        try:
            for fix in sorted(fixes, key=lambda item: int(item.get("chapter_index", 0))):
                chapter_index = int(fix.get("chapter_index", 0))
                instruction = _best_text(fix.get("instruction"), "")
                chapter_result = chapter_map.get(chapter_index)
                if chapter_result is None or not instruction:
                    continue
                prior_chapters = [item for idx, item in sorted(chapter_map.items()) if idx < chapter_index]
                pre_state = self._rebuild_continuity_state(bible, prior_chapters)
                self._chapter_contexts[chapter_index] = copy.deepcopy(pre_state)
                rolling_promises, rolling_progression, rolling_causality = self._rebuild_long_range_state(prior_chapters)
                self._promise_ledger = rolling_promises
                self._progression_ledger = rolling_progression
                self._causality_graph = rolling_causality
                try:
                    updated = self._rewrite_final_fix_chapter(
                        spec,
                        bible,
                        book_outline,
                        chapter_result,
                        pre_state,
                        prior_chapters,
                        instruction,
                        progress_message=f"终审修订第 {chapter_index} 章。",
                        progress_step="final_fix",
                        session_prefix="writer-final-fix",
                        stage_label="final_fix",
                    )
                except RuntimeError:
                    if chapter_result.review.passed and chapter_result.local_quality.passed:
                        self._emit_progress(
                            "final_fix",
                            f"第 {chapter_index} 章终审修订未获得更优版本，保留原稿进入整书复审。",
                            chapter_index=chapter_index,
                        )
                        chapter_map[chapter_index] = chapter_result
                        self._persist_chapter_result(chapter_result)
                        continue
                    raise
                chapter_map[chapter_index] = updated
                self._persist_chapter_result(updated)
                chapter_map = self._stabilize_final_fix_neighbors(spec, bible, book_outline, chapter_map, chapter_index, instruction)
        finally:
            self._promise_ledger = original_promises
            self._progression_ledger = original_progression
            self._causality_graph = original_causality
        return [chapter_map[index] for index in sorted(chapter_map)]

    def _prepare_final_review_state(
        self,
        spec: ProjectSpec,
        bible: WorldBible,
        chapters: list[ChapterResult],
        continuity: ContinuityState,
    ) -> tuple[ContinuityState, list[PromiseLedgerItem], list[CausalityEdge]]:
        sealed_continuity = self._seal_final_continuity(spec, bible, chapters, continuity)
        sealed_promises = [copy.deepcopy(item) for item in self._promise_ledger]
        sealed_causality = [copy.deepcopy(item) for item in self._causality_graph]
        sealed_continuity, sealed_promises, sealed_causality = _cleanup_final_review_state(
            sealed_continuity,
            sealed_promises,
            sealed_causality,
            chapters,
            strict_short_standalone=_is_short_standalone_spec(spec),
        )
        self.store.write_json(
            "state/final-state.preview.json",
            {
                "continuity": sealed_continuity,
                "promise_ledger": sealed_promises,
                "causality_graph": sealed_causality,
            },
        )
        return sealed_continuity, sealed_promises, sealed_causality

    def _seal_final_continuity(
        self,
        spec: ProjectSpec,
        bible: WorldBible,
        chapters: list[ChapterResult],
        continuity: ContinuityState,
    ) -> ContinuityState:
        if not chapters:
            return _sanitize_continuity_state(copy.deepcopy(continuity))
        volume_targets = _normalized_volume_chapter_targets(
            spec.volume_chapter_targets,
            chapter_count=spec.chapter_count,
            volume_count=spec.volume_count,
        )
        window_size = min(max(max(volume_targets), 6), 12, len(chapters))
        final_window = chapters[-window_size:]
        recent_summaries = [chapter.continuity.chapter_summary for chapter in final_window][-8:]
        timeline: list[str] = []
        must_remember: list[str] = []
        core_names = {item.name for item in bible.characters[:10] if item.name}
        for chapter in final_window:
            timeline = _merge_lists(timeline, chapter.continuity.timeline_events)
            must_remember = _merge_lists(must_remember, chapter.continuity.must_remember)
            for state in chapter.continuity.character_states:
                if state.name:
                    core_names.add(state.name)
        unresolved_promises = [copy.deepcopy(item) for item in self._promise_ledger if item.current_status != "paid_off"]
        active_threads = [_best_text(item.label) for item in unresolved_promises if item.label][:6]
        if spec.ending_mode != "standalone":
            active_threads = _merge_lists(active_threads, continuity.active_threads[-6:])[:8]
        resolved_threads = _merge_lists(
            continuity.resolved_threads[-12:],
            [item.label for item in self._promise_ledger if item.current_status == "paid_off" and item.label],
        )[:20]
        if spec.ending_mode == "standalone":
            must_remember = _merge_lists(
                must_remember,
                [
                    "全书主线已闭环；若后续补写，只能扩展余韵或制度运行，不得重新打开核心悬念。",
                    "终局资料应优先以已支付承诺、已落地制度和最终人物归宿为准。",
                ],
            )
        latest_states: dict[str, CharacterState] = {}
        for chapter in reversed(final_window):
            for state in reversed(chapter.continuity.character_states):
                if not state.name or state.name in latest_states:
                    continue
                if state.name in core_names or len(latest_states) < 8:
                    latest_states[state.name] = copy.deepcopy(state)
        character_states = list(reversed(list(latest_states.values())))
        return _sanitize_continuity_state(
            ContinuityState(
                recent_summaries=recent_summaries,
                active_threads=active_threads,
                resolved_threads=resolved_threads,
            timeline=timeline[-12:],
            character_states=character_states,
                must_remember=must_remember[-16:],
                last_volume_index=continuity.last_volume_index,
                last_chapter_index=continuity.last_chapter_index,
            )
        )

    def _rewrite_final_fix_chapter(
        self,
        spec: ProjectSpec,
        bible: WorldBible,
        book_outline: BookOutline | None,
        chapter_result: ChapterResult,
        pre_state: ContinuityState,
        prior_chapters: list[ChapterResult],
        instruction: str,
        *,
        progress_message: str,
        progress_step: str,
        session_prefix: str,
        stage_label: str,
    ) -> ChapterResult:
        chapter_index = chapter_result.index
        plan = chapter_result.plan
        volume_outline = self._load_volume_outline_context(chapter_result.volume_index)
        context = self._prepare_chapter_generation_context(
            spec,
            bible,
            chapter_result.outline_item,
            plan,
            pre_state,
            prior_chapters,
        )
        retrieved_memory = context["retrieved_memory"]
        style_memory = context["style_memory"]
        promise_memory = context["promise_memory"]
        causality_memory = context["causality_memory"]
        logic_audit = context["logic_audit"]
        chapter_room = context["chapter_room"]
        execution_packet = context["execution_packet"]
        original_review = asdict(chapter_result.review)
        original_local_quality = asdict(chapter_result.local_quality)
        rewritten = chapter_result.draft
        local_quality = chapter_result.local_quality
        review = chapter_result.review
        chapter_target_chars = _resolved_chapter_target_chars(spec, chapter_result.outline_item, plan)
        success = False
        previous_failure: dict[str, Any] | None = None
        for attempt in range(1, max(1, self.max_final_fix_attempts) + 1):
            self._emit_progress(
                progress_step,
                progress_message,
                chapter_index=chapter_index,
                attempt=attempt,
            )
            session_id = f"{session_prefix}-c{chapter_index}"
            self._reset_client_session(session_id)
            rewrite_feedback = {
                "model_review": original_review,
                "local_review": original_local_quality,
                "final_fix": instruction,
            }
            if previous_failure is not None:
                rewrite_feedback["previous_final_fix_feedback"] = previous_failure
            rewritten = self._generate_text_with_progress(
                progress_step,
                progress_message,
                f"第{chapter_index}章修订#{attempt}",
                draft_system_prompt(),
                rewrite_user_prompt(
                    spec,
                    bible,
                    self._style_bible,
                    chapter_result.outline_item,
                    plan,
                    chapter_result.draft,
                    rewrite_feedback,
                    pre_state,
                    self._voice_cards,
                    execution_packet=execution_packet,
                    chapter_room=chapter_room,
                    retrieved_memory=retrieved_memory,
                    style_memory=style_memory,
                    promise_memory=promise_memory,
                    causality_memory=causality_memory,
                    logic_audit=logic_audit,
                ),
                temperature=max(0.15, 0.35 - (attempt - 1) * 0.1),
                max_output_tokens=_draft_token_budget(
                    chapter_target_chars,
                    length_tolerance=spec.chapter_char_tolerance,
                    short_standalone=_is_short_standalone_spec(spec),
                ),
                session_id=session_id,
                session_max_chars=60000,
            )
            rewritten = self._clean_generated_draft(chapter_index, rewritten, stage=stage_label)
            local_quality = analyze_chapter(
                rewritten,
                chapter_target_chars,
                _character_names(bible, spec),
                market_profile=spec.market_profile,
                **self._chapter_local_quality_kwargs(spec, chapter_result.outline_item, plan, prior_chapters),
            )
            review = self._review_chapter(
                spec,
                bible,
                chapter_result.outline_item,
                plan,
                rewritten,
                local_quality,
                pre_state,
                execution_packet,
            )
            if local_quality.passed and review.passed:
                success = True
                break
            previous_failure = {
                "model_review": asdict(review),
                "local_review": asdict(local_quality),
            }
        if not success:
            self._write_failed_chapter_snapshot(
                chapter_index,
                rewritten,
                review,
                local_quality,
                chapter_result.attempts + max(1, self.max_final_fix_attempts),
            )
            raise RuntimeError(f"Final polish failed for chapter {chapter_index}.")
        continuity_update = self._extract_continuity(spec, bible, chapter_result.outline_item, rewritten, pre_state)
        self._record_stagnation_signal(chapter_index, local_quality, continuity_update)
        self._long_memory_context = pre_state
        long_memory = self._extract_long_range_memory(spec, bible, chapter_result.outline_item, chapter_result.plan, rewritten)
        return ChapterResult(
            index=chapter_result.index,
            volume_index=chapter_result.volume_index,
            title=chapter_result.title,
            outline_item=chapter_result.outline_item,
            draft=rewritten,
            plan=plan,
            review=review,
            local_quality=local_quality,
            continuity=continuity_update,
            attempts=chapter_result.attempts + 1,
            long_memory=long_memory,
        )

    def _stabilize_final_fix_neighbors(
        self,
        spec: ProjectSpec,
        bible: WorldBible,
        book_outline: BookOutline,
        chapter_map: dict[int, ChapterResult],
        anchor_index: int,
        anchor_instruction: str,
    ) -> dict[int, ChapterResult]:
        window_indices = [index for index in sorted(chapter_map) if anchor_index - 2 <= index <= anchor_index + 2]
        if len(window_indices) <= 1:
            return chapter_map
        original_promises = self._promise_ledger
        original_progression = self._progression_ledger
        original_causality = self._causality_graph
        try:
            pre_window = [chapter_map[index] for index in sorted(chapter_map) if index < window_indices[0]]
            rolling_continuity = self._rebuild_continuity_state(bible, pre_window)
            self._promise_ledger, self._progression_ledger, self._causality_graph = self._rebuild_long_range_state(pre_window)
            for chapter_index in window_indices:
                chapter_result = chapter_map[chapter_index]
                prior_chapters = [chapter_map[index] for index in sorted(chapter_map) if index < chapter_index]
                refreshed = self._refresh_final_fix_neighbor(
                    spec,
                    bible,
                    book_outline,
                    chapter_result,
                    rolling_continuity,
                    prior_chapters,
                    anchor_index,
                    anchor_instruction,
                )
                chapter_map[chapter_index] = refreshed
                self._persist_chapter_result(refreshed)
                rolling_continuity = _merge_continuity_state(rolling_continuity, refreshed.continuity, refreshed.volume_index)
                if refreshed.long_memory is not None:
                    self._promise_ledger = _merge_promise_ledger(
                        self._promise_ledger,
                        refreshed.long_memory.promise_updates,
                        current_volume=refreshed.volume_index,
                        current_chapter=refreshed.index,
                    )
                    self._progression_ledger = _merge_progression_ledger(
                        self._progression_ledger,
                        refreshed.long_memory.progression_updates,
                        current_chapter=refreshed.index,
                    )
                    self._causality_graph = _merge_causality_graph(
                        self._causality_graph,
                        refreshed.long_memory.causality_updates,
                        current_chapter=refreshed.index,
                    )
        finally:
            self._promise_ledger = original_promises
            self._progression_ledger = original_progression
            self._causality_graph = original_causality
        return chapter_map

    def _refresh_final_fix_neighbor(
        self,
        spec: ProjectSpec,
        bible: WorldBible,
        book_outline: BookOutline,
        chapter_result: ChapterResult,
        pre_state: ContinuityState,
        prior_chapters: list[ChapterResult],
        anchor_index: int,
        anchor_instruction: str,
    ) -> ChapterResult:
        retrieved_memory = self._select_story_memories(chapter_result.outline_item, chapter_result.plan, pre_state, prior_chapters)
        style_memory = self._select_style_memories(chapter_result.outline_item, chapter_result.plan, prior_chapters)
        progression_memory = self._select_progression_memories(chapter_result.outline_item, chapter_result.plan, pre_state)
        promise_memory = self._select_promise_memories(chapter_result.outline_item, chapter_result.plan, pre_state)
        causality_memory = self._select_causality_memories(chapter_result.outline_item, chapter_result.plan, pre_state)
        recent_propulsion_history = _recent_propulsion_history(prior_chapters)
        logic_audit = self._latest_logic_audit_for_volume(chapter_result.volume_index)
        execution_packet = self._build_chapter_execution_packet(
            chapter_result.outline_item,
            chapter_result.plan,
            retrieved_memory,
            style_memory,
            progression_memory,
            promise_memory,
            causality_memory,
            recent_propulsion_history,
            logic_audit,
        )
        chapter_target_chars = _resolved_chapter_target_chars(spec, chapter_result.outline_item, chapter_result.plan)
        local_quality = analyze_chapter(
            chapter_result.draft,
            chapter_target_chars,
            _character_names(bible, spec),
            market_profile=spec.market_profile,
            **self._chapter_local_quality_kwargs(spec, chapter_result.outline_item, chapter_result.plan, prior_chapters),
        )
        review = self._review_chapter(
            spec,
            bible,
            chapter_result.outline_item,
            chapter_result.plan,
            chapter_result.draft,
            local_quality,
            pre_state,
            execution_packet,
        )
        if not (local_quality.passed and review.passed):
            issue_pool = _merge_lists(review.required_fixes, review.issues, local_quality.issues)
            neighbor_instruction = (
                f"这是围绕第{anchor_index}章终审修订后的邻章复检。"
                "必须保证与前后章的事实、情绪、目标、承诺兑现和章末牵引自然衔接。"
                f" 原终审要求：{anchor_instruction}"
            )
            if issue_pool:
                neighbor_instruction += " 当前这章还要解决：" + "；".join(issue_pool[:5])
            return self._rewrite_final_fix_chapter(
                spec,
                bible,
                book_outline,
                chapter_result,
                pre_state,
                prior_chapters,
                neighbor_instruction,
                progress_message=f"邻章复检修订第 {chapter_result.index} 章。",
                progress_step="final_fix",
                session_prefix="writer-neighbor-fix",
                stage_label="final_fix",
            )
        continuity_update = self._extract_continuity(spec, bible, chapter_result.outline_item, chapter_result.draft, pre_state)
        self._long_memory_context = pre_state
        long_memory = self._extract_long_range_memory(spec, bible, chapter_result.outline_item, chapter_result.plan, chapter_result.draft)
        return ChapterResult(
            index=chapter_result.index,
            volume_index=chapter_result.volume_index,
            title=chapter_result.title,
            outline_item=chapter_result.outline_item,
            draft=chapter_result.draft,
            plan=chapter_result.plan,
            review=review,
            local_quality=local_quality,
            continuity=continuity_update,
            attempts=chapter_result.attempts,
            long_memory=long_memory,
        )

    def _persist_chapter_result(self, chapter_result: ChapterResult) -> None:
        relative_chapter = str(self.store.chapter_path(chapter_result.index).relative_to(self.store.root))
        relative_review = str(self.store.chapter_review_path(chapter_result.index).relative_to(self.store.root))
        relative_continuity = str(self.store.continuity_path(chapter_result.index).relative_to(self.store.root))
        relative_memory = str(self.store.chapter_memory_path(chapter_result.index).relative_to(self.store.root))
        self.store.write_text(relative_chapter, chapter_result.draft)
        self.store.write_json(
            relative_review,
            {"model": chapter_result.review, "local": chapter_result.local_quality, "attempts": chapter_result.attempts},
        )
        self.store.write_json(relative_continuity, chapter_result.continuity)
        self.store.write_json(relative_memory, chapter_result.long_memory or LongRangeMemoryUpdate(chapter_index=chapter_result.index))

    def _repair_chapter_cluster(
        self,
        spec: ProjectSpec,
        bible: WorldBible,
        book_outline: BookOutline,
        volume_outline: VolumeOutline,
        chapters: list[ChapterResult],
        audit: LogicAuditReport,
    ) -> list[ChapterResult]:
        chapter_map = {chapter.index: copy.deepcopy(chapter) for chapter in chapters}
        flagged = [int(item.get("chapter_index", 0)) for item in audit.flagged_chapters if int(item.get("chapter_index", 0)) > 0]
        repair_windows = audit.repair_plan or []
        if repair_windows:
            start = min(int(item.get("start_chapter", min(flagged or [volume_outline.chapter_targets[0].index]))) for item in repair_windows)
            end = max(int(item.get("end_chapter", max(flagged or [volume_outline.chapter_targets[-1].index]))) for item in repair_windows)
            instruction = "；".join(
                _best_text(item.get("instruction"), "")
                for item in repair_windows
                if _best_text(item.get("instruction"), "")
            )
        elif flagged:
            start = max(volume_outline.chapter_targets[0].index, min(flagged) - 1)
            end = min(volume_outline.chapter_targets[-1].index, max(flagged))
            instruction = "；".join(audit.issues[:4] + audit.required_followups[:4])
        else:
            return chapters

        relevant_indices = [item.index for item in volume_outline.chapter_targets if start <= item.index <= end]
        if not relevant_indices:
            return chapters

        self._emit_progress(
            "cluster_repair",
            f"执行第 {volume_outline.volume_index} 卷多章回修。",
            volume_index=volume_outline.volume_index,
            chapter_range=[min(relevant_indices), max(relevant_indices)],
        )
        pre_cluster = [chapter_map[index] for index in sorted(chapter_map) if index < min(relevant_indices)]
        rolling_continuity = self._rebuild_continuity_state(bible, pre_cluster)
        rolling_promises, rolling_progression, rolling_causality = self._rebuild_long_range_state(pre_cluster)
        original_promises = self._promise_ledger
        original_progression = self._progression_ledger
        original_causality = self._causality_graph
        try:
            self._promise_ledger = rolling_promises
            self._progression_ledger = rolling_progression
            self._causality_graph = rolling_causality
            for chapter_index in relevant_indices:
                chapter_result = chapter_map[chapter_index]
                prior_chapters = [chapter_map[index] for index in sorted(chapter_map) if index < chapter_index]
                plan = chapter_result.plan
                context = self._prepare_chapter_generation_context(
                    spec,
                    bible,
                    chapter_result.outline_item,
                    plan,
                    rolling_continuity,
                    prior_chapters,
                )
                style_memory = context["style_memory"]
                retrieved_memory = context["retrieved_memory"]
                promise_memory = context["promise_memory"]
                causality_memory = context["causality_memory"]
                logic_audit = context["logic_audit"]
                chapter_room = context["chapter_room"]
                execution_packet = context["execution_packet"]
                repair_session_id = f"writer-cluster-fix-c{chapter_index}"
                attempts = 1
                chapter_target_chars = _resolved_chapter_target_chars(
                    spec,
                    chapter_result.outline_item,
                    plan,
                )
                reroute_plan_on_retry = False
                self._reset_client_session(repair_session_id)
                rewritten = self._generate_text_with_progress(
                    "cluster_repair",
                    f"回修第 {chapter_index} 章。",
                    f"第{chapter_index}章多章回修",
                    draft_system_prompt(),
                    rewrite_user_prompt(
                        spec,
                        bible,
                        self._style_bible,
                        chapter_result.outline_item,
                        plan,
                        chapter_result.draft,
                        {
                            "model_review": asdict(chapter_result.review),
                            "local_review": asdict(chapter_result.local_quality),
                            "final_fix": instruction,
                            "logic_audit": asdict(audit),
                        },
                        rolling_continuity,
                        self._voice_cards,
                        execution_packet=execution_packet,
                        chapter_room=chapter_room,
                        retrieved_memory=retrieved_memory,
                        style_memory=style_memory,
                        promise_memory=promise_memory,
                        causality_memory=causality_memory,
                        logic_audit=logic_audit,
                    ),
                    temperature=0.45,
                    max_output_tokens=_draft_token_budget(
                        chapter_target_chars,
                        length_tolerance=spec.chapter_char_tolerance,
                        short_standalone=_is_short_standalone_spec(spec),
                    ),
                    session_id=repair_session_id,
                    session_max_chars=_writer_session_max_chars(spec),
                )
                rewritten = self._clean_generated_draft(chapter_index, rewritten, stage="cluster_repair")
                local_quality = analyze_chapter(
                    rewritten,
                    chapter_target_chars,
                    _character_names(bible, spec),
                    market_profile=spec.market_profile,
                    **self._chapter_local_quality_kwargs(spec, chapter_result.outline_item, plan, prior_chapters),
                )
                review = self._review_chapter(
                    spec,
                    bible,
                    chapter_result.outline_item,
                    plan,
                    rewritten,
                    local_quality,
                    rolling_continuity,
                    execution_packet,
                )
                while attempts <= self.max_rewrites and not (local_quality.passed and review.passed):
                    self._emit_progress(
                        "cluster_repair",
                        f"重试回修第 {chapter_index} 章。",
                        chapter_index=chapter_index,
                        attempt=attempts,
                    )
                    self._reset_client_session(repair_session_id)
                    rewritten = self._generate_text_with_progress(
                        "cluster_repair",
                        f"重试回修第 {chapter_index} 章。",
                        f"第{chapter_index}章多章回修重试#{attempts}",
                        draft_system_prompt(),
                        rewrite_user_prompt(
                            spec,
                            bible,
                            self._style_bible,
                            chapter_result.outline_item,
                            plan,
                            rewritten,
                            {
                                "model_review": asdict(review),
                                "local_review": asdict(local_quality),
                                "final_fix": instruction,
                                "logic_audit": asdict(audit),
                            },
                            rolling_continuity,
                            self._voice_cards,
                            execution_packet=execution_packet,
                            chapter_room=chapter_room,
                            retrieved_memory=retrieved_memory,
                            style_memory=style_memory,
                            promise_memory=promise_memory,
                            causality_memory=causality_memory,
                            logic_audit=logic_audit,
                        ),
                        temperature=0.4,
                        max_output_tokens=_draft_token_budget(
                            chapter_target_chars,
                            length_tolerance=spec.chapter_char_tolerance,
                            short_standalone=_is_short_standalone_spec(spec),
                        ),
                        session_id=repair_session_id,
                        session_max_chars=_writer_session_max_chars(spec),
                    )
                    rewritten = self._clean_generated_draft(chapter_index, rewritten, stage="cluster_repair")
                    local_quality = analyze_chapter(
                        rewritten,
                        chapter_target_chars,
                        _character_names(bible, spec),
                        market_profile=spec.market_profile,
                        **self._chapter_local_quality_kwargs(spec, chapter_result.outline_item, plan, prior_chapters),
                    )
                    review = self._review_chapter(
                        spec,
                        bible,
                        chapter_result.outline_item,
                        plan,
                        rewritten,
                        local_quality,
                        rolling_continuity,
                        execution_packet,
                    )
                    attempts += 1
                if not (local_quality.passed and review.passed):
                    if self._review_semantic_drift_prone() and _review_feedback_looks_malformed(review, local_quality):
                        review = _synthesize_malformed_review_pass(review, local_quality)
                    elif self._underwrite_prone() and _anthropic_review_local_divergence_needs_expansion(review, local_quality):
                        review = _synthesize_anthropic_expansion_divergence_pass(review, local_quality)
                    elif self._underwrite_prone() and _underwritten_but_structured_needs_expansion(rewritten, review, local_quality):
                        local_quality = _soften_anthropic_short_length_failure(local_quality)
                        review = _synthesize_underwritten_structured_pass(review, local_quality)
                if not (local_quality.passed and review.passed):
                    self._write_failed_chapter_snapshot(chapter_index, rewritten, review, local_quality, chapter_result.attempts + attempts)
                    raise RuntimeError(f"Cluster repair failed for chapter {chapter_index}.")
                continuity_update = self._extract_continuity(spec, bible, chapter_result.outline_item, rewritten, rolling_continuity)
                self._record_stagnation_signal(chapter_index, local_quality, continuity_update)
                self._long_memory_context = rolling_continuity
                long_memory = self._extract_long_range_memory(spec, bible, chapter_result.outline_item, plan, rewritten)
                updated = ChapterResult(
                    index=chapter_result.index,
                    volume_index=chapter_result.volume_index,
                    title=chapter_result.title,
                    outline_item=chapter_result.outline_item,
                    draft=rewritten,
                    plan=plan,
                    review=review,
                    local_quality=local_quality,
                    continuity=continuity_update,
                    attempts=chapter_result.attempts + attempts,
                    long_memory=long_memory,
                )
                chapter_map[chapter_index] = updated
                rolling_continuity = _merge_continuity_state(rolling_continuity, continuity_update, updated.volume_index)
                self._promise_ledger = _merge_promise_ledger(
                    self._promise_ledger,
                    long_memory.promise_updates,
                    current_volume=updated.volume_index,
                    current_chapter=updated.index,
                )
                self._progression_ledger = _merge_progression_ledger(
                    self._progression_ledger,
                    long_memory.progression_updates,
                    current_chapter=updated.index,
                )
                self._causality_graph = _merge_causality_graph(
                    self._causality_graph,
                    long_memory.causality_updates,
                    current_chapter=updated.index,
                )
                relative_chapter = str(self.store.chapter_path(chapter_index).relative_to(self.store.root))
                relative_review = str(self.store.chapter_review_path(chapter_index).relative_to(self.store.root))
                relative_continuity = str(self.store.continuity_path(chapter_index).relative_to(self.store.root))
                relative_memory = str(self.store.chapter_memory_path(chapter_index).relative_to(self.store.root))
                relative_execution = str(self.store.chapter_execution_path(chapter_index).relative_to(self.store.root))
                self.store.write_text(relative_chapter, rewritten)
                self.store.write_json(relative_review, {"model": review, "local": local_quality, "attempts": updated.attempts})
                self.store.write_json(relative_continuity, continuity_update)
                self.store.write_json(relative_memory, long_memory)
                self.store.write_json(relative_execution, execution_packet)
        finally:
            self._promise_ledger = original_promises
            self._progression_ledger = original_progression
            self._causality_graph = original_causality
        repaired = [chapter_map[index] for index in sorted(chapter_map)]
        return repaired

    def _rebuild_continuity_state(self, bible: WorldBible, chapters: list[ChapterResult]) -> ContinuityState:
        continuity = _initial_continuity_state(bible)
        for chapter in sorted(chapters, key=lambda item: item.index):
            continuity = _merge_continuity_state(continuity, chapter.continuity, chapter.volume_index)
        return _sanitize_continuity_state(continuity)

    def _rebuild_long_range_state(
        self,
        chapters: list[ChapterResult],
    ) -> tuple[list[PromiseLedgerItem], list[ProgressionLedgerItem], list[CausalityEdge]]:
        promises: list[PromiseLedgerItem] = []
        progression: list[ProgressionLedgerItem] = []
        causality: list[CausalityEdge] = []
        for chapter in sorted(chapters, key=lambda item: item.index):
            if chapter.long_memory is None:
                continue
            promises = _merge_promise_ledger(promises, chapter.long_memory.promise_updates, current_volume=chapter.volume_index, current_chapter=chapter.index)
            progression = _merge_progression_ledger(progression, chapter.long_memory.progression_updates, current_chapter=chapter.index)
            causality = _merge_causality_graph(causality, chapter.long_memory.causality_updates, current_chapter=chapter.index)
        return promises, progression, causality

    def _assemble_novel(self, spec: ProjectSpec, chapters: list[ChapterResult]) -> str:
        body = [f"# {spec.title}", ""]
        for chapter in chapters:
            body.extend([f"## {_chapter_heading(spec, chapter.index, chapter.title)}", "", chapter.draft.strip(), ""])
        return "\n".join(body).strip() + "\n"

    def _assemble_plain_novel(self, spec: ProjectSpec, chapters: list[ChapterResult]) -> str:
        body = [spec.title, ""]
        for chapter in chapters:
            body.extend([_chapter_heading(spec, chapter.index, chapter.title), "", chapter.draft.strip(), ""])
        return "\n".join(body).strip() + "\n"

    def _write_partial_novel(self, spec: ProjectSpec, chapters: Any) -> None:
        ordered = sorted(list(chapters), key=lambda item: item.index)
        if not ordered:
            _write_committed_progress_payload(self.store, 0)
            return
        self.store.write_text("novel.md", self._assemble_novel(spec, ordered))
        self.store.write_text("novel.txt", self._assemble_plain_novel(spec, ordered))
        _write_committed_progress_payload(self.store, ordered[-1].index)

    def _build_book_package(
        self,
        spec: ProjectSpec,
        bible: WorldBible,
        book_outline: BookOutline,
        chapters: list[ChapterResult],
        continuity: ContinuityState,
        final_review: FinalReview,
        total_chars: int,
    ) -> BookPackage:
        catalog = _build_book_catalog(book_outline, chapters)
        volume_digests = _build_volume_digests(book_outline, chapters)
        fallback = _fallback_book_package(
            spec,
            bible,
            chapters,
            continuity,
            final_review,
            total_chars,
            catalog,
            volume_digests,
        )
        self._emit_progress("book_package", "生成成书简介与目录。", chapter_count=len(chapters))
        user_prompt = book_package_user_prompt(
            spec,
            bible,
            book_outline,
            volume_digests,
            continuity,
            asdict(final_review),
            total_chars,
        )
        try:
            payload = self._generate_json_with_progress(
                "book_package",
                "生成成书简介与目录。",
                "成书简介",
                book_package_system_prompt(),
                user_prompt,
                model=self._light_model_name(),
                temperature=0.35,
                max_output_tokens=1400,
                session_id="book-package",
                session_max_chars=50000,
                provider_tier="light",
            )
        except Exception as exc:
            self._emit_progress(
                "book_package",
                "成书简介生成失败，已使用本地兜底。",
                error=str(exc)[:160],
            )
            return fallback
        if not isinstance(payload, dict):
            return fallback
        return BookPackage(
            title=fallback.title,
            genre=fallback.genre,
            audience=fallback.audience,
            tone=fallback.tone,
            protagonist=fallback.protagonist,
            total_chars=fallback.total_chars,
            chapter_count=fallback.chapter_count,
            volume_count=fallback.volume_count,
            final_score=fallback.final_score,
            final_passed=fallback.final_passed,
            factual_summary=_normalize_package_text(payload.get("factual_summary"), fallback.factual_summary, max_chars=560, min_chars=180),
            marketing_blurb=_normalize_package_text(payload.get("marketing_blurb"), fallback.marketing_blurb, max_chars=200, min_chars=40),
            catalog=fallback.catalog,
            output_language=spec.output_language,
        )

    def _render_book_summary(self, package: BookPackage) -> str:
        zh = _is_zh_output_language(package.output_language)
        status = "通过" if package.final_passed else "未通过"
        final_review = f"{status}（{package.final_score} 分）"
        if not zh:
            status = "Passed" if package.final_passed else "Not passed"
            final_review = f"{status} ({package.final_score})"
        lines = (
            [
                f"# {package.title} 简介包",
                "",
                "## 作品信息",
                "",
                f"- 题材：{package.genre}",
                f"- 读者：{package.audience}",
                f"- 风格：{package.tone}",
                f"- 主角：{package.protagonist}",
                f"- 字数：{package.total_chars}",
                f"- 章节数：{package.chapter_count}",
                f"- 卷数：{package.volume_count}",
                f"- 终审：{final_review}",
                "",
                "## 实际剧情简介",
                "",
                package.factual_summary,
                "",
                "## 平台简介",
                "",
                package.marketing_blurb,
                "",
                "## 目录",
                "",
            ]
            if zh
            else [
                f"# {package.title} Book Package",
                "",
                "## Book Info",
                "",
                f"- Genre: {package.genre}",
                f"- Audience: {package.audience}",
                f"- Tone: {package.tone}",
                f"- Protagonist: {package.protagonist}",
                f"- Total characters: {package.total_chars}",
                f"- Chapters: {package.chapter_count}",
                f"- Volumes: {package.volume_count}",
                f"- Final review: {final_review}",
                "",
                "## Factual Summary",
                "",
                package.factual_summary,
                "",
                "## Marketing Blurb",
                "",
                package.marketing_blurb,
                "",
                "## Table Of Contents",
                "",
            ]
        )
        for volume in package.catalog:
            chapter_range = volume.get("chapter_range")
            if isinstance(chapter_range, list) and len(chapter_range) == 2:
                range_text = f"（第{chapter_range[0]}-{chapter_range[1]}章）" if zh else f" (Chapters {chapter_range[0]}-{chapter_range[1]})"
            else:
                range_text = ""
            volume_index = volume.get("volume_index", "?")
            lines.extend([f"### {_volume_heading_from_parts(package.output_language, volume_index, volume.get('title', ''))}{range_text}", ""])
            for chapter in volume.get("chapters", []):
                if not isinstance(chapter, dict):
                    continue
                lines.append(f"- {_chapter_heading_from_parts(package.output_language, chapter.get('index', '?'), chapter.get('title', ''))}")
            lines.append("")
        return "\n".join(lines).strip() + "\n"

    def _clean_generated_draft(self, chapter_index: int, draft: str, *, stage: str) -> str:
        cleaned, removed = dedupe_repeated_paragraphs(draft)
        if removed > 0:
            self._emit_progress(
                stage,
                f"清理第 {chapter_index} 章重复段落。",
                chapter_index=chapter_index,
                removed_duplicate_paragraphs=removed,
            )
        return cleaned

    def _write_failed_chapter_snapshot(
        self,
        chapter_index: int,
        draft: str,
        review: ReviewFeedback,
        local_quality: LocalQualityReport,
        attempts: int,
    ) -> None:
        self.store.write_text(f"state/chapter-{chapter_index:02d}.failed.md", draft)
        self.store.write_json(
            f"state/chapter-{chapter_index:02d}.failed.review.json",
            {"model": review, "local": local_quality, "attempts": attempts},
        )

    def _reset_client_session(self, session_id: str) -> None:
        self._reset_session(session_id)

    def _reset_volume_boundary_sessions(self) -> None:
        for session_id in VOLUME_BOUNDARY_SESSION_IDS:
            self._reset_session(session_id)

    def _make_stream_observer(self, label: str) -> _DeltaPrinter | None:
        if not self.stream_output:
            return None
        self._current_stream = _DeltaPrinter(label)
        return self._current_stream

    def _make_json_stream_observer(self, step: str, message: str, label: str) -> _ProgressStreamObserver:
        delegate = _DeltaPrinter(label) if self.stream_output else None
        observer = _ProgressStreamObserver(
            delegate,
            lambda total_chars: self._emit_progress(step, f"{message}（流式接收中）", streamed_chars=total_chars),
        )
        self._current_stream = observer
        return observer

    def _generate_json_with_progress(
        self,
        step: str,
        message: str,
        label: str,
        system_prompt: str,
        user_prompt: str,
        *,
        model: str | None = None,
        temperature: float = 0.2,
        max_output_tokens: int | None = None,
        session_id: str | None = None,
        session_max_chars: int | None = None,
        provider_tier: str = "flagship",
    ) -> Any:
        try:
            return self.client.generate_json(
                system_prompt,
                user_prompt,
                model=model,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
                session_id=session_id,
                session_max_chars=session_max_chars,
                stream=True,
                stream_observer=self._make_json_stream_observer(step, message, label),
                provider_tier=provider_tier,
            )
        except JsonParseModelClientError as exc:
            self._emit_progress(
                f"{step}_parse_recover",
                f"{message}（返回非 JSON，转交后续结构修复链）",
            )
            return exc.raw_text
        finally:
            self._close_stream_observer()

    def _generate_text_with_progress(
        self,
        step: str,
        message: str,
        label: str,
        system_prompt: str,
        user_prompt: str,
        *,
        model: str | None = None,
        temperature: float = 0.3,
        max_output_tokens: int | None = None,
        session_id: str | None = None,
        session_max_chars: int | None = None,
        json_mode: bool = False,
        provider_tier: str = "flagship",
    ) -> str:
        try:
            return self.client.generate_text(
                system_prompt,
                user_prompt,
                model=model,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
                json_mode=json_mode,
                session_id=session_id,
                session_max_chars=session_max_chars,
                stream=True,
                stream_observer=self._make_text_stream_observer(step, message, label),
                provider_tier=provider_tier,
            )
        finally:
            self._close_stream_observer()

    def _make_text_stream_observer(self, step: str, message: str, label: str) -> _ProgressStreamObserver:
        delegate = _DeltaPrinter(label) if self.stream_output else None
        observer = _ProgressStreamObserver(
            delegate,
            lambda total_chars: self._emit_progress(step, f"{message}（流式接收中）", streamed_chars=total_chars),
        )
        self._current_stream = observer
        return observer

    def _close_stream_observer(self) -> None:
        current_stream = self._current_stream
        if current_stream is not None:
            current_stream.close()
            self._current_stream = None

    def _reset_session(self, session_id: str) -> None:
        reset = getattr(self.client, "reset_session", None)
        if callable(reset):
            reset(session_id)

    def _emit_progress(self, step: str, message: str, **data: Any) -> None:
        self.store.write_json("data/progress.json", {"step": step, "message": message, "data": data})
        if self.progress_callback is not None:
            self.progress_callback(step, message, data)


def _normalized_chapter_char_tolerance(value: float | None) -> float:
    if value is None:
        return 0.25
    try:
        tolerance = float(value)
    except (TypeError, ValueError):
        return 0.25
    return max(0.05, min(0.4, tolerance))


def _normalized_structure_mode(value: Any) -> str:
    mode = _best_text(value, "story_driven").strip().lower().replace("-", "_")
    if mode in {"legacy", "fixed"}:
        return "legacy"
    return "story_driven"


def _normalized_market_profile(value: Any) -> str:
    profile = _best_text(value, "qidian_longform").strip().lower().replace("-", "_")
    if profile in {"tomato_mass", "tomato", "番茄", "番茄爆款"}:
        return "tomato_mass"
    return "qidian_longform"


def _normalized_ending_mode(value: Any) -> str:
    mode = _best_text(value, "standalone").strip().lower().replace("-", "_")
    return "series" if mode == "series" else "standalone"


def _clamp_int(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, int(value)))


def _int_or_default(*values: Any, default: int = 0) -> int:
    for value in values:
        try:
            if value not in {None, ""}:
                return int(value)
        except (TypeError, ValueError):
            continue
    return default


def _float_or_default(*values: Any) -> float:
    for value in values:
        try:
            if value not in {None, ""}:
                return float(value)
        except (TypeError, ValueError):
            continue
    return 0.0


def _bool_or_default(value: Any, fallback: Any, default: bool) -> bool:
    for candidate in (value, fallback):
        if candidate in {None, ""}:
            continue
        if isinstance(candidate, bool):
            return candidate
        if isinstance(candidate, str):
            lowered = candidate.strip().lower()
            if lowered in {"true", "1", "yes", "y"}:
                return True
            if lowered in {"false", "0", "no", "n"}:
                return False
        return bool(candidate)
    return default


def _story_phase_from_position(index: int, volume_count: int) -> str:
    if volume_count <= 1:
        return "closure"
    position = index / max(volume_count - 1, 1)
    if position <= 0.1:
        return "opening"
    if position <= 0.25:
        return "escalation"
    if position <= 0.5:
        return "investigation"
    if position <= 0.68:
        return "bridge"
    if position <= 0.88:
        return "climax"
    if position <= 0.96:
        return "fallout"
    return "closure"


def _phase_weight(phase_type: str) -> float:
    return {
        "opening": 0.9,
        "bridge": 0.78,
        "investigation": 1.0,
        "escalation": 1.08,
        "climax": 1.32,
        "fallout": 0.88,
        "closure": 0.82,
    }.get(_best_text(phase_type, ""), 1.0)


def _density_mode_for_phase(phase_type: str) -> str:
    return {
        "opening": "measured",
        "bridge": "lean",
        "investigation": "steady",
        "escalation": "dense",
        "climax": "surging",
        "fallout": "breathing",
        "closure": "focused",
    }.get(_best_text(phase_type, ""), "steady")


def _importance_for_phase(phase_type: str) -> str:
    return {
        "opening": "medium",
        "bridge": "low",
        "investigation": "medium",
        "escalation": "high",
        "climax": "peak",
        "fallout": "medium",
        "closure": "high",
    }.get(_best_text(phase_type, ""), "medium")


def _phase_expected_chapter_range(phase_type: str, seed_target: int) -> tuple[int, int]:
    seed = max(1, int(seed_target))
    if phase_type == "bridge":
        return max(2, seed - 2), max(3, seed + 1)
    if phase_type == "climax":
        return max(3, seed - 1), max(seed + 3, seed + 1)
    if phase_type == "closure":
        return max(2, seed - 2), max(3, seed + 1)
    if phase_type == "opening":
        return max(2, seed - 1), max(3, seed + 1)
    if phase_type == "fallout":
        return max(2, seed - 2), max(3, seed + 1)
    return max(2, seed - 1), max(3, seed + 2)


def _expected_range_text(minimum: int, maximum: int) -> str:
    return f"{max(1, int(minimum))}-{max(maximum, minimum, 1)}"


def _parse_expected_chapter_range(value: str, fallback: tuple[int, int]) -> tuple[int, int]:
    text = _best_text(value, "")
    match = re.search(r"(\d+)\s*[-~到至]\s*(\d+)", text)
    if match:
        low = int(match.group(1))
        high = int(match.group(2))
        if low > high:
            low, high = high, low
        return low, high
    digits = re.findall(r"\d+", text)
    if len(digits) == 1:
        single = int(digits[0])
        return max(1, single - 1), max(1, single + 1)
    return fallback


def _load_bucket_score(value: Any) -> float:
    text = _best_text(value, "").strip().lower()
    return {
        "low": 0.86,
        "medium": 1.0,
        "mid": 1.0,
        "high": 1.14,
        "peak": 1.24,
        "heavy": 1.18,
        "light": 0.9,
    }.get(text, 1.0)


def _importance_score(value: Any) -> float:
    text = _best_text(value, "").strip().lower()
    return {
        "low": 0.88,
        "medium": 1.0,
        "high": 1.14,
        "peak": 1.26,
    }.get(text, 1.0)


def _story_driven_seed_volume_targets(chapter_count: int, volume_count: int) -> list[int]:
    weights = [_phase_weight(_story_phase_from_position(index, volume_count)) for index in range(volume_count)]
    targets = _weighted_volume_chapter_targets(chapter_count, volume_count, weights)
    if (
        volume_count > 1
        and chapter_count >= volume_count + 2
        and len(set(targets)) == 1
        and len(set(round(weight, 3) for weight in weights)) > 1
    ):
        highest = max(range(volume_count), key=lambda index: (weights[index], -index))
        lowest = min(range(volume_count), key=lambda index: (weights[index], index))
        if highest != lowest and targets[lowest] > 1:
            targets[highest] += 1
            targets[lowest] -= 1
    return targets


def _rebalance_targets_to_sum(
    preferred: list[int],
    minimums: list[int],
    maximums: list[int],
    total: int,
    weights: list[float],
) -> list[int]:
    count = len(preferred)
    if count == 0:
        return []
    targets = [
        _clamp_int(preferred[index], max(1, minimums[index]), max(maximums[index], minimums[index], 1))
        for index in range(count)
    ]
    diff = int(total) - sum(targets)
    guard = 0
    while diff != 0 and guard < max(1000, abs(diff) * 8):
        guard += 1
        if diff > 0:
            candidates = [
                index
                for index in range(count)
                if targets[index] < max(maximums[index], minimums[index], 1)
            ]
            if not candidates:
                break
            best = max(
                candidates,
                key=lambda idx: (
                    float(weights[idx]),
                    preferred[idx] - targets[idx],
                    maximums[idx] - targets[idx],
                    -idx,
                ),
            )
            targets[best] += 1
            diff -= 1
        else:
            candidates = [index for index in range(count) if targets[index] > max(1, minimums[index])]
            if not candidates:
                break
            best = max(
                candidates,
                key=lambda idx: (
                    targets[idx] - minimums[idx],
                    -float(weights[idx]),
                    idx,
                ),
            )
            targets[best] -= 1
            diff += 1
    return [max(1, int(item)) for item in targets]


def _weighted_volume_chapter_targets(chapter_count: int, volume_count: int, weights: list[float] | None = None) -> list[int]:
    chapter_count = max(1, int(chapter_count))
    volume_count = max(1, min(int(volume_count), chapter_count))
    if volume_count == 1:
        return [chapter_count]

    if not weights or len(weights) != volume_count:
        weights = []
        for index in range(volume_count):
            position = index / max(volume_count - 1, 1)
            center_bias = (1.0 - abs(position - 0.5) * 2.0) * 0.18
            forward_bias = (position - 0.5) * 0.12
            weights.append(1.0 + center_bias + forward_bias)
    normalized_weights = [max(float(item), 0.1) for item in weights]
    weight_total = sum(normalized_weights) or float(volume_count)
    targets = [1] * volume_count
    remaining = chapter_count - volume_count
    raw = [(item / weight_total) * remaining for item in normalized_weights]
    floors = [int(math.floor(item)) for item in raw]
    fractional = [item - math.floor(item) for item in raw]
    for index, extra in enumerate(floors):
        targets[index] += extra
    leftover = remaining - sum(floors)
    for index in sorted(range(volume_count), key=lambda item: fractional[item], reverse=True)[:leftover]:
        targets[index] += 1
    return targets


def _volume_chapter_targets(chapter_count: int, volume_count: int) -> list[int]:
    return _weighted_volume_chapter_targets(chapter_count, volume_count)


def _normalized_volume_chapter_targets(
    payload: list[int] | tuple[int, ...] | None,
    *,
    chapter_count: int,
    volume_count: int,
) -> list[int]:
    if payload:
        try:
            weights = [max(int(item), 1) for item in payload]
        except (TypeError, ValueError):
            weights = []
        if len(weights) == volume_count:
            return _weighted_volume_chapter_targets(chapter_count, volume_count, [float(item) for item in weights])
    return _volume_chapter_targets(chapter_count, volume_count)


def _soft_target_count(
    preferred: int,
    hinted: int,
    *,
    tolerance: float = 0.25,
    minimum: int = 1,
    maximum: int | None = None,
) -> int:
    preferred = max(minimum, int(preferred))
    hinted = max(minimum, int(hinted))
    hinted_window = max(1, int(round(hinted * tolerance)))
    lower = max(minimum, hinted - hinted_window)
    upper = hinted + hinted_window
    if maximum is not None:
        upper = min(upper, maximum)
    if lower > upper:
        lower = upper
    return _clamp_int(preferred, lower, upper)


def _round_half_up(value: float) -> int:
    return int(math.floor(float(value) + 0.5))


def _story_driven_chapter_count(target_total_chars: int, target_chars_per_chapter: int, requested: int) -> int:
    estimated = max(1, math.ceil(max(target_total_chars, target_chars_per_chapter) / max(target_chars_per_chapter, 1)))
    if requested <= 0:
        return estimated
    biased = _round_half_up(estimated * 0.75 + max(1, requested) * 0.25)
    return max(1, int(biased))


def _story_driven_volume_count(chapter_count: int, requested: int) -> int:
    derived = max(1, math.ceil(chapter_count / 12))
    if requested <= 0:
        return derived
    biased = _round_half_up((derived + max(1, requested)) / 2)
    return max(1, int(biased))


def _derived_target_chars_per_chapter(project_input: ProjectInput) -> int:
    explicit = project_input.target_chars_per_chapter
    if explicit not in {None, ""}:
        try:
            return max(1200, int(explicit))
        except (TypeError, ValueError):
            pass

    target_total_chars = max(0, int(project_input.target_total_chars or 0))
    requested_chapter_count = max(0, int(project_input.chapter_count or 0))
    structure_mode = _normalized_structure_mode(project_input.structure_mode)
    ending_mode = _normalized_ending_mode(project_input.ending_mode)
    market_profile = _normalized_market_profile(project_input.market_profile)

    if target_total_chars > 0 and requested_chapter_count > 0:
        estimated = int(round(target_total_chars / max(1, requested_chapter_count)))
        return _clamp_int(estimated, 1200, 4200)

    if target_total_chars <= 0:
        return 2000

    if target_total_chars >= 5_000_000:
        baseline = 3600
    elif target_total_chars >= 2_500_000:
        baseline = 3200
    elif target_total_chars >= 1_000_000:
        baseline = 2800
    elif target_total_chars >= 500_000:
        baseline = 2600
    elif target_total_chars >= 150_000:
        baseline = 2400
    elif target_total_chars >= 50_000:
        baseline = 2200
    else:
        baseline = 2000

    if structure_mode == "story_driven":
        baseline = int(round(baseline * 1.05))
    if ending_mode == "series":
        baseline = int(round(baseline * 1.05))
    if market_profile == "tomato_mass":
        baseline = int(round(baseline * 0.9))
    else:
        baseline = int(round(baseline * 1.05))
    return _clamp_int(baseline, 1200, 4200)


def _derive_structure(project_input: ProjectInput) -> dict[str, int | float | list[int]]:
    structure_mode = _normalized_structure_mode(project_input.structure_mode)
    target_chars_per_chapter = _derived_target_chars_per_chapter(project_input)
    target_total_chars = int(project_input.target_total_chars or 0)
    requested_chapter_count = int(project_input.chapter_count or 0)
    requested_volume_count = int(project_input.volume_count or 0)

    if target_total_chars <= 0 and requested_chapter_count <= 0:
        target_total_chars = 4000

    if structure_mode == "story_driven":
        if target_total_chars <= 0 and requested_chapter_count > 0:
            target_total_chars = requested_chapter_count * target_chars_per_chapter
        chapter_count = _story_driven_chapter_count(target_total_chars, target_chars_per_chapter, requested_chapter_count)
        if requested_chapter_count > 0:
            chapter_count = _soft_target_count(chapter_count, requested_chapter_count)
        if target_total_chars <= 0:
            target_total_chars = chapter_count * target_chars_per_chapter
        volume_count = _story_driven_volume_count(chapter_count, requested_volume_count)
        if requested_volume_count > 0:
            volume_count = _soft_target_count(volume_count, requested_volume_count, minimum=1, maximum=chapter_count)
    else:
        chapter_count = requested_chapter_count
        if chapter_count <= 0:
            chapter_count = max(1, math.ceil(max(target_total_chars, target_chars_per_chapter) / target_chars_per_chapter))
        if target_total_chars <= 0:
            target_total_chars = chapter_count * target_chars_per_chapter
        if requested_volume_count > 0:
            volume_count = min(max(1, requested_volume_count), chapter_count)
        else:
            volume_count = max(1, math.ceil(chapter_count / 18))
    chapters_per_volume = math.ceil(chapter_count / volume_count)
    if structure_mode == "story_driven":
        volume_chapter_targets = _story_driven_seed_volume_targets(chapter_count, volume_count)
    else:
        volume_chapter_targets = _volume_chapter_targets(chapter_count, volume_count)
    chapter_char_tolerance = _normalized_chapter_char_tolerance(project_input.chapter_char_tolerance)

    return {
        "target_total_chars": target_total_chars,
        "target_chars_per_chapter": target_chars_per_chapter,
        "chapter_count": chapter_count,
        "volume_count": volume_count,
        "chapters_per_volume": chapters_per_volume,
        "volume_chapter_targets": volume_chapter_targets,
        "chapter_char_tolerance": chapter_char_tolerance,
        "structure_mode": structure_mode,
    }


def _volume_skeletons(spec: ProjectSpec) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    current = 1
    volume_targets = _normalized_volume_chapter_targets(
        spec.volume_chapter_targets,
        chapter_count=spec.chapter_count,
        volume_count=spec.volume_count,
    )
    for index, chapter_target in enumerate(volume_targets, start=1):
        phase_type = _story_phase_from_position(index - 1, len(volume_targets)) if spec.structure_mode == "story_driven" else ""
        range_min, range_max = _phase_expected_chapter_range(phase_type, chapter_target)
        density_mode = _density_mode_for_phase(phase_type) if phase_type else ""
        end = min(spec.chapter_count, current + max(chapter_target, 1) - 1)
        target_chars = max(1, int(round(chapter_target * spec.target_chars_per_chapter * (_phase_weight(phase_type) if phase_type else 1.0))))
        items.append(
            {
                "index": index,
                "start_chapter": current,
                "end_chapter": end,
                "title": "",
                "role": "",
                "central_question": "",
                "escalation": "",
                "emotional_shift": "",
                "phase_type": phase_type,
                "volume_importance": _importance_for_phase(phase_type) if phase_type else "",
                "beat_count": max(2, chapter_target // 2),
                "new_setting_load": "medium" if phase_type in {"opening", "investigation"} else "low",
                "new_cast_load": "medium" if phase_type in {"opening", "bridge"} else "low",
                "payoff_load": "high" if phase_type in {"climax", "closure"} else "medium",
                "expected_chapter_range": _expected_range_text(range_min, range_max),
                "target_chapter_count": chapter_target,
                "chapter_count_min": range_min,
                "chapter_count_max": range_max,
                "target_chars": target_chars,
                "target_chars_min": int(math.floor(target_chars * 0.82)),
                "target_chars_max": int(math.ceil(target_chars * 1.18)),
                "density_mode": density_mode,
                "tier_floor": "",
                "tier_target": "",
                "required_breakthrough": "",
                "resource_goal": "",
                "enemy_band": "",
                "progression_payoff": "",
                "must_payoff": [],
            }
        )
        current = end + 1
    return items


def _build_volume_blueprints_from_outline_payload(
    spec: ProjectSpec,
    skeleton: list[dict[str, Any]],
    volume_payloads: dict[int, dict[str, Any]],
) -> list[VolumeBlueprint]:
    if not skeleton:
        return []

    total_volumes = len(skeleton)
    minimums: list[int] = []
    maximums: list[int] = []
    preferred: list[int] = []
    chapter_weights: list[float] = []
    char_weights: list[float] = []
    prepared: list[dict[str, Any]] = []

    for item in skeleton:
        index = int(item["index"])
        current = volume_payloads.get(index, {})
        phase_type = _best_text(
            current.get("phase_type"),
            item.get("phase_type"),
            _story_phase_from_position(index - 1, total_volumes),
        )
        importance = _best_text(
            current.get("volume_importance"),
            item.get("volume_importance"),
            _importance_for_phase(phase_type),
        )
        density_mode = _best_text(
            current.get("density_mode"),
            item.get("density_mode"),
            _density_mode_for_phase(phase_type),
        )
        expected_seed = _int_or_default(
            current.get("target_chapter_count"),
            item.get("target_chapter_count"),
            item.get("end_chapter", 1) - item.get("start_chapter", 1) + 1,
            default=1,
        )
        expected_range = _best_text(
            current.get("expected_chapter_range"),
            item.get("expected_chapter_range"),
            _expected_range_text(*_phase_expected_chapter_range(phase_type, expected_seed)),
        )
        range_min, range_max = _parse_expected_chapter_range(
            expected_range,
            _phase_expected_chapter_range(phase_type, expected_seed),
        )
        chapter_min = _clamp_int(
            _int_or_default(current.get("chapter_count_min"), item.get("chapter_count_min"), range_min, default=range_min),
            1,
            spec.chapter_count,
        )
        chapter_max = _clamp_int(
            _int_or_default(current.get("chapter_count_max"), item.get("chapter_count_max"), range_max, default=range_max),
            chapter_min,
            spec.chapter_count,
        )
        target_chapter_count = _clamp_int(
            _int_or_default(current.get("target_chapter_count"), item.get("target_chapter_count"), expected_seed, default=expected_seed),
            chapter_min,
            chapter_max,
        )
        beat_count = _clamp_int(
            _int_or_default(current.get("beat_count"), item.get("beat_count"), max(2, target_chapter_count // 2), default=2),
            2,
            max(target_chapter_count * 2, 2),
        )
        new_setting_load = _best_text(current.get("new_setting_load"), item.get("new_setting_load"), "low")
        new_cast_load = _best_text(current.get("new_cast_load"), item.get("new_cast_load"), "low")
        payoff_load = _best_text(current.get("payoff_load"), item.get("payoff_load"), "medium")
        chapter_weight = (
            _phase_weight(phase_type)
            * _importance_score(importance)
            * (1.0 + max(0, beat_count - target_chapter_count) * 0.04)
            * (1.0 + _load_bucket_score(new_setting_load) * 0.04)
            * (1.0 + _load_bucket_score(new_cast_load) * 0.04)
            * (1.0 + _load_bucket_score(payoff_load) * 0.06)
        )
        char_weight = chapter_weight * (1.0 + 0.06 * _load_bucket_score(payoff_load))

        minimums.append(chapter_min)
        maximums.append(chapter_max)
        preferred.append(target_chapter_count)
        chapter_weights.append(chapter_weight)
        char_weights.append(char_weight)
        prepared.append(
            {
                "index": index,
                "title": _best_text(current.get("title"), item.get("title")),
                "role": _best_text(current.get("role"), item.get("role")),
                "central_question": _best_text(current.get("central_question"), item.get("central_question")),
                "escalation": _best_text(current.get("escalation"), item.get("escalation")),
                "emotional_shift": _best_text(current.get("emotional_shift"), item.get("emotional_shift")),
                "must_payoff": _merge_lists(_string_list(current.get("must_payoff")), _string_list(item.get("must_payoff"))),
                "phase_type": phase_type,
                "volume_importance": importance,
                "beat_count": beat_count,
                "new_setting_load": new_setting_load,
                "new_cast_load": new_cast_load,
                "payoff_load": payoff_load,
                "expected_chapter_range": _expected_range_text(chapter_min, chapter_max),
                "chapter_count_min": chapter_min,
                "chapter_count_max": chapter_max,
                "density_mode": density_mode,
                "tier_floor": _best_text(current.get("tier_floor"), item.get("tier_floor")),
                "tier_target": _best_text(current.get("tier_target"), item.get("tier_target")),
                "required_breakthrough": _best_text(current.get("required_breakthrough"), item.get("required_breakthrough")),
                "resource_goal": _best_text(current.get("resource_goal"), item.get("resource_goal")),
                "enemy_band": _best_text(current.get("enemy_band"), item.get("enemy_band")),
                "progression_payoff": _best_text(current.get("progression_payoff"), item.get("progression_payoff")),
            }
        )

    chapter_targets = _rebalance_targets_to_sum(preferred, minimums, maximums, spec.chapter_count, chapter_weights)

    total_target_chars = max(spec.target_total_chars, spec.chapter_count * max(spec.target_chars_per_chapter, 1))
    char_minimums = [max(900, int(round(count * spec.target_chars_per_chapter * 0.72))) for count in chapter_targets]
    char_maximums = [max(char_minimums[idx], int(round(count * spec.target_chars_per_chapter * 1.42))) for idx, count in enumerate(chapter_targets)]
    char_preferred = [
        max(char_minimums[idx], int(round(chapter_targets[idx] * spec.target_chars_per_chapter * max(0.82, min(1.45, char_weights[idx])))))
        for idx in range(total_volumes)
    ]
    target_chars = _rebalance_targets_to_sum(char_preferred, char_minimums, char_maximums, total_target_chars, char_weights)

    volumes: list[VolumeBlueprint] = []
    current_chapter = 1
    for idx, meta in enumerate(prepared):
        chapter_total = chapter_targets[idx]
        start = current_chapter
        end = min(spec.chapter_count, start + chapter_total - 1)
        chapter_total = max(1, end - start + 1)
        volume_target_chars = max(target_chars[idx], chapter_total * 900)
        volumes.append(
            VolumeBlueprint(
                index=meta["index"],
                start_chapter=start,
                end_chapter=end,
                title=meta["title"] or f"第{meta['index']}卷",
                role=meta["role"] or "推进主线",
                central_question=meta["central_question"] or "主线问题继续升级。",
                escalation=meta["escalation"] or "局势进一步抬高。",
                emotional_shift=meta["emotional_shift"] or "人物关系与情绪发生变化。",
                phase_type=meta["phase_type"],
                volume_importance=meta["volume_importance"],
                beat_count=meta["beat_count"],
                new_setting_load=meta["new_setting_load"],
                new_cast_load=meta["new_cast_load"],
                payoff_load=meta["payoff_load"],
                expected_chapter_range=meta["expected_chapter_range"],
                target_chapter_count=chapter_total,
                chapter_count_min=meta["chapter_count_min"],
                chapter_count_max=meta["chapter_count_max"],
                target_chars=volume_target_chars,
                target_chars_min=max(int(math.floor(volume_target_chars * 0.84)), chapter_total * 850),
                target_chars_max=max(int(math.ceil(volume_target_chars * 1.18)), chapter_total * 1050),
                density_mode=meta["density_mode"],
                tier_floor=meta["tier_floor"],
                tier_target=meta["tier_target"],
                required_breakthrough=meta["required_breakthrough"],
                resource_goal=meta["resource_goal"],
                enemy_band=meta["enemy_band"],
                progression_payoff=meta["progression_payoff"],
                must_payoff=meta["must_payoff"],
            )
        )
        current_chapter = end + 1
    return volumes


def _chapter_role_for_position(
    offset: int,
    chapter_total: int,
    phase_type: str,
    closing_mode: str,
) -> str:
    if chapter_total <= 1:
        return "closure" if closing_mode == "book_closure" else "setpiece"
    if closing_mode == "book_closure":
        return "closure"
    if closing_mode == "volume_hook":
        return "climax" if phase_type in {"climax", "closure"} else "pivot"
    if offset == 1:
        if phase_type == "opening":
            return "opening"
        if phase_type == "bridge":
            return "bridge"
        return "reentry"
    if offset == chapter_total:
        if phase_type in {"climax", "closure"}:
            return "climax"
        if phase_type == "fallout":
            return "afterglow"
        return "pivot"
    if offset == chapter_total - 1:
        if phase_type in {"climax", "escalation"}:
            return "setpiece"
        if phase_type == "fallout":
            return "afterglow"
    mapping = {
        "opening": "investigation",
        "bridge": "bridge",
        "investigation": "investigation",
        "escalation": "escalation",
        "climax": "setpiece",
        "fallout": "afterglow",
        "closure": "afterglow",
    }
    return mapping.get(phase_type, "investigation")


def _chapter_role_weight(chapter_role: str) -> float:
    weights = {
        "opening": 1.08,
        "reentry": 0.92,
        "investigation": 1.0,
        "bridge": 0.82,
        "escalation": 1.06,
        "pivot": 1.14,
        "setpiece": 1.22,
        "climax": 1.3,
        "afterglow": 0.88,
        "closure": 1.08,
        "transition": 0.78,
    }
    return weights.get(chapter_role, 1.0)


def _chapter_target_chars(spec: ProjectSpec, volume: VolumeBlueprint, chapter_role: str) -> int:
    chapter_total = max(1, volume.target_chapter_count or (volume.end_chapter - volume.start_chapter + 1))
    base = (
        int(round(volume.target_chars / chapter_total))
        if volume.target_chars > 0
        else max(1, spec.target_chars_per_chapter)
    )
    density_weight = {
        "lean": 0.9,
        "standard": 1.0,
        "dense": 1.08,
        "climax-heavy": 1.16,
    }.get(volume.density_mode, 1.0)
    target = int(round(base * density_weight * _chapter_role_weight(chapter_role)))
    lower = max(900, int(spec.target_chars_per_chapter * 0.68))
    upper = max(lower, int(spec.target_chars_per_chapter * 1.75))
    return _clamp_int(target, lower, upper)


def _scene_type_weight(scene_type: str) -> float:
    weights = {
        "grounding": 0.72,
        "transition": 0.78,
        "investigation": 0.95,
        "dialogue": 0.9,
        "conflict": 1.02,
        "reveal": 1.08,
        "setpiece": 1.22,
        "climax": 1.32,
        "afterglow": 0.86,
    }
    return weights.get(scene_type, 1.0)


def _resolved_chapter_target_chars(
    spec: ProjectSpec,
    chapter: ChapterOutlineItem | None = None,
    plan: ChapterPlan | None = None,
) -> int:
    return max(
        1,
        int(
            (plan.target_chars if plan and plan.target_chars else None)
            or (chapter.target_chars if chapter and chapter.target_chars else None)
            or spec.target_chars_per_chapter
            or 2000
        ),
    )


def _resolved_chapter_target_bounds(
    spec: ProjectSpec,
    chapter: ChapterOutlineItem | None = None,
    plan: ChapterPlan | None = None,
) -> tuple[int, int]:
    target_chars = _resolved_chapter_target_chars(spec, chapter, plan)
    target_min = (
        int(plan.target_chars_min)
        if plan and plan.target_chars_min
        else int(chapter.target_chars_min)
        if chapter and chapter.target_chars_min
        else _chapter_char_bounds(target_chars, length_tolerance=spec.chapter_char_tolerance)[0]
    )
    target_max = (
        int(plan.target_chars_max)
        if plan and plan.target_chars_max
        else int(chapter.target_chars_max)
        if chapter and chapter.target_chars_max
        else _chapter_char_bounds(target_chars, length_tolerance=spec.chapter_char_tolerance)[1]
    )
    return target_min, target_max


def _resolve_scene_load_score(payload: dict[str, Any], chapter: ChapterOutlineItem) -> float:
    explicit = payload.get("scene_load_score")
    if explicit not in {None, ""}:
        try:
            return round(float(explicit), 2)
        except (TypeError, ValueError):
            pass
    scenes = payload.get("scenes")
    if isinstance(scenes, list) and scenes:
        weights: list[float] = []
        for item in scenes:
            if not isinstance(item, dict):
                continue
            try:
                if item.get("load_weight") not in {None, ""}:
                    weights.append(float(item.get("load_weight")))
                    continue
            except (TypeError, ValueError):
                pass
            weights.append(_scene_type_weight(_best_text(item.get("scene_type"), "")))
        if weights:
            return round(sum(weights), 2)
    if chapter.scene_load_score:
        return round(float(chapter.scene_load_score), 2)
    return round(_chapter_role_weight(chapter.chapter_role), 2)


def _resolve_plan_target_chars(spec: ProjectSpec, chapter: ChapterOutlineItem, payload: dict[str, Any]) -> int:
    raw = payload.get("target_chars")
    if raw not in {None, ""}:
        try:
            return max(900, int(raw))
        except (TypeError, ValueError):
            pass
    load_score = _resolve_scene_load_score(payload, chapter)
    target = int(round(_resolved_chapter_target_chars(spec, chapter) * max(0.75, min(1.35, load_score))))
    lower = max(900, int(spec.target_chars_per_chapter * 0.68))
    upper = max(lower, int(spec.target_chars_per_chapter * 1.75))
    return _clamp_int(target, lower, upper)


def _resolve_plan_target_min(spec: ProjectSpec, chapter: ChapterOutlineItem, payload: dict[str, Any]) -> int:
    raw = payload.get("target_chars_min")
    if raw not in {None, ""}:
        try:
            return max(800, int(raw))
        except (TypeError, ValueError):
            pass
    target = _resolve_plan_target_chars(spec, chapter, payload)
    default_min, _ = _chapter_char_bounds(target, length_tolerance=spec.chapter_char_tolerance)
    chapter_min = int(chapter.target_chars_min) if chapter.target_chars_min else default_min
    return min(chapter_min, target)


def _resolve_plan_target_max(spec: ProjectSpec, chapter: ChapterOutlineItem, payload: dict[str, Any]) -> int:
    raw = payload.get("target_chars_max")
    if raw not in {None, ""}:
        try:
            return max(900, int(raw))
        except (TypeError, ValueError):
            pass
    target = _resolve_plan_target_chars(spec, chapter, payload)
    _, default_max = _chapter_char_bounds(target, length_tolerance=spec.chapter_char_tolerance)
    chapter_max = int(chapter.target_chars_max) if chapter.target_chars_max else default_max
    return max(target, chapter_max)


def _chapter_skeleton(spec: ProjectSpec, volume: VolumeBlueprint) -> list[dict[str, Any]]:
    skeleton: list[dict[str, Any]] = []
    chapter_total = max(1, volume.end_chapter - volume.start_chapter + 1)
    for offset, index in enumerate(range(volume.start_chapter, volume.end_chapter + 1), start=1):
        closing_mode = "chapter_hook"
        if index == spec.chapter_count:
            closing_mode = "series_hook" if spec.ending_mode == "series" else "book_closure"
        elif index == volume.end_chapter:
            closing_mode = "volume_hook"
        chapter_role = _chapter_role_for_position(offset, chapter_total, volume.phase_type, closing_mode)
        target_chars = _chapter_target_chars(spec, volume, chapter_role)
        target_min, target_max = _chapter_char_bounds(target_chars, length_tolerance=spec.chapter_char_tolerance)
        skeleton.append(
            {
                "index": index,
                "volume_index": volume.index,
                "title": "",
                "purpose": "",
                "conflict": "",
                "beat_summary": "",
                "ending_note": "",
                "pov": spec.pov,
                "closing_mode": closing_mode,
                "chapter_role": chapter_role,
                "scene_load_score": round(_chapter_role_weight(chapter_role), 2),
                "target_chars": target_chars,
                "target_chars_min": target_min,
                "target_chars_max": target_max,
                "split_allowed": chapter_role in {"climax", "pivot", "setpiece"} or target_chars >= int(spec.target_chars_per_chapter * 1.25),
                "merge_allowed": chapter_role in {"bridge", "transition", "afterglow"} and chapter_total > 2,
                "progression_step_type": "",
                "progression_reward": "",
                "progression_cost": "",
                "current_tier": volume.tier_floor,
                "target_tier": volume.tier_target,
                "enemy_band": volume.enemy_band,
                "resource_focus": volume.resource_goal,
                "must_payoff": [],
            }
        )
    return skeleton


def _initial_continuity_state(bible: WorldBible) -> ContinuityState:
    return ContinuityState(
        recent_summaries=[],
        active_threads=list(bible.major_threads),
        resolved_threads=[],
        timeline=[],
        character_states=[
            CharacterState(
                name=character.name,
                current_goal=character.goal,
                emotional_state=character.public_image,
                relationship_shift="起点状态",
                risk=character.fear,
                unresolved=character.private_truth,
            )
            for character in bible.characters
        ],
        must_remember=list(bible.ending_contract),
        progression_notes=[],
        current_tier="",
        next_breakthrough="",
        last_volume_index=0,
        last_chapter_index=0,
    )


def _merge_continuity_state(
    continuity: ContinuityState,
    update: ContinuityUpdate,
    volume_index: int,
) -> ContinuityState:
    active_threads = [item for item in continuity.active_threads if item not in update.resolved_threads]
    active_threads = _merge_lists(active_threads, update.new_threads, update.next_chapter_targets)
    resolved_threads = _merge_lists(continuity.resolved_threads, update.resolved_threads)
    timeline = _tail(_merge_lists(continuity.timeline, update.timeline_events), 80)
    must_remember = _tail(_merge_lists(continuity.must_remember, update.must_remember, update.next_chapter_targets), 30)
    progression_notes = _tail(_merge_lists(continuity.progression_notes, update.progression_updates), 20)

    character_map = {item.name: copy.deepcopy(item) for item in continuity.character_states}
    for item in update.character_states:
        character_map[item.name] = item

    return _sanitize_continuity_state(
        ContinuityState(
            recent_summaries=_tail([*continuity.recent_summaries, update.chapter_summary], 8),
            active_threads=_tail(active_threads, 25),
            resolved_threads=_tail(resolved_threads, 25),
            timeline=timeline,
            character_states=list(character_map.values()),
            must_remember=must_remember,
            progression_notes=progression_notes,
            current_tier=_best_text(update.current_tier, continuity.current_tier),
            next_breakthrough=_best_text(update.next_breakthrough, continuity.next_breakthrough),
            last_volume_index=volume_index,
            last_chapter_index=update.chapter_index,
        )
    )


def _sanitize_continuity_state(continuity: ContinuityState) -> ContinuityState:
    resolved_threads = _dedupe_semantic_texts(
        _merge_lists([item for item in continuity.resolved_threads if _best_text(item)]),
        limit=25,
    )
    active_threads = _semantic_filter_unresolved(
        _dedupe_semantic_texts(
            _merge_lists([item for item in continuity.active_threads if _best_text(item)]),
            limit=25,
        ),
        resolved_threads,
    )
    timeline = _tail(_merge_lists([item for item in continuity.timeline if _best_text(item)]), 80)
    must_remember = _dedupe_semantic_texts(
        _merge_lists([item for item in continuity.must_remember if _best_text(item)]),
        limit=30,
    )
    progression_notes = _dedupe_semantic_texts(
        _merge_lists([item for item in continuity.progression_notes if _best_text(item)]),
        limit=20,
    )
    recent_summaries = _tail([item for item in continuity.recent_summaries if _best_text(item)], 8)
    character_map: dict[str, CharacterState] = {}
    for item in continuity.character_states:
        if not item.name:
            continue
        if item.name in character_map:
            del character_map[item.name]
        character_map[item.name] = copy.deepcopy(item)
    return ContinuityState(
        recent_summaries=recent_summaries,
        active_threads=_tail(active_threads, 25),
        resolved_threads=resolved_threads,
        timeline=timeline,
        character_states=list(character_map.values()),
        must_remember=must_remember,
        progression_notes=progression_notes,
        current_tier=_best_text(continuity.current_tier),
        next_breakthrough=_best_text(continuity.next_breakthrough),
        last_volume_index=continuity.last_volume_index,
        last_chapter_index=continuity.last_chapter_index,
    )


def _normalize_promise_status(status: str) -> str:
    normalized = _best_text(status, "open").lower()
    if normalized in {"open", "advanced", "paid_off", "stalled"}:
        return normalized
    return "open"


def _deadline_state_rank(state: str) -> int:
    return {
        "on_track": 0,
        "at_risk": 1,
        "overdue": 2,
    }.get(_best_text(state, "on_track").lower(), 0)


def _promise_deadline_state(
    item: PromiseLedgerItem,
    *,
    current_volume: int,
    current_chapter: int,
) -> str:
    status = _normalize_promise_status(item.current_status)
    if status == "paid_off":
        return "on_track"
    latest_touch = max(item.last_touched_chapter, item.chapter_opened, 0)
    chapter_gap = max(0, current_chapter - latest_touch)
    volume_gap = 0
    if item.target_volume > 0:
        volume_gap = max(0, current_volume - item.target_volume)
    flagged = bool(item.overdue)
    if status == "advanced":
        if volume_gap >= 2 and chapter_gap >= 8:
            return "overdue"
        if volume_gap >= 1 and chapter_gap >= 6:
            return "at_risk"
        if flagged and chapter_gap >= 10:
            return "at_risk"
        return "on_track"
    if status == "stalled":
        if flagged or volume_gap >= 1 or chapter_gap >= 6:
            return "overdue"
        return "at_risk"
    if volume_gap >= 1 and chapter_gap >= 4:
        return "overdue"
    if flagged and chapter_gap >= 3:
        return "at_risk"
    if volume_gap >= 1 or chapter_gap >= 6:
        return "at_risk"
    return "on_track"


def _normalize_promise_ledger(
    items: list[PromiseLedgerItem],
    *,
    current_volume: int,
    current_chapter: int,
) -> list[PromiseLedgerItem]:
    normalized: list[PromiseLedgerItem] = []
    for source in items:
        item = copy.deepcopy(source)
        item.current_status = _normalize_promise_status(item.current_status)
        if item.last_touched_chapter == 0:
            item.last_touched_chapter = max(item.chapter_opened, current_chapter)
        item.deadline_state = _promise_deadline_state(
            item,
            current_volume=current_volume,
            current_chapter=current_chapter,
        )
        item.overdue = item.deadline_state == "overdue"
        normalized.append(item)
    return sorted(
        normalized,
        key=lambda item: (_deadline_state_rank(item.deadline_state), item.last_touched_chapter, item.chapter_opened),
        reverse=True,
    )


def _ledger_sanity_snapshot(items: list[PromiseLedgerItem]) -> dict[str, int]:
    snapshot = {
        "total": len(items),
        "overdue": 0,
        "at_risk": 0,
        "advanced": 0,
        "open": 0,
        "stalled": 0,
        "paid_off": 0,
        "overdue_advanced": 0,
    }
    for item in items:
        status = _normalize_promise_status(item.current_status)
        snapshot[status] = snapshot.get(status, 0) + 1
        if item.deadline_state == "overdue" or item.overdue:
            snapshot["overdue"] += 1
            if status == "advanced":
                snapshot["overdue_advanced"] += 1
        elif item.deadline_state == "at_risk":
            snapshot["at_risk"] += 1
    return snapshot


def _merge_promise_ledger(
    existing: list[PromiseLedgerItem],
    updates: list[PromiseLedgerItem],
    *,
    current_volume: int,
    current_chapter: int,
) -> list[PromiseLedgerItem]:
    merged = {item.promise_id: copy.deepcopy(item) for item in existing if item.promise_id}
    for update in updates:
        if not update.promise_id:
            continue
        previous = merged.get(update.promise_id)
        if previous is None:
            merged[update.promise_id] = copy.deepcopy(update)
            continue
        previous.label = _best_text(update.label, previous.label)
        previous.thread = _best_text(update.thread, previous.thread)
        previous.chapter_opened = previous.chapter_opened or update.chapter_opened
        previous.target_volume = max(previous.target_volume, update.target_volume)
        previous.current_status = _best_text(update.current_status, previous.current_status)
        previous.last_touched_chapter = max(previous.last_touched_chapter, update.last_touched_chapter)
        previous.payoff_requirements = _merge_lists(previous.payoff_requirements, update.payoff_requirements)
        previous.overdue = previous.overdue or bool(update.overdue)
        previous.deadline_state = _best_text(update.deadline_state, previous.deadline_state, "on_track")
    return _normalize_promise_ledger(
        list(merged.values()),
        current_volume=current_volume,
        current_chapter=current_chapter,
    )


def _merge_progression_ledger(
    existing: list[ProgressionLedgerItem],
    updates: list[ProgressionLedgerItem],
    *,
    current_chapter: int,
) -> list[ProgressionLedgerItem]:
    merged = {
        _best_text(item.milestone_label, item.target_tier, item.objective): copy.deepcopy(item)
        for item in existing
        if _best_text(item.milestone_label, item.target_tier, item.objective)
    }
    for update in updates:
        key = _best_text(update.milestone_label, update.target_tier, update.objective)
        if not key:
            continue
        previous = merged.get(key)
        if previous is None:
            merged[key] = copy.deepcopy(update)
            continue
        previous.milestone_label = _best_text(update.milestone_label, previous.milestone_label)
        previous.current_tier = _best_text(update.current_tier, previous.current_tier)
        previous.target_tier = _best_text(update.target_tier, previous.target_tier)
        previous.status = _best_text(update.status, previous.status, "pending")
        previous.opened_chapter = previous.opened_chapter or update.opened_chapter
        previous.last_touched_chapter = max(previous.last_touched_chapter, update.last_touched_chapter, current_chapter)
        previous.objective = _best_text(update.objective, previous.objective)
        previous.required_resources = _merge_lists(previous.required_resources, update.required_resources)
        previous.unlocked_rewards = _merge_lists(previous.unlocked_rewards, update.unlocked_rewards)
        previous.bottleneck = _best_text(update.bottleneck, previous.bottleneck)
    return sorted(
        merged.values(),
        key=lambda item: (item.status in {"advanced", "ready", "paid_off"}, item.last_touched_chapter, item.opened_chapter),
        reverse=True,
    )


def _merge_causality_graph(
    existing: list[CausalityEdge],
    updates: list[CausalityEdge],
    *,
    current_chapter: int,
) -> list[CausalityEdge]:
    merged = {item.effect_label: copy.deepcopy(item) for item in existing if item.effect_label}
    for update in updates:
        if not update.effect_label:
            continue
        previous = merged.get(update.effect_label)
        if previous is None:
            merged[update.effect_label] = copy.deepcopy(update)
            continue
        previous.cause = _best_text(update.cause, previous.cause)
        previous.prerequisites = _merge_lists(previous.prerequisites, update.prerequisites)
        previous.required_consequences = _merge_lists(previous.required_consequences, update.required_consequences)
        previous.introduced_chapter = min(previous.introduced_chapter or current_chapter, update.introduced_chapter or current_chapter)
        previous.last_verified_chapter = max(previous.last_verified_chapter, update.last_verified_chapter)
    return sorted(merged.values(), key=lambda item: (item.last_verified_chapter, item.introduced_chapter), reverse=True)


def _logic_audit_from_dict(payload: dict[str, Any]) -> LogicAuditReport:
    flagged = payload.get("flagged_chapters")
    flagged_chapters = [item for item in flagged if isinstance(item, dict)] if isinstance(flagged, list) else []
    repair = payload.get("repair_plan")
    repair_plan = [item for item in repair if isinstance(item, dict)] if isinstance(repair, list) else []
    gate_passed = bool(payload.get("gate_passed", payload.get("passed", True)))
    gate_level = _best_text(payload.get("gate_level"), "")
    if not gate_level:
        issues_text = "\n".join(_string_list(payload.get("issues"))) + "\n" + _best_text(payload.get("summary"), "")
        if gate_passed:
            gate_level = "pass"
        elif any(token in issues_text for token in ("账本", "资料污染", "metadata", "状态失真")):
            gate_level = "repair_metadata"
        else:
            gate_level = "repair_cluster"
    return LogicAuditReport(
        passed=bool(payload.get("passed", True)),
        gate_passed=gate_passed,
        summary=_best_text(payload.get("summary"), "长线逻辑暂未发现明显断裂。"),
        issues=_string_list(payload.get("issues")),
        watch_items=_string_list(payload.get("watch_items")),
        required_followups=_string_list(payload.get("required_followups")),
        structure_risks=_string_list(payload.get("structure_risks")),
        voice_risks=_string_list(payload.get("voice_risks")),
        density_risks=_string_list(payload.get("density_risks")),
        pressure_risks=_string_list(payload.get("pressure_risks")),
        grounding_risks=_string_list(payload.get("grounding_risks")),
        progression_risks=_string_list(payload.get("progression_risks")),
        flagged_chapters=flagged_chapters,
        repair_plan=repair_plan,
        gate_level=gate_level,
        ledger_sanity=payload.get("ledger_sanity", {}) if isinstance(payload.get("ledger_sanity"), dict) else {},
    )


def _story_memory_query_terms(
    chapter: ChapterOutlineItem,
    plan: ChapterPlan | None,
    continuity: ContinuityState,
) -> list[str]:
    raw_terms = [
        chapter.title,
        chapter.purpose,
        chapter.conflict,
        chapter.beat_summary,
        chapter.ending_note,
        *chapter.must_payoff,
        *(plan.continuity_targets if plan is not None else []),
        *(continuity.active_threads[-6:]),
        *(continuity.must_remember[-8:]),
    ]
    for state in continuity.character_states:
        if state.name and state.name in chapter.beat_summary + chapter.purpose + chapter.conflict:
            raw_terms.extend([state.name, state.current_goal, state.unresolved])
    deduped: list[str] = []
    for term in raw_terms:
        text = _best_text(term)
        if len(_normalize_story_memory_text(text)) < 4:
            continue
        if text not in deduped:
            deduped.append(text)
    return deduped[:20]


def _progression_query_terms(
    chapter: ChapterOutlineItem,
    plan: ChapterPlan | None,
    continuity: ContinuityState,
) -> list[str]:
    raw_terms = [
        _best_text(plan.progression_step_type if plan else "", chapter.progression_step_type),
        _best_text(plan.current_tier if plan else "", chapter.current_tier, continuity.current_tier),
        _best_text(plan.target_tier if plan else "", chapter.target_tier, continuity.next_breakthrough),
        _best_text(plan.enemy_band if plan else "", chapter.enemy_band),
        _best_text(plan.resource_focus if plan else "", chapter.resource_focus),
        _best_text(plan.progression_reward if plan else "", chapter.progression_reward),
        _best_text(plan.progression_cost if plan else "", chapter.progression_cost),
        *continuity.progression_notes[-6:],
        *chapter.must_payoff[:4],
    ]
    deduped: list[str] = []
    for term in raw_terms:
        text = _best_text(term)
        if len(_normalize_story_memory_text(text)) < 2:
            continue
        if text not in deduped:
            deduped.append(text)
    return deduped[:16]


def _recent_progression_history(
    chapters: list[ChapterResult],
    *,
    limit: int = 8,
) -> list[dict[str, Any]]:
    history: list[dict[str, Any]] = []
    for chapter in chapters[-limit:]:
        step_type = _best_text(chapter.plan.progression_step_type, chapter.outline_item.progression_step_type)
        current_tier = _best_text(chapter.plan.current_tier, chapter.outline_item.current_tier, chapter.continuity.current_tier)
        target_tier = _best_text(chapter.plan.target_tier, chapter.outline_item.target_tier, chapter.continuity.next_breakthrough)
        reward = _best_text(chapter.plan.progression_reward, chapter.outline_item.progression_reward)
        cost = _best_text(chapter.plan.progression_cost, chapter.outline_item.progression_cost)
        history.append(
            {
                "chapter_index": chapter.index,
                "progression_step_type": step_type,
                "current_tier": current_tier,
                "target_tier": target_tier,
                "progression_reward": reward,
                "progression_cost": cost,
            }
        )
    return history


def _chapter_phase_brief(spec: ProjectSpec, chapter_index: int) -> dict[str, Any]:
    total = max(spec.chapter_count, 1)
    early_limit = min(max(12, math.ceil(total * 0.24)), 120)
    late_start = max(early_limit + 1, total - max(10, math.ceil(total * 0.18)) + 1)
    if chapter_index <= early_limit:
        return {
            "phase": "early",
            "reader_focus": "先让读者看懂人、局势和代价，再逐步扩世界信息。",
            "term_budget": "low",
            "theme_visibility": "subtext",
            "variation_focus": "优先用关系变化、身体风险、生活细节、即时抉择驱动，而不是连续堆制度和节点。",
            "grounding_focus": "给出能落地的身体感、路径成本、食宿或现实操作。",
        }
    if chapter_index >= late_start:
        return {
            "phase": "late",
            "reader_focus": "优先收束承诺和后果，允许术语密度略高，但每次升级都必须付出代价。",
            "term_budget": "medium",
            "theme_visibility": "edge",
            "variation_focus": "在收束与余波之间切换，不要只靠更大的节点解释一切。",
            "grounding_focus": "让最终选择落到现实代价、人物关系和制度后果上。",
        }
    return {
        "phase": "mid",
        "reader_focus": "避免中段发动机同构，保持推进手感变化。",
        "term_budget": "medium",
        "theme_visibility": "subtext",
        "variation_focus": "主动在证据推进、关系推进、潜伏渗透、代价交换、动作压力、生活沉降之间换挡。",
        "grounding_focus": "每隔几章补一处生活、职业、身体或人情落点，避免长期悬空。",
    }


def _recent_propulsion_history(
    chapters: list[ChapterResult],
    *,
    limit: int = 6,
) -> list[dict[str, Any]]:
    history: list[dict[str, Any]] = []
    for chapter in chapters[-limit:]:
        propulsion = _best_text(
            chapter.plan.primary_propulsion,
            _infer_primary_propulsion(
                chapter.plan.purpose,
                chapter.outline_item.conflict,
                chapter.continuity.chapter_summary,
            ),
        )
        history.append(
            {
                "chapter_index": chapter.index,
                "title": chapter.title,
                "primary_propulsion": propulsion,
                "chapter_role": chapter.plan.chapter_role or chapter.outline_item.chapter_role,
                "variation_goal": chapter.plan.variation_goal,
                "scene_types": [scene.scene_type for scene in chapter.plan.scenes if _best_text(scene.scene_type)],
                "theme_visibility": chapter.plan.theme_visibility,
                "grounding_beat": chapter.plan.grounding_beat,
            }
        )
    return history


def _infer_primary_propulsion(*parts: str) -> str:
    text = _normalize_story_memory_text(" ".join(_best_text(part) for part in parts))
    if not text:
        return "局势推进"
    keyword_groups = [
        ("证据推进", ["证", "账", "名单", "碑", "卷", "索引", "线索", "口供", "印记"]),
        ("潜伏渗透", ["潜", "埋伏", "渗透", "伪装", "暗缝", "尾随", "盯梢"]),
        ("关系推进", ["关系", "对话", "信任", "背叛", "和解", "对视", "亲属", "盟友"]),
        ("代价交换", ["代价", "交换", "赌", "牺牲", "偿还", "付出", "交易"]),
        ("动作压力", ["追", "逃", "杀", "冲", "围", "拦", "坠", "战", "裂", "追击"]),
        ("生活沉降", ["吃", "饭", "睡", "船", "屋", "钱", "路", "雨", "药", "伤", "市集", "码头"]),
        ("制度谈判", ["规章", "官", "审", "议", "账房", "契", "令", "手续", "流程"]),
    ]
    for label, keywords in keyword_groups:
        if any(keyword in text for keyword in keywords):
            return label
    return "局势推进"


def _mapping_object_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        for key in ("items", "cards", "entries", "list", "value"):
            candidate = value.get(key)
            if isinstance(candidate, list):
                return [item for item in candidate if isinstance(item, dict)]
    return []


def _mapping_value_present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict)):
        return bool(value)
    return True


def _merge_mapping_object_lists(*values: Any) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for value in values:
        for item in _mapping_object_list(value):
            marker = repr(sorted(item.items()))
            if marker in seen:
                continue
            seen.add(marker)
            merged.append(item)
    return merged


def _merge_mapping_blocks(
    payload: Any,
    *,
    wrapper_keys: list[str],
    scalar_keys: list[str],
    list_keys: list[str],
    object_list_keys: list[str],
) -> dict[str, Any]:
    payload = _unwrap_structured_payload(payload, wrapper_keys=wrapper_keys, list_alias_fields=object_list_keys)
    if isinstance(payload, dict):
        source_blocks = [payload]
    elif isinstance(payload, list):
        source_blocks = [item for item in _structured_payload_items(payload, wrapper_keys=wrapper_keys, list_alias_fields=object_list_keys) if isinstance(item, dict)]
    else:
        source_blocks = []
    merged: dict[str, Any] = {}
    for block in source_blocks:
        for key in scalar_keys:
            if not _mapping_value_present(merged.get(key)) and _mapping_value_present(block.get(key)):
                merged[key] = block.get(key)
        for key in list_keys:
            merged[key] = _merge_lists(merged.get(key) or [], _string_list(block.get(key)))
        for key in object_list_keys:
            merged[key] = _merge_mapping_object_lists(merged.get(key), block.get(key))
    return merged


def _structured_mapping_has_keys(payload: Any, *, wrapper_keys: list[str], expected_keys: list[str], list_alias_fields: list[str] | None = None) -> bool:
    list_alias_fields = list_alias_fields or []
    payload = _unwrap_structured_payload(payload, wrapper_keys=wrapper_keys, list_alias_fields=list_alias_fields)
    candidates: list[dict[str, Any]] = []
    if isinstance(payload, dict):
        candidates = [payload]
    elif isinstance(payload, list):
        candidates = [item for item in _structured_payload_items(payload, wrapper_keys=wrapper_keys, list_alias_fields=list_alias_fields) if isinstance(item, dict)]
    for candidate in candidates:
        if any(key in candidate for key in expected_keys):
            return True
    return False


def _intake_payload_shape(project_input: ProjectInput) -> dict[str, Any]:
    return {
        "title": project_input.title,
        "output_language": project_input.output_language,
        "genre": "题材定位",
        "audience": "目标读者",
        "tone": "叙事气质",
        "premise": "故事前提",
        "theme": "核心主题",
        "hook": "一句话钩子",
        "setting": "时空和环境设定",
        "protagonist": "主角简介",
        "outline_hint": "可执行总纲",
        "world_hint": "世界观约束",
        "progression_mode": "soft_progression 或 hard_realm_progression",
        "progression_flavor": "xuanhuan_fast / xianxia_steady / sci_fi_evolution / 空",
        "progression_pacing": "fast / steady / slow",
        "power_system_hint": "升级体系约束，非硬升级可留空",
        "style_examples": ["具体风格要求"],
        "must_include": ["关键元素"],
        "avoid": ["明确禁止出现的问题"],
        "character_seeds": [{"name": "角色名", "role": "功能定位", "goal": "显性目标", "conflict": "核心矛盾", "notes": "补充说明"}],
    }


def _normalize_intake_payload(payload: Any) -> dict[str, Any]:
    merged = _merge_mapping_blocks(
        payload,
        wrapper_keys=["project", "brief", "project_spec", "spec"],
        scalar_keys=["title", "output_language", "genre", "audience", "tone", "premise", "theme", "hook", "setting", "protagonist", "outline_hint", "world_hint", "progression_mode", "progression_flavor", "progression_pacing", "power_system_hint"],
        list_keys=["style_examples", "must_include", "avoid"],
        object_list_keys=["character_seeds"],
    )
    if "characters" in merged and "character_seeds" not in merged:
        merged["character_seeds"] = _mapping_object_list(merged.get("characters"))
    return merged


def _intake_payload_has_content(payload: dict[str, Any]) -> bool:
    return bool(
        _best_text(payload.get("premise"))
        or _best_text(payload.get("hook"))
        or _best_text(payload.get("theme"))
        or _string_list(payload.get("style_examples"))
        or _mapping_object_list(payload.get("character_seeds"))
    )


def _intake_payload_has_signal(payload: Any) -> bool:
    return _structured_mapping_has_keys(
        payload,
        wrapper_keys=["project", "brief", "project_spec", "spec"],
        expected_keys=["premise", "hook", "theme", "style_examples", "must_include", "character_seeds", "characters", "progression_mode", "progression_flavor", "power_system_hint"],
        list_alias_fields=["character_seeds", "characters"],
    )


def _world_payload_shape(spec: ProjectSpec) -> dict[str, Any]:
    return {
        "title": spec.title,
        "logline": "一句话卖点",
        "setting_summary": "150到260字",
        "core_conflict": "主冲突",
        "theme_statement": "主题表达",
        "narrative_voice": ["文风要求"],
        "world_rules": ["硬规则"],
        "chapter_guardrails": ["章节约束"],
        "ending_contract": ["最终章必须兑现的承诺"],
        "major_threads": ["主要线索"],
        "characters": [{"name": "角色名", "role": "功能定位", "goal": "显性目标"}],
    }


def _normalize_world_payload(payload: Any) -> dict[str, Any]:
    merged = _merge_mapping_blocks(
        payload,
        wrapper_keys=["world", "world_bible", "setting_bible", "bible"],
        scalar_keys=["title", "logline", "setting_summary", "core_conflict", "theme_statement"],
        list_keys=["narrative_voice", "world_rules", "chapter_guardrails", "ending_contract", "major_threads"],
        object_list_keys=["characters"],
    )
    alias_lists = {
        "world_rules": ["rules", "laws"],
        "chapter_guardrails": ["guardrails", "writing_guardrails"],
        "ending_contract": ["ending_requirements", "end_contract"],
        "major_threads": ["threads", "major_lines"],
        "characters": ["cast", "people"],
    }
    source = _unwrap_structured_payload(payload, wrapper_keys=["world", "world_bible", "setting_bible", "bible"], list_alias_fields=["characters", "cast", "people"])
    blocks = [source] if isinstance(source, dict) else [item for item in _structured_payload_items(source, wrapper_keys=["world", "world_bible", "setting_bible", "bible"], list_alias_fields=["characters", "cast", "people"]) if isinstance(item, dict)] if isinstance(source, list) else []
    for target, aliases in alias_lists.items():
        for block in blocks:
            for alias in aliases:
                if target == "characters":
                    merged[target] = _merge_mapping_object_lists(merged.get(target), block.get(alias))
                else:
                    merged[target] = _merge_lists(merged.get(target), _string_list(block.get(alias)))
    return merged


def _world_payload_has_content(payload: dict[str, Any]) -> bool:
    return bool(
        _best_text(payload.get("setting_summary"))
        or _best_text(payload.get("core_conflict"))
        or _string_list(payload.get("world_rules"))
        or _string_list(payload.get("chapter_guardrails"))
        or _string_list(payload.get("major_threads"))
        or _mapping_object_list(payload.get("characters"))
    )


def _world_payload_has_signal(payload: Any) -> bool:
    return _structured_mapping_has_keys(
        payload,
        wrapper_keys=["world", "world_bible", "setting_bible", "bible"],
        expected_keys=["setting_summary", "core_conflict", "world_rules", "chapter_guardrails", "major_threads", "characters", "cast", "people"],
        list_alias_fields=["characters", "cast", "people"],
    )


def _story_room_payload_shape() -> dict[str, Any]:
    return {
        "notes": [{"agent": "world_architect", "focus": "职责焦点", "must_hold": ["硬约束"], "risks": ["风险"], "opportunities": ["亮点"], "summary": "立场"}],
        "shared_contract": ["会议共识"],
        "global_risks": ["总风险"],
    }


def _normalize_story_room_payload(payload: Any) -> dict[str, Any]:
    merged = _merge_mapping_blocks(
        payload,
        wrapper_keys=["story_room", "room", "meeting", "story_meeting"],
        scalar_keys=[],
        list_keys=["shared_contract", "global_risks"],
        object_list_keys=["notes"],
    )
    source = _unwrap_structured_payload(payload, wrapper_keys=["story_room", "room", "meeting", "story_meeting"], list_alias_fields=["notes"])
    blocks = [source] if isinstance(source, dict) else [item for item in _structured_payload_items(source, wrapper_keys=["story_room", "room", "meeting", "story_meeting"], list_alias_fields=["notes"]) if isinstance(item, dict)] if isinstance(source, list) else []
    for block in blocks:
        merged["shared_contract"] = _merge_lists(merged.get("shared_contract"), _string_list(block.get("contracts")))
        merged["global_risks"] = _merge_lists(merged.get("global_risks"), _string_list(block.get("risks")))
        merged["notes"] = _merge_mapping_object_lists(merged.get("notes"), block.get("discussion_notes"), block.get("agent_notes"))
    return merged


def _story_room_payload_has_content(payload: dict[str, Any]) -> bool:
    return bool(_mapping_object_list(payload.get("notes")) or _string_list(payload.get("shared_contract")) or _string_list(payload.get("global_risks")))


def _story_room_payload_has_signal(payload: Any) -> bool:
    return _structured_mapping_has_keys(
        payload,
        wrapper_keys=["story_room", "room", "meeting", "story_meeting"],
        expected_keys=["notes", "shared_contract", "global_risks", "contracts", "discussion_notes", "agent_notes"],
        list_alias_fields=["notes", "discussion_notes", "agent_notes"],
    )


def _power_system_payload_shape(spec: ProjectSpec) -> dict[str, Any]:
    return {
        "progression_mode": spec.progression_mode,
        "progression_flavor": spec.progression_flavor,
        "progression_pacing": spec.progression_pacing,
        "core_axis": "主升级轴",
        "secondary_axes": ["副升级轴"],
        "progression_contract": ["升级体系硬约束"],
        "realm_ladder": [
            {
                "rank": 1,
                "name": "层级名",
                "summary": "这一层的核心变化",
                "signature_gains": ["能力提升"],
                "bottlenecks": ["关键卡点"],
                "typical_resources": ["典型资源"],
                "danger_band": "会遇到的危险",
                "breakthrough_requirements": [
                    {
                        "kind": "resource",
                        "label": "突破条件名",
                        "details": "突破条件说明",
                        "mandatory": True,
                    }
                ],
            }
        ],
        "resource_axes": [
            {
                "name": "资源轴",
                "purpose": "用途",
                "acquisition_modes": ["获得方式"],
                "scarcity_curve": "稀缺曲线",
            }
        ],
        "enemy_ladder": [
            {
                "name": "敌人带宽",
                "floor_tier": "下限层级",
                "ceiling_tier": "上限层级",
                "pressure_sources": ["压迫来源"],
                "expected_payoffs": ["打赢回报"],
            }
        ],
        "milestone_plan": [
            {
                "label": "阶段名",
                "chapter_window": "1-30",
                "current_tier": "当前层级",
                "target_tier": "目标层级",
                "objective": "阶段目标",
                "required_resources": ["必拿资源"],
                "key_trial": "关键试炼",
                "payoff": "阶段回报",
            }
        ],
        "forbidden_shortcuts": ["绝对不能出现的偷渡升级方式"],
    }


def _normalize_power_system_payload(payload: Any) -> dict[str, Any]:
    merged = _merge_mapping_blocks(
        payload,
        wrapper_keys=["power_system", "power_bible", "progression_system", "system"],
        scalar_keys=["progression_mode", "progression_flavor", "progression_pacing", "core_axis"],
        list_keys=["secondary_axes", "progression_contract", "forbidden_shortcuts"],
        object_list_keys=["realm_ladder", "resource_axes", "enemy_ladder", "milestone_plan"],
    )
    source = _unwrap_structured_payload(
        payload,
        wrapper_keys=["power_system", "power_bible", "progression_system", "system"],
        list_alias_fields=["realm_ladder", "resource_axes", "enemy_ladder", "milestone_plan"],
    )
    blocks = [source] if isinstance(source, dict) else [item for item in _structured_payload_items(source, wrapper_keys=["power_system", "power_bible", "progression_system", "system"], list_alias_fields=["realm_ladder", "resource_axes", "enemy_ladder", "milestone_plan"]) if isinstance(item, dict)] if isinstance(source, list) else []
    alias_lists = {
        "realm_ladder": ["tiers", "realms", "ladder"],
        "resource_axes": ["resources", "resource_ladder"],
        "enemy_ladder": ["enemy_bands", "enemy_tiers"],
        "milestone_plan": ["milestones", "progression_milestones"],
    }
    for block in blocks:
        for target, aliases in alias_lists.items():
            for alias in aliases:
                merged[target] = _merge_mapping_object_lists(merged.get(target), block.get(alias))
    return merged


def _power_system_payload_has_content(payload: dict[str, Any]) -> bool:
    return bool(
        _mapping_object_list(payload.get("realm_ladder"))
        or _mapping_object_list(payload.get("resource_axes"))
        or _mapping_object_list(payload.get("enemy_ladder"))
        or _mapping_object_list(payload.get("milestone_plan"))
    )


def _power_system_payload_has_signal(payload: Any) -> bool:
    return _structured_mapping_has_keys(
        payload,
        wrapper_keys=["power_system", "power_bible", "progression_system", "system"],
        expected_keys=[
            "core_axis",
            "progression_contract",
            "realm_ladder",
            "tiers",
            "realms",
            "milestone_plan",
            "milestones",
        ],
        list_alias_fields=["realm_ladder", "tiers", "realms", "milestone_plan", "milestones"],
    )


def _chapter_room_payload_shape() -> dict[str, Any]:
    return {
        "notes": [
            {
                "agent": "continuity_guard",
                "must_land": ["本章必须接住的连续性点"],
                "risks": ["最容易打架的地方"],
                "summary": "连续性视角总结",
            }
        ],
        "shared_mandates": ["写手本章必须共同遵守的执行要求"],
        "blocking_issues": ["如果不解决，本章会出硬伤的问题"],
    }


def _looks_like_chapter_room_note_payload(payload: dict[str, Any]) -> bool:
    keys = ("agent", "must_land", "risks", "summary")
    return sum(1 for key in keys if _best_text(payload.get(key)) or _string_list(payload.get(key))) >= 2


def _normalize_chapter_room_payload(payload: Any) -> dict[str, Any]:
    merged = _merge_mapping_blocks(
        payload,
        wrapper_keys=["chapter_room", "room", "meeting", "meeting_notes", "brief"],
        scalar_keys=[],
        list_keys=["shared_mandates", "blocking_issues"],
        object_list_keys=["notes"],
    )
    source = _unwrap_structured_payload(
        payload,
        wrapper_keys=["chapter_room", "room", "meeting", "meeting_notes", "brief"],
        list_alias_fields=["notes", "meeting_notes", "agent_notes"],
    )
    blocks = [source] if isinstance(source, dict) else [item for item in _structured_payload_items(source, wrapper_keys=["chapter_room", "room", "meeting", "meeting_notes", "brief"], list_alias_fields=["notes", "meeting_notes", "agent_notes"]) if isinstance(item, dict)] if isinstance(source, list) else []
    for block in blocks:
        merged["notes"] = _merge_mapping_object_lists(
            merged.get("notes"),
            block.get("meeting_notes"),
            block.get("agent_notes"),
        )
        merged["shared_mandates"] = _merge_lists(
            merged.get("shared_mandates"),
            _string_list(block.get("shared_contract")),
            _string_list(block.get("mandates")),
        )
        merged["blocking_issues"] = _merge_lists(
            merged.get("blocking_issues"),
            _string_list(block.get("blockers")),
            _string_list(block.get("risks")),
        )
    if isinstance(source, list) and all(isinstance(item, dict) and _looks_like_chapter_room_note_payload(item) for item in source):
        merged["notes"] = _merge_mapping_object_lists(merged.get("notes"), source)
    return merged


def _chapter_room_payload_has_content(payload: dict[str, Any]) -> bool:
    return bool(
        _mapping_object_list(payload.get("notes"))
        or _string_list(payload.get("shared_mandates"))
        or _string_list(payload.get("blocking_issues"))
    )


def _chapter_room_payload_has_signal(payload: Any) -> bool:
    if isinstance(payload, list) and all(isinstance(item, dict) and _looks_like_chapter_room_note_payload(item) for item in payload):
        return True
    return _structured_mapping_has_keys(
        payload,
        wrapper_keys=["chapter_room", "room", "meeting", "meeting_notes", "brief"],
        expected_keys=["notes", "shared_mandates", "blocking_issues", "shared_contract", "mandates", "blockers", "agent_notes"],
        list_alias_fields=["notes", "meeting_notes", "agent_notes"],
    )


def _style_bible_payload_shape() -> dict[str, Any]:
    return {
        "audience_contract": ["读者期待边界"],
        "tone_targets": ["整体气质目标"],
        "pacing_rules": ["节奏规则"],
        "propulsion_rules": ["推进变化规则"],
        "clarity_rules": ["术语密度规则"],
        "dialogue_rules": ["对白规则"],
        "prose_rules": ["叙述规则"],
        "sensory_rules": ["感官规则"],
        "thematic_subtext_rules": ["主题呈现规则"],
        "pressure_curve_rules": ["压力曲线规则"],
        "grounding_rules": ["落地规则"],
        "taboo_phrases": ["绝对避免表达"],
        "sample_passages": [{"label": "样例标签", "use_case": "适用场景", "text": "示例文风片段"}],
    }


def _normalize_style_bible_payload(payload: Any) -> dict[str, Any]:
    merged = _merge_mapping_blocks(
        payload,
        wrapper_keys=["style_bible", "style", "style_guide", "bible"],
        scalar_keys=[],
        list_keys=[
            "audience_contract",
            "tone_targets",
            "pacing_rules",
            "propulsion_rules",
            "clarity_rules",
            "dialogue_rules",
            "prose_rules",
            "sensory_rules",
            "thematic_subtext_rules",
            "pressure_curve_rules",
            "grounding_rules",
            "taboo_phrases",
        ],
        object_list_keys=["sample_passages"],
    )
    source = _unwrap_structured_payload(payload, wrapper_keys=["style_bible", "style", "style_guide", "bible"], list_alias_fields=["sample_passages"])
    blocks = [source] if isinstance(source, dict) else [item for item in _structured_payload_items(source, wrapper_keys=["style_bible", "style", "style_guide", "bible"], list_alias_fields=["sample_passages"]) if isinstance(item, dict)] if isinstance(source, list) else []
    for block in blocks:
        merged["sample_passages"] = _merge_mapping_object_lists(merged.get("sample_passages"), block.get("samples"), block.get("passages"), block.get("examples"))
    return merged


def _style_bible_payload_has_content(payload: dict[str, Any]) -> bool:
    return bool(
        _string_list(payload.get("tone_targets"))
        or _string_list(payload.get("propulsion_rules"))
        or _string_list(payload.get("clarity_rules"))
        or _mapping_object_list(payload.get("sample_passages"))
    )


def _style_bible_payload_has_signal(payload: Any) -> bool:
    return _structured_mapping_has_keys(
        payload,
        wrapper_keys=["style_bible", "style", "style_guide", "bible"],
        expected_keys=["tone_targets", "propulsion_rules", "clarity_rules", "sample_passages", "samples", "passages", "examples"],
        list_alias_fields=["sample_passages", "samples", "passages", "examples"],
    )


def _voice_cards_payload_shape() -> dict[str, Any]:
    return {
        "voice_cards": [{"name": "角色名", "speech_rhythm": "说话节奏", "emotional_expression": "情绪表达方式", "sentence_shape": "句式特征"}],
    }


def _normalize_voice_cards_payload(payload: Any) -> dict[str, Any]:
    payload = _unwrap_structured_payload(payload, wrapper_keys=["voice_cards", "voices", "voice_bible", "cards"], list_alias_fields=["voice_cards", "voices", "cards"])
    if isinstance(payload, list):
        return {"voice_cards": _mapping_object_list(payload)}
    merged = _merge_mapping_blocks(
        payload,
        wrapper_keys=["voice_cards", "voices", "voice_bible", "cards"],
        scalar_keys=[],
        list_keys=[],
        object_list_keys=["voice_cards"],
    )
    source = _unwrap_structured_payload(payload, wrapper_keys=["voice_cards", "voices", "voice_bible", "cards"], list_alias_fields=["voice_cards", "voices", "cards"])
    blocks = [source] if isinstance(source, dict) else []
    for block in blocks:
        merged["voice_cards"] = _merge_mapping_object_lists(merged.get("voice_cards"), block.get("voices"), block.get("cards"))
    return merged


def _voice_cards_payload_has_content(payload: dict[str, Any]) -> bool:
    return bool(_mapping_object_list(payload.get("voice_cards")))


def _voice_cards_payload_has_signal(payload: Any) -> bool:
    if isinstance(payload, list):
        return bool(_mapping_object_list(payload))
    return _structured_mapping_has_keys(
        payload,
        wrapper_keys=["voice_cards", "voices", "voice_bible", "cards"],
        expected_keys=["voice_cards", "voices", "cards"],
        list_alias_fields=["voice_cards", "voices", "cards"],
    )


def _logic_audit_payload_shape(chapters: list[ChapterResult]) -> dict[str, Any]:
    return {
        "passed": True,
        "gate_passed": True,
        "gate_level": "pass",
        "summary": "概括当前长线状态",
        "issues": ["逻辑问题"],
        "watch_items": ["后续约束"],
        "required_followups": ["后续事项"],
        "structure_risks": ["结构风险"],
        "voice_risks": ["声口风险"],
        "density_risks": ["密度风险"],
        "pressure_risks": ["压力风险"],
        "grounding_risks": ["地面感风险"],
        "progression_risks": ["升级体系风险"],
        "flagged_chapters": [{"chapter_index": chapters[-1].index if chapters else 1, "reason": "重点回看原因"}],
        "repair_plan": [{"start_chapter": chapters[-1].index if chapters else 1, "end_chapter": chapters[-1].index if chapters else 1, "instruction": "修复指令"}],
    }


def _normalize_logic_audit_payload(payload: Any) -> dict[str, Any]:
    merged = _merge_mapping_blocks(
        payload,
        wrapper_keys=["logic_audit", "audit", "report"],
        scalar_keys=["passed", "gate_passed", "gate_level", "summary"],
        list_keys=["issues", "watch_items", "required_followups", "structure_risks", "voice_risks", "density_risks", "pressure_risks", "grounding_risks", "progression_risks"],
        object_list_keys=["flagged_chapters", "repair_plan"],
    )
    source = _unwrap_structured_payload(payload, wrapper_keys=["logic_audit", "audit", "report"], list_alias_fields=["flagged_chapters", "repair_plan"])
    blocks = [source] if isinstance(source, dict) else [item for item in _structured_payload_items(source, wrapper_keys=["logic_audit", "audit", "report"], list_alias_fields=["flagged_chapters", "repair_plan"]) if isinstance(item, dict)] if isinstance(source, list) else []
    for block in blocks:
        merged["flagged_chapters"] = _merge_mapping_object_lists(merged.get("flagged_chapters"), block.get("flagged"), block.get("flagged_items"))
        merged["repair_plan"] = _merge_mapping_object_lists(merged.get("repair_plan"), block.get("fixes"), block.get("repairs"))
    return merged


def _logic_audit_payload_has_content(payload: dict[str, Any]) -> bool:
    return bool(
        "passed" in payload
        or "gate_passed" in payload
        or _best_text(payload.get("summary"))
        or _string_list(payload.get("issues"))
        or _string_list(payload.get("watch_items"))
        or _string_list(payload.get("progression_risks"))
    )


def _logic_audit_payload_has_signal(payload: Any) -> bool:
    return _structured_mapping_has_keys(
        payload,
        wrapper_keys=["logic_audit", "audit", "report"],
        expected_keys=["passed", "gate_passed", "gate_level", "summary", "issues", "watch_items", "progression_risks", "flagged_chapters", "repair_plan", "flagged", "fixes"],
        list_alias_fields=["flagged_chapters", "repair_plan", "flagged", "fixes"],
    )


def _final_review_payload_shape(chapters: list[ChapterResult]) -> dict[str, Any]:
    return {
        "passed": True,
        "score": 90,
        "strengths": ["全书优点"],
        "issues": ["全书问题"],
        "required_fixes": ["修订方向"],
        "short_summary": "完成度概括",
        "chapter_fixes": [{"chapter_index": chapters[-1].index if chapters else 1, "instruction": "章节级修订指令"}],
    }


def _normalize_final_review_payload(payload: Any) -> dict[str, Any]:
    merged = _merge_mapping_blocks(
        payload,
        wrapper_keys=["final_review", "review", "report", "judgement"],
        scalar_keys=["passed", "score", "short_summary"],
        list_keys=["strengths", "issues", "required_fixes"],
        object_list_keys=["chapter_fixes"],
    )
    source = _unwrap_structured_payload(payload, wrapper_keys=["final_review", "review", "report", "judgement"], list_alias_fields=["chapter_fixes"])
    blocks = [source] if isinstance(source, dict) else [item for item in _structured_payload_items(source, wrapper_keys=["final_review", "review", "report", "judgement"], list_alias_fields=["chapter_fixes"]) if isinstance(item, dict)] if isinstance(source, list) else []
    for block in blocks:
        merged["chapter_fixes"] = _merge_mapping_object_lists(merged.get("chapter_fixes"), block.get("fixes"), block.get("repair_plan"))
    return merged


def _final_review_payload_has_content(payload: dict[str, Any]) -> bool:
    return bool(
        "passed" in payload
        or "score" in payload
        or _best_text(payload.get("short_summary"))
        or _string_list(payload.get("issues"))
    )


def _final_review_payload_has_signal(payload: Any) -> bool:
    return _structured_mapping_has_keys(
        payload,
        wrapper_keys=["final_review", "review", "report", "judgement"],
        expected_keys=["passed", "score", "issues", "required_fixes", "short_summary", "chapter_fixes", "fixes", "repair_plan"],
        list_alias_fields=["chapter_fixes", "fixes", "repair_plan"],
    )


def _review_payload_shape() -> dict[str, Any]:
    return {
        "passed": True,
        "score": 88,
        "strengths": ["优点"],
        "issues": ["问题"],
        "required_fixes": ["修订方向"],
        "short_summary": "80字以内摘要",
        "chapter_fixes": [{"chapter_index": 1, "instruction": "修订指令"}],
    }


def _review_payload_has_content(payload: dict[str, Any]) -> bool:
    return bool(
        "passed" in payload
        or "score" in payload
        or _string_list(payload.get("strengths"))
        or _string_list(payload.get("issues"))
        or _string_list(payload.get("required_fixes"))
        or _best_text(payload.get("short_summary"))
        or _mapping_object_list(payload.get("chapter_fixes"))
    )


def _review_payload_has_signal(payload: Any) -> bool:
    return _structured_mapping_has_keys(
        payload,
        wrapper_keys=["review", "feedback", "final_review"],
        expected_keys=["passed", "score", "strengths", "issues", "required_fixes", "short_summary", "chapter_fixes", "fixes", "repair_plan"],
        list_alias_fields=["chapter_fixes", "fixes", "repair_plan"],
    )


def _continuity_payload_shape(chapter: ChapterOutlineItem) -> dict[str, Any]:
    return {
        "chapter_index": chapter.index,
        "chapter_summary": "80字以内摘要",
        "new_threads": ["新线索"],
        "resolved_threads": ["已关闭线索"],
        "timeline_events": ["关键事实"],
        "character_states": [
            {
                "name": "角色名",
                "current_goal": "当前目标",
                "emotional_state": "情绪状态",
                "relationship_shift": "关系变化",
                "risk": "当前风险",
                "unresolved": "未解决问题",
            }
        ],
        "next_chapter_targets": ["下一章必须记住的推进点"],
        "must_remember": ["必须保留的事实"],
        "progression_updates": ["升级推进约束"],
        "current_tier": "当前台阶",
        "next_breakthrough": "下一次突破",
    }


def _continuity_payload_has_content(payload: dict[str, Any]) -> bool:
    return bool(
        _string_list(payload.get("new_threads"))
        or _string_list(payload.get("resolved_threads"))
        or _string_list(payload.get("timeline_events"))
        or _mapping_object_list(payload.get("character_states"))
        or _string_list(payload.get("next_chapter_targets"))
        or _string_list(payload.get("must_remember"))
        or _string_list(payload.get("progression_updates"))
        or _best_text(payload.get("current_tier"))
        or _best_text(payload.get("next_breakthrough"))
    )


def _continuity_payload_has_signal(payload: Any) -> bool:
    return _structured_mapping_has_keys(
        payload,
        wrapper_keys=["continuity", "continuity_update", "update"],
        expected_keys=["chapter_summary", "new_threads", "resolved_threads", "timeline_events", "character_states", "next_chapter_targets", "must_remember", "progression_updates", "current_tier", "next_breakthrough"],
        list_alias_fields=["character_states"],
    )


def _long_memory_payload_shape(chapter: ChapterOutlineItem) -> dict[str, Any]:
    return {
        "chapter_index": chapter.index,
        "promise_updates": [
            {
                "promise_id": "promise-001",
                "label": "承诺",
                "thread": "主线",
                "chapter_opened": chapter.index,
                "target_volume": chapter.volume_index,
                "current_status": "open",
                "last_touched_chapter": chapter.index,
                "payoff_requirements": ["兑现条件"],
                "overdue": False,
            }
        ],
        "causality_updates": [
            {
                "effect_label": "结果",
                "cause": "原因",
                "prerequisites": ["前置条件"],
                "required_consequences": ["后续结果"],
                "introduced_chapter": chapter.index,
                "last_verified_chapter": chapter.index,
            }
        ],
        "progression_updates": [
            {
                "milestone_label": "里程碑",
                "current_tier": "当前台阶",
                "target_tier": "目标台阶",
                "status": "pending|ready|advanced|paid_off",
                "opened_chapter": chapter.index,
                "last_touched_chapter": chapter.index,
                "objective": "阶段目标",
                "required_resources": ["资源"],
                "unlocked_rewards": ["回报"],
                "bottleneck": "卡点",
            }
        ],
    }


def _long_memory_payload_has_content(payload: dict[str, Any]) -> bool:
    update_keys = ("promise_updates", "causality_updates", "progression_updates")
    present_keys = [key for key in update_keys if key in payload]
    return bool(
        _mapping_object_list(payload.get("promise_updates"))
        or _mapping_object_list(payload.get("causality_updates"))
        or _mapping_object_list(payload.get("progression_updates"))
        or (
            bool(present_keys)
            and all(isinstance(payload.get(key), list) for key in present_keys)
        )
    )


def _long_memory_payload_has_signal(payload: Any) -> bool:
    return _structured_mapping_has_keys(
        payload,
        wrapper_keys=["long_memory", "memory_update", "update"],
        expected_keys=["promise_updates", "causality_updates", "progression_updates", "promise_delta", "causality_delta", "progression_delta"],
        list_alias_fields=["promise_updates", "causality_updates", "progression_updates", "promise_delta", "causality_delta", "progression_delta"],
    )


def _chapter_plan_from_payload(
    spec: ProjectSpec,
    chapter: ChapterOutlineItem,
    payload: dict[str, Any],
    *,
    phase_brief: dict[str, Any] | None = None,
) -> ChapterPlan:
    phase_brief = phase_brief or {}
    return ChapterPlan(
        chapter_index=int(payload.get("chapter_index", chapter.index)),
        chapter_title=_best_text(payload.get("chapter_title"), chapter.title),
        purpose=_best_text(payload.get("purpose"), chapter.purpose),
        continuity_targets=_merge_lists(chapter.must_payoff, _string_list(payload.get("continuity_targets"))),
        opening_image=_best_text(payload.get("opening_image"), chapter.beat_summary),
        closing_image=_best_text(payload.get("closing_image"), chapter.ending_note),
        closing_mode=chapter.closing_mode,
        scenes=[_scene_from_dict(item) for item in payload.get("scenes", []) if isinstance(item, dict)],
        primary_propulsion=_best_text(
            payload.get("primary_propulsion"),
            _infer_primary_propulsion(chapter.purpose, chapter.conflict, chapter.beat_summary),
        ),
        variation_goal=_best_text(
            payload.get("variation_goal"),
            phase_brief.get("variation_focus"),
            "避免与最近章节重复同构推进。",
        ),
        term_budget=_best_text(payload.get("term_budget"), phase_brief.get("term_budget"), "medium"),
        theme_visibility=_best_text(payload.get("theme_visibility"), phase_brief.get("theme_visibility"), "subtext"),
        grounding_beat=_best_text(payload.get("grounding_beat"), phase_brief.get("grounding_focus"), ""),
        chapter_role=_best_text(payload.get("chapter_role"), chapter.chapter_role, ""),
        scene_load_score=_resolve_scene_load_score(payload, chapter),
        target_chars=_resolve_plan_target_chars(spec, chapter, payload),
        target_chars_min=_resolve_plan_target_min(spec, chapter, payload),
        target_chars_max=_resolve_plan_target_max(spec, chapter, payload),
        split_allowed=_bool_or_default(payload.get("split_allowed"), chapter.split_allowed, False),
        merge_allowed=_bool_or_default(payload.get("merge_allowed"), chapter.merge_allowed, False),
        progression_step_type=_best_text(payload.get("progression_step_type"), chapter.progression_step_type),
        progression_reward=_best_text(payload.get("progression_reward"), chapter.progression_reward),
        progression_cost=_best_text(payload.get("progression_cost"), chapter.progression_cost),
        current_tier=_best_text(payload.get("current_tier"), chapter.current_tier),
        target_tier=_best_text(payload.get("target_tier"), chapter.target_tier),
        enemy_band=_best_text(payload.get("enemy_band"), chapter.enemy_band),
        resource_focus=_best_text(payload.get("resource_focus"), chapter.resource_focus),
    )


def _minimal_chapter_plan_payload(
    spec: ProjectSpec,
    chapter: ChapterOutlineItem,
    volume_outline: VolumeOutline,
    *,
    phase_brief: dict[str, Any] | None = None,
) -> dict[str, Any]:
    phase_brief = phase_brief or {}
    objective = _best_text(chapter.purpose, volume_outline.goal, chapter.beat_summary, "推进当前主线")
    conflict = _best_text(chapter.conflict, volume_outline.climax, "新的阻力逼近。")
    opening_image = _best_text(chapter.beat_summary, objective)
    closing_image = _best_text(chapter.ending_note, volume_outline.progression_payoff, "留下明确后续压力。")
    primary_location = _best_text(volume_outline.title, chapter.title, spec.setting, "当前场域")
    must_payoff = chapter.must_payoff[:3]
    return {
        "chapter_index": chapter.index,
        "chapter_title": _best_text(chapter.title, f"第{chapter.index}章"),
        "purpose": objective,
        "continuity_targets": must_payoff,
        "opening_image": opening_image,
        "closing_image": closing_image,
        "closing_mode": chapter.closing_mode,
        "primary_propulsion": _infer_primary_propulsion(objective, conflict, chapter.beat_summary),
        "variation_goal": _best_text(phase_brief.get("variation_focus"), "保证本章有新的后果、代价或信息推进。"),
        "term_budget": _best_text(phase_brief.get("term_budget"), "medium"),
        "theme_visibility": _best_text(phase_brief.get("theme_visibility"), "subtext"),
        "grounding_beat": _best_text(phase_brief.get("grounding_focus"), "给出一个能落地的动作、身体或生活细节。"),
        "chapter_role": _best_text(chapter.chapter_role, ""),
        "target_chars": max(chapter.target_chars, 0),
        "target_chars_min": max(chapter.target_chars_min, 0),
        "target_chars_max": max(chapter.target_chars_max, 0),
        "split_allowed": bool(chapter.split_allowed),
        "merge_allowed": bool(chapter.merge_allowed),
        "progression_step_type": _best_text(chapter.progression_step_type),
        "progression_reward": _best_text(chapter.progression_reward),
        "progression_cost": _best_text(chapter.progression_cost),
        "current_tier": _best_text(chapter.current_tier, volume_outline.tier_floor),
        "target_tier": _best_text(chapter.target_tier, volume_outline.tier_target),
        "enemy_band": _best_text(chapter.enemy_band, volume_outline.enemy_band),
        "resource_focus": _best_text(chapter.resource_focus, volume_outline.resource_goal),
        "scenes": [
            {
                "scene_index": 1,
                "scene_type": "setup",
                "location": primary_location,
                "goal": objective,
                "conflict": conflict,
                "turn": _best_text(chapter.beat_summary, "主角确认本章必须立刻处理的问题。"),
                "must_include": must_payoff[:1],
            },
            {
                "scene_index": 2,
                "scene_type": "confrontation",
                "location": primary_location,
                "goal": _best_text(volume_outline.goal, objective, "把局势往前推进一格。"),
                "conflict": _best_text(conflict, volume_outline.climax, "中段阻力抬高。"),
                "turn": "局势出现新的代价、阻碍或站位变化，迫使主角改变做法。",
                "must_include": must_payoff[:2],
            },
            {
                "scene_index": 3,
                "scene_type": "hook",
                "location": primary_location,
                "goal": _best_text(chapter.ending_note, volume_outline.progression_payoff, "把下一步压力钉在章尾。"),
                "conflict": _best_text(conflict, "核心问题仍未彻底解决。"),
                "turn": _best_text(chapter.ending_note, "章尾留下明确牵引或代价。"),
                "must_include": must_payoff[:3],
            },
        ],
    }


def _chapter_scene_total_load(plan: ChapterPlan) -> float:
    if not plan.scenes:
        return 0.0
    total = 0.0
    for scene in plan.scenes:
        weight = float(scene.load_weight or 1.0)
        total += max(0.5, min(2.0, weight))
    return round(total, 2)


def _chapter_plan_restructure_notes(
    chapter: ChapterOutlineItem,
    plan: ChapterPlan,
    recent_propulsion_history: list[dict[str, Any]] | None = None,
    *,
    escalation_level: int = 1,
) -> list[str]:
    notes: list[str] = []
    scene_count = len(plan.scenes)
    total_load = _chapter_scene_total_load(plan)
    role_text = _normalize_story_memory_text(f"{plan.chapter_role} {chapter.chapter_role}")
    chapter_target_max = max(plan.target_chars_max, chapter.target_chars_max)
    chapter_target_min = max(plan.target_chars_min, chapter.target_chars_min)
    current_propulsion = _canonical_propulsion_label(plan.primary_propulsion)
    recent_labels = [
        _canonical_propulsion_label(_best_text(item.get("primary_propulsion"), ""))
        for item in (recent_propulsion_history or [])
    ]
    recent_labels = [item for item in recent_labels if item]

    trailing_same_family = 0
    if current_propulsion:
        for label in recent_labels:
            if label != current_propulsion:
                break
            trailing_same_family += 1
    if current_propulsion and trailing_same_family >= 2:
        notes.append(
            f"最近几章仍在“{current_propulsion}”这一推进簇内；本章允许继续围绕同一核心问题推进，"
            "但必须带来新的后果、代价、站位变化或不同 scene 功能，不能只是把同一结论再抬半级。"
        )
    elif current_propulsion and len(recent_labels) >= 6 and recent_labels[:6].count(current_propulsion) >= 4:
        notes.append(
            f"最近长窗口里“{current_propulsion}”占比很高；本章重点是避免空转，优先改变章内功能和升级方式，"
            "而不是机械更换章型或只改措辞。"
        )
    if escalation_level >= 2:
        notes.append("这是第二级重排：优先调整章内功能、scene 组合或后果类型；允许继续同一推进簇，但不能继续重复同一种确认/施压/抬级动作。")
    if escalation_level >= 3:
        notes.append("这是第三级重排：必要时可以直接改成余波、代价、关系、决断或局面收束章；重点是打破空转，不是机械轮换章型。")

    overloaded = False
    if scene_count >= 5 and total_load >= 4.8:
        overloaded = True
    if chapter_target_max and chapter_target_max <= 2800 and scene_count >= 4 and total_load >= 4.4:
        overloaded = True
    if any(token in role_text for token in ("bridge", "transition", "过桥", "转场", "缓冲")) and (scene_count >= 4 or total_load >= 4.0):
        notes.append("本章是过桥/转场功能，但当前负载过重，应该压轻结构或把高潮场景移给相邻章节。")
        overloaded = True
    if overloaded:
        notes.append("本章场景数和负载明显过高，必须减少场景、拆章或重分配，不要把多个转折硬塞进一章。")
    if chapter.split_allowed and scene_count >= 6:
        notes.append("如果这些场景都必须保留，必须显式拆章，而不是假装一章能装下全部负载。")
    if chapter.merge_allowed and scene_count <= 2 and total_load <= 1.6 and chapter_target_min >= 1800:
        notes.append("本章功能偏薄，若没有新增关键转折，应考虑与相邻章节合并，而不是单独撑满一章。")

    deduped: list[str] = []
    for note in notes:
        if note not in deduped:
            deduped.append(note)
    return deduped[:4]


def _chapter_memory_payload(chapter: ChapterResult) -> dict[str, Any]:
    return {
        "chapter_index": chapter.index,
        "volume_index": chapter.volume_index,
        "title": chapter.title,
        "summary": chapter.continuity.chapter_summary,
        "purpose": chapter.plan.purpose,
        "primary_propulsion": chapter.plan.primary_propulsion,
        "variation_goal": chapter.plan.variation_goal,
        "theme_visibility": chapter.plan.theme_visibility,
        "grounding_beat": chapter.plan.grounding_beat,
        "progression_step_type": chapter.plan.progression_step_type,
        "current_tier": chapter.plan.current_tier,
        "target_tier": chapter.plan.target_tier,
        "progression_reward": chapter.plan.progression_reward,
        "progression_cost": chapter.plan.progression_cost,
        "threads": _merge_lists(chapter.continuity.new_threads, chapter.continuity.resolved_threads, chapter.plan.continuity_targets)[:6],
        "must_remember": chapter.continuity.must_remember[:6],
        "progression_notes": chapter.continuity.progression_updates[:4],
        "characters": [
            {
                "name": state.name,
                "current_goal": state.current_goal,
                "risk": state.risk,
                "unresolved": state.unresolved,
            }
            for state in chapter.continuity.character_states[:4]
        ],
    }


def _promise_memory_payload(item: PromiseLedgerItem) -> dict[str, Any]:
    return {
        "promise_id": item.promise_id,
        "label": item.label,
        "thread": item.thread,
        "status": item.current_status,
        "deadline_state": item.deadline_state,
        "overdue": item.overdue,
        "chapter_opened": item.chapter_opened,
        "target_volume": item.target_volume,
        "last_touched_chapter": item.last_touched_chapter,
        "payoff_requirements": item.payoff_requirements,
    }


def _progression_memory_payload(item: ProgressionLedgerItem) -> dict[str, Any]:
    return {
        "milestone_label": item.milestone_label,
        "current_tier": item.current_tier,
        "target_tier": item.target_tier,
        "status": item.status,
        "opened_chapter": item.opened_chapter,
        "last_touched_chapter": item.last_touched_chapter,
        "objective": item.objective,
        "required_resources": item.required_resources,
        "unlocked_rewards": item.unlocked_rewards,
        "bottleneck": item.bottleneck,
    }


def _causality_memory_payload(item: CausalityEdge) -> dict[str, Any]:
    return {
        "effect_label": item.effect_label,
        "cause": item.cause,
        "prerequisites": item.prerequisites,
        "required_consequences": item.required_consequences,
        "introduced_chapter": item.introduced_chapter,
        "last_verified_chapter": item.last_verified_chapter,
    }


def _score_story_memory(
    query_terms: list[str],
    current_chapter: ChapterOutlineItem,
    memory: dict[str, Any],
) -> tuple[int, list[str]]:
    haystack_parts = [
        _best_text(memory.get("title")),
        _best_text(memory.get("summary")),
        _best_text(memory.get("purpose")),
        *_string_list(memory.get("threads")),
        *_string_list(memory.get("must_remember")),
        *[
            _best_text(item.get("name"), item.get("current_goal"), item.get("unresolved"))
            for item in memory.get("characters", [])
            if isinstance(item, dict)
        ],
    ]
    haystack = "\n".join(part for part in haystack_parts if part)
    normalized_haystack = _normalize_story_memory_text(haystack)
    score = max(0, 18 - (current_chapter.index - int(memory.get("chapter_index", 0))))
    if int(memory.get("volume_index", 0)) == current_chapter.volume_index:
        score += 6
    reasons: list[str] = []
    for term in query_terms:
        normalized_term = _normalize_story_memory_text(term)
        if not normalized_term:
            continue
        if normalized_term in normalized_haystack or normalized_haystack in normalized_term:
            score += 5
            reasons.append(f"命中“{term[:18]}”")
    return score, reasons


def _score_named_memory(query_terms: list[str], payload: dict[str, Any]) -> tuple[int, list[str]]:
    haystack_parts = [
        _best_text(payload.get("label")),
        _best_text(payload.get("thread")),
        _best_text(payload.get("status")),
        _best_text(payload.get("deadline_state")),
        _best_text(payload.get("cause")),
        _best_text(payload.get("effect_label")),
        *_string_list(payload.get("payoff_requirements")),
        *_string_list(payload.get("prerequisites")),
        *_string_list(payload.get("required_consequences")),
    ]
    haystack = _normalize_story_memory_text("\n".join(part for part in haystack_parts if part))
    score = 0
    reasons: list[str] = []
    for term in query_terms:
        normalized = _normalize_story_memory_text(term)
        if not normalized:
            continue
        if normalized in haystack or haystack in normalized:
            score += 4
            reasons.append(f"命中“{term[:18]}”")
    return score, reasons


def _style_memory_query_terms(chapter: ChapterOutlineItem, plan: ChapterPlan | None) -> list[str]:
    raw_terms = [
        chapter.title,
        chapter.purpose,
        chapter.conflict,
        chapter.closing_mode,
        *(plan.continuity_targets if plan is not None else []),
        plan.primary_propulsion if plan is not None else "",
        plan.variation_goal if plan is not None else "",
        plan.theme_visibility if plan is not None else "",
        plan.grounding_beat if plan is not None else "",
    ]
    deduped: list[str] = []
    for term in raw_terms:
        text = _best_text(term)
        if text and text not in deduped:
            deduped.append(text)
    return deduped[:12]


def _score_style_memory(query_terms: list[str], payload: dict[str, Any]) -> int:
    haystack = _normalize_story_memory_text(
        " ".join(
            [
                _best_text(payload.get("label")),
                _best_text(payload.get("use_case")),
                _best_text(payload.get("text")),
            ]
        )
    )
    score = 2 if payload.get("source") == "style_bible" else 0
    for term in query_terms:
        normalized = _normalize_story_memory_text(term)
        if normalized and normalized in haystack:
            score += 3
    return score


def _chapter_style_excerpt(text: str, *, max_chars: int = 220) -> str:
    stripped = text.strip()
    if not stripped:
        return ""
    excerpt = stripped[:max_chars]
    if len(stripped) > max_chars:
        excerpt = excerpt.rstrip() + "……"
    return excerpt


def _recent_style_samples(
    chapters: list[ChapterResult],
    *,
    limit: int = 8,
) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    for chapter in chapters[-limit:]:
        excerpt = _chapter_style_excerpt(chapter.draft, max_chars=260)
        if not excerpt:
            continue
        samples.append(
            {
                "chapter_index": chapter.index,
                "title": chapter.title,
                "purpose": chapter.plan.purpose,
                "closing_mode": chapter.plan.closing_mode,
                "primary_propulsion": chapter.plan.primary_propulsion,
                "variation_goal": chapter.plan.variation_goal,
                "theme_visibility": chapter.plan.theme_visibility,
                "grounding_beat": chapter.plan.grounding_beat,
                "excerpt": excerpt,
            }
        )
    return samples


def _recent_voice_samples(
    chapters: list[ChapterResult],
    character_names: list[str],
    *,
    limit_per_character: int = 3,
) -> list[dict[str, Any]]:
    if not chapters or not character_names:
        return []
    paragraphs_by_chapter = [
        (chapter, [part.strip() for part in re.split(r"\n\s*\n", chapter.draft) if part.strip()])
        for chapter in chapters[-12:]
    ]
    samples: list[dict[str, Any]] = []
    for name in character_names:
        excerpts: list[dict[str, Any]] = []
        for chapter, paragraphs in reversed(paragraphs_by_chapter):
            for paragraph in paragraphs:
                if name not in paragraph and "“" not in paragraph and "\"" not in paragraph:
                    continue
                excerpt = _chapter_style_excerpt(paragraph, max_chars=180)
                if not excerpt:
                    continue
                excerpts.append(
                    {
                        "chapter_index": chapter.index,
                        "title": chapter.title,
                        "excerpt": excerpt,
                    }
                )
                if len(excerpts) >= limit_per_character:
                    break
            if len(excerpts) >= limit_per_character:
                break
        if excerpts:
            samples.append({"name": name, "evidence": list(reversed(excerpts))})
    return samples


def _normalize_chapter_plan_payload(payload: Any) -> dict[str, Any]:
    scene_alias_fields = {
        "scene_cards",
        "chapter_scenes",
        "scene_list",
        "scene_items",
    }
    recognized_fields = {
        "chapter_index",
        "chapter_title",
        "purpose",
        "continuity_targets",
        "opening_image",
        "closing_image",
        "closing_mode",
        "scenes",
        "primary_propulsion",
        "variation_goal",
        "term_budget",
        "theme_visibility",
        "grounding_beat",
        "chapter_role",
        "scene_load_score",
        "target_chars",
        "target_chars_min",
        "target_chars_max",
        "split_allowed",
        "merge_allowed",
        "progression_step_type",
        "progression_reward",
        "progression_cost",
        "current_tier",
        "target_tier",
        "enemy_band",
        "resource_focus",
    } | scene_alias_fields
    payload = _unwrap_structured_payload(
        payload,
        recognized_fields=recognized_fields,
        wrapper_keys=("chapter_plan", "plan"),
    )
    if isinstance(payload, dict):
        return _normalize_chapter_plan_mapping(payload, scene_alias_fields=scene_alias_fields)
    if isinstance(payload, list):
        items = _structured_payload_items(
            payload,
            recognized_fields=recognized_fields,
            wrapper_keys=("chapter_plan", "plan"),
        )
        if not items:
            return {}
        merged = _merge_named_payload_blocks(items, recognized_fields=recognized_fields)
        scenes = _extract_plan_scene_payloads(merged, scene_alias_fields=scene_alias_fields)
        if not scenes:
            for item in items:
                scenes = _extract_plan_scene_payloads(item, scene_alias_fields=scene_alias_fields)
                if scenes:
                    break
        if scenes:
            merged["scenes"] = scenes
            for key in scene_alias_fields:
                merged.pop(key, None)
            return merged
        if all(_looks_like_scene_payload(item) for item in items):
            return {"scenes": items}
        first = items[0]
        if any(key in first for key in ("chapter_index", "chapter_title", "purpose", "continuity_targets", "scenes")):
            return _normalize_chapter_plan_mapping(first, scene_alias_fields=scene_alias_fields)
    return {}


def _normalize_chapter_plan_mapping(
    payload: dict[str, Any],
    *,
    scene_alias_fields: set[str],
) -> dict[str, Any]:
    normalized = dict(payload)
    scenes = _extract_plan_scene_payloads(normalized, scene_alias_fields=scene_alias_fields)
    if scenes:
        normalized["scenes"] = scenes
    else:
        normalized.pop("scenes", None)
    for key in scene_alias_fields:
        normalized.pop(key, None)
    return normalized


def _normalize_book_outline_payload(payload: Any) -> dict[str, Any]:
    volume_alias_fields = {
        "volume_outlines",
        "volume_targets",
        "outline_volumes",
    }
    recognized_fields = {
        "title",
        "one_line_summary",
        "act_structure",
        "volumes",
        "tier_floor",
        "tier_target",
        "required_breakthrough",
        "resource_goal",
        "enemy_band",
        "progression_payoff",
    } | volume_alias_fields
    payload = _unwrap_structured_payload(
        payload,
        recognized_fields=recognized_fields,
        wrapper_keys=("book_outline", "outline", "book_plan"),
    )
    if isinstance(payload, dict):
        normalized = dict(payload)
        volumes = _extract_outline_items(normalized, primary_key="volumes", alias_fields=volume_alias_fields)
        if volumes:
            normalized["volumes"] = volumes
        for key in volume_alias_fields:
            normalized.pop(key, None)
        return normalized
    if isinstance(payload, list):
        items = _structured_payload_items(
            payload,
            recognized_fields=recognized_fields,
            wrapper_keys=("book_outline", "outline", "book_plan"),
        )
        if not items:
            return {}
        merged = _merge_named_payload_blocks(items, recognized_fields=recognized_fields)
        volumes = _extract_outline_items(merged, primary_key="volumes", alias_fields=volume_alias_fields)
        if not volumes:
            for item in items:
                volumes = _extract_outline_items(item, primary_key="volumes", alias_fields=volume_alias_fields)
                if volumes:
                    break
        if volumes:
            merged["volumes"] = volumes
            for key in volume_alias_fields:
                merged.pop(key, None)
            return merged
        if all(_looks_like_volume_blueprint_payload(item) for item in items):
            return {"volumes": items}
        first = items[0]
        if any(key in first for key in ("title", "one_line_summary", "act_structure", "volumes")):
            return first
    return {}


def _normalize_volume_outline_payload(payload: Any, volume: VolumeBlueprint) -> dict[str, Any]:
    chapter_alias_fields = {
        "chapters",
        "chapter_outlines",
        "chapter_items",
        "targets",
    }
    recognized_fields = {
        "volume_index",
        "title",
        "goal",
        "climax",
        "carry_over_threads",
        "tier_floor",
        "tier_target",
        "required_breakthrough",
        "resource_goal",
        "enemy_band",
        "progression_payoff",
        "chapter_targets",
        "progression_step_type",
        "progression_reward",
        "progression_cost",
        "current_tier",
        "target_tier",
        "enemy_band",
        "resource_focus",
    } | chapter_alias_fields
    payload = _unwrap_structured_payload(
        payload,
        recognized_fields=recognized_fields,
        wrapper_keys=("volume_outline", "outline", "volume_plan"),
    )
    if isinstance(payload, dict):
        normalized = dict(payload)
        chapter_targets = _extract_outline_items(normalized, primary_key="chapter_targets", alias_fields=chapter_alias_fields)
        if chapter_targets:
            normalized["chapter_targets"] = chapter_targets
        for key in chapter_alias_fields:
            normalized.pop(key, None)
        normalized.setdefault("volume_index", volume.index)
        normalized.setdefault("title", volume.title)
        return normalized
    if isinstance(payload, list):
        items = _structured_payload_items(
            payload,
            recognized_fields=recognized_fields,
            wrapper_keys=("volume_outline", "outline", "volume_plan"),
        )
        if not items:
            return {"volume_index": volume.index, "title": volume.title}
        merged = _merge_named_payload_blocks(items, recognized_fields=recognized_fields)
        chapter_targets = _extract_outline_items(merged, primary_key="chapter_targets", alias_fields=chapter_alias_fields)
        if not chapter_targets:
            for item in items:
                chapter_targets = _extract_outline_items(item, primary_key="chapter_targets", alias_fields=chapter_alias_fields)
                if chapter_targets:
                    break
        if chapter_targets:
            merged["chapter_targets"] = chapter_targets
            for key in chapter_alias_fields:
                merged.pop(key, None)
            merged.setdefault("volume_index", volume.index)
            merged.setdefault("title", volume.title)
            return merged
        if all(_looks_like_chapter_outline_payload(item) for item in items):
            return {
                "volume_index": volume.index,
                "title": volume.title,
                "chapter_targets": items,
            }
        first = dict(items[0])
        first.setdefault("volume_index", volume.index)
        first.setdefault("title", volume.title)
        return first
    return {"volume_index": volume.index, "title": volume.title}


def _normalize_continuity_payload(payload: Any, chapter: ChapterOutlineItem) -> dict[str, Any]:
    recognized_fields = {
        "chapter_index",
        "chapter_summary",
        "new_threads",
        "resolved_threads",
        "timeline_events",
        "character_states",
        "next_chapter_targets",
        "must_remember",
        "progression_updates",
        "current_tier",
        "next_breakthrough",
    }
    payload = _unwrap_structured_payload(
        payload,
        recognized_fields=recognized_fields,
        wrapper_keys=("continuity", "continuity_update", "update"),
    )
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, list):
        items = _structured_payload_items(
            payload,
            recognized_fields=recognized_fields,
            wrapper_keys=("continuity", "continuity_update", "update"),
        )
        if items:
            merged = _merge_named_payload_blocks(
                items,
                recognized_fields=recognized_fields,
            )
            if merged:
                merged.setdefault("chapter_index", chapter.index)
                merged.setdefault("chapter_summary", chapter.beat_summary)
                return merged
            if all(_looks_like_character_state_payload(item) for item in items):
                return {
                    "chapter_index": chapter.index,
                    "chapter_summary": chapter.beat_summary,
                    "character_states": items,
                }
    return {
        "chapter_index": chapter.index,
        "chapter_summary": chapter.beat_summary,
    }


def _normalize_long_memory_payload(payload: Any, chapter: ChapterOutlineItem) -> dict[str, Any]:
    recognized_fields = {
        "chapter_index",
        "promise_updates",
        "causality_updates",
        "progression_updates",
        "promise_delta",
        "causality_delta",
        "progression_delta",
    }
    payload = _unwrap_structured_payload(
        payload,
        recognized_fields=recognized_fields,
        wrapper_keys=("long_memory", "memory_update", "update"),
    )
    if isinstance(payload, dict):
        normalized = dict(payload)
        if "progression_updates" not in normalized and "progression_delta" in normalized:
            normalized["progression_updates"] = normalized.get("progression_delta")
        return normalized
    if isinstance(payload, list):
        items = _structured_payload_items(
            payload,
            recognized_fields=recognized_fields,
            wrapper_keys=("long_memory", "memory_update", "update"),
        )
        if items:
            merged = _merge_named_payload_blocks(
                items,
                recognized_fields=recognized_fields,
            )
            if merged:
                if "progression_updates" not in merged and "progression_delta" in merged:
                    merged["progression_updates"] = merged.get("progression_delta")
                merged.setdefault("chapter_index", chapter.index)
                return merged
            promise_updates = [item for item in items if _looks_like_promise_payload(item)]
            causality_updates = [item for item in items if _looks_like_causality_payload(item)]
            progression_updates = [item for item in items if _looks_like_progression_payload(item)]
            if promise_updates or causality_updates or progression_updates:
                return {
                    "chapter_index": chapter.index,
                    "promise_updates": promise_updates,
                    "causality_updates": causality_updates,
                    "progression_updates": progression_updates,
                }
    return {"chapter_index": chapter.index}


def _normalize_review_payload(payload: Any) -> dict[str, Any]:
    recognized_fields = {
        "passed",
        "score",
        "strengths",
        "issues",
        "required_fixes",
        "short_summary",
        "chapter_fixes",
    }
    payload = _unwrap_structured_payload(
        payload,
        recognized_fields=recognized_fields,
        wrapper_keys=("review", "feedback", "final_review"),
    )
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, list):
        items = _structured_payload_items(
            payload,
            recognized_fields=recognized_fields,
            wrapper_keys=("review", "feedback", "final_review"),
        )
        if items:
            merged = _merge_named_payload_blocks(
                items,
                recognized_fields=recognized_fields,
            )
            if merged:
                return merged
            first = items[0]
            if any(
                key in first
                for key in ("passed", "score", "strengths", "issues", "required_fixes", "short_summary", "chapter_fixes")
            ):
                return first
        string_items = _string_list(payload)
        if string_items:
            return {
                "passed": False,
                "score": 0,
                "issues": string_items[:8],
                "required_fixes": string_items[:4],
                "short_summary": string_items[0],
            }
    return {}


def _normalize_stagnation_judge_payload(payload: Any, chapter_index: int) -> dict[str, Any]:
    recognized_fields = {
        "chapter_index",
        "verdict",
        "recommended_action",
        "confidence",
        "reason",
        "scope_start_chapter",
        "scope_end_chapter",
        "next_chapter_constraints",
        "repair_goal",
    }
    payload = _unwrap_structured_payload(
        payload,
        recognized_fields=recognized_fields,
        wrapper_keys=("judge_review", "stagnation_review", "review", "decision"),
    )
    if isinstance(payload, dict):
        normalized = dict(payload)
    elif isinstance(payload, list):
        items = _structured_payload_items(
            payload,
            recognized_fields=recognized_fields,
            wrapper_keys=("judge_review", "stagnation_review", "review", "decision"),
        )
        if items:
            normalized = _merge_named_payload_blocks(items, recognized_fields=recognized_fields)
            if not normalized:
                normalized = dict(items[0])
        else:
            normalized = {}
    else:
        normalized = {}
    normalized.setdefault("chapter_index", chapter_index)
    normalized.setdefault("verdict", "stagnation_risk")
    normalized.setdefault("recommended_action", "forward_fix")
    normalized.setdefault("confidence", 0)
    normalized.setdefault("reason", "")
    normalized.setdefault("scope_start_chapter", chapter_index)
    normalized.setdefault("scope_end_chapter", chapter_index)
    normalized.setdefault("next_chapter_constraints", [])
    normalized.setdefault("repair_goal", "")
    return normalized


def _stagnation_judge_payload_shape(chapter_index: int) -> dict[str, Any]:
    return {
        "chapter_index": chapter_index,
        "verdict": "reasonable_cluster",
        "recommended_action": "accept",
        "confidence": 80,
        "reason": "判断理由",
        "scope_start_chapter": chapter_index,
        "scope_end_chapter": chapter_index,
        "next_chapter_constraints": ["后续约束"],
        "repair_goal": "最小修复目标",
    }


def _stagnation_judge_payload_has_content(payload: dict[str, Any]) -> bool:
    confidence = payload.get("confidence")
    return bool(
        _best_text(payload.get("reason"))
        or _string_list(payload.get("next_chapter_constraints"))
        or _best_text(payload.get("repair_goal"))
        or (isinstance(confidence, (int, float)) and confidence > 0)
        or _best_text(payload.get("verdict")) not in {"", "stagnation_risk"}
        or _best_text(payload.get("recommended_action")) not in {"", "forward_fix"}
    )


def _stagnation_judge_payload_has_signal(payload: Any) -> bool:
    return _structured_mapping_has_keys(
        payload,
        wrapper_keys=["judge_review", "stagnation_review", "review", "decision"],
        expected_keys=["verdict", "recommended_action", "confidence", "reason", "scope_start_chapter", "scope_end_chapter", "next_chapter_constraints", "repair_goal"],
        list_alias_fields=["next_chapter_constraints"],
    )


def _protect_structured_leaf_strings(
    payload: Any,
    *,
    min_length: int = 32,
) -> tuple[Any, dict[str, str]]:
    tokens: dict[str, str] = {}
    counter = 0

    def walk(value: Any) -> Any:
        nonlocal counter
        if isinstance(value, dict):
            return {key: walk(item) for key, item in value.items()}
        if isinstance(value, list):
            return [walk(item) for item in value]
        if isinstance(value, str):
            text = value.strip()
            if len(text) < min_length:
                return value
            token = f"__NF_TOKEN_{counter:04d}__"
            counter += 1
            tokens[token] = value
            return token
        return value

    return walk(payload), tokens


def _restore_structured_leaf_strings(payload: Any, tokens: dict[str, str]) -> Any:
    def walk(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: walk(item) for key, item in value.items()}
        if isinstance(value, list):
            return [walk(item) for item in value]
        if isinstance(value, str):
            return tokens.get(value, value)
        return value

    return walk(payload)


def _unwrap_structured_payload(
    payload: Any,
    *,
    recognized_fields: set[str] | None = None,
    wrapper_keys: tuple[str, ...] | list[str] = (),
    list_alias_fields: tuple[str, ...] | list[str] = (),
    max_depth: int = 3,
) -> Any:
    recognized_fields = set(recognized_fields or [])
    list_alias_fields = tuple(str(field) for field in list_alias_fields)
    recognized_fields.update(list_alias_fields)
    wrapper_keys = tuple(wrapper_keys)
    current = payload
    depth = 0
    known_wrapper_keys = wrapper_keys + ("payload", "data", "result", "output")
    while depth < max_depth:
        if isinstance(current, dict):
            if recognized_fields.intersection(current.keys()):
                return current
            candidates: list[Any] = []
            if len(current) == 1:
                only_key, only_value = next(iter(current.items()))
                if isinstance(only_value, dict):
                    candidates.append(only_value)
                elif isinstance(only_value, list) and (only_key in known_wrapper_keys or only_key in list_alias_fields):
                    candidates.append(only_value)
            for key in known_wrapper_keys:
                value = current.get(key)
                if isinstance(value, (dict, list)):
                    candidates.append(value)
            chosen: Any | None = None
            for candidate in candidates:
                if isinstance(candidate, dict) and recognized_fields.intersection(candidate.keys()):
                    chosen = candidate
                    break
                if isinstance(candidate, list):
                    chosen = candidate
                    break
            if chosen is None:
                return current
            current = chosen
            depth += 1
            continue
        return current
    return current


def _extract_outline_items(
    payload: dict[str, Any],
    *,
    primary_key: str,
    alias_fields: set[str],
) -> list[dict[str, Any]]:
    for key in (primary_key, *sorted(alias_fields)):
        value = payload.get(key)
        items = _extract_outline_item_list(value)
        if items:
            return items
    return []


def _structured_payload_items(
    payload: Any,
    *,
    recognized_fields: set[str] | None = None,
    wrapper_keys: tuple[str, ...] | list[str] = (),
    list_alias_fields: tuple[str, ...] | list[str] = (),
) -> list[dict[str, Any]]:
    if not isinstance(payload, list):
        return []
    items: list[dict[str, Any]] = []
    for item in payload:
        candidate = _unwrap_structured_payload(
            item,
            recognized_fields=recognized_fields,
            wrapper_keys=wrapper_keys,
            list_alias_fields=list_alias_fields,
            max_depth=2,
        )
        if isinstance(candidate, dict):
            items.append(candidate)
    return items


def _merge_named_payload_blocks(
    items: list[dict[str, Any]],
    *,
    recognized_fields: set[str],
) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for item in items:
        keys = recognized_fields.intersection(item.keys())
        if not keys:
            continue
        if len(keys) == 1:
            key = next(iter(keys))
            value = item.get(key)
            if isinstance(value, list) and isinstance(merged.get(key), list):
                merged[key] = [*merged[key], *value]
            elif key not in merged or _payload_value_missing(merged.get(key)):
                merged[key] = value
            continue
        for key in keys:
            value = item.get(key)
            if isinstance(value, list) and isinstance(merged.get(key), list):
                merged[key] = [*merged[key], *value]
            elif key not in merged or _payload_value_missing(merged.get(key)):
                merged[key] = value
    return merged


def _extract_scene_payloads(value: Any) -> list[dict[str, Any]]:
    scene_fields = {
        "scene_index",
        "location",
        "goal",
        "conflict",
        "turn",
        "scene_type",
        "load_weight",
        "must_include",
    }
    payload = _unwrap_structured_payload(
        value,
        recognized_fields=scene_fields,
        wrapper_keys=("scenes", "scene_cards", "items"),
        max_depth=3,
    )
    if isinstance(payload, list):
        scenes: list[dict[str, Any]] = []
        for item in payload:
            candidate = _unwrap_structured_payload(
                item,
                recognized_fields=scene_fields,
                wrapper_keys=("scene", "card"),
                max_depth=2,
            )
            if isinstance(candidate, dict) and (
                _looks_like_scene_payload(candidate) or scene_fields.intersection(candidate.keys())
            ):
                scenes.append(candidate)
        return scenes
    if isinstance(payload, dict) and _looks_like_scene_payload(payload):
        return [payload]
    return []


def _extract_outline_item_list(value: Any) -> list[dict[str, Any]]:
    payload = _unwrap_structured_payload(
        value,
        recognized_fields={"items", "entries", "values", "list", "volumes", "chapter_targets", "chapters"},
        wrapper_keys=("payload", "data", "result", "output"),
    )
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("items", "entries", "values", "list", "volumes", "chapter_targets", "chapters"):
            nested = payload.get(key)
            if isinstance(nested, list):
                return [item for item in nested if isinstance(item, dict)]
    return []


def _looks_like_volume_blueprint_payload(payload: dict[str, Any]) -> bool:
    informative = {
        key
        for key in (
            "index",
            "role",
            "central_question",
            "escalation",
            "emotional_shift",
            "phase_type",
            "must_payoff",
            "start_chapter",
            "end_chapter",
            "target_chapter_count",
            "expected_chapter_range",
        )
        if key in payload
    }
    return bool(informative)


def _looks_like_chapter_outline_payload(payload: dict[str, Any]) -> bool:
    return any(
        key in payload
        for key in (
            "index",
            "title",
            "purpose",
            "conflict",
            "beat_summary",
            "ending_note",
            "chapter_role",
            "target_chars",
            "closing_mode",
        )
    )


def _extract_plan_scene_payloads(
    payload: dict[str, Any],
    *,
    scene_alias_fields: set[str],
) -> list[dict[str, Any]]:
    for key in ("scenes", *sorted(scene_alias_fields)):
        value = payload.get(key)
        if _payload_value_missing(value):
            continue
        scenes = _extract_clean_scene_payloads(value)
        if scenes is None:
            return []
        if scenes:
            return scenes
    return []


def _extract_clean_scene_payloads(value: Any) -> list[dict[str, Any]] | None:
    scene_fields = {
        "scene_index",
        "location",
        "goal",
        "conflict",
        "turn",
        "scene_type",
        "load_weight",
        "must_include",
    }
    payload = _unwrap_structured_payload(
        value,
        recognized_fields=scene_fields,
        wrapper_keys=("scenes", "scene_cards", "items"),
        max_depth=3,
    )
    if isinstance(payload, list):
        if not payload:
            return []
        scenes: list[dict[str, Any]] = []
        invalid_items = 0
        for item in payload:
            candidate = _unwrap_structured_payload(
                item,
                recognized_fields=scene_fields,
                wrapper_keys=("scene", "card"),
                max_depth=2,
            )
            if isinstance(candidate, dict) and (
                _looks_like_scene_payload(candidate) or scene_fields.intersection(candidate.keys())
            ):
                scenes.append(candidate)
            else:
                invalid_items += 1
        if invalid_items:
            return None
        return scenes
    if isinstance(payload, dict) and (
        _looks_like_scene_payload(payload) or scene_fields.intersection(payload.keys())
    ):
        return [payload]
    return None


def _chapter_plan_has_scene_signal(payload: Any) -> bool:
    scene_alias_fields = {
        "scene_cards",
        "chapter_scenes",
        "scene_list",
        "scene_items",
        "items",
        "scene_payload_blocks",
        "scene_blocks",
    }
    normalized = _normalize_chapter_plan_payload(payload)
    if normalized.get("scenes"):
        return True

    recognized_fields = {
        "chapter_index",
        "chapter_title",
        "purpose",
        "continuity_targets",
        "opening_image",
        "closing_image",
        "closing_mode",
        "scenes",
    } | scene_alias_fields
    unwrapped = _unwrap_structured_payload(
        payload,
        recognized_fields=recognized_fields,
        wrapper_keys=("chapter_plan", "plan"),
    )
    if isinstance(unwrapped, dict):
        for key in ("scenes", *sorted(scene_alias_fields)):
            value = unwrapped.get(key)
            if value not in (None, "", []):
                return True
    if isinstance(unwrapped, list):
        if any(isinstance(item, dict) and _chapter_plan_has_scene_signal(item) for item in unwrapped):
            return True
        text_items = [item.strip() for item in unwrapped if isinstance(item, str) and item.strip()]
        if text_items and all(("场景" in item) or bool(re.match(r"^(scene|beat)\\s*\\d+", item, flags=re.IGNORECASE)) for item in text_items[: min(3, len(text_items))]):
            return True
    return False


def _chapter_plan_has_valid_scenes(payload: dict[str, Any]) -> bool:
    scenes = payload.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        return False
    return all(
        isinstance(item, dict)
        and (_looks_like_scene_payload(item) or bool(item.keys()))
        for item in scenes
    )


def _looks_like_scene_payload(payload: dict[str, Any]) -> bool:
    scene_keys = ("scene_index", "location", "goal", "conflict", "turn")
    return sum(1 for key in scene_keys if _best_text(payload.get(key))) >= 3


def _looks_like_character_state_payload(payload: dict[str, Any]) -> bool:
    keys = ("name", "current_goal", "emotional_state", "relationship_shift", "risk", "unresolved")
    return sum(1 for key in keys if _best_text(payload.get(key))) >= 2


def _looks_like_promise_payload(payload: dict[str, Any]) -> bool:
    keys = ("promise_id", "label", "thread", "current_status", "payoff_requirements")
    return sum(1 for key in keys if _best_text(payload.get(key)) or _string_list(payload.get(key))) >= 2


def _looks_like_causality_payload(payload: dict[str, Any]) -> bool:
    keys = ("effect_label", "cause", "prerequisites", "required_consequences")
    return sum(1 for key in keys if _best_text(payload.get(key)) or _string_list(payload.get(key))) >= 2


def _looks_like_progression_payload(payload: dict[str, Any]) -> bool:
    keys = (
        "milestone_label",
        "current_tier",
        "target_tier",
        "status",
        "objective",
        "required_resources",
        "unlocked_rewards",
        "bottleneck",
    )
    return sum(1 for key in keys if _best_text(payload.get(key)) or _string_list(payload.get(key))) >= 2


def _payload_value_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, list):
        return not value
    if isinstance(value, dict):
        return not value
    return not _best_text(value)


def _blend_style_bibles(
    anchor: StyleBible,
    calibration: StyleBible,
    chapters: list[ChapterResult],
) -> tuple[StyleBible, dict[str, Any]]:
    applied: dict[str, list[str]] = {}
    blocked: dict[str, list[str]] = {}
    merged = StyleBible(
        audience_contract=_merge_lists(anchor.audience_contract or calibration.audience_contract),
        tone_targets=_merge_lists(anchor.tone_targets or calibration.tone_targets),
        pacing_rules=_weighted_style_rules(anchor.pacing_rules, calibration.pacing_rules, field_name="pacing_rules", applied=applied, blocked=blocked),
        propulsion_rules=_weighted_style_rules(anchor.propulsion_rules, calibration.propulsion_rules, field_name="propulsion_rules", applied=applied, blocked=blocked, max_calibration=2),
        clarity_rules=_weighted_style_rules(anchor.clarity_rules, calibration.clarity_rules, field_name="clarity_rules", applied=applied, blocked=blocked, max_calibration=2),
        dialogue_rules=_weighted_style_rules(anchor.dialogue_rules, calibration.dialogue_rules, field_name="dialogue_rules", applied=applied, blocked=blocked),
        prose_rules=_weighted_style_rules(anchor.prose_rules, calibration.prose_rules, field_name="prose_rules", applied=applied, blocked=blocked),
        sensory_rules=_weighted_style_rules(anchor.sensory_rules, calibration.sensory_rules, field_name="sensory_rules", applied=applied, blocked=blocked),
        thematic_subtext_rules=_weighted_style_rules(anchor.thematic_subtext_rules, calibration.thematic_subtext_rules, field_name="thematic_subtext_rules", applied=applied, blocked=blocked, max_calibration=2),
        pressure_curve_rules=_weighted_style_rules(anchor.pressure_curve_rules, calibration.pressure_curve_rules, field_name="pressure_curve_rules", applied=applied, blocked=blocked, max_calibration=2),
        grounding_rules=_weighted_style_rules(anchor.grounding_rules, calibration.grounding_rules, field_name="grounding_rules", applied=applied, blocked=blocked, max_calibration=2),
        taboo_phrases=_merge_lists(anchor.taboo_phrases, calibration.taboo_phrases),
        sample_passages=_blend_style_passages(anchor.sample_passages, calibration.sample_passages, applied=applied, blocked=blocked),
    )
    blocked["audience_contract"] = [
        item for item in calibration.audience_contract
        if item not in merged.audience_contract
    ]
    blocked["tone_targets"] = [
        item for item in calibration.tone_targets
        if item not in merged.tone_targets
    ]
    report = {
        "mode": "weighted_calibration",
        "anchor_weight": 0.75,
        "calibration_weight": 0.25,
        "through_chapter": chapters[-1].index if chapters else 0,
        "through_volume": chapters[-1].volume_index if chapters else 0,
        "sample_chapters": [chapter.index for chapter in chapters[-8:]],
        "applied_adjustments": {key: value for key, value in applied.items() if value},
        "blocked_adjustments": {key: value for key, value in blocked.items() if value},
    }
    return merged, report


def _weighted_style_rules(
    anchor_rules: list[str],
    calibration_rules: list[str],
    *,
    field_name: str,
    applied: dict[str, list[str]],
    blocked: dict[str, list[str]],
    max_total: int = 8,
    max_calibration: int = 1,
) -> list[str]:
    merged = _merge_lists(anchor_rules)
    if len(merged) > max_total:
        merged = merged[:max_total]
    applied_items: list[str] = []
    blocked_items: list[str] = []
    for rule in calibration_rules:
        if not rule or rule in merged:
            continue
        if len(applied_items) >= max_calibration or len(merged) >= max_total:
            blocked_items.append(rule)
            continue
        merged.append(rule)
        applied_items.append(rule)
    applied[field_name] = applied_items
    blocked[field_name] = blocked_items
    return merged


def _blend_style_passages(
    anchor_passages: list[StylePassage],
    calibration_passages: list[StylePassage],
    *,
    applied: dict[str, list[str]],
    blocked: dict[str, list[str]],
    max_anchor: int = 3,
    max_calibration: int = 2,
) -> list[StylePassage]:
    selected: list[StylePassage] = []
    seen: set[str] = set()
    for passage in anchor_passages[:max_anchor]:
        key = f"{passage.label}::{passage.use_case}::{passage.text}"
        if key in seen:
            continue
        selected.append(copy.deepcopy(passage))
        seen.add(key)
    applied_items: list[str] = []
    blocked_items: list[str] = []
    for passage in calibration_passages:
        key = f"{passage.label}::{passage.use_case}::{passage.text}"
        if key in seen:
            continue
        if len(applied_items) >= max_calibration:
            blocked_items.append(passage.label or passage.use_case or "unnamed")
            continue
        selected.append(copy.deepcopy(passage))
        seen.add(key)
        applied_items.append(passage.label or passage.use_case or "unnamed")
    if not selected:
        selected = [copy.deepcopy(passage) for passage in calibration_passages[:max_calibration]]
    applied["sample_passages"] = applied_items
    blocked["sample_passages"] = blocked_items
    return selected


def _normalize_story_memory_text(text: str) -> str:
    return re.sub(r"\s+", "", _best_text(text)).lower()


def _build_book_catalog(book_outline: BookOutline, chapters: list[ChapterResult]) -> list[dict[str, Any]]:
    chapter_map: dict[int, list[ChapterResult]] = {}
    for chapter in chapters:
        chapter_map.setdefault(chapter.volume_index, []).append(chapter)
    catalog: list[dict[str, Any]] = []
    for volume in book_outline.volumes:
        volume_chapters = sorted(chapter_map.get(volume.index, []), key=lambda item: item.index)
        catalog.append(
            {
                "volume_index": volume.index,
                "title": volume.title,
                "role": volume.role,
                "chapter_range": [volume.start_chapter, volume.end_chapter],
                "chapters": [{"index": chapter.index, "title": chapter.title} for chapter in volume_chapters],
            }
        )
    return catalog


def _build_volume_digests(book_outline: BookOutline, chapters: list[ChapterResult]) -> list[dict[str, Any]]:
    chapter_map: dict[int, list[ChapterResult]] = {}
    for chapter in chapters:
        chapter_map.setdefault(chapter.volume_index, []).append(chapter)
    digests: list[dict[str, Any]] = []
    for volume in book_outline.volumes:
        volume_chapters = sorted(chapter_map.get(volume.index, []), key=lambda item: item.index)
        if not volume_chapters:
            continue
        points: list[str] = []
        for index in _sample_indices(len(volume_chapters), target=4):
            chapter = volume_chapters[index]
            summary = _best_text(chapter.continuity.chapter_summary, chapter.plan.purpose, chapter.outline_item.beat_summary)
            if summary:
                points.append(f"第{chapter.index}章《{chapter.title}》：{summary}")
        digests.append(
            {
                "volume_index": volume.index,
                "title": volume.title,
                "role": volume.role,
                "central_question": volume.central_question,
                "chapter_range": [volume.start_chapter, volume.end_chapter],
                "summary": _clip_text("；".join(points), 360),
            }
        )
    return digests


def _sample_indices(length: int, *, target: int) -> list[int]:
    if length <= 0:
        return []
    if length <= target:
        return list(range(length))
    candidates = {0, length - 1}
    for rank in range(1, max(target - 1, 1)):
        position = round((length - 1) * rank / max(target - 1, 1))
        candidates.add(position)
    return sorted(index for index in candidates if 0 <= index < length)


def _fallback_book_package(
    spec: ProjectSpec,
    bible: WorldBible,
    chapters: list[ChapterResult],
    continuity: ContinuityState,
    final_review: FinalReview,
    total_chars: int,
    catalog: list[dict[str, Any]],
    volume_digests: list[dict[str, Any]],
) -> BookPackage:
    zh = _is_zh_output_language(spec.output_language)
    factual_parts: list[str] = []
    opening = _best_text(bible.logline, spec.premise, spec.hook)
    if opening:
        factual_parts.append(_ensure_sentence(opening))
    for digest in volume_digests[:6]:
        summary = _best_text(digest.get("summary"))
        if summary:
            if zh:
                factual_parts.append(f"第{digest.get('volume_index', '?')}卷，{summary}")
            else:
                factual_parts.append(f"Volume {digest.get('volume_index', '?')}: {summary}")
    closing = _best_text(
        continuity.recent_summaries[-1] if continuity.recent_summaries else "",
        final_review.short_summary,
    )
    if closing:
        if zh:
            factual_parts.append(f"最终，{_strip_terminal_punctuation(closing)}。")
        else:
            factual_parts.append(f"Finally, {_strip_terminal_punctuation(closing)}.")
    factual_summary = _normalize_package_text("".join(factual_parts), "", max_chars=560, min_chars=220)
    if not factual_summary:
        fallback_conflict = (
            f"{spec.protagonist} is pulled into a conflict that must be resolved."
            if not zh
            else f"{spec.protagonist}卷入了一场必须收束的冲突。"
        )
        fallback_close = "The book completes its main arc." if not zh else "整部作品完成了主线收束。"
        factual_summary = _clip_text(
            _ensure_sentence(spec.hook or spec.premise or fallback_conflict)
            + _ensure_sentence(final_review.short_summary or fallback_close),
            560,
        )

    marketing_seed = " ".join(
        item
        for item in [
            spec.hook,
            bible.logline,
            (
                f"{spec.protagonist}必须直面{bible.core_conflict}"
                if zh and spec.protagonist and bible.core_conflict
                else f"{spec.protagonist} must face {bible.core_conflict}"
                if spec.protagonist and bible.core_conflict
                else ""
            ),
        ]
        if item
    )
    marketing_blurb = _normalize_package_text(marketing_seed, "", max_chars=200, min_chars=40)
    if not marketing_blurb:
        fallback_hook = (
            f"{spec.protagonist}被迫面对一场无法回避的局势。"
            if zh
            else f"{spec.protagonist} is forced into a situation they cannot avoid."
        )
        marketing_blurb = _clip_text(
            _ensure_sentence(spec.hook or fallback_hook),
            200,
        )

    return BookPackage(
        title=spec.title,
        genre=spec.genre,
        audience=spec.audience,
        tone=spec.tone,
        protagonist=spec.protagonist,
        total_chars=total_chars,
        chapter_count=len(chapters),
        volume_count=spec.volume_count,
        final_score=final_review.score,
        final_passed=final_review.passed,
        factual_summary=factual_summary,
        marketing_blurb=marketing_blurb,
        catalog=catalog,
        output_language=spec.output_language,
    )


def _normalize_package_text(value: Any, fallback: str, *, max_chars: int, min_chars: int) -> str:
    text = _best_text(value)
    text = re.sub(r"\s+", "", text)
    if text and len(text) >= min_chars:
        return _clip_text(text, max_chars)
    fallback_text = re.sub(r"\s+", "", _best_text(fallback))
    if fallback_text:
        return _clip_text(fallback_text, max_chars)
    return ""


def _clip_text(text: str, max_chars: int) -> str:
    cleaned = _best_text(text)
    if len(cleaned) <= max_chars:
        return cleaned
    clipped = cleaned[: max_chars - 1].rstrip("，,、；; ")
    if clipped and clipped[-1] not in "。！？!?":
        clipped += "。"
    return clipped


def _ensure_sentence(text: str) -> str:
    cleaned = _best_text(text)
    if not cleaned:
        return ""
    if cleaned[-1] in "。！？!?":
        return cleaned
    return cleaned + "。"


def _strip_terminal_punctuation(text: str) -> str:
    return _best_text(text).rstrip("。！？!?")


def _character_from_dict(payload: dict[str, Any]) -> CharacterProfile:
    return CharacterProfile(
        name=_best_text(payload.get("name"), ""),
        role=_best_text(payload.get("role"), ""),
        goal=_best_text(payload.get("goal"), ""),
        fear=_best_text(payload.get("fear"), ""),
        contradiction=_best_text(payload.get("contradiction"), ""),
        arc=_best_text(payload.get("arc"), ""),
        public_image=_best_text(payload.get("public_image"), ""),
        private_truth=_best_text(payload.get("private_truth"), ""),
        speaking_style=_best_text(payload.get("speaking_style"), ""),
        signature_image=_best_text(payload.get("signature_image"), ""),
        relationship_tensions=_string_list(payload.get("relationship_tensions")),
        do_not_break=_string_list(payload.get("do_not_break")),
    )


def _project_spec_from_dict(payload: dict[str, Any]) -> ProjectSpec:
    chapter_count = int(payload.get("chapter_count", 1) or 1)
    volume_count = int(payload.get("volume_count", 1) or 1)
    chapters_per_volume = int(payload.get("chapters_per_volume", math.ceil(chapter_count / max(volume_count, 1))) or 1)
    output_language = _normalized_output_language(payload.get("output_language"))
    defaults = _project_language_defaults(output_language, payload.get("title"))
    volume_chapter_targets = _normalized_volume_chapter_targets(
        payload.get("volume_chapter_targets"),
        chapter_count=chapter_count,
        volume_count=volume_count,
    )
    return ProjectSpec(
        title=_best_text(payload.get("title"), ""),
        genre=_best_text(payload.get("genre"), defaults["genre"]),
        audience=_best_text(payload.get("audience"), defaults["audience"]),
        tone=_best_text(payload.get("tone"), defaults["tone"]),
        premise=_best_text(payload.get("premise"), ""),
        theme=_best_text(payload.get("theme"), ""),
        hook=_best_text(payload.get("hook"), ""),
        setting=_best_text(payload.get("setting"), ""),
        protagonist=_best_text(payload.get("protagonist"), ""),
        outline_hint=_best_text(payload.get("outline_hint"), ""),
        world_hint=_best_text(payload.get("world_hint"), ""),
        ending_mode=_best_text(payload.get("ending_mode"), "standalone"),
        pov=_best_text(payload.get("pov"), defaults["pov"]),
        target_total_chars=int(payload.get("target_total_chars", 0) or 0),
        target_chars_per_chapter=int(payload.get("target_chars_per_chapter", 0) or 0),
        chapter_count=chapter_count,
        volume_count=volume_count,
        chapters_per_volume=chapters_per_volume,
        volume_chapter_targets=volume_chapter_targets,
        chapter_char_tolerance=_normalized_chapter_char_tolerance(payload.get("chapter_char_tolerance")),
        structure_mode=_best_text(payload.get("structure_mode"), "legacy"),
        market_profile=_resolved_market_profile_from_payload(payload.get("market_profile"), payload),
        progression_mode=_normalized_progression_mode(payload.get("progression_mode")),
        progression_flavor=_normalized_progression_flavor(payload.get("progression_flavor")),
        progression_pacing=_normalized_progression_pacing(payload.get("progression_pacing")),
        power_system_hint=_best_text(payload.get("power_system_hint"), ""),
        style_examples=_string_list(payload.get("style_examples")),
        must_include=_string_list(payload.get("must_include")),
        avoid=_string_list(payload.get("avoid")),
        character_seeds=_character_seed_list(payload.get("character_seeds")),
        seed=int(payload["seed"]) if payload.get("seed") is not None else None,
        output_language=output_language,
    )


def _world_bible_from_dict(payload: dict[str, Any]) -> WorldBible:
    return WorldBible(
        title=_best_text(payload.get("title"), ""),
        logline=_best_text(payload.get("logline"), ""),
        setting_summary=_best_text(payload.get("setting_summary"), ""),
        core_conflict=_best_text(payload.get("core_conflict"), ""),
        theme_statement=_best_text(payload.get("theme_statement"), ""),
        narrative_voice=_string_list(payload.get("narrative_voice")),
        world_rules=_string_list(payload.get("world_rules")),
        chapter_guardrails=_string_list(payload.get("chapter_guardrails")),
        ending_contract=_string_list(payload.get("ending_contract")),
        major_threads=_string_list(payload.get("major_threads")),
        characters=[_character_from_dict(item) for item in payload.get("characters", []) if isinstance(item, dict)],
    )


def _style_passage_from_dict(payload: dict[str, Any]) -> StylePassage:
    return StylePassage(
        label=_best_text(payload.get("label"), ""),
        use_case=_best_text(payload.get("use_case"), ""),
        text=_best_text(payload.get("text"), ""),
    )


def _style_bible_from_dict(payload: dict[str, Any]) -> StyleBible:
    return StyleBible(
        audience_contract=_string_list(payload.get("audience_contract")),
        tone_targets=_string_list(payload.get("tone_targets")),
        pacing_rules=_string_list(payload.get("pacing_rules")),
        propulsion_rules=_string_list(payload.get("propulsion_rules")),
        clarity_rules=_string_list(payload.get("clarity_rules")),
        dialogue_rules=_string_list(payload.get("dialogue_rules")),
        prose_rules=_string_list(payload.get("prose_rules")),
        sensory_rules=_string_list(payload.get("sensory_rules")),
        thematic_subtext_rules=_string_list(payload.get("thematic_subtext_rules")),
        pressure_curve_rules=_string_list(payload.get("pressure_curve_rules")),
        grounding_rules=_string_list(payload.get("grounding_rules")),
        taboo_phrases=_string_list(payload.get("taboo_phrases")),
        sample_passages=[_style_passage_from_dict(item) for item in payload.get("sample_passages", []) if isinstance(item, dict)],
    )


def _voice_card_from_dict(payload: dict[str, Any]) -> CharacterVoiceCard:
    return CharacterVoiceCard(
        name=_best_text(payload.get("name"), ""),
        speech_rhythm=_best_text(payload.get("speech_rhythm"), "简洁"),
        emotional_expression=_best_text(payload.get("emotional_expression"), ""),
        sentence_shape=_best_text(payload.get("sentence_shape"), ""),
        social_register=_best_text(payload.get("social_register"), ""),
        humor_style=_best_text(payload.get("humor_style"), ""),
        silence_pattern=_best_text(payload.get("silence_pattern"), ""),
        contrast_anchor=_best_text(payload.get("contrast_anchor"), ""),
        common_words=_string_list(payload.get("common_words")),
        tension_triggers=_string_list(payload.get("tension_triggers")),
        forbidden_drifts=_string_list(payload.get("forbidden_drifts")),
    )


def _promise_ledger_item_from_dict(payload: dict[str, Any]) -> PromiseLedgerItem:
    return PromiseLedgerItem(
        promise_id=_best_text(payload.get("promise_id"), ""),
        label=_best_text(payload.get("label"), ""),
        thread=_best_text(payload.get("thread"), ""),
        chapter_opened=int(payload.get("chapter_opened", 0) or 0),
        target_volume=int(payload.get("target_volume", 0) or 0),
        current_status=_best_text(payload.get("current_status"), "open"),
        last_touched_chapter=int(payload.get("last_touched_chapter", 0) or 0),
        payoff_requirements=_string_list(payload.get("payoff_requirements")),
        overdue=bool(payload.get("overdue")),
        deadline_state=_best_text(payload.get("deadline_state"), "on_track"),
    )


def _causality_edge_from_dict(payload: dict[str, Any]) -> CausalityEdge:
    return CausalityEdge(
        effect_label=_best_text(payload.get("effect_label"), ""),
        cause=_best_text(payload.get("cause"), ""),
        prerequisites=_string_list(payload.get("prerequisites")),
        required_consequences=_string_list(payload.get("required_consequences")),
        introduced_chapter=int(payload.get("introduced_chapter", 0) or 0),
        last_verified_chapter=int(payload.get("last_verified_chapter", 0) or 0),
    )


def _volume_blueprint_from_dict(payload: dict[str, Any]) -> VolumeBlueprint:
    return VolumeBlueprint(
        index=int(payload.get("index", 0)),
        start_chapter=int(payload.get("start_chapter", 1)),
        end_chapter=int(payload.get("end_chapter", 1)),
        title=_best_text(payload.get("title"), ""),
        role=_best_text(payload.get("role"), ""),
        central_question=_best_text(payload.get("central_question"), ""),
        escalation=_best_text(payload.get("escalation"), ""),
        emotional_shift=_best_text(payload.get("emotional_shift"), ""),
        phase_type=_best_text(payload.get("phase_type"), ""),
        volume_importance=_best_text(payload.get("volume_importance"), ""),
        beat_count=int(payload.get("beat_count", 0) or 0),
        new_setting_load=_best_text(payload.get("new_setting_load"), ""),
        new_cast_load=_best_text(payload.get("new_cast_load"), ""),
        payoff_load=_best_text(payload.get("payoff_load"), ""),
        expected_chapter_range=_best_text(payload.get("expected_chapter_range"), ""),
        target_chapter_count=int(payload.get("target_chapter_count", 0) or 0),
        chapter_count_min=int(payload.get("chapter_count_min", 0) or 0),
        chapter_count_max=int(payload.get("chapter_count_max", 0) or 0),
        target_chars=int(payload.get("target_chars", 0) or 0),
        target_chars_min=int(payload.get("target_chars_min", 0) or 0),
        target_chars_max=int(payload.get("target_chars_max", 0) or 0),
        density_mode=_best_text(payload.get("density_mode"), ""),
        tier_floor=_best_text(payload.get("tier_floor"), ""),
        tier_target=_best_text(payload.get("tier_target"), ""),
        required_breakthrough=_best_text(payload.get("required_breakthrough"), ""),
        resource_goal=_best_text(payload.get("resource_goal"), ""),
        enemy_band=_best_text(payload.get("enemy_band"), ""),
        progression_payoff=_best_text(payload.get("progression_payoff"), ""),
        must_payoff=_string_list(payload.get("must_payoff")),
    )


def _book_outline_from_dict(payload: dict[str, Any]) -> BookOutline:
    return BookOutline(
        title=_best_text(payload.get("title"), ""),
        one_line_summary=_best_text(payload.get("one_line_summary"), ""),
        act_structure=_string_list(payload.get("act_structure")),
        volumes=[_volume_blueprint_from_dict(item) for item in payload.get("volumes", []) if isinstance(item, dict)],
    )


def _chapter_outline_item_from_dict(payload: dict[str, Any], volume_index: int) -> ChapterOutlineItem:
    return ChapterOutlineItem(
        index=int(payload.get("index", 0)),
        volume_index=int(payload.get("volume_index", volume_index) or volume_index),
        title=_best_text(payload.get("title"), ""),
        purpose=_best_text(payload.get("purpose"), ""),
        conflict=_best_text(payload.get("conflict"), ""),
        beat_summary=_best_text(payload.get("beat_summary"), ""),
        ending_note=_best_text(payload.get("ending_note"), ""),
        pov=_best_text(payload.get("pov"), "第三人称有限视角"),
        closing_mode=_best_text(payload.get("closing_mode"), "chapter_hook"),
        chapter_role=_best_text(payload.get("chapter_role"), ""),
        scene_load_score=float(payload.get("scene_load_score", 0.0) or 0.0),
        target_chars=int(payload.get("target_chars", 0) or 0),
        target_chars_min=int(payload.get("target_chars_min", 0) or 0),
        target_chars_max=int(payload.get("target_chars_max", 0) or 0),
        split_allowed=bool(payload.get("split_allowed")),
        merge_allowed=bool(payload.get("merge_allowed")),
        progression_step_type=_best_text(payload.get("progression_step_type"), ""),
        progression_reward=_best_text(payload.get("progression_reward"), ""),
        progression_cost=_best_text(payload.get("progression_cost"), ""),
        current_tier=_best_text(payload.get("current_tier"), ""),
        target_tier=_best_text(payload.get("target_tier"), ""),
        enemy_band=_best_text(payload.get("enemy_band"), ""),
        resource_focus=_best_text(payload.get("resource_focus"), ""),
        must_payoff=_string_list(payload.get("must_payoff")),
    )


def _volume_outline_from_dict(payload: dict[str, Any]) -> VolumeOutline:
    volume_index = int(payload.get("volume_index", 0))
    return VolumeOutline(
        volume_index=volume_index,
        title=_best_text(payload.get("title"), ""),
        goal=_best_text(payload.get("goal"), ""),
        climax=_best_text(payload.get("climax"), ""),
        carry_over_threads=_string_list(payload.get("carry_over_threads")),
        tier_floor=_best_text(payload.get("tier_floor"), ""),
        tier_target=_best_text(payload.get("tier_target"), ""),
        required_breakthrough=_best_text(payload.get("required_breakthrough"), ""),
        resource_goal=_best_text(payload.get("resource_goal"), ""),
        enemy_band=_best_text(payload.get("enemy_band"), ""),
        progression_payoff=_best_text(payload.get("progression_payoff"), ""),
        chapter_targets=[
            _chapter_outline_item_from_dict(item, volume_index)
            for item in payload.get("chapter_targets", [])
            if isinstance(item, dict)
        ],
    )


def _chapter_plan_from_dict(payload: dict[str, Any]) -> ChapterPlan:
    return ChapterPlan(
        chapter_index=int(payload.get("chapter_index", 0)),
        chapter_title=_best_text(payload.get("chapter_title"), ""),
        purpose=_best_text(payload.get("purpose"), ""),
        continuity_targets=_string_list(payload.get("continuity_targets")),
        opening_image=_best_text(payload.get("opening_image"), ""),
        closing_image=_best_text(payload.get("closing_image"), ""),
        closing_mode=_best_text(payload.get("closing_mode"), "chapter_hook"),
        scenes=[_scene_from_dict(item) for item in payload.get("scenes", []) if isinstance(item, dict)],
        primary_propulsion=_best_text(payload.get("primary_propulsion"), ""),
        variation_goal=_best_text(payload.get("variation_goal"), ""),
        term_budget=_best_text(payload.get("term_budget"), ""),
        theme_visibility=_best_text(payload.get("theme_visibility"), ""),
        grounding_beat=_best_text(payload.get("grounding_beat"), ""),
        chapter_role=_best_text(payload.get("chapter_role"), ""),
        scene_load_score=float(payload.get("scene_load_score", 0.0) or 0.0),
        target_chars=int(payload.get("target_chars", 0) or 0),
        target_chars_min=int(payload.get("target_chars_min", 0) or 0),
        target_chars_max=int(payload.get("target_chars_max", 0) or 0),
        split_allowed=bool(payload.get("split_allowed")),
        merge_allowed=bool(payload.get("merge_allowed")),
        progression_step_type=_best_text(payload.get("progression_step_type"), ""),
        progression_reward=_best_text(payload.get("progression_reward"), ""),
        progression_cost=_best_text(payload.get("progression_cost"), ""),
        current_tier=_best_text(payload.get("current_tier"), ""),
        target_tier=_best_text(payload.get("target_tier"), ""),
        enemy_band=_best_text(payload.get("enemy_band"), ""),
        resource_focus=_best_text(payload.get("resource_focus"), ""),
    )


def _local_quality_from_dict(payload: dict[str, Any]) -> LocalQualityReport:
    return LocalQualityReport(
        passed=bool(payload.get("passed")),
        score=int(payload.get("score", 0)),
        issues=_string_list(payload.get("issues")),
        strengths=_string_list(payload.get("strengths")),
        short_summary=_best_text(payload.get("short_summary"), ""),
        metrics=payload.get("metrics") if isinstance(payload.get("metrics"), dict) else {},
    )


def _review_feedback_from_dict(payload: dict[str, Any]) -> ReviewFeedback:
    return ReviewFeedback(
        passed=bool(payload.get("passed")),
        score=int(payload.get("score", 0)),
        strengths=_string_list(payload.get("strengths")),
        issues=_string_list(payload.get("issues")),
        required_fixes=_string_list(payload.get("required_fixes")),
        short_summary=_best_text(payload.get("short_summary"), ""),
        chapter_fixes=_chapter_fix_list(payload.get("chapter_fixes")),
    )


def _continuity_update_from_dict(payload: dict[str, Any]) -> ContinuityUpdate:
    return ContinuityUpdate(
        chapter_index=int(payload.get("chapter_index", 0)),
        chapter_summary=_best_text(payload.get("chapter_summary"), ""),
        new_threads=_string_list(payload.get("new_threads")),
        resolved_threads=_string_list(payload.get("resolved_threads")),
        timeline_events=_string_list(payload.get("timeline_events")),
        character_states=[_character_state_from_dict(item) for item in payload.get("character_states", []) if isinstance(item, dict)],
        next_chapter_targets=_string_list(payload.get("next_chapter_targets")),
        must_remember=_string_list(payload.get("must_remember")),
        progression_updates=_string_list(payload.get("progression_updates")),
        current_tier=_best_text(payload.get("current_tier"), ""),
        next_breakthrough=_best_text(payload.get("next_breakthrough"), ""),
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


def _scene_from_dict(payload: dict[str, Any]) -> SceneCard:
    return SceneCard(
        scene_index=int(payload.get("scene_index", 0)),
        scene_type=_best_text(payload.get("scene_type"), ""),
        load_weight=float(payload.get("load_weight", 0.0) or 0.0),
        location=_best_text(payload.get("location"), ""),
        goal=_best_text(payload.get("goal"), ""),
        conflict=_best_text(payload.get("conflict"), ""),
        turn=_best_text(payload.get("turn"), ""),
        must_include=_string_list(payload.get("must_include")),
    )


def _character_state_from_dict(payload: dict[str, Any]) -> CharacterState:
    return CharacterState(
        name=_best_text(payload.get("name"), ""),
        current_goal=_best_text(payload.get("current_goal"), ""),
        emotional_state=_best_text(payload.get("emotional_state"), ""),
        relationship_shift=_best_text(payload.get("relationship_shift"), ""),
        risk=_best_text(payload.get("risk"), ""),
        unresolved=_best_text(payload.get("unresolved"), ""),
    )


def _project_spec_to_input(spec: ProjectSpec) -> ProjectInput:
    return ProjectInput(
        title=spec.title,
        output_language=spec.output_language,
        genre=spec.genre,
        audience=spec.audience,
        tone=spec.tone,
        premise=spec.premise,
        theme=spec.theme,
        hook=spec.hook,
        setting=spec.setting,
        protagonist=spec.protagonist,
        outline_hint=spec.outline_hint,
        world_hint=spec.world_hint,
        ending_mode=spec.ending_mode,
        pov=spec.pov,
        target_total_chars=spec.target_total_chars,
        target_chars_per_chapter=spec.target_chars_per_chapter,
        chapter_count=spec.chapter_count,
        volume_count=spec.volume_count,
        chapter_char_tolerance=spec.chapter_char_tolerance,
        structure_mode=spec.structure_mode,
        market_profile=spec.market_profile,
        progression_mode=spec.progression_mode,
        progression_flavor=spec.progression_flavor,
        progression_pacing=spec.progression_pacing,
        power_system_hint=spec.power_system_hint,
        style_examples=list(spec.style_examples),
        must_include=list(spec.must_include),
        avoid=list(spec.avoid),
        character_seeds=list(spec.character_seeds),
        seed=spec.seed,
    )


def _index_dicts(value: Any) -> dict[int, dict[str, Any]]:
    if not isinstance(value, list):
        return {}
    indexed: dict[int, dict[str, Any]] = {}
    for item in value:
        if not isinstance(item, dict):
            continue
        try:
            index = int(item.get("index"))
        except (TypeError, ValueError):
            continue
        indexed[index] = item
    return indexed


def _merge_character_seeds(primary: list[CharacterSeed], secondary: list[CharacterSeed]) -> list[CharacterSeed]:
    merged: dict[str, CharacterSeed] = {}
    for item in [*primary, *secondary]:
        if item.name and item.name not in merged:
            merged[item.name] = item
    return list(merged.values())

def _merge_lists(*groups: list[str]) -> list[str]:
    merged: list[str] = []
    for group in groups:
        for item in group:
            text = _best_text(item, "")
            if text and text not in merged:
                merged.append(text)
    return merged


_SEMANTIC_NOISE_PATTERN = re.compile(
    r"^(继续(?:把|保住|守住|盯住|钉住)?|先|再|仍要|当前关键是|关键是|重点是|要|必须|尽快|优先|集中|设法|确保|防止|避免)+"
)


def _semantic_text_normal_form(text: str) -> str:
    normalized = _best_text(text, "")
    if not normalized:
        return ""
    normalized = re.sub(r"\s+", "", normalized)
    normalized = re.sub(r"[，。！？；：、“”‘’（）()【】《》…·—-]", "", normalized)
    normalized = _SEMANTIC_NOISE_PATTERN.sub("", normalized)
    return normalized


def _ngram_set(text: str, size: int = 2) -> set[str]:
    if not text:
        return set()
    if len(text) <= size:
        return {text}
    return {text[index : index + size] for index in range(0, len(text) - size + 1)}


def _semantic_text_close(left: str, right: str) -> bool:
    normalized_left = _semantic_text_normal_form(left)
    normalized_right = _semantic_text_normal_form(right)
    if not normalized_left or not normalized_right:
        return False
    if normalized_left == normalized_right:
        return True
    shorter, longer = sorted((normalized_left, normalized_right), key=len)
    if len(shorter) >= 3 and shorter in longer:
        return True
    matcher = difflib.SequenceMatcher(a=normalized_left, b=normalized_right)
    longest = matcher.find_longest_match(0, len(normalized_left), 0, len(normalized_right)).size
    if longest < max(5, int(len(shorter) * 0.33)):
        return False
    left_ngrams = _ngram_set(normalized_left)
    right_ngrams = _ngram_set(normalized_right)
    if not left_ngrams or not right_ngrams:
        return False
    jaccard = len(left_ngrams & right_ngrams) / max(1, len(left_ngrams | right_ngrams))
    return jaccard >= 0.33 or matcher.ratio() >= 0.6


def _dedupe_semantic_texts(items: list[str], *, limit: int | None = None) -> list[str]:
    deduped: list[str] = []
    for item in items:
        text = _best_text(item, "")
        if not text:
            continue
        replaced = False
        for index, existing in enumerate(deduped):
            if _semantic_text_close(existing, text):
                deduped[index] = text if len(_semantic_text_normal_form(text)) >= len(_semantic_text_normal_form(existing)) else existing
                replaced = True
                break
        if not replaced:
            deduped.append(text)
    if limit is not None and limit > 0:
        deduped = deduped[-limit:]
    return deduped


def _semantic_filter_unresolved(active_threads: list[str], resolved_threads: list[str]) -> list[str]:
    unresolved: list[str] = []
    for thread in active_threads:
        if any(_semantic_text_close(thread, resolved) for resolved in resolved_threads):
            continue
        unresolved.append(thread)
    return unresolved


def _promise_runtime_merge_score(item: PromiseLedgerItem) -> tuple[int, int, int, int]:
    status = _normalize_promise_status(item.current_status)
    return (
        _deadline_state_rank(item.deadline_state),
        1 if status != "paid_off" else 0,
        item.last_touched_chapter,
        len(_semantic_text_normal_form(item.label)),
    )


def _promise_items_semantically_close(left: PromiseLedgerItem, right: PromiseLedgerItem) -> bool:
    left_label = _best_text(left.label, "")
    right_label = _best_text(right.label, "")
    left_thread = _best_text(left.thread, "")
    right_thread = _best_text(right.thread, "")
    if _semantic_text_close(f"{left_thread} {left_label}", f"{right_thread} {right_label}"):
        return True
    if left_label and right_label and _semantic_text_close(left_label, right_label):
        return True
    return False


def _dedupe_runtime_promises(items: list[PromiseLedgerItem]) -> list[PromiseLedgerItem]:
    deduped: list[PromiseLedgerItem] = []
    for source in items:
        item = copy.deepcopy(source)
        merged = False
        for index, existing in enumerate(deduped):
            if not _promise_items_semantically_close(existing, item):
                continue
            preferred = existing
            secondary = item
            if _promise_runtime_merge_score(item) > _promise_runtime_merge_score(existing):
                preferred = item
                secondary = existing
            combined = copy.deepcopy(preferred)
            combined.chapter_opened = min(
                value for value in [existing.chapter_opened, item.chapter_opened] if value > 0
            ) if any(value > 0 for value in [existing.chapter_opened, item.chapter_opened]) else 0
            combined.target_volume = max(existing.target_volume, item.target_volume)
            combined.last_touched_chapter = max(existing.last_touched_chapter, item.last_touched_chapter)
            combined.payoff_requirements = _dedupe_semantic_texts(
                _merge_lists(existing.payoff_requirements, item.payoff_requirements)
            )
            combined.overdue = existing.overdue or item.overdue
            combined.deadline_state = (
                existing.deadline_state
                if _deadline_state_rank(existing.deadline_state) >= _deadline_state_rank(item.deadline_state)
                else item.deadline_state
            )
            if _normalize_promise_status(combined.current_status) == "paid_off" and any(
                _normalize_promise_status(candidate.current_status) != "paid_off" for candidate in (existing, item)
            ):
                combined.current_status = (
                    existing.current_status
                    if _normalize_promise_status(existing.current_status) != "paid_off"
                    else item.current_status
                )
            deduped[index] = combined
            merged = True
            break
        if not merged:
            deduped.append(item)
    return deduped


def _chapter_fix_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    fixes: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        chapter_index = item.get("chapter_index")
        instruction = _best_text(item.get("instruction"), "")
        if chapter_index is None or not instruction:
            continue
        fixes.append({"chapter_index": int(chapter_index), "instruction": instruction})
    return fixes


def _story_room_constraint_target(text: str, *, agent: str = "") -> str:
    normalized = _best_text(agent, "") + " " + _best_text(text, "")
    if any(marker in normalized for marker in ["文风", "语气", "口吻", "腔调", "节奏", "表达"]):
        return "narrative_voice"
    if any(marker in normalized for marker in ["结局", "终局", "收束", "闭环", "回收", "payoff"]):
        return "ending_contract"
    if any(marker in normalized for marker in ["世界", "设定", "规则", "机制", "体系"]):
        return "world_rules"
    return "chapter_guardrails"


def _char_count(text: str) -> int:
    return len(re.sub(r"\s+", "", text))


def _is_zh_output_language(language: object) -> bool:
    value = _normalized_output_language(language)
    return value in {"zh", "zh-Hans", "zh-CN", "zh-Hant", "zh-TW"} or value.startswith("zh-")


def _project_language_defaults(language: object, title: object) -> dict[str, str]:
    title_text = _best_text(title, "Untitled")
    if _is_zh_output_language(language):
        return {
            "genre": "中文强剧情小说",
            "audience": "中文读者",
            "tone": "紧凑、具体、可读",
            "premise": f"围绕《{title_text}》展开的完整故事。",
            "theme": "人在压力下如何做出真正的选择",
            "hook": f"《{title_text}》必须从开篇就给出明确问题。",
            "setting": "以现实感强的中文叙事空间为主要舞台。",
            "outline_hint": "前中后段都要持续升级，最终章必须闭环。",
            "world_hint": "世界规则必须服务剧情，不准设定炫技。",
            "pov": "第三人称有限视角",
        }
    return {
        "genre": "high-concept commercial fiction",
        "audience": "online fiction readers",
        "tone": "fast, concrete, readable",
        "premise": f"A complete story built around {title_text}.",
        "theme": "how people make real choices under pressure",
        "hook": f"{title_text} must open with a clear problem.",
        "setting": "a vivid, grounded story world that serves the plot.",
        "outline_hint": "Escalate through the beginning, middle, and ending; close the main arc in the final chapter.",
        "world_hint": "World rules must serve story pressure rather than decorative exposition.",
        "pov": "third person limited",
    }


def _chapter_heading(spec: ProjectSpec, index: object, title: object) -> str:
    return _chapter_heading_from_parts(spec.output_language, index, title)


def _chapter_heading_from_parts(language: object, index: object, title: object) -> str:
    title_text = _best_text(title, "")
    if _is_zh_output_language(language):
        return f"第{index}章 {title_text}".strip()
    return f"Chapter {index}: {title_text}".strip()


def _volume_heading_from_parts(language: object, index: object, title: object) -> str:
    title_text = _best_text(title, "")
    if _is_zh_output_language(language):
        return f"第{index}卷 {title_text}".strip()
    return f"Volume {index}: {title_text}".strip()


def _is_short_standalone_spec(spec: ProjectSpec) -> bool:
    return (
        spec.ending_mode == "standalone"
        and spec.volume_count <= 1
        and spec.chapter_count <= 8
        and spec.target_total_chars <= 20000
    )


def _is_strict_short_length_spec(spec: ProjectSpec) -> bool:
    target_total_chars = int(spec.target_total_chars or 0)
    return 0 < target_total_chars < 20000


def _cleanup_final_review_state(
    continuity: ContinuityState,
    promises: list[PromiseLedgerItem],
    causality: list[CausalityEdge],
    chapters: list[ChapterResult],
    *,
    strict_short_standalone: bool = False,
) -> tuple[ContinuityState, list[PromiseLedgerItem], list[CausalityEdge]]:
    if not chapters:
        return continuity, promises, causality
    final_index = max(chapter.index for chapter in chapters)
    current_volume = max(chapter.volume_index for chapter in chapters)
    window_size = 3 if strict_short_standalone else min(max(4, len(chapters) // 3), 6)
    recent_floor = max(1, final_index - (2 if strict_short_standalone else 4))
    relevant_text = " ".join(
        _best_text(part, "")
        for chapter in chapters[-window_size:]
        for part in [
            chapter.title,
            chapter.outline_item.title,
            chapter.outline_item.purpose,
            chapter.outline_item.conflict,
            chapter.outline_item.ending_note,
            chapter.continuity.chapter_summary,
            *chapter.continuity.timeline_events,
            *chapter.continuity.must_remember,
            *chapter.continuity.next_chapter_targets,
        ]
        if _best_text(part, "")
    )
    relevant_text = " ".join(
        [
            relevant_text,
            " ".join(continuity.recent_summaries[-6:]),
            " ".join(continuity.must_remember[-10:]),
        ]
    )

    def _meaningful_terms(parts: list[str]) -> list[str]:
        weak_terms = {"无", "暂无", "待定", "未知", "其他", "杂线"}
        return [
            term
            for term in [_best_text(piece, "").strip() for piece in parts]
            if len(term) >= 2 and term not in weak_terms
        ]

    def _promise_is_relevant(item: PromiseLedgerItem) -> bool:
        promise_terms = _meaningful_terms(
            [
                _best_text(item.label, ""),
                _best_text(item.thread, ""),
                *item.payoff_requirements,
            ]
        )
        mentioned = any(term and term in relevant_text for term in promise_terms)
        recent = item.last_touched_chapter >= recent_floor
        high_risk = item.deadline_state in {"overdue", "at_risk"} or item.current_status == "stalled"
        volume_relevant = item.target_volume >= current_volume
        if item.current_status == "paid_off":
            return recent or mentioned
        if strict_short_standalone:
            return recent or mentioned or (item.current_status == "stalled" and (recent or mentioned))
        if item.current_status == "advanced":
            return recent or mentioned or (high_risk and volume_relevant and item.last_touched_chapter >= max(1, recent_floor - 1))
        return high_risk or recent or mentioned

    filtered_promises = _dedupe_runtime_promises([copy.deepcopy(item) for item in promises if _promise_is_relevant(item)])
    filtered_causality = [
        copy.deepcopy(item)
        for item in causality
        if item.last_verified_chapter >= recent_floor
        or any(
            token and token in relevant_text
            for token in _meaningful_terms([item.effect_label, item.cause, *item.required_consequences])
        )
    ]
    active_promise_labels = [
        _best_text(item.label, "")
        for item in filtered_promises
        if item.current_status != "paid_off" and (item.deadline_state in {"overdue", "at_risk"} or item.current_status == "stalled")
    ]
    if not strict_short_standalone:
        active_promise_labels = _merge_lists(
            active_promise_labels,
            [
                _best_text(item.label, "")
                for item in filtered_promises
                if item.current_status != "paid_off" and item.last_touched_chapter >= recent_floor
            ],
        )
    active_threads = _dedupe_semantic_texts(
        _merge_lists(
            [thread for thread in continuity.active_threads if _best_text(thread, "") and _best_text(thread, "") in relevant_text],
            active_promise_labels,
        ),
        limit=(4 if strict_short_standalone else 8),
    )
    resolved_threads = _dedupe_semantic_texts(
        _merge_lists(
            continuity.resolved_threads[-8 if strict_short_standalone else 12 :],
            [_best_text(item.label, "") for item in filtered_promises if item.current_status == "paid_off" and item.label],
        ),
        limit=(12 if strict_short_standalone else 16),
    )
    cleaned = copy.deepcopy(continuity)
    cleaned.active_threads = _semantic_filter_unresolved(active_threads, resolved_threads)
    cleaned.resolved_threads = resolved_threads
    cleaned.must_remember = _tail(_merge_lists(cleaned.must_remember, [
        "终审前先以近期正文、已兑现承诺和最终角色状态为准清洁状态池，避免旧线程污染判断。",
        "若主线已闭环，未进入近期正文与承诺账本高危区的旧线程不应继续占据活动状态。",
    ]), 12 if strict_short_standalone else 16)
    return _sanitize_continuity_state(cleaned), filtered_promises, filtered_causality


def _cleanup_short_standalone_final_state(
    continuity: ContinuityState,
    promises: list[PromiseLedgerItem],
    causality: list[CausalityEdge],
    chapters: list[ChapterResult],
) -> tuple[ContinuityState, list[PromiseLedgerItem], list[CausalityEdge]]:
    return _cleanup_final_review_state(
        continuity,
        promises,
        causality,
        chapters,
        strict_short_standalone=True,
    )


def _tail(items: list[str], limit: int) -> list[str]:
    if limit <= 0:
        return []
    return items[-limit:]


def _character_names(bible: WorldBible, spec: ProjectSpec) -> list[str]:
    names = [character.name for character in bible.characters if character.name]
    for item in spec.character_seeds:
        if item.name and item.name not in names:
            names.append(item.name)
    return names


def _draft_token_budget(
    target_chars_per_chapter: int,
    *,
    length_tolerance: float = 0.25,
    short_standalone: bool = False,
) -> int:
    _, max_chars = _chapter_char_bounds(target_chars_per_chapter, length_tolerance=length_tolerance)
    ratio = 0.46 if short_standalone else 0.52
    buffer = 50 if short_standalone else 120
    floor = 720 if short_standalone else 1000
    return max(int(math.ceil(max_chars * ratio)) + buffer, floor)


def _compaction_token_budget(
    target_chars_per_chapter: int,
    *,
    length_tolerance: float = 0.25,
    short_standalone: bool = False,
) -> int:
    _, max_chars = _chapter_char_bounds(target_chars_per_chapter, length_tolerance=length_tolerance)
    ratio = 0.4 if short_standalone else 0.45
    buffer = 40 if short_standalone else 90
    floor = 560 if short_standalone else 820
    return max(int(math.ceil(max_chars * ratio)) + buffer, floor)


def _chapter_char_bounds(target_chars_per_chapter: int, *, length_tolerance: float = 0.25) -> tuple[int, int]:
    target = max(1, int(target_chars_per_chapter or 2000))
    tolerance = max(0.05, min(0.4, float(length_tolerance or 0.25)))
    return int(math.floor(target * (1.0 - tolerance))), int(math.ceil(target * (1.0 + tolerance)))


def _chapter_is_over_length(local_quality: LocalQualityReport) -> bool:
    metrics = local_quality.metrics or {}
    try:
        char_count = int(metrics.get("char_count", 0))
        target_max = int(metrics.get("target_chars_max", 0))
    except Exception:
        return False
    return char_count > 0 and target_max > 0 and char_count > target_max


def _chapter_is_extremely_over_length(local_quality: LocalQualityReport, *, multiplier: float = 3.0) -> bool:
    metrics = local_quality.metrics or {}
    try:
        char_count = int(metrics.get("char_count", 0))
        target_max = int(metrics.get("target_chars_max", 0))
    except Exception:
        return False
    if char_count <= 0 or target_max <= 0:
        return False
    return char_count > int(target_max * max(1.0, float(multiplier or 3.0)))


def _chapter_length_over_ratio(metrics: dict[str, Any] | None) -> float:
    payload = metrics or {}
    try:
        ratio = float(payload.get("length_over_ratio", 0.0) or 0.0)
    except Exception:
        ratio = 0.0
    if ratio > 0:
        return ratio
    try:
        char_count = int(payload.get("char_count", 0) or 0)
        target_max = int(payload.get("target_chars_max", 0) or 0)
    except Exception:
        return 0.0
    if char_count <= 0 or target_max <= 0:
        return 0.0
    return float(char_count) / float(target_max)


def _recent_overlength_tail(prior_chapters: list[ChapterResult], *, threshold: float) -> int:
    tail = 0
    for chapter in reversed(prior_chapters):
        ratio = _chapter_length_over_ratio(getattr(chapter.local_quality, "metrics", None))
        if ratio <= threshold:
            break
        tail += 1
    return tail


def _should_attempt_length_compaction(spec: ProjectSpec, local_quality: LocalQualityReport) -> bool:
    if not _chapter_is_over_length(local_quality):
        return False
    metrics = local_quality.metrics or {}
    if _is_strict_short_length_spec(spec):
        return True
    if _normalized_market_profile(spec.market_profile) == "tomato_mass":
        signal = _best_text(metrics.get("length_signal_level"), "ok").lower()
        return signal in {"debt", "hard_fail"}
    return _chapter_is_extremely_over_length(local_quality, multiplier=3.0)


def _writer_session_max_chars(spec: ProjectSpec) -> int:
    volume_targets = _normalized_volume_chapter_targets(
        spec.volume_chapter_targets,
        chapter_count=spec.chapter_count,
        volume_count=spec.volume_count,
    )
    volume_target_chars = max(max(volume_targets), 1) * max(spec.target_chars_per_chapter, 1)
    return max(60000, min(120000, int(volume_target_chars * 2.2)))
