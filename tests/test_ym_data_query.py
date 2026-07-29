from __future__ import annotations

import os
import inspect
import unittest
from unittest.mock import Mock, patch

from scripts import snapshot_auction
from scripts.collectors import iwencai_poll
from scripts import ym_data_query
from scripts.ym_data_query import compat_iwencai_query, data_api_mode


class YmDataQueryCompatibilityTests(unittest.TestCase):
    def compare(self, canonical_result, legacy_result):
        self.assertTrue(
            hasattr(ym_data_query, "compare_review_results"),
            "compare_review_results must own the pure comparison contract",
        )
        return ym_data_query.compare_review_results(canonical_result, legacy_result)

    def test_compare_review_results_matches_wrapped_code_sets_without_order(self):
        canonical = {
            "data": {
                "rows": [
                    {"股票代码": "000001.SZ"},
                    {"证券代码": "600519.SH"},
                ]
            },
            "_meta": {"status": "degraded"},
        }
        legacy = {
            "datas": [
                {"code": "600519"},
                {"code": "1"},
            ]
        }

        result = self.compare(canonical, legacy)

        self.assertEqual("exact_code_set_match", result)
        self.assertNotIn("000001", result)
        self.assertNotIn("query", result.lower())

    def test_compare_review_results_rejects_canonical_error_and_empty_sides(self):
        valid_rows = [{"股票代码": "000001"}]
        cases = (
            ({"data": {"rows": valid_rows}, "_meta": {"status": "error"}}, {"datas": valid_rows}),
            ({"data": {"rows": []}, "_meta": {"status": "success"}}, {"datas": valid_rows}),
            ({"data": {"rows": valid_rows}, "_meta": {"status": "success"}}, {"datas": []}),
        )
        for canonical, legacy in cases:
            with self.subTest(canonical=canonical, legacy=legacy):
                self.assertEqual("inconclusive_empty", self.compare(canonical, legacy))

    def test_compare_review_results_rejects_non_mapping_or_missing_codes(self):
        cases = (
            ([{"股票代码": "000001"}, "not-a-row"], [{"股票代码": "000001"}]),
            ([{"股票简称": "样本"}], [{"股票代码": "000001"}]),
            ([{"股票代码": "000001"}], [{"code": "not-a-code"}]),
        )
        for canonical_rows, legacy_rows in cases:
            canonical = {"data": {"rows": canonical_rows}, "_meta": {"status": "success"}}
            legacy = {"datas": legacy_rows}
            with self.subTest(canonical_rows=canonical_rows, legacy_rows=legacy_rows):
                self.assertEqual("shape_mismatch", self.compare(canonical, legacy))

    def test_compare_review_results_reports_different_valid_code_sets(self):
        canonical = {
            "data": {"rows": [{"股票代码": "000001"}]},
            "_meta": {"status": "success"},
        }
        legacy = {"datas": [{"股票代码": "600519"}]}

        self.assertEqual("code_set_mismatch", self.compare(canonical, legacy))

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
