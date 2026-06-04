"""test_sync_guard.py — event_id isolation + positions pollution guard (W22-SYNC-R4)"""
import io, json, tempfile, threading, unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
import scripts.db as db
import scripts.bridge as bridge


def _setup(test):
    test.tmp = tempfile.TemporaryDirectory()
    test.orig_path = db.DB_PATH; test.orig_local = db._local
    test.orig_inited = bridge._db_inited; test.orig_cache = dict(bridge.CACHE)
    test.orig_data = bridge.DATA_FILE
    db.DB_PATH = Path(test.tmp.name) / "test.db"; db._local = threading.local()
    bridge._db_inited = False
    bridge.DATA_FILE = Path(test.tmp.name) / "d.json"
    bridge.DATA_FILE.write_text(json.dumps({"meta": {"date": "2026-05-27"}, "positions": [], "pnl": {}}))
    db.init_db()


def _teardown(test):
    db.close_conn()
    db.DB_PATH = test.orig_path; db._local = test.orig_local
    bridge._db_inited = test.orig_inited; bridge.DATA_FILE = test.orig_data
    bridge.CACHE.clear(); bridge.CACHE.update(test.orig_cache)
    test.tmp.cleanup()


def _handler(path, payload):
    h = object.__new__(bridge.BridgeHandler)
    h.command = 'POST'; h.path = path
    h.requestline = f'POST {path} HTTP/1.1'
    h.request_version = 'HTTP/1.1'
    h.request = mock.MagicMock(); h.request.version = 'HTTP/1.1'
    h.client_address = ('127.0.0.1', 12345); h.server = mock.MagicMock()
    body = json.dumps(payload).encode()
    h.rfile = io.BytesIO(body); h.headers = mock.MagicMock()
    h.headers.get = lambda k, d=None: str(len(body))
    h.log_message = mock.MagicMock()
    h._resp_status = None; h._resp_body = b''
    def _sr(c, p=None): h._resp_status = c
    def _sh(k, v): pass
    def _eh(): pass
    def _ww(s, d): h._resp_body += d
    h.send_response = _sr; h.send_header = _sh; h.end_headers = _eh
    h.wfile = type('WFile', (), {'write': _ww})()
    return h


def _manual_backfill_entry(entry):
    entry = dict(entry)
    entry.setdefault('input_source', 'manual_backfill')
    entry.setdefault('confirmed_by', 'yimu')
    entry.setdefault('audit_note', 'test manual backfill')
    entry.setdefault('原因', 'test manual backfill')
    return entry


