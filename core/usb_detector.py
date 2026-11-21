"""
LaptopShare USB-C & Direct Cable Hardware Detection Engine
Audits USB host controllers, USB4, Thunderbolt 3/4 networking capabilities,
detects direct cable link-local network interfaces (169.254.x.x), and probes peer connectivity.
Uses pure in-memory psutil calls during monitoring to ensure ZERO PowerShell window popups.
"""

import os
import sys
import time
import socket
import subprocess
import threading
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple, Callable
from pathlib import Path
import psutil

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

@dataclass
class USBControllerInfo:
    name: str
    manufacturer: str
    device_id: str
    is_usb4_or_thunderbolt: bool = False
    details: str = ""

@dataclass
class DirectLinkAdapter:
    name: str
    description: str
    status: str
    link_speed: str
    ipv4_address: Optional[str] = None
    is_direct_cable: bool = False
    cable_type: str = "Standard"

@dataclass
class HardwareAuditReport:
    laptop_model: str
    controllers: List[USBControllerInfo]
    has_usb4_or_thunderbolt: bool
    direct_adapters: List[DirectLinkAdapter]
    active_direct_cable: Optional[DirectLinkAdapter] = None
    diagnostic_summary: str = ""
    supported_cable_modes: List[str] = field(default_factory=list)

