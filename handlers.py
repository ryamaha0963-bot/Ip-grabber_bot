import asyncio
import logging
import io
import zipfile
from pyrogram import Client, filters
from pyrogram.types import Message, InlineQuery, InlineQueryResultArticle, InputTextMessageContent, InlineKeyboardButton, InlineKeyboardMarkup
from pyrogram.handlers import MessageHandler, InlineQueryHandler
from pyrogram.errors import FloodWait
from db import (
    add_session, get_session, get_all_sessions, delete_session, clear_sessions,
    export_sessions, approve_user, remove_user, is_approved, get_approved_users
)
from session_manager import SessionManager
from config import Config

logger = logging.getLogger(__name__)

class Handlers:
    def __init__(self, app: Client, manager: SessionManager):
        self.app = app
        self.manager = manager
        self.owner_id = Config.OWNER_ID

        # Register commands
        app.add_handler(MessageHandler(self.cmd_start, filters.command("start")))
        app.add_handler(MessageHandler(self.cmd_help, filters.command("help")))
        app.add_handler(MessageHandler(self.cmd_addsession, filters.command("addsession") & filters.user(self.owner_id)))
        app.add_handler(MessageHandler(self.cmd_delsession, filters.command("delsession") & filters.user(self.owner_id)))
        app.add_handler(MessageHandler(self.cmd_clearsessions, filters.command("clearsessions") & filters.user(self.owner_id)))
        app.add_handler(MessageHandler(self.cmd_exportsessions, filters.command("exportsessions") & filters.user(self.owner_id)))
        app.add_handler(MessageHandler(self.cmd_join, filters.command("join")))
        app.add_handler(MessageHandler(self.cmd_leave, filters.command("leave")))
        app.add_handler(MessageHandler(self.cmd_getip, filters.command("getip")))
        app.add_handler(MessageHandler(self.cmd_approve, filters.command("approve") & filters.user(self.owner_id)))
        app.add_handler(MessageHandler(self.cmd_remove, filters.command("remove") & filters.user(self.owner_id)))
        app.add_handler(MessageHandler(self.cmd_approved, filters.command("approved") & filters.user(self.owner_id)))
        app.add_handler(MessageHandler(self.cmd_restart, filters.command("restart") & filters.user(self.owner_id)))

        # Inline handler
        app.add_handler(InlineQueryHandler(self.inline_query))

        # Document handler for .zip upload
        app.add_handler(MessageHandler(self.handle_document, filters.document & filters.user(self.owner_id)))

    # ---------- COMMANDS ----------
    async def cmd_start(self, client, msg: Message):
        await msg.reply(
            "👋 **IP Grabber Bot**\n"
            "Manage multiple Telegram sessions to extract IPs from voice chats.\n"
            "Use /help for commands."
        )

    async def cmd_help(self, client, msg: Message):
        await msg.reply(
            "**Commands**\n\n"
            "**Sessions:**\n"
            "• /addsession <name> <string> – add a session\n"
            "• /delsession <name> – delete a session\n"
            "• /clearsessions – remove all sessions\n"
            "• /exportsessions – download all sessions as ZIP\n"
            "• Send a .zip file – bulk import sessions (files inside: name.txt with string)\n\n"
            "**Actions:**\n"
            "• /join <session_name|all> <chat_id> – join VC\n"
            "• /leave <session_name|all> <chat_id> – leave VC\n"
            "• /getip <session_name> <chat_id> – extract IPs\n\n"
            "**Owner:**\n"
            "• /approve <user_id|reply> – grant access\n"
            "• /remove <user_id> – revoke\n"
            "• /approved – list approved users\n\n"
            "**Inline:**\n"
            "Type `@YourBot <session> <chat>` to get IPs instantly."
        )

    # ---------- SESSION MANAGEMENT ----------
    async def cmd_addsession(self, client, msg: Message):
        if len(msg.command) < 3:
            await msg.reply("Usage: /addsession <name> <session_string>")
            return
        name = msg.command[1]
        string = msg.command[2]
        # store in db
        await add_session(name, string)
        # start the client
        ok = await self.manager.start_session(name, string)
        if ok:
            await msg.reply(f"✅ Session **{name}** added and started.")
        else:
            await msg.reply(f"❌ Session **{name}** added but failed to start. Check string.")

    async def cmd_delsession(self, client, msg: Message):
        if len(msg.command) < 2:
            await msg.reply("Usage: /delsession <name>")
            return
        name = msg.command[1]
        await self.manager.stop_session(name)
        deleted = await delete_session(name)
        await msg.reply(f"✅ Deleted {name}" if deleted else "❌ Not found")

    async def cmd_clearsessions(self, client, msg: Message):
        await self.manager.stop_all()
        await clear_sessions()
        await msg.reply("✅ All sessions cleared.")

    async def cmd_exportsessions(self, client, msg: Message):
        sessions = await export_sessions()
        if not sessions:
            await msg.reply("No sessions to export.")
            return
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w") as zf:
            for s in sessions:
                zf.writestr(f"{s['name']}.txt", s['string'])
        zip_buffer.seek(0)
        await msg.reply_document(
            document=zip_buffer,
            file_name="sessions.zip",
            caption="📦 All session strings"
        )

    async def handle_document(self, client, msg: Message):
        if not msg.document or not msg.document.file_name.endswith('.zip'):
            await msg.reply("Please send a .zip file.")
            return
        file = await msg.download()
        try:
            with zipfile.ZipFile(file, 'r') as zf:
                count = 0
                for name in zf.namelist():
                    if name.endswith('.txt'):
                        string = zf.read(name).decode('utf-8').strip()
                        session_name = name[:-4]
                        await add_session(session_name, string)
                        await self.manager.start_session(session_name, string)
                        count += 1
            await msg.reply(f"✅ Imported {count} sessions.")
        except Exception as e:
            await msg.reply(f"❌ Failed to import: {e}")

    # ---------- VC ACTIONS ----------
    async def cmd_join(self, client, msg: Message):
        if len(msg.command) < 3:
            await msg.reply("Usage: /join <session_name|all> <chat_id>")
            return
        session_arg = msg.command[1]
        chat_id = msg.command[2]
        if not await self._is_authorized(msg.from_user.id):
            await msg.reply("⛔ You are not approved.")
            return

        if session_arg == "all":
            sessions = await get_all_sessions()
            if not sessions:
                await msg.reply("No sessions.")
                return
            results = []
            for s in sessions:
                res = await self.manager.join_call(s['name'], chat_id)
                results.append(f"{s['name']}: {res}")
            await msg.reply("\n".join(results))
        else:
            res = await self.manager.join_call(session_arg, chat_id)
            await msg.reply(res)

    async def cmd_leave(self, client, msg: Message):
        if len(msg.command) < 3:
            await msg.reply("Usage: /leave <session_name|all> <chat_id>")
            return
        session_arg = msg.command[1]
        chat_id = msg.command[2]
        if not await self._is_authorized(msg.from_user.id):
            await msg.reply("⛔ Not approved.")
            return

        if session_arg == "all":
            sessions = await get_all_sessions()
            results = []
            for s in sessions:
                res = await self.manager.leave_call(s['name'], chat_id)
                results.append(f"{s['name']}: {res}")
            await msg.reply("\n".join(results))
        else:
            res = await self.manager.leave_call(session_arg, chat_id)
            await msg.reply(res)

    async def cmd_getip(self, client, msg: Message):
        if len(msg.command) < 3:
            await msg.reply("Usage: /getip <session_name> <chat_id>")
            return
        session_name = msg.command[1]
        chat_id = msg.command[2]
        if not await self._is_authorized(msg.from_user.id):
            await msg.reply("⛔ Not approved.")
            return
        res = await self.manager.get_ip(session_name, chat_id)
        await msg.reply(res)

    # ---------- INLINE ----------
    async def inline_query(self, client, inline_query: InlineQuery):
        query = inline_query.query.strip()
        if not query:
            return
        parts = query.split()
        if len(parts) < 2:
            return
        session_name = parts[0]
        chat_id = parts[1]
        if not await self._is_authorized(inline_query.from_user.id):
            result = InlineQueryResultArticle(
                id="unauth",
                title="⛔ Not approved",
                input_message_content=InputTextMessageContent("You are not approved to use this bot.")
            )
            await inline_query.answer([result], cache_time=1)
            return
        # Get IP
        ip_result = await self.manager.get_ip(session_name, chat_id)
        # Add a button to copy? We'll keep it as text.
        result = InlineQueryResultArticle(
            id="ip",
            title=f"IPs for {session_name} in {chat_id}",
            input_message_content=InputTextMessageContent(ip_result),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📋 Copy", switch_inline_query_current_chat="")]  # optional placeholder
            ])
        )
        await inline_query.answer([result], cache_time=10)

    # ---------- OWNER COMMANDS ----------
    async def cmd_approve(self, client, msg: Message):
        user_id = None
        if msg.reply_to_message:
            user_id = msg.reply_to_message.from_user.id
        elif len(msg.command) > 1:
            user_id = int(msg.command[1])
        if not user_id:
            await msg.reply("Reply to a user or provide user_id")
            return
        await approve_user(user_id)
        await msg.reply(f"✅ User {user_id} approved.")

    async def cmd_remove(self, client, msg: Message):
        if len(msg.command) < 2:
            await msg.reply("Usage: /remove <user_id>")
            return
        user_id = int(msg.command[1])
        await remove_user(user_id)
        await msg.reply(f"✅ User {user_id} removed.")

    async def cmd_approved(self, client, msg: Message):
        users = await get_approved_users()
        if not users:
            await msg.reply("No approved users.")
        else:
            await msg.reply("Approved users:\n" + "\n".join(str(u) for u in users))

    async def cmd_restart(self, client, msg: Message):
        await msg.reply("🔄 Restarting...")
        # Stop all sessions, then reinitialize from DB
        await self.manager.stop_all()
        sessions = await get_all_sessions()
        for s in sessions:
            await self.manager.start_session(s['name'], s['string'])
        await msg.reply(f"✅ Restarted {len(sessions)} sessions.")

    # ---------- UTILITY ----------
    async def _is_authorized(self, user_id: int) -> bool:
        if user_id == self.owner_id:
            return True
        return await is_approved(user_id)
