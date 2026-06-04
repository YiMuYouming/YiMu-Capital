"""test_bridge_bootstrap.py — bridge cold-start bootstrap lifecycle tests."""
import unittest
from unittest.mock import MagicMock, patch

import scripts.bridge as bridge


class BridgeBootstrapTests(unittest.TestCase):
    def test_run_cold_bootstrap_calls_collectors_with_force(self):
        collector = MagicMock(name="collector")

        bridge._run_cold_bootstrap([collector])

        collector.assert_called_once_with(force=True)

    def test_start_cold_bootstrap_runs_in_background_thread(self):
        slow_fn = MagicMock(name="slow_fn")

        with patch("scripts.bridge.Thread") as thread_cls:
            thread = thread_cls.return_value
            result = bridge.start_cold_bootstrap([slow_fn])

        self.assertIs(result, thread)
        thread_cls.assert_called_once()
        kwargs = thread_cls.call_args.kwargs
        self.assertTrue(kwargs.get("daemon"))
        self.assertEqual(kwargs.get("name"), "bridge-cold-bootstrap")
        thread.start.assert_called_once()
        slow_fn.assert_not_called()


if __name__ == "__main__":
    unittest.main()
