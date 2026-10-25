# Target-Side Diagnosis (T1) & Clean-VM Verification Checklist (T7)
**Project:** CellWatch AI — Philippine BJMP Jail Cell Monitoring System  
**Track:** Inno Setup Installer Prerequisites & Packaging Pipeline  
**Target Hardware:** ASUS TUF Gaming (AMD Ryzen 7 7435HS, NVIDIA RTX 2050 4GB VRAM, Windows 11 x64)

---

## 1. T1: Target-Side Diagnosis Protocol & Captured Failure Modes

### Diagnostic Procedure
When deploying `CellWatch.exe` to a non-development or clean Windows 11 target laptop, the executable must be run from a Command Prompt (`cmd.exe`) to capture the **first error** emitted to `stdout`/`stderr` before any window appears:
```cmd
cd "C:\Program Files\CellWatch"
CellWatch.exe
```

### Captured Failure Modes & Prescribed Architectural Mitigations

| Error Code / Symptom | Root Cause | Triggered Plan Slice & Resolution |
| :--- | :--- | :--- |
| **`VCRUNTIME140_1.dll was not found`** or **`MSVCP140.dll missing`** | Target machine lacks Microsoft Visual C++ 2015–2022 x64 Redistributable runtimes. | **T2 (VC++ Redistributable):** Vendored `vc_redist.x64.exe` in `installer/redist/` with pinned SHA-256 (`cc0ff0eb1dc3f5188ae6300faef32bf5beeba4bdd6e8e445a9184072096b713b`). `installer/CellWatch.iss` queries `HKLM\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\X64` and silently installs runtime if missing. |
| **`nvcuda.dll not found`** or **`CUDA driver version is insufficient`** (driver < R545) | Target machine lacks an NVIDIA discrete GPU or has an outdated display driver (< 545.00 / R545) incompatible with TensorRT 11.1 / CUDA 11.8. | **T3 (GPU & Driver Pre-check):** Inno Setup `InitializeSetup()` queries WMI `Win32_VideoController` for NVIDIA GPU and DriverVersion ≥ 545.00. Aborts setup with critical dialog providing the driver link (`https://www.nvidia.com/Download/index.aspx`). (Bypassable with `/SKIPGPU` for headless VMs). |
| **`sqlite3.OperationalError: unable to open database file`** | The application attempts to open `app_state.db` or `incidents.db` in `C:\Program Files\CellWatch\`, where standard user accounts have read-only access. | **T5 (Writable Data Isolation):** `monitor_app/utils.py::data_path()` routes all writable state to `%LocalAppData%\CellWatchAI\`. `monitor_app/utils.py::migrate_legacy_data()` automatically migrates existing DBs and directories (`recordings`, `exports`, `updates`) from legacy locations without import-time UI freezes. |
| **`ModuleNotFoundError: No module named 'polars'`** | Third-party dependencies (Ultralytics) attempting to import Polars when PyInstaller spec erroneously excluded it. | **Spec Fix:** Reverted `polars` from `CellWatch.spec` excludes to preserve full Contraband detection and analytics runtime integrity. |

---

## 2. T7: Clean-VM Verification Checklist

### Pre-conditions
- **Environment:** Clean Windows 11 23H2 / 24H2 virtual machine or physical target laptop.
- **Tools:** Zero development dependencies (No Python, No Visual Studio, No Git, No PyCharm, No CUDA Toolkit).
- **Target Profiles:**
  - **Profile A (Production BJMP Deployment):** Windows 11 with NVIDIA GeForce RTX GPU and Driver ≥ 545.00.
  - **Profile B (Non-GPU / Office Laptop):** Windows 11 with Intel Iris Xe or AMD Radeon integrated graphics only.

### Step-by-Step Verification Matrix

| # | Checkpoint | Verification Procedure | Expected Outcome | Pass/Fail |
| :-: | :--- | :--- | :--- | :-: |
| **1** | **UAC & Admin Elevation** | Double-click `CellWatch-Setup-1.0.0.exe`. | Windows User Account Control prompt appears requesting Administrator privileges (`PrivilegesRequired=admin`). | [ ] |
| **2** | **Disk Space Requirement** | Ensure drive C:\ has between 11 GB and 14 GB free space. | Setup continues without false disk space block (demands ~10.2 GB total, not ~16 GB). | [ ] |
| **3A** | **Profile A Hardware Pass** | Run installer on machine with NVIDIA RTX GPU (Driver ≥ 545.00). | `CheckNvidiaGPU()` validates hardware and driver without warning or interruption. | [ ] |
| **3B** | **Profile B Hardware Abort** | Run installer on non-NVIDIA machine without parameters. | Setup halts immediately with Critical Error naming the GPU requirement and providing the NVIDIA driver URL (`https://www.nvidia.com/Download/index.aspx`). | [ ] |
| **3C** | **Profile B Parameter Bypass** | Run `CellWatch-Setup-1.0.0.exe /SKIPGPU`. | Setup bypasses hardware check for CPU validation testing. | [ ] |
| **4** | **VC++ Runtime Auto-Install** | Ensure `HKLM\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\X64` is absent prior to run. | Setup silently invokes bundled `vc_redist.x64.exe /quiet /norestart`. Registry key is created and `Installed=1`. | [ ] |
| **5** | **Installation Directory & Exclusions** | Inspect `C:\Program Files\CellWatch\` post-install. | Application binaries installed. No `.db`, `.log`, or development cache files present in the installation directory. | [ ] |
| **6** | **First Launch & User Data Routing** | Launch application via Start Menu or Desktop shortcut. | Launches smoothly with no tracebacks. Verified that `app_state.db` and `incidents.db` are created under `%LocalAppData%\CellWatchAI\`. | [ ] |
| **7** | **Operator Login & Profile Settings** | Log in with standard operator credentials, modify alert threshold or camera settings, close app. | Settings saved to `%LocalAppData%\CellWatchAI\app_state.db`. | [ ] |
| **8** | **Live Surveillance & Recording** | Start live monitoring for 60 seconds and trigger test alert. | Video recorded to `%LocalAppData%\CellWatchAI\recordings\`, incident logged to `%LocalAppData%\CellWatchAI\incidents.db`. No write errors. | [ ] |
| **9** | **Reinstallation & Data Survival** | Run `CellWatch-Setup-1.0.0.exe` over existing installation. | Setup completes. Relaunch app: previous operator login, settings, and incident history in `%LocalAppData%\CellWatchAI\` remain intact. | [ ] |
| **10**| **Uninstallation Cleanliness** | Uninstall via Windows Settings -> Installed apps. | `C:\Program Files\CellWatch\` removed cleanly. Operational databases in `%LocalAppData%\CellWatchAI\` preserved for audit retention. | [ ] |
