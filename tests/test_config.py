from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from config import Settings, load_settings


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.project = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def write_env(self, text):
        (self.project / ".env").write_text(text, encoding="utf-8")

    def test_literal_env_loading_and_environment_override(self):
        self.write_env("OPENAI_API_KEY='fake-key'\nOPENAI_MODEL=gpt-5-mini\nMEDHUB_PORT=8011\n")
        settings = load_settings(self.project, {"OPENAI_MODEL": "test-model"})
        self.assertEqual(settings.api_key, "fake-key")
        self.assertEqual(settings.model, "test-model")
        self.assertEqual(settings.port, 8011)
        self.assertEqual(settings.allowed_origins[0], "http://127.0.0.1:8011")
        self.assertNotIn("fake-key", repr(settings))
        self.assertNotIn(settings.signing_secret, repr(settings))

    def test_raw_secret_line_is_rejected_without_echoing_it(self):
        self.write_env("raw-super-private-key")
        with self.assertRaises(ValueError) as caught:
            load_settings(self.project, {})
        self.assertNotIn("raw-super-private-key", str(caught.exception))

    def test_parent_fallback_only_for_known_nested_workspace(self):
        self.write_env("OPENAI_API_KEY=parent-fake-key")
        arbitrary = self.project / "another-project"
        arbitrary.mkdir()
        self.assertEqual(load_settings(arbitrary, {}).api_key, "")
        nested = self.project / "MedHub_CheckUp"
        nested.mkdir()
        self.assertEqual(load_settings(nested, {}).api_key, "")
        (self.project / "server.py").write_text("# workspace marker", encoding="utf-8")
        self.assertEqual(load_settings(nested, {}).api_key, "parent-fake-key")
        (nested / ".env").write_text("OPENAI_API_KEY=child-fake-key", encoding="utf-8")
        self.assertEqual(load_settings(nested, {}).api_key, "child-fake-key")

    def test_production_requires_https_origin_and_random_secret(self):
        base = {"MEDHUB_ENV": "production"}
        with self.assertRaises(ValueError):
            load_settings(self.project, base)
        base["MEDHUB_ALLOWED_ORIGINS"] = "http://clinic.example"
        with self.assertRaises(ValueError):
            load_settings(self.project, base)
        base["MEDHUB_ALLOWED_ORIGINS"] = "https://clinic.example"
        for secret in ("", "a" * 48, "change-this-example-secret-for-production"):
            with self.subTest(secret=secret), self.assertRaises(ValueError):
                load_settings(self.project, {**base, "MEDHUB_SIGNING_SECRET": secret})
        settings = load_settings(self.project, {**base, "MEDHUB_SIGNING_SECRET": "K1n6J9e2P8a3Q0v4Z7w5YcXdRmBhLsTg"})
        self.assertEqual(settings.environment, "production")

    def test_rejects_invalid_origins_limits_and_admin_tokens(self):
        for values in ({"MEDHUB_ALLOWED_ORIGINS": "https://*.example"}, {"MEDHUB_ALLOWED_ORIGINS": "https://clinic.example/path"}, {"MEDHUB_ALLOWED_ORIGINS": "https://user:secret@clinic.example"}, {"MEDHUB_PORT": "-1"}, {"OPENAI_TIMEOUT_SECONDS": "NaN"}, {"MEDHUB_AGENT_ENABLED": "yes"}, {"ADMIN_TOKEN": "short"}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                load_settings(self.project, values)

    def test_ai_availability_requires_key_and_enabled(self):
        self.assertFalse(Settings().ai_available)
        self.assertTrue(Settings(api_key="fake-key").ai_available)
        self.assertFalse(Settings(api_key="fake-key", agent_enabled=False).ai_available)


if __name__ == "__main__":
    unittest.main()
