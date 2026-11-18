# LaptopShare ⚡
### Reliable Windows-to-Windows LAN File Transfer Application

**LaptopShare** is a standalone, high-performance Windows desktop application designed to transfer files and entire directories between two Windows laptops (such as an OLD laptop and a NEW Lenovo LOQ) connected to the same Wi-Fi network without relying on Windows Network Sharing (SMB), homegroups, or Windows network credentials.

---

## 🌟 Why LaptopShare?

Traditional Windows file sharing frequently fails due to:
- Windows Network Discovery being disabled or failing silently.
- SMB file sharing disabled by Windows security policies.
- Incessant Windows Network Credential / password prompts.
- Public vs. Private network permission conflicts.
- Inability to discover other laptops automatically.

**LaptopShare solves this permanently:**
- **Zero SMB Dependency**: Uses direct TLS-encrypted TCP socket streaming over local Wi-Fi.
- **PIN & QR Code Pairing**: Simple 6-digit connection code or QR code eliminates credential headaches.
- **Receiver Approval**: Incoming transfers require one-click approval on the receiving screen.
- **Chunk-Based Streaming**: Designed for large files (10 GB+) with minimal RAM footprint.
- **SHA-256 Integrity Verification**: Automatically hashes every file on both sides to guarantee byte-for-byte perfection.
- **Interruption & Resume Support**: Resumes partially transferred files from the exact byte offset where interrupted.
- **Dual Discovery**: Automatic UDP LAN beaconing + Manual Direct IP entry fallback.
- **Windows 11 Fluent Design**: Modern dark & light themes with rounded cards and transfer telemetry.

---

## 🚀 Quick Start (Running LaptopShare.exe)

LaptopShare is built as a portable standalone Windows executable (`dist/LaptopShare.exe`). It requires **no Python installation and no dependencies** on either laptop.

### Step 1: Copy to Both Laptops
1. Copy `LaptopShare.exe` to your **OLD laptop** and your **NEW Lenovo LOQ** (via USB flash drive or direct download).
2. Double-click `LaptopShare.exe` on both laptops.

### Step 2: Receiving Laptop (e.g. New Lenovo LOQ)
1. Open the **Receive Files** tab.
2. Note your **Local IP Address** (e.g., `192.168.1.55`) and the **6-Digit PIN** (e.g., `482910`).
3. Set your preferred download destination folder (defaults to `Downloads\LaptopShare`).

### Step 3: Sending Laptop (e.g. Old Laptop)
1. Open the **Send Files** tab.
2. Drag and drop any files or entire folders into the window (or click **Add Files** / **Add Folder**).
3. Under **Recipient Laptop**:
   - Select your Lenovo LOQ from the **Nearby Discovered Device** dropdown.
   - *OR* select **Manual IP & PIN**, type the IP and 6-digit PIN shown on the receiving screen.
4. Click **Send Files Now**.

### Step 4: Approve Transfer
1. A notification banner pops up on the receiving laptop showing the sender device name, file count, and total size.
2. Click **✅ Accept Transfer**.
3. Watch the real-time speed (MB/s), file progress, ETA, and automatic SHA-256 integrity verification!

---

## 🔍 Mode 2: Browse & Choose What to Copy (Remote Access with Permission)

Instead of manually picking files on your old laptop, you can sit at your **new Lenovo LOQ**, request permission to browse your old laptop, and choose exactly what files or folders to copy!

### Step 1: Open LaptopShare on Both Laptops
Ensure LaptopShare is running on your old laptop and new Lenovo LOQ on the same Wi-Fi.

### Step 2: On Your Lenovo LOQ
1. Open the **📂 Browse & Copy** tab.
2. Select your Old Laptop from the **Nearby Discovered Device** dropdown (or enter its IP & PIN).
3. Click **🔑 Connect & Request Access**.

### Step 3: Grant Permission on Your Old Laptop
1. A green prompt appears on the Old Laptop:
   `"🔐 Remote Laptop File Access Request: Laptop 'Lenovo-LOQ' is requesting permission to browse files and copy them."`
2. Click **✅ Grant Browsing Permission**.

