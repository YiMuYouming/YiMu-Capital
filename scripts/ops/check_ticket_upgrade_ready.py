#!/usr/bin/env python3
"""Read-only readiness checks for the trade ticket upgrade on a dashboard URL."""

import argparse
import json
import sys
import urllib.error
import urllib.request


def _fetch_text(url, opener=urllib.request.urlopen, timeout=5):
    req = urllib.request.Request(url, method="GET")
    try:
        with opener(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return {
                "status": getattr(resp, "status", 200),
                "content_type": resp.headers.get("Content-Type", ""),
                "body": body,
            }
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return {
            "status": exc.code,
            "content_type": exc.headers.get("Content-Type", ""),
            "body": body,
        }
    except Exception as exc:
        return {
            "status": 0,
            "content_type": "",
            "body": "",
            "error": str(exc),
        }


def _item(name, ok, detail):
    return {"name": name, "ok": bool(ok), "detail": detail}


def check(base_url, opener=urllib.request.urlopen, timeout=5):
    base = str(base_url or "").rstrip("/")
    checks = []

    index = _fetch_text(base + "/", opener=opener, timeout=timeout)
    index_body = index.get("body", "")
    index_ok = index.get("status") == 200
    checks.append(_item("index_http_200", index_ok, f"status={index.get('status')}"))
    checks.append(_item(
        "index_w24_resource",
        index_ok and "widgets/trade-tickets.js" in index_body and "W24" in index_body,
        "requires W24 shortcut and widgets/trade-tickets.js script",
    ))

    widget = _fetch_text(base + "/widgets/trade-tickets.js", opener=opener, timeout=timeout)
    widget_body = widget.get("body", "")
    checks.append(_item("trade_tickets_widget_http_200", widget.get("status") == 200, f"status={widget.get('status')}"))
    checks.append(_item(
        "trade_tickets_widget_flow",
        all(token in widget_body for token in [
            "_prepareTicket",
            "data-tt-prepare",
            "/api/trade/fills/confirm",
            "确认成交",
        ]),
        "requires prepare/preview/confirm frontend flow",
    ))

    tickets = _fetch_text(base + "/api/trade/tickets", opener=opener, timeout=timeout)
    tickets_body = tickets.get("body", "")
    api_ok = False
    api_detail = f"status={tickets.get('status')}"
    if tickets.get("status") == 200:
        try:
            parsed = json.loads(tickets_body)
            api_ok = isinstance(parsed.get("tickets"), list)
            api_detail = "tickets list present" if api_ok else "missing tickets list"
        except Exception as exc:
            api_detail = f"invalid json: {exc}"
    checks.append(_item("trade_tickets_api_json", api_ok, api_detail))

    return {
        "ok": all(item["ok"] for item in checks),
        "base_url": base,
        "checks": checks,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read-only trade ticket upgrade readiness check")
    parser.add_argument("--base-url", default="http://127.0.0.1:8088")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--timeout", type=int, default=5)
    args = parser.parse_args(argv)

    result = check(args.base_url, timeout=args.timeout)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"Trade ticket upgrade readiness: {'OK' if result['ok'] else 'FAILED'}")
        print(f"Base URL: {result['base_url']}")
        for item in result["checks"]:
            mark = "OK" if item["ok"] else "FAIL"
            print(f"  [{mark}] {item['name']}: {item['detail']}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
