import importlib
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


class SecurityConfigTests(unittest.TestCase):
    def _reload_config(self):
        sys.modules.pop("config", None)
        return importlib.import_module("config")

    def test_development_may_use_local_signing_key(self):
        with patch.dict(os.environ, {"APP_ENV": "development"}, clear=False):
            os.environ.pop("SECRET_KEY", None)
            config = self._reload_config()

        self.assertGreaterEqual(len(config.SECRET_KEY), 32)

    def test_production_requires_explicit_signing_key(self):
        with patch.dict(os.environ, {"APP_ENV": "production"}, clear=False):
            os.environ.pop("SECRET_KEY", None)
            with self.assertRaisesRegex(RuntimeError, "SECRET_KEY"):
                self._reload_config()

    def test_unspecified_environment_is_secure_by_default(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "SECRET_KEY"):
                self._reload_config()

    def test_production_rejects_short_signing_key(self):
        with patch.dict(
            os.environ,
            {"APP_ENV": "production", "SECRET_KEY": "too-short"},
            clear=False,
        ):
            with self.assertRaisesRegex(RuntimeError, "32"):
                self._reload_config()

    def test_production_rejects_documented_placeholder_key(self):
        with patch.dict(
            os.environ,
            {
                "APP_ENV": "production",
                "SECRET_KEY": "pixelcraft-change-this-in-production",
            },
            clear=False,
        ):
            with self.assertRaisesRegex(RuntimeError, "placeholder"):
                self._reload_config()

    def test_unified_auth_uses_shared_validated_key(self):
        strong_key = "a-production-secret-that-is-at-least-32-characters"
        with patch.dict(
            os.environ,
            {"APP_ENV": "production", "SECRET_KEY": strong_key},
            clear=False,
        ):
            config = self._reload_config()
        self.assertEqual(config.SECRET_KEY, strong_key)
        auth_source = (BACKEND / "auth.py").read_text()
        self.assertIn("from config import SECRET_KEY", auth_source)
        self.assertFalse((BACKEND / "member_auth.py").exists())


if __name__ == "__main__":
    unittest.main()
