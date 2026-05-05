from __future__ import annotations

import unittest

from sagaquill.projectio import normalized_output_language, panel_template_payload, project_input_from_dict, resolved_market_profile
from sagaquill.models import BatchConfig, ProjectInput


class ProjectIOTests(unittest.TestCase):
    def test_resolved_market_profile_prefers_explicit_value(self) -> None:
        profile = resolved_market_profile(
            "qidian_longform",
            {
                "audience": "番茄大众男频",
                "tone": "小白快节奏",
            },
        )
        self.assertEqual(profile, "qidian_longform")

    def test_resolved_market_profile_infers_legacy_tomato_from_hints(self) -> None:
        profile = resolved_market_profile(
            None,
            {
                "audience": "番茄大众男频",
                "tone": "小白快节奏",
                "style_examples": ["黄金三章", "高频回报"],
                "avoid": ["慢热"],
            },
        )
        self.assertEqual(profile, "tomato_mass")

    def test_project_input_from_dict_infers_tomato_profile_for_legacy_payload(self) -> None:
        payload = {
            "title": "老番茄书",
            "genre": "都市异能",
            "audience": "番茄大众男频",
            "tone": "小白快节奏",
            "premise": "主角开局爆炸式入局。",
            "style_examples": ["番茄爆款", "追读优先"],
            "must_include": ["黄金三章"],
            "avoid": ["慢热"],
        }

        project_input = project_input_from_dict(payload)

        self.assertEqual(project_input.market_profile, "tomato_mass")

    def test_project_input_from_dict_parses_progression_fields(self) -> None:
        payload = {
            "title": "凡人练气簿",
            "premise": "少年从练气一路往上修。",
            "progression_mode": "hard_realm_progression",
            "progression_flavor": "xianxia_steady",
            "progression_pacing": "slow",
            "power_system_hint": "练气、筑基、结丹；突破需要丹药、洞府和寿元代价。",
        }

        project_input = project_input_from_dict(payload)

        self.assertEqual(project_input.progression_mode, "hard_realm_progression")
        self.assertEqual(project_input.progression_flavor, "xianxia_steady")
        self.assertEqual(project_input.progression_pacing, "slow")
        self.assertEqual(project_input.power_system_hint, "练气、筑基、结丹；突破需要丹药、洞府和寿元代价。")

    def test_project_input_from_dict_parses_output_language_alias(self) -> None:
        project_input = project_input_from_dict(
            {
                "title": "Night Courier",
                "language": "English",
                "premise": "A courier delivers to haunted addresses.",
            }
        )

        self.assertEqual(project_input.output_language, "en")
        self.assertEqual(project_input.pov, "third person limited")
        self.assertEqual(normalized_output_language("日本語"), "ja")
        self.assertEqual(normalized_output_language("zh_Hant"), "zh-Hant")
        self.assertEqual(normalized_output_language("繁体中文"), "zh-Hant")

    def test_project_input_from_dict_localizes_default_chinese_pov_for_non_chinese(self) -> None:
        project_input = project_input_from_dict(
            {
                "title": "Night Courier",
                "output_language": "en",
                "pov": "第三人称有限视角",
            }
        )

        self.assertEqual(project_input.pov, "third person limited")

    def test_language_fields_do_not_break_legacy_positional_dataclasses(self) -> None:
        project_input = ProjectInput("旧接口书名", "都市悬疑")
        batch_config = BatchConfig(800000, 2500)

        self.assertEqual(project_input.genre, "都市悬疑")
        self.assertEqual(project_input.output_language, "zh-Hans")
        self.assertEqual(batch_config.target_total_chars, 800000)
        self.assertEqual(batch_config.target_chars_per_chapter, 2500)
        self.assertEqual(batch_config.output_language, "zh-Hans")

    def test_panel_template_payload_exposes_progression_options(self) -> None:
        payload = panel_template_payload()

        self.assertIn("progression_mode_options", payload)
        self.assertIn("output_language_options", payload)
        self.assertIn("progression_flavor_options", payload)
        self.assertIn("progression_pacing_options", payload)
        self.assertTrue(any(option["id"] == "hard_realm_progression" for option in payload["progression_mode_options"]))
        self.assertTrue(any(option["id"] == "en" for option in payload["output_language_options"]))
        self.assertTrue(any(option["id"] == "xianxia_steady" for option in payload["progression_flavor_options"]))
        self.assertTrue(any(option["id"] == "slow" for option in payload["progression_pacing_options"]))


if __name__ == "__main__":
    unittest.main()
