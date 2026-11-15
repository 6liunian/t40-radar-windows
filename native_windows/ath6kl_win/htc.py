"""Minimal HTC service handshake; wire layout from local ath6kl headers."""
import struct
import threading


class HtcUsbTransport:
    """Match ath6kl htc_pipe.c TX flags and per-endpoint sequence counters.

    Apply only to HTC bulk traffic, never to BMI endpoint-zero controls.
    Keep reads outside the TX lock so synchronous USB RX cannot stall TX.
    """
    def __init__(self, bulk):
        self.bulk = bulk
        self.sequences = {}
        self.tx_lock = threading.Lock()

    def __call__(self, usb_endpoint, payload):
        if usb_endpoint & 0x80:
            return self.bulk(usb_endpoint, payload)
        endpoint, _ = decode(payload)
        with self.tx_lock:
            sequence = self.sequences.get(endpoint, 0)
            packet = bytearray(payload)
            packet[1] |= 4  # HTC_FLAGS_TX_FIXUP_NETBUF
            packet[4] = 0
            packet[5] = sequence
            self.sequences[endpoint] = (sequence + 1) & 255
            return self.bulk(usb_endpoint, bytes(packet))

def frame(endpoint, payload):
    return struct.pack('<BBHBB', endpoint, 0, len(payload), 0, 0) + payload

def decode(packet):
    if len(packet) < 6:
        raise ValueError('Short HTC header')
    endpoint, flags, length, trailer, _ = struct.unpack_from('<BBHBB', packet)
    if len(packet) != length + 6:
        raise ValueError('HTC length mismatch')
    payload = packet[6:]
    if flags & 2:
        if trailer > len(payload):
            raise ValueError('Invalid HTC trailer')
        if trailer:
            payload = payload[:-trailer]
    return endpoint, payload

def connect_services(bulk, ready):
    endpoint, payload = decode(ready)
    if endpoint or len(payload) != 10:
        raise ValueError('Invalid ready frame')
    message, credits, size, max_ep, _, version, _ = struct.unpack('<HHHBBBB', payload)
    if message != 1 or not credits or not size:
        raise ValueError('Invalid ready resources')
    unit = (1536 + size - 1) // size
    vi = max(1, credits // 4)
    vo = max(1, (credits - vi) // 4)
    be = credits - vi - vo - 2 * unit
    if be <= 0:
        raise ValueError('Insufficient credits')
    endpoints = {}
    for service, alloc in ((0x100, unit), (0x101, be), (0x102, unit), (0x103, vi), (0x104, vo)):
        flags = (alloc << 8) | (8 if service == 0x100 else 13)
        bulk(0x01, frame(0, struct.pack('<HHHBB', 2, service, flags, 0, 0)))
        ep, response = decode(bulk(0x82, 4096))
        if ep or len(response) < 10:
            raise ValueError('Invalid connection response')
        msg, svc, status, assigned, maximum, meta, _ = struct.unpack_from('<HHBBHBB', response)
        if msg != 3 or svc != service or status or not 0 < assigned < max_ep or not maximum:
            raise ValueError('Service rejected: ' + response.hex())
        if assigned in endpoints.values():
            raise ValueError('Duplicate endpoint')
        endpoints[service] = assigned
        print('SERVICE_CONNECTED', hex(service), assigned, maximum, flush=True)
    bulk(0x01, frame(0, struct.pack('<HIB3x', 5, 0, 0)))
    for _ in range(12):
        ep, payload = decode(bulk(0x82, 4096))
        print('WMI_RX', ep, payload.hex(), flush=True)
        if ep == endpoints[0x100] and len(payload) >= 21 and struct.unpack_from('<H', payload)[0] == 0x1001:
            sw, abi = struct.unpack_from('<II', payload, 6)
            print('WMI_READY_CONFIRMED', hex(sw), hex(abi), payload[14:20].hex(':'), flush=True)
            return endpoints, payload[14:20]
    raise RuntimeError('WMI_READY not received')
