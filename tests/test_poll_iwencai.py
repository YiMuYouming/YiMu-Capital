from __future__ import annotations

import inspect
import io
import unittest
from contextlib import redirect_stderr
from unittest.mock import patch

from scripts import poll_iwencai


class PollIwencaiTests(unittest.TestCase):
    def test_non_writing_helper_uses_canonical_query_and_logs_only_metadata(self):
        result = {
            "data": {"rows": [{"股票代码": "000001", "股票简称": "样本"}]},
            "_meta": {
                "status": "degraded",
                "provider_used": "pywencai",
                "attempts": [
                    {
                        "provider": "iwencai_openapi",
                        "status": "auth_error",
                        "error_code": "HTTP_401",
                    },
                    {
                        "provider": "pywencai",
                        "status": "success",
                        "error_code": None,
                    },
                ],
            },
        }
        stderr = io.StringIO()

        with patch.object(poll_iwencai, "_canonical_query", return_value=result) as query_call, redirect_stderr(stderr):
            rows = poll_iwencai.run_iwencai("脱敏样例", extra_args={"limit": 7})

        self.assertEqual(result["data"]["rows"], rows)
        query_call.assert_called_once_with("脱敏样例", limit=7)
        log = stderr.getvalue()
        self.assertIn("status=degraded", log)
        self.assertIn("provider=pywencai", log)
        self.assertIn("HTTP_401", log)
        self.assertNotIn("000001", log)
        self.assertNotIn("样本", log)

    def test_error_result_returns_none_without_printing_payload(self):
        result = {
            "data": {"rows": []},
            "_meta": {
                "status": "error",
                "provider_used": None,
                "attempts": [
                    {
                        "provider": "iwencai_openapi",
                        "status": "auth_error",
                        "error_code": "HTTP_401",
                    }
                ],
            },
            "secret_payload": "DO_NOT_PRINT",
        }
        stderr = io.StringIO()

        with patch.object(poll_iwencai, "_canonical_query", return_value=result), redirect_stderr(stderr):
            rows = poll_iwencai.run_iwencai("脱敏样例")

        self.assertIsNone(rows)
        self.assertIn("status=error", stderr.getvalue())
        self.assertNotIn("DO_NOT_PRINT", stderr.getvalue())

    def test_helper_has_no_direct_source_or_v2_import(self):
        source = inspect.getsource(poll_iwencai)
        self.assertNotIn("ym_stock_data.sources", source)
        self.assertNotIn("ym_stock_data.v2", source)
        self.assertIn("from ym_stock_data import query", source)


if __name__ == "__main__":
    unittest.main()
