import tempfile
import unittest
from pathlib import Path

from autotrader.config import ConfigurationError, load_config


class ConfigTests(unittest.TestCase):
    def test_defaults_are_paper_only_with_initial_capital(self):
        cfg = load_config()
        self.assertTrue(cfg.paper_only)
        self.assertFalse(cfg.live_trading_enabled)
        self.assertEqual(str(cfg.initial_cash), "118.85")

    def test_live_trading_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text("[system]\nlive_trading_enabled=true\n", encoding="utf-8")
            with self.assertRaises(ConfigurationError):
                load_config(path)

