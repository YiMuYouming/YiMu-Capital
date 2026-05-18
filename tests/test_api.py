"""test_api.py — bridge API 端点测试（需要 bridge 在 8088 端口运行）"""
import json, urllib.request, pytest

BASE = "http://localhost:8088"


def _get(path):
    try:
        with urllib.request.urlopen(BASE + path, timeout=10) as r:
            return json.loads(r.read())
    except Exception as e:
        pytest.skip(f"bridge not reachable: {e}")


def test_api_baseline():
    data = _get("/api/baseline")
    assert isinstance(data, dict)
    assert "meta" in data
    assert "_freshness" in data
    assert data["_freshness"]["level"] in ("live", "delayed")


def test_api_pnl():
    data = _get("/api/pnl?range=today")
    assert isinstance(data, dict)
    assert "_freshness" in data


def test_api_trades():
    data = _get("/api/trades")
    assert isinstance(data, (dict, list))
    # trades can be empty list
    if isinstance(data, dict):
        assert "_freshness" in data


def test_api_live_quotes():
    data = _get("/api/live/quotes")
    assert isinstance(data, dict)
    assert "_freshness" in data
    assert "live_index" in data
    assert "breadth" in data


def test_api_iwencai():
    data = _get("/api/live/iwencai")
    assert isinstance(data, dict)
    assert "_freshness" in data


def test_api_sectors():
    data = _get("/api/live/sectors")
    assert isinstance(data, dict)
    assert "_freshness" in data


def test_api_freshness_fields():
    for path in ["/api/baseline", "/api/live/quotes", "/api/live/iwencai"]:
        data = _get(path)
        f = data.get("_freshness", {})
        assert "level" in f, f"{path}: missing level"
        assert "type" in f, f"{path}: missing type"
        assert "age_seconds" in f, f"{path}: missing age_seconds"


def test_api_baseline_has_widget_data():
    data = _get("/api/baseline")
    assert "market" in data
    assert "sentiment" in data
    assert "lianban_pool" in data
    assert "trend_pool" in data
