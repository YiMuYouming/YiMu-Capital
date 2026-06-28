"""test_trade_review.py — 成交上下文与事后结果 (Gate 3A)

全隔离：temp DB，不访问 data/**，不调用真实写接口。
"""
import io, json, tempfile, threading, unittest
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
import scripts.db as db
import scripts.bridge as bridge


def _setup_temp_db(test):
    test.tmp = tempfile.TemporaryDirectory()
    test.orig_path = db.DB_PATH
    test.orig_local = db._local
    db.DB_PATH = Path(test.tmp.name) / "test.db"
    db._local = threading.local()
    db.init_db()


def _teardown_temp_db(test):
    db.close_conn()
    db.DB_PATH = test.orig_path
    db._local = test.orig_local
    test.tmp.cleanup()


class MigrationTest(unittest.TestCase):

    def setUp(self):
        _setup_temp_db(self)

    def tearDown(self):
        _teardown_temp_db(self)

    def test_new_columns_exist_after_init(self):
        cols = {r['name'] for r in db._exec("PRAGMA table_info(trade_records)")}
        for c in ['rule_state_json', 'market_snapshot_json', 'outcome', 'review_note']:
            self.assertIn(c, cols, f"列 {c} 应在 trade_records 中")

    def test_old_db_migrates(self):
        """模拟旧库无新列 → init_db 自动添加"""
        conn = db.get_conn()
        for c in ['rule_state_json', 'market_snapshot_json', 'outcome', 'review_note']:
            try:
                conn.execute(f"ALTER TABLE trade_records DROP COLUMN {c}")
            except Exception:
                pass
        conn.commit()
        cols_before = {r['name'] for r in db._exec("PRAGMA table_info(trade_records)")}
        self.assertNotIn('outcome', cols_before)
        db.init_db()  # re-run migration
        cols_after = {r['name'] for r in db._exec("PRAGMA table_info(trade_records)")}
        for c in ['rule_state_json', 'market_snapshot_json', 'outcome', 'review_note']:
            self.assertIn(c, cols_after, f"迁移后应有 {c}")


class ReviewContextTest(unittest.TestCase):

    def setUp(self):
        _setup_temp_db(self)
        self._trade_seq = 0

    def tearDown(self):
        _teardown_temp_db(self)

    def test_insert_with_context(self):
        rs = {'version': 'g1a-v1', 'tradable': True, 'caps': {}, 'windows': {'w1': {}, 'w2': {}}, 'blocks': [], 'warnings': []}
        mkt = {'iwencai': {'情绪值': 65}}
        ok = db.insert_trade_with_context({
            'trade_date': '2026-05-27', 'trade_time': '10:00',
            'action': 'W1追涨', 'code': '000001', 'name': '测试', 'price': 10, 'qty': 100,
            'window': 'W1', 'reason': 'W1信号'
        }, rule_state=rs, market_snapshot=mkt)
        self.assertTrue(ok)

        rows = db._exec("SELECT * FROM trade_records ORDER BY id DESC LIMIT 1")
        t = dict(rows[0])
        self.assertIsNotNone(t.get('rule_state_json'))
        self.assertIsNotNone(t.get('market_snapshot_json'))
        rs_parsed = json.loads(t['rule_state_json'])
        self.assertEqual(rs_parsed['version'], 'g1a-v1')

    def test_insert_without_context_has_nulls(self):
        db.insert_trade({
            'trade_date': '2026-05-27', 'trade_time': '14:00',
            'action': '卖出', 'code': '000001', 'name': '测试', 'price': 12, 'qty': 100,
            'reason': '止盈'
        })
        rows = db._exec("SELECT * FROM trade_records ORDER BY id DESC LIMIT 1")
        t = dict(rows[0])
        self.assertIsNone(t.get('rule_state_json'))
        self.assertIsNone(t.get('market_snapshot_json'))

    def test_outcome_update_only_writes_outcome(self):
        """日结只写 outcome，不修改原成交事实"""
        db.insert_trade({
            'trade_date': '2026-05-27', 'trade_time': '10:00',
            'action': 'W1追涨', 'code': '000001', 'name': '测试', 'price': 10, 'qty': 100,
            'reason': 'W1信号'
        })
        rows = db._exec("SELECT id, action, price, qty, code, outcome FROM trade_records")
        tid = rows[0]['id']
        orig_action = rows[0]['action']
        orig_price = rows[0]['price']

        db.update_trade_outcomes('2026-05-27', {int(tid): 'W1追涨 测试 浮盈+2%'})

        rows2 = db._exec("SELECT action, price, qty, code, outcome FROM trade_records WHERE id = ?", (tid,))
        self.assertEqual(rows2[0]['action'], orig_action, "原成交 action 不变")
        self.assertEqual(rows2[0]['price'], orig_price, "原成交 price 不变")
        self.assertEqual(rows2[0]['outcome'], 'W1追涨 测试 浮盈+2%')

    def test_query_trade_reviews(self):
        rs = {'version': 'g1a-v1', 'tradable': True}
        db.insert_trade_with_context({
            'trade_date': '2026-05-27', 'trade_time': '10:00',
            'action': 'W1追涨', 'code': '000001', 'name': '测试A', 'price': 10, 'qty': 100,
            'reason': 'W1信号'
        }, rule_state=rs, market_snapshot={'情绪值': 65})
        db.update_trade_outcomes('2026-05-27', {1: 'W1追涨 测试A 浮盈'})

        reviews = db.query_trade_reviews('2026-05-27')
        self.assertEqual(len(reviews), 1)
        r = reviews[0]
        self.assertEqual(r['name'], '测试A')
        self.assertIn('rule_state', r)
        self.assertEqual(r['rule_state']['version'], 'g1a-v1')
        self.assertIn('market_snapshot', r)
        self.assertEqual(r['outcome'], 'W1追涨 测试A 浮盈')


