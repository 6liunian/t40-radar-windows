#!/usr/bin/env python3
"""Recover a wedged ath6kl USB AP when an active panel loses radar V2 data."""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path


HEALTH_PATH = Path("/tmp/dji-radar-relay-health.json")
WINDOWS_ACTIVE_SECONDS = 6.0
RADAR_STALE_SECONDS = 12.0
CHECK_SECONDS = 2.0
REQUIRED_STALE_CHECKS = 3
RECOVERY_COOLDOWN_SECONDS = 90.0


def find_usbwlan() -> Path | None:
    for device in Path("/sys/bus/usb/devices").glob("*"):
        try:
            vendor = (device / "idVendor").read_text().strip().lower()
            product = (device / "idProduct").read_text().strip().lower()
        except OSError:
            continue
        if vendor == "0cf3" and product == "1022":
            return device
    return None


def service(action: str, *names: str) -> None:
    subprocess.run(
        ["/usr/bin/systemctl", action, *names],
        check=False,
        timeout=30,
    )


def recover() -> None:
    print("[watchdog] radar V2 stalled; resetting ath6kl USBWLAN", flush=True)
    service("stop", "dji-radar-relay.service", "dji-radar-ap.service")
    device = find_usbwlan()
    if device is not None:
        try:
            (device / "authorized").write_text("0\n")
        except OSError as exc:
            print(f"[watchdog] USB deauthorize failed: {exc}", flush=True)

    # VMware normally reconnects the configured USB device automatically.
    deadline = time.monotonic() + 35.0
    while time.monotonic() < deadline:
        if find_usbwlan() is not None:
            break
        time.sleep(1.0)
    time.sleep(4.0)
    service("start", "dji-radar-ap.service")
    time.sleep(8.0)
    service("start", "dji-radar-relay.service")
    print("[watchdog] AP and relay restart requested", flush=True)


def main() -> None:
    stale_checks = 0
    last_recovery = 0.0
    while True:
        time.sleep(CHECK_SECONDS)
        try:
            health = json.loads(HEALTH_PATH.read_text(encoding="ascii"))
        except (OSError, ValueError, TypeError):
            stale_checks = 0
            continue

        now = time.time()
        windows_at = float(health.get("last_windows_control_at", 0.0))
        radar_at = float(health.get("last_radar_v2_at", 0.0))
        panel_active = 0.0 <= now - windows_at <= WINDOWS_ACTIVE_SECONDS
        radar_stale = radar_at <= 0.0 or now - radar_at >= RADAR_STALE_SECONDS
        if panel_active and radar_stale:
            stale_checks += 1
        else:
            stale_checks = 0

        if (
            stale_checks >= REQUIRED_STALE_CHECKS
            and time.monotonic() - last_recovery >= RECOVERY_COOLDOWN_SECONDS
        ):
            stale_checks = 0
            last_recovery = time.monotonic()
            recover()


if __name__ == "__main__":
    main()
