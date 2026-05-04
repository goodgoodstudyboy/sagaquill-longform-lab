from __future__ import annotations

import csv
import io
import time
import uuid
from dataclasses import asdict
from typing import Any

from .models import BatchConfig, BatchItemState, BatchRecord, CharacterSeed, ProjectInput, ProposalRecord
from .normalize import optional_text


_CSV_FIELD_MAP = {
    "编号": "row_id",
    "书名": "title",
    "赛道": "track",
    "平台适配": "platform_fit",
    "参考需求": "reference_requirements",
    "一句话钩子": "hook",
    "平台简介": "platform_blurb",
    "故事核心": "core_story",
    "主题": "theme",
    "世界场景": "world_scene",
    "世界观": "world_seed",
    "风格": "style_seed",
    "前30章": "chapter_seed",
    "卷纲": "volume_seed",
    "人物表": "character_seed",
    "备注": "notes",
}


def create_batch_from_csv(
    csv_text: str,
    *,
    source_name: str,
    batch_name: str | None = None,
    provider_snapshot: dict[str, Any] | None = None,
    config: BatchConfig | None = None,
) -> tuple[BatchRecord, list[ProposalRecord], list[BatchItemState]]:
    rows = _parse_csv_rows(csv_text)
    batch_id = f"batch-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    now = time.time()
    batch = BatchRecord(
        batch_id=batch_id,
        name=batch_name or source_name.rsplit(".", 1)[0] or batch_id,
        source_name=source_name,
        created_at=now,
        updated_at=now,
        status="draft",
        max_concurrent=2,
        provider_snapshot=dict(provider_snapshot or {}),
        config=config or BatchConfig(),
    )
    proposals: list[ProposalRecord] = []
    items: list[BatchItemState] = []
    for row_index, raw in enumerate(rows, start=1):
        proposal = _proposal_from_row(batch_id, row_index, raw)
        proposals.append(proposal)
        items.append(
            BatchItemState(
                batch_id=batch.batch_id,
                proposal_id=proposal.proposal_id,
                title=proposal.title,
                status="draft",
                selected=True,
                priority=row_index,
                created_at=now,
                updated_at=now,
            )
        )
    return batch, proposals, items


def batch_export_payload(batch: BatchRecord, proposals: list[ProposalRecord], items: list[BatchItemState]) -> dict[str, Any]:
    proposal_map = {proposal.proposal_id: proposal for proposal in proposals}
    return {
        "batch_id": batch.batch_id,
        "name": batch.name,
        "status": batch.status,
        "source_name": batch.source_name,
        "created_at": batch.created_at,
        "updated_at": batch.updated_at,
        "max_concurrent": batch.max_concurrent,
        "config": asdict(batch.config),
        "counts": batch_counts(items),
        "items": [
            {
                "proposal_id": item.proposal_id,
                "title": item.title,
                "status": item.status,
                "job_id": item.job_id,
                "output_dir": item.output_dir,
                "last_error": item.last_error,
                "pause_reason": item.pause_reason,
                "written_chars": item.written_chars,
                "hook": proposal_map.get(item.proposal_id).hook if proposal_map.get(item.proposal_id) else "",
                "platform_fit": proposal_map.get(item.proposal_id).platform_fit if proposal_map.get(item.proposal_id) else "",
            }
            for item in items
        ],
    }


def batch_counts(items: list[BatchItemState]) -> dict[str, int]:
    counts = {
        "total": len(items),
        "selected": 0,
        "draft": 0,
        "queued": 0,
        "launching": 0,
        "running": 0,
        "paused": 0,
        "completed": 0,
        "failed": 0,
    }
    for item in items:
        if item.selected:
            counts["selected"] += 1
        if item.status in counts:
            counts[item.status] += 1
    return counts