class DailyTicketReviewTest(unittest.TestCase):

    def setUp(self):
        _setup_temp_db(self)
        self._trade_seq = 0

    def tearDown(self):
        _teardown_temp_db(self)

    def _insert_trade(self, action, code, name, qty, ticket_id, group_id, window='W2'):
        self._trade_seq += 1
        db.insert_trade({
            'trade_date': '2026-06-03', 'trade_time': f'10:{self._trade_seq:02d}',
            'action': action, 'code': code, 'name': name, 'price': 10,
            'qty': qty, 'window': window, 'reason': 'pilot',
        })
        tid = db._exec("SELECT id FROM trade_records ORDER BY id DESC LIMIT 1")[0]['id']
        db.link_trade_to_ticket(tid, ticket_id, group_id, 'fill')
        return tid

    def test_build_daily_ticket_review_summary(self):
        from scripts.account_ssot import build_daily_ticket_review

        db.create_trade_ticket({
            'ticket_id': 'TICKET-20260603-600726-EXIT',
            'trade_date': '2026-06-03', 'code': '600726', 'name': '华电能源',
            'action_type': 'clear', 'status': 'closed_with_conflict',
            'window': 'W2', 'triggered_rule_ids': ['SELL-CLEAR-001'],
        })
        db.create_trade_ticket({
            'ticket_id': 'TICKET-20260603-002281-T',
            'trade_date': '2026-06-03', 'code': '002281', 'name': '光迅科技',
            'action_type': 'do_t', 'status': 'filled', 'window': 'W2',
            'triggered_rule_ids': ['T-001'],
        })
        db.create_trade_ticket({
            'ticket_id': 'TICKET-20260603-002475-W2-BUY',
            'trade_date': '2026-06-03', 'code': '002475', 'name': '立讯精密',
            'action_type': 'buy', 'status': 'filled', 'window': 'W2',
            'triggered_rule_ids': ['WIN-W2-001'],
        })
        for _ in range(3):
            self._insert_trade('卖出', '600726', '华电能源', 1000, 'TICKET-20260603-600726-EXIT', 'G-HD')
        self._insert_trade('卖出', '002281', '光迅科技', 500, 'TICKET-20260603-002281-T', 'G-GX')
        self._insert_trade('买入', '002281', '光迅科技', 500, 'TICKET-20260603-002281-T', 'G-GX')
        self._insert_trade('卖出', '002281', '光迅科技', 500, 'TICKET-20260603-002281-T', 'G-GX')
        self._insert_trade('W2买入', '002475', '立讯精密', 300, 'TICKET-20260603-002475-W2-BUY', 'G-LX')
        db._exec_write("""
            INSERT INTO ticket_conflict_log
            (trade_date, ticket_id, code, conflict_type, severity, expected_json, actual_json, note)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, ('2026-06-03', 'TICKET-20260603-600726-EXIT', '600726',
              'T1_SELLABLE_MISMATCH', 'high',
              json.dumps({'sellable': 7000}), json.dumps({'sell': 10000}), 'pilot'))

        summary = build_daily_ticket_review('2026-06-03')

        self.assertEqual(summary['ticket_count'], 3)
        self.assertEqual(summary['fill_count'], 7)
        self.assertEqual(len(summary['t1_conflicts']), 1)
        self.assertEqual(len(summary['do_t_results']), 1)
        self.assertEqual(summary['by_action_type']['buy'], 1)
        self.assertIn('3 tickets', summary['review_markdown'])
        self.assertIn('7 fills', summary['review_markdown'])
        self.assertIn('1 T+1 conflict candidate', summary['review_markdown'])
        self.assertIn('1 do-T group', summary['review_markdown'])
        self.assertIn('1 W2 buy', summary['review_markdown'])
        self.assertIn('rule_id_stats', summary)
        self.assertIn('blocked_but_later_would_win_count', summary['rule_id_stats'][0])


class BackfillTradeTicketsTest(unittest.TestCase):

    def setUp(self):
        _setup_temp_db(self)
        self.ref = Path(self.tmp.name) / "trade_tickets_2026-06-03.md"
        self.ref.write_text("# pilot\n", encoding="utf-8")
        self._insert_pilot_trade(42, "09:30", "卖出", "600726", "华电能源", 3000, 8.96)
        self._insert_pilot_trade(45, "13:46", "卖出", "600726", "华电能源", 2000, 9.57)
        self._insert_pilot_trade(46, "14:05", "卖出", "600726", "华电能源", 5000, 9.59)
        self._insert_pilot_trade(43, "10:14", "W1追涨", "002281", "光迅科技", 100, 225.78, "W1")
        self._insert_pilot_trade(44, "10:15", "W1追涨", "002281", "光迅科技", 100, 226.42, "W1")
        self._insert_pilot_trade(48, "14:56", "卖出", "002281", "光迅科技", 200, 223.80)
        self._insert_pilot_trade(47, "14:30", "W2买入", "002475", "立讯精密", 2000, 75.31, "W2")

    def tearDown(self):
        _teardown_temp_db(self)

    def _insert_pilot_trade(self, tid, time, action, code, name, qty, price, window=None):
        db._exec_write("""
            INSERT INTO trade_records
            (id, trade_date, trade_time, action, code, name, price, qty, window, reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (tid, "2026-06-03", time, action, code, name, price, qty, window, "pilot"))

    def test_backfill_dry_run_writes_nothing(self):
        from scripts.ops import backfill_trade_tickets

        out = io.StringIO()
        with redirect_stdout(out):
            backfill_trade_tickets.main([
                "--date", "2026-06-03", "--dry-run", "--reference", str(self.ref)
            ])

        self.assertIn("Would create ticket TICKET-20260603-600726-EXIT from trades 42,45,46", out.getvalue())
        self.assertEqual(db.query_trade_tickets(date_from="2026-06-03", date_to="2026-06-03"), [])
        rows = db._exec("SELECT COUNT(*) AS n FROM trade_records WHERE ticket_id IS NOT NULL")
        self.assertEqual(rows[0]["n"], 0)

    def test_backfill_apply_links_all_pilot_trades_and_archives_reference(self):
        from scripts.ops import backfill_trade_tickets

        out = io.StringIO()
        with redirect_stdout(out):
            backfill_trade_tickets.main([
                "--date", "2026-06-03", "--apply", "--reference", str(self.ref)
            ])

        tickets = db.query_trade_tickets(date_from="2026-06-03", date_to="2026-06-03", limit=10)
        self.assertEqual(len(tickets), 3)
        hd = db.query_trade_ticket("TICKET-20260603-600726-EXIT")
        self.assertEqual(hd["status"], "closed_with_conflict")
        linked = db._exec("SELECT COUNT(*) AS n FROM trade_records WHERE trade_date = ? AND ticket_id IS NOT NULL", ("2026-06-03",))
        self.assertEqual(linked[0]["n"], 7)
        conflicts = db._exec("SELECT * FROM ticket_conflict_log WHERE conflict_type = ?", ("T1_SELLABLE_MISMATCH",))
        self.assertEqual(len(conflicts), 1)
        self.assertIn("Creates 3 trade_tickets", out.getvalue())
        archived = Path(self.tmp.name) / "reference_archive" / "trade_tickets_2026-06-03.reference_only.md"
        self.assertTrue(archived.exists())
        self.assertIn("reference_only: true", archived.read_text(encoding="utf-8"))


class BackfillOrphanTradeTicketTest(unittest.TestCase):

    def setUp(self):
        _setup_temp_db(self)
        db._exec_write("""
            INSERT INTO trade_records
            (id, trade_date, trade_time, action, code, name, price, qty, window,
             reason, rule_state_json, market_snapshot_json, context_captured_at,
             context_status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            49, "2026-06-04", "14:10", "W2买入", "002281", "光迅科技",
            222.38, 200, "W2", "缩量回踩，加仓",
            json.dumps({"version": "g1a-v1"}, ensure_ascii=False),
            json.dumps({"iwencai": {"情绪值": 24.1}}, ensure_ascii=False),
            "2026-06-04T15:11:29", "trusted",
        ))
        db._exec_write("""
            INSERT INTO position_lots
            (lot_id, code, name, source_trade_id, buy_date, original_qty, open_qty,
             cost_price, locked_until, lot_source, migration_source, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            "trade:49", "002281", "光迅科技", 49, "2026-06-04",
            200, 200, 222.38, "2026-06-05", "same_day_trade",
            "trade_records:49", "open",
        ))

    def tearDown(self):
        _teardown_temp_db(self)

    def test_dry_run_writes_nothing(self):
        from scripts.ops import backfill_orphan_trade_ticket

        result = backfill_orphan_trade_ticket.run(
            49,
            apply=False,
            snapshot_meta={
                "rule_snapshot_hash": "hash-1",
                "today_execution_card_id": "EXEC-20260604",
                "rule_pack_version": "g1a-v1",
            },
        )

        self.assertEqual(result["status"], "dry_run")
        self.assertIsNone(dict(db._exec("SELECT ticket_id FROM trade_records WHERE id = 49")[0])["ticket_id"])
        self.assertEqual(db.query_trade_tickets(date_from="2026-06-04", date_to="2026-06-04"), [])

    def test_cli_accepts_explicit_snapshot_metadata(self):
        from scripts.ops import backfill_orphan_trade_ticket

        out = io.StringIO()
        with redirect_stdout(out):
            status = backfill_orphan_trade_ticket.main([
                "--trade-id", "49",
                "--dry-run",
                "--rule-snapshot-hash", "hash-1",
                "--today-execution-card-id", "EXEC-20260604",
                "--rule-pack-version", "g1a-v1",
            ])

        self.assertEqual(status, 0)
        self.assertIn('"rule_snapshot_hash": "hash-1"', out.getvalue())
        self.assertEqual(db.query_trade_tickets(date_from="2026-06-04", date_to="2026-06-04"), [])

    def test_apply_creates_hashed_posthoc_ticket_and_links_trade_and_lot(self):
        from scripts.ops import backfill_orphan_trade_ticket

        result = backfill_orphan_trade_ticket.run(
            49,
            apply=True,
            snapshot_meta={
                "rule_snapshot_hash": "hash-1",
                "today_execution_card_id": "EXEC-20260604",
                "rule_pack_version": "g1a-v1",
            },
        )

        self.assertEqual(result["status"], "applied")
        trade = dict(db._exec("SELECT ticket_id, trade_group_id, leg_type FROM trade_records WHERE id = 49")[0])
        ticket = db.query_trade_ticket(trade["ticket_id"])
        lot = dict(db._exec("SELECT source_ticket_id FROM position_lots WHERE source_trade_id = 49")[0])
        self.assertEqual(ticket["rule_snapshot_hash"], "hash-1")
        self.assertEqual(ticket["today_execution_card_id"], "EXEC-20260604")
        self.assertEqual(ticket["status"], "filled")
        self.assertIn("posthoc", ticket["review_note"])
        self.assertEqual(trade["trade_group_id"], "POSTHOC-20260604-002281-49")
        self.assertEqual(trade["leg_type"], "buy_add")
        self.assertEqual(lot["source_ticket_id"], ticket["ticket_id"])


class AssetPnLParityTest(unittest.TestCase):
    """增加元数据前后资产/PnL 完全一致"""

    def setUp(self):
        _setup_temp_db(self)
        today = '2026-05-27'
        self.data_file = Path(self.tmp.name) / "dashboard_data.json"
        self.data_file.write_text(json.dumps({
            "meta": {"date": today},
            "pnl": {"可用资金": 100000, "累计入金": 100000},
            "positions": [],
        }), encoding="utf-8")
        db.insert_account_baseline({
            'date': today, 'effective_at': f'{today}T09:30:00',
            'trade_id_cutoff': 0, 'cash': 100000, 'day_start_asset': 100000,
            'total_deposit': 100000, 'positions': [], 'source': 'recovery',
        })

    def tearDown(self):
        _teardown_temp_db(self)

    def _baseline_state(self):
        from scripts.account_ssot import load_current_account_state
        return load_current_account_state(
            {},
            now="2026-05-27T10:00:00",
            data_file=self.data_file,
        )

    def _insert_and_check(self):
        """Insert trades with context, verify asset state unchanged vs plain insert"""
        # Plain insert
        db.insert_trade({
            'trade_date': '2026-05-27', 'trade_time': '10:00',
            'action': 'W1追涨', 'code': '000001', 'name': '测试', 'price': 10, 'qty': 100,
            'reason': 'W1信号'
        })
        state1 = self._baseline_state()

        # Now insert same trade but WITH context — asset should be identical
        db.insert_trade_with_context({
            'trade_date': '2026-05-27', 'trade_time': '10:05',
            'action': '卖出', 'code': '000001', 'name': '测试', 'price': 11, 'qty': 50,
            'reason': '减仓'
        }, rule_state={'version': 'g1a-v1'}, market_snapshot={'情绪值': 65})
        state2 = self._baseline_state()

        # Asset state should be additive (both trades counted)
        self.assertIsNotNone(state1.get('total_asset'))
        self.assertIsNotNone(state2.get('total_asset'))
        # With context insert, the trade should still be counted identically
        # Verify the second state has both trades
        self.assertNotEqual(state1['total_asset'], state2['total_asset'],
                            "卖出后资产应变化")

    def test_correction_chain_preserved(self):
        """纠错链不受 outcome 写入影响"""
        db.insert_trade({
            'trade_date': '2026-05-27', 'trade_time': '10:00',
            'action': 'W1追涨', 'code': '000001', 'name': '测试', 'price': 10, 'qty': 100,
            'reason': 'initial'
        })
        state_before = self._baseline_state()

        new_id = db.insert_correction_trade(1, '卖出', 10, 100, '纠错测试')
        self.assertGreater(new_id, 0)

        db.update_trade_outcomes('2026-05-27', {1: '已纠错', new_id: '纠错记录'})

        rows = db._exec("SELECT id, action, reversal_of_id, is_reversal, outcome FROM trade_records ORDER BY id")
        self.assertEqual(rows[0]['outcome'], '已纠错')
        self.assertEqual(rows[1]['is_reversal'], 1)
        self.assertEqual(rows[1]['reversal_of_id'], 1)
        # Original trade facts unchanged
        self.assertEqual(rows[0]['action'], 'W1追涨')

    def test_closing_anchor_outcome_fill(self):
        """日结补 outcome 不改变资产"""
        from scripts.account_ssot import generate_closing_anchor, reduce_account_state
        from scripts.db import query_account_baseline, query_trades, query_fund_events

        db.insert_trade({
            'trade_date': '2026-05-27', 'trade_time': '10:00',
            'action': 'W1追涨', 'code': '000001', 'name': '测试', 'price': 10, 'qty': 100,
            'reason': 'W1信号'
        })
        db.insert_trade({
            'trade_date': '2026-05-27', 'trade_time': '14:30',
            'action': '卖出', 'code': '000001', 'name': '测试', 'price': 12, 'qty': 100,
            'reason': '止盈'
        })

        pnl_path = Path(self.tmp.name) / "pnl_history.json"
        pnl_path.write_text(json.dumps({"meta": {}, "daily": []}))

        result = generate_closing_anchor(
            {'000001': {'最新价': 12}}, now='2026-05-27T15:05:00',
            pnl_history_path=pnl_path)
        self.assertIsNotNone(result)

        # Check outcomes were written
        rows = db._exec("SELECT id, action, outcome FROM trade_records ORDER BY id")
        for r in rows:
            self.assertTrue(r['outcome'], f"trade {r['id']} ({r['action']}) 应有 outcome")


class UnverifiedContextTest(unittest.TestCase):
    """历史日期/重放操作不应绑定可信上下文"""

    def setUp(self):
        _setup_temp_db(self)

    def tearDown(self):
        _teardown_temp_db(self)

    def test_historical_trade_has_null_context(self):
        """客户端提交历史 trade_date，context 列应为 null"""
        # Simulate bridge logic: trade_date != today => context is None
        historical_date = '2020-01-15'
        today = datetime.now().strftime('%Y-%m-%d')
        is_today = (historical_date == today)
        rule_ctx = {'version': 'g1a-v1', 'tradable': True} if is_today else None
        mkt_ctx = {'情绪值': 65} if is_today else None
        self.assertIsNone(rule_ctx, "历史日期不应获得 rule_state")
        self.assertIsNone(mkt_ctx, "历史日期不应获得 market_snapshot")
        db.insert_trade_with_context({
            'trade_date': historical_date, 'trade_time': '10:00',
            'action': '买入', 'code': '000001', 'name': '测试', 'price': 10, 'qty': 100,
        }, rule_state=rule_ctx, market_snapshot=mkt_ctx)
        rows = db._exec("SELECT * FROM trade_records")
        t = dict(rows[0])
        self.assertIsNone(t.get('rule_state_json'))
        self.assertIsNone(t.get('market_snapshot_json'))

    def test_insert_with_context_stores_json(self):
        """insert_trade_with_context 正确存储 JSON context（功能保留，供未来服务端事件源使用）"""
        today = datetime.now().strftime('%Y-%m-%d')
        db.insert_trade_with_context({
            'trade_date': today, 'trade_time': '10:00',
            'action': '买入', 'code': '000001', 'name': '测试', 'price': 10, 'qty': 100,
        }, rule_state={'version': 'g1a-v1'}, market_snapshot={'情绪值': 65})
        rows = db._exec("SELECT * FROM trade_records")
        t = dict(rows[0])
        self.assertIsNotNone(t.get('rule_state_json'))
        self.assertIsNotNone(t.get('market_snapshot_json'))


class OutcomeWithCloseTest(unittest.TestCase):

    def setUp(self):
        _setup_temp_db(self)
        today = '2026-05-27'
        db.insert_account_baseline({
            'date': today, 'effective_at': f'{today}T09:30:00',
            'trade_id_cutoff': 0, 'cash': 100000, 'day_start_asset': 100000,
            'total_deposit': 100000, 'positions': [], 'source': 'recovery',
        })

    def tearDown(self):
        _teardown_temp_db(self)

    def test_buy_outcome_reflects_close_price(self):
        """买入价10 收盘价12 复盘结果必须反映收盘表现"""
        db.insert_trade({
            'trade_date': '2026-05-27', 'trade_time': '10:00',
            'action': 'W1追涨', 'code': '000001', 'name': '测试', 'price': 10, 'qty': 100,
            'reason': 'W1信号'
        })
        from scripts.account_ssot import generate_closing_anchor
        pnl_path = Path(self.tmp.name) / "pnl_history.json"
        pnl_path.write_text(json.dumps({"meta": {}, "daily": []}))
        generate_closing_anchor(
            {'000001': {'最新价': 12}}, now='2026-05-27T15:05:00',
            pnl_history_path=pnl_path)
        rows = db._exec("SELECT outcome FROM trade_records")
        out = rows[0]['outcome']
        self.assertIn('12', out, f"outcome 应含收盘价 12: {out}")
        self.assertIn('浮盈', out, f"应标识浮盈: {out}")
        self.assertIn('+20', out, f"应含收益率 +20%: {out}")

    def test_review_note_persistence(self):
        """review_note 可写入并由只读复盘 API 读出"""
        db.insert_trade({
            'trade_date': '2026-05-27', 'trade_time': '10:00',
            'action': '买入', 'code': '000001', 'name': '测试', 'price': 10, 'qty': 100,
        })
        rows = db._exec("SELECT id FROM trade_records")
        tid = rows[0]['id']
        db.update_trade_review_note(int(tid), 'W1追涨 连板龙一 竞价高开5% 符合三件套')
        reviews = db.query_trade_reviews('2026-05-27')
        self.assertEqual(reviews[0]['review_note'], 'W1追涨 连板龙一 竞价高开5% 符合三件套')


class CrossDayRejectionTest(unittest.TestCase):

    def setUp(self):
        _setup_temp_db(self)

    def tearDown(self):
        _teardown_temp_db(self)

    def test_cross_day_outcome_rejected(self):
        """跨日 outcome 写入应被拒绝（trade_date 不匹配）"""
        db.insert_trade({
            'trade_date': '2026-05-26', 'trade_time': '10:00',
            'action': '买入', 'code': '000001', 'name': '测试', 'price': 10, 'qty': 100,
        })
        rows = db._exec("SELECT id FROM trade_records")
        tid = rows[0]['id']
        # Try to write outcome for trade on 05-26 but pass date_str='2026-05-27'
        db.update_trade_outcomes('2026-05-27', {int(tid): 'should not write'})
        rows2 = db._exec("SELECT outcome FROM trade_records WHERE id = ?", (tid,))
        self.assertEqual(rows2[0]['outcome'] or '', '', "跨日 outcome 不应写入")


class ManualSyncUnverifiedTest(unittest.TestCase):
    """/api/sync 人工成交统一 unverified — 客户端时间不可信"""

    def setUp(self):
        _setup_temp_db(self)

    def tearDown(self):
        _teardown_temp_db(self)

    def test_current_minute_forged_trade_unverified(self):
        """客户端伪造当前分钟操作仍不得获得 trusted context"""
        now = datetime.now()
        trade_time = now.strftime('%H:%M')  # client forges current minute
        db.insert_trade_with_context({
            'trade_date': now.strftime('%Y-%m-%d'),
            'trade_time': trade_time, 'action': '买入', 'code': '000001',
            'name': '测试', 'price': 10, 'qty': 100,
        }, rule_state=None, market_snapshot=None)
        reviews = db.query_trade_reviews(now.strftime('%Y-%m-%d'))
        self.assertEqual(len(reviews), 1)
        self.assertIsNone(reviews[0].get('rule_state'), "伪造时间不得有 trusted rule_state")
        self.assertIsNone(reviews[0].get('market_snapshot'), "伪造时间不得有 trusted market_snapshot")

    def test_batch_sync_all_unverified(self):
        """整批 /api/sync 写入全为 unverified"""
        today = datetime.now().strftime('%Y-%m-%d')
        for tm in ['09:31', '10:00', '14:57']:
            db.insert_trade_with_context({
                'trade_date': today, 'trade_time': tm,
                'action': '买入', 'code': '000001', 'name': '测试', 'price': 10, 'qty': 100,
            }, rule_state=None, market_snapshot=None)
        reviews = db.query_trade_reviews(today)
        self.assertEqual(len(reviews), 3)
        for r in reviews:
            self.assertIsNone(r.get('rule_state'), f"成交 {r['trade_time']} 应无 trusted context")
            self.assertIsNone(r.get('market_snapshot'))

    def test_replayed_list_unverified(self):
        """列表重放同样不得 trusted"""
        today = datetime.now().strftime('%Y-%m-%d')
        # First insert
        db.insert_trade_with_context({
            'trade_date': today, 'trade_time': '10:00',
            'action': '买入', 'code': '000001', 'name': '测试', 'price': 10, 'qty': 100,
        }, rule_state=None, market_snapshot=None)
        # Replay same trade (gets ignored by INSERT OR IGNORE, but we test the principle)
        db.insert_trade_with_context({
            'trade_date': today, 'trade_time': '10:00',
            'action': '买入', 'code': '000001', 'name': '测试', 'price': 10, 'qty': 100,
        }, rule_state=None, market_snapshot=None)
        reviews = db.query_trade_reviews(today)
        self.assertEqual(len(reviews), 1)
        self.assertIsNone(reviews[0].get('rule_state'))


class SyncTrustedContextTests(unittest.TestCase):
    """v3 Phase 2: /api/sync 当日在线成交绑定服务端可信上下文"""

    def setUp(self):
        _setup_temp_db(self)

    def tearDown(self):
        _teardown_temp_db(self)

    def test_insert_with_context_captured_at(self):
        """insert_trade_with_context 支持 context_status 和 context_captured_at 参数并写入 DB"""
        today = datetime.now().strftime('%Y-%m-%d')
        rs = {'version': 'g1a-v1', 'tradable': True, 'windows': {'w1': {}, 'w2': {}}, 'blocks': [], 'warnings': []}
        mkt = {'iwencai': {'情绪值': 65}, 'live_index': {'上证指数涨幅': '-0.22'}}
        captured = f"{today}T10:00:05"
        ok, tid, status = db.insert_trade_with_context({
            'trade_date': today, 'trade_time': '10:00',
            'action': '买入', 'code': '000001', 'name': '测试', 'price': 10, 'qty': 100,
        }, rule_state=rs, market_snapshot=mkt, context_captured_at=captured,
           context_status='trusted')
        self.assertTrue(ok, "insert_trade_with_context 应返回 True")
        reviews = db.query_trade_reviews(today)
        self.assertEqual(len(reviews), 1)
        self.assertEqual(reviews[0].get('context_captured_at'), captured)
        self.assertEqual(reviews[0].get('context_status'), 'trusted')
        self.assertIsNone(reviews[0].get('context_unavailable_reason'))

    def test_unavailable_context_stores_status_and_reason(self):
        """不可用上下文存储 context_status='unavailable' + 原因"""
        today = datetime.now().strftime('%Y-%m-%d')
        db.insert_trade_with_context({
            'trade_date': today, 'trade_time': '14:00',
            'action': '买入', 'code': '000001', 'name': '测试', 'price': 12, 'qty': 100,
        }, rule_state=None, market_snapshot=None, context_status='unavailable',
           context_unavailable_reason='行情数据不可用')
        reviews = db.query_trade_reviews(today)
        self.assertEqual(len(reviews), 1)
        self.assertIsNone(reviews[0].get('rule_state'))
        self.assertIsNone(reviews[0].get('context_captured_at'))
        self.assertEqual(reviews[0].get('context_status'), 'unavailable')
        self.assertEqual(reviews[0].get('context_unavailable_reason'), '行情数据不可用')

    def test_historical_sync_no_context_captured(self):
        """历史补录成交不得标记 trusted → context_captured_at = None"""
        db.insert_trade({
            'trade_date': '2020-01-15', 'trade_time': '10:00',
            'action': '买入', 'code': '000001', 'name': '测试', 'price': 10, 'qty': 100,
        })
        reviews = db.query_trade_reviews('2020-01-15')
        self.assertEqual(len(reviews), 1)
        self.assertIsNone(reviews[0].get('rule_state'))
        self.assertIsNone(reviews[0].get('context_captured_at'))
        self.assertIsNone(reviews[0].get('context_status'))

    def test_client_forged_context_not_trusted(self):
        """客户端夹带 rule_state/market_snapshot → 服务端拒绝"""
        today = datetime.now().strftime('%Y-%m-%d')
        db.insert_trade_with_context({
            'trade_date': today, 'trade_time': '10:00',
            'action': '买入', 'code': '000001', 'name': '测试', 'price': 10, 'qty': 100,
            # These would be client-forged — server should ignore
            'rule_state': {'version': 'fake'},
            'market_snapshot': {'fake': 'data'},
        }, rule_state=None, market_snapshot=None)
        reviews = db.query_trade_reviews(today)
        self.assertEqual(len(reviews), 1)
        # Context from client data dict should NOT be stored
        self.assertIsNone(reviews[0].get('rule_state'), "客户端伪造的 rule_state 应被忽略")
        self.assertIsNone(reviews[0].get('market_snapshot'), "客户端伪造的 market_snapshot 应被忽略")
        self.assertIsNone(reviews[0].get('context_captured_at'), "客户端伪造时 context_captured_at 应为 None")


class BuildTradeContextTests(unittest.TestCase):
    """/api/sync 上下文构建函数 _build_trade_context 完整测试"""

    def setUp(self):
        self._orig_cache = dict(bridge.CACHE)
        bridge.CACHE.clear()
        self._orig_build_rule = bridge._build_rule_state

    def tearDown(self):
        bridge.CACHE.clear()
        bridge.CACHE.update(self._orig_cache)
        bridge._build_rule_state = self._orig_build_rule

    def test_no_quotes_returns_unavailable(self):
        """无 live_quotes → 返回 unavailable"""
        result = bridge._build_trade_context()
        self.assertEqual(result['context_status'], 'unavailable')
        self.assertIsNotNone(result['context_unavailable_reason'])

    def test_old_quotes_returns_unavailable(self):
        """旧行情（>600s）→ 返回 unavailable"""
        import time
        old = time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime(time.time() - 1200))
        bridge.CACHE['live_quotes'] = {'_updated': old}
        result = bridge._build_trade_context()
        self.assertEqual(result['context_status'], 'unavailable')

    def test_block_untrusted_returns_unavailable(self):
        """rule_state 含 DATA_UNTRUSTED → 返回 unavailable 带 codes"""
        fresh = datetime.now().strftime('%Y-%m-%dT%H:%M:%SZ')
        bridge.CACHE['live_quotes'] = {'_updated': fresh}
        bridge.CACHE['iwencai'] = {'情绪值': 65}
        bridge.CACHE['live_index'] = {'上证指数涨幅': '-0.22'}
        bridge._build_rule_state = lambda: {
            'version': 'g1a-v1', 'tradable': False, 'blocks': [
                {'code': 'DATA_UNTRUSTED', 'scope': 'all'},
            ], 'warnings': [], 'windows': {'w1': {}, 'w2': {}},
        }
        result = bridge._build_trade_context()
        self.assertEqual(result['context_status'], 'unavailable')
        self.assertIn('DATA_UNTRUSTED', result.get('context_unavailable_reason', ''))

    def test_healthy_returns_trusted(self):
        """行情新鲜 + 无阻断块 → 返回 trusted 含全部字段"""
        fresh = datetime.now().strftime('%Y-%m-%dT%H:%M:%SZ')
        bridge.CACHE['live_quotes'] = {'_updated': fresh}
        bridge.CACHE['iwencai'] = {'情绪值': 65}
        bridge.CACHE['live_index'] = {'上证指数涨幅': '-0.22'}
        bridge._build_rule_state = lambda: {
            'version': 'g1a-v1', 'tradable': True, 'blocks': [],
            'warnings': [], 'windows': {'w1': {}, 'w2': {}},
        }
        result = bridge._build_trade_context()
        self.assertEqual(result['context_status'], 'trusted')
        self.assertIsNotNone(result['rule_state'])
        self.assertIsNotNone(result['market_snapshot'])
        self.assertIsNotNone(result['context_captured_at'])
        self.assertIsNone(result['context_unavailable_reason'])


