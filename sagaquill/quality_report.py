from __future__ import annotations

import re
from collections import Counter
from dataclasses import asdict
from typing import Any

from .models import (
    CausalityEdge,
    ChapterResult,
    ContinuityState,
    FinalReview,
    LogicAuditReport,
    LocalQualityReport,
    PromiseLedgerItem,
    ProjectSpec,
    ProgressionLedgerItem,
)
from .projectio import is_chinese_output_language


QUALITY_POLICY_VERSION = "2026-05-05"


def build_quality_report(
    *,
    spec: ProjectSpec,
    chapters: list[ChapterResult],
    final_review: FinalReview,
    continuity: ContinuityState,
    promise_ledger: list[PromiseLedgerItem] | None = None,
    causality_graph: list[CausalityEdge] | None = None,
    progression_ledger: list[ProgressionLedgerItem] | None = None,
    logic_audits: list[LogicAuditReport] | None = None,
    total_chars: int = 0,
) -> dict[str, Any]:
    ordered = sorted(chapters, key=lambda item: item.index)
    checks = _build_checks(
        spec=spec,
        chapters=ordered,
        final_review=final_review,
        continuity=continuity,
        promise_ledger=promise_ledger or [],
        causality_graph=causality_graph or [],
        progression_ledger=progression_ledger or [],
        logic_audits=logic_audits or [],
    )
    counts = _severity_counts(checks)
    status = "fail" if counts["red"] or counts["fail"] else "warn" if counts["warn"] else "pass"
    score = _quality_score(checks, final_review)
    return {
        "schema_version": 1,
        "policy_version": QUALITY_POLICY_VERSION,
        "status": status,
        "score": score,
        "summary": _summary_text(status, counts, spec),
        "project": {
            "title": spec.title,
            "market_profile": spec.market_profile,
            "progression_mode": spec.progression_mode,
            "output_language": spec.output_language,
            "chapter_count": len(ordered),
            "volume_count": spec.volume_count,
            "total_chars": int(total_chars or 0),
            "target_total_chars": spec.target_total_chars,
        },
        "scorecard": _scorecard(checks),
        "counts": counts,
        "rules": quality_policy_rules(spec),
        "checks": checks,
        "auto_repair_log": _auto_repair_log(ordered, logic_audits or []),
        "source_artifacts": {
            "chapter_reviews": "reviews/chapter-*.review.json",
            "logic_audits": "audits/volume-*.logic-audit.json",
            "final_review": "data/final-review.json",
            "continuity_state": "data/continuity-state.json",
            "promise_ledger": "data/promise-ledger.json",
            "causality_graph": "data/causality-graph.json",
            "progression_ledger": "data/progression-ledger.json",
        },
    }