def proposal_to_project_input(proposal: ProposalRecord, config: BatchConfig) -> ProjectInput:
    protagonist, character_seeds = _character_seed_payload(proposal.character_seed)
    style_examples = _collect_lines(
        proposal.style_seed,
        proposal.reference_requirements,
        proposal.platform_fit,
    )
    must_include = _collect_lines(
        proposal.hook,
        proposal.core_story,
        proposal.chapter_seed,
        proposal.volume_seed,
    )
    avoid = []
    outline_hint = _join_sections(
        ("故事核心", proposal.core_story),
        ("前30章", proposal.chapter_seed),
        ("卷纲", proposal.volume_seed),
        ("备注", proposal.notes),
    )
    world_hint = _join_sections(
        ("世界场景", proposal.world_scene),
        ("世界观", proposal.world_seed),
    )
    premise = proposal.core_story or proposal.hook or proposal.platform_blurb or proposal.title
    ending_mode = config.ending_mode or ("series" if config.run_to_completion is False else "standalone")
    return ProjectInput(
        title=proposal.title,
        genre=optional_text(proposal.track),
        audience=optional_text(proposal.platform_fit),
        tone=optional_text(proposal.style_seed),
        premise=optional_text(premise),
        theme=optional_text(proposal.theme),
        hook=optional_text(proposal.hook),
        setting=optional_text(proposal.world_scene),
        protagonist=optional_text(protagonist),
        outline_hint=optional_text(outline_hint),
        world_hint=optional_text(world_hint),
        ending_mode=ending_mode,
        pov=config.pov or "第三人称有限视角",
        target_total_chars=config.target_total_chars,
        target_chars_per_chapter=config.target_chars_per_chapter,
        chapter_count=config.chapter_count,
        volume_count=config.volume_count,
        chapter_char_tolerance=config.chapter_char_tolerance,
        structure_mode=config.structure_mode,
        market_profile=config.market_profile,
        progression_mode=config.progression_mode,
        progression_flavor=config.progression_flavor,
        progression_pacing=config.progression_pacing,
        power_system_hint=config.power_system_hint,
        style_examples=style_examples,
        must_include=must_include,
        avoid=avoid,
        character_seeds=character_seeds,
    )


def _parse_csv_rows(csv_text: str) -> list[dict[str, str]]:
    stream = io.StringIO(csv_text.lstrip("\ufeff"))
    reader = csv.DictReader(stream)
    rows: list[dict[str, str]] = []
    for raw in reader:
        normalized: dict[str, str] = {}
        for key, value in raw.items():
            if key is None:
                continue
            mapped_key = _CSV_FIELD_MAP.get(str(key).strip(), str(key).strip())
            normalized[mapped_key] = str(value or "").strip()
        if normalized.get("title"):
            rows.append(normalized)
    if not rows:
        raise ValueError("CSV 中没有可用提案。请确认表头包含“书名”等字段。")
    return rows


def _proposal_from_row(batch_id: str, row_index: int, raw: dict[str, str]) -> ProposalRecord:
    proposal_id = f"{batch_id}-row-{row_index:03d}"
    return ProposalRecord(
        proposal_id=proposal_id,
        row_index=row_index,
        source_batch_id=batch_id,
        title=raw.get("title", "").strip(),
        track=raw.get("track", "").strip(),
        platform_fit=raw.get("platform_fit", "").strip(),
        reference_requirements=raw.get("reference_requirements", "").strip(),
        hook=raw.get("hook", "").strip(),
        platform_blurb=raw.get("platform_blurb", "").strip(),
        core_story=raw.get("core_story", "").strip(),
        theme=raw.get("theme", "").strip(),
        world_scene=raw.get("world_scene", "").strip(),
        world_seed=raw.get("world_seed", "").strip(),
        style_seed=raw.get("style_seed", "").strip(),
        chapter_seed=raw.get("chapter_seed", "").strip(),
        volume_seed=raw.get("volume_seed", "").strip(),
        character_seed=raw.get("character_seed", "").strip(),
        notes=raw.get("notes", "").strip(),
        status="draft",
        raw=dict(raw),
    )


def _collect_lines(*values: str) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        for chunk in str(value or "").replace(" / ", "\n").splitlines():
            text = chunk.strip(" -\t")
            if not text or text in seen:
                continue
            seen.add(text)
            result.append(text)
    return result


def _join_sections(*sections: tuple[str, str]) -> str:
    parts: list[str] = []
    for label, value in sections:
        text = str(value or "").strip()
        if not text:
            continue
        parts.append(f"{label}：{text}")
    return "\n\n".join(parts)


def _character_seed_payload(raw: str) -> tuple[str, list[CharacterSeed]]:
    seeds: list[CharacterSeed] = []
    protagonist = ""
    for line in _collect_lines(raw):
        name, notes = _split_character_line(line)
        if not name:
            continue
        role = "主角" if not seeds else ""
        seeds.append(CharacterSeed(name=name, role=role, notes=notes))
        if not protagonist:
            protagonist = f"{name}，{notes}" if notes else name
    return protagonist, seeds


def _split_character_line(line: str) -> tuple[str, str]:
    for token in ("：", ":", "—", "-", "，", ","):
        if token in line:
            left, right = line.split(token, 1)
            name = left.strip()
            notes = right.strip()
            if name:
                return name, notes
    return line.strip(), ""


def batch_to_payload(batch: BatchRecord) -> dict[str, Any]:
    payload = asdict(batch)
    payload["config"] = asdict(batch.config)
    return payload