class EventIdIsolationTest(unittest.TestCase):
    def setUp(self): _setup(self); bridge.CACHE['live_quotes'] = {}
    def tearDown(self): _teardown(self)

    def test_two_different_event_ids_same_fields_both_inserted(self):
        for evt in ['evt-a1', 'evt-a2']:
            h = _handler('/api/sync', {'entry': _manual_backfill_entry({
                '时间': '10:00', '动作': '买入', '代码': '000001', '标的': 'T',
                '价格': 10, '数量': 100, 'event_id': evt
            })})
            h.do_POST()
            r = json.loads(h._resp_body)
            self.assertEqual(r['status'], 'inserted', f'{evt} should be inserted')
        trades = db._exec("SELECT * FROM trade_records")
        self.assertEqual(len(trades), 2)

    def test_same_event_id_replay_idempotent(self):
        h1 = _handler('/api/sync', {'entry': _manual_backfill_entry({
            '时间': '10:00', '动作': '买入', '代码': '000001', '标的': 'T',
            '价格': 10, '数量': 100, 'event_id': 'evt-r1'
        })})
        h1.do_POST()
        r1 = json.loads(h1._resp_body)
        tid = r1['trade_id']
        h2 = _handler('/api/sync', {'entry': _manual_backfill_entry({
            '时间': '10:00', '动作': '买入', '代码': '000001', '标的': 'T',
            '价格': 10, '数量': 100, 'event_id': 'evt-r1'
        })})
        h2.do_POST()
        r2 = json.loads(h2._resp_body)
        self.assertEqual(r2['status'], 'idempotent')
        self.assertEqual(r2['trade_id'], tid)
        self.assertEqual(len(db._exec("SELECT * FROM trade_records")), 1)

    def test_replay_with_positions_blocked(self):
        """同 event_id 重放夹带 positions → 拒绝"""
        h1 = _handler('/api/sync', {'entry': _manual_backfill_entry({
            '时间': '10:00', '动作': '买入', '代码': '000001', '标的': 'T',
            '价格': 10, '数量': 100, 'event_id': 'evt-r2'
        })})
        h1.do_POST()
        h2 = _handler('/api/sync', {
            'entry': _manual_backfill_entry({'时间': '10:00', '动作': '买入', '代码': '000001', '标的': 'T',
                       '价格': 10, '数量': 100, 'event_id': 'evt-r2'}),
            'positions': [{'标的': 'HAX', '代码': '999'}]
        })
        h2.do_POST()
        self.assertEqual(h2._resp_status, 400)
        # DATA_FILE unchanged
        data = json.loads(bridge.DATA_FILE.read_text())
        self.assertEqual(data.get('positions'), [])

    def test_non_event_id_conflict_not_idempotent(self):
        """无 event_id 的重复提交返回 duplicate（非 idempotent）"""
        h1 = _handler('/api/sync', {'entry': _manual_backfill_entry({
            '时间': '10:00', '动作': '买入', '代码': '000001', '标的': 'T',
            '价格': 10, '数量': 100
        })})
        h1.do_POST()
        h2 = _handler('/api/sync', {'entry': _manual_backfill_entry({
            '时间': '10:00', '动作': '买入', '代码': '000001', '标的': 'T',
            '价格': 10, '数量': 100
        })})
        h2.do_POST()
        r2 = json.loads(h2._resp_body)
        self.assertEqual(r2['status'], 'duplicate')


class W15PayloadTest(unittest.TestCase):
    def test_w15_payload_has_entry_no_positions(self):
        src = (ROOT / "widgets" / "positions.js").read_text()
        self.assertIn('{ entry: entry }', src)
        self.assertNotIn("'positions': pos", src)
        self.assertIn('event_id', src)


class PositionsOnlyGuardTest(unittest.TestCase):
    """Fix 5: positions-only 409 必须在任何 CACHE/data 变更之前发生"""

    def setUp(self): _setup(self); bridge.CACHE['live_quotes'] = {}
    def tearDown(self): _teardown(self)

    def test_positions_only_409_before_cache_mutation(self):
        """positions-only 请求返回 409 且不改变 CACHE 和 DATA_FILE"""
        orig_data = bridge.DATA_FILE.read_text()
        bridge.CACHE['_stock_codes'] = ['000001']
        orig_codes = list(bridge.CACHE.get('_stock_codes', []))
        h = _handler('/api/sync', {
            'positions': [{'标的': 'HAX', '代码': '999999', '数量': 100}]
        })
        h.do_POST()
        self.assertEqual(h._resp_status, 409)
        # CACHE 不变
        self.assertEqual(bridge.CACHE.get('_stock_codes'), orig_codes,
                         "CACHE['_stock_codes'] 在 409 后不应被修改")
        # DATA_FILE 不变
        self.assertEqual(bridge.DATA_FILE.read_text(), orig_data,
                         "DATA_FILE 在 409 后不应被修改")

    def test_entry_with_positions_still_400(self):
        """entry + positions 仍然返回 400（不变）"""
        h = _handler('/api/sync', {
            'entry': {'时间': '10:00', '动作': '买入', '代码': '000001', '标的': 'T',
                       '价格': 10, '数量': 100, 'event_id': 'evt-pos'},
            'positions': [{'标的': 'HAX', '代码': '999'}]
        })
        h.do_POST()
        self.assertEqual(h._resp_status, 400)


