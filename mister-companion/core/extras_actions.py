import io
import os
import posixpath
import re
import shlex
import zipfile

import requests

from core.language import tr


GITHUB_RELEASES_API = "https://api.github.com/repos/kimchiman52/3s-mister-arm/releases/latest"
PICO8_GITHUB_RELEASES_API = "https://api.github.com/repos/MiSTerOrganize/MiSTer_PICO-8/releases/latest"
SONIC_MANIA_GITHUB_RELEASES_API = "https://api.github.com/repos/kimchiman52/sonic-mania-mister/releases/latest"

REMOTE_RBF_PATH = "/media/fat/_Other/3S-ARM.rbf"
REMOTE_GAME_DIR = "/media/fat/games/3s-arm"
REMOTE_RESOURCES_DIR = "/media/fat/games/3s-arm/resources"
REMOTE_LAUNCHER_PATH = "/media/fat/MiSTer_3S-ARM"
REMOTE_VERSION_FILE = "/media/fat/games/3s-arm/.mister_companion_version"
REMOTE_INI_PATH = "/media/fat/MiSTer.ini"
REMOTE_AFS_PATH = "/media/fat/games/3s-arm/resources/SF33RD.AFS"

OLD_REMOTE_RBF_PATH = "/media/fat/_Other/3SX.rbf"
OLD_REMOTE_GAME_DIR = "/media/fat/games/3sx"
OLD_REMOTE_RESOURCES_DIR = "/media/fat/games/3sx/resources"
OLD_REMOTE_LAUNCHER_PATH = "/media/fat/MiSTer_3SX"
OLD_REMOTE_VERSION_FILE = "/media/fat/games/3sx/.mister_companion_version"
OLD_REMOTE_AFS_PATH = "/media/fat/games/3sx/resources/SF33RD.AFS"

INI_BLOCK = "[3S-ARM]\nmain=MiSTer_3S-ARM\n"

PICO8_REMOTE_RBF_DIR = "/media/fat/_Other"
PICO8_LEGACY_REMOTE_RBF_DIR = "/media/fat/_Console"
PICO8_REMOTE_GAME_DIR = "/media/fat/games/PICO-8"
PICO8_REMOTE_DOCS_DIR = "/media/fat/docs/PICO-8"
PICO8_REMOTE_SCRIPTS_DIR = "/media/fat/Scripts"
PICO8_REMOTE_INPUTS_DIR = "/media/fat/config/inputs"
PICO8_REMOTE_VERSION_FILE = "/media/fat/games/PICO-8/.mister_companion_version"
PICO8_REMOTE_BINARY_PATH = "/media/fat/games/PICO-8/PICO-8"
PICO8_REMOTE_BOOTROM_PATH = "/media/fat/games/PICO-8/boot.rom"
PICO8_REMOTE_DAEMON_PATH = "/media/fat/games/PICO-8/pico8_daemon.sh"
PICO8_REMOTE_README_PATH = "/media/fat/docs/PICO-8/README.md"
PICO8_REMOTE_INSTALL_SCRIPT_PATH = "/media/fat/Scripts/Install_PICO-8.sh"
PICO8_REMOTE_USER_STARTUP_PATH = "/media/fat/linux/user-startup.sh"
PICO8_DAEMON_STARTUP_LINE = "/media/fat/games/PICO-8/pico8_daemon.sh &"

SONIC_MANIA_REMOTE_RBF_DIR = "/media/fat/_Other"
SONIC_MANIA_REMOTE_GAME_DIR = "/media/fat/games/sonic-mania"
SONIC_MANIA_REMOTE_LAUNCHER_PATH = "/media/fat/MiSTer_SonicMania"
SONIC_MANIA_REMOTE_VERSION_FILE = "/media/fat/games/sonic-mania/.mister_companion_version"
SONIC_MANIA_REMOTE_DATA_RSDK_PATH = "/media/fat/games/sonic-mania/Data.rsdk"

SONIC_MANIA_INI_BLOCKS = (
    "[Sonic Mania]\n"
    "main=MiSTer_SonicMania\n"
    "\n"
    "[Sonic Mania (4:3)]\n"
    "main=MiSTer_SonicMania\n"
)


def _quote(value: str) -> str:
    return shlex.quote(value)


def _unknown_lower() -> str:
    return tr("common.unknown").lower()


def _remote_file_exists(sftp, path: str) -> bool:
    try:
        sftp.stat(path)
        return True
    except Exception:
        return False


def _write_remote_bytes(connection, path: str, data: bytes):
    sftp = connection.client.open_sftp()
    try:
        with sftp.open(path, "wb") as remote_file:
            remote_file.write(data)
    finally:
        sftp.close()


def _write_remote_text(connection, path: str, text: str):
    sftp = connection.client.open_sftp()
    try:
        with sftp.open(path, "wb") as remote_file:
            remote_file.write(text.encode("utf-8"))
    finally:
        sftp.close()


def _read_remote_text(connection, path: str) -> str:
    sftp = connection.client.open_sftp()
    try:
        with sftp.open(path, "r") as remote_file:
            data = remote_file.read()
            if isinstance(data, bytes):
                return data.decode("utf-8", errors="replace")
            return data
    except Exception:
        return ""
    finally:
        sftp.close()


def _ensure_remote_dir(connection, remote_dir: str):
    connection.run_command(f"mkdir -p {_quote(remote_dir)}")


def _remote_command_success(connection, command: str) -> bool:
    result = connection.run_command(f"{command} >/dev/null 2>&1 && echo OK || echo FAIL")
    return "OK" in (result or "")


def _path_exists(connection, path: str) -> bool:
    result = connection.run_command(f"test -e {_quote(path)} && echo EXISTS || echo MISSING")
    return "EXISTS" in (result or "")


def _glob_exists(connection, pattern: str) -> bool:
    command = (
        f"for f in {pattern}; do "
        f'[ -e "$f" ] && echo EXISTS && exit 0; '
        f"done; echo MISSING"
    )
    result = connection.run_command(command)
    return "EXISTS" in (result or "")


def _is_3sx_installed(connection) -> bool:
    return (
        _path_exists(connection, REMOTE_RBF_PATH)
        and _path_exists(connection, REMOTE_GAME_DIR)
        and _path_exists(connection, REMOTE_LAUNCHER_PATH)
    )


