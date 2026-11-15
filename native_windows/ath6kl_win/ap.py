"""Experimental open AP configuration using ath6kl WMI wire commands."""
import struct
import time
from .htc import frame, decode

def profile(ssid=b'radar_wifi', frequency=5240):
    if not 1 <= len(ssid) <= 32 or frequency != 5240:
        raise ValueError('Only the validated SSID length and channel 48 are supported')
    return struct.pack('<8B32sH6sIB', 16, 1, 1, 1, 0, 1, 0, len(ssid), ssid, frequency, bytes(6), 0, 0)

def start_ap(bulk, endpoints, mac):
    def command(cmd, data):
        bulk(1, frame(endpoints[0x100], struct.pack('<HHH', cmd, 0, 0) + data))
        print('WMI_COMMAND_SENT', hex(cmd), flush=True)
    command(0x0f, struct.pack('<I', 100))
    command(0xf015, struct.pack('<I', 2))
    command(0xf00b, b'\0')
    command(0xf05a, b'\1')
    command(0xf00f, profile())
    deadline = time.monotonic() + 25
    started = False
    while time.monotonic() < deadline:
        ep, payload = decode(bulk(0x82, 4096))
        print('AP_EVENT', ep, payload.hex(), flush=True)
        if ep != endpoints[0x100] or len(payload) < 6:
            continue
        event = struct.unpack_from('<H', payload)[0]
        if event == 0x1005:
            raise RuntimeError('Firmware rejected WMI command: ' + payload.hex())
        if event == 0x1002 and len(payload) >= 25:
            if payload[8:14] == mac:
                channel = struct.unpack_from('<H', payload, 6)[0]
                if channel != 5240:
                    raise RuntimeError('Unexpected AP channel')
                started = True
                print('AP_STARTED_CONFIRMED radar_wifi channel=48', flush=True)
                return
    if not started:
        raise RuntimeError('No AP start event')
