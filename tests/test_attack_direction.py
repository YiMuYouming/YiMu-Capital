"""test_attack_direction.py — W26 主攻方向 payload 回归测试"""
from datetime import datetime, timedelta, timezone
import unittest

from scripts.attack_direction import build_attack_direction


class AttackDirectionPayloadTests(unittest.TestCase):
    def test_builds_confirmed_early_first_board_direction(self):
        tz = timezone(timedelta(hours=8))
        now = datetime(2026, 6, 20, 9, 42, tzinfo=tz)
        payload = build_attack_direction(
            {
                "_updated": "2026-06-20T09:41:00+08:00",
                "zt_count": 4,
                "zt_stocks": [
                    {"code": "000001", "name": "算力一号", "reason": "算力", "seal_time": "09:34", "board_count": 1},
                    {"code": "000002", "name": "芯片二号", "reason": "半导体", "seal_time": "09:39", "board_count": 1},
                    {"code": "000003", "name": "算力三号", "reason": "算力", "seal_time": "09:50", "board_count": 2},
                    {"code": "000004", "name": "机器人", "reason": "机器人", "seal_time": "09:36", "board_count": 1},
                ],
            },
            sector_inflow=[{"名称": "算力", "涨跌幅": "+2.1%", "主力净流入": "6.5亿"}],
            now=now,
        )

        self.assertEqual(payload["source_status"], "confirmed")
        self.assertEqual(payload["summary"]["leader_sector"], "算力/半导体")
        self.assertEqual(payload["summary"]["early_first_count"], 3)
        self.assertGreaterEqual(payload["summary"]["confidence"], 45)
        self.assertEqual(payload["source_freshness"]["level"], "live")
        leader = payload["sectors"][0]
        self.assertEqual(leader["sector"], "算力/半导体")
        self.assertEqual(leader["early_first_count"], 2)
        self.assertEqual(leader["all_limit_count"], 3)
        self.assertIn("早封首板2只", leader["evidence"])

    def test_missing_confirmed_list_falls_back_to_reason_stats_without_overstating(self):
        tz = timezone(timedelta(hours=8))
        now = datetime(2026, 6, 20, 9, 50, tzinfo=tz)
        payload = build_attack_direction(
            {
                "_updated": "2026-06-20T09:45:00+08:00",
                "zt_count": 8,
                "reason_stats": {"算力": 4, "机器人": 2},
            },
            now=now,
        )

        self.assertEqual(payload["source_status"], "partial_reason_stats")
        self.assertEqual(payload["summary"]["conclusion"], "题材方向观察")
        self.assertEqual(payload["summary"]["early_first_count"], 0)
        self.assertIn("不能验收早封首板", payload["warnings"][0])
        self.assertEqual(payload["sectors"][0]["conclusion"], "题材观察")


if __name__ == "__main__":
    unittest.main()
