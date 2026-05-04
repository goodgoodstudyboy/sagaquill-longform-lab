from __future__ import annotations

import unittest

from sagaquill.retrying import is_non_retryable_error_text, is_retryable_error_text


class RetryingTests(unittest.TestCase):
    def test_clientconn_close_is_retryable(self) -> None:
        self.assertTrue(
            is_retryable_error_text("http2: client connection force closed via ClientConn.Close")
        )

    def test_unexpected_eof_is_retryable(self) -> None:
        self.assertTrue(
            is_retryable_error_text("unexpected EOF")
        )

    def test_authentication_errors_remain_non_retryable(self) -> None:
        self.assertTrue(
            is_non_retryable_error_text("403 forbidden: authentication failed for this api key")
        )
        self.assertFalse(
            is_retryable_error_text("403 forbidden: authentication failed for this api key")
        )

    def test_relay_specific_forbidden_message_is_retryable(self) -> None:
        text = "Upstream access forbidden, please contact administrator"
        self.assertTrue(is_non_retryable_error_text(text))
        self.assertTrue(is_retryable_error_text(text))


if __name__ == "__main__":
    unittest.main()
