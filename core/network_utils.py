"""
LaptopShare Network Utilities
Detects local IPv4 addresses, active network adapters, tests port availability,
and provides network diagnostics and firewall assistance.
"""

import socket
import subprocess
from typing import List, Dict, Optional, Tuple, Any

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

def get_local_ip_addresses() -> List[Dict[str, str]]:
    """
    Returns a list of active local IPv4 addresses on the system,
    with adapter name, IP address, and whether it looks like Wi-Fi/Ethernet.
    """
    results = []
    seen_ips = set()

    # Priority 1: try socket connection to find default gateway route IP
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        # 192.168.255.255 or 8.8.8.8 without sending actual packets
        s.connect(("8.8.8.8", 80))
        primary_ip = s.getsockname()[0]
        s.close()
        if primary_ip and not primary_ip.startswith("127."):
            seen_ips.add(primary_ip)
            results.append({
                "ip": primary_ip,
                "name": "Primary LAN (Default Route)",
                "is_primary": True
            })
    except Exception:
        pass

    # Priority 2: Use psutil if available or socket.gethostbyname_ex
    try:
        import psutil
        for iface_name, addrs in psutil.net_if_addrs().items():
            # Check stats to see if adapter is up
            stats = psutil.net_if_stats().get(iface_name)
            is_up = stats.isup if stats else True
            if not is_up:
                continue

            for addr in addrs:
                if addr.family == socket.AF_INET:
                    ip = addr.address
                    if ip.startswith("127."):
                        continue
                    is_wifi = any(w in iface_name.lower() for w in ["wi-fi", "wifi", "wlan", "wireless"])
                    is_eth = any(e in iface_name.lower() for e in ["ethernet", "eth", "lan", "realtek", "intel", "gbe", "pcie"])

                    # If APIPA link-local (169.254.x.x), keep it if it's an active direct Ethernet/LAN interface
                    if ip.startswith("169.254.") and not is_eth:
                        continue

                    if ip not in seen_ips:
                        seen_ips.add(ip)
                        label = iface_name
                        if is_eth and ip.startswith("169.254."):
                            label += " (Direct Ethernet Link-Local)"
                        elif is_wifi:
                            label += " (Wi-Fi)"
                        elif is_eth:
                            label += " (Ethernet)"

                        results.append({
                            "ip": ip,
                            "name": label,
                            "is_primary": False
                        })
    except Exception:
        # Fallback to standard socket
        try:
            hostname = socket.gethostname()
            _, _, ips = socket.gethostbyname_ex(hostname)
            for ip in ips:
                if not ip.startswith("127.") and not ip.startswith("169.254.") and ip not in seen_ips:
                    seen_ips.add(ip)
                    results.append({
                        "ip": ip,
                        "name": f"Interface ({ip})",
                        "is_primary": False
                    })
        except Exception:
            pass

    if not results:
        results.append({
            "ip": "127.0.0.1",
            "name": "Localhost (Loopback)",
            "is_primary": True
        })

    return results

def get_primary_ip() -> str:
    """Returns the best single local IP address for this machine."""
    ips = get_local_ip_addresses()
    for item in ips:
        if item.get("is_primary"):
            return item["ip"]
    return ips[0]["ip"] if ips else "127.0.0.1"

def is_port_available(port: int, host: str = "0.0.0.0") -> bool:
    """Checks whether a TCP port is free to bind."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((host, port))
            return True
    except OSError:
        return False

def test_lan_connection(host: str, port: int, timeout: float = 3.0) -> Tuple[bool, str]:
    """
    Tests direct TCP connectivity to a remote host and port.
    Returns (success, message).
    """
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect((host, port))
        s.close()
        return True, f"Connection to {host}:{port} succeeded."
    except socket.timeout:
        return False, f"Connection timed out reaching {host}:{port}. Check Windows Firewall on the receiver laptop."
    except ConnectionRefusedError:
        return False, f"Connection refused at {host}:{port}. LaptopShare receiver might not be active on that port."
    except Exception as e:
        return False, f"Could not reach {host}:{port} ({e})."

def get_firewall_troubleshooting_info(app_exe_path: Optional[str] = None) -> str:
    """
    Returns helpful troubleshooting steps for Windows Firewall without disabling it.
    """
    exe_target = app_exe_path or "LaptopShare.exe"
    return f"""### Windows Defender Firewall Configuration Guide

If your laptops cannot connect, Windows Firewall may be blocking inbound LAN connections.
**Do NOT disable your firewall.** Instead, allow LaptopShare through:

#### Method 1: Windows Firewall GUI (Recommended)
1. Press **Win + S** and type **Allow an app through Windows Firewall**.
2. Click **Change settings** (requires administrator permission).
3. Look for **LaptopShare** (or Python if running from source).
4. Check both the **Private** and **Public** checkboxes.
5. If LaptopShare is not listed, click **Allow another app...**, browse to `{exe_target}`, and click **Add**.
6. Click **OK** to save.

#### Method 2: PowerShell (Run as Administrator)
Open PowerShell as Administrator and run:
```powershell
New-NetFirewallRule -DisplayName "LaptopShare File Transfer" -Direction Inbound -Program "{exe_target}" -Action Allow -Profile Any
```

