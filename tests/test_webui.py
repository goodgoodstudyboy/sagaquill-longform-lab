from __future__ import annotations

import unittest

from sagaquill.webui import panel_html


class WebUITests(unittest.TestCase):
    def test_provider_panel_exposes_review_model_field(self) -> None:
        html = panel_html()
        self.assertIn('input id="provider_review_model"', html)
        self.assertIn('document.querySelector("#provider_review_model")', html)

    def test_market_profile_selects_are_template_driven(self) -> None:
        html = panel_html()
        self.assertIn('<select id="market_profile" name="market_profile"></select>', html)
        self.assertIn('<select id="batch_market_profile"></select>', html)
        self.assertIn("renderMarketProfileOptions(template.market_profile_options || []);", html)

    def test_progression_controls_are_template_driven(self) -> None:
        html = panel_html()
        self.assertIn('<select id="progression_mode" name="progression_mode"></select>', html)
        self.assertIn('<select id="progression_flavor" name="progression_flavor"></select>', html)
        self.assertIn('<select id="progression_pacing" name="progression_pacing"></select>', html)
        self.assertIn('<select id="batch_progression_mode"></select>', html)
        self.assertIn('<select id="batch_progression_flavor"></select>', html)
        self.assertIn('<select id="batch_progression_pacing"></select>', html)
        self.assertIn('textarea id="power_system_hint"', html)
        self.assertIn('textarea id="batch_power_system_hint"', html)
        self.assertIn("renderProgressionModeOptions(template.progression_mode_options || []);", html)
        self.assertIn("renderProgressionFlavorOptions(template.progression_flavor_options || []);", html)
        self.assertIn("renderProgressionPacingOptions(template.progression_pacing_options || []);", html)


if __name__ == "__main__":
    unittest.main()