class TradeValidationTests(unittest.TestCase):
    """YM-W15-01: 成交写入安全门禁 — 输入校验 400"""

    def setUp(self): _setup(self); bridge.CACHE['live_quotes'] = {}
    def tearDown(self): _teardown(self)

    def _valid_entry(self, **overrides):
        e = _manual_backfill_entry({'时间': '10:00', '动作': '买入', '代码': '000001', '标的': 'TEST',
             '价格': 10, '数量': 100, 'event_id': 'evt-val'})
        e.update(overrides)
        return e

    def _post(self, entry):
        h = _handler('/api/sync', {'entry': entry})
        h.do_POST()
        return h._resp_status, json.loads(h._resp_body) if h._resp_body else {}

    def test_reject_empty_code(self):
        status, body = self._post(self._valid_entry(代码=''))
        self.assertEqual(status, 400, f"空代码应400: {body}")
        self.assertIn('代码', body.get('error', ''))

    def test_reject_empty_name(self):
        status, body = self._post(self._valid_entry(标的=''))
        self.assertEqual(status, 400, f"空名称应400: {body}")

    def test_reject_price_zero_or_negative(self):
        for p in [0, -1]:
            status, body = self._post(self._valid_entry(价格=p))
            self.assertEqual(status, 400, f"价格{p}应400: {body}")

    def test_reject_qty_zero_or_negative(self):
        for q in [0, -5]:
            status, body = self._post(self._valid_entry(数量=q))
            self.assertEqual(status, 400, f"数量{q}应400: {body}")

    def test_reject_invalid_action(self):
        for act in ['', '未知', 'random', 'W3买入']:
            status, body = self._post(self._valid_entry(动作=act))
            self.assertEqual(status, 400, f"动作'{act}'应400: {body}")

    def test_reject_invalid_time_format(self):
        for t in ['bad', '25:00', '9:00', '10:99', '00:01:99', '']:
            status, body = self._post(self._valid_entry(时间=t))
            self.assertEqual(status, 400, f"时间'{t}'应400: {body}")

    def test_reject_price_nan_infinity(self):
        import math
        for p in [float('nan'), float('inf'), float('-inf')]:
            status, body = self._post(self._valid_entry(价格=p))
            self.assertEqual(status, 400, f"价格{p}应400: {body}")

    def test_reject_qty_float_or_bool(self):
        for q in [1.5, True, False, "1.5", 0.5]:
            status, body = self._post(self._valid_entry(数量=q))
            self.assertEqual(status, 400, f"数量{q!r}应400: {body}")

    def test_valid_entry_inserts(self):
        """合法 entry 正常插入，不会误拦截"""
        status, body = self._post(self._valid_entry())
        self.assertEqual(status, 200)
        self.assertEqual(body.get('status'), 'inserted')
        self.assertEqual(len(db._exec("SELECT * FROM trade_records")), 1)

    def test_invalid_entry_zero_trades_in_db(self):
        """非法 entry 返回 400 后临时库零新增"""
        import math
        for bad in [
            {'代码': ''}, {'标的': ''}, {'价格': 0}, {'数量': 0}, {'动作': 'noop'},
            {'时间': 'bad'}, {'价格': -1}, {'数量': -1},
            {'数量': 1.5}, {'价格': float('nan')}, {'时间': '00:01:99'},
        ]:
            self._post(self._valid_entry(**bad))
        self.assertEqual(len(db._exec("SELECT * FROM trade_records")), 0,
                         "所有非法提交均不得插入数据库")

    def test_entry_forged_context_ignored(self):
        """客户端夹带 rule_state/market_snapshot → handler 忽略，不存储为 trusted"""
        entry = self._valid_entry()
        entry['rule_state'] = {'version': 'forged'}
        entry['market_snapshot'] = {'forged': 'data'}
        status, body = self._post(entry)
        self.assertEqual(status, 200, f"夹带上下文的合法 entry 仍应插入: {body}")
        rows = db._exec("SELECT rule_state_json, market_snapshot_json FROM trade_records")
        if rows[0]['rule_state_json']:
            self.assertNotIn('forged', rows[0]['rule_state_json'], "handler 不得存储客户端夹带的 rule_state")
        if rows[0]['market_snapshot_json']:
            self.assertNotIn('forged', rows[0]['market_snapshot_json'], "handler 不得存储客户端夹带的 market_snapshot")


