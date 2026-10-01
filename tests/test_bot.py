from __future__ import annotations

import asyncio
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from pathlib import Path

from app import (
    MAX_MESSAGE_UNITS,
    TelegramAutomation,
    app,
    Command,
    parse_command,
    parse_spam_args,
    ping,
    render_ping_url,
    split_telegram_text,
    utf16_length,
)
from state import ConversationMode, StateStore
from telethon import functions, types


class RenderLivenessTests(unittest.TestCase):
    def test_ping_is_registered_and_does_not_depend_on_telegram_readiness(self) -> None:
        self.assertIn("/ping", {route.path for route in app.routes})
        self.assertEqual(asyncio.run(ping()), {"status": "alive"})

    def test_render_external_url_builds_only_a_safe_ping_url(self) -> None:
        self.assertEqual(render_ping_url("https://tgibot.onrender.com/"), "https://tgibot.onrender.com/ping")
        for invalid in (
            None,
            "http://tgibot.onrender.com",
            "https://user:pass@tgibot.onrender.com",
            "https://tgibot.onrender.com/path",
            "https://tgibot.onrender.com/?token=secret",
            "https://tgibot.onrender.com.attacker.example",
            "https://tgibot.onrender.com:bad-port",
        ):
            with self.subTest(invalid=invalid):
                self.assertIsNone(render_ping_url(invalid))


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
        self.assertEqual(parse_command("/UNMUTE@tgibot", "TGIbot"), Command("unmute", ""))

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


class FakeTelegramClient:
    def __init__(self) -> None:
        self.business_requests = []
        self.exported_dcs = []
        self.connection_requests = []
        self.connection_response = None

    async def __call__(self, request):
        self.connection_requests.append(request)
        return self.connection_response

    async def get_input_entity(self, peer):
        return peer

    async def _borrow_exported_sender(self, dc_id: int):
        self.exported_dcs.append(dc_id)
        return dc_id

    async def _call(self, sender, request):
        self.business_requests.append(request)
        return None

    async def _return_exported_sender(self, sender) -> None:
        return None


class TelegramMuteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = StateStore(Path(self.temp_dir.name) / "mute.sqlite3")
        self.connection_id = "bc-mute-test"
        self.chat_id = 900
        self.store.save_connection(
            self.connection_id,
            owner_id=42,
            dc_id=2,
            enabled=True,
            can_reply=True,
            can_delete_received_messages=True,
        )
        self.client = FakeTelegramClient()
        self.automation = TelegramAutomation(self.client, self.store, ai=None)

    def tearDown(self) -> None:
        self.store.close()
        self.temp_dir.cleanup()

    def update(self, text: str, *, sender_id: int = 900, outgoing: bool = False):
        message = SimpleNamespace(
            id=321,
            peer_id=types.PeerUser(user_id=self.chat_id),
            from_id=types.PeerUser(user_id=sender_id),
            message=text,
            out=outgoing,
            via_bot_id=None,
        )
        return SimpleNamespace(connection_id=self.connection_id, message=message)

    def test_muted_incoming_message_is_deleted_for_both_sides(self) -> None:
        self.store.change_mute(self.connection_id, self.chat_id, True)

        asyncio.run(self.automation._handle_business_message(self.update("Please stop")))

        self.assertEqual(len(self.client.business_requests), 1)
        wrapped = self.client.business_requests[0]
        self.assertEqual(wrapped.connection_id, self.connection_id)
        self.assertIsInstance(wrapped.query, functions.messages.DeleteMessagesRequest)
        self.assertEqual(wrapped.query.id, [321])
        self.assertTrue(wrapped.query.revoke)

    def test_mute_deletion_works_even_without_reply_permission(self) -> None:
        self.store.save_connection(
            self.connection_id,
            owner_id=42,
            dc_id=2,
            enabled=True,
            can_reply=False,
            can_delete_received_messages=True,
        )
        self.store.change_mute(self.connection_id, self.chat_id, True)

        asyncio.run(self.automation._handle_business_message(self.update("")))

        self.assertEqual(len(self.client.business_requests), 1)
        self.assertIsInstance(
            self.client.business_requests[0].query,
            functions.messages.DeleteMessagesRequest,
        )

    def test_unmute_is_processed_before_muted_message_deletion(self) -> None:
        self.store.change_mute(self.connection_id, self.chat_id, True)

        asyncio.run(self.automation._handle_business_message(self.update("/unmute")))

        self.assertFalse(self.store.get_mode(self.connection_id, self.chat_id).mute_enabled)
        self.assertEqual(len(self.client.business_requests), 1)
        self.assertIsInstance(
            self.client.business_requests[0].query,
            functions.messages.SendMessageRequest,
        )
        self.assertIn("Mute is off", self.client.business_requests[0].query.message)

    def test_profile_owner_can_issue_mute_control_but_regular_text_is_ignored(self) -> None:
        asyncio.run(
            self.automation._handle_business_message(
                self.update("/mute", sender_id=42, outgoing=True)
            )
        )
        self.assertTrue(self.store.get_mode(self.connection_id, self.chat_id).mute_enabled)
        self.assertEqual(len(self.client.business_requests), 1)
        self.client.business_requests.clear()

        asyncio.run(
            self.automation._handle_business_message(
                self.update("owner's regular message", sender_id=42, outgoing=True)
            )
        )
        self.assertEqual(self.client.business_requests, [])

    def test_uncached_delete_permission_is_refetched_from_telegram(self) -> None:
        self.store._db.execute(
            "UPDATE business_connections SET can_delete_received_messages = NULL WHERE connection_id = ?",
            (self.connection_id,),
        )
        rights = types.BusinessBotRights(reply=True, delete_received_messages=True)
        connection = types.BotBusinessConnection(
            connection_id=self.connection_id,
            user_id=42,
            dc_id=2,
            date=None,
            disabled=False,
            rights=rights,
        )
        update = types.UpdateBotBusinessConnect(connection=connection, qts=1)
        self.client.connection_response = SimpleNamespace(updates=[update])

        info = asyncio.run(self.automation._get_connection(self.connection_id))

        self.assertIsNotNone(info)
        self.assertTrue(info.can_delete_received_messages)
        self.assertEqual(len(self.client.connection_requests), 1)

    def test_mute_is_not_enabled_without_delete_received_permission(self) -> None:
        self.store.save_connection(
            self.connection_id,
            owner_id=42,
            dc_id=2,
            enabled=True,
            can_reply=True,
            can_delete_received_messages=False,
        )

        asyncio.run(self.automation._handle_business_message(self.update("/mute")))

        self.assertFalse(self.store.get_mode(self.connection_id, self.chat_id).mute_enabled)
        self.assertEqual(len(self.client.business_requests), 1)
        self.assertIsInstance(
            self.client.business_requests[0].query,
            functions.messages.SendMessageRequest,
        )
        self.assertIn("delete received messages", self.client.business_requests[0].query.message.casefold())


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

    def test_mute_mode_persists_without_changing_copy_or_autobot_modes(self) -> None:
        connection_id, chat_id = "bc-mute", 456
        self.store.change_mode(connection_id, chat_id, "copy", True)
        mode = self.store.change_mute(connection_id, chat_id, True)
        self.assertEqual(mode, ConversationMode(copy_enabled=True, mute_enabled=True))

        mode = self.store.change_mute(connection_id, chat_id, False)
        self.assertEqual(mode, ConversationMode(copy_enabled=True, mute_enabled=False))

        self.store.change_mute(connection_id, chat_id, True)
        self.store.close()
        reopened = StateStore(self.db_path)
        try:
            self.assertEqual(
                reopened.get_mode(connection_id, chat_id),
                ConversationMode(copy_enabled=True, mute_enabled=True),
            )
        finally:
            reopened.close()
        self.store = StateStore(self.db_path)

    def test_connection_metadata_round_trips(self) -> None:
        expected = self.store.save_connection(
            "bc-2", 42, 4, True, True, can_delete_received_messages=True
        )
        self.assertEqual(self.store.get_connection("bc-2"), expected)
        self.assertTrue(self.store.get_connection("bc-2").can_delete_received_messages)

    def test_old_sqlite_schema_migrates_mute_and_delete_permission_columns(self) -> None:
        legacy_path = Path(self.temp_dir.name) / "legacy.sqlite3"
        with sqlite3.connect(legacy_path) as db:
            db.executescript(
                """
                CREATE TABLE business_connections (
                    connection_id TEXT PRIMARY KEY,
                    owner_id INTEGER NOT NULL,
                    dc_id INTEGER NOT NULL,
                    enabled INTEGER NOT NULL,
                    can_reply INTEGER NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE conversation_modes (
                    connection_id TEXT NOT NULL,
                    chat_id INTEGER NOT NULL,
                    copy_enabled INTEGER NOT NULL DEFAULT 0,
                    autobot_enabled INTEGER NOT NULL DEFAULT 0,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (connection_id, chat_id),
                    CHECK (copy_enabled = 0 OR autobot_enabled = 0)
                );
                INSERT INTO business_connections VALUES ('bc-old', 42, 2, 1, 1, 1.0);
                INSERT INTO conversation_modes VALUES ('bc-old', 99, 1, 0, 1.0);
                """
            )
        migrated = StateStore(legacy_path)
        try:
            self.assertEqual(
                migrated.get_mode("bc-old", 99),
                ConversationMode(copy_enabled=True, mute_enabled=False),
            )
            old_connection = migrated.get_connection("bc-old")
            self.assertIsNotNone(old_connection)
            self.assertIsNone(old_connection.can_delete_received_messages)
            migrated.change_mute("bc-old", 99, True)
            self.assertTrue(migrated.get_mode("bc-old", 99).mute_enabled)
        finally:
            migrated.close()

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