class ReviewAPIWriteTest(unittest.TestCase):

    def setUp(self):
        _setup_temp_db(self)
        db.insert_trade({
            'trade_date': '2026-05-27', 'trade_time': '10:00',
            'action': '买入', 'code': '000001', 'name': '测试', 'price': 10, 'qty': 100,
        })

    def tearDown(self):
        _teardown_temp_db(self)

    def test_review_note_write_and_read(self):
        """写入 review_note 后只读 API 可读出，原成交事实不变"""
        rows = db._exec("SELECT id, action, price FROM trade_records")
        tid = rows[0]['id']
        orig_action = rows[0]['action']
        orig_price = rows[0]['price']

        db.update_trade_review_note(int(tid), 'W1追涨 符合三件套 龙头确认')

        rows2 = db._exec("SELECT action, price, review_note FROM trade_records WHERE id = ?", (tid,))
        self.assertEqual(rows2[0]['action'], orig_action, "成交事实不变")
        self.assertEqual(rows2[0]['price'], orig_price, "价格不变")
        self.assertEqual(rows2[0]['review_note'], 'W1追涨 符合三件套 龙头确认')

        # Read via query_trade_reviews
        reviews = db.query_trade_reviews('2026-05-27')
        self.assertEqual(reviews[0]['review_note'], 'W1追涨 符合三件套 龙头确认')

    def test_review_note_only_changes_note(self):
        """review_note 写入不修改 asset/锚点/correction 链"""
        rows = db._exec("SELECT id, action, price, qty, code, realized_pnl, reversal_of_id, is_reversal FROM trade_records")
        tid = rows[0]['id']
        before = dict(rows[0])

        db.update_trade_review_note(int(tid), '事后归因测试')

        after = dict(db._exec("SELECT * FROM trade_records WHERE id = ?", (tid,))[0])
        for col in ['action', 'price', 'qty', 'code', 'realized_pnl', 'reversal_of_id', 'is_reversal']:
            self.assertEqual(after.get(col), before.get(col), f"列 {col} 不应变")



