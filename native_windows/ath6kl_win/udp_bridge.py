"""Restricted radar UDP bridge: 127.0.0.2 <-> 192.168.8.2.

No routing or TCP. Fragmented IPv4 is deliberately rejected for now.
"""
import socket
import struct
import queue
import time
from .network import HOST_IP, checksum, pack_data
from .htc import frame

RADAR_IP = bytes([192, 168, 8, 2])
PORTS = (50007, 40204)

def parse_udp(ethernet):
    if len(ethernet) < 42 or ethernet[12:14] != b'\x08\0':
        return None
    ip = ethernet[14:]
    ihl = (ip[0] & 15) * 4
    length = struct.unpack_from('!H', ip, 2)[0]
    if ip[0] >> 4 != 4 or ihl < 20 or length < ihl + 8 or length > len(ip):
        return None
    if ip[9] != 17 or ip[12:16] != RADAR_IP or ip[16:20] != HOST_IP:
        return None
    if checksum(ip[:ihl]) or struct.unpack_from('!H', ip, 6)[0] & 0x3fff:
        return None
    udp = ip[ihl:length]
    source, destination, size, check = struct.unpack_from('!HHHH', udp)
    if source not in PORTS or destination not in PORTS or size != len(udp):
        return None
    if check and checksum(ip[12:20] + struct.pack('!BBH', 0, 17, size) + udp):
        return None
    return source, destination, udp[8:]

def build_udp(mac, peer, port, payload):
    if port not in PORTS or len(payload) > 1472:
        raise ValueError('Unsupported UDP port or payload size')
    udp = struct.pack('!HHHH', port, port, len(payload) + 8, 0) + payload
    ip = struct.pack('!BBHHHBBH4s4s', 0x45, 0, len(udp) + 20, 0, 0x4000, 64, 17, 0, HOST_IP, RADAR_IP)
    ip = ip[:10] + struct.pack('!H', checksum(ip)) + ip[12:]
    return peer + mac + b'\x08\0' + ip + udp

class UdpBridge:
    def __init__(self, bulk, endpoint, mac, tap_guid=None, tap_ip=None, tap_direct=False):
        self.bulk, self.endpoint, self.mac = bulk, endpoint, mac
        self.peer = None
        self.last_rx = 0.0
        self.next_arp = 0.0
        self.rx = self.tx = self.dropped = 0
        self.reply_queue = queue.Queue(maxsize=64)
        self.replies_sent = 0
        self.sockets = {}
        self.tap = None
        self.tap_direct = tap_direct
        try:
            if tap_direct and (not tap_guid or tap_ip != HOST_IP):
                raise ValueError('Direct TAP requires the host address 192.168.8.1')
            if tap_guid:
                from .tap_debug import TapDebug
                self.tap = TapDebug(tap_guid, mac, tap_ip or bytes([192, 168, 8, 3]), allow_udp=tap_direct)
            if tap_direct:
                return
            for port in PORTS:
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                self.sockets[port] = sock
                sock.bind(('127.0.0.2', port))
                sock.setblocking(False)
        except BaseException:
            self.close()
            raise

    def receive(self, ethernet):
        if getattr(self, 'tap', None) is not None:
            self.tap.receive(ethernet)
        if getattr(self, 'tap_direct', False):
            if parse_udp(ethernet) is not None:
                self.rx += 1
            return
        # Discover the neighbor independently of application UDP. After a
        # reconnect the radar may wait for host traffic before sending UDP.
        if len(ethernet) >= 42 and ethernet[12:14] == b'\x08\x06':
            arp = ethernet[14:42]
            if (arp[:6] == bytes.fromhex('000108000604')
                    and arp[6:8] in (b'\0\1', b'\0\2')
                    and arp[14:18] == RADAR_IP and arp[24:28] == HOST_IP
                    and arp[8:14] == ethernet[6:12]):
                self.peer = arp[8:14]
        parsed = parse_udp(ethernet)
        if parsed is None:
            return
        source, destination, payload = parsed
        self.peer = ethernet[6:12]
        self.last_rx = time.monotonic()
        try:
            self.sockets[source].sendto(payload, ('127.0.0.1', destination))
        except ConnectionResetError:
            # Closing/reopening the panel must not terminate the USB service.
            pass
        self.rx += 1

    def poll(self):
        if getattr(self, 'tap', None) is not None:
            self.tap.poll(lambda packet: self.bulk(2, frame(self.endpoint, pack_data(packet))))
        if getattr(self, 'tap_direct', False):
            self.tx = self.tap.tx
            return
        now = time.monotonic()
        if now >= self.next_arp and (self.peer is None or now - self.last_rx > 5):
            # Standard ARP request also refreshes the radar's host-IP mapping.
            arp = (bytes.fromhex('0001080006040001') + self.mac + HOST_IP
                   + bytes(6) + RADAR_IP)
            self.bulk(2, frame(self.endpoint, pack_data(bytes([255]) * 6 + self.mac + b'\x08\x06' + arp)))
            self.next_arp = now + 2
        for _ in range(8):
            try:
                ethernet = self.reply_queue.get_nowait()
            except queue.Empty:
                break
            self.bulk(2, frame(self.endpoint, pack_data(ethernet)))
            self.replies_sent += 1
        for port, sock in self.sockets.items():
            for _ in range(8):
                try:
                    payload, sender = sock.recvfrom(65535)
                except (BlockingIOError, ConnectionResetError):
                    break
                if sender != ('127.0.0.1', port) or self.peer is None or len(payload) > 1472:
                    self.dropped += 1
                    continue
                ethernet = build_udp(self.mac, self.peer, port, payload)
                self.bulk(2, frame(self.endpoint, pack_data(ethernet)))
                self.tx += 1

    def enqueue_reply(self, ethernet):
        try:
            self.reply_queue.put_nowait(ethernet)
            return True
        except queue.Full:
            self.dropped += 1
            return False

    def close(self):
        if getattr(self, 'tap', None) is not None:
            self.tap.close()
        for sock in self.sockets.values():
            sock.close()
