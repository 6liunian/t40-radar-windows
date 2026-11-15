"""Per-request Windows OVERLAPPED state for concurrent UsbDk bulk transfers."""
import ctypes as c
from ctypes import wintypes as w

class Overlapped(c.Structure):
    _fields_ = [('internal', c.c_size_t), ('internal_high', c.c_size_t),
                ('offset', w.DWORD), ('offset_high', w.DWORD), ('event', w.HANDLE)]

class BulkIo:
    def __init__(self, dll, handle):
        self.dll, self.handle = dll, handle
        dll.UsbDk_GetRedirectorSystemHandle.argtypes = [c.c_void_p]
        dll.UsbDk_GetRedirectorSystemHandle.restype = w.HANDLE
        self.system_handle = dll.UsbDk_GetRedirectorSystemHandle(handle)
        if self.system_handle in (None, c.c_void_p(-1).value):
            raise RuntimeError('Invalid redirector system handle')
        self.kernel = c.WinDLL('kernel32', use_last_error=True)
        signatures = {
            'CreateEventW': ([c.c_void_p, w.BOOL, w.BOOL, w.LPCWSTR], w.HANDLE),
            'CloseHandle': ([w.HANDLE], w.BOOL),
            'WaitForSingleObject': ([w.HANDLE, w.DWORD], w.DWORD),
            'GetOverlappedResult': ([w.HANDLE, c.POINTER(Overlapped), c.POINTER(w.DWORD), w.BOOL], w.BOOL),
            'CancelIoEx': ([w.HANDLE, c.POINTER(Overlapped)], w.BOOL),
        }
        for name, (args, result) in signatures.items():
            fn = getattr(self.kernel, name)
            fn.argtypes, fn.restype = args, result

    def submit(self, fn, request, timeout=8000):
        event = self.kernel.CreateEventW(None, True, False, None)
        if not event:
            raise c.WinError(c.get_last_error())
        ov = Overlapped(event=event)
        count = w.DWORD()
        try:
            result = fn(self.handle, c.byref(request), c.byref(ov))
            if result == 0:
                raise RuntimeError(f'UsbDk submit failed, endpoint={request.endpoint:#x}')
            if result == 2:
                wait = self.kernel.WaitForSingleObject(event, timeout)
                if wait != 0:
                    self.kernel.CancelIoEx(self.system_handle, c.byref(ov))
                    # Drain cancellation before releasing buffer/OVERLAPPED memory.
                    self.kernel.GetOverlappedResult(self.system_handle, c.byref(ov), c.byref(count), True)
                    if wait == 258:
                        raise TimeoutError(f'Bulk {request.endpoint:#x} timed out')
                    raise RuntimeError(f'Overlapped wait failed: {wait:#x}')
                if not self.kernel.GetOverlappedResult(self.system_handle, c.byref(ov), c.byref(count), False):
                    raise c.WinError(c.get_last_error())
            elif result != 1:
                raise RuntimeError(f'Unknown UsbDk result {result}')
            if request.status:
                raise RuntimeError(f'USB status {request.status:#x} endpoint={request.endpoint:#x}')
        finally:
            self.kernel.CloseHandle(event)