def _is_old_3sx_installed(connection) -> bool:
    return (
        _path_exists(connection, OLD_REMOTE_RBF_PATH)
        and _path_exists(connection, OLD_REMOTE_GAME_DIR)
        and _path_exists(connection, OLD_REMOTE_LAUNCHER_PATH)
    )


def _has_pico8_rbf_in_other(connection) -> bool:
    return _glob_exists(connection, "/media/fat/_Other/PICO-8_*.rbf")


def _has_pico8_rbf_in_console(connection) -> bool:
    return _glob_exists(connection, "/media/fat/_Console/PICO-8_*.rbf")


def _is_pico8_installed(connection) -> bool:
    return (
        _has_pico8_rbf_in_other(connection)
        and _path_exists(connection, PICO8_REMOTE_BINARY_PATH)
        and _path_exists(connection, PICO8_REMOTE_BOOTROM_PATH)
        and _path_exists(connection, PICO8_REMOTE_DAEMON_PATH)
    )


def _is_pico8_legacy_installed(connection) -> bool:
    return (
        _has_pico8_rbf_in_console(connection)
        and _path_exists(connection, PICO8_REMOTE_BINARY_PATH)
        and _path_exists(connection, PICO8_REMOTE_BOOTROM_PATH)
        and _path_exists(connection, PICO8_REMOTE_DAEMON_PATH)
    )


def _has_sonic_mania_rbf(connection) -> bool:
    return _glob_exists(connection, "/media/fat/_Other/Sonic_Mania*.rbf")


def _is_sonic_mania_installed(connection) -> bool:
    return (
        _has_sonic_mania_rbf(connection)
        and _path_exists(connection, SONIC_MANIA_REMOTE_GAME_DIR)
        and _path_exists(connection, SONIC_MANIA_REMOTE_LAUNCHER_PATH)
    )


def _fetch_latest_release():
    response = requests.get(
        GITHUB_RELEASES_API,
        headers={"Accept": "application/vnd.github+json"},
        timeout=20,
    )
    response.raise_for_status()

    payload = response.json()
    tag_name = (payload.get("tag_name") or "").strip()

    zip_url = None
    for asset in payload.get("assets", []):
        url = asset.get("browser_download_url", "")
        name = asset.get("name", "")
        if url.lower().endswith(".zip") or name.lower().endswith(".zip"):
            zip_url = url
            break

    if not tag_name:
        raise RuntimeError(tr("extras_tab.github_latest_3sx_failed"))

    if not zip_url:
        raise RuntimeError(tr("extras_tab.github_zip_3sx_missing"))

    return {
        "version": tag_name,
        "zip_url": zip_url,
        "release_name": payload.get("name", tag_name),
    }


def _fetch_latest_pico8_release():
    response = requests.get(
        PICO8_GITHUB_RELEASES_API,
        headers={"Accept": "application/vnd.github+json"},
        timeout=20,
    )
    response.raise_for_status()

    payload = response.json()
    tag_name = (payload.get("tag_name") or "").strip()

    zip_url = None
    for asset in payload.get("assets", []):
        url = asset.get("browser_download_url", "")
        name = asset.get("name", "")
        lower_name = name.lower()
        lower_url = url.lower()
        if lower_name.endswith(".zip") or lower_url.endswith(".zip"):
            zip_url = url
            break

    if not tag_name:
        raise RuntimeError(tr("extras_tab.github_latest_pico8_failed"))

    if not zip_url:
        raise RuntimeError(tr("extras_tab.github_zip_pico8_missing"))

    return {
        "version": tag_name,
        "zip_url": zip_url,
        "release_name": payload.get("name", tag_name),
    }


def _fetch_latest_sonic_mania_release():
    response = requests.get(
        SONIC_MANIA_GITHUB_RELEASES_API,
        headers={"Accept": "application/vnd.github+json"},
        timeout=20,
    )
    response.raise_for_status()

    payload = response.json()
    tag_name = (payload.get("tag_name") or "").strip()

    zip_url = None
    for asset in payload.get("assets", []):
        url = asset.get("browser_download_url", "")
        name = asset.get("name", "")
        lower_name = name.lower()
        lower_url = url.lower()
        if lower_name.endswith(".zip") or lower_url.endswith(".zip"):
            zip_url = url
            break

    if not tag_name:
        raise RuntimeError(tr("extras_tab.github_latest_sonic_mania_failed"))

    if not zip_url:
        raise RuntimeError(tr("extras_tab.github_zip_sonic_mania_missing"))

    return {
        "version": tag_name,
        "zip_url": zip_url,
        "release_name": payload.get("name", tag_name),
    }


def _read_installed_version(connection) -> str:
    version = _read_remote_text(connection, REMOTE_VERSION_FILE).strip()
    if version:
        return version
    return _read_remote_text(connection, OLD_REMOTE_VERSION_FILE).strip()


def _read_installed_pico8_version(connection) -> str:
    return _read_remote_text(connection, PICO8_REMOTE_VERSION_FILE).strip()


def _read_installed_sonic_mania_version(connection) -> str:
    return _read_remote_text(connection, SONIC_MANIA_REMOTE_VERSION_FILE).strip()


def _write_installed_version(connection, version: str):
    _ensure_remote_dir(connection, posixpath.dirname(REMOTE_VERSION_FILE))
    _write_remote_text(connection, REMOTE_VERSION_FILE, version.strip() + "\n")


def _write_installed_pico8_version(connection, version: str):
    _ensure_remote_dir(connection, posixpath.dirname(PICO8_REMOTE_VERSION_FILE))
    _write_remote_text(connection, PICO8_REMOTE_VERSION_FILE, version.strip() + "\n")


def _write_installed_sonic_mania_version(connection, version: str):
    _ensure_remote_dir(connection, posixpath.dirname(SONIC_MANIA_REMOTE_VERSION_FILE))
    _write_remote_text(connection, SONIC_MANIA_REMOTE_VERSION_FILE, version.strip() + "\n")


def _normalize_ini_text_for_append(text: str) -> str:
    normalized = text.replace("\r\n", "\n").rstrip("\n")
    if normalized:
        normalized += "\n\n"
    return normalized


