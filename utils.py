from __future__ import annotations
import ipaddress, socket, re

def human_bytes(b: int) -> str:
    for unit in ["B","KB","MB","GB"]:
        if b < 1024.0: return f"{b:.1f} {unit}"
        b /= 1024.0
    return f"{b:.1f} TB"

def is_valid_port(p: int) -> bool: return 1 <= p <= 65535

def is_private_or_loopback(ip: str) -> bool:
    try:
        ip_obj = ipaddress.ip_address(ip)
        return ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_link_local or ip_obj.is_reserved
    except: return False

def resolve(host: str) -> str | None:
    try: return socket.gethostbyname(host)
    except: return None

IPV4_RE = re.compile(r'\b(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\b')
