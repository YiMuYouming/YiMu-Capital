"""test_api.py — bridge API 端点测试（需要 bridge 在 8088 端口运行）

本测试仅在真实 bridge 运行时执行。bridge 不可达时自动跳过。
HTTP 错误（尤其 500）必须让测试失败，不得转为 SkipTest。
"""
import json
import socket
import unittest
import urllib.error
import urllib.request


BASE = "http://localhost:8088"


def _get(path):
    """Fetch API endpoint.

    SkipTest: only when bridge is genuinely unreachable
    (connection refused / timeout / DNS failure).
    HTTPError (including 500) must fail the test.
    """
    try:
        with urllib.request.urlopen(BASE + path, timeout=5) as r:
            if r.status >= 400:
                # Server is reachable but returned an error — this is a test FAILURE
                raise urllib.error.HTTPError(
                    BASE + path, r.status, f"HTTP {r.status}",
                    r.headers, None,
                )
            return json.loads(r.read())
    except urllib.error.HTTPError:
        # Always propagate HTTP errors as test failures
        raise
    except (ConnectionRefusedError, TimeoutError, socket.timeout) as e:
        raise unittest.SkipTest(f"bridge not reachable at {BASE}: {e}") from e
    except urllib.error.URLError as e:
        reason = e.reason
        if isinstance(reason, (ConnectionRefusedError, TimeoutError, socket.timeout)):
            raise unittest.SkipTest(f"bridge not reachable at {BASE}: {e.reason}") from e
        # Other transport errors (DNS, etc.) — also unreachable
        raise unittest.SkipTest(f"bridge not reachable at {BASE}: {e}") from e


class TestBridgeAPI(unittest.TestCase):

    def test_api_baseline(self):
        data = _get("/api/baseline")
        self.assertIsInstance(data, dict)
        self.assertIn("meta", data)
        self.assertIn("_freshness", data)
        self.assertIn(data["_freshness"]["level"], ("live", "delayed"))

    def test_api_pnl(self):
        data = _get("/api/pnl?range=today")
        self.assertIsInstance(data, dict)
        self.assertIn("_freshness", data)

    def test_api_trades(self):
        data = _get("/api/trades")
        self.assertIsInstance(data, (dict, list))
        if isinstance(data, dict):
            self.assertIn("_freshness", data)

    def test_api_live_quotes(self):
        data = _get("/api/live/quotes")
        self.assertIsInstance(data, dict)
        self.assertIn("_freshness", data)
        self.assertIn("live_index", data)
        self.assertIn("breadth", data)

    def test_api_iwencai(self):
        data = _get("/api/live/iwencai")
        self.assertIsInstance(data, dict)
        self.assertIn("_freshness", data)

    def test_api_sectors(self):
        data = _get("/api/live/sectors")
        self.assertIsInstance(data, dict)
        self.assertIn("_freshness", data)

    def test_api_freshness_fields(self):
        for path in ["/api/baseline", "/api/live/quotes", "/api/live/iwencai"]:
            with self.subTest(path=path):
                data = _get(path)
                f = data.get("_freshness", {})
                self.assertIn("level", f, f"{path}: missing level")
                self.assertIn("type", f, f"{path}: missing type")
                self.assertIn("age_seconds", f, f"{path}: missing age_seconds")

    def test_api_baseline_has_widget_data(self):
        data = _get("/api/baseline")
        self.assertIn("market", data)
        self.assertIn("sentiment", data)
        self.assertIn("lianban_pool", data)
        self.assertIn("trend_pool", data)


class HTTPErrorNotSkippedTest(unittest.TestCase):
    """回归：HTTP 500 不得被转为 SkipTest"""

    def test_http_500_is_not_skip_test(self):
        """mock urlopen 抛 HTTPError(500)，断言一定以 HTTPError 失败，不 SkipTest"""
        import io
        from unittest.mock import patch

        fake_response = io.BytesIO(b"Internal Server Error")
        http_err = urllib.error.HTTPError(
            BASE + "/api/test", 500, "Internal Server Error",
            {}, fake_response,
        )

        try:
            with patch("urllib.request.urlopen", side_effect=http_err):
                with self.assertRaises(urllib.error.HTTPError):
                    _get("/api/test")
        finally:
            http_err.close()


if __name__ == "__main__":
    unittest.main()