def _ensure_ini_block(connection) -> bool:
    current = _read_remote_text(connection, REMOTE_INI_PATH)
    normalized = current.replace("\r\n", "\n")

    if "[3S-ARM]" in normalized and "main=MiSTer_3S-ARM" in normalized:
        return False

    old_pattern = re.compile(
        r"(?:\n{0,2})\[3SX\]\nmain=MiSTer_3SX\n(?:video_mode=8\n?)?",
        re.MULTILINE,
    )
    normalized = re.sub(old_pattern, "\n", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized).rstrip("\n")

    updated = _normalize_ini_text_for_append(normalized) + INI_BLOCK
    _write_remote_text(connection, REMOTE_INI_PATH, updated)
    return True


def _remove_ini_block(connection) -> bool:
    current = _read_remote_text(connection, REMOTE_INI_PATH)
    if not current:
        return False

    normalized = current.replace("\r\n", "\n")

    pattern = re.compile(
        r"(?:\n{0,2})\[(?:3SX|3S-ARM)\]\nmain=(?:MiSTer_3SX|MiSTer_3S-ARM)\n(?:video_mode=8\n?)?",
        re.MULTILINE,
    )
    updated = re.sub(pattern, "\n", normalized)
    updated = re.sub(r"\n{3,}", "\n\n", updated).rstrip("\n")

    if updated:
        updated += "\n"

    if updated == normalized:
        return False

    _write_remote_text(connection, REMOTE_INI_PATH, updated)
    return True


def _ensure_sonic_mania_ini_blocks(connection) -> bool:
    current = _read_remote_text(connection, REMOTE_INI_PATH)
    normalized = current.replace("\r\n", "\n")

    has_16_9 = "[Sonic Mania]" in normalized and "main=MiSTer_SonicMania" in normalized
    has_4_3 = "[Sonic Mania (4:3)]" in normalized and "main=MiSTer_SonicMania" in normalized

    if has_16_9 and has_4_3:
        return False

    updated = normalized

    if not has_16_9:
        updated = _normalize_ini_text_for_append(updated) + "[Sonic Mania]\nmain=MiSTer_SonicMania\n"

    if not has_4_3:
        updated = _normalize_ini_text_for_append(updated) + "[Sonic Mania (4:3)]\nmain=MiSTer_SonicMania\n"

    _write_remote_text(connection, REMOTE_INI_PATH, updated)
    return True


def _remove_sonic_mania_ini_blocks(connection) -> bool:
    current = _read_remote_text(connection, REMOTE_INI_PATH)
    if not current:
        return False

    normalized = current.replace("\r\n", "\n")

    pattern = re.compile(
        r"(?:\n{0,2})\[Sonic Mania(?: \(4:3\))?\]\nmain=MiSTer_SonicMania\n?",
        re.MULTILINE,
    )
    updated = re.sub(pattern, "\n", normalized)
    updated = re.sub(r"\n{3,}", "\n\n", updated).rstrip("\n")

    if updated:
        updated += "\n"

    if updated == normalized:
        return False

    _write_remote_text(connection, REMOTE_INI_PATH, updated)
    return True


def _ensure_startup_line(connection, startup_path: str, line: str) -> bool:
    current = _read_remote_text(connection, startup_path)
    normalized = current.replace("\r\n", "\n")

    existing_lines = [entry.rstrip() for entry in normalized.split("\n") if entry.strip()]
    if line in existing_lines:
        return False

    updated = normalized.rstrip("\n")
    if updated:
        updated += "\n"
    updated += line + "\n"

    _ensure_remote_dir(connection, posixpath.dirname(startup_path))
    _write_remote_text(connection, startup_path, updated)
    return True


def _remove_startup_line(connection, startup_path: str, line: str) -> bool:
    current = _read_remote_text(connection, startup_path)
    if not current:
        return False

    normalized = current.replace("\r\n", "\n")
    original_lines = normalized.split("\n")
    kept_lines = [entry for entry in original_lines if entry.strip() != line]

    if kept_lines == original_lines:
        return False

    updated = "\n".join(kept_lines).rstrip("\n")
    if updated:
        updated += "\n"

    _write_remote_text(connection, startup_path, updated)
    return True


def _remove_if_empty_dir(connection, path: str):
    connection.run_command(
        f"if [ -d {_quote(path)} ] && [ -z \"$(ls -A {_quote(path)} 2>/dev/null)\" ]; then rmdir {_quote(path)}; fi"
    )


def _remove_glob(connection, pattern: str):
    command = (
        f"for f in {pattern}; do "
        f'[ -e "$f" ] && rm -f "$f"; '
        f"done"
    )
    connection.run_command(command)


def _migrate_old_install(connection, log):
    old_present = _is_old_3sx_installed(connection)
    if not old_present:
        return False

    log(tr("extras_tab.log_detected_legacy_3sx"))

    _ensure_remote_dir(connection, "/media/fat/_Other")
    _ensure_remote_dir(connection, "/media/fat/games")

    if _path_exists(connection, OLD_REMOTE_LAUNCHER_PATH) and not _path_exists(connection, REMOTE_LAUNCHER_PATH):
        log(tr("extras_tab.log_renaming_launcher", old_path=OLD_REMOTE_LAUNCHER_PATH, new_path=REMOTE_LAUNCHER_PATH))
        connection.run_command(
            f"mv {_quote(OLD_REMOTE_LAUNCHER_PATH)} {_quote(REMOTE_LAUNCHER_PATH)}"
        )

    if _path_exists(connection, OLD_REMOTE_RBF_PATH) and not _path_exists(connection, REMOTE_RBF_PATH):
        log(tr("extras_tab.log_renaming_rbf", old_path=OLD_REMOTE_RBF_PATH, new_path=REMOTE_RBF_PATH))
        connection.run_command(
            f"mv {_quote(OLD_REMOTE_RBF_PATH)} {_quote(REMOTE_RBF_PATH)}"
        )

    if _path_exists(connection, OLD_REMOTE_GAME_DIR) and not _path_exists(connection, REMOTE_GAME_DIR):
        log(tr("extras_tab.log_renaming_game_data", old_path=OLD_REMOTE_GAME_DIR, new_path=REMOTE_GAME_DIR))
        connection.run_command(
            f"mv {_quote(OLD_REMOTE_GAME_DIR)} {_quote(REMOTE_GAME_DIR)}"
        )

    if _path_exists(connection, OLD_REMOTE_VERSION_FILE) and not _path_exists(connection, REMOTE_VERSION_FILE):
        _ensure_remote_dir(connection, posixpath.dirname(REMOTE_VERSION_FILE))
        log(tr("extras_tab.log_moving_version_marker", old_path=OLD_REMOTE_VERSION_FILE, new_path=REMOTE_VERSION_FILE))
        connection.run_command(
            f"mv {_quote(OLD_REMOTE_VERSION_FILE)} {_quote(REMOTE_VERSION_FILE)}"
        )

    ini_changed = _ensure_ini_block(connection)
    if ini_changed:
        log(tr("extras_tab.log_updated_ini_3sx"))

    if _path_exists(connection, REMOTE_LAUNCHER_PATH):
        connection.run_command(f"chmod +x {_quote(REMOTE_LAUNCHER_PATH)}")

    return True


