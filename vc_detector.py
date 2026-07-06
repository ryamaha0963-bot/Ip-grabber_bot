from __future__ import annotations
import asyncio, json, logging, re, time, socket, ipaddress
from dataclasses import dataclass
from pyrogram import Client
from pyrogram.errors import FloodWait, ChatAdminRequired, UserAlreadyParticipant
from pyrogram.raw import functions, types
from utils import IPV4_RE

LOGGER = logging.getLogger(__name__)

@dataclass
class VCRecord:
    dialog_id: int; title: str; peer: any; call: any; chat_id: int

class VCDetector:
    def __init__(self, client: Client, cooldown: int = 5):
        self.client = client
        self.cooldown = cooldown
        self._last = 0.0

    async def scan(self, limit: int = 50) -> list[VCRecord]:
        now = time.time()
        if now - self._last < self.cooldown:
            await asyncio.sleep(self.cooldown - (now - self._last))
        self._last = time.time()
        results = []
        async for dialog in self.client.get_dialogs(limit=limit):
            chat = dialog.chat
            try:
                peer = await self.client.resolve_peer(chat.id)
                call = await self._get_call(peer)
                if call:
                    results.append(VCRecord(chat.id, chat.title or str(chat.id), peer, call, chat.id))
            except FloodWait as e:
                await asyncio.sleep(e.value + 1)
            except Exception:
                pass
        return results

    async def _get_call(self, peer):
        if isinstance(peer, types.InputPeerChannel):
            full = await self.client.invoke(functions.channels.GetFullChannel(
                channel=types.InputChannel(peer.channel_id, peer.access_hash)))
            return getattr(full.full_chat, "call", None)
        if isinstance(peer, types.InputPeerChat):
            full = await self.client.invoke(functions.messages.GetFullChat(chat_id=peer.chat_id))
            return getattr(full.full_chat, "call", None)
        return None

    async def extract(self, record: VCRecord) -> dict:
        joined = False
        notice = None
        parsed = {}
        for attempt in range(3):
            try:
                me = await self.client.resolve_peer('me')
                call_params = getattr(record.call, "params", None)
                if not call_params:
                    call_params = types.DataJSON(data=json.dumps({"ufrag":"x","pwd":"y","fingerprints":[],"ssrc":1}))
                    notice = "Fallback params"
                await self.client.invoke(functions.phone.JoinGroupCall(
                    call=types.InputGroupCall(record.call.id, record.call.access_hash),
                    join_as=me,
                    params=call_params,
                    muted=True, video_stopped=True
                ))
                joined = True
                await asyncio.sleep(1.5)
                break
            except UserAlreadyParticipant:
                joined = True
                break
            except FloodWait as e:
                await asyncio.sleep(e.value + 1)
            except Exception as e:
                notice = f"Join failed: {e}"
                break

        try:
            group = await self.client.invoke(functions.phone.GetGroupCall(
                call=types.InputGroupCall(record.call.id, record.call.access_hash),
                limit=200
            ))
            call_obj = group.call
            raw = getattr(call_obj, "params", None)
            data = getattr(raw, "data", "{}") if raw else "{}"
            parsed = json.loads(data) if data else {}
        except Exception as e:
            notice = (notice or "") + f" GetGroupCall error: {e}"

        all_text = json.dumps(parsed) + str(record.call)
        ips = set()
        for ip in IPV4_RE.findall(all_text):
            if ip not in ips:
                ips.add(ip)
        for ep in parsed.get("endpoints", []):
            if isinstance(ep, str) and ":" in ep:
                parts = ep.rsplit(":",1)
                if len(parts)==2 and parts[0].replace('.','').isdigit():
                    ips.add(parts[0])
        for srv in parsed.get("servers", []):
            if isinstance(srv, dict):
                ip = srv.get("ip") or srv.get("host")
                if ip and isinstance(ip, str):
                    ips.add(ip)

        ip_list = []
        for ip in ips:
            if ip and not ip.startswith("0.") and not ip.startswith("127."):
                ip_list.append({"ip": ip, "port": 0, "type": "auto", "region": "unknown", "source": "regex"})
        for i in ip_list:
            i["port"] = 10001 if i["port"] == 0 else i["port"]

        return {
            "title": record.title,
            "call_id": record.call.id,
            "chat_id": record.chat_id,
            "joined": joined,
            "notice": notice,
            "extracted_ips": ip_list,
            "participants": len(getattr(group, "participants", [])) if 'group' in locals() else 0
        }

    async def leave(self, record: VCRecord):
        try:
            await self.client.invoke(functions.phone.LeaveGroupCall(
                call=types.InputGroupCall(record.call.id, record.call.access_hash),
                source=0
            ))
        except Exception:
            pass