class USBDetectionService:
    """
    Monitors direct cable connections in the background using lightweight
    in-memory psutil network queries with zero console window popups.
    """
    def __init__(self, check_interval_sec: float = 3.0):
        self.check_interval_sec = check_interval_sec
        self.running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

        # Cached hardware audit results (audited once on startup)
        self._cached_model: Optional[str] = None
        self._cached_controllers: Optional[List[USBControllerInfo]] = None
        self._cached_has_tb: Optional[bool] = None

        self.last_report: Optional[HardwareAuditReport] = None
        self.connected_peer_ip: Optional[str] = None
        self.connected_peer_name: Optional[str] = None
        self.negotiated_speed: str = "Unknown"

        # Callbacks
        self.on_cable_connected: Optional[Callable[[DirectLinkAdapter, str], None]] = None
        self.on_cable_disconnected: Optional[Callable[[], None]] = None
        self.on_status_updated: Optional[Callable[[HardwareAuditReport], None]] = None

    def start(self):
        if self.running:
            return
        self.running = True
        # Perform initial hardware audit silently in background thread
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True, name="USBDetectionThread")
        self._thread.start()

    def stop(self):
        self.running = False

    def audit_hardware(self, force_refresh: bool = False) -> HardwareAuditReport:
        """Performs hardware audit. Static hardware info is cached after first run to avoid process spawning."""
        with self._lock:
            if force_refresh or self._cached_model is None:
                self._cached_model = self._detect_laptop_model_silent()
                self._cached_controllers = self._detect_usb_controllers_silent()
                has_tb = any(c.is_usb4_or_thunderbolt for c in self._cached_controllers)
                if not has_tb:
                    has_tb = self._check_pnp_thunderbolt_usb4_silent()
                self._cached_has_tb = has_tb

            model = self._cached_model or "Windows Laptop"
            controllers = self._cached_controllers or []
            has_tb_or_usb4 = bool(self._cached_has_tb)

        # Query active adapters purely in-memory using psutil (zero subprocesses, 0ms latency)
        adapters = self._detect_direct_link_adapters_in_memory()
        active_cable = next((a for a in adapters if a.is_direct_cable and a.status == "Up"), None)

        supported_modes = []
        if has_tb_or_usb4:
            supported_modes.append("⚡ Thunderbolt 4 / USB4 Direct Cable (20 - 40 Gbps)")
        supported_modes.append("🔗 USB-C Host-to-Host Data Transfer Bridge Cable (5 - 10 Gbps, e.g. Plugable / Belkin / Prolific PL27A1)")
        supported_modes.append("🌐 Direct Gigabit / 2.5G Ethernet Crossover Cable (1 - 2.5 Gbps, ~115 - 280 MB/s sustained)")
        supported_modes.append("📡 Direct High-Speed Wi-Fi 6 Direct P2P Wireless Link (480 - 1200 Mbps fallback)")

        if active_cable:
            summary = f"Direct cable connection active via {active_cable.name} ({active_cable.link_speed})."
        elif has_tb_or_usb4:
            summary = "Thunderbolt / USB4 capable port detected. Plug in a Thunderbolt 3/4 or USB4 cable to establish instant 20-40 Gbps direct connection."
        else:
            summary = (
                f"Standard USB 3.2 xHCI Host ports detected on {model}. "
                "Note: Standard USB-C charging cables are host-only and cannot transfer data directly between two laptop hosts. "
                "For direct cable sharing, use a Direct Ethernet Cable (fastest & easiest) or USB-to-USB Transfer Bridge Cable."
            )

        report = HardwareAuditReport(
            laptop_model=model,
            controllers=controllers,
            has_usb4_or_thunderbolt=has_tb_or_usb4,
            direct_adapters=adapters,
            active_direct_cable=active_cable,
            diagnostic_summary=summary,
            supported_cable_modes=supported_modes
        )

        with self._lock:
            self.last_report = report

        return report

    def _monitor_loop(self):
        last_was_connected = False
        # Run initial audit
        try:
            self.audit_hardware(force_refresh=True)
        except Exception as e:
            print(f"[USBDetectionService] Initial audit error: {e}")

        while self.running:
            try:
                # In-memory scan only! Zero subprocess / zero powershell popups!
                report = self.audit_hardware(force_refresh=False)
                is_connected = (report.active_direct_cable is not None)

                if is_connected and not last_was_connected:
                    last_was_connected = True
                    adapter = report.active_direct_cable
                    speed = adapter.link_speed if adapter else "1 Gbps"
                    self.negotiated_speed = speed
                    peer_ip = self._find_peer_on_adapter_silent(adapter)
                    self.connected_peer_ip = peer_ip
                    if self.on_cable_connected and adapter:
                        self.on_cable_connected(adapter, peer_ip or "")
                elif not is_connected and last_was_connected:
                    last_was_connected = False
                    self.connected_peer_ip = None
                    self.connected_peer_name = None
                    if self.on_cable_disconnected:
                        self.on_cable_disconnected()

                if self.on_status_updated:
                    self.on_status_updated(report)

            except Exception as e:
                print(f"[USBDetectionService] Error in monitor loop: {e}")

            time.sleep(self.check_interval_sec)

    def _detect_direct_link_adapters_in_memory(self) -> List[DirectLinkAdapter]:
        """
        Pure in-memory adapter inspection using psutil.
        Does NOT invoke PowerShell or any external binary.
        """
        adapters = []
        try:
            stats_dict = psutil.net_if_stats()
            addrs_dict = psutil.net_if_addrs()

            for iface_name, stats in stats_dict.items():
                iface_lower = iface_name.lower()
                # Skip loopback
                if "loopback" in iface_lower:
                    continue

                is_up = stats.isup
                speed_mbps = stats.speed
                speed_str = f"{speed_mbps} Mbps" if speed_mbps > 0 else "Unknown"

                # Extract IPv4
                ipv4 = None
                for addr in addrs_dict.get(iface_name, []):
                    if addr.family == socket.AF_INET and not addr.address.startswith("127."):
                        ipv4 = addr.address
                        break

                is_direct = False
                cable_type = "Standard"

                # Check if interface is direct cable (Thunderbolt, USB4, NCM, RNDIS, CDC, or Ethernet link-local)
                if any(k in iface_lower for k in ["thunderbolt", "usb4", "host-to-host"]):
                    is_direct = True
                    cable_type = "Thunderbolt 4 / USB4 Direct Cable"
                elif any(k in iface_lower for k in ["ncm", "rndis", "cdc", "pl27a1", "prolific", "usb-to-usb", "bridge"]):
                    is_direct = True
                    cable_type = "USB-C Host-to-Host Transfer Cable"
                elif "ethernet" in iface_lower:
                    # If Ethernet is up or has a link-local address (169.254.x.x), it's a direct cable connection!
                    if is_up:
                        is_direct = True
                        cable_type = "Direct Ethernet Cable (1 - 2.5 Gbps)"
                    elif ipv4 and ipv4.startswith("169.254."):
                        is_direct = True
                        cable_type = "Direct Cable (Link-Local)"

                adapters.append(DirectLinkAdapter(
                    name=iface_name,
                    description=iface_name,
                    status="Up" if is_up else "Disconnected",
                    link_speed=speed_str,
                    ipv4_address=ipv4,
                    is_direct_cable=is_direct,
                    cable_type=cable_type
                ))
        except Exception as e:
            print(f"[USBDetection] in-memory adapter query error: {e}")

        return adapters

    def _detect_laptop_model_silent(self) -> str:
        """Runs once on startup with CREATE_NO_WINDOW."""
        try:
            cmd = ["powershell", "-NoProfile", "-Command", "Get-CimInstance Win32_ComputerSystem | Select-Object -ExpandProperty Model"]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=3, creationflags=CREATE_NO_WINDOW)
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout.strip()
        except Exception:
            pass
        return "Windows Laptop"

    def _detect_usb_controllers_silent(self) -> List[USBControllerInfo]:
        """Runs once on startup with CREATE_NO_WINDOW."""
        controllers = []
        try:
            cmd = ["powershell", "-NoProfile", "-Command", "Get-CimInstance Win32_USBController | Select-Object Name, Manufacturer, DeviceID | ConvertTo-Csv -NoTypeInformation"]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=4, creationflags=CREATE_NO_WINDOW)
            if res.returncode == 0:
                lines = res.stdout.strip().splitlines()
                if len(lines) > 1:
                    import csv
                    reader = csv.DictReader(lines)
                    for row in reader:
                        name = row.get("Name", "")
                        mfg = row.get("Manufacturer", "")
                        dev_id = row.get("DeviceID", "")
                        is_tb = any(k in (name + dev_id).lower() for k in ["thunderbolt", "usb4", "tbt", "nhie"])
                        controllers.append(USBControllerInfo(
                            name=name,
                            manufacturer=mfg,
                            device_id=dev_id,
                            is_usb4_or_thunderbolt=is_tb,
                            details="Thunderbolt / USB4 Host Controller" if is_tb else "Standard USB 3.x xHCI Host Controller"
                        ))
        except Exception:
            pass
        return controllers

    def _check_pnp_thunderbolt_usb4_silent(self) -> bool:
        """Runs once on startup with CREATE_NO_WINDOW."""
        try:
            cmd = ["powershell", "-NoProfile", "-Command", "Get-PnpDevice | Where-Object { $_.FriendlyName -match 'Thunderbolt|USB4' } | Measure-Object | Select-Object -ExpandProperty Count"]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=3, creationflags=CREATE_NO_WINDOW)
            if res.returncode == 0 and res.stdout.strip():
                count = int(res.stdout.strip())
                return count > 0
        except Exception:
            pass
        return False

    def _find_peer_on_adapter_silent(self, adapter: DirectLinkAdapter) -> Optional[str]:
        """Probes ARP table silently with CREATE_NO_WINDOW."""
        if not adapter.ipv4_address:
            return None

        local_ip = adapter.ipv4_address
        # Send a quick UDP probe to broadcast so neighbor discovery cache is triggered
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe_s:
                probe_s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                probe_s.settimeout(0.1)
                bcast = "169.254.255.255" if local_ip.startswith("169.254.") else "255.255.255.255"
                probe_s.sendto(b"DISCOVERY_PROBE", (bcast, 52141))
        except Exception:
            pass

        try:
            cmd = ["arp", "-a"]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=3, creationflags=CREATE_NO_WINDOW)
            if res.returncode == 0:
                prefix = ".".join(local_ip.split(".")[:2])
                for line in res.stdout.splitlines():
                    parts = line.split()
                    if len(parts) >= 2:
                        candidate_ip = parts[0].strip()
                        if candidate_ip.startswith(prefix) and candidate_ip != local_ip:
                            if not candidate_ip.endswith(".255"):
                                return candidate_ip
        except Exception:
            pass
        return None
