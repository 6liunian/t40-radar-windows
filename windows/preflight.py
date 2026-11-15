#!/usr/bin/env python3
from __future__ import annotations

import ctypes
import argparse
import os
import socket
import sys
from pathlib import Path


RADAR_IP = "192.168.8.2"
PCAN_CHANNEL = "PCAN_USBBUS1"
PCAN_DLL = Path(__file__).resolve().parent / "pcan-basic-x64" / "x64" / "PCANBasic.dll"
_dll_dir_handle = None

if sys.platform == "win32" and PCAN_DLL.exists():
    os.environ["PATH"] = f"{PCAN_DLL.parent}{os.pathsep}{os.environ.get('PATH', '')}"
    _dll_dir_handle = os.add_dll_directory(str(PCAN_DLL.parent))


def check_pcan_dll() -> bool:
    try:
        ctypes.WinDLL(str(PCAN_DLL) if PCAN_DLL.exists() else "PCANBasic.dll")
    except OSError as exc:
        print(f"[FAIL] PCANBasic.dll: {exc}")
        print("       Install the PCAN Windows driver with PCAN-Basic selected.")
        return False
    print("[ OK ] PCANBasic.dll is loadable")
    return True


def check_pcan_channel(channel: str) -> bool:
    try:
        import can
        bus = can.Bus(
            interface="pcan",
            channel=channel,
            bitrate=1_000_000,
        )
    except Exception as exc:
        print(f"[FAIL] {channel}: {exc}")
        return False
    try:
        print(f"[ OK ] {channel} opened at 1,000,000 bit/s")
    finally:
        bus.shutdown()
    return True


def check_local_ip(local_ip: str) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.bind((local_ip, 0))
    except OSError as exc:
        print(f"[FAIL] local address {local_ip}: {exc}")
        return False
    finally:
        sock.close()
    print(f"[ OK ] local address {local_ip} is configured")
    return True


def check_radar_ssh(radar_ip: str, radar_ssh_port: int) -> bool:
    try:
        with socket.create_connection((radar_ip, radar_ssh_port), timeout=2.0) as sock:
            sock.settimeout(5.0)
            banner = sock.recv(64)
            if not banner.startswith(b"SSH-"):
                raise OSError("TCP relay opened, but no SSH banner arrived from the radar")
    except OSError as exc:
        print(f"[FAIL] radar SSH {radar_ip}:{radar_ssh_port}: {exc}")
        print("       Check the radar AP/relay and radar power.")
        return False
    print(f"[ OK ] radar SSH is reachable at {radar_ip}:{radar_ssh_port}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Check native Windows radar prerequisites")
    parser.add_argument("--can-channel", default=PCAN_CHANNEL)
    parser.add_argument("--local-ip", default="192.168.8.1")
    parser.add_argument("--radar-ip", default=RADAR_IP)
    parser.add_argument("--radar-ssh-port", type=int, default=107)
    args = parser.parse_args()
    if sys.platform != "win32":
        print("This preflight check is intended for native Windows.")
        return 2
    print(f"Project: {Path(__file__).resolve().parents[1]}")
    checks = [
        check_pcan_dll(),
        check_pcan_channel(args.can_channel),
        check_local_ip(args.local_ip),
        check_radar_ssh(args.radar_ip, args.radar_ssh_port),
    ]
    passed = sum(checks)
    print(f"\nResult: {passed}/{len(checks)} checks passed")
    return 0 if all(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())

