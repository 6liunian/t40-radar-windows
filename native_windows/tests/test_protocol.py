from __future__ import annotations

import struct
import unittest

from ath6kl_win.protocol import (
    AR6004_HW_3_0_VERSION,
    TARGET_TYPE_AR6004,
    EndpointMap,
    build_bmi_get_target_info,
    parse_target_info,
)


class ProtocolTests(unittest.TestCase):
    def test_bmi_get_target_info_command_is_little_endian(self) -> None:
        self.assertEqual(build_bmi_get_target_info(), b"\x08\x00\x00\x00")

    def test_parse_usb_target_info(self) -> None:
        raw = struct.pack("<III", 12, AR6004_HW_3_0_VERSION, TARGET_TYPE_AR6004)
        info = parse_target_info(raw)
        self.assertTrue(info.extended)
        self.assertTrue(info.is_expected_ar6004_hw30)

    def test_parse_legacy_target_info(self) -> None:
        info = parse_target_info(struct.pack("<I", AR6004_HW_3_0_VERSION))
        self.assertFalse(info.extended)
        self.assertEqual(info.version, AR6004_HW_3_0_VERSION)

    def test_endpoint_validation(self) -> None:
        endpoints = EndpointMap()
        endpoints.validate(endpoints.required() | {0x05})
        with self.assertRaisesRegex(ValueError, "0x84"):
            endpoints.validate(endpoints.required() - {0x84})


if __name__ == "__main__":
    unittest.main()
