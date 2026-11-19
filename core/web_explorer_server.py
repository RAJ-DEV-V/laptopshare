"""
LaptopShare Web & Windows Explorer (WebDAV) File Server
Enables native exploration and copying directly via Windows File Explorer (explorer.exe),
WebDAV network drive mapping (Drive Z:), and local web browser portal without SMB credentials.
"""

import os
import sys
import time
import socket
import urllib.parse
import mimetypes
import zipfile
import threading
import io
import subprocess
from email.utils import formatdate
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from pathlib import Path
from typing import Dict, List, Optional, Tuple

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

from .config import ConfigManager, get_system_shared_roots, DEFAULT_TRANSFER_PORT

DEFAULT_WEB_EXPLORER_PORT = 52145

def get_free_drive_letter() -> Optional[str]:
    """Finds an unused Windows drive letter starting from Z: down to E:"""
    import string
    import ctypes
    bitmask = ctypes.windll.kernel32.GetLogicalDrives()
    letters = list(string.ascii_uppercase)
    # Search backwards: Z down to E
    for i in range(25, 3, -1):
        if not (bitmask & (1 << i)):
            return f"{letters[i]}:"
    return None

def mount_remote_in_windows_explorer(ip: str, port: int = DEFAULT_WEB_EXPLORER_PORT) -> Tuple[bool, str, str]:
    """
    Mounts the remote LaptopShare WebDAV service as a Windows drive (e.g. Z:)
    and opens it immediately in native Windows File Explorer.
    """
    drive_letter = get_free_drive_letter()
    if not drive_letter:
        drive_letter = "Z:"

    # 1. Ensure Windows WebClient service is started
    try:
        subprocess.run(["sc", "start", "webclient"], capture_output=True, timeout=3, creationflags=CREATE_NO_WINDOW)
    except Exception:
        pass

    # 2. Try mounting via 'net use'
    webdav_url = f"http://{ip}:{port}/"
    cmd = ["net", "use", drive_letter, webdav_url, "/persistent:no"]

    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=8, creationflags=CREATE_NO_WINDOW)
        if res.returncode == 0:
            # Successfully mounted drive
            subprocess.Popen(["explorer.exe", f"{drive_letter}\\"])
            return True, drive_letter, f"Mounted as {drive_letter} in Windows Explorer!"
    except Exception as e:
        print(f"[WebDAV] net use attempt 1 error: {e}")

    # Fallback attempt 2: UNC style \\ip@port\DavWWWRoot
    unc_path = f"\\\\{ip}@{port}\\DavWWWRoot"
    cmd2 = ["net", "use", drive_letter, unc_path, "/persistent:no"]
    try:
        res2 = subprocess.run(cmd2, capture_output=True, text=True, timeout=8, creationflags=CREATE_NO_WINDOW)
        if res2.returncode == 0:
            subprocess.Popen(["explorer.exe", f"{drive_letter}\\"])
            return True, drive_letter, f"Mounted as {drive_letter} in Windows Explorer!"
    except Exception as e:
        print(f"[WebDAV] net use attempt 2 error: {e}")

    # Fallback attempt 3: Open UNC path directly in explorer.exe
    try:
        subprocess.Popen(["explorer.exe", unc_path])
        return True, unc_path, f"Opened {unc_path} directly in Windows Explorer."
    except Exception as e:
        # Fallback attempt 4: Open web browser portal
        import webbrowser
        webbrowser.open(f"http://{ip}:{port}/")
        return False, "", f"Could not map drive automatically ({e}). Opened Web Explorer in browser instead."

def unmount_drive(drive_letter: str) -> bool:
    """Unmounts a mapped network drive."""
    clean_letter = drive_letter.strip().rstrip("\\")
    if not clean_letter.endswith(":"):
        clean_letter += ":"
    try:
        res = subprocess.run(["net", "use", clean_letter, "/delete", "/y"], capture_output=True, text=True, timeout=5, creationflags=CREATE_NO_WINDOW)
        return res.returncode == 0
    except Exception:
        return False

