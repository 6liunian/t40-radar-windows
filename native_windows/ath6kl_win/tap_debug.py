"""Optional Windows TCP diagnostic path on 192.168.8.3 via an existing TAP.

TAP IOCTL definitions: OpenVPN/tap-windows6 src/tap-windows.h.
No routing, default gateway, DNS, or adapter installation is performed here.
Only this host IP and the radar IP are forwarded; the panel retains .8.1.
"""
import ctypes as c
from ctypes import wintypes as w
import queue
import struct
from .overlapped import Overlapped

DEBUG_IP = bytes([192, 168, 8, 3])
RADAR_IP = bytes([192, 168, 8, 2])


def translate(packet, source_mac, target_mac, outgoing, debug_ip=DEBUG_IP, allow_udp=False):
    if len(packet) < 14:
        return None
    data = bytearray(packet)
    if data[12:14] == b'\x08\x06':
        if len(data) < 42 or data[14:20] != bytes.fromhex('000108000604'):
            return None
        sender, target = bytes(data[28:32]), bytes(data[38:42])
        if (sender, target) != ((debug_ip, RADAR_IP) if outgoing else (RADAR_IP, debug_ip)):
            return None
        for start in (22, 32):
            if data[start:start+6] == source_mac:
                data[start:start+6] = target_mac
    elif data[12:14] == b'\x08\0':
        if len(data) < 34:
            return None
        if data[23] not in ((1, 6, 17) if allow_udp else (1, 6)):
            return None  # Never feed panel UDP into the Windows TCP stack.
        sender, target = bytes(data[26:30]), bytes(data[30:34])
        if (sender, target) != ((debug_ip, RADAR_IP) if outgoing else (RADAR_IP, debug_ip)):
            return None
    else:
        return None
    for start in (0, 6):
        if data[start:start+6] == source_mac:
            data[start:start+6] = target_mac
    return bytes(data)


