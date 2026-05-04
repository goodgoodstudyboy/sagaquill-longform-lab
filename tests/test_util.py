from __future__ import annotations

import unittest

from sagaquill.util import extract_json_object


class UtilTests(unittest.TestCase):
    def test_extract_json_object_accepts_trailing_text(self) -> None:
        payload = extract_json_object('{"ok": true, "count": 2}\n说明：后面这段不是 JSON。')

        self.assertEqual(payload, {"ok": True, "count": 2})