def open_in_windows_explorer(target_path: str):
    """Opens native Windows File Explorer focused on the specified path."""
    p = Path(target_path)
    if not p.exists():
        p.mkdir(parents=True, exist_ok=True)
    try:
        os.startfile(str(p))
    except Exception:
        subprocess.Popen(["explorer.exe", str(p)])


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class WebExplorerHandler(BaseHTTPRequestHandler):
    server_version = "LaptopShare-WebDAV/1.0"

    def log_message(self, format, *args):
        # Suppress verbose terminal spam for normal status 200/206/207
        pass

    def _get_mapped_roots(self) -> Dict[str, Path]:
        """Returns clean dictionary of virtual root name -> Path."""
        roots: Dict[str, Path] = {}
        for r in get_system_shared_roots():
            name = r["name"]
            # Clean icons and special chars: "📁 Desktop" -> "Desktop", "💾 Local Disk (C:)" -> "Drive_C"
            clean_name = name.replace("📁", "").replace("💾", "").replace("Local Disk", "Drive").strip()
            clean_name = clean_name.replace("(", "").replace(")", "").replace(":", "").replace(" ", "_")
            p = Path(r["path"])
            if p.exists():
                roots[clean_name] = p
        return roots

    def _resolve_url_path(self, raw_path: str) -> Tuple[Optional[Path], bool, str]:
        """
        Resolves requested URL path to a local Path.
        Returns: (local_path_or_none, is_root, virtual_rel_path)
        """
        parsed = urllib.parse.urlparse(raw_path).path
        decoded = urllib.parse.unquote(parsed)

        # Strip DavWWWRoot prefix if present (used by Windows Explorer WebDAV client)
        if decoded.startswith("/DavWWWRoot"):
            decoded = decoded[len("/DavWWWRoot"):]
            if not decoded.startswith("/"):
                decoded = "/" + decoded

        decoded = decoded.strip("/")
        if not decoded:
            return None, True, ""

        parts = [p for p in decoded.split("/") if p and p != "." and p != ".."]
        if not parts:
            return None, True, ""

        root_name = parts[0]
        roots = self._get_mapped_roots()
        if root_name not in roots:
            # Case insensitive root matching
            found_root = None
            for k in roots:
                if k.lower() == root_name.lower():
                    found_root = k
                    break
            if not found_root:
                return None, False, decoded
            root_name = found_root

        base_path = roots[root_name]
        if len(parts) == 1:
            return base_path, False, decoded

        # Sub-path within base_path
        sub_path = Path(*parts[1:])
        full_path = (base_path / sub_path).resolve()

        # Prevent traversal outside base_path
        try:
            full_path.relative_to(base_path)
            return full_path, False, decoded
        except ValueError:
            return None, False, decoded

    # ================= WebDAV Methods =================

    def do_OPTIONS(self):
        """Responds to WebDAV capability inquiries from Windows Explorer."""
        self.send_response(200)
        self.send_header("DAV", "1, 2")
        self.send_header("MS-Author-Via", "DAV")
        self.send_header("Allow", "OPTIONS, GET, HEAD, PROPFIND")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_PROPFIND(self):
        """Generates WebDAV XML multistatus for Windows Explorer."""
        depth = self.headers.get("Depth", "1").strip().lower()
        local_path, is_root, virtual_rel = self._resolve_url_path(self.path)

        if not is_root and (local_path is None or not local_path.exists()):
            self.send_error(404, "Not Found")
            return

        xml_entries = []

        def make_propstat(href: str, display_name: str, is_dir: bool, size: int, mtime: float):
            d_time = formatdate(mtime, usegmt=True)
            res_type = "<D:collection/>" if is_dir else ""
            mime_type = "httpd/unix-directory" if is_dir else (mimetypes.guess_type(display_name)[0] or "application/octet-stream")
            return f"""  <D:response>
    <D:href>{href}</D:href>
    <D:propstat>
      <D:prop>
        <D:displayname>{urllib.parse.quote(display_name)}</D:displayname>
        <D:resourcetype>{res_type}</D:resourcetype>
        <D:getcontentlength>{size}</D:getcontentlength>
        <D:getlastmodified>{d_time}</D:getlastmodified>
        <D:getcontenttype>{mime_type}</D:getcontenttype>
      </D:prop>
      <D:status>HTTP/1.1 200 OK</D:status>
    </D:propstat>
  </D:response>"""

        prefix = "/DavWWWRoot/" if self.path.startswith("/DavWWWRoot") else "/"

        if is_root:
            # Root collection entry
            xml_entries.append(make_propstat(prefix, "LaptopShare", True, 0, time.time()))

            if depth != "0":
                roots = self._get_mapped_roots()
                for root_name, root_p in roots.items():
                    mtime = root_p.stat().st_mtime if root_p.exists() else time.time()
                    href = f"{prefix}{root_name}/"
                    xml_entries.append(make_propstat(href, root_name, True, 0, mtime))
        else:
            # Target path entry
            is_d = local_path.is_dir()
            sz = 0 if is_d else local_path.stat().st_size
            mtime = local_path.stat().st_mtime
            cur_href = f"{prefix}{virtual_rel}"
            if is_d and not cur_href.endswith("/"):
                cur_href += "/"
            xml_entries.append(make_propstat(cur_href, local_path.name, is_d, sz, mtime))

            if is_d and depth != "0":
                try:
                    for child in local_path.iterdir():
                        try:
                            c_is_d = child.is_dir()
                            c_sz = 0 if c_is_d else child.stat().st_size
                            c_mtime = child.stat().st_mtime
                            c_href = f"{cur_href}{child.name}"
                            if c_is_d:
                                c_href += "/"
                            xml_entries.append(make_propstat(c_href, child.name, c_is_d, c_sz, c_mtime))
                        except (PermissionError, FileNotFoundError, OSError):
                            continue
                except (PermissionError, OSError):
                    pass

        body = f"""<?xml version="1.0" encoding="utf-8" ?>
<D:multistatus xmlns:D="DAV:">
{os.linesep.join(xml_entries)}
</D:multistatus>""".encode("utf-8")

        self.send_response(207, "Multi-Status")
        self.send_header("Content-Type", 'application/xml; charset="utf-8"')
        self.send_header("DAV", "1, 2")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ================= HTTP GET / HEAD Methods =================

    def do_HEAD(self):
        self._handle_get(head_only=True)

    def do_GET(self):
        # Check for zip download query: ?zip=1
        if "?zip=1" in self.path:
            self._handle_zip_download()
            return
        self._handle_get(head_only=False)

    def _handle_get(self, head_only: bool = False):
        local_path, is_root, virtual_rel = self._resolve_url_path(self.path)

        # Check if browser is viewing HTML
        accept_header = self.headers.get("Accept", "")
        user_agent = self.headers.get("User-Agent", "")
        is_browser = ("text/html" in accept_header) or ("Mozilla" in user_agent and "Dav" not in user_agent)

        if is_root or (local_path and local_path.is_dir()):
            if is_browser:
                self._render_browser_html(local_path, is_root, virtual_rel)
            else:
                # WebDAV client accessing directory via GET: redirect with trailing slash
                if not self.path.endswith("/"):
                    self.send_response(301)
                    self.send_header("Location", self.path + "/")
                    self.end_headers()
                else:
                    self._render_browser_html(local_path, is_root, virtual_rel)
            return

        if not local_path or not local_path.exists() or not local_path.is_file():
            self.send_error(404, "File Not Found")
            return

        file_size = local_path.stat().st_size
        mime_type, _ = mimetypes.guess_type(str(local_path))
        if not mime_type:
            mime_type = "application/octet-stream"

        # Handle HTTP Range Header (Critical for Windows Explorer and video streaming)
        range_header = self.headers.get("Range")
        start = 0
        end = file_size - 1

        if range_header and range_header.startswith("bytes="):
            try:
                parts = range_header[6:].split("-")
                if parts[0]:
                    start = int(parts[0])
                if len(parts) > 1 and parts[1]:
                    end = int(parts[1])
                if start > end or start >= file_size:
                    self.send_response(416, "Requested Range Not Satisfiable")
                    self.send_header("Content-Range", f"bytes */{file_size}")
                    self.end_headers()
                    return

                length = end - start + 1
                self.send_response(206, "Partial Content")
                self.send_header("Content-Type", mime_type)
                self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
                self.send_header("Content-Length", str(length))
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Last-Modified", formatdate(local_path.stat().st_mtime, usegmt=True))
                self.end_headers()

                if not head_only:
                    with open(local_path, "rb") as f:
                        f.seek(start)
                        remaining = length
                        while remaining > 0:
                            chunk_sz = min(1024 * 1024, remaining)
                            buf = f.read(chunk_sz)
                            if not buf:
                                break
                            self.wfile.write(buf)
                            remaining -= len(buf)
                return
            except Exception as e:
                print(f"[WebDAV] Range processing error: {e}")

        # Regular full GET
        self.send_response(200)
        self.send_header("Content-Type", mime_type)
        self.send_header("Content-Length", str(file_size))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Last-Modified", formatdate(local_path.stat().st_mtime, usegmt=True))
        self.send_header("Content-Disposition", f'inline; filename="{urllib.parse.quote(local_path.name)}"')
        self.end_headers()

        if not head_only:
            with open(local_path, "rb") as f:
                while True:
                    buf = f.read(1024 * 1024)
                    if not buf:
                        break
                    try:
                        self.wfile.write(buf)
                    except (ConnectionResetError, BrokenPipeError):
                        break

    def _handle_zip_download(self):
        """Streams a folder as a ZIP archive for one-click downloading."""
        clean_path = self.path.split("?")[0]
        local_path, is_root, virtual_rel = self._resolve_url_path(clean_path)

        if is_root or not local_path or not local_path.is_dir():
            self.send_error(400, "ZIP download only supported for directories")
            return

        folder_name = local_path.name
        self.send_response(200)
        self.send_header("Content-Type", "application/zip")
        self.send_header("Content-Disposition", f'attachment; filename="{urllib.parse.quote(folder_name)}.zip"')
        self.end_headers()

        try:
            with zipfile.ZipFile(self.wfile, "w", zipfile.ZIP_DEFLATED, False) as zf:
                for root, dirs, files in os.walk(local_path):
                    for fname in files:
                        fp = Path(root) / fname
                        try:
                            rel_in_zip = fp.relative_to(local_path).as_posix()
                            zf.write(fp, arcname=rel_in_zip)
                        except (PermissionError, FileNotFoundError, OSError):
                            continue
        except (ConnectionResetError, BrokenPipeError):
            pass

    def _render_browser_html(self, local_path: Optional[Path], is_root: bool, virtual_rel: str):
        """Renders modern Windows Fluent Web Explorer HTML page for browsers."""
        cfg = ConfigManager().get()
        host = self.headers.get("Host", f"localhost:{DEFAULT_WEB_EXPLORER_PORT}")
        ip_only = host.split(":")[0]

        items_html = []
        current_title = "LaptopShare File Explorer"

        if is_root:
            current_title = f"{cfg.device_name} — Shared Locations"
            roots = self._get_mapped_roots()
            for r_name, r_path in roots.items():
                items_html.append(f"""
                <tr onclick="location.href='/{r_name}/'">
                    <td class="icon-col">📁</td>
                    <td class="name-col"><a href="/{r_name}/">{r_name}</a></td>
                    <td class="size-col">Folder</td>
                    <td class="date-col">--</td>
                    <td class="action-col"><a class="btn-sm" href="/{r_name}/?zip=1">📦 ZIP</a></td>
                </tr>
                """)
        else:
            current_title = f"{local_path.name} — {cfg.device_name}"
            # Parent link
            parent_rel = "/".join(virtual_rel.strip("/").split("/")[:-1])
            parent_url = f"/{parent_rel}/" if parent_rel else "/"
            items_html.append(f"""
            <tr onclick="location.href='{parent_url}'">
                <td class="icon-col">⬆️</td>
                <td class="name-col"><a href="{parent_url}">.. (Parent Directory)</a></td>
                <td class="size-col">--</td>
                <td class="date-col">--</td>
                <td class="action-col"></td>
            </tr>
            """)

            try:
                entries = sorted(local_path.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
                for e in entries:
                    try:
                        is_d = e.is_dir()
                        icon = "📁" if is_d else ("🎬" if e.suffix.lower() in [".mp4", ".mkv", ".mov", ".avi"] else ("🖼️" if e.suffix.lower() in [".jpg", ".jpeg", ".png", ".webp", ".gif"] else "📄"))
                        url = f"/{virtual_rel.strip('/')}/{urllib.parse.quote(e.name)}"
                        if is_d:
                            url += "/"
                            sz_text = "Folder"
                            act = f'<a class="btn-sm" href="{url}?zip=1">📦 ZIP</a>'
                        else:
                            sz = e.stat().st_size
                            sz_text = f"{sz / (1024*1024):.2f} MB" if sz > 1024*1024 else f"{sz / 1024:.1f} KB"
                            act = f'<a class="btn-sm primary" href="{url}" download>📥 Download</a>'

                        mtime_str = time.strftime("%Y-%m-%d %H:%M", time.localtime(e.stat().st_mtime))
                        items_html.append(f"""
                        <tr onclick="if(event.target.tagName!='A') location.href='{url}'">
                            <td class="icon-col">{icon}</td>
                            <td class="name-col"><a href="{url}">{e.name}</a></td>
                            <td class="size-col">{sz_text}</td>
                            <td class="date-col">{mtime_str}</td>
                            <td class="action-col">{act}</td>
                        </tr>
                        """)
                    except (PermissionError, OSError):
                        continue
            except PermissionError:
                items_html.append("<tr><td colspan='5' style='color:#ef4444;text-align:center;'>Access Denied to this folder</td></tr>")

        html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{current_title}</title>
<style>
  :root {{
    --bg: #0f172a;
    --card: #1e293b;
    --text: #f8fafc;
    --muted: #94a3b8;
    --accent: #0284c7;
    --accent-hover: #0369a1;
    --border: #334155;
    --row-hover: #273549;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: var(--bg); color: var(--text); padding: 24px; }}
  .container {{ max-width: 1080px; margin: 0 auto; }}
  .header {{ display: flex; align-items: center; justify-content: space-between; margin-bottom: 20px; flex-wrap: wrap; gap: 12px; }}
  .title-box h1 {{ font-size: 22px; font-weight: 700; color: #38bdf8; }}
  .title-box p {{ font-size: 13px; color: var(--muted); }}
  .banner {{ background: linear-gradient(135deg, #0369a1, #0f766e); padding: 14px 18px; border-radius: 10px; margin-bottom: 20px; display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 10px; }}
  .banner-text {{ font-size: 13px; line-height: 1.5; }}
  .banner-code {{ background: rgba(0,0,0,0.3); padding: 4px 8px; border-radius: 5px; font-family: monospace; font-size: 13px; color: #a7f3d0; user-select: all; }}
  .card {{ background: var(--card); border: 1px solid var(--border); border-radius: 12px; overflow: hidden; }}
  table {{ width: 100%; border-collapse: collapse; text-align: left; font-size: 14px; }}
  th {{ background: #172033; padding: 12px 16px; color: var(--muted); font-weight: 600; border-bottom: 1px solid var(--border); }}
  td {{ padding: 12px 16px; border-bottom: 1px solid rgba(51,65,85,0.5); vertical-align: middle; }}
  tr:hover {{ background: var(--row-hover); cursor: pointer; }}
  .icon-col {{ width: 36px; font-size: 18px; text-align: center; }}
  .name-col {{ font-weight: 500; }}
  .name-col a {{ color: var(--text); text-decoration: none; }}
  .name-col a:hover {{ text-decoration: underline; color: #38bdf8; }}
  .size-col {{ width: 110px; color: var(--muted); }}
  .date-col {{ width: 150px; color: var(--muted); }}
  .action-col {{ width: 130px; text-align: right; }}
  .btn-sm {{ display: inline-block; padding: 5px 10px; border-radius: 6px; font-size: 12px; text-decoration: none; color: #cbd5e1; background: #334155; transition: 0.2s; }}
  .btn-sm:hover {{ background: #475569; color: #ffffff; }}
  .btn-sm.primary {{ background: var(--accent); color: #ffffff; }}
  .btn-sm.primary:hover {{ background: var(--accent-hover); }}
  .search-box {{ width: 100%; padding: 10px 14px; background: #172033; border: 1px solid var(--border); border-radius: 8px; color: #fff; margin-bottom: 14px; outline: none; }}
  .search-box:focus {{ border-color: var(--accent); }}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <div class="title-box">
      <h1>⚡ LaptopShare Web & Windows Explorer Access</h1>
      <p>Host Laptop: <strong>{cfg.device_name}</strong> &bull; IP: {ip_only}</p>
    </div>
  </div>

  <div class="banner">
    <div class="banner-text">
      <strong>📂 Want to copy files via native Windows File Explorer?</strong><br>
      Press <kbd>Win + R</kbd> and paste: <span class="banner-code">\\\\{ip_only}@{DEFAULT_WEB_EXPLORER_PORT}\\DavWWWRoot</span> or run <span class="banner-code">net use Z: http://{ip_only}:{DEFAULT_WEB_EXPLORER_PORT}</span>
    </div>
  </div>

  <input type="text" class="search-box" id="search" placeholder="🔍 Filter files and folders in this list..." onkeyup="filterTable()">

  <div class="card">
    <table id="file-table">
      <thead>
        <tr>
          <th></th>
          <th>Name</th>
          <th>Size</th>
          <th>Modified</th>
          <th style="text-align: right;">Action</th>
        </tr>
      </thead>
      <tbody>
        {"".join(items_html)}
      </tbody>
    </table>
  </div>
</div>

<script>
function filterTable() {{
  var input = document.getElementById("search");
  var filter = input.value.toLowerCase();
  var table = document.getElementById("file-table");
  var tr = table.getElementsByTagName("tr");
  for (var i = 1; i < tr.length; i++) {{
    var td = tr[i].getElementsByTagName("td")[1];
    if (td) {{
      var txt = td.textContent || td.innerText;
      tr[i].style.display = txt.toLowerCase().indexOf(filter) > -1 ? "" : "none";
    }}
  }}
}}
</script>
</body>
</html>
"""
        body_bytes = html_content.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body_bytes)))
        self.end_headers()
        self.wfile.write(body_bytes)


class WebExplorerServer:
    """Manages the background WebDAV & Web Browser File Sharing Server."""
    def __init__(self, port: int = DEFAULT_WEB_EXPLORER_PORT):
        self.port = port
        self.running = False
        self._server: Optional[ThreadedHTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    def start(self):
        if self.running:
            return
        self.running = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="WebExplorerServerThread")
        self._thread.start()

    def _run(self):
        try:
            self._server = ThreadedHTTPServer(("0.0.0.0", self.port), WebExplorerHandler)
            print(f"[WebExplorer] WebDAV & Browser File Portal active on port {self.port}")
            self._server.serve_forever()
        except Exception as e:
            print(f"[WebExplorer] Failed to start on port {self.port}: {e}")
            self.running = False

    def stop(self):
        self.running = False
        if self._server:
            try:
                self._server.shutdown()
                self._server.server_close()
            except Exception:
                pass
            self._server = None