def render_quality_report_markdown(report: dict[str, Any], *, output_language: str = "zh-Hans") -> str:
    zh = is_chinese_output_language(output_language)
    title = "质量报告" if zh else "Quality Report"
    status_label = _status_label(str(report.get("status") or "pass"), zh=zh)
    lines = [
        f"# {report.get('project', {}).get('title', '')} {title}".strip(),
        "",
        _kv("整体状态" if zh else "Overall status", status_label, zh),
        _kv("质量分" if zh else "Quality score", report.get("score", 0), zh),
        _kv("策略版本" if zh else "Policy version", report.get("policy_version", ""), zh),
        _kv("摘要" if zh else "Summary", report.get("summary", ""), zh),
        "",
        f"## {'计分卡' if zh else 'Scorecard'}",
        "",
    ]
    for item in report.get("scorecard", []):
        if not isinstance(item, dict):
            continue
        lines.append(
            _kv(
                str(item.get("label") or item.get("dimension") or ""),
                f"{_status_label(str(item.get('status') or 'pass'), zh=zh)}; "
                f"{'红线' if zh else 'red'} {item.get('red', 0)}, "
                f"{'失败' if zh else 'fail'} {item.get('fail', 0)}, "
                f"{'警告' if zh else 'warn'} {item.get('warn', 0)}",
                zh,
            )
        )
    lines.extend(["", f"## {'红线与失败项' if zh else 'Red Lines And Failures'}", ""])
    blocking = [
        item for item in report.get("checks", [])
        if isinstance(item, dict) and str(item.get("severity")) in {"red", "fail"}
    ]
    if not blocking:
        lines.append("未发现阻断性交付问题。" if zh else "No blocking delivery issues found.")
    else:
        for item in blocking:
            lines.extend(_render_check_item(item, zh=zh))
    lines.extend(["", f"## {'警告项' if zh else 'Warnings'}", ""])
    warnings = [
        item for item in report.get("checks", [])
        if isinstance(item, dict) and str(item.get("severity")) == "warn"
    ]
    if not warnings:
        lines.append("暂无警告项。" if zh else "No warnings.")
    else:
        for item in warnings[:30]:
            lines.extend(_render_check_item(item, zh=zh))
        if len(warnings) > 30:
            lines.append(f"... 还有 {len(warnings) - 30} 条警告，详见 quality-report.json。" if zh else f"... {len(warnings) - 30} more warnings. See quality-report.json.")
    lines.extend(["", f"## {'自动修复记录' if zh else 'Auto Repair Log'}", ""])
    repairs = report.get("auto_repair_log", [])
    if not repairs:
        lines.append("没有记录到自动回修。" if zh else "No automatic repair recorded.")
    else:
        for item in repairs[:40]:
            if not isinstance(item, dict):
                continue
            chapter = item.get("chapter_index", "-")
            action = item.get("action", "")
            reason = item.get("reason", "")
            lines.append(f"- {'第' + str(chapter) + '章' if zh else 'Chapter ' + str(chapter)}: {action} - {reason}".rstrip(" -"))
    lines.extend(["", f"## {'质检规则摘要' if zh else 'Quality Policy Summary'}", ""])
    for rule in report.get("rules", []):
        if not isinstance(rule, dict):
            continue
        lines.append(f"- `{rule.get('id')}` {rule.get('name')}: {rule.get('description')}")
    return "\n".join(str(line) for line in lines).strip() + "\n"


def quality_policy_rules(spec: ProjectSpec | None = None) -> list[dict[str, Any]]:
    market_profile = (getattr(spec, "market_profile", "") or "").strip() if spec else ""
    progression_mode = (getattr(spec, "progression_mode", "") or "").strip() if spec else ""
    return [
        {
            "id": "hygiene.placeholder",
            "dimension": "hygiene",
            "name": "占位与未完成痕迹",
            "severity": "red",
            "description": "正文、终审或章节审校中出现 TODO、placeholder、作者按、这里略去、待补等未完成痕迹时，判为红线。",
        },
        {
            "id": "repetition.duplicate_block",
            "dimension": "repetition",
            "name": "重复段落与重复句",
            "severity": "fail",
            "description": "长段重复、章节开场重复、重复句超过整书容忍线时判为失败；轻微短句重复只记警告。",
        },
        {
            "id": "density.procedural_load",
            "dimension": "density",
            "name": "术语/流程密度",
            "severity": "fail",
            "description": "按章节 term_budget 统计流程词和制度词密度，超出硬阈值时判为失败，普通超标记为警告。",
        },
        {
            "id": "length.extreme",
            "dimension": "length",
            "name": "异常篇幅",
            "severity": "fail",
            "description": "章节或整书明显低于/高于容忍带时记录失败或债务；番茄模式会放宽普通长度问题，但仍保留极端异常红线。",
            "profile": market_profile,
        },
        {
            "id": "continuity.thread_integrity",
            "dimension": "continuity",
            "name": "连续性与承诺兑现",
            "severity": "fail",
            "description": "结合连续性状态、承诺账本和逻辑审计，标记线索失踪、承诺逾期、因果链断裂和资料污染。",
        },
        {
            "id": "character.voice_and_state",
            "dimension": "character",
            "name": "人物状态与声线",
            "severity": "fail",
            "description": "结合角色声线卡、连续性 character_states 和逻辑审计，标记人物目标回退、关系突变、同腔同调和设定冲突。",
        },
        {
            "id": "timeline.event_order",
            "dimension": "timeline",
            "name": "时间线一致性",
            "severity": "fail",
            "description": "从章节 continuity timeline_events 和逻辑审计中检查时间顺序、地点转移、先后因果是否打架。",
        },
        {
            "id": "progression.realm_payoff",
            "dimension": "progression",
            "name": "升级系统兑现",
            "severity": "fail",
            "description": "硬升级模式下检查台阶、资源、敌人梯度、突破代价和阶段回报是否持续推进。",
            "profile": progression_mode,
        },
        {
            "id": "ending.closure",
            "dimension": "ending",
            "name": "结尾闭环",
            "severity": "fail",
            "description": "standalone 结局不能只用新事件或下一案钩子替代主线收束。",
        },
    ]