def _migrate_old_pico8_install(connection, log):
    if not _has_pico8_rbf_in_console(connection):
        return False

    log(tr("extras_tab.log_detected_legacy_pico8"))
    _ensure_remote_dir(connection, PICO8_REMOTE_RBF_DIR)

    connection.run_command(
        "for f in /media/fat/_Console/PICO-8_*.rbf; do "
        '[ -e "$f" ] || continue; '
        'mv "$f" /media/fat/_Other/; '
        "done"
    )

    _remove_if_empty_dir(connection, PICO8_LEGACY_REMOTE_RBF_DIR)
    return True


def get_3sx_status(connection):
    if not connection.is_connected():
        return {
            "installed": False,
            "installed_version": "",
            "latest_version": "",
            "latest_error": "",
            "update_available": False,
            "afs_present": False,
            "status_text": tr("common.unknown"),
            "install_label": tr("extras_tab.install"),
            "install_enabled": False,
            "upload_enabled": False,
            "uninstall_enabled": False,
        }

    latest_version = ""
    latest_error = ""

    try:
        latest = _fetch_latest_release()
        latest_version = latest["version"]
    except Exception as exc:
        latest_error = str(exc)

    installed = _is_3sx_installed(connection)
    legacy_installed = _is_old_3sx_installed(connection)
    installed_version = _read_installed_version(connection) if (installed or legacy_installed) else ""

    afs_present = False
    if installed:
        afs_present = _path_exists(connection, REMOTE_AFS_PATH)
    elif legacy_installed:
        afs_present = _path_exists(connection, OLD_REMOTE_AFS_PATH)

    update_available = False
    if (installed or legacy_installed) and latest_version and installed_version:
        update_available = installed_version != latest_version
    elif (installed or legacy_installed) and latest_version and not installed_version:
        update_available = True

    if not installed and not legacy_installed:
        status_text = tr("extras_tab.status_not_installed")
        install_label = tr("extras_tab.install")
        install_enabled = True
        upload_enabled = False
        uninstall_enabled = False
    elif legacy_installed and not installed:
        status_text = tr("extras_tab.status_legacy_3sx")
        install_label = tr("extras_tab.migrate_install")
        install_enabled = True
        upload_enabled = not afs_present
        uninstall_enabled = True
    elif update_available:
        status_text = tr(
            "extras_tab.status_update_available",
            installed_version=installed_version or _unknown_lower(),
            latest_version=latest_version,
        )
        install_label = tr("extras_tab.update")
        install_enabled = True
        upload_enabled = not afs_present
        uninstall_enabled = True
    else:
        version_display = installed_version or latest_version or _unknown_lower()
        status_text = tr("extras_tab.status_installed_with_version", version=version_display)
        install_label = tr("extras_tab.installed_label")
        install_enabled = False
        upload_enabled = not afs_present
        uninstall_enabled = True

    return {
        "installed": installed or legacy_installed,
        "installed_version": installed_version,
        "latest_version": latest_version,
        "latest_error": latest_error,
        "update_available": update_available,
        "afs_present": afs_present,
        "status_text": status_text,
        "install_label": install_label,
        "install_enabled": install_enabled,
        "upload_enabled": upload_enabled,
        "uninstall_enabled": uninstall_enabled,
    }


def get_pico8_status(connection):
    if not connection.is_connected():
        return {
            "installed": False,
            "installed_version": "",
            "latest_version": "",
            "latest_error": "",
            "update_available": False,
            "status_text": tr("common.unknown"),
            "install_label": tr("extras_tab.install"),
            "install_enabled": False,
            "uninstall_enabled": False,
        }

    latest_version = ""
    latest_error = ""

    try:
        latest = _fetch_latest_pico8_release()
        latest_version = latest["version"]
    except Exception as exc:
        latest_error = str(exc)

    installed = _is_pico8_installed(connection)
    legacy_installed = _is_pico8_legacy_installed(connection)
    installed_version = _read_installed_pico8_version(connection) if (installed or legacy_installed) else ""

    update_available = False
    if (installed or legacy_installed) and latest_version and installed_version:
        update_available = installed_version != latest_version
    elif (installed or legacy_installed) and latest_version and not installed_version:
        update_available = True

    if not installed and not legacy_installed:
        status_text = tr("extras_tab.status_not_installed")
        install_label = tr("extras_tab.install")
        install_enabled = True
        uninstall_enabled = False
    elif legacy_installed and not installed:
        status_text = tr("extras_tab.status_legacy_pico8")
        install_label = tr("extras_tab.migrate_install")
        install_enabled = True
        uninstall_enabled = True
    elif update_available:
        status_text = tr(
            "extras_tab.status_update_available",
            installed_version=installed_version or _unknown_lower(),
            latest_version=latest_version,
        )
        install_label = tr("extras_tab.update")
        install_enabled = True
        uninstall_enabled = True
    else:
        version_display = installed_version or latest_version or _unknown_lower()
        status_text = tr("extras_tab.status_installed_with_version", version=version_display)
        install_label = tr("extras_tab.installed_label")
        install_enabled = False
        uninstall_enabled = True

    return {
        "installed": installed or legacy_installed,
        "installed_version": installed_version,
        "latest_version": latest_version,
        "latest_error": latest_error,
        "update_available": update_available,
        "status_text": status_text,
        "install_label": install_label,
        "install_enabled": install_enabled,
        "uninstall_enabled": uninstall_enabled,
    }


