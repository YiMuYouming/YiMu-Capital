"""One rollback boundary for scheduled WenCai consumers.

The rollout defaults to the legacy source path. ``unified`` uses the public
``ym_stock_data.query`` contract and retains a narrow legacy guard only when
the canonical result is empty, invalid, or failed.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Callable, Mapping


MODE_ENV = "YM_DATA_API_MODE"
VALID_MODES = frozenset({"legacy", "unified"})
_pipeline_path: Path | None = None


def data_api_mode(environ: Mapping[str, str] | None = None) -> str:
    values = os.environ if environ is None else environ
    mode = str(values.get(MODE_ENV, "legacy") or "legacy").strip().lower()
    if mode not in VALID_MODES:
        raise ValueError(f"{MODE_ENV} must be legacy or unified")
    return mode


def _load_pipeline_path() -> Path:
    configured = os.environ.get("YM_DATA_PIPELINE_PATH", "")
    if configured:
        path = Path(configured)
        if path.exists():
            return path
        raise RuntimeError("configured YM_DATA_PIPELINE_PATH does not exist")
    return Path(__file__).resolve().parents[2] / "YM-data-pipeline"


def _ensure_pipeline() -> Path:
    global _pipeline_path
    if _pipeline_path is None:
        _pipeline_path = _load_pipeline_path()
        if str(_pipeline_path) not in sys.path:
            sys.path.insert(0, str(_pipeline_path))
    return _pipeline_path


def canonical_review_query(query_text: str, *, limit: int = 100) -> dict:
    _ensure_pipeline()
    from ym_stock_data import query

    return query("review_sentiment", query=query_text, limit=limit)


def legacy_review_query(query_text: str, *, limit: int = 100) -> dict:
    _ensure_pipeline()
    from ym_stock_data.sources.iwencai import query

    return query(query_text, limit=limit)


def _rows(result: object) -> list:
    if not isinstance(result, dict):
        return []
    for key in ("datas", "rows", "items"):
        value = result.get(key)
        if isinstance(value, list):
            return value
    data = result.get("data")
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("datas", "rows", "items"):
            value = data.get(key)
            if isinstance(value, list):
                return value
    return []


def _normalized_code(row: object) -> str | None:
    if not isinstance(row, Mapping):
        return None
    raw = row.get("股票代码") or row.get("code") or row.get("证券代码")
    if raw is None:
        return None
    text = str(raw).strip().split(".", 1)[0]
    digits = "".join(char for char in text if char.isdigit())
    if not digits or len(digits) > 6:
        return None
    return digits.zfill(6)


def compare_review_results(canonical_result: object, legacy_result: object) -> str:
    """Compare normalized code sets without retaining rows or query text."""

    meta = canonical_result.get("_meta") if isinstance(canonical_result, Mapping) else None
    if not isinstance(meta, Mapping) or meta.get("status") not in {"success", "degraded"}:
        return "inconclusive_empty"
    canonical_rows = _rows(canonical_result)
    legacy_rows = _rows(legacy_result)
    if not canonical_rows or not legacy_rows:
        return "inconclusive_empty"
    canonical_codes = {_normalized_code(row) for row in canonical_rows}
    legacy_codes = {_normalized_code(row) for row in legacy_rows}
    if None in canonical_codes or None in legacy_codes:
        return "shape_mismatch"
    if canonical_codes == legacy_codes:
        return "exact_code_set_match"
    return "code_set_mismatch"


def _canonical_projection(result: object) -> dict:
    if not isinstance(result, dict):
        return {
            "datas": [],
            "error": "INVALID_CANONICAL_RESULT",
            "_meta": {"status": "error", "provider_used": None, "attempts": []},
        }
    meta = result.get("_meta")
    if not isinstance(meta, dict):
        meta = {"status": "error", "provider_used": None, "attempts": []}
    projected = {"datas": _rows(result), "_meta": dict(meta)}
    if meta.get("status") == "error":
        projected["error"] = "CANONICAL_QUERY_FAILED"
    return projected


def compat_iwencai_query(
    query_text: str,
    *,
    limit: int = 100,
    mode: str | None = None,
    canonical_fn: Callable | None = None,
    legacy_fn: Callable | None = None,
) -> dict:
    """Return the legacy ``datas`` shape behind one explicit rollback switch."""

    selected_mode = data_api_mode({MODE_ENV: mode}) if mode is not None else data_api_mode()
    canonical_call = canonical_fn or canonical_review_query
    legacy_call = legacy_fn or legacy_review_query
    if selected_mode == "legacy":
        return legacy_call(query_text, limit=limit)

    try:
        canonical_result = canonical_call(query_text, limit=limit)
    except Exception:
        canonical_result = {
            "data": {"rows": []},
            "_meta": {"status": "error", "provider_used": None, "attempts": []},
        }
    projected = _canonical_projection(canonical_result)
    canonical_meta = projected["_meta"]
    canonical_rows = projected["datas"]
    if canonical_meta.get("status") in {"success", "degraded"} and canonical_rows:
        projected["_ym_data_compat"] = {
            "mode": "unified",
            "selected": "unified",
        }
        return projected

    try:
        legacy_result = legacy_call(query_text, limit=limit)
    except Exception:
        legacy_result = {"datas": []}
    legacy_rows = _rows(legacy_result)
    if legacy_rows:
        guarded = dict(legacy_result) if isinstance(legacy_result, dict) else {"datas": legacy_rows}
        guarded["datas"] = legacy_rows
        guarded["_ym_data_compat"] = {
            "mode": "unified",
            "selected": "legacy_guard",
            "canonical_meta": dict(canonical_meta),
            "legacy_source": (
                legacy_result.get("_source", "legacy")
                if isinstance(legacy_result, dict)
                else "legacy"
            ),
        }
        return guarded

    projected["_ym_data_compat"] = {
        "mode": "unified",
        "selected": "unified",
    }
    return projected
