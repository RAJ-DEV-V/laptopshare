"""
LaptopShare Peer Discovery
Implements UDP broadcast discovery and direct unicast discovery pings.
"""

import json
import time
import socket
import threading
import uuid
from typing import Dict, List, Callable, Optional
from dataclasses import dataclass

from .config import ConfigManager, DEFAULT_DISCOVERY_PORT, DEFAULT_TRANSFER_PORT
from .network_utils import get_local_ip_addresses, get_primary_ip

DISCOVERY_MAGIC = "LAPTOPSHARE_BEACON"

@dataclass
class PeerDevice:
    device_id: str
    device_name: str
    ip: str
    port: int
    os_name: str
    last_seen: float

    def to_dict(self) -> dict:
        return {
            "device_id": self.device_id,
            "device_name": self.device_name,
            "ip": self.ip,
            "port": self.port,
            "os_name": self.os_name,
            "last_seen": self.last_seen,
        }

class DiscoveryService:
    def __init__(self, port: int = DEFAULT_DISCOVERY_PORT):
        self.port = port
        self.device_id = str(uuid.uuid4())
        self.running = False
        self._lock = threading.Lock()
        self.peers: Dict[str, PeerDevice] = {}  # key: device_id
        self.on_peers_updated: Optional[Callable[[List[PeerDevice]], None]] = None

        self._broadcast_thread: Optional[threading.Thread] = None
        self._listen_thread: Optional[threading.Thread] = None

    def start(self):
        """Starts discovery broadcasting and listening."""
        if self.running:
            return
        self.running = True

        self._listen_thread = threading.Thread(target=self._listen_loop, daemon=True, name="DiscoveryListener")
        self._listen_thread.start()

        self._broadcast_thread = threading.Thread(target=self._broadcast_loop, daemon=True, name="DiscoveryBroadcaster")
        self._broadcast_thread.start()

    def stop(self):
        """Stops discovery service."""
        self.running = False

    def _get_beacon_payload(self) -> bytes:
        cfg = ConfigManager().get()
        data = {
            "magic": DISCOVERY_MAGIC,
            "device_id": self.device_id,
            "device_name": cfg.device_name,
            "ip": get_primary_ip(),
            "port": cfg.transfer_port,
            "os_name": "Windows",
            "timestamp": time.time(),
        }
        return json.dumps(data).encode("utf-8")

    def _broadcast_loop(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.settimeout(1.0)

        while self.running:
            try:
                payload = self._get_beacon_payload()
                # Broadcast on standard 255.255.255.255
                sock.sendto(payload, ("255.255.255.255", self.port))

                # Also broadcast on subnet-specific broadcast if identifiable
                for iface in get_local_ip_addresses():
                    ip = iface["ip"]
                    if not ip.startswith("127."):
                        parts = ip.split(".")
                        if len(parts) == 4:
                            subnet_bcast = f"{parts[0]}.{parts[1]}.{parts[2]}.255"
                            try:
                                sock.sendto(payload, (subnet_bcast, self.port))
                            except Exception:
                                pass
            except Exception:
                pass

            # Prune stale devices
            self._prune_peers()

            # Sleep 2.5 seconds between beacons
            for _ in range(25):
                if not self.running:
                    break
                time.sleep(0.1)

        sock.close()

    def _listen_loop(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("", self.port))
        except Exception as e:
            print(f"[Discovery] Could not bind listener socket to port {self.port}: {e}")
            sock.close()
            return

        sock.settimeout(1.0)

        while self.running:
            try:
                data, addr = sock.recvfrom(4096)
                if not data:
                    continue
                try:
                    msg = json.loads(data.decode("utf-8"))
                except Exception:
                    continue

                if msg.get("magic") != DISCOVERY_MAGIC:
                    continue

                peer_id = msg.get("device_id")
                # Ignore self
                if peer_id == self.device_id:
                    continue

                peer_ip = addr[0]
                peer_port = msg.get("port", DEFAULT_TRANSFER_PORT)
                peer_name = msg.get("device_name", "Unknown Laptop")
                os_name = msg.get("os_name", "Windows")

                peer = PeerDevice(
                    device_id=peer_id,
                    device_name=peer_name,
                    ip=peer_ip,
                    port=peer_port,
                    os_name=os_name,
                    last_seen=time.time(),
                )

                updated = False
                with self._lock:
                    if peer_id not in self.peers or self.peers[peer_id].ip != peer_ip or self.peers[peer_id].device_name != peer_name:
                        updated = True
                    self.peers[peer_id] = peer

                if updated and self.on_peers_updated:
                    self._notify_update()

            except socket.timeout:
                continue
            except Exception:
                pass

        sock.close()

    def _prune_peers(self):
        now = time.time()
        removed = False
        with self._lock:
            stale_keys = [k for k, p in self.peers.items() if now - p.last_seen > 8.0]
            for k in stale_keys:
                del self.peers[k]
                removed = True

        if removed and self.on_peers_updated:
            self._notify_update()

    def _notify_update(self):
        with self._lock:
            current_list = list(self.peers.values())
        if self.on_peers_updated:
            try:
                self.on_peers_updated(current_list)
            except Exception as e:
                print(f"[Discovery] Error invoking peer update callback: {e}")

    def get_peers(self) -> List[PeerDevice]:
        with self._lock:
            return list(self.peers.values())

    def direct_probe(self, ip: str, port: int = DEFAULT_DISCOVERY_PORT) -> bool:
        """Sends a direct unicast discovery beacon to a specific IP."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            payload = self._get_beacon_payload()
            sock.sendto(payload, (ip, port))
            sock.close()
            return True
        except Exception:
            return False