def get_sonic_mania_status(connection):
    if not connection.is_connected():
        return {
            "installed": False,
            "installed_version": "",
            "latest_version": "",
            "latest_error": "",
            "update_available": False,
            "data_rsdk_present": False,
            "status_text": tr("common.unknown"),
            "install_label": tr("extras_tab.install"),
            "install_enabled": False,
            "upload_enabled": False,
            "uninstall_enabled": False,
        }

    latest_version = ""
    latest_error = ""

    try:
        latest = _fetch_latest_sonic_mania_release()
        latest_version = latest["version"]
    except Exception as exc:
        latest_error = str(exc)

    installed = _is_sonic_mania_installed(connection)
    installed_version = _read_installed_sonic_mania_version(connection) if installed else ""
    data_rsdk_present = _path_exists(connection, SONIC_MANIA_REMOTE_DATA_RSDK_PATH) if installed else False

    update_available = False
    if installed and latest_version and installed_version:
        update_available = installed_version != latest_version
    elif installed and latest_version and not installed_version:
        update_available = True

    if not installed:
        status_text = tr("extras_tab.status_not_installed")
        install_label = tr("extras_tab.install")
        install_enabled = True
        upload_enabled = False
        uninstall_enabled = False
    elif update_available:
        status_text = tr(
            "extras_tab.status_update_available",
            installed_version=installed_version or _unknown_lower(),
            latest_version=latest_version,
        )
        install_label = tr("extras_tab.update")
        install_enabled = True
        upload_enabled = not data_rsdk_present
        uninstall_enabled = True
    else:
        version_display = installed_version or latest_version or _unknown_lower()
        status_text = tr("extras_tab.status_installed_with_version", version=version_display)
        install_label = tr("extras_tab.installed_label")
        install_enabled = False
        upload_enabled = not data_rsdk_present
        uninstall_enabled = True

    return {
        "installed": installed,
        "installed_version": installed_version,
        "latest_version": latest_version,
        "latest_error": latest_error,
        "update_available": update_available,
        "data_rsdk_present": data_rsdk_present,
        "status_text": status_text,
        "install_label": install_label,
        "install_enabled": install_enabled,
        "upload_enabled": upload_enabled,
        "uninstall_enabled": uninstall_enabled,
    }


def install_or_update_3sx(connection, log):
    if not connection.is_connected():
        raise RuntimeError(tr("extras_tab.not_connected"))

    _migrate_old_install(connection, log)

    latest = _fetch_latest_release()
    version = latest["version"]
    zip_url = latest["zip_url"]

    log(tr("extras_tab.log_latest_version", version=version))
    log(tr("extras_tab.log_downloading", url=zip_url))

    response = requests.get(zip_url, timeout=60)
    response.raise_for_status()
    archive_data = response.content

    log(tr("extras_tab.log_downloaded_bytes", bytes=len(archive_data)))

    with zipfile.ZipFile(io.BytesIO(archive_data)) as zf:
        members = [m for m in zf.infolist() if not m.is_dir()]
        if not members:
            raise RuntimeError(tr("extras_tab.archive_empty_3sx"))

        log(tr("extras_tab.log_inspecting_archive"))

        payloads = []
        for member in members:
            name = member.filename.replace("\\", "/")
            basename = posixpath.basename(name)

            if not basename:
                continue

            if basename.lower() == "readme.txt":
                log(tr("extras_tab.log_skipping_readme", name=name))
                continue

            payloads.append(member)

        sftp = connection.client.open_sftp()
        try:
            for member in payloads:
                name = member.filename.replace("\\", "/")
                basename = posixpath.basename(name)
                data = zf.read(member)

                if basename == "MiSTer_3S-ARM":
                    log(tr("extras_tab.log_uploading_launcher", path=REMOTE_LAUNCHER_PATH))
                    with sftp.open(REMOTE_LAUNCHER_PATH, "wb") as remote_file:
                        remote_file.write(data)
                    continue

                parts = [p for p in name.split("/") if p]
                if not parts:
                    continue

                if "_Other" in parts:
                    idx = parts.index("_Other")
                    relative = parts[idx + 1:]
                    if not relative:
                        continue

                    relative_path = "/".join(relative)
                    remote_path = posixpath.join("/media/fat/_Other", *relative)
                    _ensure_remote_dir(connection, posixpath.dirname(remote_path))
                    log(tr("extras_tab.log_merging_other", path=relative_path))

                    with sftp.open(remote_path, "wb") as remote_file:
                        remote_file.write(data)
                    continue

                if "games" in parts:
                    idx = parts.index("games")
                    relative = parts[idx + 1:]
                    if not relative:
                        continue

                    relative_path = "/".join(relative)
                    remote_path = posixpath.join("/media/fat/games", *relative)
                    _ensure_remote_dir(connection, posixpath.dirname(remote_path))
                    log(tr("extras_tab.log_merging_games", path=relative_path))

                    with sftp.open(remote_path, "wb") as remote_file:
                        remote_file.write(data)
                    continue

                if basename == "3S-ARM.rbf":
                    _ensure_remote_dir(connection, "/media/fat/_Other")
                    log(tr("extras_tab.log_uploading_rbf", path=REMOTE_RBF_PATH))

                    with sftp.open(REMOTE_RBF_PATH, "wb") as remote_file:
                        remote_file.write(data)
                    continue

                log(tr("extras_tab.log_skipping_unhandled_file", name=name))

        finally:
            sftp.close()

    connection.run_command(f"chmod +x {_quote(REMOTE_LAUNCHER_PATH)}")

    ini_added = _ensure_ini_block(connection)
    if ini_added:
        log(tr("extras_tab.log_ini_3sx_added"))
    else:
        log(tr("extras_tab.log_ini_3sx_already_present"))

    _write_installed_version(connection, version)
    log(tr("extras_tab.log_stored_version_marker", version=version))

    return {
        "installed_version": version,
    }


