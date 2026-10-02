from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app import Settings


class SettingsLoadingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_path = Path(self.temp_dir.name) / "config.py"
        self.config_path.write_text(
            'TELEGRAM_BOT_TOKEN = "123456:local-token"\n'
            'TELEGRAM_API_ID = "98765"\n'
            'TELEGRAM_API_HASH = "local-api-hash"\n'
            'ORCAROUTER_API_KEY = "local-ai-key"\n'
            'DATA_DIR = "~/tgibot-data"\n',
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_loads_all_credentials_from_local_python_file(self) -> None:
        settings = Settings.from_env(environ={}, config_path=self.config_path)

        self.assertEqual(settings.telegram_bot_token, "123456:local-token")
        self.assertEqual(settings.telegram_bot_id, 123456)
        self.assertEqual(settings.telegram_api_id, 98765)
        self.assertEqual(settings.telegram_api_hash, "local-api-hash")
        self.assertEqual(settings.orcarouter_api_key, "local-ai-key")
        self.assertEqual(settings.data_dir, Path("~/tgibot-data").expanduser())

    def test_environment_overrides_local_config(self) -> None:
        settings = Settings.from_env(
            environ={
                "TELEGRAM_BOT_TOKEN": "654321:hosted-token",
                "TELEGRAM_API_ID": "24680",
                "TELEGRAM_API_HASH": "hosted-api-hash",
                "ORCAROUTER_API_KEY": "hosted-ai-key",
                "DATA_DIR": "/var/data",
            },
            config_path=self.config_path,
        )

        self.assertEqual(settings.telegram_bot_id, 654321)
        self.assertEqual(settings.telegram_api_id, 24680)
        self.assertEqual(settings.telegram_api_hash, "hosted-api-hash")
        self.assertEqual(settings.orcarouter_api_key, "hosted-ai-key")
        self.assertEqual(settings.data_dir, Path("/var/data"))

    def test_ai_key_is_optional_for_non_ai_commands(self) -> None:
        self.config_path.write_text(
            'TELEGRAM_BOT_TOKEN = "123456:local-token"\n'
            'TELEGRAM_API_ID = 98765\n'
            'TELEGRAM_API_HASH = "local-api-hash"\n'
            'ORCAROUTER_API_KEY = "   "\n',
            encoding="utf-8",
        )

        settings = Settings.from_env(environ={}, config_path=self.config_path)

        self.assertIsNone(settings.orcarouter_api_key)

    def test_missing_required_setting_explains_config_file(self) -> None:
        self.config_path.write_text('TELEGRAM_BOT_TOKEN = ""\n', encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "TELEGRAM_API_ID.*config.py"):
            Settings.from_env(environ={}, config_path=self.config_path)

    def test_malformed_bot_token_is_rejected(self) -> None:
        self.config_path.write_text(
            'TELEGRAM_BOT_TOKEN = "123456:"\n'
            'TELEGRAM_API_ID = 98765\n'
            'TELEGRAM_API_HASH = "local-api-hash"\n',
            encoding="utf-8",
        )

        with self.assertRaisesRegex(ValueError, "TELEGRAM_BOT_TOKEN is malformed"):
            Settings.from_env(environ={}, config_path=self.config_path)

    def test_api_id_must_be_plain_ascii_digits(self) -> None:
        self.config_path.write_text(
            'TELEGRAM_BOT_TOKEN = "123456:local-token"\n'
            'TELEGRAM_API_ID = "12_345"\n'
            'TELEGRAM_API_HASH = "local-api-hash"\n',
            encoding="utf-8",
        )

        with self.assertRaisesRegex(ValueError, "TELEGRAM_API_ID must be a positive integer"):
            Settings.from_env(environ={}, config_path=self.config_path)

    def test_config_syntax_errors_are_reported_without_echoing_config_values(self) -> None:
        self.config_path.write_text("raise RuntimeError('private token text')\n", encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "Could not load config.py") as raised:
            Settings.from_env(environ={}, config_path=self.config_path)
        self.assertNotIn("private token text", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
