from __future__ import annotations

import os
import inspect
import unittest
from unittest.mock import Mock, patch

from scripts import snapshot_auction
from scripts.collectors import iwencai_poll
from scripts.ym_data_query import compat_iwencai_query, data_api_mode


class YmDataQueryCompatibilityTests(unittest.TestCase):
    def test_scheduled_consumers_use_one_compatibility_boundary(self):
        for module in (iwencai_poll, snapshot_auction):
            with self.subTest(module=module.__name__):
                source = inspect.getsource(module)
                self.assertNotIn("ym_stock_data.sources", source)
                self.assertNotIn("ym_stock_data.v2", source)
                self.assertIn("compat_iwencai_query", source)
                self.assertTrue(callable(getattr(module, "_load_pipeline_path", None)))

    def test_scheduled_query_helpers_delegate_to_compatibility_boundary(self):
        expected = {"datas": [{"股票代码": "000001"}]}
        for module in (iwencai_poll, snapshot_auction):
            with self.subTest(module=module.__name__), patch.object(
                module, "compat_iwencai_query", return_value=expected, create=True
            ) as compat:
                self.assertEqual(
                    expected,
                    module._iwencai_query("脱敏样例", limit=3),
                )
                compat.assert_called_once_with("脱敏样例", limit=3)

    def test_default_mode_is_legacy_and_does_not_call_canonical(self):
        legacy = Mock(return_value={"datas": [{"股票代码": "000001"}], "_source": "iwencai"})
        canonical = Mock(side_effect=AssertionError("canonical must not run by default"))

        with patch.dict(os.environ, {}, clear=True):
            result = compat_iwencai_query(
                "脱敏样例",
                limit=3,
                canonical_fn=canonical,
                legacy_fn=legacy,
            )

        self.assertEqual("legacy", data_api_mode({}))
        self.assertEqual([{"股票代码": "000001"}], result["datas"])
        legacy.assert_called_once_with("脱敏样例", limit=3)
        canonical.assert_not_called()

    def test_unified_success_preserves_rows_provider_and_attempts(self):
        canonical_result = {
            "data": {"rows": [{"股票代码": "000001"}]},
            "_meta": {
                "status": "success",
                "provider_used": "pywencai",
                "attempts": [
                    {"provider": "iwencai_openapi", "status": "auth_error", "error_code": "HTTP_401"},
                    {"provider": "pywencai", "status": "success", "error_code": None},
                ],
            },
        }
        legacy = Mock(side_effect=AssertionError("legacy guard must not run on valid success"))

        result = compat_iwencai_query(
            "脱敏样例",
            limit=3,
            mode="unified",
            canonical_fn=Mock(return_value=canonical_result),
            legacy_fn=legacy,
        )

        self.assertEqual(canonical_result["data"]["rows"], result["datas"])
        self.assertEqual("pywencai", result["_meta"]["provider_used"])
        self.assertEqual(2, len(result["_meta"]["attempts"]))
        self.assertEqual("unified", result["_ym_data_compat"]["selected"])
        legacy.assert_not_called()

    def test_unified_empty_or_error_cannot_overwrite_valid_legacy_rows(self):
        legacy_rows = [{"股票代码": "000001", "股票简称": "保留样本"}]
        legacy = Mock(return_value={"datas": legacy_rows, "_source": "legacy_iwencai"})
        cases = (
            {
                "data": {"rows": []},
                "_meta": {"status": "empty", "provider_used": "pywencai", "attempts": []},
            },
            {
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
            },
        )
        for canonical_result in cases:
            with self.subTest(status=canonical_result["_meta"]["status"]):
                result = compat_iwencai_query(
                    "脱敏样例",
                    limit=3,
                    mode="unified",
                    canonical_fn=Mock(return_value=canonical_result),
                    legacy_fn=legacy,
                )
                self.assertEqual(legacy_rows, result["datas"])
                compat = result["_ym_data_compat"]
                self.assertEqual("legacy_guard", compat["selected"])
                self.assertEqual(canonical_result["_meta"], compat["canonical_meta"])
                self.assertEqual("legacy_iwencai", compat["legacy_source"])

    def test_invalid_mode_fails_closed_before_any_provider_call(self):
        canonical = Mock()
        legacy = Mock()
        with self.assertRaisesRegex(ValueError, "YM_DATA_API_MODE"):
            compat_iwencai_query(
                "脱敏样例",
                mode="future",
                canonical_fn=canonical,
                legacy_fn=legacy,
            )
        canonical.assert_not_called()
        legacy.assert_not_called()


if __name__ == "__main__":
    unittest.main()
