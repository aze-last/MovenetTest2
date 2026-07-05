## PyInstaller Packaging & Path Resolution Strategy

**Critical Issue Identified:** 
The current codebase relies on `os.path.dirname(os.path.abspath(__file__))` to resolve `BASE_DIR`. In a PyInstaller `--onedir` bundle, this resolves to the temporary extraction directory. Without a fix, **read-write data** (like `app_state.db`, `incidents.db`, uploaded profiles, benchmark logs, and exported PDFs) will be created inside this temporary folder and **permanently deleted** the moment the application closes.

**Resolution Plan (Approved for Implementation):**
To safely package CellWatch without risking catastrophic data loss, we must implement a bifurcated path resolution strategy. There is not one universal patch, but two distinct strategies depending on the file type:

### 1. Read-Only Bundled Assets
*   **Applies to:** `config.yaml`, `models/best.pt`, `models/movenet_multipose/`, `assets/logo.png`.
*   **Strategy:** Implement a `resource_path()` helper function in `utils.py` that dynamically checks for `sys._MEIPASS`.
    *   If running frozen (via `.exe`), resolve paths relative to `sys._MEIPASS` so bundled assets can be read correctly.
    *   If running as a plain `.py` script, fall back to standard `__file__` relative paths.

### 2. Read-Write Application Data (Portable Mode)
*   **Applies to:** 
    *   `app_state.db`
    *   `incidents.db`
    *   `benchmark.db`
    *   `runs/benchmark_sessions/` (including all PDF exports, `manifest.json`, `timeline.csv`, and graphs)
    *   Custom user profiles (`assets/profiles/` and `assets/custom/`)
    *   `.log` files
*   **Strategy:** These files must NEVER live near the temp extraction folder. We will implement a `data_path()` helper to route all persistence to a safe, fully portable location.
    *   **Target Location (Parallel to Executable):** We will resolve the base directory to the folder containing the `.exe` (`os.path.dirname(sys.executable)`). This ensures the application remains fully self-contained and portable, capable of running off a USB stick on borrowed machines without requiring write permissions to `%APPDATA%`.
    *   The `ensure_app_state()`, `init_db()`, and `ResultExporter` output root generation will all use this `data_path()` helper to guarantee no benchmark reports or incident logs are ever saved inside the ephemeral `_MEIPASS` extraction directory.