def install_or_update_pico8(connection, log):
    if not connection.is_connected():
        raise RuntimeError(tr("extras_tab.not_connected"))

    _migrate_old_pico8_install(connection, log)

    latest = _fetch_latest_pico8_release()
    version = latest["version"]
    zip_url = latest["zip_url"]

    log(tr("extras_tab.log_latest_version", version=version))
    log(tr("extras_tab.log_downloading", url=zip_url))

    response = requests.get(zip_url, timeout=60)
    response.raise_for_status()
    archive_data = response.content

    log(tr("extras_tab.log_downloaded_bytes", bytes=len(archive_data)))

    with zipfile.ZipFile(io.BytesIO(archive_data)) as zf:
        members = [m for m in zf.infolist() if not m.is_dir()]
        if not members:
            raise RuntimeError(tr("extras_tab.archive_empty_pico8"))

        log(tr("extras_tab.log_inspecting_archive"))

        rbf_member = None
        input_map_member = None
        binary_member = None
        bootrom_member = None
        daemon_member = None
        readme_member = None
        install_script_member = None

        for member in members:
            name = member.filename.replace("\\", "/")
            basename = posixpath.basename(name)
            parts = [p for p in name.split("/") if p]

            if parts[:1] == ["_Other"] and basename.startswith("PICO-8_") and basename.lower().endswith(".rbf"):
                rbf_member = member
                continue

            if parts[:2] == ["config", "inputs"] and basename.startswith("PICO-8_input_") and basename.lower().endswith(".map"):
                input_map_member = member
                continue

            if parts[:2] == ["games", "PICO-8"] and basename == "PICO-8":
                binary_member = member
                continue

            if parts[:2] == ["games", "PICO-8"] and basename == "boot.rom":
                bootrom_member = member
                continue

            if parts[:2] == ["games", "PICO-8"] and basename == "pico8_daemon.sh":
                daemon_member = member
                continue

            if parts[:2] == ["docs", "PICO-8"] and basename.lower() == "readme.md":
                readme_member = member
                continue

            if parts[:1] == ["Scripts"] and basename == "Install_PICO-8.sh":
                install_script_member = member
                continue

        missing = []
        if rbf_member is None:
            missing.append("_Other/PICO-8_*.rbf")
        if binary_member is None:
            missing.append("games/PICO-8/PICO-8")
        if bootrom_member is None:
            missing.append("games/PICO-8/boot.rom")
        if daemon_member is None:
            missing.append("games/PICO-8/pico8_daemon.sh")
        if readme_member is None:
            missing.append("docs/PICO-8/README.md")
        if install_script_member is None:
            missing.append("Scripts/Install_PICO-8.sh")

        if missing:
            raise RuntimeError(
                tr("extras_tab.archive_missing_pico8_files", files="\n- ".join(missing))
            )

        _ensure_remote_dir(connection, PICO8_REMOTE_RBF_DIR)
        _ensure_remote_dir(connection, PICO8_REMOTE_GAME_DIR)
        _ensure_remote_dir(connection, posixpath.join(PICO8_REMOTE_GAME_DIR, "Carts"))
        _ensure_remote_dir(connection, "/media/fat/logs/PICO-8")
        _ensure_remote_dir(connection, "/media/fat/saves/PICO-8")
        _ensure_remote_dir(connection, PICO8_REMOTE_DOCS_DIR)
        _ensure_remote_dir(connection, PICO8_REMOTE_SCRIPTS_DIR)
        _ensure_remote_dir(connection, PICO8_REMOTE_INPUTS_DIR)

        log(tr("extras_tab.log_remove_old_pico8_other"))
        _remove_glob(connection, "/media/fat/_Other/PICO-8_*.rbf")

        log(tr("extras_tab.log_remove_legacy_pico8_console"))
        _remove_glob(connection, "/media/fat/_Console/PICO-8_*.rbf")

        log(tr("extras_tab.log_remove_old_pico8_input_maps"))
        _remove_glob(connection, "/media/fat/config/inputs/PICO-8_input_*.map")

        uploads = [
            (
                rbf_member,
                posixpath.join(
                    PICO8_REMOTE_RBF_DIR,
                    posixpath.basename(rbf_member.filename.replace("\\", "/")),
                ),
            ),
            (binary_member, PICO8_REMOTE_BINARY_PATH),
            (bootrom_member, PICO8_REMOTE_BOOTROM_PATH),
            (daemon_member, PICO8_REMOTE_DAEMON_PATH),
            (readme_member, PICO8_REMOTE_README_PATH),
            (install_script_member, PICO8_REMOTE_INSTALL_SCRIPT_PATH),
        ]

        if input_map_member is not None:
            uploads.insert(
                1,
                (
                    input_map_member,
                    posixpath.join(
                        PICO8_REMOTE_INPUTS_DIR,
                        posixpath.basename(input_map_member.filename.replace("\\", "/")),
                    ),
                ),
            )

        sftp = connection.client.open_sftp()
        try:
            for member, destination in uploads:
                data = zf.read(member)
                log(tr("extras_tab.log_uploading_path", path=destination))

                with sftp.open(destination, "wb") as remote_file:
                    remote_file.write(data)
        finally:
            sftp.close()

    connection.run_command(f"chmod +x {_quote(PICO8_REMOTE_BINARY_PATH)}")
    connection.run_command(f"chmod +x {_quote(PICO8_REMOTE_DAEMON_PATH)}")
    connection.run_command(f"chmod +x {_quote(PICO8_REMOTE_INSTALL_SCRIPT_PATH)}")

    added_startup = _ensure_startup_line(
        connection,
        PICO8_REMOTE_USER_STARTUP_PATH,
        PICO8_DAEMON_STARTUP_LINE,
    )

    if added_startup:
        log(tr("extras_tab.log_pico8_startup_added"))
    else:
        log(tr("extras_tab.log_pico8_startup_already_present"))

    _write_installed_pico8_version(connection, version)
    log(tr("extras_tab.log_stored_version_marker", version=version))

    return {
        "installed_version": version,
    }