class TapDebug:
    def __init__(self, guid, ap_mac, debug_ip=DEBUG_IP, allow_udp=False):
        self.ap_mac = ap_mac
        self.debug_ip = debug_ip
        self.allow_udp = allow_udp
        self.kernel = c.WinDLL('kernel32', use_last_error=True)
        signatures = {
            'CreateFileW': ([w.LPCWSTR, w.DWORD, w.DWORD, c.c_void_p, w.DWORD, w.DWORD, w.HANDLE], w.HANDLE),
            'CreateEventW': ([c.c_void_p, w.BOOL, w.BOOL, w.LPCWSTR], w.HANDLE),
            'CloseHandle': ([w.HANDLE], w.BOOL),
            'ReadFile': ([w.HANDLE, c.c_void_p, w.DWORD, c.POINTER(w.DWORD), c.POINTER(Overlapped)], w.BOOL),
            'WriteFile': ([w.HANDLE, c.c_void_p, w.DWORD, c.POINTER(w.DWORD), c.POINTER(Overlapped)], w.BOOL),
            'DeviceIoControl': ([w.HANDLE, w.DWORD, c.c_void_p, w.DWORD, c.c_void_p, w.DWORD, c.POINTER(w.DWORD), c.POINTER(Overlapped)], w.BOOL),
            'WaitForSingleObject': ([w.HANDLE, w.DWORD], w.DWORD),
            'GetOverlappedResult': ([w.HANDLE, c.POINTER(Overlapped), c.POINTER(w.DWORD), w.BOOL], w.BOOL),
            'CancelIoEx': ([w.HANDLE, c.POINTER(Overlapped)], w.BOOL),
        }
        for name, (args, result) in signatures.items():
            fn = getattr(self.kernel, name)
            fn.argtypes, fn.restype = args, result
        self.handle = self.kernel.CreateFileW('\\\\.\\Global\\' + guid + '.tap',
                                              0xc0000000, 0, None, 3, 0x40000000, None)
        if self.handle in (None, c.c_void_p(-1).value):
            raise c.WinError(c.get_last_error())
        self.read_op = None
        self.queue = queue.Queue(maxsize=256)
        self.rx = self.tx = 0
        self.tcp_tx = 0
        try:
            mac = c.create_string_buffer(6)
            self.ioctl((0x22 << 16) | (1 << 2), mac, 6, mac, 6)
            self.mac = mac.raw
            value = w.DWORD(1)
            self.ioctl((0x22 << 16) | (6 << 2), c.byref(value), 4, c.byref(value), 4)
            print('TAP_DEBUG_OPEN', guid, self.mac.hex(':'), flush=True)
        except BaseException:
            self.close()
            raise

    def operation(self):
        event = self.kernel.CreateEventW(None, True, False, None)
        if not event:
            raise c.WinError(c.get_last_error())
        return Overlapped(event=event)

    def complete(self, op, result, timeout=1000):
        count = w.DWORD()
        if not result:
            error = c.get_last_error()
            if error != 997:
                raise c.WinError(error)
            if self.kernel.WaitForSingleObject(op.event, timeout) != 0:
                self.kernel.CancelIoEx(self.handle, c.byref(op))
                self.kernel.GetOverlappedResult(self.handle, c.byref(op), c.byref(count), True)
                raise TimeoutError('TAP I/O timeout')
        if not self.kernel.GetOverlappedResult(self.handle, c.byref(op), c.byref(count), False):
            raise c.WinError(c.get_last_error())
        return count.value

    def ioctl(self, code, inp, inlen, out, outlen):
        op = self.operation()
        count = w.DWORD()
        try:
            result = self.kernel.DeviceIoControl(self.handle, code, inp, inlen, out, outlen, c.byref(count), c.byref(op))
            return self.complete(op, result)
        finally:
            self.kernel.CloseHandle(op.event)

    def receive(self, packet):
        translated = translate(packet, self.ap_mac, self.mac, False, self.debug_ip, self.allow_udp)
        if translated is not None:
            try:
                self.queue.put_nowait(translated)
            except queue.Full:
                pass

    def poll(self, send):
        for _ in range(8):
            try:
                packet = self.queue.get_nowait()
            except queue.Empty:
                break
            op = self.operation()
            buf = c.create_string_buffer(packet)
            try:
                result = self.kernel.WriteFile(self.handle, buf, len(packet), None, c.byref(op))
                if self.complete(op, result) != len(packet):
                    raise RuntimeError('Short TAP write')
                self.rx += 1
            finally:
                self.kernel.CloseHandle(op.event)
        for _ in range(8):
            if self.read_op is None:
                self.read_buf = c.create_string_buffer(65536)
                self.read_op = self.operation()
                result = self.kernel.ReadFile(self.handle, self.read_buf, 65536, None, c.byref(self.read_op))
                if not result and c.get_last_error() != 997:
                    raise c.WinError(c.get_last_error())
            if self.kernel.WaitForSingleObject(self.read_op.event, 0) != 0:
                break
            count = w.DWORD()
            if not self.kernel.GetOverlappedResult(self.handle, c.byref(self.read_op), c.byref(count), False):
                raise c.WinError(c.get_last_error())
            packet = self.read_buf.raw[:count.value]
            self.kernel.CloseHandle(self.read_op.event)
            self.read_op = None
            translated = translate(packet, self.mac, self.ap_mac, True, self.debug_ip, self.allow_udp)
            if translated is not None:
                if len(translated)>=34 and translated[12:14]==b'\x08\x00' and translated[23]==6:
                    self.tcp_tx += 1
                    if self.tcp_tx<=30:print('TAP_TCP_TX',translated[:96].hex(),flush=True)
                if self.tx < 30:
                    print('TAP_TX', translated[:80].hex(), flush=True)
                send(translated)
                self.tx += 1

    def close(self):
        if self.read_op is not None:
            count = w.DWORD()
            self.kernel.CancelIoEx(self.handle, c.byref(self.read_op))
            self.kernel.GetOverlappedResult(self.handle, c.byref(self.read_op), c.byref(count), True)
            self.kernel.CloseHandle(self.read_op.event)
            self.read_op = None
        self.kernel.CloseHandle(self.handle)
