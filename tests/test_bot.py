from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from app import (
    MAX_MESSAGE_UNITS,
    TELEGRAM_MAX_MESSAGE_UNITS,
    Command,
    TelegramAutomation,
    parse_command,
    parse_spam_args,
    prepare_data_directory,
    split_telegram_text,
    utf16_length,
)
from state import ConnectionInfo, ConversationMode, StateStore


class CommandParsingTests(unittest.TestCase):
    def test_parses_spam_with_text_containing_spaces(self) -> None:
        command = parse_command("/spam 3 hello, two words", "tgibot")
        self.assertEqual(command, Command("spam", "3 hello, two words"))
        self.assertEqual(parse_spam_args(command.args), (3, "hello, two words"))

    def test_parses_explicit_username_case_insensitively(self) -> None:
        self.assertEqual(
            parse_command("/COPY@TgIbot off", "tgibot"),
            Command("copy", "off"),
        )
        self.assertIsNone(parse_command("/copy@another_bot on", "tgibot"))

    def test_invalid_spam_arguments_are_rejected(self) -> None:
        for args in ("", "0 hello", "11 hello", "three hello", "3", "3   ", "9" * 5000 + " hello"):
            with self.subTest(args=args):
                self.assertIsNone(parse_spam_args(args))

    def test_spam_text_limit_uses_utf16_units(self) -> None:
        oversized = "😀" * (MAX_MESSAGE_UNITS // 2 + 1)
        self.assertIsNone(parse_spam_args(f"1 {oversized}"))

    def test_text_splitter_never_breaks_a_unicode_character(self) -> None:
        text = "a" * (MAX_MESSAGE_UNITS - 1) + "😀" + "b"
        chunks = split_telegram_text(text)
        self.assertEqual("".join(chunks), text)
        self.assertTrue(all(utf16_length(chunk) <= MAX_MESSAGE_UNITS for chunk in chunks))


class TelegramMessageSendingTests(unittest.IsolatedAsyncioTestCase):
    async def test_send_text_accepts_telegram_maximum_message_length(self) -> None:
        automation = object.__new__(TelegramAutomation)
        automation._invoke_business = AsyncMock()
        info = ConnectionInfo("bc-test", 1, 2, True, True)
        text = "x" * TELEGRAM_MAX_MESSAGE_UNITS

        await automation._send_text(info, object(), text)

        automation._invoke_business.assert_awaited_once()

    async def test_send_text_rejects_text_over_telegram_limit(self) -> None:
        automation = object.__new__(TelegramAutomation)
        automation._invoke_business = AsyncMock()
        info = ConnectionInfo("bc-test", 1, 2, True, True)

        with self.assertRaises(ValueError):
            await automation._send_text(
                info,
                object(),
                "x" * (TELEGRAM_MAX_MESSAGE_UNITS + 1),
            )

        automation._invoke_business.assert_not_awaited()


@unittest.skipUnless(os.name == "posix", "POSIX file permissions are required")
class RuntimeFilePermissionTests(unittest.TestCase):
    def test_existing_data_directory_is_restricted(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            data_dir.mkdir(mode=0o755)
            data_dir.chmod(0o755)

            prepare_data_directory(data_dir)

            self.assertEqual(stat.S_IMODE(data_dir.stat().st_mode), 0o700)


class StateStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "state.sqlite3"
        self.store = StateStore(self.db_path)

    def tearDown(self) -> None:
        self.store.close()
        self.temp_dir.cleanup()

    def test_mode_transitions_are_exclusive_and_durable(self) -> None:
        connection_id, chat_id = "bc-test", 123
        self.assertEqual(self.store.get_mode(connection_id, chat_id), ConversationMode())

        mode = self.store.change_mode(connection_id, chat_id, "copy", True)
        self.assertEqual(mode, ConversationMode(copy_enabled=True, autobot_enabled=False))
        mode = self.store.change_mode(connection_id, chat_id, "autobot", True)
        self.assertEqual(mode, ConversationMode(copy_enabled=False, autobot_enabled=True))
        mode = self.store.change_mode(connection_id, chat_id, "autobot", False)
        self.assertEqual(mode, ConversationMode())

        self.store.close()
        reopened = StateStore(self.db_path)
        try:
            self.assertEqual(reopened.get_mode(connection_id, chat_id), ConversationMode())
        finally:
            reopened.close()
        # Replace the closed handle so tearDown remains safe.
        self.store = StateStore(self.db_path)

    def test_connection_metadata_round_trips(self) -> None:
        expected = self.store.save_connection("bc-2", 42, 4, True, True)
        self.assertEqual(self.store.get_connection("bc-2"), expected)

    @unittest.skipUnless(os.name == "posix", "POSIX file permissions are required")
    def test_database_and_sqlite_sidecars_are_owner_only(self) -> None:
        self.store.save_connection("bc-private", 42, 4, True, True)

        self.assertEqual(stat.S_IMODE(self.db_path.stat().st_mode), 0o600)
        for suffix in ("-wal", "-shm"):
            sidecar = Path(f"{self.db_path}{suffix}")
            if sidecar.exists():
                with self.subTest(sidecar=sidecar.name):
                    self.assertEqual(stat.S_IMODE(sidecar.stat().st_mode), 0o600)

    def test_fixed_window_rate_limit(self) -> None:
        scope, connection_id, user_id = "spam", "bc-rate", 456
        self.assertIsNone(self.store.consume_limit(scope, connection_id, user_id, 1, 60, now=120))
        retry_after = self.store.consume_limit(scope, connection_id, user_id, 1, 60, now=150)
        self.assertEqual(retry_after, 30)
        self.assertIsNone(self.store.consume_limit(scope, connection_id, user_id, 1, 60, now=180))

    def test_ai_history_is_isolated_per_business_chat(self) -> None:
        self.store.add_exchange("bc-a", 100, "question", "answer")
        self.assertEqual(
            self.store.get_history("bc-a", 100, 12),
            [
                {"role": "user", "content": "question"},
                {"role": "assistant", "content": "answer"},
            ],
        )
        self.assertEqual(self.store.get_history("bc-b", 100, 12), [])
        self.assertEqual(self.store.get_history("bc-a", 101, 12), [])


if __name__ == "__main__":
    unittest.main()