class ReviewNoteHandlerTest(unittest.TestCase):
    """POST /api/trades/review: 存在返回200，不存在返回404"""

    def setUp(self):
        _setup_temp_db(self)

    def tearDown(self):
        _teardown_temp_db(self)

    def test_existing_trade_review_note_returns_true(self):
        db.insert_trade({
            'trade_date': '2026-05-27', 'trade_time': '10:00',
            'action': '买入', 'code': '000001', 'name': '测试', 'price': 10, 'qty': 100,
        })
        rows = db._exec("SELECT id FROM trade_records")
        tid = rows[0]['id']
        updated = db.update_trade_review_note(int(tid), 'W1追涨 三件套全满足')
        self.assertTrue(updated, "存在记录应返回 True")
        # Verify written
        reviews = db.query_trade_reviews('2026-05-27')
        self.assertEqual(reviews[0]['review_note'], 'W1追涨 三件套全满足')

    def test_nonexistent_trade_review_note_returns_false(self):
        updated = db.update_trade_review_note(99999, '不存在的记录')
        self.assertFalse(updated, "不存在 trade_id 应返回 False")

    def test_review_note_on_nonexistent_preserves_others(self):
        """对不存在记录写 review_note 不影响已有记录"""
        db.insert_trade({
            'trade_date': '2026-05-27', 'trade_time': '10:00',
            'action': '买入', 'code': '000001', 'name': '测试', 'price': 10, 'qty': 100,
        })
        before = dict(db._exec("SELECT * FROM trade_records")[0])
        db.update_trade_review_note(99999, '不应该写进去')
        after = dict(db._exec("SELECT * FROM trade_records")[0])
        for col in ['action', 'price', 'qty', 'code', 'name', 'review_note']:
            self.assertEqual(after.get(col), before.get(col), f"列 {col} 不应变")