def install_or_update_sonic_mania(connection, log):
    if not connection.is_connected():
        raise RuntimeError(tr("extras_tab.not_connected"))

    latest = _fetch_latest_sonic_mania_release()
    version = latest["version"]
    zip_url = latest["zip_url"]

    log(tr("extras_tab.log_latest_version", version=version))
    log(tr("extras_tab.log_downloading", url=zip_url))

    response = requests.get(zip_url, timeout=60)
    response.raise_for_status()
    archive_data = response.content

    log(tr("extras_tab.log_downloaded_bytes", bytes=len(archive_data)))

    with zipfile.ZipFile(io.BytesIO(archive_data)) as zf:
        members = [m for m in zf.infolist() if not m.is_dir()]
        if not members:
            raise RuntimeError(tr("extras_tab.archive_empty_sonic_mania"))

        log(tr("extras_tab.log_inspecting_archive"))

        payloads = []
        for member in members:
            name = member.filename.replace("\\", "/")
            basename = posixpath.basename(name)
            lower_basename = basename.lower()

            if not basename:
                continue

            if lower_basename in ("readme.txt", "readme.md", "license.txt", "license.md"):
                log(tr("extras_tab.log_skipping_documentation", name=name))
                continue

            payloads.append(member)

        sftp = connection.client.open_sftp()
        try:
            _ensure_remote_dir(connection, SONIC_MANIA_REMOTE_RBF_DIR)
            _ensure_remote_dir(connection, SONIC_MANIA_REMOTE_GAME_DIR)

            log(tr("extras_tab.log_remove_old_sonic_rbf"))
            _remove_glob(connection, "/media/fat/_Other/Sonic_Mania*.rbf")

            for member in payloads:
                name = member.filename.replace("\\", "/")
                basename = posixpath.basename(name)
                data = zf.read(member)

                if basename == "MiSTer_SonicMania":
                    log(tr("extras_tab.log_uploading_launcher", path=SONIC_MANIA_REMOTE_LAUNCHER_PATH))

                    with sftp.open(SONIC_MANIA_REMOTE_LAUNCHER_PATH, "wb") as remote_file:
                        remote_file.write(data)
                    continue

                parts = [p for p in name.split("/") if p]
                if not parts:
                    continue

                if "_Other" in parts:
                    idx = parts.index("_Other")
                    relative = parts[idx + 1:]
                    if not relative:
                        continue

                    relative_path = "/".join(relative)
                    remote_path = posixpath.join("/media/fat/_Other", *relative)
                    _ensure_remote_dir(connection, posixpath.dirname(remote_path))
                    log(tr("extras_tab.log_merging_other", path=relative_path))

                    with sftp.open(remote_path, "wb") as remote_file:
                        remote_file.write(data)
                    continue

                if "games" in parts:
                    idx = parts.index("games")
                    relative = parts[idx + 1:]
                    if not relative:
                        continue

                    if relative == ["sonic-mania", "Data.rsdk"]:
                        log(tr("extras_tab.log_skip_bundled_data_rsdk"))
                        continue

                    relative_path = "/".join(relative)
                    remote_path = posixpath.join("/media/fat/games", *relative)
                    _ensure_remote_dir(connection, posixpath.dirname(remote_path))
                    log(tr("extras_tab.log_merging_games", path=relative_path))

                    with sftp.open(remote_path, "wb") as remote_file:
                        remote_file.write(data)
                    continue

                log(tr("extras_tab.log_skipping_unhandled_file", name=name))

        finally:
            sftp.close()

    connection.run_command(f"chmod +x {_quote(SONIC_MANIA_REMOTE_LAUNCHER_PATH)}")
    connection.run_command(f"chmod +x {_quote('/media/fat/games/sonic-mania/bin/RSDKv5U')}")
    connection.run_command(f"chmod +x {_quote('/media/fat/games/sonic-mania/scripts/run-mania.sh')}")

    ini_added = _ensure_sonic_mania_ini_blocks(connection)
    if ini_added:
        log(tr("extras_tab.log_sonic_ini_added"))
    else:
        log(tr("extras_tab.log_sonic_ini_already_present"))

    _write_installed_sonic_mania_version(connection, version)
    log(tr("extras_tab.log_stored_version_marker", version=version))

    return {
        "installed_version": version,
    }


def upload_3sx_afs(connection, local_path: str, log):
    if not connection.is_connected():
        raise RuntimeError(tr("extras_tab.not_connected"))

    if not os.path.isfile(local_path):
        raise RuntimeError(tr("extras_tab.selected_afs_missing"))

    local_name = os.path.basename(local_path)
    if local_name.lower() != "sf33rd.afs":
        log(tr("extras_tab.warning_selected_afs_name", name=local_name))

    if not (_is_3sx_installed(connection) or _is_old_3sx_installed(connection)):
        raise RuntimeError(tr("extras_tab.threesx_not_installed"))

    if _is_3sx_installed(connection):
        target_resources_dir = REMOTE_RESOURCES_DIR
        target_afs_path = REMOTE_AFS_PATH
    else:
        target_resources_dir = OLD_REMOTE_RESOURCES_DIR
        target_afs_path = OLD_REMOTE_AFS_PATH

    _ensure_remote_dir(connection, target_resources_dir)

    file_size = os.path.getsize(local_path)
    log(tr("extras_tab.log_uploading_asset", path=target_afs_path))
    log(tr("extras_tab.log_file_size", bytes=file_size))

    last_percent = {"value": -1}

    def progress_callback(transferred, total):
        if total <= 0:
            return

        percent = int((transferred / total) * 100)
        if percent != last_percent["value"]:
            last_percent["value"] = percent
            log(f"[PROGRESS] {percent}%")

    sftp = connection.client.open_sftp()
    try:
        sftp.put(local_path, target_afs_path, callback=progress_callback)
    finally:
        sftp.close()

    log(tr("extras_tab.log_upload_completed"))
    return {"afs_present": True}


def upload_sonic_mania_data_rsdk(connection, local_path: str, log):
    if not connection.is_connected():
        raise RuntimeError(tr("extras_tab.not_connected"))

    if not os.path.isfile(local_path):
        raise RuntimeError(tr("extras_tab.selected_data_rsdk_missing"))

    local_name = os.path.basename(local_path)
    if local_name.lower() != "data.rsdk":
        log(tr("extras_tab.warning_selected_data_rsdk_name", name=local_name))

    if not _is_sonic_mania_installed(connection):
        raise RuntimeError(tr("extras_tab.sonic_mania_not_installed"))

    _ensure_remote_dir(connection, SONIC_MANIA_REMOTE_GAME_DIR)

    file_size = os.path.getsize(local_path)
    log(tr("extras_tab.log_uploading_data_rsdk", path=SONIC_MANIA_REMOTE_DATA_RSDK_PATH))
    log(tr("extras_tab.log_file_size", bytes=file_size))

    last_percent = {"value": -1}

    def progress_callback(transferred, total):
        if total <= 0:
            return

        percent = int((transferred / total) * 100)
        if percent != last_percent["value"]:
            last_percent["value"] = percent
            log(f"[PROGRESS] {percent}%")

    sftp = connection.client.open_sftp()
    try:
        sftp.put(local_path, SONIC_MANIA_REMOTE_DATA_RSDK_PATH, callback=progress_callback)
    finally:
        sftp.close()

    log(tr("extras_tab.log_upload_completed"))
    return {"data_rsdk_present": True}


