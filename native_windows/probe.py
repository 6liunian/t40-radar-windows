#!/usr/bin/env python3
"""M0/M1 diagnostic front end for the native AR6004 Windows port.

The default invocation is non-invasive and only prints the expected protocol
and driver state.  Hardware I/O is intentionally gated until the WinUSB
transport implementation and a rollback procedure are ready.
"""

from __future__ import annotations

import argparse
import json
import platform

from ath6kl_win.protocol import (
    AR6004_HW_3_0_VERSION,
    USB_PID,
    USB_VID,
    EndpointMap,
    build_bmi_get_target_info,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--describe",
        action="store_true",
        help="print the expected native transport contract as JSON",
    )
    args = parser.parse_args()
    if not args.describe:
        parser.error("M0 is non-invasive; use --describe")

    endpoints = EndpointMap()
    print(
        json.dumps(
            {
                "host": platform.platform(),
                "usb_id": f"{USB_VID:04x}:{USB_PID:04x}",
                "expected_target_version": f"0x{AR6004_HW_3_0_VERSION:08x}",
                "endpoints": [f"0x{value:02x}" for value in sorted(endpoints.required())],
                "bmi_get_target_info": build_bmi_get_target_info().hex(),
                "hardware_io_enabled": False,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
