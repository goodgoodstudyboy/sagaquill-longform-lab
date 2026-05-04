from __future__ import annotations

from pathlib import Path
from typing import Any

from .util import dump_json, dump_text, ensure_directory


class ProjectStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.data_dir = self.root / "data"
        self.plan_dir = self.root / "plans"
        self.volume_dir = self.root / "volumes"
        self.chapter_dir = self.root / "chapters"
        self.state_dir = self.root / "state"
        self.review_dir = self.root / "reviews"
        self.audit_dir = self.root / "audits"
        ensure_directory(self.data_dir)
        ensure_directory(self.plan_dir)
        ensure_directory(self.volume_dir)
        ensure_directory(self.chapter_dir)
        ensure_directory(self.state_dir)
        ensure_directory(self.review_dir)
        ensure_directory(self.audit_dir)

    def write_json(self, relative_path: str, payload: Any) -> Path:
        target = self.root / relative_path
        dump_json(target, payload)
        return target

    def write_text(self, relative_path: str, content: str) -> Path:
        target = self.root / relative_path
        dump_text(target, content)
        return target

    def chapter_path(self, chapter_index: int) -> Path:
        return self.chapter_dir / f"chapter-{chapter_index:02d}.md"

    def chapter_review_path(self, chapter_index: int) -> Path:
        return self.review_dir / f"chapter-{chapter_index:02d}.review.json"

    def chapter_plan_path(self, chapter_index: int) -> Path:
        return self.plan_dir / f"chapter-{chapter_index:02d}.plan.json"

    def volume_outline_path(self, volume_index: int) -> Path:
        return self.volume_dir / f"volume-{volume_index:02d}.outline.json"

    def continuity_path(self, chapter_index: int) -> Path:
        return self.state_dir / f"chapter-{chapter_index:02d}.continuity.json"

    def chapter_room_path(self, chapter_index: int) -> Path:
        return self.state_dir / f"chapter-{chapter_index:02d}.room.json"

    def chapter_memory_path(self, chapter_index: int) -> Path:
        return self.state_dir / f"chapter-{chapter_index:02d}.memory.json"

    def chapter_execution_path(self, chapter_index: int) -> Path:
        return self.state_dir / f"chapter-{chapter_index:02d}.execution.json"

    def logic_audit_path(self, volume_index: int) -> Path:
        return self.audit_dir / f"volume-{volume_index:02d}.logic-audit.json"

    def style_bible_path(self) -> Path:
        return self.data_dir / "style-bible.json"

    def style_bible_anchor_path(self) -> Path:
        return self.data_dir / "style-bible.anchor.json"

    def style_bible_calibration_path(self) -> Path:
        return self.data_dir / "style-bible.calibration.json"

    def style_bible_runtime_path(self) -> Path:
        return self.data_dir / "style-bible.runtime.json"

    def voice_cards_path(self) -> Path:
        return self.data_dir / "voice-cards.json"

    def power_system_path(self) -> Path:
        return self.data_dir / "power-system.json"

    def progression_ledger_path(self) -> Path:
        return self.data_dir / "progression-ledger.json"

    def voice_cards_runtime_path(self) -> Path:
        return self.data_dir / "voice-cards.runtime.json"

    def style_bible_meta_path(self) -> Path:
        return self.data_dir / "style-bible.meta.json"

    def voice_cards_meta_path(self) -> Path:
        return self.data_dir / "voice-cards.meta.json"

    def promise_ledger_path(self) -> Path:
        return self.data_dir / "promise-ledger.json"

    def causality_graph_path(self) -> Path:
        return self.data_dir / "causality-graph.json"

    def continuity_runtime_path(self) -> Path:
        return self.data_dir / "continuity.runtime.json"

    def story_room_alignment_path(self) -> Path:
        return self.data_dir / "story-room-alignment.json"

    def committed_progress_path(self) -> Path:
        return self.data_dir / "committed-progress.json"

    def orphaned_chapters_dir(self) -> Path:
        return self.state_dir / "orphaned-chapters"

    def delivery_cleanup_report_path(self) -> Path:
        return self.data_dir / "delivery-cleanup.json"


class BatchStore:
    def __init__(self, root: str | Path, batch_id: str) -> None:
        self.root = Path(root) / ".sagaquill" / "batches" / batch_id
        self.batch_id = batch_id
        ensure_directory(self.root)

    @property
    def batch_path(self) -> Path:
        return self.root / "batch.json"

    @property
    def proposals_path(self) -> Path:
        return self.root / "proposals.json"

    @property
    def items_path(self) -> Path:
        return self.root / "items.json"

    @property
    def export_path(self) -> Path:
        return self.root / "export.json"

    def write_batch(self, payload: Any) -> Path:
        return self.write_json(self.batch_path, payload)

    def write_proposals(self, payload: Any) -> Path:
        return self.write_json(self.proposals_path, payload)

    def write_items(self, payload: Any) -> Path:
        return self.write_json(self.items_path, payload)

    def write_export(self, payload: Any) -> Path:
        return self.write_json(self.export_path, payload)

    def write_json(self, path: str | Path, payload: Any) -> Path:
        target = Path(path)
        dump_json(target, payload)
        return target
