"""Synchronous bulk I/O with bounded RX endpoint stall recovery.

Only one reader owns each IN endpoint; after its transfer has returned PIPE
there are no pending reads on that endpoint. Never replay an OUT command.
"""
import time
from collections import deque
import usb1


class UsbBulk:
    def __init__(self, handle, clock=time.monotonic, context=None):
        self.handle = handle
        self.context = context
        self.clock = clock
        self.recent_clears = {}
        self.stall_recoveries = 0

    def __call__(self, endpoint, payload):
        try:
            if endpoint & 0x80:
                try:
                    return bytes(self.handle.bulkRead(endpoint, payload, timeout=8000))
                except usb1.USBErrorPipe:
                    now = self.clock()
                    recent = self.recent_clears.setdefault(endpoint, deque())
                    while recent and now-recent[0] > 10:
                        recent.popleft()
                    if len(recent) >= 3:
                        raise
                    recent.append(now)
                    print(f'USB_RX_STALL endpoint={endpoint:#x}; clearing once', flush=True)
                    self.handle.clearHalt(endpoint)
                    result = bytes(self.handle.bulkRead(endpoint, payload, timeout=8000))
                    self.stall_recoveries += 1
                    print(f'USB_RX_RESUMED count={self.stall_recoveries}', flush=True)
                    return result
            count = (self.write_terminated(endpoint, payload) if self.context is not None
                     else self.handle.bulkWrite(endpoint, payload, timeout=8000))
            if count != len(payload):
                raise RuntimeError('Short bulk write')
            return b''
        except usb1.USBErrorTimeout as exc:
            raise TimeoutError(f'USB endpoint {endpoint:#x} timed out') from exc

    def write_terminated(self, endpoint, payload):
        # WinUSB fixes SHORT_PACKET_TERMINATE on the first endpoint transfer.
        # Always request the policy, including during HTC startup, rather than
        # switching it on only for a later exact-multiple write.
        transfer = self.handle.getTransfer(add_zero_packet=True)
        try:
            transfer.setBulk(endpoint, payload, callback=lambda _: None, timeout=8000)
            transfer.submit()
            while transfer.isSubmitted():
                self.context.handleEventsTimeout(.005)
            status = transfer.getStatus()
            if status == usb1.TRANSFER_TIMED_OUT:raise usb1.USBErrorTimeout()
            if status == usb1.TRANSFER_STALL:raise usb1.USBErrorPipe()
            if status == usb1.TRANSFER_NO_DEVICE:raise usb1.USBErrorNoDevice()
            if status != usb1.TRANSFER_COMPLETED:raise usb1.USBErrorIO()
            count = transfer.getActualLength()
            if payload and len(payload)%512 == 0:
                print(f'USB_TX_ZLP endpoint={endpoint:#x} bytes={len(payload)}',flush=True)
            return count
        finally:
            if transfer.isSubmitted():
                try:transfer.cancel()
                except usb1.USBErrorNotFound:pass
                while transfer.isSubmitted():self.context.handleEventsTimeout(.05)
            transfer.close()
