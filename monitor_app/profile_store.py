import hashlib
import json
import os
import secrets
import shutil
import sqlite3
from datetime import datetime


from monitor_app.utils import resource_path, data_path

DB_PATH = data_path("app_state.db")
# Bundled assets (read-only)
ASSETS_DIR = resource_path("assets")
# Custom user data (read-write)
CUSTOM_ASSETS_DIR = data_path(os.path.join("assets", "custom"))
PROFILE_PHOTOS_DIR = data_path(os.path.join("assets", "profiles"))

DEFAULT_PROFILE = {
    "system_name": "CellWatch AI",
    "company_name": "Institutional Monitoring Platform",
    "logo_path": "monitor_app/assets/logo.png",
}

DEFAULT_CUSTOM_SETTINGS = {
    "conf_thr": 0.22,
    "agg_thr": 180.0,
    "active_thr": 90.0,
    "alert_frames": 3,
    "motion_threshold": 5000,
    "motion_ratio": 0.010,
    "yolo_knife_conf": 0.30,
    "yolo_cell_conf": 0.30,
    "yolo_fallback_conf": 0.50,
}

PASSWORD_ITERATIONS = 200000


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_app_state():
    os.makedirs(CUSTOM_ASSETS_DIR, exist_ok=True)
    os.makedirs(PROFILE_PHOTOS_DIR, exist_ok=True)

    conn = _connect()
    cursor = conn.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS app_profile (
            profile_id INTEGER PRIMARY KEY CHECK (profile_id = 1),
            company_name TEXT NOT NULL,
            system_name TEXT NOT NULL,
            logo_path TEXT,
            updated_at TEXT,
            updated_by TEXT
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY AUTOINCREMENT,
            digital_id TEXT NOT NULL UNIQUE,
            full_name TEXT NOT NULL,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK (role IN ('ADMIN', 'OPERATOR')),
            description TEXT DEFAULT '',
            photo_path TEXT,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            created_by TEXT,
            updated_at TEXT NOT NULL,
            updated_by TEXT,
            disabled_at TEXT,
            disabled_by TEXT
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS cameras (
            camera_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            source TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS audit_log (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            actor_user_id INTEGER,
            actor_username TEXT,
            action_type TEXT NOT NULL,
            target_type TEXT NOT NULL,
            target_id TEXT,
            details TEXT,
            created_at TEXT NOT NULL
        )
        """
    )

    cursor.execute("SELECT COUNT(*) FROM app_profile")
    if cursor.fetchone()[0] == 0:
        cursor.execute(
            """
            INSERT INTO app_profile (
                profile_id, company_name, system_name, logo_path, updated_at, updated_by
            ) VALUES (1, ?, ?, ?, ?, ?)
            """,
            (
                DEFAULT_PROFILE["company_name"],
                DEFAULT_PROFILE["system_name"],
                DEFAULT_PROFILE["logo_path"],
                _now(),
                "system",
            ),
        )

    cursor.execute("SELECT COUNT(*) FROM users")
    if cursor.fetchone()[0] == 0:
        timestamp = _now()
        cursor.execute(
            """
            INSERT INTO users (
                digital_id, full_name, username, password_hash, role, description,
                photo_path, is_active, created_at, created_by, updated_at, updated_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
            """,
            (
                "CW-2026-0001",
                "System Administrator",
                "admin",
                hash_password("admin"),
                "ADMIN",
                "Default administrator account for local system configuration.",
                None,
                timestamp,
                "system",
                timestamp,
                "system",
            ),
        )

    cursor.execute("SELECT COUNT(*) FROM cameras")
    if cursor.fetchone()[0] == 0:
        timestamp = _now()
        # Default local cameras
        defaults = [
            ("Primary Intake", "0"),
            ("Secondary Perimeter", "1")
        ]
        for name, src in defaults:
            cursor.execute(
                "INSERT INTO cameras (name, source, is_active, created_at) VALUES (?, ?, 1, ?)",
                (name, src, timestamp)
            )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_settings (
            settings_id INTEGER PRIMARY KEY CHECK (settings_id = 1),
            active_profile TEXT NOT NULL DEFAULT 'medium',
            custom_settings_json TEXT,
            updated_at TEXT,
            updated_by TEXT
        )
        """
    )

    cursor.execute("SELECT COUNT(*) FROM ai_settings")
    if cursor.fetchone()[0] == 0:
        cursor.execute(
            """
            INSERT INTO ai_settings (
                settings_id, active_profile, custom_settings_json, updated_at, updated_by
            ) VALUES (1, 'medium', ?, ?, 'system')
            """,
            (json.dumps(DEFAULT_CUSTOM_SETTINGS), _now()),
        )

    conn.commit()
    conn.close()


def hash_password(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS)
    return f"pbkdf2_sha256${PASSWORD_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password, stored_hash):
    try:
        algorithm, iterations, salt_hex, digest_hex = stored_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        computed = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            bytes.fromhex(salt_hex),
            int(iterations),
        )
        return secrets.compare_digest(computed.hex(), digest_hex)
    except Exception:
        return False


def row_to_dict(row):
    if row is None:
        return None
    data = dict(row)
    if "is_active" in data:
        data["is_active"] = bool(data["is_active"])
    data["photo_abspath"] = resolve_asset_path(data.get("photo_path"))
    if "logo_path" in data:
        data["logo_abspath"] = resolve_asset_path(data.get("logo_path"))
    return data


def resolve_asset_path(relative_path):
    if not relative_path:
        return None
    if os.path.isabs(relative_path):
        return relative_path
    
    # Check if this is a custom read-write asset
    if relative_path.startswith("assets/custom/") or relative_path.startswith("assets/profiles/"):
        # Fix slashes for windows if necessary
        return data_path(os.path.normpath(relative_path))
        
    # Fallback to bundled read-only asset
    return resource_path(os.path.normpath(relative_path))


def get_app_profile():
    ensure_app_state()
    conn = _connect()
    row = conn.execute("SELECT * FROM app_profile WHERE profile_id = 1").fetchone()
    conn.close()
    return row_to_dict(row)


def get_branding():
    profile = get_app_profile()
    return {
        "system_name": profile["system_name"],
        "company_name": profile["company_name"],
        "logo_path": profile.get("logo_path"),
        "logo_abspath": profile.get("logo_abspath"),
    }


def list_users(include_disabled=True):
    ensure_app_state()
    conn = _connect()
    query = "SELECT * FROM users"
    params = ()
    if not include_disabled:
        query += " WHERE is_active = 1"
    query += " ORDER BY full_name COLLATE NOCASE, username COLLATE NOCASE"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [row_to_dict(row) for row in rows]


def get_user_by_id(user_id):
    ensure_app_state()
    conn = _connect()
    row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
    conn.close()
    return row_to_dict(row)


def get_user_by_username(username):
    ensure_app_state()
    conn = _connect()
    row = conn.execute("SELECT * FROM users WHERE username = ?", (username.strip(),)).fetchone()
    conn.close()
    return row_to_dict(row)


def authenticate_user(username, password):
    ensure_app_state()
    normalized_username = username.strip()
    if not normalized_username or not password:
        return None, "Enter both username and password."

    conn = _connect()
    row = conn.execute("SELECT * FROM users WHERE username = ?", (normalized_username,)).fetchone()
    conn.close()

    if row is None:
        return None, "Invalid credentials. Please use an authorized operator account."

    user = row_to_dict(row)
    if not user["is_active"]:
        return None, "This account has been disabled. Contact an administrator."

    if not verify_password(password, user["password_hash"]):
        return None, "Invalid credentials. Please use an authorized operator account."

    record_audit_event(
        actor_user_id=user["user_id"],
        actor_username=user["username"],
        action_type="LOGIN_SUCCESS",
        target_type="USER",
        target_id=str(user["user_id"]),
        details=f"Authenticated as {user['role']}.",
    )
    return user, None


def update_app_profile(company_name, system_name, logo_source_path=None, actor_username=None):
    ensure_app_state()
    company_name = (company_name or "").strip()
    system_name = (system_name or "").strip()

    if not company_name:
        raise ValueError("Company name is required.")
    if not system_name:
        raise ValueError("System name is required.")

    profile = get_app_profile()
    logo_path = profile.get("logo_path")
    if logo_source_path:
        logo_path = _copy_logo_asset(logo_source_path)

    conn = _connect()
    conn.execute(
        """
        UPDATE app_profile
        SET company_name = ?, system_name = ?, logo_path = ?, updated_at = ?, updated_by = ?
        WHERE profile_id = 1
        """,
        (company_name, system_name, logo_path, _now(), actor_username or "system"),
    )
    conn.commit()
    conn.close()

    record_audit_event(
        actor_username=actor_username,
        action_type="PROFILE_UPDATE",
        target_type="APP_PROFILE",
        target_id="1",
        details=f"Updated branding to system='{system_name}', company='{company_name}'.",
    )
    return get_app_profile()


def create_user(
    full_name,
    username,
    password,
    role,
    description="",
    photo_source_path=None,
    actor_username=None,
):
    ensure_app_state()
    full_name = (full_name or "").strip()
    username = (username or "").strip()
    role = (role or "").strip().upper()
    description = (description or "").strip()

    if not full_name:
        raise ValueError("Full name is required.")
    if not username:
        raise ValueError("Username is required.")
    if not password:
        raise ValueError("Password is required for a new account.")
    if not description:
        raise ValueError("Description is required for a new account.")
    if not photo_source_path:
        raise ValueError("Profile photo is required for a new account.")
    if role not in {"ADMIN", "OPERATOR"}:
        raise ValueError("Role must be ADMIN or OPERATOR.")
    if get_user_by_username(username):
        raise ValueError("Username is already in use.")

    conn = _connect()
    cursor = conn.cursor()
    digital_id = _generate_digital_id(cursor)
    timestamp = _now()

    cursor.execute(
        """
        INSERT INTO users (
            digital_id, full_name, username, password_hash, role, description,
            photo_path, is_active, created_at, created_by, updated_at, updated_by
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
        """,
        (
            digital_id,
            full_name,
            username,
            hash_password(password),
            role,
            description,
            None,
            timestamp,
            actor_username or "system",
            timestamp,
            actor_username or "system",
        ),
    )
    user_id = cursor.lastrowid

    photo_path = None
    if photo_source_path:
        photo_path = _copy_profile_photo(photo_source_path, user_id)
        cursor.execute("UPDATE users SET photo_path = ? WHERE user_id = ?", (photo_path, user_id))

    conn.commit()
    conn.close()

    record_audit_event(
        actor_username=actor_username,
        action_type="USER_CREATE",
        target_type="USER",
        target_id=str(user_id),
        details=f"Created {role} account '{username}' with digital ID {digital_id}.",
    )
    return get_user_by_id(user_id)


def update_user(
    user_id,
    full_name,
    username,
    role,
    description="",
    photo_source_path=None,
    password=None,
    actor_username=None,
):
    ensure_app_state()
    current = get_user_by_id(user_id)
    if current is None:
        raise ValueError("User account not found.")

    full_name = (full_name or "").strip()
    username = (username or "").strip()
    role = (role or "").strip().upper()
    description = (description or "").strip()

    if not full_name:
        raise ValueError("Full name is required.")
    if not username:
        raise ValueError("Username is required.")
    if role not in {"ADMIN", "OPERATOR"}:
        raise ValueError("Role must be ADMIN or OPERATOR.")

    existing = get_user_by_username(username)
    if existing and existing["user_id"] != user_id:
        raise ValueError("Username is already in use.")

    photo_path = current.get("photo_path")
    if photo_source_path:
        photo_path = _copy_profile_photo(photo_source_path, user_id)

    conn = _connect()
    conn.execute(
        """
        UPDATE users
        SET full_name = ?, username = ?, role = ?, description = ?, photo_path = ?,
            updated_at = ?, updated_by = ?
        WHERE user_id = ?
        """,
        (
            full_name,
            username,
            role,
            description,
            photo_path,
            _now(),
            actor_username or "system",
            user_id,
        ),
    )

    if password:
        conn.execute(
            """
            UPDATE users
            SET password_hash = ?, updated_at = ?, updated_by = ?
            WHERE user_id = ?
            """,
            (hash_password(password), _now(), actor_username or "system", user_id),
        )

    conn.commit()
    conn.close()

    record_audit_event(
        actor_username=actor_username,
        action_type="USER_UPDATE",
        target_type="USER",
        target_id=str(user_id),
        details=f"Updated account '{username}'.",
    )
    return get_user_by_id(user_id)


def disable_user(user_id, actor_username=None):
    ensure_app_state()
    user = get_user_by_id(user_id)
    if user is None:
        raise ValueError("User account not found.")
    if not user["is_active"]:
        raise ValueError("User account is already disabled.")

    conn = _connect()
    if user["role"] == "ADMIN":
        active_admins = conn.execute(
            "SELECT COUNT(*) FROM users WHERE role = 'ADMIN' AND is_active = 1"
        ).fetchone()[0]
        if active_admins <= 1:
            conn.close()
            raise ValueError("At least one active admin account must remain.")

    conn.execute(
        """
        UPDATE users
        SET is_active = 0, disabled_at = ?, disabled_by = ?, updated_at = ?, updated_by = ?
        WHERE user_id = ?
        """,
        (_now(), actor_username or "system", _now(), actor_username or "system", user_id),
    )
    conn.commit()
    conn.close()

    record_audit_event(
        actor_username=actor_username,
        action_type="USER_DISABLE",
        target_type="USER",
        target_id=str(user_id),
        details=f"Disabled account '{user['username']}'.",
    )
    return get_user_by_id(user_id)


def record_audit_event(
    action_type,
    target_type,
    target_id=None,
    details=None,
    actor_username=None,
    actor_user_id=None,
):
    ensure_app_state()
    conn = _connect()
    conn.execute(
        """
        INSERT INTO audit_log (
            actor_user_id, actor_username, action_type, target_type, target_id, details, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            actor_user_id,
            actor_username,
            action_type,
            target_type,
            target_id,
            details,
            _now(),
        ),
    )
    conn.commit()
    conn.close()


def get_display_name(user):
    if not user:
        return "Unknown"
    return user.get("full_name") or user.get("username") or "Unknown"


def _generate_digital_id(cursor):
    year = datetime.now().year
    sequence = 1
    while True:
        digital_id = f"CW-{year}-{sequence:04d}"
        existing = cursor.execute(
            "SELECT 1 FROM users WHERE digital_id = ?",
            (digital_id,),
        ).fetchone()
        if existing is None:
            return digital_id
        sequence += 1


def _copy_logo_asset(source_path):
    extension = os.path.splitext(source_path)[1].lower() or ".png"
    relative_path = os.path.join("assets", "custom", f"brand_logo{extension}")
    absolute_path = os.path.join(BASE_DIR, relative_path)
    shutil.copy2(source_path, absolute_path)
    return relative_path


def _copy_profile_photo(source_path, user_id):
    extension = os.path.splitext(source_path)[1].lower() or ".png"
    relative_path = os.path.join("assets", "profiles", f"user_{user_id}{extension}")
    absolute_path = os.path.join(BASE_DIR, relative_path)
    shutil.copy2(source_path, absolute_path)
    return relative_path


# --- CAMERA CRUD FUNCTIONS ---

def list_cameras(include_inactive=False):
    ensure_app_state()
    conn = _connect()
    query = "SELECT * FROM cameras"
    if not include_inactive:
        query += " WHERE is_active = 1"
    rows = conn.execute(query).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def add_camera(name, source, actor_username=None):
    ensure_app_state()
    name = (name or "").strip()
    source = (source or "").strip()
    if not name or not source:
        raise ValueError("Camera name and source are required.")

    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO cameras (name, source, is_active, created_at) VALUES (?, ?, 1, ?)",
        (name, source, _now())
    )
    cam_id = cursor.lastrowid
    conn.commit()
    conn.close()

    record_audit_event(
        actor_username=actor_username,
        action_type="CAMERA_CREATE",
        target_type="CAMERA",
        target_id=str(cam_id),
        details=f"Added camera '{name}' with source '{source}'.",
    )
    return cam_id


def update_camera(camera_id, name, source, is_active=1, actor_username=None):
    ensure_app_state()
    name = (name or "").strip()
    source = (source or "").strip()
    if not name or not source:
        raise ValueError("Camera name and source are required.")

    conn = _connect()
    conn.execute(
        "UPDATE cameras SET name = ?, source = ?, is_active = ? WHERE camera_id = ?",
        (name, source, int(is_active), camera_id)
    )
    conn.commit()
    conn.close()

    record_audit_event(
        actor_username=actor_username,
        action_type="CAMERA_UPDATE",
        target_type="CAMERA",
        target_id=str(camera_id),
        details=f"Updated camera ID {camera_id} (name='{name}', source='{source}').",
    )


def delete_camera(camera_id, actor_username=None):
    ensure_app_state()
    conn = _connect()
    # Check if exists
    row = conn.execute("SELECT name FROM cameras WHERE camera_id = ?", (camera_id,)).fetchone()
    if not row:
        conn.close()
        raise ValueError("Camera not found.")
    
    name = row["name"]
    conn.execute("DELETE FROM cameras WHERE camera_id = ?", (camera_id,))
    conn.commit()
    conn.close()

    record_audit_event(
        actor_username=actor_username,
        action_type="CAMERA_DELETE",
        target_type="CAMERA",
        target_id=str(camera_id),
        details=f"Deleted camera '{name}' (ID {camera_id}).",
    )


# ==========================================
# AI SETTINGS PERSISTENCE
# ==========================================
def get_ai_settings():
    """Return dict with active_profile and parsed custom_settings."""
    ensure_app_state()
    conn = _connect()
    row = conn.execute(
        "SELECT active_profile, custom_settings_json FROM ai_settings WHERE settings_id = 1"
    ).fetchone()
    conn.close()
    if row is None:
        return {"active_profile": "medium", "custom_settings": DEFAULT_CUSTOM_SETTINGS.copy()}
    custom = DEFAULT_CUSTOM_SETTINGS.copy()
    if row["custom_settings_json"]:
        try:
            custom.update(json.loads(row["custom_settings_json"]))
        except (json.JSONDecodeError, TypeError):
            pass
    return {"active_profile": row["active_profile"], "custom_settings": custom}


def save_ai_settings(active_profile, custom_settings=None, actor_username=None):
    """Persist the selected profile and optional custom JSON blob."""
    ensure_app_state()
    custom_json = json.dumps(custom_settings) if custom_settings else None
    conn = _connect()
    conn.execute(
        """
        UPDATE ai_settings
        SET active_profile = ?, custom_settings_json = ?, updated_at = ?, updated_by = ?
        WHERE settings_id = 1
        """,
        (active_profile, custom_json, _now(), actor_username or "system"),
    )
    conn.commit()
    conn.close()
    record_audit_event(
        actor_username=actor_username,
        action_type="AI_SETTINGS_UPDATE",
        target_type="AI_SETTINGS",
        target_id="1",
        details=f"Profile changed to '{active_profile}'.",
    )