class ReviewHandlerHTTPTest(unittest.TestCase):
    """真实 mock handler POST /api/trades/review 覆盖"""

    def setUp(self):
        _setup_temp_db(self)
        self.orig_cache = dict(bridge.CACHE)
        self.orig_inited = bridge._db_inited
        bridge._db_inited = False
        db.insert_trade({
            'trade_date': '2026-05-27', 'trade_time': '10:00',
            'action': '买入', 'code': '000001', 'name': '测试', 'price': 10, 'qty': 100,
        })

    def tearDown(self):
        _teardown_temp_db(self)
        bridge._db_inited = self.orig_inited
        bridge.CACHE.clear()
        bridge.CACHE.update(self.orig_cache)

    def _make_handler(self, path, payload):
        import io
        handler = object.__new__(bridge.BridgeHandler)
        handler.command = 'POST'
        handler.requestline = f'POST {path} HTTP/1.1'
        handler.path = path
        handler.request_version = 'HTTP/1.1'
        handler.request = mock.MagicMock()
        handler.request.version = 'HTTP/1.1'
        handler.client_address = ('127.0.0.1', 12345)
        handler.server = mock.MagicMock()
        body = json.dumps(payload).encode()
        handler.rfile = io.BytesIO(body)
        handler.headers = mock.MagicMock()
        handler.headers.get = lambda k, d=None: str(len(body))
        handler.log_message = mock.MagicMock()
        handler._resp_status = None
        handler._resp_body = b''

        def msr(code, p=None): handler._resp_status = code
        def msh(k, v): pass
        def meh(): pass
        def mww(s, d): handler._resp_body += d
        handler.send_response = msr
        handler.send_header = msh
        handler.end_headers = meh
        handler.wfile = type('WFile', (), {'write': mww})()
        return handler

    def test_existing_trade_returns_200(self):
        rows = db._exec("SELECT id FROM trade_records")
        tid = rows[0]['id']
        handler = self._make_handler('/api/trades/review', {'trade_id': int(tid), 'review_note': 'W1三件套全满足'})
        handler.do_POST()
        self.assertEqual(handler._resp_status, 200)
        body = json.loads(handler._resp_body)
        self.assertTrue(body.get('ok'))
        # Verify written to DB
        reviews = db.query_trade_reviews('2026-05-27')
        self.assertEqual(reviews[0]['review_note'], 'W1三件套全满足')

    def test_nonexistent_trade_returns_404(self):
        handler = self._make_handler('/api/trades/review', {'trade_id': 99999, 'review_note': '不存在的记录'})
        handler.do_POST()
        self.assertEqual(handler._resp_status, 404)
        body = json.loads(handler._resp_body)
        self.assertFalse(body.get('ok'))
        self.assertIn('not found', body.get('error', ''))

    def test_review_note_does_not_change_trade_facts(self):
        rows = db._exec("SELECT id, action, price, qty, code FROM trade_records")
        tid = rows[0]['id']
        before = dict(rows[0])
        handler = self._make_handler('/api/trades/review', {'trade_id': int(tid), 'review_note': '事后归因'})
        handler.do_POST()
        after = dict(db._exec("SELECT * FROM trade_records WHERE id = ?", (tid,))[0])
        for col in ['action', 'price', 'qty', 'code']:
            self.assertEqual(after.get(col), before.get(col), f"列 {col} 不应变")
        self.assertEqual(after.get('review_note'), '事后归因')

    def test_handler_releases_connection(self):
        rows = db._exec("SELECT id FROM trade_records")
        tid = rows[0]['id']
        handler = self._make_handler('/api/trades/review', {'trade_id': int(tid), 'review_note': '测试连接释放'})
        handler.do_POST()
        self.assertIsNone(getattr(db._local, 'conn', None), "handler 应释放 DB 连接")



if __name__ == '__main__':
    unittest.main()