def uninstall_3sx(connection, log):
    if not connection.is_connected():
        raise RuntimeError(tr("extras_tab.not_connected"))

    log(tr("extras_tab.log_removing_path", path=REMOTE_RBF_PATH))
    connection.run_command(f"rm -f {_quote(REMOTE_RBF_PATH)}")

    log(tr("extras_tab.log_removing_path", path=REMOTE_LAUNCHER_PATH))
    connection.run_command(f"rm -f {_quote(REMOTE_LAUNCHER_PATH)}")

    if _path_exists(connection, REMOTE_VERSION_FILE):
        log(tr("extras_tab.log_removing_version_marker", path=REMOTE_VERSION_FILE))
        connection.run_command(f"rm -f {_quote(REMOTE_VERSION_FILE)}")

    log(tr("extras_tab.log_removing_path", path=REMOTE_GAME_DIR))
    connection.run_command(f"rm -rf {_quote(REMOTE_GAME_DIR)}")

    log(tr("extras_tab.log_removing_legacy_path", path=OLD_REMOTE_RBF_PATH))
    connection.run_command(f"rm -f {_quote(OLD_REMOTE_RBF_PATH)}")

    log(tr("extras_tab.log_removing_legacy_path", path=OLD_REMOTE_LAUNCHER_PATH))
    connection.run_command(f"rm -f {_quote(OLD_REMOTE_LAUNCHER_PATH)}")

    if _path_exists(connection, OLD_REMOTE_VERSION_FILE):
        log(tr("extras_tab.log_removing_legacy_version_marker", path=OLD_REMOTE_VERSION_FILE))
        connection.run_command(f"rm -f {_quote(OLD_REMOTE_VERSION_FILE)}")

    log(tr("extras_tab.log_removing_legacy_path", path=OLD_REMOTE_GAME_DIR))
    connection.run_command(f"rm -rf {_quote(OLD_REMOTE_GAME_DIR)}")

    removed_ini = _remove_ini_block(connection)
    if removed_ini:
        log(tr("extras_tab.log_removed_3sx_ini"))
    else:
        log(tr("extras_tab.log_no_3sx_ini_found"))

    return {"uninstalled": True}


def uninstall_pico8(connection, log):
    if not connection.is_connected():
        raise RuntimeError(tr("extras_tab.not_connected"))

    log(tr("extras_tab.log_removing_pico8_other"))
    _remove_glob(connection, "/media/fat/_Other/PICO-8_*.rbf")

    log(tr("extras_tab.log_removing_pico8_console"))
    _remove_glob(connection, "/media/fat/_Console/PICO-8_*.rbf")

    log(tr("extras_tab.log_removing_path", path=PICO8_REMOTE_BINARY_PATH))
    connection.run_command(f"rm -f {_quote(PICO8_REMOTE_BINARY_PATH)}")

    log(tr("extras_tab.log_removing_path", path=PICO8_REMOTE_DAEMON_PATH))
    connection.run_command(f"rm -f {_quote(PICO8_REMOTE_DAEMON_PATH)}")

    log(tr("extras_tab.log_removing_path", path=PICO8_REMOTE_BOOTROM_PATH))
    connection.run_command(f"rm -f {_quote(PICO8_REMOTE_BOOTROM_PATH)}")

    log(tr("extras_tab.log_removing_path", path=PICO8_REMOTE_README_PATH))
    connection.run_command(f"rm -f {_quote(PICO8_REMOTE_README_PATH)}")

    log(tr("extras_tab.log_removing_path", path=PICO8_REMOTE_INSTALL_SCRIPT_PATH))
    connection.run_command(f"rm -f {_quote(PICO8_REMOTE_INSTALL_SCRIPT_PATH)}")

    log(tr("extras_tab.log_removing_pico8_input_maps"))
    _remove_glob(connection, "/media/fat/config/inputs/PICO-8_input_*.map")

    if _path_exists(connection, PICO8_REMOTE_VERSION_FILE):
        log(tr("extras_tab.log_removing_version_marker", path=PICO8_REMOTE_VERSION_FILE))
        connection.run_command(f"rm -f {_quote(PICO8_REMOTE_VERSION_FILE)}")

    removed_startup = _remove_startup_line(
        connection,
        PICO8_REMOTE_USER_STARTUP_PATH,
        PICO8_DAEMON_STARTUP_LINE,
    )

    if removed_startup:
        log(tr("extras_tab.log_pico8_startup_removed"))
    else:
        log(tr("extras_tab.log_pico8_startup_not_found"))

    _remove_if_empty_dir(connection, PICO8_REMOTE_DOCS_DIR)
    _remove_if_empty_dir(connection, PICO8_REMOTE_GAME_DIR)
    _remove_if_empty_dir(connection, PICO8_REMOTE_INPUTS_DIR)
    _remove_if_empty_dir(connection, PICO8_REMOTE_SCRIPTS_DIR)
    _remove_if_empty_dir(connection, PICO8_LEGACY_REMOTE_RBF_DIR)

    return {"uninstalled": True}


def uninstall_sonic_mania(connection, log):
    if not connection.is_connected():
        raise RuntimeError(tr("extras_tab.not_connected"))

    log(tr("extras_tab.log_removing_sonic_rbf"))
    _remove_glob(connection, "/media/fat/_Other/Sonic_Mania*.rbf")

    log(tr("extras_tab.log_removing_path", path=SONIC_MANIA_REMOTE_LAUNCHER_PATH))
    connection.run_command(f"rm -f {_quote(SONIC_MANIA_REMOTE_LAUNCHER_PATH)}")

    if _path_exists(connection, SONIC_MANIA_REMOTE_VERSION_FILE):
        log(tr("extras_tab.log_removing_version_marker", path=SONIC_MANIA_REMOTE_VERSION_FILE))
        connection.run_command(f"rm -f {_quote(SONIC_MANIA_REMOTE_VERSION_FILE)}")

    log(tr("extras_tab.log_removing_path", path=SONIC_MANIA_REMOTE_GAME_DIR))
    connection.run_command(f"rm -rf {_quote(SONIC_MANIA_REMOTE_GAME_DIR)}")

    removed_ini = _remove_sonic_mania_ini_blocks(connection)
    if removed_ini:
        log(tr("extras_tab.log_sonic_ini_removed"))
    else:
        log(tr("extras_tab.log_sonic_ini_not_found"))

    return {"uninstalled": True}