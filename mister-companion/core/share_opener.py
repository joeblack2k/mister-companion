import os
import subprocess
import sys

from core.language import tr


def open_mister_share(ip, username="root", password="1"):
    if not ip:
        raise ValueError(tr("device_core.no_mister_ip"))

    if sys.platform.startswith("win"):
        subprocess.Popen(["explorer", f"\\\\{ip}\\"])
        return

    if sys.platform.startswith("linux"):
        env = os.environ.copy()

        subprocess.run(
            ["gio", "mount", f"smb://{ip}/"],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

        subprocess.Popen(
            ["gio", "open", f"smb://{ip}/"],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        return

    if sys.platform == "darwin":
        username = username or "root"
        password = password or "1"
        home = os.path.expanduser("~")

        for share in ["sdcard", "usb0"]:
            mount_point = os.path.join(home, f"MiSTer_{share}")
            subprocess.run(["mkdir", "-p", mount_point], capture_output=True)
            subprocess.run(
                ["mount_smbfs", f"//{username}:{password}@{ip}/{share}", mount_point],
                capture_output=True
            )

        subprocess.Popen(["open", os.path.join(home, "MiSTer_sdcard")])
        return

    raise RuntimeError(tr("device_core.unsupported_platform", platform=sys.platform))