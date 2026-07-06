import asyncio
import logging
from typing import Optional, Dict, List
from pyrogram import Client
from pyrogram.raw import functions, types
from pyrogram.errors import RPCError
from config import Config

logger = logging.getLogger(__name__)

class SessionManager:
    def __init__(self):
        self.clients: Dict[str, Client] = {}   # name -> Client
        self._lock = asyncio.Lock()

    async def start_session(self, name: str, string: str) -> bool:
        async with self._lock:
            if name in self.clients:
                return False
            client = Client(
                name,
                api_id=Config.API_ID,
                api_hash=Config.API_HASH,
                session_string=string,
                in_memory=True,
            )
            try:
                await client.start()
                self.clients[name] = client
                logger.info(f"Session {name} started")
                return True
            except Exception as e:
                logger.error(f"Failed to start {name}: {e}")
                return False

    async def stop_session(self, name: str):
        async with self._lock:
            client = self.clients.pop(name, None)
            if client:
                await client.stop()
                logger.info(f"Session {name} stopped")

    async def stop_all(self):
        async with self._lock:
            for name, client in list(self.clients.items()):
                await client.stop()
            self.clients.clear()

    async def get_client(self, name: str) -> Optional[Client]:
        return self.clients.get(name)

    async def get_me(self, name: str) -> Optional[dict]:
        client = await self.get_client(name)
        if client:
            try:
                me = await client.get_me()
                return {"id": me.id, "username": me.username, "first_name": me.first_name}
            except:
                pass
        return None

    # ---------- VC ACTIONS ----------
    async def join_call(self, name: str, chat_id: int) -> str:
        client = await self.get_client(name)
        if not client:
            return "❌ Session not active"
        try:
            peer = await client.resolve_peer(chat_id)
            # Get full chat to get call
            if isinstance(peer, types.InputPeerChannel):
                full = await client.invoke(functions.channels.GetFullChannel(
                    channel=types.InputChannel(peer.channel_id, peer.access_hash)
                ))
            elif isinstance(peer, types.InputPeerChat):
                full = await client.invoke(functions.messages.GetFullChat(chat_id=peer.chat_id))
            else:
                return "❌ Unsupported chat type"

            call = getattr(full.full_chat, "call", None)
            if not call:
                return "❌ No active voice chat"

            # Join
            await client.invoke(functions.phone.JoinGroupCall(
                call=types.InputGroupCall(call.id, call.access_hash),
                join_as=await client.resolve_peer('me'),
                params=types.DataJSON(data='{"ufrag":"x","pwd":"y","fingerprints":[],"ssrc":1}'),
                muted=True, video_stopped=True
            ))
            return f"✅ Joined VC in chat {chat_id} using {name}"
        except RPCError as e:
            return f"❌ RPC error: {e}"
        except Exception as e:
            return f"❌ Error: {e}"

    async def leave_call(self, name: str, chat_id: int) -> str:
        client = await self.get_client(name)
        if not client:
            return "❌ Session not active"
        try:
            peer = await client.resolve_peer(chat_id)
            # get call
            if isinstance(peer, types.InputPeerChannel):
                full = await client.invoke(functions.channels.GetFullChannel(
                    channel=types.InputChannel(peer.channel_id, peer.access_hash)
                ))
            else:
                full = await client.invoke(functions.messages.GetFullChat(chat_id=peer.chat_id))
            call = getattr(full.full_chat, "call", None)
            if not call:
                return "❌ No active voice chat"
            await client.invoke(functions.phone.LeaveGroupCall(
                call=types.InputGroupCall(call.id, call.access_hash),
                source=0
            ))
            return f"✅ Left VC in chat {chat_id} using {name}"
        except Exception as e:
            return f"❌ Error: {e}"

    async def get_ip(self, name: str, chat_id: int) -> str:
        client = await self.get_client(name)
        if not client:
            return "❌ Session not active"
        try:
            peer = await client.resolve_peer(chat_id)
            if isinstance(peer, types.InputPeerChannel):
                full = await client.invoke(functions.channels.GetFullChannel(
                    channel=types.InputChannel(peer.channel_id, peer.access_hash)
                ))
            else:
                full = await client.invoke(functions.messages.GetFullChat(chat_id=peer.chat_id))
            call = getattr(full.full_chat, "call", None)
            if not call:
                return "❌ No active voice chat"
            # Get group call details
            group_call = await client.invoke(functions.phone.GetGroupCall(
                call=types.InputGroupCall(call.id, call.access_hash),
                limit=200
            ))
            # Extract IPs from participants' video/audio streams
            ips = set()
            for participant in group_call.participants:
                # various fields where IP can appear
                for attr in ['video_source', 'audio_source']:
                    source = getattr(participant, attr, None)
                    if source:
                        # not direct, but we can get from call participants
                        pass
            # Alternatively, parse the call params
            params = getattr(call, "params", None)
            if params and hasattr(params, "data"):
                import json
                data = json.loads(params.data)
                # look for endpoints
                endpoints = data.get("endpoints", [])
                for ep in endpoints:
                    if isinstance(ep, str) and ":" in ep:
                        ip = ep.split(":")[0]
                        if ip.replace('.', '').isdigit():
                            ips.add(ip)
                # also check servers
                servers = data.get("servers", [])
                for srv in servers:
                    if isinstance(srv, dict):
                        ip = srv.get("ip") or srv.get("host")
                        if ip and isinstance(ip, str) and ip.replace('.', '').isdigit():
                            ips.add(ip)
            if not ips:
                return "⚠️ No IPs found (maybe no participants)"
            return "📡 IPs: " + ", ".join(ips)
        except Exception as e:
            return f"❌ Error: {e}"
