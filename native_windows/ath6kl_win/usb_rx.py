"""Queued USB IN transfers, matching ath6kl's 32 x 4096-byte receive pool.

The event callback only copies a completed buffer and requeues the read.
Endpoint recovery runs outside callbacks, after all pending IN transfers drain.
"""
import queue
import threading
import time
from collections import deque
import usb1


class AsyncUsbRx:
    def __init__(self, context, handle, depth=32):
        self.context=context; self.handle=handle; self.depth=depth
        self.queue=queue.Queue(maxsize=512)
        self.stop=threading.Event(); self.paused=threading.Event()
        self.callback_lock=threading.RLock()
        self.error=None; self.fault=None; self.transfers=[]; self.recent=deque()
        self.thread=threading.Thread(target=self.run,name='usb-rx-pool')

    def completed(self, transfer):
        with self.callback_lock:self._completed(transfer)

    def _completed(self, transfer):
        if self.stop.is_set() or self.paused.is_set():return
        status=transfer.getStatus()
        if status!=usb1.TRANSFER_COMPLETED:
            self.fault=status; self.paused.set(); return
        try:
            count=transfer.getActualLength()
            if count:self.queue.put_nowait(bytes(transfer.getBuffer()[:count]))
            transfer.submit()
        except Exception as exc:
            self.error=exc; self.paused.set()

    def drain(self):
        with self.callback_lock:
            for transfer in self.transfers:
                if transfer.isSubmitted():
                    try:transfer.cancel()
                    except usb1.USBErrorNotFound:pass
        deadline=time.monotonic()+10
        while any(t.isSubmitted() for t in self.transfers):
            self.context.handleEventsTimeout(.05)
            if time.monotonic()>deadline:raise RuntimeError('USB RX cancellation did not complete')

    def run(self):
        try:
            for _ in range(self.depth):
                transfer=self.handle.getTransfer()
                transfer.setBulk(0x82,4096,callback=self.completed,timeout=0)
                self.transfers.append(transfer)
                transfer.submit()
            print(f'USB_RX_POOL depth={self.depth} bytes=4096',flush=True)
            while not self.stop.is_set():
                self.context.handleEventsTimeout(.05)
                if self.error:break
                if self.fault is not None:
                    status=self.fault
                    self.drain()
                    if status!=usb1.TRANSFER_STALL:
                        raise RuntimeError(f'USB RX transfer status {status}')
                    now=time.monotonic()
                    while self.recent and now-self.recent[0]>10:self.recent.popleft()
                    if len(self.recent)>=3:raise RuntimeError('Repeated USB RX stalls in 10 seconds')
                    self.recent.append(now)
                    self.handle.clearHalt(0x82)
                    print('USB_RX_POOL_STALL_CLEARED',flush=True)
                    self.fault=None; self.paused.clear()
                    if not self.stop.is_set():
                        for transfer in self.transfers:transfer.submit()
        except Exception as exc:
            self.error=exc
        finally:
            self.paused.set()
            try:self.drain()
            except Exception as exc:self.error=self.error or exc

    def read(self, endpoint, size):
        if endpoint!=0x82:raise ValueError('RX pool owns only endpoint 0x82')
        if self.error:raise self.error
        try:return self.queue.get(timeout=1)
        except queue.Empty:
            if self.error:raise self.error
            raise TimeoutError('Waiting for USB RX pool')

    def __enter__(self):
        self.thread.start(); return self

    def __exit__(self, *args):
        self.stop.set(); self.paused.set()
        self.thread.join()
        for transfer in self.transfers:
            if not transfer.isSubmitted():transfer.close()
