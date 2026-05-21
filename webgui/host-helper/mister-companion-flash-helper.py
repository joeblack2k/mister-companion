#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

TOKEN_FILE = Path("/etc/mister-companion-flash-helper/token")
HOST = os.environ.get("FLASH_HELPER_HOST", "192.168.2.22")
PORT = int(os.environ.get("FLASH_HELPER_PORT", "18080"))


def token() -> str:
    try:
        return TOKEN_FILE.read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def removable_devices() -> list[dict]:
    raw = subprocess.check_output(
        [
            "lsblk",
            "-J",
            "-b",
            "-o",
            "NAME,PATH,MODEL,SIZE,TYPE,RM,TRAN,HOTPLUG,MOUNTPOINTS,RO",
        ],
        text=True,
    )
    data = json.loads(raw)
    devices = []
    for dev in data.get("blockdevices", []):
        if dev.get("type") != "disk":
            continue
        removable = str(dev.get("rm")) == "1" or dev.get("tran") == "usb" or str(dev.get("hotplug")) == "1"
        if not removable:
            continue
        mounts = dev.get("mountpoints") or []
        if any(m in {"/", "/boot", "/boot/efi"} for m in mounts if m):
            continue
        devices.append(
            {
                "name": dev.get("name"),
                "path": dev.get("path"),
                "model": dev.get("model") or "",
                "size": dev.get("size"),
                "tran": dev.get("tran"),
                "mountpoints": mounts,
                "read_only": str(dev.get("ro")) == "1",
            }
        )
    return devices


def assert_allowed(path: str) -> None:
    allowed = {item["path"] for item in removable_devices()}
    if path not in allowed:
        raise ValueError("Device is not in removable whitelist")


class Handler(BaseHTTPRequestHandler):
    def _auth(self) -> bool:
        expected = token()
        got = self.headers.get("Authorization", "")
        return bool(expected) and got == f"Bearer {expected}"

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/health":
            self._json(200, {"ok": True})
            return
        if not self._auth():
            self._json(401, {"error": "unauthorized"})
            return
        if self.path == "/devices":
            self._json(200, {"devices": removable_devices()})
            return
        self._json(404, {"error": "not found"})

    def do_POST(self) -> None:
        if not self._auth():
            self._json(401, {"error": "unauthorized"})
            return
        if self.path != "/flash":
            self._json(404, {"error": "not found"})
            return
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length) or b"{}")
        device = str(payload.get("device") or "")
        image_path = Path(str(payload.get("image_path") or ""))
        try:
            assert_allowed(device)
            if not image_path.exists() or not str(image_path).startswith("/srv/vm-data/mister-companion-web/var-lib/"):
                raise ValueError("Image path is outside allowed app state")
            if image_path.suffix in {".zip", ".xz", ".gz"}:
                raise ValueError("Compressed images must be extracted before writing")
            subprocess.check_call(["sync"])
            subprocess.check_call(["dd", f"if={image_path}", f"of={device}", "bs=4M", "conv=fsync", "status=none"])
            subprocess.check_call(["sync"])
        except Exception as exc:
            self._json(400, {"ok": False, "error": str(exc)})
            return
        self._json(200, {"ok": True, "device": device})


if __name__ == "__main__":
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
