from __future__ import annotations

import asyncio
import json
import os
import queue
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Callable

import requests
from fastapi import FastAPI, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field


STATE_DIR = Path(os.environ.get("APP_STATE_DIR", "/var/lib/mister-companion-web"))
CONFIG_DIR = Path(os.environ.get("APP_CONFIG_DIR", str(STATE_DIR)))
DATA_DIR = Path(os.environ.get("APP_DATA_DIR", str(STATE_DIR)))
APP_ROOT = Path(os.environ.get("APP_ROOT", "/opt/mister-companion-web/app"))
UPSTREAM_DIR = Path(
    os.environ.get(
        "UPSTREAM_DIR",
        str(APP_ROOT / "vendor" / "mister-companion" / "mister-companion"),
    )
)
FRONTEND_DIST = Path(os.environ.get("FRONTEND_DIST", str(APP_ROOT / "frontend" / "dist")))
FLASH_HELPER_URL = os.environ.get("FLASH_HELPER_URL", "http://192.168.2.22:18080").rstrip("/")
FLASH_HELPER_DATA_PREFIX = os.environ.get(
    "FLASH_HELPER_DATA_PREFIX",
    "/srv/vm-data/mister-companion-web/var-lib",
)
FLASH_HELPER_TOKEN_FILE = Path(
    os.environ.get("FLASH_HELPER_TOKEN_FILE", str(CONFIG_DIR / "flash-helper-token"))
)

STATE_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)
(DATA_DIR / "logs").mkdir(exist_ok=True)
(DATA_DIR / "downloads").mkdir(exist_ok=True)
(DATA_DIR / "backups").mkdir(exist_ok=True)
(DATA_DIR / "cache").mkdir(exist_ok=True)
os.chdir(CONFIG_DIR)

if UPSTREAM_DIR.exists():
    sys.path.insert(0, str(UPSTREAM_DIR))

try:
    from core.app_info import APP_NAME, APP_VERSION
    from core.config import load_config, save_config
    from core.connection import MiSTerConnection
    from core.device_actions import (
        disable_smb_offline,
        disable_smb_remote,
        enable_smb_offline,
        enable_smb_remote,
        get_sd_storage_info,
        get_sd_storage_info_offline,
        get_usb_storage_info,
        is_smb_enabled,
        is_smb_enabled_offline,
        return_to_menu_remote,
    )
    from core.device_profiles import (
        add_device,
        delete_device,
        get_device_by_index,
        get_devices,
        update_device,
    )
except Exception as exc:  # pragma: no cover - surfaced by /api/health
    APP_NAME = "MiSTer Companion"
    APP_VERSION = "unknown"
    MiSTerConnection = None  # type: ignore[assignment]
    IMPORT_ERROR = str(exc)
else:
    IMPORT_ERROR = ""


app = FastAPI(title="MiSTer Companion Web", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

connection = MiSTerConnection() if MiSTerConnection else None
state_lock = threading.RLock()
state_path = CONFIG_DIR / "web-state.json"
profiles_path = CONFIG_DIR / "profiles.json"


def app_config() -> dict[str, Any]:
    if IMPORT_ERROR:
        raise HTTPException(status_code=500, detail=IMPORT_ERROR)
    return load_config()


def load_state() -> dict[str, Any]:
    if not state_path.exists():
        return {"mode": "online", "offline_sd_root": "", "ra": {}}
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"mode": "online", "offline_sd_root": "", "ra": {}}
        data.setdefault("mode", "online")
        data.setdefault("offline_sd_root", "")
        data.setdefault("ra", {})
        return data
    except Exception:
        return {"mode": "online", "offline_sd_root": "", "ra": {}}


def save_state(data: dict[str, Any]) -> dict[str, Any]:
    with state_lock:
        state_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return data


runtime_state = load_state()


def _profile_id() -> str:
    return uuid.uuid4().hex[:12]


def _redact_profile(profile: dict[str, Any]) -> dict[str, Any]:
    public = dict(profile)
    public["has_password"] = bool(public.get("password"))
    public.pop("password", None)
    public.setdefault("id", _profile_id())
    public.setdefault("name", public.get("host") or public.get("ip") or "MiSTer")
    public.setdefault("host", public.get("ip") or "")
    public.setdefault("username", "root")
    return public


