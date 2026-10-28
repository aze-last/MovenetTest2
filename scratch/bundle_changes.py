import os
import zipfile

zip_path = "changes_today.zip"
files_to_pack = [
    "capstone_progress_report.md",
    "monitor_app/alert_manager.py",
    "monitor_app/auth.py",
    "monitor_app/camera_view.py",
    "monitor_app/central_inference.py",
    "monitor_app/events.py",
    "monitor_app/fusion.py",
    "monitor_app/incident_record.py",
    "monitor_app/incidents.py",
    "monitor_app/main.py",
    "monitor_app/profile_store.py",
    "monitor_app/reports.py",
    "monitor_app/settings.py",
    "monitor_app/assets/logo.png",
    "monitor_app/assets/logo_full.png",
    "monitor_app/assets/app_icon.ico",
    "assets/logo.png",
    "assets/app_icon.ico",
    "installer/CellWatch.iss",
    "installer/wizard_banner.bmp",
    "installer/wizard_small.bmp",
    "CellWatch.spec",
    "tests/test_live_incident_pipeline.py",
    "tests/test_dashboard_incidents_ui.py",
    "tests/test_reports_settings_ui.py",
    "tests/test_installer_prereqs.py",
    "artifacts/installer/version.json"
]

with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
    for f in files_to_pack:
        if os.path.exists(f):
            zf.write(f, arcname=f)
            print(f"Added {f} ({os.path.getsize(f)} bytes)")
        else:
            print(f"WARNING: {f} not found!")

print(f"\nUpdated {zip_path} successfully. Total size: {os.path.getsize(zip_path)} bytes.")
