from __future__ import annotations

import ctypes
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import time
import zipfile
from pathlib import Path
from typing import Callable

import requests

from core.language import tr

try:
    import winreg
except ImportError:
    winreg = None


APP_NAME = "MiSTer Companion"


ANSI_ESCAPE_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")


def clean_output(text: str) -> str:
    return ANSI_ESCAPE_RE.sub("", text)


def get_app_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = get_app_base_dir()
TOOLS_DIR = BASE_DIR / "tools"
BALENA_DIR = TOOLS_DIR / "balena-cli"
MR_FUSION_DIR = TOOLS_DIR / "mr-fusion"
SUPERSTATION_DIR = TOOLS_DIR / "superstation"

BALENA_REPO = "balena-io/balena-cli"
MR_FUSION_REPO = "MiSTer-devel/mr-fusion"
SUPERSTATION_REPO = "Retro-Remake/SuperStation-SD-Card-Installer"

GITHUB_API_BASE = "https://api.github.com/repos"
REQUEST_HEADERS = {
    "User-Agent": APP_NAME,
    "Accept": "application/vnd.github+json",
}

LogCallback = Callable[[str], None]


def _noop_log(_: str) -> None:
    pass


def _log(log_callback: LogCallback | None, message: str) -> None:
    (log_callback or _noop_log)(message)


def is_flash_supported() -> bool:
    return platform.system() in {"Windows", "Linux", "Darwin"}


def get_platform_key() -> str:
    system = platform.system()
    if system == "Windows":
        return "windows"
    if system == "Linux":
        return "linux"
    if system == "Darwin":
        return "macos"
    return "unsupported"


def get_arch_key() -> str:
    machine = platform.machine().lower()

    if machine in {"x86_64", "amd64"}:
        return "x64"
    if machine in {"aarch64", "arm64"}:
        return "arm64"

    raise RuntimeError(tr("flash_tools.unsupported_arch", machine=machine))


def _clean_subprocess_env() -> dict[str, str]:
    """
    Return a safe environment for external system tools.

    PyInstaller can modify LD_LIBRARY_PATH so the bundled libraries are preferred.
    That is useful for the app itself, but it can break external commands.

    On Arch Linux this can cause system bash to load an incompatible readline
    library, resulting in:

        bash: symbol lookup error: bash: undefined symbol: rl_print_keybinding

    For external tools like balena CLI, bash, diskutil, gio, etc. we restore the
    original library path if PyInstaller saved it, otherwise we remove the
    PyInstaller-provided LD_LIBRARY_PATH.
    """
    env = os.environ.copy()

    if platform.system() in {"Linux", "Darwin"}:
        original_ld_library_path = env.get("LD_LIBRARY_PATH_ORIG")

        if original_ld_library_path is not None:
            if original_ld_library_path:
                env["LD_LIBRARY_PATH"] = original_ld_library_path
            else:
                env.pop("LD_LIBRARY_PATH", None)
        else:
            env.pop("LD_LIBRARY_PATH", None)

        env.pop("LD_PRELOAD", None)

    return env


def is_admin_windows() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def is_root_linux() -> bool:
    try:
        return os.geteuid() == 0
    except AttributeError:
        return False


def _get_windows_autoplay_value() -> int | None:
    if platform.system() != "Windows" or winreg is None:
        return None

    try:
        key = winreg.CreateKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Policies\Explorer",
        )
        try:
            value, _ = winreg.QueryValueEx(key, "NoDriveTypeAutoRun")
            return int(value)
        finally:
            winreg.CloseKey(key)
    except Exception:
        return None


def _set_windows_autoplay_value(value: int) -> None:
    if platform.system() != "Windows" or winreg is None:
        return

    key = winreg.CreateKey(
        winreg.HKEY_CURRENT_USER,
        r"Software\Microsoft\Windows\CurrentVersion\Policies\Explorer",
    )
    try:
        winreg.SetValueEx(key, "NoDriveTypeAutoRun", 0, winreg.REG_DWORD, int(value))
    finally:
        winreg.CloseKey(key)