def _build_checks(
    *,
    spec: ProjectSpec,
    chapters: list[ChapterResult],
    final_review: FinalReview,
    continuity: ContinuityState,
    promise_ledger: list[PromiseLedgerItem],
    causality_graph: list[CausalityEdge],
    progression_ledger: list[ProgressionLedgerItem],
    logic_audits: list[LogicAuditReport],
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    checks.extend(_chapter_quality_checks(chapters))
    checks.extend(_final_quality_checks(final_review))
    checks.extend(_continuity_checks(continuity, promise_ledger, causality_graph, logic_audits))
    checks.extend(_progression_checks(spec, progression_ledger, final_review))
    checks.extend(_timeline_checks(chapters, logic_audits))
    checks.extend(_character_checks(chapters, logic_audits))
    return sorted(checks, key=lambda item: (_severity_rank(item["severity"]), item.get("chapter_index") or 0, item["id"]))


def _chapter_quality_checks(chapters: list[ChapterResult]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for chapter in chapters:
        local = chapter.local_quality
        review = chapter.review
        metrics = local.metrics or {}
        chapter_ref = {"chapter_index": chapter.index, "chapter_title": chapter.title}
        if metrics.get("placeholder_hits"):
            checks.append(_check("hygiene.placeholder", "hygiene", "red", "占位与未完成痕迹", "本章出现占位词或未完成标记。", chapter_ref, evidence=metrics.get("placeholder_hits"), action="重写或清稿，清除占位词与草稿残句。"))
        if int(metrics.get("duplicate_paragraphs", 0) or 0) > 0:
            checks.append(_check("repetition.duplicate_paragraph", "repetition", "fail", "重复段落", "本章存在长段重复，疑似生成打转。", chapter_ref, evidence={"duplicate_paragraphs": metrics.get("duplicate_paragraphs")}, action="删除重复段或按原场景目标重写。"))
        if int(metrics.get("duplicate_sentences", 0) or 0) > 1:
            checks.append(_check("repetition.duplicate_sentence", "repetition", "warn", "重复句式", "本章存在重复句式或重复句子。", chapter_ref, evidence={"duplicate_sentences": metrics.get("duplicate_sentences")}, action="发行前做压重和句式替换。"))
        if metrics.get("procedural_density_hard_fail"):
            checks.append(_check("density.procedural_hard_fail", "density", "fail", "术语/流程密度硬超标", "术语和流程信息压住阅读。", chapter_ref, evidence=_metric_pick(metrics, ["procedural_term_hits", "procedural_term_distinct", "term_budget"]), action="压缩流程解释，把制度信息改成动作、代价或冲突结果。"))
        elif any("术语" in item or "流程" in item for item in local.issues):
            checks.append(_check("density.procedural_warning", "density", "warn", "术语/流程密度偏高", "术语或流程说明偏密。", chapter_ref, evidence=_matching_issues(local, ("术语", "流程")), action="减少新名词，优先复用已有概念并绑定具体后果。"))
        if metrics.get("length_hard_fail"):
            checks.append(_check("length.chapter_hard_fail", "length", "fail", "章节篇幅异常", "章节篇幅明显偏离容忍带。", chapter_ref, evidence=_metric_pick(metrics, ["char_count", "target_chars_min", "target_chars_max", "length_under_ratio", "length_over_ratio"]), action="偏短则补场景层次和回报，偏长则压缩重复解释。"))
        elif metrics.get("length_debt") or metrics.get("length_warning"):
            checks.append(_check("length.chapter_warning", "length", "warn", "章节篇幅债务", "章节篇幅有轻度偏差。", chapter_ref, evidence=_metric_pick(metrics, ["char_count", "target_chars_min", "target_chars_max", "length_signal_level"]), action="后续章节回补或收束节奏。"))
        if metrics.get("stagnation_debt") or metrics.get("stagnation_escalation"):
            severity = "fail" if metrics.get("stagnation_escalation") else "warn"
            checks.append(_check("repetition.propulsion_stagnation", "repetition", severity, "推进同构/空转", "最近章节推进簇或章型重复度偏高。", chapter_ref, evidence=_metric_pick(metrics, ["current_propulsion", "recent_propulsion_history", "stagnation_signal_level", "stagnation_same_family_tail", "stagnation_same_role_tail"]), action="更换 scene 功能、后果类型、站位变化或升级回报。"))
        if metrics.get("ending_voice_hard_fail"):
            checks.append(_check("character.ending_voice_convergence", "character", "fail", "收束段人物同腔", "终盘人物声线趋同。", chapter_ref, evidence=_matching_issues(local, ("同一种", "声口", "语气")), action="按角色声线卡重写关键对白和情绪反应。"))
        if metrics.get("progression_fake_payoff") or metrics.get("progression_stall"):
            checks.append(_check("progression.chapter_debt", "progression", "warn", "章节升级债务", "本章升级回报、代价或台阶推进不够明确。", chapter_ref, evidence=_metric_pick(metrics, ["progression_step_type", "current_tier", "target_tier", "progression_reward", "progression_cost", "progression_signal_level"]), action="补清突破条件、代价、资源变化或能力回报。"))
        if not local.passed:
            checks.append(_check("chapter.local_gate_failed", "chapter", "fail", "本地质量门未通过", local.short_summary or "本地质量门未通过。", chapter_ref, evidence=local.issues[:6], action="按本地 issues 定向重写或回修。"))
        if not review.passed:
            checks.append(_check("chapter.model_review_failed", "chapter", "fail", "模型审校未通过", review.short_summary or "模型审校未通过。", chapter_ref, evidence=[*review.issues[:4], *review.required_fixes[:4]], action="优先执行 required_fixes；若与本地门冲突，进入仲裁/重审。"))
        if chapter.attempts > 1:
            checks.append(_check("chapter.auto_rewrite", "chapter", "info", "章节发生自动重写", f"本章经过 {chapter.attempts} 次尝试后通过。", chapter_ref, evidence={"attempts": chapter.attempts}, action="已自动处理；交付前可抽检。"))
    return checks


def _final_quality_checks(final_review: FinalReview) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    local = final_review.local_quality
    if local is not None:
        metrics = local.metrics or {}
        if metrics.get("placeholder_hits"):
            checks.append(_check("final.placeholder", "hygiene", "red", "整书占位痕迹", "整书本地终审发现占位词。", evidence=metrics.get("placeholder_hits"), action="全书搜索并清稿。"))
        if int(metrics.get("duplicate_paragraphs", 0) or 0) > int(metrics.get("allowed_duplicate_paragraphs", 0) or 0):
            checks.append(_check("final.duplicate_paragraphs", "repetition", "fail", "整书重复段落超标", "整书长段重复超过容忍线。", evidence=_metric_pick(metrics, ["duplicate_paragraphs", "allowed_duplicate_paragraphs"]), action="运行发行前压重，删除重复段。"))
        if int(metrics.get("duplicate_openings", 0) or 0) > int(metrics.get("allowed_duplicate_openings", 0) or 0):
            checks.append(_check("final.duplicate_openings", "repetition", "fail", "章节开场重复超标", "不同章节开场趋同。", evidence=_metric_pick(metrics, ["duplicate_openings", "allowed_duplicate_openings"]), action="重写重复开场，增加场景差异。"))
        if metrics.get("novel_length_hard_fail"):
            checks.append(_check("final.length_hard_fail", "length", "fail", "整书字数严重偏离", "整书总字数严重偏离目标容忍带。", evidence=_metric_pick(metrics, ["novel_total_chars", "target_chars_min", "target_chars_max", "novel_length_over_ratio"]), action="调整规划或压缩重复支线。"))
        if metrics.get("progression_hard_fail"):
            checks.append(_check("final.progression_hard_fail", "progression", "fail", "升级系统整书失效", "硬升级模式下缺少清晰里程碑推进或终盘回报。", evidence=_metric_pick(metrics, ["progression_ledger_size", "progression_stall", "progression_hard_fail"]), action="回修升级里程碑、资源链和终盘兑现。"))
    if not final_review.passed:
        checks.append(_check("final.review_failed", "final_review", "fail", "终审未通过", final_review.short_summary or "终审未通过。", evidence=[*final_review.issues[:6], *final_review.required_fixes[:6]], action="按 chapter_fixes 或 required_fixes 做终审修订。"))
    for fix in final_review.chapter_fixes[:12]:
        checks.append(_check("final.chapter_fix", "final_review", "fail", "终审章节修订项", "终审要求修改具体章节。", {"chapter_index": fix.get("chapter_index")}, evidence=fix, action=str(fix.get("instruction") or "按终审要求修订。")))
    return checks


def _continuity_checks(
    continuity: ContinuityState,
    promise_ledger: list[PromiseLedgerItem],
    causality_graph: list[CausalityEdge],
    logic_audits: list[LogicAuditReport],
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    overdue = [item for item in promise_ledger if item.overdue or item.deadline_state == "overdue"]
    at_risk = [item for item in promise_ledger if item.deadline_state == "at_risk"]
    if overdue:
        checks.append(_check("continuity.promise_overdue", "continuity", "fail", "承诺账本逾期", "存在超过兑现窗口仍未推进的承诺或伏笔。", evidence=[_promise_payload(item) for item in overdue[:10]], action="回修对应章节或在后续章节明确兑现/关闭。"))
    if at_risk:
        checks.append(_check("continuity.promise_at_risk", "continuity", "warn", "承诺账本临期", "部分承诺接近风险窗口。", evidence=[_promise_payload(item) for item in at_risk[:10]], action="后续章节优先推进这些承诺。"))
    stale_edges = [item for item in causality_graph if continuity.last_chapter_index and item.last_verified_chapter and continuity.last_chapter_index - item.last_verified_chapter >= 30]
    if stale_edges:
        checks.append(_check("continuity.causality_stale", "continuity", "warn", "因果链长期未校验", "部分因果边很久没有被后文重新验证。", evidence=[_causality_payload(item) for item in stale_edges[:10]], action="后续逻辑审计或章节计划中重新校验这些因果后果。"))
    active_limit = max(20, continuity.last_chapter_index // 6)
    if len(continuity.active_threads) > active_limit:
        checks.append(_check("continuity.active_threads_high", "continuity", "warn", "活跃线索过多", "active_threads 数量偏高，可能导致读者记忆负担。", evidence={"active_threads": len(continuity.active_threads), "limit": active_limit, "sample": continuity.active_threads[:12]}, action="合并、关闭或转入 must_remember。"))
    for audit in logic_audits:
        severity = "fail" if not audit.gate_passed and audit.gate_level not in {"pass", "warn", "repair_metadata"} else "warn" if audit.issues or audit.watch_items else "info"
        if severity == "info":
            continue
        checks.append(_check("continuity.logic_audit", "continuity", severity, f"第 {getattr(audit, 'gate_level', 'warn')} 级逻辑审计", audit.summary or "逻辑审计发现长线风险。", evidence=[*audit.issues[:5], *audit.required_followups[:5]], action="按 logic audit 的 repair_plan 或 required_followups 处理。"))
    return checks


def _progression_checks(
    spec: ProjectSpec,
    progression_ledger: list[ProgressionLedgerItem],
    final_review: FinalReview,
) -> list[dict[str, Any]]:
    if spec.progression_mode != "hard_realm_progression":
        return []
    checks: list[dict[str, Any]] = []
    meaningful = [item for item in progression_ledger if item.status in {"advanced", "ready", "paid_off"}]
    paid_off = [item for item in progression_ledger if item.status == "paid_off"]
    if spec.chapter_count >= 20 and not meaningful:
        checks.append(_check("progression.no_meaningful_milestone", "progression", "fail", "缺少有效升级里程碑", "硬升级项目没有记录到有效推进的升级里程碑。", evidence={"progression_ledger_size": len(progression_ledger)}, action="补写升级体系圣经、卷目标和章节 progression_step_type。"))
    elif spec.chapter_count >= 20 and len(meaningful) <= 1:
        checks.append(_check("progression.weak_milestone_chain", "progression", "warn", "升级里程碑偏弱", "升级推进偏少，可能变成挂件。", evidence=[asdict(item) for item in meaningful[:4]], action="增加资源、试炼、突破和敌人梯度的阶段兑现。"))
    if spec.ending_mode == "standalone" and spec.chapter_count >= 20 and not paid_off and final_review.passed:
        checks.append(_check("progression.no_paid_off_stage", "progression", "warn", "缺少已兑现升级阶段", "standalone 结尾没有记录到 paid_off 的阶段回报。", evidence={"paid_off": 0, "progression_ledger_size": len(progression_ledger)}, action="终盘补出阶段回报或明确当前卷闭环。"))
    return checks


def _timeline_checks(chapters: list[ChapterResult], logic_audits: list[LogicAuditReport]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    empty_count = sum(1 for chapter in chapters if not chapter.continuity.timeline_events)
    if chapters and empty_count / len(chapters) > 0.35:
        checks.append(_check("timeline.sparse_events", "timeline", "warn", "时间线事件记录偏少", "超过三分之一章节没有提取到 timeline_events，后续时间线审计证据会变弱。", evidence={"empty_timeline_chapters": empty_count, "chapter_count": len(chapters)}, action="加强 continuity 提取或抽检对应章节。"))
    timeline_markers = ("时间线", "时间顺序", "先后", "同一晚", "同一天", "转场", "地点", "timeline")
    for audit in logic_audits:
        hits = [item for item in [*audit.issues, *audit.watch_items, *audit.required_followups] if _contains_any(item, timeline_markers)]
        if hits:
            checks.append(_check("timeline.logic_audit_signal", "timeline", "fail" if not audit.gate_passed else "warn", "逻辑审计标记时间线风险", "逻辑审计发现时间或地点连续性风险。", evidence=hits[:6], action="定位相关章节，修正事件顺序、地点转移或承接段。"))
    return checks


def _character_checks(chapters: list[ChapterResult], logic_audits: list[LogicAuditReport]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    state_counter = Counter(
        state.name
        for chapter in chapters
        for state in chapter.continuity.character_states
        if state.name
    )
    if chapters and not state_counter:
        checks.append(_check("character.no_state_tracking", "character", "warn", "人物状态记录为空", "连续性提取没有记录人物状态，人物设定冲突难以追踪。", evidence={"chapter_count": len(chapters)}, action="加强 continuity 提取，或在设定圣经里明确核心角色。"))
    character_markers = ("人物", "角色", "声口", "同腔", "动机", "关系", "状态", "character", "voice")
    for audit in logic_audits:
        hits = [item for item in [*audit.issues, *audit.voice_risks, *audit.watch_items, *audit.required_followups] if _contains_any(item, character_markers)]
        if hits:
            checks.append(_check("character.logic_audit_signal", "character", "fail" if not audit.gate_passed else "warn", "逻辑审计标记人物风险", "逻辑审计发现人物状态、动机或声线风险。", evidence=hits[:6], action="按角色声线卡和连续性状态重写相关章节。"))
    return checks


def _auto_repair_log(chapters: list[ChapterResult], logic_audits: list[LogicAuditReport]) -> list[dict[str, Any]]:
    repairs: list[dict[str, Any]] = []
    for chapter in chapters:
        if chapter.attempts > 1:
            repairs.append(
                {
                    "chapter_index": chapter.index,
                    "action": "chapter_rewrite",
                    "attempts": chapter.attempts,
                    "reason": "章节初稿未一次性通过质量门或审校。",
                }
            )
    for audit in logic_audits:
        for plan in audit.repair_plan:
            if not isinstance(plan, dict):
                continue
            repairs.append(
                {
                    "chapter_index": plan.get("start_chapter"),
                    "end_chapter": plan.get("end_chapter"),
                    "action": audit.gate_level or "logic_audit_repair",
                    "reason": plan.get("instruction") or audit.summary,
                }
            )
    return repairs


def _scorecard(checks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    dimensions = [
        ("hygiene", "清稿卫生"),
        ("length", "篇幅控制"),
        ("repetition", "重复/水文"),
        ("density", "术语密度"),
        ("continuity", "连续性"),
        ("timeline", "时间线"),
        ("character", "人物一致性"),
        ("progression", "升级系统"),
        ("ending", "结尾闭环"),
        ("final_review", "终审"),
    ]
    result = []
    for dimension, label in dimensions:
        items = [item for item in checks if item.get("dimension") == dimension]
        counts = _severity_counts(items)
        status = "fail" if counts["red"] or counts["fail"] else "warn" if counts["warn"] else "pass"
        result.append({"dimension": dimension, "label": label, "status": status, **counts})
    return result


def _severity_counts(checks: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"red": 0, "fail": 0, "warn": 0, "info": 0, "pass": 0}
    for item in checks:
        severity = str(item.get("severity") or "info")
        counts[severity if severity in counts else "info"] += 1
    return counts


def _quality_score(checks: list[dict[str, Any]], final_review: FinalReview) -> int:
    score = int(final_review.score or 0)
    counts = _severity_counts(checks)
    score -= counts["red"] * 25
    score -= counts["fail"] * 8
    score -= counts["warn"] * 2
    return max(0, min(100, score))


def _summary_text(status: str, counts: dict[str, int], spec: ProjectSpec) -> str:
    if is_chinese_output_language(spec.output_language):
        if status == "pass":
            return "未发现阻断性交付问题，仍建议抽检警告项。"
        if status == "warn":
            return f"发现 {counts['warn']} 个警告项，不阻断交付，但建议发行前处理。"
        return f"发现 {counts['red']} 个红线和 {counts['fail']} 个失败项，建议修复后再交付。"
    if status == "pass":
        return "No blocking delivery issues found. Spot-check warnings before publication."
    if status == "warn":
        return f"{counts['warn']} warning(s) found. Delivery is not blocked, but pre-release cleanup is recommended."
    return f"{counts['red']} red-line issue(s) and {counts['fail']} failure(s) found. Repair before delivery."


def _check(
    rule_id: str,
    dimension: str,
    severity: str,
    title: str,
    message: str,
    refs: dict[str, Any] | None = None,
    *,
    evidence: Any = None,
    action: str = "",
) -> dict[str, Any]:
    payload = {
        "id": rule_id,
        "dimension": dimension,
        "severity": severity,
        "title": title,
        "message": message,
        "evidence": evidence,
        "repair_action": action,
    }
    if refs:
        payload.update({key: value for key, value in refs.items() if value not in {None, ""}})
    return payload


def _render_check_item(item: dict[str, Any], *, zh: bool) -> list[str]:
    chapter = item.get("chapter_index")
    prefix = f"第 {chapter} 章" if zh and chapter else f"Chapter {chapter}" if chapter else "全书" if zh else "Book"
    lines = [
        f"- [{item.get('severity')}] {prefix} `{item.get('id')}` {item.get('title')}: {item.get('message')}",
    ]
    evidence = item.get("evidence")
    if evidence:
        lines.append(f"  {'证据' if zh else 'Evidence'}: {_short_repr(evidence)}")
    action = item.get("repair_action")
    if action:
        lines.append(f"  {'处理' if zh else 'Repair'}: {action}")
    return lines


def _kv(label: str, value: object, zh: bool) -> str:
    return f"- {label}：{value}" if zh else f"- {label}: {value}"


def _status_label(status: str, *, zh: bool) -> str:
    table = {
        "pass": ("通过", "pass"),
        "warn": ("警告", "warn"),
        "fail": ("失败", "fail"),
        "red": ("红线", "red"),
        "info": ("信息", "info"),
    }
    return table.get(status, (status, status))[0 if zh else 1]


def _severity_rank(severity: str) -> int:
    return {"red": 0, "fail": 1, "warn": 2, "info": 3, "pass": 4}.get(severity, 3)


def _metric_pick(metrics: dict[str, Any], keys: list[str]) -> dict[str, Any]:
    return {key: metrics.get(key) for key in keys if key in metrics}


def _matching_issues(report: LocalQualityReport, markers: tuple[str, ...]) -> list[str]:
    return [item for item in report.issues if _contains_any(item, markers)]


def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
    lowered = str(text or "").lower()
    return any(marker.lower() in lowered for marker in markers)


def _promise_payload(item: PromiseLedgerItem) -> dict[str, Any]:
    return {
        "promise_id": item.promise_id,
        "label": item.label,
        "thread": item.thread,
        "status": item.current_status,
        "deadline_state": item.deadline_state,
        "last_touched_chapter": item.last_touched_chapter,
        "target_volume": item.target_volume,
    }


def _causality_payload(item: CausalityEdge) -> dict[str, Any]:
    return {
        "effect_label": item.effect_label,
        "cause": item.cause,
        "introduced_chapter": item.introduced_chapter,
        "last_verified_chapter": item.last_verified_chapter,
        "required_consequences": item.required_consequences[:4],
    }


def _short_repr(value: Any, *, limit: int = 320) -> str:
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text if len(text) <= limit else text[: limit - 3] + "..."