class SyncContextHandlerTest(unittest.TestCase):
    """v3 Phase 2: /api/sync 服务端绑定成交上下文"""

    def setUp(self):
        _setup(self)
        bridge.CACHE['live_quotes'] = {}
        # Mock _build_trade_context to return known contexts
        self._orig_build_ctx = bridge._build_trade_context

    def tearDown(self):
        bridge._build_trade_context = self._orig_build_ctx
        _teardown(self)

    def _post(self, entry):
        h = _handler('/api/sync', {'entry': entry})
        h.do_POST()
        return h._resp_status, json.loads(h._resp_body) if h._resp_body else {}

    def test_trusted_context_stored_by_handler(self):
        """当日健康在线成交 → 服务端绑定 rule_state + context_status=trusted"""
        bridge._build_trade_context = lambda: {
            'rule_state': {'version': 'g1a-v1', 'tradable': True, 'blocks': [], 'warnings': [],
                           'windows': {'w1': {}, 'w2': {}}},
            'market_snapshot': {'iwencai': {'情绪值': 65}, 'live_index': {'上证指数涨幅': '-0.22'}},
            'context_captured_at': '2026-05-27T10:00:05',
            'context_status': 'trusted',
            'context_unavailable_reason': None,
        }
        entry = _manual_backfill_entry({'时间': '10:00', '动作': '买入', '代码': '000001', '标的': 'TEST',
                 '价格': 10, '数量': 100, 'event_id': 'evt-trust'})
        status, body = self._post(entry)
        self.assertEqual(status, 200, f"应插入成功: {body}")
        rows = db._exec("SELECT rule_state_json, context_status, context_captured_at FROM trade_records")
        self.assertIsNotNone(rows[0]['rule_state_json'], "应有 rule_state")
        self.assertEqual(rows[0]['context_status'], 'trusted')
        self.assertIsNotNone(rows[0]['context_captured_at'])

    def test_unavailable_context_stored_by_handler(self):
        """行情不可用 → 上下文 context_status=unavailable 带原因"""
        bridge._build_trade_context = lambda: {
            'rule_state': None,
            'market_snapshot': None,
            'context_captured_at': None,
            'context_status': 'unavailable',
            'context_unavailable_reason': '行情数据不可用',
        }
        entry = _manual_backfill_entry({'时间': '10:00', '动作': '买入', '代码': '000001', '标的': 'TEST',
                 '价格': 10, '数量': 100, 'event_id': 'evt-unavail'})
        status, body = self._post(entry)
        self.assertEqual(status, 200, f"unavailable 也应插入成功: {body}")
        rows = db._exec("SELECT rule_state_json, context_status, context_unavailable_reason FROM trade_records")
        self.assertIsNone(rows[0]['rule_state_json'], "不可用时应无 rule_state")
        self.assertEqual(rows[0]['context_status'], 'unavailable')
        self.assertIsNotNone(rows[0]['context_unavailable_reason'])

    def test_client_forged_context_not_in_db(self):
        """客户端夹带 rule_state/market_snapshot → handler 不写入 DB"""
        bridge._build_trade_context = lambda: {
            'rule_state': None, 'market_snapshot': None,
            'context_captured_at': None, 'context_status': 'unavailable',
            'context_unavailable_reason': '行情数据不可用',
        }
        entry = _manual_backfill_entry({'时间': '10:00', '动作': '买入', '代码': '000001', '标的': 'TEST',
                 '价格': 10, '数量': 100, 'event_id': 'evt-forged',
                 'rule_state': {'version': 'forged'},
                 'market_snapshot': {'fake': 'data'}})
        status, body = self._post(entry)
        self.assertEqual(status, 200, f"合法 entry 仍应插入: {body}")
        rows = db._exec("SELECT rule_state_json, market_snapshot_json FROM trade_records")
        if rows[0]['rule_state_json']:
            self.assertNotIn('forged', rows[0]['rule_state_json'], "handler 不得写入客户端夹带的 rule_state")
        if rows[0]['market_snapshot_json']:
            self.assertNotIn('fake', rows[0]['market_snapshot_json'], "handler 不得写入客户端夹带的 market_snapshot")


