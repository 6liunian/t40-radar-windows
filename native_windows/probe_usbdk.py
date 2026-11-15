"""UsbDk probe; --boot loads RAM firmware, --services tests WMI handshake."""
import ctypes as c
import struct
import sys
import threading
from pathlib import Path
from ath6kl_win.protocol import parse_target_info

class DeviceId(c.Structure):
    _fields_ = [('device', c.c_wchar * 200), ('instance', c.c_wchar * 200)]

class Request(c.Structure):
    _fields_ = [(name, c.c_uint64) for name in (
        'endpoint', 'buffer', 'length', 'kind', 'iso_count', 'iso_array',
        'transferred', 'status', 'iso_results')]

def main():
    dll = c.WinDLL(r'C:\Program Files\UsbDk Runtime Library\UsbDkHelper.dll')
    dll.UsbDk_StartRedirect.argtypes = [c.POINTER(DeviceId)]
    dll.UsbDk_StartRedirect.restype = c.c_void_p
    dll.UsbDk_StopRedirect.argtypes = [c.c_void_p]
    for name in ('UsbDk_ReadPipe', 'UsbDk_WritePipe'):
        fn = getattr(dll, name)
        fn.argtypes = [c.c_void_p, c.POINTER(Request), c.c_void_p]
        fn.restype = c.c_int
    ident = DeviceId(r'USB\VID_0CF3&PID_1022', '12345678')
    handle = dll.UsbDk_StartRedirect(c.byref(ident))
    if handle in (None, c.c_void_p(-1).value):
        raise RuntimeError('UsbDk_StartRedirect failed')
    print('CAPTURE_OK', flush=True)
    try:
        if '--reset' in sys.argv:
            dll.UsbDk_ResetDevice.argtypes = [c.c_void_p]
            dll.UsbDk_ResetDevice.restype = c.c_int
            print('USB_RESET', dll.UsbDk_ResetDevice(handle), flush=True)
        from ath6kl_win.overlapped import BulkIo
        bulk_io = BulkIo(dll, handle)
        def transfer(incoming, request, payload):
            length = payload if incoming else len(payload)
            setup = struct.pack('<BBHHH', 0xc0 if incoming else 0x40, request, 0, 0, length)
            data = setup + (bytes(length) if incoming else payload)
            buf = c.create_string_buffer(data, len(data))
            req = Request(buffer=c.addressof(buf), length=len(data))
            fn = dll.UsbDk_ReadPipe if incoming else dll.UsbDk_WritePipe
            bulk_io.submit(fn, req, timeout=3000)
            if req.transferred != length:
                raise RuntimeError('Short control transfer')
            return buf.raw[8:]
        def bulk(endpoint, payload):
            incoming = bool(endpoint & 0x80)
            buf = c.create_string_buffer(payload) if incoming else c.create_string_buffer(payload, len(payload))
            req = Request(endpoint=endpoint, buffer=c.addressof(buf), length=c.sizeof(buf), kind=1)
            fn = dll.UsbDk_ReadPipe if incoming else dll.UsbDk_WritePipe
            bulk_io.submit(fn, req)
            if not incoming and req.transferred != len(payload):
                raise RuntimeError('Short bulk write')
            return buf.raw[:req.transferred]
        if '--receive-only' not in sys.argv:
            transfer(False, 1, struct.pack('<I', 8))
            response = transfer(True, 2, 12)
            print('RAW', response.hex(), flush=True)
            info = parse_target_info(response)
            print(info, flush=True)
            if '--boot' in sys.argv:
                if not info.is_expected_ar6004_hw30:
                    raise RuntimeError('Unsupported chip')
                from ath6kl_win.boot import boot
                boot(transfer, Path(__file__).parent / 'firmware')
        if '--boot' in sys.argv or '--receive-only' in sys.argv:
            dll.UsbDk_AbortPipe.argtypes = [c.c_void_p, c.c_uint64]
            buf = c.create_string_buffer(4096)
            req = Request(endpoint=0x82, buffer=c.addressof(buf), length=4096, kind=1)
            timer = threading.Timer(8, lambda: dll.UsbDk_AbortPipe(handle, 0x82))
            timer.start()
            try:
                result = dll.UsbDk_ReadPipe(handle, c.byref(req), None)
            finally:
                timer.cancel()
                timer.join()
            packet = buf.raw[:req.transferred]
            print('HTC_RX', result, hex(req.status), packet.hex(), flush=True)
            if result != 1 or req.status or len(packet) < 14:
                raise RuntimeError('No valid HTC ready packet')
            if packet[0] != 0 or struct.unpack_from('<H', packet, 6)[0] != 1:
                raise RuntimeError('Unexpected HTC message')
            print('HTC_READY_CONFIRMED', flush=True)
            if '--services' in sys.argv:
                from ath6kl_win.htc import connect_services
                endpoints, mac = connect_services(bulk, packet)
                if '--ap' in sys.argv:
                    from ath6kl_win.ap import start_ap
                    start_ap(bulk, endpoints, mac)
                    if '--serve' in sys.argv:
                        from ath6kl_win.monitor import serve
                        serve(bulk, endpoints, mac, Path(__file__).parent / 'runtime')
    finally:
        print('RELEASE', dll.UsbDk_StopRedirect(handle), flush=True)

if __name__ == '__main__':
    main()
