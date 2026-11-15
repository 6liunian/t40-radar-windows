"""Wire constants and codecs shared by the WinUSB transport prototype.

Values are ported from the dual BSD/GPL ath6kl USB and BMI implementation in
this repository.  All multibyte BMI fields are little-endian.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from enum import IntEnum
from typing import Iterable


USB_VID = 0x0CF3
USB_PID = 0x1022
AR6004_HW_3_0_VERSION = 0x31C809F8
TARGET_TYPE_AR6004 = 5
TARGET_VERSION_SENTINEL = 0xFFFFFFFF

USB_CONTROL_REQ_SEND_BMI_CMD = 1
USB_CONTROL_REQ_RECV_BMI_RESP = 2
USB_CONTROL_REQ_DIAG_CMD = 3
USB_CONTROL_REQ_DIAG_RESP = 4


class BmiCommand(IntEnum):
    DONE = 1
    READ_MEMORY = 2
    WRITE_MEMORY = 3
    EXECUTE = 4
    SET_APP_START = 5
    READ_SOC_REGISTER = 6
    WRITE_SOC_REGISTER = 7
    GET_TARGET_INFO = 8
    LZ_STREAM_START = 13
    LZ_DATA = 14


@dataclass(frozen=True)
class EndpointMap:
    control_in: int = 0x81
    data_in: int = 0x82
    data2_in: int = 0x83
    interrupt_in: int = 0x84
    control_out: int = 0x01
    data_low_out: int = 0x02
    data_medium_out: int = 0x03
    data_high_out: int = 0x04

    def required(self) -> frozenset[int]:
        return frozenset(self.__dict__.values())

    def validate(self, discovered: Iterable[int]) -> None:
        missing = self.required() - set(discovered)
        if missing:
            values = ", ".join(f"0x{value:02x}" for value in sorted(missing))
            raise ValueError(f"AR6004 USB interface is missing endpoints: {values}")


@dataclass(frozen=True)
class TargetInfo:
    version: int
    target_type: int | None
    byte_count: int | None
    extended: bool

    @property
    def is_expected_ar6004_hw30(self) -> bool:
        return (
            self.version == AR6004_HW_3_0_VERSION
            and self.target_type == TARGET_TYPE_AR6004
        )


def build_bmi_get_target_info() -> bytes:
    return struct.pack("<I", BmiCommand.GET_TARGET_INFO)


def parse_target_info(data: bytes) -> TargetInfo:
    """Parse either the old 4-byte response or the 12-byte USB response.

    ath6kl's USB HIF reads the packed target-info structure in one transfer.
    Some ROM revisions return only the legacy version word, so accepting both
    formats makes the M1 probe useful across replacement adapters.
    """

    if len(data) == 4:
        (version,) = struct.unpack("<I", data)
        return TargetInfo(version, None, None, False)
    if len(data) != 12:
        raise ValueError(f"unexpected BMI target-info length: {len(data)}")

    byte_count, version, target_type = struct.unpack("<III", data)
    if byte_count == TARGET_VERSION_SENTINEL:
        # Certain USB ROMs place the sentinel in the first word before the
        # complete structure is fetched.  The transport must perform the
        # follow-up read; this codec deliberately rejects an incomplete blob.
        raise ValueError("BMI target-info response contains only the sentinel")
    if byte_count != 12:
        raise ValueError(f"unexpected BMI target-info byte_count: {byte_count}")
    return TargetInfo(version, target_type, byte_count, True)