class ConcurrentSellGuardTests(unittest.TestCase):
    """YM-W15-01: 并发卖出原子门禁"""

    def setUp(self):
        _setup(self)
        bridge.CACHE['live_quotes'] = {}
        from datetime import datetime
        self.today = datetime.now().strftime("%Y-%m-%d")

    def tearDown(self): _teardown(self)

    def _insert_anchor_and_position(self):
        from scripts.account_ssot import ensure_today_anchor
        data = {
            "pnl": {"可用资金": 100000, "累计入金": 100000},
            "positions": [{"标的": "TEST", "代码": "000001", "数量": 100,
                           "成本": 10, "现价": 10, "状态": "持有"}],
        }
        # 建锚点使卖出有持仓可查
        db.insert_account_baseline({
            "date": self.today,
            "effective_at": f"{self.today}T09:30:00",
            "trade_id_cutoff": 0,
            "cash": 100000,
            "day_start_asset": 101000,
            "total_deposit": 100000,
            "positions": [{"标的": "TEST", "代码": "000001", "数量": 100,
                           "成本": 10, "状态": "持有"}],
            "source": "manual_correction",
        })
        db._exec_write("""INSERT INTO position_lots
            (lot_id, code, name, buy_date, original_qty, open_qty, cost_price,
             locked_until, lot_source, migration_source, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("old-000001", "000001", "TEST", self.today, 100, 100, 10,
             self.today, "test", "test", "open"))

    def _post_sell(self, qty=100):
        h = _handler('/api/sync', {'entry': {
            '时间': '10:00', '动作': '卖出', '代码': '000001', '标的': 'TEST',
            '价格': 15, '数量': qty, 'event_id': f'evt-sell-{qty}-{id(self)}'
        }})
        h.do_POST()
        return h._resp_status, json.loads(h._resp_body) if h._resp_body else {}

    def test_concurrent_sell_only_one_succeeds(self):
        """同一100股持仓，并发两条卖出100股（不同event_id）：只一条200，另一条409"""
        self._insert_anchor_and_position()
        import threading, random

        results = []

        ticket_ids = [
            db.create_trade_ticket({
                "trade_date": self.today,
                "code": "000001",
                "name": "TEST",
                "action_type": "sell",
                "status": "executable",
            })
            for _ in range(2)
        ]

        def sell(evt_id, ticket_id):
            h = _handler('/api/sync', {'entry': {
                '时间': '10:00', '动作': '卖出', '代码': '000001', '标的': 'TEST',
                '价格': 15, '数量': 100, 'event_id': evt_id,
                'ticket_id': ticket_id,
                'input_source': 'spoken_confirmed',
                'confirmed_by': 'yimu',
                'audit_note': 'concurrent sell test',
            }})
            h.do_POST()
            results.append((h._resp_status, json.loads(h._resp_body) if h._resp_body else {}))

        eid1 = 'evt-conc-a-' + str(random.random())
        eid2 = 'evt-conc-b-' + str(random.random())
        t1 = threading.Thread(target=sell, args=(eid1, ticket_ids[0]))
        t2 = threading.Thread(target=sell, args=(eid2, ticket_ids[1]))
        t1.start(); t2.start()
        t1.join(); t2.join()

        statuses = [r[0] for r in results]
        inserted = sum(1 for s in statuses if s == 200)
        rejected = sum(1 for s in statuses if s == 409)

        self.assertEqual(inserted, 1,
            f"并发卖出只能一笔200, 实为 {results}")
        self.assertGreaterEqual(rejected, 1,
            f"至少一笔409, 实为 {results}")

        # 账本验证：只有一笔成交
        trades = db._exec("SELECT * FROM trade_records")
        self.assertEqual(len(trades), 1,
            f"应只有1条成交记录, 实为{len(trades)}条")

        # 回放验证：持仓 0，现金正确
        from scripts.account_ssot import reduce_account_state
        anchor = db.query_account_baseline(self.today)
        trades_list = db.query_trades(date_from=self.today, date_to=self.today, limit=10)
        state = reduce_account_state(anchor, trades_list, {})
        self.assertEqual(state["cash"], 101500,  # 100000 + 100*15
            f"现金应为100000+1500=101500, 实为{state['cash']}")
        self.assertEqual(len(state["positions"]), 0,
            "持仓应为0")


if __name__ == "__main__":
    unittest.main()