def _delete_windows_autoplay_value() -> None:
    if platform.system() != "Windows" or winreg is None:
        return

    key = winreg.CreateKey(
        winreg.HKEY_CURRENT_USER,
        r"Software\Microsoft\Windows\CurrentVersion\Policies\Explorer",
    )
    try:
        try:
            winreg.DeleteValue(key, "NoDriveTypeAutoRun")
        except FileNotFoundError:
            pass
        except OSError:
            pass
    finally:
        winreg.CloseKey(key)


def _disable_windows_autoplay(log_callback: LogCallback | None = None) -> int | None:
    if platform.system() != "Windows":
        return None

    original_value = _get_windows_autoplay_value()
    _log(log_callback, tr("flash_tools.disable_windows_autoplay"))
    _set_windows_autoplay_value(0xFF)
    return original_value


def _restore_windows_autoplay(
    original_value: int | None,
    log_callback: LogCallback | None = None,
) -> None:
    if platform.system() != "Windows":
        return

    if original_value is None:
        _delete_windows_autoplay_value()
        return

    _log(log_callback, tr("flash_tools.windows_settings_restored"))
    _set_windows_autoplay_value(original_value)


def _ensure_flash_privileges() -> None:
    system = platform.system()

    if system == "Windows":
        if not is_admin_windows():
            raise RuntimeError(tr("flash_tools.admin_required_windows"))

    elif system == "Linux":
        if not is_root_linux():
            if shutil.which("pkexec"):
                raise RuntimeError(tr("flash_tools.root_required_pkexec"))
            raise RuntimeError(tr("flash_tools.root_required_sudo"))


def ensure_tools_dirs(log_callback: LogCallback | None = None) -> None:
    TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    BALENA_DIR.mkdir(parents=True, exist_ok=True)
    MR_FUSION_DIR.mkdir(parents=True, exist_ok=True)
    SUPERSTATION_DIR.mkdir(parents=True, exist_ok=True)
    _log(log_callback, tr("flash_tools.using_tools_dir", path=TOOLS_DIR))


def _get_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(REQUEST_HEADERS)
    return session


def _github_latest_release(repo: str) -> dict:
    url = f"{GITHUB_API_BASE}/{repo}/releases/latest"
    session = _get_session()
    response = session.get(url, timeout=30)
    response.raise_for_status()
    return response.json()


def _download_file(
    url: str,
    dest_path: Path,
    log_callback: LogCallback | None = None,
) -> Path:
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    _log(log_callback, tr("flash_tools.downloading", name=dest_path.name))

    session = _get_session()
    with session.get(url, stream=True, timeout=120) as response:
        response.raise_for_status()

        total_bytes = int(response.headers.get("Content-Length", 0))
        written_bytes = 0
        last_logged_percent = -1

        with dest_path.open("wb") as f:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if not chunk:
                    continue

                f.write(chunk)
                written_bytes += len(chunk)

                if total_bytes > 0:
                    percent = int((written_bytes / total_bytes) * 100)
                    if percent >= last_logged_percent + 10:
                        last_logged_percent = percent
                        _log(
                            log_callback,
                            tr(
                                "flash_tools.download_percent",
                                name=dest_path.name,
                                percent=percent,
                            ),
                        )

    _log(log_callback, tr("flash_tools.finished_downloading", name=dest_path.name))
    return dest_path


def _clear_directory_contents(folder: Path) -> None:
    if not folder.exists():
        return

    for item in folder.iterdir():
        if item.is_dir():
            shutil.rmtree(item, ignore_errors=True)
        else:
            try:
                item.unlink()
            except FileNotFoundError:
                pass


def _safe_extract_tar(archive_path: Path, dest_dir: Path) -> None:
    dest_dir.mkdir(parents=True, exist_ok=True)

    with tarfile.open(archive_path, "r:*") as tar:
        resolved_dest = dest_dir.resolve()

        for member in tar.getmembers():
            member_path = dest_dir / member.name
            resolved_member = member_path.resolve()
            if not str(resolved_member).startswith(str(resolved_dest)):
                raise RuntimeError(tr("flash_tools.unsafe_tar_path", name=member.name))

        tar.extractall(dest_dir)


