"""
LaptopShare USB-C & Direct Cable Hardware Detection Engine
Audits USB host controllers, USB4, Thunderbolt 3/4 networking capabilities,
detects direct cable link-local network interfaces (169.254.x.x), and probes peer connectivity.
"""

import os
import sys
import time
import socket
import subprocess
import threading
import ipaddress
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple, Callable
from pathlib import Path

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
    Monitors USB hardware, Thunderbolt / USB4 network adapters,
    and direct cable connections in the background.
    """
    def __init__(self, check_interval_sec: float = 2.0):
        self.check_interval_sec = check_interval_sec
        self.running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

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
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True, name="USBDetectionThread")
        self._thread.start()

    def stop(self):
        self.running = False

    def audit_hardware(self) -> HardwareAuditReport:
        """Performs a comprehensive audit of USB controllers, USB4, Thunderbolt, and network adapters."""
        model = self._detect_laptop_model()
        controllers = self._detect_usb_controllers()
        has_tb_or_usb4 = any(c.is_usb4_or_thunderbolt for c in controllers)

        # Check PnP entities specifically for Thunderbolt or USB4 drivers
        if not has_tb_or_usb4:
            has_tb_or_usb4 = self._check_pnp_thunderbolt_usb4()

        adapters = self._detect_direct_link_adapters()
        active_cable = next((a for a in adapters if a.is_direct_cable and a.status == "Up"), None)

        supported_modes = []
        if has_tb_or_usb4:
            supported_modes.append("⚡ Thunderbolt 4 / USB4 Direct Cable (20 - 40 Gbps)")
        supported_modes.append("🔗 USB-C Host-to-Host Data Transfer Bridge Cable (5 - 10 Gbps, e.g. Plugable / Belkin / Prolific PL27A1)")
        supported_modes.append("🌐 USB-C to Gigabit/2.5G Ethernet Direct Crossover Link (1 - 2.5 Gbps)")
        supported_modes.append("📡 Direct High-Speed Wi-Fi 6 Direct P2P Wireless Link (480 - 1200 Mbps fallback)")

        if active_cable:
            summary = f"Direct cable connection active via {active_cable.description} ({active_cable.link_speed})."
        elif has_tb_or_usb4:
            summary = "Thunderbolt / USB4 capable port detected. Plug in a Thunderbolt 3/4 or USB4 cable to establish instant 20-40 Gbps direct connection."
        else:
            summary = (
                "Standard USB 3.2 xHCI Host ports detected. Note: Standard USB-C charging cables cannot connect two host "
                "controllers directly without a USB-C Host-to-Host Transfer Bridge Cable (e.g. Belkin/Plugable/Prolific) "
                "or USB-Ethernet crossover link. High-speed direct fallback is available."
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
        while self.running:
            try:
                report = self.audit_hardware()
                is_connected = (report.active_direct_cable is not None)

                if is_connected and not last_was_connected:
                    last_was_connected = True
                    adapter = report.active_direct_cable
                    speed = adapter.link_speed if adapter else "10 Gbps"
                    self.negotiated_speed = speed
                    # Attempt peer detection on direct link
                    peer_ip = self._find_peer_on_adapter(adapter)
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

    def _detect_laptop_model(self) -> str:
        try:
            cmd = ["powershell", "-NoProfile", "-Command", "Get-CimInstance Win32_ComputerSystem | Select-Object -ExpandProperty Model"]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout.strip()
        except Exception:
            pass
        return "Windows Laptop"

    def _detect_usb_controllers(self) -> List[USBControllerInfo]:
        controllers = []
        try:
            cmd = ["powershell", "-NoProfile", "-Command", "Get-CimInstance Win32_USBController | Select-Object Name, Manufacturer, DeviceID | ConvertTo-Csv -NoTypeInformation"]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=4)
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
        except Exception as e:
            print(f"[USBDetection] USB Controller query error: {e}")
        return controllers

    def _check_pnp_thunderbolt_usb4(self) -> bool:
        try:
            cmd = ["powershell", "-NoProfile", "-Command", "Get-PnpDevice | Where-Object { $_.FriendlyName -match 'Thunderbolt|USB4' } | Measure-Object | Select-Object -ExpandProperty Count"]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
            if res.returncode == 0 and res.stdout.strip():
                count = int(res.stdout.strip())
                return count > 0
        except Exception:
            pass
        return False

    def _detect_direct_link_adapters(self) -> List[DirectLinkAdapter]:
        adapters = []
        try:
            cmd = [
                "powershell", "-NoProfile", "-Command",
                "Get-NetAdapter | Select-Object Name, InterfaceDescription, LinkSpeed, Status | ConvertTo-Csv -NoTypeInformation"
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=4)
            if res.returncode == 0:
                lines = res.stdout.strip().splitlines()
                if len(lines) > 1:
                    import csv
                    reader = csv.DictReader(lines)
                    for row in reader:
                        name = row.get("Name", "")
                        desc = row.get("InterfaceDescription", "")
                        speed = row.get("LinkSpeed", "Unknown")
                        status = row.get("Status", "Unknown")

                        desc_lower = desc.lower()
                        name_lower = name.lower()

                        is_direct = False
                        cable_type = "Standard"

                        if any(k in desc_lower for k in ["thunderbolt", "usb4", "host-to-host"]):
                            is_direct = True
                            cable_type = "Thunderbolt 4 / USB4 Direct Cable"
                        elif any(k in desc_lower for k in ["ncm", "rndis", "cdc", "pl27a1", "prolific", "usb-to-usb", "bridge"]):
                            is_direct = True
                            cable_type = "USB-C Host-to-Host Transfer Cable"
                        elif "ethernet" in name_lower and any(k in desc_lower for k in ["usb", "realtek usb", "asix"]):
                            is_direct = True
                            cable_type = "USB-C Ethernet Direct Crossover"

                        # Retrieve IP for this adapter if Up
                        ip_addr = None
                        if status == "Up":
                            ip_addr = self._get_adapter_ipv4(name)
                            # If IP is APIPA (169.254.x.x) and not Wi-Fi, it is almost certainly a direct link-local cable!
                            if ip_addr and ip_addr.startswith("169.254.") and "wi-fi" not in desc_lower and "wireless" not in desc_lower:
                                is_direct = True
                                cable_type = cable_type if cable_type != "Standard" else "Direct Link-Local Cable"

                        adapters.append(DirectLinkAdapter(
                            name=name,
                            description=desc,
                            status=status,
                            link_speed=speed,
                            ipv4_address=ip_addr,
                            is_direct_cable=is_direct,
                            cable_type=cable_type
                        ))
        except Exception as e:
            print(f"[USBDetection] Adapter query error: {e}")
        return adapters

    def _get_adapter_ipv4(self, adapter_name: str) -> Optional[str]:
        try:
            cmd = [
                "powershell", "-NoProfile", "-Command",
                f"(Get-NetIPAddress -InterfaceAlias '{adapter_name}' -AddressFamily IPv4 -ErrorAction SilentlyContinue).IPAddress"
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
            if res.returncode == 0:
                for line in res.stdout.strip().splitlines():
                    ip_str = line.strip()
                    if ip_str and not ip_str.startswith("127."):
                        return ip_str
        except Exception:
            pass
        return None

    def _find_peer_on_adapter(self, adapter: DirectLinkAdapter) -> Optional[str]:
        """Probes the direct cable subnet to discover the peer laptop's IP address."""
        if not adapter.ipv4_address:
            return None

        local_ip = adapter.ipv4_address

        # Check ARP table for neighbor entries on this interface
        try:
            cmd = ["arp", "-a"]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
            if res.returncode == 0:
                # Look for IP in same subnet
                prefix = ".".join(local_ip.split(".")[:2])  # 169.254 or 192.168
                for line in res.stdout.splitlines():
                    parts = line.split()
                    if len(parts) >= 2:
                        candidate_ip = parts[0].strip()
                        if candidate_ip.startswith(prefix) and candidate_ip != local_ip:
                            if not candidate_ip.endswith(".255"):
                                return candidate_ip
        except Exception:
            pass

        # In direct point-to-point link, peer is often adjacent
        return None