#### Network Profile Note:
Ensure your Wi-Fi network profile on both laptops is set to **Private Network** (Settings > Network & internet > Wi-Fi > [Your Wi-Fi network] > Network profile type = Private). Windows blocks LAN traffic when set to Public!
"""

def get_wifi_diagnostics() -> Dict[str, Any]:
    """
    Audits the current Wi-Fi adapter state using 'netsh wlan show interfaces' silently.
    Returns details on SSID, band, radio type (802.11ax), speeds, and performance advice.
    """
    info = {
        "connected": False,
        "name": "",
        "ssid": "",
        "band": "",
        "radio": "",
        "link_speed_tx": "0",
        "link_speed_rx": "0",
        "signal": "",
        "is_5ghz": False,
        "is_wifi6": False,
        "advice": ""
    }
    try:
        res = subprocess.run(
            ["netsh", "wlan", "show", "interfaces"],
            capture_output=True,
            text=True,
            timeout=2,
            creationflags=CREATE_NO_WINDOW
        )
        if res.returncode == 0:
            parsed = {}
            for line in res.stdout.splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    parsed[k.strip().lower()] = v.strip()

            state = parsed.get("state", "").lower()
            if state == "connected":
                info["connected"] = True
                info["name"] = parsed.get("name", "Wi-Fi")
                info["ssid"] = parsed.get("ssid", "")
                info["band"] = parsed.get("band", "")
                info["radio"] = parsed.get("radio type", "")
                info["link_speed_tx"] = parsed.get("transmit rate (mbps)", "0")
                info["link_speed_rx"] = parsed.get("receive rate (mbps)", "0")
                info["signal"] = parsed.get("signal", "")
                info["is_5ghz"] = "5" in info["band"] or "6" in info["band"]
                info["is_wifi6"] = "802.11ax" in info["radio"].lower() or "wi-fi 6" in info["radio"].lower()

                # Generate actionable optimization advice
                tx_spd = 0
                try:
                    tx_spd = int(info["link_speed_tx"])
                except Exception:
                    pass

                if not info["is_5ghz"]:
                    info["advice"] = "⚠️ Connected on slow 2.4 GHz band. Switch to 5 GHz or enable Windows 5GHz Direct Hotspot for 5x–10x faster speeds!"
                elif tx_spd < 600:
                    info["advice"] = f"💡 2-Hop Relay / Moderate link ({tx_spd} Mbps via '{info['ssid']}'). For maximum wireless speed (100+ MB/s), host a Windows 5GHz Direct Hotspot on this PC!"
                else:
                    info["advice"] = f"⚡ Ultra-Fast Wi-Fi Active: {info['radio']} on {info['band']} ({tx_spd} Mbps link rate)."
    except Exception as e:
        info["advice"] = f"Wi-Fi diagnostic unavailable ({e})."
    return info

def open_mobile_hotspot_settings():
    """Opens Windows 11/10 Mobile Hotspot Settings directly."""
    try:
        import os
        os.startfile("ms-settings:network-mobilehotspot")
    except Exception:
        pass

def get_ethernet_status() -> Dict[str, Any]:
    """
    Returns real-time diagnostics of the system's Ethernet adapter(s),
    including connection state, negotiated link speed, and IPv4 address.
    """
    info = {
        "is_connected": False,
        "adapter_name": "Ethernet",
        "speed_mbps": 0,
        "speed_text": "Disconnected",
        "ipv4": "",
        "is_gigabit": False,
        "status_text": "Ethernet Cable Disconnected",
        "peer_ip": None
    }
    try:
        import psutil
        stats_dict = psutil.net_if_stats()
        addrs_dict = psutil.net_if_addrs()

        for iface_name, stats in stats_dict.items():
            iface_lower = iface_name.lower()
            if any(k in iface_lower for k in ["ethernet", "eth", "lan", "realtek", "gbe", "pcie"]):
                if "bluetooth" in iface_lower or "virtual" in iface_lower or "vpn" in iface_lower:
                    continue
                info["adapter_name"] = iface_name
                info["is_connected"] = stats.isup
                info["speed_mbps"] = stats.speed if stats.speed > 0 else 0
                info["is_gigabit"] = (stats.speed >= 1000)

                for addr in addrs_dict.get(iface_name, []):
                    if addr.family == socket.AF_INET and not addr.address.startswith("127."):
                        info["ipv4"] = addr.address
                        break

                if stats.isup:
                    spd_txt = f"{stats.speed} Mbps" if stats.speed > 0 else "Active Link"
                    if stats.speed >= 1000:
                        spd_txt += " (Gigabit Ultra-Fast)"
                    info["speed_text"] = spd_txt
                    info["status_text"] = f"🟢 Direct Ethernet Link Active ({spd_txt})"
                    break
    except Exception as e:
        info["status_text"] = f"Ethernet diagnostic unavailable: {e}"

    return info

def open_network_connections():
    """Opens Windows Network Connections control panel (ncpa.cpl)."""
    try:
        import os
        os.startfile("ncpa.cpl")
    except Exception:
        pass