def _extract_zip(archive_path: Path, dest_dir: Path) -> None:
    dest_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path, "r") as zf:
        zf.extractall(dest_dir)


def _extract_archive(
    archive_path: Path,
    dest_dir: Path,
    log_callback: LogCallback | None = None,
) -> None:
    _log(log_callback, tr("flash_tools.extracting", name=archive_path.name))

    name = archive_path.name.lower()
    if name.endswith((".tar.gz", ".tgz", ".tar")):
        _safe_extract_tar(archive_path, dest_dir)
    elif name.endswith(".zip"):
        _extract_zip(archive_path, dest_dir)
    else:
        raise RuntimeError(tr("flash_tools.unsupported_archive", name=archive_path.name))

    _log(log_callback, tr("flash_tools.finished_extracting", name=archive_path.name))

    try:
        archive_path.unlink()
        _log(log_callback, tr("flash_tools.removed_archive", name=archive_path.name))
    except FileNotFoundError:
        pass


def _make_executable(path: Path) -> None:
    if not path.exists():
        return

    current_mode = path.stat().st_mode
    path.chmod(current_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _find_first_matching_file(root: Path, pattern: str) -> Path | None:
    matches = sorted(p for p in root.rglob(pattern) if p.is_file())
    return matches[0] if matches else None


def _find_newest_matching_file(root: Path, pattern: str) -> Path | None:
    matches = [p for p in root.rglob(pattern) if p.is_file()]
    if not matches:
        return None
    return max(matches, key=lambda p: p.stat().st_mtime)


def has_balena_cli() -> bool:
    try:
        get_balena_executable()
        return True
    except Exception:
        return False


def has_mr_fusion_image() -> bool:
    try:
        get_mr_fusion_image()
        return True
    except Exception:
        return False


def has_superstation_image() -> bool:
    try:
        get_superstation_image()
        return True
    except Exception:
        return False


def get_balena_executable() -> Path:
    platform_key = get_platform_key()

    if platform_key == "windows":
        exe = _find_first_matching_file(BALENA_DIR, "balena.cmd")
        if exe:
            return exe

    if platform_key in {"linux", "macos"}:
        exe = _find_first_matching_file(BALENA_DIR, "balena")
        if exe:
            return exe

    raise RuntimeError(tr("flash_tools.balena_not_found"))


def get_mr_fusion_image() -> Path:
    image = _find_first_matching_file(MR_FUSION_DIR, "*.img")
    if image:
        return image

    raise RuntimeError(tr("flash_tools.mr_fusion_not_found"))


def get_superstation_image() -> Path:
    image = _find_first_matching_file(SUPERSTATION_DIR, "*.img")
    if image:
        return image

    raise RuntimeError(tr("flash_tools.superstation_not_found"))


def remove_balena_cli(log_callback: LogCallback | None = None) -> None:
    ensure_tools_dirs(log_callback)
    _clear_directory_contents(BALENA_DIR)
    _log(log_callback, tr("flash_tools.balena_removed"))


def remove_mr_fusion_image(log_callback: LogCallback | None = None) -> None:
    ensure_tools_dirs(log_callback)
    _clear_directory_contents(MR_FUSION_DIR)
    _log(log_callback, tr("flash_tools.mr_fusion_removed"))


def remove_superstation_image(log_callback: LogCallback | None = None) -> None:
    ensure_tools_dirs(log_callback)
    _clear_directory_contents(SUPERSTATION_DIR)
    _log(log_callback, tr("flash_tools.superstation_removed"))


def _select_balena_asset(release_data: dict) -> dict:
    platform_key = get_platform_key()
    arch_key = get_arch_key()

    if platform_key not in {"windows", "linux", "macos"}:
        raise RuntimeError(tr("flash_tools.flash_supported_platforms"))

    expected_fragment = f"{platform_key}-{arch_key}-standalone.tar.gz"
    assets = release_data.get("assets", [])

    for asset in assets:
        name = asset.get("name", "").lower()
        if expected_fragment in name:
            return asset

    raise RuntimeError(
        tr("flash_tools.balena_asset_not_found", platform=platform_key, arch=arch_key)
    )


def _select_mr_fusion_asset(release_data: dict) -> dict:
    assets = release_data.get("assets", [])

    for asset in assets:
        lower_name = asset.get("name", "").lower()
        if re.fullmatch(r"mr-fusion-v[\d.]+\.img\.zip", lower_name):
            return asset

    for asset in assets:
        lower_name = asset.get("name", "").lower()
        if lower_name.endswith(".img.zip") and "mr-fusion" in lower_name:
            return asset

    raise RuntimeError(tr("flash_tools.mr_fusion_asset_not_found"))


def _select_superstation_asset(release_data: dict) -> dict:
    assets = release_data.get("assets", [])
    img_zip_assets = []

    for asset in assets:
        name = str(asset.get("name", "")).strip()
        lower_name = name.lower()
        if lower_name.endswith(".img.zip"):
            img_zip_assets.append(asset)

    if not img_zip_assets:
        raise RuntimeError(tr("flash_tools.superstation_asset_not_found"))

    def asset_sort_key(asset: dict) -> tuple[str, str]:
        updated = str(asset.get("updated_at") or "")
        created = str(asset.get("created_at") or "")
        timestamp = updated or created
        name = str(asset.get("name") or "")
        return (timestamp, name)

    return max(img_zip_assets, key=asset_sort_key)


def _get_local_archive_name(folder: Path) -> str | None:
    archive = _find_newest_matching_file(folder, "*.img.zip")
    if archive:
        return archive.name
    return None


def _asset_timestamp(asset: dict) -> str:
    return str(asset.get("updated_at") or asset.get("created_at") or "")


def get_superstation_image_status(log_callback: LogCallback | None = None) -> dict:
    ensure_tools_dirs(log_callback)

    local_archive_name = _get_local_archive_name(SUPERSTATION_DIR)
    local_img = _find_first_matching_file(SUPERSTATION_DIR, "*.img")

    installed = bool(local_img)
    local_name = local_archive_name or (local_img.name if local_img else None)

    latest_name = None
    up_to_date = None
    update_available = False

    try:
        release_data = _github_latest_release(SUPERSTATION_REPO)
        latest_asset = _select_superstation_asset(release_data)
        latest_name = str(latest_asset.get("name", "")).strip() or None

        if installed:
            if local_archive_name and latest_name:
                up_to_date = local_archive_name == latest_name
                update_available = not up_to_date
            else:
                up_to_date = None
                update_available = False
    except Exception as e:
        _log(log_callback, tr("flash_tools.latest_superstation_check_failed", error=e))
        latest_name = None
        if installed:
            up_to_date = None
            update_available = False

    return {
        "installed": installed,
        "up_to_date": up_to_date,
        "local_name": local_name,
        "latest_name": latest_name,
        "update_available": update_available,
    }


def ensure_balena_cli(
    force_download: bool = False,
    log_callback: LogCallback | None = None,
) -> Path:
    if not is_flash_supported():
        raise RuntimeError(tr("flash_tools.flash_not_supported_platform"))

    ensure_tools_dirs(log_callback)

    if not force_download:
        try:
            exe = get_balena_executable()
            if platform.system() in ("Linux", "Darwin"):
                _make_executable(exe)
            _log(log_callback, tr("flash_tools.using_existing_balena", path=exe))
            return exe
        except Exception:
            pass

    _log(log_callback, tr("flash_tools.checking_balena"))
    release_data = _github_latest_release(BALENA_REPO)
    asset = _select_balena_asset(release_data)

    archive_path = BALENA_DIR / asset["name"]

    _clear_directory_contents(BALENA_DIR)
    _download_file(asset["browser_download_url"], archive_path, log_callback)
    _extract_archive(archive_path, BALENA_DIR, log_callback)

    exe = get_balena_executable()
    if platform.system() in ("Linux", "Darwin"):
        _make_executable(exe)

    _log(log_callback, tr("flash_tools.balena_ready", path=exe))
    return exe


def ensure_mr_fusion_image(
    force_download: bool = False,
    log_callback: LogCallback | None = None,
) -> Path:
    if not is_flash_supported():
        raise RuntimeError(tr("flash_tools.flash_not_supported_platform"))

    ensure_tools_dirs(log_callback)

    if not force_download:
        try:
            image = get_mr_fusion_image()
            _log(log_callback, tr("flash_tools.using_existing_mr_fusion", path=image))
            return image
        except Exception:
            pass

    _log(log_callback, tr("flash_tools.checking_mr_fusion"))
    release_data = _github_latest_release(MR_FUSION_REPO)
    asset = _select_mr_fusion_asset(release_data)

    archive_path = MR_FUSION_DIR / asset["name"]

    _clear_directory_contents(MR_FUSION_DIR)
    _download_file(asset["browser_download_url"], archive_path, log_callback)
    _extract_archive(archive_path, MR_FUSION_DIR, log_callback)

    image = get_mr_fusion_image()
    _log(log_callback, tr("flash_tools.mr_fusion_ready", path=image))
    return image


def ensure_superstation_image(
    force_download: bool = False,
    log_callback: LogCallback | None = None,
) -> Path:
    if not is_flash_supported():
        raise RuntimeError(tr("flash_tools.flash_not_supported_platform"))

    ensure_tools_dirs(log_callback)

    if not force_download:
        try:
            status = get_superstation_image_status(log_callback=log_callback)
            if status.get("installed") and not status.get("update_available"):
                image = get_superstation_image()
                _log(log_callback, tr("flash_tools.using_existing_superstation", path=image))
                return image
        except Exception:
            pass

    _log(log_callback, tr("flash_tools.checking_superstation"))
    release_data = _github_latest_release(SUPERSTATION_REPO)
    asset = _select_superstation_asset(release_data)

    asset_name = str(asset.get("name", "")).strip()
    asset_timestamp = _asset_timestamp(asset)
    if asset_timestamp:
        _log(
            log_callback,
            tr(
                "flash_tools.latest_superstation_with_date",
                name=asset_name,
                date=asset_timestamp,
            ),
        )
    else:
        _log(log_callback, tr("flash_tools.latest_superstation", name=asset_name))

    archive_path = SUPERSTATION_DIR / asset["name"]

    _clear_directory_contents(SUPERSTATION_DIR)
    _download_file(asset["browser_download_url"], archive_path, log_callback)
    _extract_archive(archive_path, SUPERSTATION_DIR, log_callback)

    image = get_superstation_image()
    _log(log_callback, tr("flash_tools.superstation_ready", path=image))
    return image


def _run_subprocess(
    cmd: list[str],
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    startupinfo = None
    if platform.system() == "Windows":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(cwd) if cwd else None,
        startupinfo=startupinfo,
        env=_clean_subprocess_env(),
    )


def _get_windows_drive_letter_map() -> dict[str, list[str]]:
    if platform.system() != "Windows":
        return {}

    cmd = [
        "powershell",
        "-NoProfile",
        "-Command",
        (
            "Get-Partition | "
            "Where-Object DriveLetter -ne $null | "
            "ForEach-Object { "
            "Write-Output ($_.DiskNumber.ToString() + '|' + $_.DriveLetter) "
            "}"
        ),
    ]

    result = _run_subprocess(cmd)
    if result.returncode != 0:
        return {}

    drive_letter_map: dict[str, list[str]] = {}

    for raw_line in (result.stdout or "").splitlines():
        line = raw_line.strip()
        if not line or "|" not in line:
            continue

        disk_number, drive_letter = line.split("|", 1)
        disk_number = disk_number.strip()
        drive_letter = drive_letter.strip()

        if not disk_number or not drive_letter:
            continue

        drive_letter_map.setdefault(disk_number, []).append(f"{drive_letter}:")

    return drive_letter_map


def _build_drive_display_name(
    device: str,
    description: str = "",
    size: int | None = None,
    windows_drive_letter_map: dict[str, list[str]] | None = None,
) -> str:
    parts: list[str] = []

    if platform.system() == "Windows":
        display_prefix = device

        match = re.match(r"^\\\\\.\\PhysicalDrive(\d+)$", device, re.IGNORECASE)
        if match and windows_drive_letter_map is not None:
            disk_number = match.group(1)
            letters = windows_drive_letter_map.get(disk_number, [])
            if letters:
                display_prefix = " / ".join(letters)

        if display_prefix:
            parts.append(display_prefix)
    else:
        if device:
            parts.append(device)

    if description:
        parts.append(description)

    if size:
        try:
            size_gb = float(size) / (1024 ** 3)
            parts.append(f"{size_gb:.1f} GB")
        except Exception:
            pass

    return " - ".join(parts) if parts else tr("flash_tools.unknown_drive")


def _size_text_to_bytes(size_text: str) -> int | None:
    match = re.match(r"^\s*([\d.]+)\s*([KMGTP]?B)\s*$", size_text, re.IGNORECASE)
    if not match:
        return None

    value = float(match.group(1))
    unit = match.group(2).upper()

    multipliers = {
        "KB": 1024,
        "MB": 1024 ** 2,
        "GB": 1024 ** 3,
        "TB": 1024 ** 4,
        "PB": 1024 ** 5,
    }

    return int(value * multipliers.get(unit, 1))


def _parse_available_drives_output(output: str) -> list[dict]:
    drives: list[dict] = []

    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if not lines:
        return drives

    for line in lines:
        upper_line = line.upper()
        if "DEVICE" in upper_line and "SIZE" in upper_line:
            continue

        match = re.match(
            r"^(?P<device>\S+)\s+(?P<size>[\d.]+\s*[KMGTP]?B)\s+(?P<description>.+)$",
            line,
            re.IGNORECASE,
        )
        if not match:
            continue

        device = match.group("device").strip()
        size_text = match.group("size").strip()
        description = match.group("description").strip()

        drives.append(
            {
                "device": device,
                "size": _size_text_to_bytes(size_text),
                "description": description,
            }
        )

    return drives


def list_available_drives(
    log_callback: LogCallback | None = None,
) -> list[dict]:
    if not is_flash_supported():
        return []

    if not has_balena_cli():
        raise RuntimeError(tr("flash_tools.balena_missing_download_first"))

    balena_exe = get_balena_executable()
    _log(log_callback, tr("flash_tools.refreshing_drives"))

    result = _run_subprocess(
        [str(balena_exe), "util", "available-drives"],
        cwd=balena_exe.parent,
    )

    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        stdout = (result.stdout or "").strip()
        combined = "\n".join(part for part in [stderr, stdout] if part).strip()
        raise RuntimeError(combined or tr("flash_tools.failed_get_drives"))

    stdout = (result.stdout or "").strip()
    if not stdout:
        return []

    _log(log_callback, tr("flash_tools.raw_balena_output"))
    for line in stdout.splitlines():
        _log(log_callback, line)

    drives = _parse_available_drives_output(stdout)

    windows_drive_letter_map: dict[str, list[str]] = {}
    if platform.system() == "Windows":
        windows_drive_letter_map = _get_windows_drive_letter_map()

    for drive in drives:
        device = str(drive.get("device", "")).strip()
        description = str(drive.get("description", "")).strip()
        size = drive.get("size")

        drive["display_name"] = _build_drive_display_name(
            device=device,
            description=description,
            size=size,
            windows_drive_letter_map=windows_drive_letter_map,
        )

    _log(log_callback, tr("flash_tools.parsed_drives", count=len(drives)))
    return drives


def flash_image(
    image_path: str | Path,
    drive: str,
    log_callback: LogCallback | None = None,
    password: str | None = None,
) -> None:
    _ensure_flash_privileges()

    image_path = Path(image_path)
    if not image_path.exists():
        raise RuntimeError(tr("flash_tools.image_not_found", path=image_path))

    if not drive:
        raise RuntimeError(tr("flash_tools.no_drive_selected"))

    if not has_balena_cli():
        raise RuntimeError(tr("flash_tools.balena_missing_download_first"))

    balena_exe = get_balena_executable()

    cmd = [
        str(balena_exe),
        "local",
        "flash",
        str(image_path),
        "--drive",
        drive,
        "--yes",
    ]

    if platform.system() == "Darwin":
        cmd = ["sudo", "-S"] + cmd

    _log(log_callback, tr("flash_tools.starting_flash", name=image_path.name))
    _log(log_callback, tr("flash_tools.target_drive", drive=drive))

    clean_env = _clean_subprocess_env()

    if platform.system() == "Darwin":
        _log(log_callback, tr("flash_tools.unmounting_disk"))
        subprocess.run(
            ["diskutil", "unmountDisk", drive],
            capture_output=True,
            text=True,
            env=clean_env,
        )

    original_autoplay_value = None
    if platform.system() == "Windows":
        original_autoplay_value = _disable_windows_autoplay(log_callback)

    startupinfo = None
    if platform.system() == "Windows":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

    process = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE if platform.system() == "Darwin" else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        cwd=str(balena_exe.parent),
        startupinfo=startupinfo,
        bufsize=1,
        env=clean_env,
    )

    if platform.system() == "Darwin" and password is not None:
        assert process.stdin is not None
        process.stdin.write(password + "\n")
        process.stdin.flush()
        process.stdin.close()

    output_lines: list[str] = []

    try:
        assert process.stdout is not None

        for raw_line in process.stdout:
            cleaned_line = clean_output(raw_line).strip()
            if not cleaned_line:
                continue

            lower_line = cleaned_line.lower()

            if "source and destination checksums do not match" in lower_line:
                continue

            output_lines.append(cleaned_line)
            _log(log_callback, cleaned_line)

        return_code = process.wait()
        combined_output = "\n".join(output_lines).lower()

        error_markers = [
            "eacces",
            "couldn't clean the drive",
            "could not clean the drive",
            "try running this command with elevated privileges",
            "administrator privileges",
            "access is denied",
            "permission denied",
            "symbol lookup error",
            "undefined symbol",
            "error:",
        ]

        if return_code != 0:
            if "symbol lookup error" in combined_output or "undefined symbol" in combined_output:
                raise RuntimeError(
                    tr("flash_tools.flash_failed_linux_command", code=return_code)
                )

            raise RuntimeError(tr("flash_tools.flash_failed_exit_code", code=return_code))

        for marker in error_markers:
            if marker in combined_output:
                if platform.system() == "Windows":
                    raise RuntimeError(tr("flash_tools.flash_failed_windows_permission"))

                if platform.system() == "Linux":
                    if marker in {"symbol lookup error", "undefined symbol"}:
                        raise RuntimeError(tr("flash_tools.flash_failed_linux_library"))

                    raise RuntimeError(tr("flash_tools.flash_failed_linux_permission"))

                if platform.system() == "Darwin":
                    raise RuntimeError(tr("flash_tools.flash_failed_macos_permission"))

                raise RuntimeError(tr("flash_tools.flash_failed_permission"))

        _log(log_callback, tr("flash_tools.flash_complete"))

        if platform.system() == "Darwin":
            _log(log_callback, tr("flash_tools.ejecting_drive"))
            subprocess.run(
                ["diskutil", "eject", drive],
                capture_output=True,
                text=True,
                env=clean_env,
            )
            _log(log_callback, tr("flash_tools.drive_ejected"))

    finally:
        if process.stdout is not None:
            try:
                process.stdout.close()
            except Exception as e:
                _log(log_callback, tr("flash_tools.failed_close_stdout", error=e))

        if platform.system() == "Windows":
            try:
                _log(log_callback, tr("flash_tools.waiting_restore_windows"))
                time.sleep(3.0)
                _log(log_callback, tr("flash_tools.restoring_autoplay"))
                _restore_windows_autoplay(original_autoplay_value, log_callback)
                _log(log_callback, tr("flash_tools.autoplay_restore_complete"))
            except Exception as e:
                _log(log_callback, tr("flash_tools.failed_restore_windows", error=e))