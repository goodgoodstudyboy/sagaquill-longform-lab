from __future__ import annotations

import unittest

from sagaquill.models import (
    ChapterOutlineItem,
    ChapterPlan,
    ProjectSpec,
    SceneCard,
    WorldBible,
)
from sagaquill.prompts import chapter_room_user_prompt


class PromptI18nTests(unittest.TestCase):
    def test_chapter_room_prompt_carries_non_chinese_language_guard(self) -> None:
        spec = ProjectSpec(
            title="Night Courier",
            genre="urban fantasy",
            audience="webnovel readers",
            tone="fast and concrete",
            premise="A courier delivers haunted final orders.",
            theme="survival and choice",
            hook="Every delivery changes the address.",
            setting="a modern city",
            protagonist="Mara",
            outline_hint="escalate quickly",
            world_hint="rules serve plot",
            ending_mode="series",
            pov="third person limited",
            target_total_chars=800_000,
            target_chars_per_chapter=2500,
            chapter_count=320,
            volume_count=20,
            chapters_per_volume=16,
            output_language="en",
        )
        bible = WorldBible(
            title="Night Courier",
            logline="A courier takes supernatural final deliveries.",
            setting_summary="A grounded city with haunted addresses.",
            core_conflict="Every delivery demands a cost.",
            theme_statement="Choice under pressure.",
            narrative_voice=["fast"],
            world_rules=["deliveries bind the living and dead"],
            chapter_guardrails=["keep each scene concrete"],
            ending_contract=["close the main route"],
            major_threads=["delivery route"],
            characters=[],
        )
        chapter = ChapterOutlineItem(
            index=1,
            volume_index=1,
            title="The Last Order",
            purpose="Launch the courier route.",
            conflict="The address changes after pickup.",
            beat_summary="Mara accepts an order no one else will touch.",
            ending_note="The next address appears.",
            pov="third person limited",
            closing_mode="chapter_hook",
        )
        plan = ChapterPlan(
            chapter_index=1,
            chapter_title="The Last Order",
            purpose="Launch the courier route.",
            continuity_targets=["route"],
            opening_image="A delivery bag hums on the counter.",
            closing_image="The address changes.",
            closing_mode="chapter_hook",
            scenes=[
                SceneCard(
                    scene_index=1,
                    location="delivery station",
                    goal="take the order",
                    conflict="the dispatcher refuses to explain",
                    turn="Mara accepts anyway",
                )
            ],
        )

        prompt = chapter_room_user_prompt(spec, bible, chapter, plan)

        self.assertIn("输出语言要求（English）", prompt)
        self.assertIn("不要默认回到中文网文表达", prompt)


if __name__ == "__main__":
    unittest.main()