### Step 4: Choose & Copy Files on Your Lenovo LOQ
1. Your Lenovo LOQ instantly displays the **Remote File Explorer** showing Desktop, Documents, Downloads, Pictures, Videos, and Drives (`C:\`, `D:\`) of the old laptop.
2. Double-click any folder to navigate inside it.
3. Check the checkboxes next to any files or folders you want to copy.
4. Click **📥 Copy Selected to This Laptop**.
5. Files stream directly over Wi-Fi with live speed, ETA, and automatic SHA-256 checksum verification!

---

## 🔄 Mode 3: Seamless PC Migration Wizard (Switch to New PC in 1 Click)

When moving from your old PC to your new Lenovo LOQ, you don't need to hunt for individual files. The **PC Migration Wizard** automatically scans your entire user profile and lets you migrate everything in an organized way:

### Automatic Category Detection:
- 🖥️ **Desktop**: All desktop files, shortcuts, and folders.
- 📄 **Documents**: Personal documents, spreadsheets, PDFs, and work files.
- 🖼️ **Pictures & Photos**: Camera roll, albums, and wallpapers.
- 📥 **Downloads**: Downloaded files and installers (optional).
- 🎬 **Videos**: Video captures, recordings, and movies.
- 🎵 **Music**: Music libraries, audio tracks, and podcasts.
- 🌐 **Browser Bookmarks**: Google Chrome and Microsoft Edge bookmarks & favorites.
- 💻 **Developer Configs**: VS Code user settings, keybindings, and Git/SSH keys.

### Migration Instructions:
1. Open `LaptopShare.exe` on both laptops.
2. On your **New Lenovo LOQ**, click the **🔄 PC Migration** tab.
3. Select your Old Laptop (or enter its IP & PIN), then click **🔍 Connect & Scan Old PC**.
4. On your **Old Laptop**, click **✅ Approve PC Migration** on the purple authorization card.
5. On your **Lenovo LOQ**, choose the categories you want (or click **Recommended Only**).
6. Choose destination:
   - **Clean Organized Folder** (`Downloads\LaptopShare\Migrated_Old_PC`) — recommended!
   - *OR* **Direct User Profile** (`C:\Users\<user>`) — merges directly into your new profile.
7. Click **🚀 Start Seamless PC Migration**.
8. All files stream directly over local Wi-Fi with category indicators, live speed, ETA, and automatic SHA-256 checksum verification! When complete, click **Yes** to open the organized migrated folder.

---

## 🗂️ Mode 4: Native Windows File Explorer & Web Browser Access (Zero Credentials)

If you prefer using native **Windows File Explorer (`explorer.exe`)** to copy, paste, and drag & drop files between your laptops:

LaptopShare includes a built-in zero-dependency WebDAV & Web Explorer file server on port `52145` that Windows Explorer connects to natively without asking for Windows passwords!

### Option A: 1-Click Mount in Windows Explorer
1. On your **New Lenovo LOQ**, go to **📂 Browse & Copy** or **📡 Nearby Devices**.
2. Select your Old Laptop.
3. Click **"📂 Mount in Windows Explorer (Drive Z:)"** (or click **🗂️ Explorer** on the device card).
4. Windows File Explorer will immediately open showing **Drive Z:** containing all Desktop, Documents, Pictures, Videos, and Hard Drives (`C:`, `D:`) from the old laptop!
5. Drag and drop or copy and paste files directly using Windows File Explorer.

### Option B: Open via Windows Run (`Win + R`)
1. On your Lenovo LOQ, press `Win + R`.
2. Paste the Explorer network path shown on your Old Laptop's **Receive Files** tab:
   ```
   \\192.168.1.XX@52145\DavWWWRoot
   ```
3. Press Enter. Windows File Explorer opens the remote laptop's files directly!

### Option C: View in Web Browser (Chrome, Edge, Firefox)
1. Open any web browser on your Wi-Fi network.
2. Visit: `http://192.168.1.XX:52145/`
3. View, search, preview photos and 4K videos, download single files, or download any folder as a `.ZIP` file in one click!

---

## ⚡ High-Performance Streaming for Large Files & Videos (10 GB+)

LaptopShare is specifically engineered to handle large 4K video files, heavy raw camera photo batches, and multi-gigabyte archives:
- **In-Flight Incremental SHA-256**: Hashes are computed in memory *concurrently while bytes stream across Wi-Fi*. No more freezing or waiting 30–60 seconds before/after a large file transfer.
- **2 MB High-Throughput Buffers**: Sockets use 2 MB send/receive buffers with `TCP_NODELAY` enabled for sustained 50–100+ MB/s Wi-Fi 6 speeds.
- **300-Second Socket Timeout**: Prevents premature disconnects or timeout drops during massive video streaming.
- **Resume Capability**: If Wi-Fi briefly disconnects, re-initiating the transfer resumes from the exact byte offset without restarting from scratch.

---

## 🛡️ Windows Defender Firewall Instructions

LaptopShare communicates directly over LAN on TCP port `52140` and UDP port `52141`.
**DO NOT DISABLE YOUR FIREWALL.** Follow these safe steps if Windows blocks incoming connections:

### Method 1: Allow through Windows Firewall GUI (Recommended)
1. Press `Win + S` and type **Allow an app through Windows Firewall**.
2. Click **Change settings** (administrator shield).
3. Look for **LaptopShare.exe** (or Python if running from source).
4. Check both the **Private** and **Public** checkboxes.
5. If LaptopShare is not listed, click **Allow another app...**, browse to `LaptopShare.exe`, and click **Add**.
6. Click **OK**.

### Method 2: PowerShell (Run as Administrator)
Open PowerShell as Administrator and run:
```powershell
New-NetFirewallRule -DisplayName "LaptopShare LAN Transfer" -Direction Inbound -Program "C:\Path\To\LaptopShare.exe" -Action Allow -Profile Any
```

> **Important Wi-Fi Note:** Ensure your Wi-Fi connection profile on both laptops is set to **Private Network** (Settings > Network & internet > Wi-Fi > [Your Network] > Network profile type = **Private**). Windows aggressively blocks peer-to-peer traffic on Public profiles.

---

## 💻 Running From Source Code

If you wish to run or develop LaptopShare from source:

### Prerequisites
- Python 3.12+ (or 3.10+)
- Windows 10 or Windows 11

### Setup
```powershell
# Navigate to directory
cd C:\Users\mishr\.gemini\antigravity\scratch\LaptopShare

# Install dependencies
pip install -r requirements.txt

# Run GUI
python main.py
```

### CLI / Headless Modes (Optional)
```powershell
# Run as headless receiver on port 52140 with PIN 123456
python main.py --headless-receiver --port 52140 --pin 123456

# Send files from command line
python main.py --send-cli --target 192.168.1.55 --pin 123456 file1.zip folder/
```

---

## 🏗️ Building Standalone Executable (.EXE)

To rebuild `LaptopShare.exe` with PyInstaller:
```powershell
python build_exe.py
```
The output executable will be placed in `dist/LaptopShare.exe`.

---

## 🧪 Automated Testing

LaptopShare includes automated integration and concurrency tests:
```powershell
# Test handshake, PIN auth, chunking, resume, and SHA-256 verification
python tests/test_transfer.py

# Test two instances with a 50 MB file transfer
python tests/test_two_instances.py
```

---

## 📁 Project Architecture

```
LaptopShare/
│
├── core/
│   ├── config.py           # App settings, device name, persistent JSON config
│   ├── discovery.py        # UDP broadcast LAN beacon & unicast probe
│   ├── file_manager.py     # Recursive folder scanner, safe relative paths, SHA-256
│   ├── history.py          # Transfer history records manager
│   ├── network_utils.py    # Local IP detection, Wi-Fi adapter stats, firewall guides
│   ├── protocol.py         # Binary framing protocol (LSH1), packet headers
│   ├── security.py         # Ephemeral X.509 TLS cert generation & PIN auth
│   ├── transfer_client.py  # Sender worker thread, chunk streaming, resume logic
│   └── transfer_server.py  # Receiver TLS TCP server, approval workflow, file writer
│
├── ui/
│   ├── main_window.py      # Fluent sidebar navigation & view stack
│   ├── send_tab.py         # Drag-and-drop file queue, recipient selector, progress card
│   ├── receive_tab.py      # Local IP cards, 6-digit PIN, QR code, approval card
│   ├── devices_tab.py      # Nearby discovered laptops list & quick send
│   ├── history_tab.py      # Transfer history log with open folder action
│   ├── settings_tab.py     # Preferences, network diagnostics & firewall tools
│   ├── styles.py           # Windows 11 Fluent dark & light QSS stylesheets
│   └── qr_widget.py        # QR code generator and renderer
│
├── assets/
│   ├── icon.ico            # Windows multi-size application icon
│   └── icon.png            # Application logo image
│
├── tests/
│   ├── test_transfer.py     # Integration pipeline & resume test suite
│   └── test_two_instances.py# Dual-instance 50 MB file transfer test
│
├── build_exe.py            # Automated PyInstaller packaging script
├── main.py                 # Application launcher & CLI options
├── requirements.txt        # Python dependency manifest
└── README.md               # User manual & documentation
```