def load_profiles_private() -> list[dict[str, Any]]:
    if profiles_path.exists():
        try:
            data = json.loads(profiles_path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return [p for p in data if isinstance(p, dict)]
        except Exception:
            pass

    profiles: list[dict[str, Any]] = []
    if not IMPORT_ERROR:
        try:
            for device in get_devices(app_config()):
                item = dict(device)
                item["id"] = item.get("id") or _profile_id()
                item["host"] = item.get("host") or item.get("ip") or ""
                item["username"] = item.get("username") or "root"
                profiles.append(item)
        except Exception:
            profiles = []
    save_profiles_private(profiles)
    return profiles


def save_profiles_private(profiles: list[dict[str, Any]]) -> None:
    profiles_path.write_text(json.dumps(profiles, indent=2), encoding="utf-8")


def public_profiles() -> list[dict[str, Any]]:
    return [_redact_profile(profile) for profile in load_profiles_private()]


def find_profile_private(profile_id: str) -> dict[str, Any]:
    for profile in load_profiles_private():
        if str(profile.get("id")) == profile_id:
            return profile
    raise HTTPException(status_code=404, detail="Profile not found")


def is_connected() -> bool:
    return bool(connection and connection.is_connected())


def is_offline() -> bool:
    return runtime_state.get("mode") == "offline"


def require_connected() -> Any:
    if not connection or not connection.is_connected():
        raise HTTPException(status_code=409, detail="Not connected to MiSTer")
    return connection


def require_sd_root() -> Path:
    root = Path(str(runtime_state.get("offline_sd_root") or "")).expanduser()
    if not root.exists() or not root.is_dir():
        raise HTTPException(status_code=409, detail="Offline SD root is not available")
    return root


def remote_to_local(sd_root: Path, remote_path: str) -> Path:
    normalized = remote_path.replace("\\", "/")
    if normalized == "/media/fat":
        rel = ""
    elif normalized.startswith("/media/fat/"):
        rel = normalized[len("/media/fat/") :]
    else:
        rel = normalized.lstrip("/")
    return sd_root / rel


def sftp_read_text(remote_path: str) -> str:
    conn = require_connected()
    sftp = conn.client.open_sftp()
    try:
        with sftp.open(remote_path, "r") as handle:
            data = handle.read()
            if isinstance(data, bytes):
                return data.decode("utf-8", errors="ignore")
            return str(data)
    finally:
        sftp.close()


def sftp_write_text(remote_path: str, text: str) -> None:
    conn = require_connected()
    sftp = conn.client.open_sftp()
    try:
        parent = str(PurePosixPath(remote_path).parent)
        conn.run_command(f'mkdir -p "{parent}"')
        with sftp.open(remote_path, "w") as handle:
            handle.write(text)
    finally:
        sftp.close()


def sftp_exists(remote_path: str) -> bool:
    conn = require_connected()
    sftp = conn.client.open_sftp()
    try:
        try:
            sftp.stat(remote_path)
            return True
        except Exception:
            return False
    finally:
        sftp.close()


INI_SETTINGS_SCHEMA: list[dict[str, Any]] = [
    {
        "key": "video_mode",
        "label": "Primary video mode",
        "category": "Video output",
        "type": "select",
        "options": [
            {"value": "", "label": "Auto-detect display"},
            {"value": "0", "label": "1280x720 @ 60Hz"},
            {"value": "7", "label": "1280x720 @ 50Hz"},
            {"value": "8", "label": "1920x1080 @ 60Hz"},
            {"value": "9", "label": "1920x1080 @ 50Hz"},
            {"value": "14", "label": "2560x1440 @ 60Hz"},
            {"value": "6", "label": "640x480 @ 60Hz"},
        ],
        "description": "Choose the base HDMI output resolution and refresh rate. Leave it on auto when your display negotiates correctly; set a fixed mode when a TV, capture card, scaler, or monitor needs a predictable signal.",
    },
    {
        "key": "vsync_adjust",
        "label": "VSync adjust",
        "category": "Video output",
        "type": "select",
        "options": [
            {"value": "0", "label": "Off / most compatible"},
            {"value": "1", "label": "Smooth original refresh"},
            {"value": "2", "label": "Low latency single buffer"},
        ],
        "description": "Allows MiSTer to bend the HDMI pixel clock so cores can run at their original refresh rate. Use 1 for smooth motion on tolerant displays, 2 when you want the lowest latency and your display can handle it.",
    },
    {"key": "video_mode_ntsc", "label": "NTSC base video mode", "category": "Video output", "type": "text", "description": "Optional fallback mode used when VSync adjust switches to NTSC-like refresh rates. This is useful for picky displays that need separate 50Hz and 60Hz base timings."},
    {"key": "video_mode_pal", "label": "PAL base video mode", "category": "Video output", "type": "text", "description": "Optional fallback mode used when VSync adjust switches to PAL-like refresh rates. Set this when 50Hz content needs a different stable HDMI mode than 60Hz content."},
    {"key": "refresh_min", "label": "Minimum adaptive refresh", "category": "Video output", "type": "text", "description": "Prevents VSync adjust from going below a refresh rate your display cannot show. Leave at 0 unless PAL/NTSC switching makes your screen drop out."},
    {"key": "refresh_max", "label": "Maximum adaptive refresh", "category": "Video output", "type": "text", "description": "Prevents VSync adjust from going above a refresh rate your display cannot show. This helps monitors or capture devices that dislike unusual arcade refresh rates."},
    {
        "key": "vscale_mode",
        "label": "Vertical scale",
        "category": "Scaling and picture",
        "type": "select",
        "options": [
            {"value": "0", "label": "Fit screen"},
            {"value": "1", "label": "Integer scale only"},
            {"value": "2", "label": "Half-step scaling"},
            {"value": "3", "label": "Quarter-step scaling"},
            {"value": "4", "label": "Integer using core aspect"},
            {"value": "5", "label": "Integer using display aspect"},
        ],
        "description": "Controls how aggressively MiSTer scales each core vertically. Integer modes keep pixels sharp, while fit modes fill more of the screen.",
    },
    {"key": "vscale_border", "label": "Vertical overscan border", "category": "Scaling and picture", "type": "text", "description": "Adds a top and bottom safety border for displays that crop the image. CRT-style TVs and some flat panels benefit from this when menu text is cut off."},
    {"key": "video_info", "label": "Show video info overlay", "category": "Scaling and picture", "type": "text", "description": "Shows the current video mode for a few seconds after startup or mode changes. Handy while tuning a display, usually left at 0 once everything works."},
    {"key": "video_brightness", "label": "Brightness", "category": "Scaling and picture", "type": "text", "description": "Adjusts HDMI brightness from the MiSTer side. Keep the default unless your display cannot be calibrated cleanly."},
    {"key": "video_contrast", "label": "Contrast", "category": "Scaling and picture", "type": "text", "description": "Adjusts HDMI contrast before the signal reaches the display. Useful for capture setups or screens with limited picture controls."},
    {"key": "video_saturation", "label": "Saturation", "category": "Scaling and picture", "type": "text", "description": "Controls color intensity. Lower values can tame oversaturated TVs; higher values are mostly for personal preference."},
    {"key": "video_hue", "label": "Hue", "category": "Scaling and picture", "type": "text", "description": "Rotates HDMI color hue. Most users should leave this at 0 unless correcting a specific display or capture chain."},
    {"key": "video_gain_offset", "label": "RGB gain and offset", "category": "Scaling and picture", "type": "text", "description": "Advanced RGB correction using gain and offset pairs. This is for careful display calibration, capture profiles, or special color workflows."},
    {"key": "hdmi_limited", "label": "HDMI limited color range", "category": "HDMI and audio", "type": "select", "options": [{"value": "0", "label": "Full range RGB"}, {"value": "1", "label": "Limited 16-235"}, {"value": "2", "label": "Limited 16-255"}], "description": "Changes the HDMI color range. Use limited range when black levels look crushed or washed out on a TV; keep full range for monitors and most capture devices."},
    {"key": "dvi_mode", "label": "DVI mode", "category": "HDMI and audio", "type": "checkbox", "description": "Disables HDMI audio and behaves like DVI. Use this only for older monitors or adapters that fail with normal HDMI negotiation."},
    {"key": "hdmi_audio_96k", "label": "96 kHz HDMI audio", "category": "HDMI and audio", "type": "checkbox", "description": "Raises HDMI audio output to 96 kHz. Leave it off unless your audio chain expects 96 kHz and you have confirmed compatibility."},
    {"key": "hdr", "label": "HDR mode", "category": "HDMI and audio", "type": "select", "options": [{"value": "0", "label": "Off"}, {"value": "1", "label": "HLG HDR"}, {"value": "2", "label": "DCI-P3 HDR"}], "description": "Enables HDR metadata on HDMI. This is mainly for modern HDR displays and needs picture tuning; SDR setups should keep it disabled."},
    {"key": "hdr_max_nits", "label": "HDR peak brightness", "category": "HDMI and audio", "type": "text", "description": "Sets HDR peak brightness metadata. Match this to your display's real peak brightness to avoid clipped highlights."},
    {"key": "hdr_avg_nits", "label": "HDR average brightness", "category": "HDMI and audio", "type": "text", "description": "Sets HDR average brightness metadata. A value around one quarter of peak brightness is a sane starting point."},
    {"key": "direct_video", "label": "Direct Video over HDMI", "category": "Analog and CRT", "type": "select", "options": [{"value": "0", "label": "Off"}, {"value": "1", "label": "Direct Video"}, {"value": "2", "label": "Auto for HDMI DACs"}], "description": "Sends core-native timings through HDMI for DACs and CRT/scaler workflows. Do not enable this for normal TVs unless you are using a known Direct Video adapter."},
    {"key": "vga_mode", "label": "VGA output mode", "category": "Analog and CRT", "type": "select", "options": [{"value": "rgb", "label": "RGB"}, {"value": "ypbpr", "label": "YPbPr component"}, {"value": "svideo", "label": "S-Video"}, {"value": "cvbs", "label": "Composite"}, {"value": "subcarrier", "label": "Subcarrier"}], "description": "Chooses the analog signal format for the VGA/IO-board output. This matters for CRTs, component cables, and external analog converters."},
    {"key": "ypbpr", "label": "Legacy YPbPr toggle", "category": "Analog and CRT", "type": "checkbox", "description": "Older MiSTer.ini files used this for component output. Prefer VGA output mode on current setups, but this remains available for compatibility."},
    {"key": "ntsc_mode", "label": "NTSC composite mode", "category": "Analog and CRT", "type": "select", "options": [{"value": "0", "label": "Normal NTSC"}, {"value": "1", "label": "PAL-60"}, {"value": "2", "label": "PAL-M"}], "description": "Changes color encoding for S-Video or composite output. Only use it when working with analog video gear."},
    {"key": "composite_sync", "label": "Composite sync on VGA", "category": "Analog and CRT", "type": "checkbox", "description": "Combines sync onto the HSync line for equipment that expects composite sync. CRT monitors and RGB scalers may need this."},
    {"key": "vga_scaler", "label": "Scaler on VGA", "category": "Analog and CRT", "type": "checkbox", "description": "Routes the scaler to VGA output instead of raw core timings. Use it for VGA monitors or scalers that need a stable PC-like resolution."},
    {"key": "vga_sog", "label": "Sync on green", "category": "Analog and CRT", "type": "checkbox", "description": "Enables sync-on-green for compatible analog IO boards and displays. Only enable this if your monitor or cable chain explicitly requires it."},
    {"key": "fb_size", "label": "Framebuffer size", "category": "Menu and OSD", "type": "select", "options": [{"value": "0", "label": "Automatic"}, {"value": "1", "label": "Full size"}, {"value": "2", "label": "Half size"}, {"value": "4", "label": "Quarter size"}], "description": "Controls menu framebuffer memory usage. Automatic is best unless you are diagnosing menu performance or memory pressure."},
    {"key": "fb_terminal", "label": "Framebuffer terminal", "category": "Menu and OSD", "type": "checkbox", "description": "Keeps the framebuffer terminal available. Most users leave this enabled because it helps with diagnostics and scripts."},
    {"key": "osd_timeout", "label": "OSD timeout", "category": "Menu and OSD", "type": "text", "description": "Sets how long the menu OSD remains visible before fading or hiding. Use 0 if you never want it to time out."},
    {"key": "osd_rotate", "label": "OSD rotation", "category": "Menu and OSD", "type": "select", "options": [{"value": "0", "label": "No rotation"}, {"value": "1", "label": "Rotate right"}, {"value": "2", "label": "Rotate left"}], "description": "Rotates the on-screen display. This is useful for vertical cabinets, rotated monitors, or specialty arcade builds."},
    {"key": "video_off", "label": "Menu video blank timeout", "category": "Menu and OSD", "type": "text", "description": "Blanks the menu output after a period of inactivity. Use it to reduce burn-in risk on OLEDs or arcade monitors."},
    {"key": "video_off_hdmi", "label": "Power down HDMI when blanked", "category": "Menu and OSD", "type": "checkbox", "description": "Lets the display sleep when menu video blanking triggers. Useful for TVs, but disable it if your capture device or monitor reconnects slowly."},
    {"key": "menu_pal", "label": "PAL menu mode", "category": "Menu and OSD", "type": "checkbox", "description": "Runs the menu core in PAL timing. This is mainly for PAL displays or regional CRT setups."},
    {"key": "logo", "label": "Show MiSTer logo", "category": "Menu and OSD", "type": "checkbox", "description": "Shows or hides the MiSTer logo in the menu core. This is a cosmetic choice for clean cabinets or custom themes."},
    {"key": "lookahead", "label": "Menu list lookahead", "category": "Menu and OSD", "type": "text", "description": "Scrolls lists earlier as the cursor approaches the top or bottom. Increase it if long game lists feel cramped."},
    {"key": "rbf_hide_datecode", "label": "Hide core date codes", "category": "Menu and OSD", "type": "checkbox", "description": "Hides build dates from core file names in menus. Useful when you want cleaner lists and do not need to compare core versions at a glance."},
    {"key": "recents", "label": "Recent items menu", "category": "Boot and navigation", "type": "checkbox", "description": "Tracks recently opened files and mounted media. It makes repeated play faster, but it writes to the SD card whenever content is loaded."},
    {"key": "bootcore", "label": "Autoboot core", "category": "Boot and navigation", "type": "text", "description": "Starts a specific core, the last core, or an exact core automatically after boot. Useful for dedicated cabinets or family-friendly single-system setups."},
    {"key": "bootcore_timeout", "label": "Autoboot delay", "category": "Boot and navigation", "type": "text", "description": "Adds a countdown before autobooting the selected core. Set a delay when you still want time to interrupt boot and open the menu."},
    {"key": "bootscreen", "label": "Core boot screens", "category": "Boot and navigation", "type": "checkbox", "description": "Controls boot screens for cores that support it. Disable when you prefer faster or cleaner startup."},
    {"key": "key_menu_as_rgui", "label": "Menu key as right GUI", "category": "Input", "type": "checkbox", "description": "Maps the menu key to right GUI in cores such as Minimig. This is mostly for Amiga keyboard layouts and Keyrah-style setups."},
    {"key": "reset_combo", "label": "Reset key combo", "category": "Input", "type": "select", "options": [{"value": "0", "label": "LCtrl + LAlt + RAlt"}, {"value": "1", "label": "LCtrl + LGUI + RGUI"}, {"value": "2", "label": "LCtrl + LAlt + Del"}, {"value": "3", "label": "Legacy combo"}], "description": "Defines the keyboard shortcut that emulates the USER/reset button. Pick the combo that does not conflict with your keyboard or cabinet controls."},
    {"key": "controller_info", "label": "Controller info overlay", "category": "Input", "type": "text", "description": "Shows controller button mapping briefly after the first button press. Keep it on while setting up controllers, then reduce or disable it for a cleaner experience."},
    {"key": "jamma_vid", "label": "JAMMA primary VID", "category": "Input", "type": "text", "description": "Identifies a JAMMA/J-PAC/I-PAC style controller interface for automatic player mapping. Only set this for arcade cabinets with known USB VID/PID values."},
    {"key": "jamma_pid", "label": "JAMMA primary PID", "category": "Input", "type": "text", "description": "Pairs with JAMMA primary VID to map cabinet controls predictably. Leave it alone unless you know the device PID."},
    {"key": "jamma2_vid", "label": "JAMMA secondary VID", "category": "Input", "type": "text", "description": "Optional second cabinet controller interface for players 3 and 4. Useful for larger arcade builds."},
    {"key": "jamma2_pid", "label": "JAMMA secondary PID", "category": "Input", "type": "text", "description": "Pairs with JAMMA secondary VID for multi-player cabinet wiring. Leave default unless your second encoder is known."},
    {"key": "no_merge_vid", "label": "Do not merge VID", "category": "Input", "type": "text", "description": "Stops MiSTer from merging devices with a matching vendor ID. Use this when only player one works because multiple controllers are being treated as one."},
    {"key": "no_merge_pid", "label": "Do not merge PID", "category": "Input", "type": "text", "description": "Narrows no-merge behavior to a specific product ID. Leave empty if all devices from the vendor should stay separate."},
    {"key": "sniper_mode", "label": "Mouse sniper mode behavior", "category": "Input", "type": "checkbox", "description": "Swaps mouse emulation speed behavior between normal and sniper modes. Useful for cores where analog aiming feels reversed or awkward."},
    {"key": "mouse_throttle", "label": "Mouse throttle", "category": "Input", "type": "text", "description": "Divides mouse speed for very sensitive mice or adapters. Increase it if pointer movement is too fast in mouse-driven cores."},
    {"key": "spinner_vid", "label": "Spinner mouse VID", "category": "Input", "type": "text", "description": "Treats a specific mouse X axis as a spinner or paddle. This is for arcade controls and specialty input devices."},
    {"key": "spinner_pid", "label": "Spinner mouse PID", "category": "Input", "type": "text", "description": "Pairs with spinner VID to identify the mouse or adapter. Use FFFF/FFFF only when every mouse should act as a spinner."},
    {"key": "spinner_throttle", "label": "Spinner throttle", "category": "Input", "type": "text", "description": "Adjusts spinner sensitivity and direction. Negative values reverse direction, higher values slow the spinner down."},
    {"key": "debug", "label": "Debug logging", "category": "Advanced system", "type": "checkbox", "description": "Enables additional MiSTer debug messages. Use it temporarily while troubleshooting; leave it off for normal use."},
    {"key": "forced_scandoubler", "label": "Force scandoubler", "category": "Advanced system", "type": "checkbox", "description": "Forces scandoubler behavior on VGA output where supported by cores. This is for display compatibility experiments, not a normal HDMI setting."},
    {"key": "shared_folder", "label": "Shared folder path", "category": "Advanced system", "type": "text", "description": "Sets a custom shared folder for cores that support one, such as Minimig or ao486. The path must exist before the core starts."},
    {"key": "browse_expand", "label": "Expand long filenames", "category": "Advanced system", "type": "checkbox", "description": "Controls whether long filenames can use a second line in file lists. Disable it if you prefer denser menus."},
    {"key": "font", "label": "Custom menu font", "category": "Advanced system", "type": "text", "description": "Loads a custom 8x8 bitmap font. This is for theme builders and cabinet polish rather than normal setup."},
    {"key": "keyrah_mode", "label": "Keyrah VID/PID mode", "category": "Advanced system", "type": "text", "description": "Applies special key translation for Keyrah-style keyboard adapters. Set this only when using supported retro keyboard hardware."},
]


def parse_ini_values(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", ";", "[")) or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.split(";", 1)[0].split("#", 1)[0].strip()
    return values


def update_ini_values(text: str, values: dict[str, str]) -> str:
    pending = {key: str(value) for key, value in values.items()}
    output: list[str] = []
    seen: set[str] = set()
    pattern = re.compile(r"^(\s*)([A-Za-z0-9_]+)(\s*=\s*)(.*?)(\s*(?:[;#].*)?)$")
    for line in text.splitlines():
        match = pattern.match(line)
        if match and match.group(2) in pending:
            key = match.group(2)
            output.append(f"{match.group(1)}{key}{match.group(3)}{pending[key]}{match.group(5)}")
            seen.add(key)
        else:
            output.append(line)
    for key, value in pending.items():
        if key not in seen:
            output.append(f"{key}={value}")
    return "\n".join(output) + ("\n" if text.endswith("\n") else "")


class Job:
    def __init__(self, label: str):
        self.id = uuid.uuid4().hex
        self.label = label
        self.status = "queued"
        self.created_at = datetime.utcnow().isoformat() + "Z"
        self.updated_at = self.created_at
        self.exit_code: int | None = None
        self.error: str | None = None
        self.logs: list[str] = []
        self.events: queue.Queue[str] = queue.Queue()
        self.cancel_requested = False
        self.lock = threading.RLock()

    def log(self, message: str) -> None:
        text = str(message)
        with self.lock:
            self.logs.append(text)
            self.updated_at = datetime.utcnow().isoformat() + "Z"
        self.events.put(text)

    def set_status(self, status: str, error: str | None = None, exit_code: int | None = None) -> None:
        with self.lock:
            self.status = status
            self.error = error
            self.exit_code = exit_code
            self.updated_at = datetime.utcnow().isoformat() + "Z"
        self.events.put(f"__status__:{status}")

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {
                "id": self.id,
                "label": self.label,
                "status": self.status,
                "created_at": self.created_at,
                "updated_at": self.updated_at,
                "exit_code": self.exit_code,
                "error": self.error,
                "logs": self.logs[-500:],
            }


jobs: dict[str, Job] = {}
jobs_lock = threading.RLock()


def start_job(label: str, fn: Callable[[Job], Any]) -> Job:
    job = Job(label)
    with jobs_lock:
        jobs[job.id] = job

    def runner() -> None:
        job.set_status("running")
        try:
            fn(job)
            if job.status != "cancelled":
                job.set_status("succeeded", exit_code=0)
        except Exception as exc:
            job.log(f"Error: {exc}")
            job.set_status("failed", error=str(exc), exit_code=1)

    threading.Thread(target=runner, daemon=True).start()
    return job


def run_local_stream(command: list[str], job: Job, cwd: Path | None = None) -> None:
    proc = subprocess.Popen(
        command,
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        if job.cancel_requested:
            proc.terminate()
            job.set_status("cancelled")
            return
        job.log(line.rstrip("\n"))
    code = proc.wait()
    if code != 0:
        raise RuntimeError(f"Command exited with {code}")


class ConnectRequest(BaseModel):
    host: str
    username: str = "root"
    password: str = ""
    use_ssh_agent: bool = False
    look_for_ssh_keys: bool = False


class DeviceProfile(BaseModel):
    name: str
    host: str
    username: str = "root"
    password: str = ""


class ProfileRequest(BaseModel):
    name: str
    host: str
    username: str = "root"
    password: str = ""
    use_ssh_agent: bool = False
    look_for_ssh_keys: bool = False


class ActiveProfileRequest(BaseModel):
    id: str


class ModeRequest(BaseModel):
    mode: str = Field(pattern="^(online|offline)$")
    offline_sd_root: str = ""


class TextWriteRequest(BaseModel):
    path: str
    text: str


class IniSettingsWriteRequest(BaseModel):
    path: str = "MiSTer.ini"
    values: dict[str, str]


class SmbRequest(BaseModel):
    enabled: bool


class ScriptRunRequest(BaseModel):
    key: str


class ScriptsConfigRequest(BaseModel):
    values: dict[str, Any]


class ExtraActionRequest(BaseModel):
    key: str
    action: str = Field(pattern="^(install|uninstall)$")


class RemoteCommandRequest(BaseModel):
    command: str


class FlashWriteRequest(BaseModel):
    device: str
    image_path: str


class DownloadRequest(BaseModel):
    source: str = Field(pattern="^(mr-fusion|superstation)$")


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "ok": not IMPORT_ERROR,
        "app": APP_NAME,
        "upstream_version": APP_VERSION,
        "import_error": IMPORT_ERROR,
        "state_dir": str(STATE_DIR),
        "config_dir": str(CONFIG_DIR),
        "data_dir": str(DATA_DIR),
        "upstream_dir": str(UPSTREAM_DIR),
        "connected": is_connected(),
        "mode": runtime_state.get("mode"),
        "offline_sd_root": runtime_state.get("offline_sd_root"),
        "active_profile_id": runtime_state.get("active_profile_id", ""),
    }


@app.get("/api/tabs")
def tabs() -> list[dict[str, Any]]:
    names = [
        "Flash SD",
        "Connection",
        "Device",
        "MiSTer Settings",
        "Scripts",
        "ZapScripts",
        "SaveManager",
        "Wallpapers",
        "Extras",
        "RetroAchievements",
        "Manuals",
    ]
    return [{"name": name, "enabled": True} for name in names]


@app.get("/api/state")
def get_state() -> dict[str, Any]:
    public_state = {
        key: value
        for key, value in runtime_state.items()
        if key != "ra"
    }
    public_state["ra"] = ra_config()
    public_state["connected"] = is_connected()
    public_state["active_profile_id"] = runtime_state.get("active_profile_id", "")
    return public_state


@app.post("/api/state/mode")
def set_mode(req: ModeRequest) -> dict[str, Any]:
    runtime_state["mode"] = req.mode
    runtime_state["offline_sd_root"] = req.offline_sd_root
    save_state(runtime_state)
    return get_state()


@app.get("/api/profiles")
def list_profiles() -> dict[str, Any]:
    return {
        "active_profile_id": runtime_state.get("active_profile_id", ""),
        "profiles": public_profiles(),
    }


@app.post("/api/profiles")
def create_profile(profile: ProfileRequest) -> dict[str, Any]:
    profiles = load_profiles_private()
    data = profile.model_dump()
    data["id"] = _profile_id()
    profiles.append(data)
    save_profiles_private(profiles)
    if not runtime_state.get("active_profile_id"):
        runtime_state["active_profile_id"] = data["id"]
        save_state(runtime_state)
    return list_profiles()


@app.get("/api/profiles/active")
def get_active_profile() -> dict[str, Any]:
    active_id = str(runtime_state.get("active_profile_id") or "")
    if not active_id:
        profiles = load_profiles_private()
        if profiles:
            active_id = str(profiles[0].get("id"))
            runtime_state["active_profile_id"] = active_id
            save_state(runtime_state)
    profile = find_profile_private(active_id) if active_id else {}
    return {"active_profile_id": active_id, "profile": _redact_profile(profile) if profile else None}


@app.put("/api/profiles/active")
def set_active_profile(req: ActiveProfileRequest) -> dict[str, Any]:
    find_profile_private(req.id)
    runtime_state["active_profile_id"] = req.id
    save_state(runtime_state)
    return get_active_profile()


@app.put("/api/profiles/{profile_id}")
def update_profile(profile_id: str, profile: ProfileRequest) -> dict[str, Any]:
    profiles = load_profiles_private()
    for index, item in enumerate(profiles):
        if str(item.get("id")) == profile_id:
            data = profile.model_dump()
            data["id"] = profile_id
            profiles[index] = data
            save_profiles_private(profiles)
            return list_profiles()
    raise HTTPException(status_code=404, detail="Profile not found")


@app.delete("/api/profiles/{profile_id}")
def delete_profile(profile_id: str) -> dict[str, Any]:
    profiles = [profile for profile in load_profiles_private() if str(profile.get("id")) != profile_id]
    if len(profiles) == len(load_profiles_private()):
        raise HTTPException(status_code=404, detail="Profile not found")
    save_profiles_private(profiles)
    if runtime_state.get("active_profile_id") == profile_id:
        runtime_state["active_profile_id"] = profiles[0].get("id", "") if profiles else ""
        save_state(runtime_state)
    return list_profiles()


@app.post("/api/profiles/{profile_id}/connect")
def connect_profile(profile_id: str) -> dict[str, Any]:
    profile = find_profile_private(profile_id)
    runtime_state["active_profile_id"] = profile_id
    return connect(
        ConnectRequest(
            host=profile.get("host") or profile.get("ip") or "",
            username=profile.get("username") or "root",
            password=profile.get("password") or "",
            use_ssh_agent=bool(profile.get("use_ssh_agent")),
            look_for_ssh_keys=bool(profile.get("look_for_ssh_keys")),
        )
    )


@app.get("/api/devices")
def list_devices() -> list[dict[str, Any]]:
    if IMPORT_ERROR:
        return public_profiles()
    return list(get_devices(app_config()))


@app.post("/api/devices")
def create_device(profile: DeviceProfile) -> list[dict[str, Any]]:
    data = profile.model_dump()
    data.setdefault("ip", data.get("host", ""))
    ok, message = add_device(app_config(), data)
    if not ok:
        raise HTTPException(status_code=409, detail=message)
    return list_devices()


@app.put("/api/devices/{index}")
def put_device(index: int, profile: DeviceProfile) -> list[dict[str, Any]]:
    data = profile.model_dump()
    data.setdefault("ip", data.get("host", ""))
    ok, message, _ = update_device(app_config(), index, data)
    if not ok:
        raise HTTPException(status_code=409, detail=message)
    return list_devices()


@app.delete("/api/devices/{index}")
def remove_device(index: int) -> list[dict[str, Any]]:
    ok, message, _ = delete_device(app_config(), index)
    if not ok:
        raise HTTPException(status_code=409, detail=message)
    return list_devices()


@app.get("/api/devices/{index}")
def get_device(index: int) -> dict[str, Any]:
    device = get_device_by_index(app_config(), index)
    if not device:
        raise HTTPException(status_code=404, detail="Device profile not found")
    return dict(device)


@app.post("/api/connect")
def connect(req: ConnectRequest) -> dict[str, Any]:
    if not connection:
        raise HTTPException(status_code=500, detail=IMPORT_ERROR or "Connection core unavailable")
    ok = connection.connect(
        req.host,
        req.username,
        req.password,
        use_ssh_agent=req.use_ssh_agent,
        look_for_ssh_keys=req.look_for_ssh_keys,
    )
    if not ok:
        raise HTTPException(status_code=401, detail="Unable to connect over SSH")
    runtime_state["mode"] = "online"
    if not runtime_state.get("active_profile_id"):
        for profile in load_profiles_private():
            if (profile.get("host") or profile.get("ip")) == req.host:
                runtime_state["active_profile_id"] = profile.get("id", "")
                break
    save_state(runtime_state)
    return get_state()


@app.post("/api/disconnect")
def disconnect() -> dict[str, Any]:
    if connection:
        connection.disconnect()
    return get_state()


@app.get("/api/network/scan")
def scan_network(prefix: str = "192.168.2", start: int = 1, end: int = 254) -> list[dict[str, Any]]:
    start = max(1, min(start, 254))
    end = max(start, min(end, 254))

    def probe(host: str) -> dict[str, Any] | None:
        try:
            with socket.create_connection((host, 22), timeout=0.25):
                pass
            return {"host": host, "ssh": True}
        except Exception:
            return None

    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=64) as pool:
        futures = [pool.submit(probe, f"{prefix}.{i}") for i in range(start, end + 1)]
        for fut in as_completed(futures):
            item = fut.result()
            if item:
                results.append(item)
    return sorted(results, key=lambda x: tuple(int(p) for p in x["host"].split(".")))


@app.get("/api/device/info")
def device_info() -> dict[str, Any]:
    if is_offline():
        root = require_sd_root()
        return {
            "mode": "offline",
            "sd": get_sd_storage_info_offline(str(root)),
            "usb": {"present": False, "label": "USB storage is only checked in online mode"},
            "smb_enabled": is_smb_enabled_offline(str(root)),
        }
    conn = require_connected()
    return {
        "mode": "online",
        "sd": get_sd_storage_info(conn),
        "usb": get_usb_storage_info(conn),
        "smb_enabled": is_smb_enabled(conn),
    }


@app.post("/api/device/smb")
def set_smb(req: SmbRequest) -> dict[str, Any]:
    if is_offline():
        root = require_sd_root()
        enable_smb_offline(str(root)) if req.enabled else disable_smb_offline(str(root))
    else:
        conn = require_connected()
        enable_smb_remote(conn) if req.enabled else disable_smb_remote(conn)
    return device_info()


@app.post("/api/device/reboot")
def reboot() -> dict[str, Any]:
    conn = require_connected()
    conn.reboot()
    return get_state()


@app.post("/api/device/return-to-menu")
def return_to_menu() -> dict[str, Any]:
    conn = require_connected()
    return {"output": return_to_menu_remote(conn)}


@app.get("/api/ini")
def list_ini() -> list[str]:
    if is_offline():
        root = require_sd_root()
        names = ["MiSTer.ini"] + sorted(p.name for p in root.glob("MiSTer_*.ini"))
        return [name for name in names if (root / name).exists()]
    conn = require_connected()
    out = conn.run_command("ls -1 /media/fat/MiSTer.ini /media/fat/MiSTer_*.ini 2>/dev/null | xargs -n1 basename")
    return [line.strip() for line in out.splitlines() if line.strip()]


@app.get("/api/ini/read")
def read_ini(path: str = "MiSTer.ini") -> dict[str, str]:
    safe = PurePosixPath(path).name
    if is_offline():
        file_path = require_sd_root() / safe
        if not file_path.exists():
            raise HTTPException(status_code=404, detail="INI file not found")
        return {"path": safe, "text": file_path.read_text(encoding="utf-8", errors="ignore")}
    remote = f"/media/fat/{safe}"
    if not sftp_exists(remote):
        raise HTTPException(status_code=404, detail="INI file not found")
    return {"path": safe, "text": sftp_read_text(remote)}


@app.post("/api/ini/write")
def write_ini(req: TextWriteRequest) -> dict[str, str]:
    safe = PurePosixPath(req.path).name
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    if is_offline():
        file_path = require_sd_root() / safe
        if file_path.exists():
            backup = file_path.with_name(f"{safe}.{stamp}.bak")
            shutil.copy2(file_path, backup)
        file_path.write_text(req.text, encoding="utf-8")
    else:
        remote = f"/media/fat/{safe}"
        if sftp_exists(remote):
            conn = require_connected()
            conn.run_command(f'cp "{remote}" "{remote}.{stamp}.bak"')
        sftp_write_text(remote, req.text)
    return {"path": safe, "status": "saved"}


@app.get("/api/ini/schema")
def ini_schema(path: str = "MiSTer.ini") -> dict[str, Any]:
    ini = read_ini(path)
    values = parse_ini_values(ini["text"])
    settings = []
    for item in INI_SETTINGS_SCHEMA:
        setting = dict(item)
        raw = values.get(setting["key"], "")
        setting["value"] = raw
        setting["enabled"] = raw not in {"", "0", "false", "False", "no", "No"} if setting["type"] == "checkbox" else raw
        settings.append(setting)
    categories = []
    for setting in settings:
        category = setting.get("category", "General")
        if category not in categories:
            categories.append(category)
    return {"path": ini["path"], "categories": categories, "settings": settings, "raw": ini["text"]}


@app.post("/api/ini/settings")
def write_ini_settings(req: IniSettingsWriteRequest) -> dict[str, Any]:
    ini = read_ini(req.path)
    allowed = {item["key"] for item in INI_SETTINGS_SCHEMA}
    values = {key: value for key, value in req.values.items() if key in allowed}
    if not values:
        raise HTTPException(status_code=400, detail="No supported INI settings supplied")
    text = update_ini_values(ini["text"], values)
    write_ini(TextWriteRequest(path=req.path, text=text))
    return ini_schema(req.path)


@app.get("/api/scripts/status")
def scripts_status() -> dict[str, Any]:
    try:
        import core.scripts_common as scripts_common

        if is_offline():
            for fn_name in ("get_scripts_status_offline", "detect_scripts_status_offline"):
                fn = getattr(scripts_common, fn_name, None)
                if fn:
                    return vars(fn(str(require_sd_root())))
        else:
            for fn_name in ("get_scripts_status", "detect_scripts_status"):
                fn = getattr(scripts_common, fn_name, None)
                if fn:
                    return vars(fn(require_connected()))
        empty = getattr(scripts_common, "empty_scripts_status", None)
        if empty:
            return vars(empty())
    except Exception as exc:
        return {"error": str(exc)}
    return {}


@app.get("/api/scripts/config")
def scripts_config() -> dict[str, Any]:
    try:
        from core.update_all_config import load_update_all_config, load_update_all_config_local

        if is_offline():
            values = load_update_all_config_local(str(require_sd_root()))
        else:
            values = load_update_all_config(require_connected())
        return {"available": True, "values": values}
    except Exception as exc:
        return {"available": False, "values": {}, "error": str(exc)}


@app.post("/api/scripts/config")
def save_scripts_config(req: ScriptsConfigRequest) -> dict[str, Any]:
    try:
        from core.update_all_config import save_update_all_config, save_update_all_config_local

        if is_offline():
            save_update_all_config_local(str(require_sd_root()), req.values)
        else:
            save_update_all_config(require_connected(), req.values)
        return scripts_config()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


SCRIPT_COMMANDS = {
    "update_all": 'if [ -x /media/fat/Scripts/update_all.sh ]; then /media/fat/Scripts/update_all.sh; elif [ -x /media/fat/Scripts/update.sh ]; then /media/fat/Scripts/update.sh; else echo "update_all is not installed"; exit 1; fi',
    "zaparoo": 'if [ -x /media/fat/Scripts/zaparoo.sh ]; then /media/fat/Scripts/zaparoo.sh; else echo "Zaparoo script is not installed"; exit 1; fi',
    "auto_time": 'if [ -x /media/fat/Scripts/auto_time.sh ]; then /media/fat/Scripts/auto_time.sh; else echo "auto_time is not installed"; exit 1; fi',
}


@app.post("/api/scripts/run")
def run_script(req: ScriptRunRequest) -> dict[str, Any]:
    if req.key not in SCRIPT_COMMANDS:
        raise HTTPException(status_code=404, detail="Unknown script key")
    if is_offline():
        raise HTTPException(status_code=409, detail="Offline script execution is exposed by status/config adapters only")
    conn = require_connected()

    def work(job: Job) -> None:
        job.log(f"Running {req.key}...")
        conn.run_command_stream(SCRIPT_COMMANDS[req.key], job.log)
        if req.key == "update_all":
            joined_logs = "\n".join(job.logs)
            if "Update All failed!" in joined_logs or "There were some errors in the Updaters" in joined_logs:
                raise RuntimeError("update_all reported updater errors. Check Scripts/.config/update_all/update_all.log on the MiSTer.")

    return start_job(f"script:{req.key}", work).snapshot()


@app.post("/api/zapscripts/send")
def send_zap(req: RemoteCommandRequest) -> dict[str, Any]:
    allowed = {
        "menu": 'echo "load_core /media/fat/menu.rbf" > /dev/MiSTer_cmd',
        "osd": 'echo "osd" > /dev/MiSTer_cmd',
        "bluetooth": 'echo "bt" > /dev/MiSTer_cmd',
        "wallpaper": 'echo "wallpaper" > /dev/MiSTer_cmd',
    }
    if req.command not in allowed:
        raise HTTPException(status_code=404, detail="Unknown remote command")
    conn = require_connected()
    return {"output": conn.run_command(allowed[req.command])}


def _download_dir_sftp(sftp: Any, remote_dir: str, local_dir: Path) -> None:
    import stat

    local_dir.mkdir(parents=True, exist_ok=True)
    for item in sftp.listdir_attr(remote_dir):
        remote_path = f"{remote_dir}/{item.filename}"
        local_path = local_dir / item.filename
        if stat.S_ISDIR(item.st_mode):
            _download_dir_sftp(sftp, remote_path, local_path)
        else:
            sftp.get(remote_path, str(local_path))


@app.get("/api/savemanager/backups")
def list_save_backups() -> list[str]:
    root = DATA_DIR / "SaveManager" / "backups"
    root.mkdir(parents=True, exist_ok=True)
    return sorted([p.name for p in root.iterdir() if p.is_dir()], reverse=True)


@app.post("/api/savemanager/backup")
def backup_saves(include_savestates: bool = True) -> dict[str, Any]:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = DATA_DIR / "SaveManager" / "backups" / stamp

    def work(job: Job) -> None:
        dest.mkdir(parents=True, exist_ok=True)
        if is_offline():
            root = require_sd_root()
            for name in ["saves", "savestates"] if include_savestates else ["saves"]:
                src = root / name
                if src.exists():
                    job.log(f"Copying {name}...")
                    shutil.copytree(src, dest / name, dirs_exist_ok=True)
            return
        conn = require_connected()
        sftp = conn.client.open_sftp()
        try:
            for remote, name in [("/media/fat/saves", "saves"), ("/media/fat/savestates", "savestates")]:
                if name == "savestates" and not include_savestates:
                    continue
                job.log(f"Downloading {name}...")
                try:
                    _download_dir_sftp(sftp, remote, dest / name)
                except FileNotFoundError:
                    job.log(f"{remote} does not exist")
        finally:
            sftp.close()

    return start_job("savemanager:backup", work).snapshot()


@app.get("/api/wallpapers/status")
def wallpapers_status() -> dict[str, Any]:
    if is_offline():
        root = require_sd_root()
        folder = root / "wallpapers"
        return {"count": len(list(folder.glob("*"))) if folder.exists() else 0, "path": str(folder)}
    conn = require_connected()
    out = conn.run_command("find /media/fat/wallpapers -maxdepth 1 -type f 2>/dev/null | wc -l")
    return {"count": int((out or "0").strip() or "0"), "path": "/media/fat/wallpapers"}


@app.post("/api/wallpapers/upload")
async def upload_wallpaper(file: UploadFile = File(...)) -> dict[str, Any]:
    name = PurePosixPath(file.filename or "").name
    suffix = Path(name).suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png"}:
        raise HTTPException(status_code=400, detail="Upload a JPG, JPEG, or PNG wallpaper file")
    data = await file.read()
    if len(data) > 25 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Wallpaper file is too large")
    if is_offline():
        root = require_sd_root()
        dest = root / "wallpapers" / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
    else:
        conn = require_connected()
        conn.run_command("mkdir -p /media/fat/wallpapers")
        sftp = conn.client.open_sftp()
        try:
            with sftp.open(f"/media/fat/wallpapers/{name}", "wb") as handle:
                handle.write(data)
        finally:
            sftp.close()
    return {"uploaded": name, "size": len(data), "status": wallpapers_status()}


@app.get("/api/extras/status")
def extras_status() -> dict[str, Any]:
    checks = {
        "zaparoo_launcher": "/media/fat/Scripts/zaparoo.sh",
        "ra_cores": "/media/fat/Scripts/.config/ra_cores",
        "sonic_mania": "/media/fat/games/Sonic_MiSTer",
        "three_s_arm": "/media/fat/games/3S",
    }
    if is_offline():
        root = require_sd_root()
        return {name: remote_to_local(root, path).exists() for name, path in checks.items()}
    conn = require_connected()
    return {
        name: "YES" in conn.run_command(f'test -e "{path}" && echo YES || echo NO')
        for name, path in checks.items()
    }


EXTRA_ACTIONS: dict[str, dict[str, str]] = {
    "zaparoo_launcher": {
        "install": "install_or_update_zaparoo_launcher",
        "install_local": "install_or_update_zaparoo_launcher_local",
        "uninstall": "uninstall_zaparoo_launcher",
        "uninstall_local": "uninstall_zaparoo_launcher_local",
        "module": "core.extras_zaparoo_launcher",
    },
    "ra_cores": {
        "install": "install_or_update_ra_cores",
        "install_local": "install_or_update_ra_cores_local",
        "uninstall": "uninstall_ra_cores",
        "uninstall_local": "uninstall_ra_cores_local",
        "module": "core.extras_ra_cores",
    },
    "sonic_mania": {
        "install": "install_or_update_sonic_mania",
        "install_local": "install_or_update_sonic_mania_local",
        "uninstall": "uninstall_sonic_mania",
        "uninstall_local": "uninstall_sonic_mania_local",
        "module": "core.extras_sonic_mania",
    },
    "three_s_arm": {
        "install": "install_or_update_3sx",
        "install_local": "install_or_update_3sx_local",
        "uninstall": "uninstall_3sx",
        "uninstall_local": "uninstall_3sx_local",
        "module": "core.extras_3s_arm",
    },
}


@app.post("/api/extras/action")
def extras_action(req: ExtraActionRequest) -> dict[str, Any]:
    if req.key not in EXTRA_ACTIONS:
        raise HTTPException(status_code=404, detail="Unknown extra")
    spec = EXTRA_ACTIONS[req.key]

    def work(job: Job) -> None:
        import importlib

        module = importlib.import_module(spec["module"])
        if is_offline():
            fn = getattr(module, spec[f"{req.action}_local"])
            fn(str(require_sd_root()), job.log)
        else:
            fn = getattr(module, spec[req.action])
            fn(require_connected(), job.log)

    return start_job(f"extra:{req.key}:{req.action}", work).snapshot()


@app.get("/api/retroachievements/config")
def ra_config() -> dict[str, Any]:
    data = dict(runtime_state.get("ra") or {})
    return {
        "username": data.get("username", ""),
        "has_password": bool(data.get("password")),
        "has_api_key": bool(data.get("api_key")),
    }


@app.post("/api/retroachievements/config")
def set_ra_config(data: dict[str, Any]) -> dict[str, Any]:
    current = dict(runtime_state.get("ra") or {})
    for key in {"username", "password", "api_key"}:
        if key in data:
            current[key] = data.get(key) or ""
    runtime_state["ra"] = current
    save_state(runtime_state)
    return ra_config()


@app.get("/api/retroachievements/summary")
def ra_summary() -> dict[str, Any]:
    data = dict(runtime_state.get("ra") or {})
    username = data.get("username", "")
    api_key = data.get("api_key", "")

    if not username or not api_key:
        return {
            "configured": bool(username),
            "available": False,
            "reason": "RetroAchievements Web API key is required for the viewer API.",
        }

    try:
        from core.retroachievements_api import (
            flatten_recent_achievements,
            get_user_summary,
            normalize_recent_games,
        )

        summary = get_user_summary(username, api_key)
        return {
            "configured": True,
            "available": True,
            "summary": summary,
            "recent_games": normalize_recent_games(summary),
            "recent_achievements": flatten_recent_achievements(summary),
        }
    except Exception as exc:
        return {"configured": True, "available": False, "reason": str(exc)}


@app.get("/api/manuals")
def manuals() -> dict[str, Any]:
    return {
        "available": True,
        "database_path": str(DATA_DIR / "cache" / "manuals"),
        "note": "Manual database hooks are ready for the upstream manuals core.",
    }


def flash_headers() -> dict[str, str]:
    token = FLASH_HELPER_TOKEN_FILE.read_text(encoding="utf-8").strip() if FLASH_HELPER_TOKEN_FILE.exists() else ""
    return {"Authorization": f"Bearer {token}"} if token else {}


@app.get("/api/flash/devices")
def flash_devices() -> list[dict[str, Any]]:
    try:
        resp = requests.get(f"{FLASH_HELPER_URL}/devices", headers=flash_headers(), timeout=5)
        resp.raise_for_status()
        return list(resp.json().get("devices", []))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Flash helper unavailable: {exc}") from exc


@app.get("/api/flash/releases")
def flash_releases() -> dict[str, Any]:
    repos = {
        "mr-fusion": "MiSTer-devel/mr-fusion",
        "superstation": "Retro-Remake/SuperStation-SD-Card-Installer",
    }
    result: dict[str, Any] = {}
    for key, repo in repos.items():
        try:
            r = requests.get(f"https://api.github.com/repos/{repo}/releases/latest", timeout=10)
            r.raise_for_status()
            data = r.json()
            result[key] = {
                "tag": data.get("tag_name"),
                "name": data.get("name"),
                "assets": [
                    {"name": a.get("name"), "url": a.get("browser_download_url"), "size": a.get("size")}
                    for a in data.get("assets", [])
                ],
            }
        except Exception as exc:
            result[key] = {"error": str(exc)}
    return result


@app.post("/api/flash/download")
def flash_download(req: DownloadRequest) -> dict[str, Any]:
    def work(job: Job) -> None:
        releases = flash_releases()
        info = releases.get(req.source, {})
        assets = info.get("assets") or []
        asset = next((a for a in assets if str(a.get("name", "")).lower().endswith((".img.zip", ".zip", ".xz", ".img"))), None)
        if not asset:
            raise RuntimeError(f"No downloadable image asset found for {req.source}")
        url = asset["url"]
        dest = DATA_DIR / "downloads" / asset["name"]
        job.log(f"Downloading {asset['name']}...")
        with requests.get(url, stream=True, timeout=30) as r:
            r.raise_for_status()
            with dest.open("wb") as fh:
                for chunk in r.iter_content(chunk_size=1024 * 1024):
                    if job.cancel_requested:
                        job.set_status("cancelled")
                        return
                    if chunk:
                        fh.write(chunk)
        job.log(f"Saved to {dest}")

    return start_job(f"flash:download:{req.source}", work).snapshot()


@app.post("/api/flash/write")
def flash_write(req: FlashWriteRequest) -> dict[str, Any]:
    image = Path(req.image_path)
    if not image.exists() or DATA_DIR not in image.resolve().parents:
        raise HTTPException(status_code=400, detail="Image must exist under the app data directory")

    def work(job: Job) -> None:
        payload = {
            "device": req.device,
            "image_path": str(image.resolve()).replace(str(DATA_DIR), FLASH_HELPER_DATA_PREFIX, 1),
        }
        job.log(f"Requesting host flash helper for {req.device}")
        resp = requests.post(f"{FLASH_HELPER_URL}/flash", headers=flash_headers(), json=payload, timeout=10)
        resp.raise_for_status()
        job.log(json.dumps(resp.json()))

    return start_job("flash:write", work).snapshot()


@app.get("/api/jobs")
def list_jobs() -> list[dict[str, Any]]:
    with jobs_lock:
        return [job.snapshot() for job in jobs.values()]


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job.snapshot()


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str) -> dict[str, Any]:
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    job.cancel_requested = True
    job.log("Cancel requested")
    return job.snapshot()


@app.websocket("/ws/jobs/{job_id}")
async def job_ws(websocket: WebSocket, job_id: str) -> None:
    await websocket.accept()
    job = jobs.get(job_id)
    if not job:
        await websocket.send_json({"type": "error", "message": "Job not found"})
        await websocket.close()
        return
    await websocket.send_json({"type": "snapshot", "job": job.snapshot()})
    try:
        while True:
            try:
                item = await asyncio.to_thread(job.events.get, True, 1)
                await websocket.send_json({"type": "log", "message": item, "job": job.snapshot()})
            except queue.Empty:
                await websocket.send_json({"type": "ping", "job": job.snapshot()})
            if job.status in {"succeeded", "failed", "cancelled"} and job.events.empty():
                await websocket.send_json({"type": "done", "job": job.snapshot()})
                break
    except WebSocketDisconnect:
        return


if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIST / "assets")), name="assets")

if (UPSTREAM_DIR / "assets").exists():
    app.mount("/mc-assets", StaticFiles(directory=str(UPSTREAM_DIR / "assets")), name="mc-assets")

if (UPSTREAM_DIR.parent / "assets").exists():
    app.mount("/repo-assets", StaticFiles(directory=str(UPSTREAM_DIR.parent / "assets")), name="repo-assets")


@app.get("/{path:path}")
def frontend(path: str) -> FileResponse:
    if path.startswith("api/") or path.startswith("ws/"):
        raise HTTPException(status_code=404)
    index = FRONTEND_DIST / "index.html"
    if not index.exists():
        raise HTTPException(status_code=503, detail="Frontend has not been built")
    return FileResponse(index)
