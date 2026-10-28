import os
import sys
import tempfile
import shutil
import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from monitor_app import utils
from monitor_app.ai_engine import get_models_dir


class TestInstallerPrereqs:
    """Automated tests validating installer prerequisites, paths, and configurations."""

    def test_data_path_dev_routes_to_project_root(self):
        """In development mode (sys.frozen=False), data_path routes to project root."""
        orig_frozen = getattr(sys, "frozen", False)
        try:
            sys.frozen = False
            result = utils.data_path("app_state.db")
            expected = os.path.join(PROJECT_ROOT, "app_state.db")
            assert os.path.normcase(os.path.normpath(result)) == os.path.normcase(os.path.normpath(expected))
        finally:
            if orig_frozen:
                sys.frozen = orig_frozen
            elif hasattr(sys, "frozen"):
                delattr(sys, "frozen")

    def test_data_path_frozen_routes_to_localappdata(self, monkeypatch):
        """In frozen mode (sys.frozen=True), data_path routes to %LocalAppData%\\CellWatch."""
        orig_frozen = getattr(sys, "frozen", False)
        orig_exe = sys.executable
        try:
            sys.frozen = True
            sys.executable = r"C:\Program Files\CellWatch\CellWatch.exe"
            
            result = utils.data_path("app_state.db")
            assert not result.startswith(r"C:\Program Files\CellWatch")
            assert "CellWatch" in result
            assert result.endswith("app_state.db")
        finally:
            sys.executable = orig_exe
            if orig_frozen:
                sys.frozen = orig_frozen
            elif hasattr(sys, "frozen"):
                delattr(sys, "frozen")

    def test_legacy_database_and_directory_migration(self, tmp_path, monkeypatch):
        """Databases and runtime directories (recordings, exports, updates) are migrated from legacy root."""
        fake_exe_dir = tmp_path / "fake_program_files"
        fake_exe_dir.mkdir()
        fake_exe = fake_exe_dir / "CellWatch.exe"
        fake_exe.write_text("dummy binary")
        
        # Create legacy files
        legacy_db1 = fake_exe_dir / "app_state.db"
        legacy_db1.write_text("APP_STATE_V1")
        legacy_db2 = fake_exe_dir / "incidents.db"
        legacy_db2.write_text("INCIDENTS_V1")

        # Create legacy directories with content
        legacy_recs = fake_exe_dir / "recordings"
        legacy_recs.mkdir()
        (legacy_recs / "incident_001.mp4").write_text("FAKE_MP4_DATA")

        legacy_exports = fake_exe_dir / "exports"
        legacy_exports.mkdir()
        (legacy_exports / "report_001.pdf").write_text("FAKE_PDF_DATA")

        legacy_updates = fake_exe_dir / "updates"
        legacy_updates.mkdir()
        (legacy_updates / "pending.json").write_text("FAKE_UPDATE_DATA")

        fake_appdata = tmp_path / "fake_appdata"
        fake_appdata.mkdir()

        monkeypatch.setenv("LOCALAPPDATA", str(fake_appdata))
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "executable", str(fake_exe))

        # Reset migration flag
        utils._LEGACY_MIGRATION_DONE = False

        target_dir = fake_appdata / "CellWatchAI"
        migrated = utils.migrate_legacy_data(legacy_root=str(fake_exe_dir), target_root=str(target_dir))

        # Check files migrated
        assert os.path.exists(target_dir / "app_state.db")
        assert (target_dir / "app_state.db").read_text() == "APP_STATE_V1"
        assert os.path.exists(target_dir / "incidents.db")
        assert (target_dir / "incidents.db").read_text() == "INCIDENTS_V1"

        # Check directories migrated
        assert os.path.exists(target_dir / "recordings" / "incident_001.mp4")
        assert (target_dir / "recordings" / "incident_001.mp4").read_text() == "FAKE_MP4_DATA"
        assert os.path.exists(target_dir / "exports" / "report_001.pdf")
        assert (target_dir / "exports" / "report_001.pdf").read_text() == "FAKE_PDF_DATA"
        assert os.path.exists(target_dir / "updates" / "pending.json")
        assert (target_dir / "updates" / "pending.json").read_text() == "FAKE_UPDATE_DATA"

    def test_resource_path_resolves_bundled_models(self):
        """Bundled models resolve to existing files via get_models_dir()."""
        models_dir = get_models_dir()
        assert os.path.exists(models_dir)
        assert os.path.exists(os.path.join(models_dir, "movenet_multipose.onnx"))
        assert os.path.exists(os.path.join(models_dir, "best.pt"))

    def test_inno_setup_script_structure(self):
        """The Inno Setup script exists and contains necessary safety sections, hardware checks, and excludes."""
        iss_path = os.path.join(PROJECT_ROOT, "installer", "CellWatch.iss")
        assert os.path.exists(iss_path)

        with open(iss_path, "r", encoding="utf-8") as f:
            content = f.read()

        assert "[Setup]" in content
        assert "[Files]" in content
        assert "[Icons]" in content
        assert "[Run]" in content
        assert "[Code]" in content
        assert "*.db" in content
        assert "*.log" in content
        assert "NeedsVCRedist" in content
        assert "vc_redist.x64.exe" in content
        assert "CheckNvidiaGPU" in content
        assert "InitializeSetup" in content
        assert "https://www.nvidia.com/Download/index.aspx" in content
        assert "ExtraDiskSpaceRequired=2147483648" in content

    def test_pyinstaller_spec_dependencies(self):
        """CellWatch.spec excludes TensorFlow (migrated to ONNX), retains polars (required by YOLO), and bundles platformdirs."""
        spec_path = os.path.join(PROJECT_ROOT, "CellWatch.spec")
        assert os.path.exists(spec_path)

        with open(spec_path, "r", encoding="utf-8") as f:
            content = f.read()

        # TensorFlow excluded
        assert "'tensorflow'" in content
        assert "'tensorflow_hub'" in content
        assert "'tf2onnx'" in content

        # polars must NOT be excluded (ultralytics requires it)
        assert "'polars'" not in content

        # platformdirs must be bundled in hiddenimports
        assert "'platformdirs'" in content

    def test_build_script_pins_vc_redist_sha256(self):
        """scripts/build_installer.ps1 verifies pinned SHA-256 hash for vc_redist.x64.exe."""
        script_path = os.path.join(PROJECT_ROOT, "scripts", "build_installer.ps1")
        assert os.path.exists(script_path)

        with open(script_path, "r", encoding="utf-8") as f:
            content = f.read()

        assert "$ExpectedVcRedistSha256" in content
        assert "cc0ff0eb1dc3f5188ae6300faef32bf5beeba4bdd6e8e445a9184072096b713b" in content

    def test_logo_and_installer_branding_assets(self):
        """Verify new institutional logo, Windows icon, and Inno Setup wizard assets exist and have valid dimensions."""
        from PIL import Image

        # 1. Main Logo
        logo_path = os.path.join(PROJECT_ROOT, "monitor_app", "assets", "logo.png")
        assert os.path.exists(logo_path)
        with Image.open(logo_path) as img:
            assert img.format == "PNG"
            assert img.size == (512, 512)

        # 2. Windows Application Icon (.ico)
        ico_path = os.path.join(PROJECT_ROOT, "monitor_app", "assets", "app_icon.ico")
        assert os.path.exists(ico_path)
        with Image.open(ico_path) as img:
            assert img.format == "ICO"

        # 3. Inno Setup Wizard Banner
        banner_path = os.path.join(PROJECT_ROOT, "installer", "wizard_banner.bmp")
        assert os.path.exists(banner_path)
        with Image.open(banner_path) as img:
            assert img.format == "BMP"
            assert img.size == (164, 314)

        # 4. Inno Setup Wizard Small Image
        small_path = os.path.join(PROJECT_ROOT, "installer", "wizard_small.bmp")
        assert os.path.exists(small_path)
        with Image.open(small_path) as img:
            assert img.format == "BMP"
            assert img.size == (55, 55)

        # 5. Inno Setup script references
        iss_path = os.path.join(PROJECT_ROOT, "installer", "CellWatch.iss")
        with open(iss_path, "r", encoding="utf-8") as f:
            iss_text = f.read()
        assert "WizardImageFile=wizard_banner.bmp" in iss_text
        assert "WizardSmallImageFile=wizard_small.bmp" in iss_text
        assert "SetupIconFile=" in iss_text

        # 6. PyInstaller spec icon reference
        spec_path = os.path.join(PROJECT_ROOT, "CellWatch.spec")
        with open(spec_path, "r", encoding="utf-8") as f:
            spec_text = f.read()
        assert "icon='monitor_app/assets/app_icon.ico'" in spec_text
