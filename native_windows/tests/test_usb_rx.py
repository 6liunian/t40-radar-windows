import queue
import unittest
from unittest.mock import Mock
import usb1
from ath6kl_win.usb_rx import AsyncUsbRx


class AsyncRxTests(unittest.TestCase):
    def transfer(self, status=usb1.TRANSFER_COMPLETED):
        return Mock(getStatus=Mock(return_value=status),getActualLength=Mock(return_value=3),
                    getBuffer=Mock(return_value=bytearray(b'abcPAD')))

    def test_copy_exact_bytes_before_resubmitting(self):
        rx=AsyncUsbRx(Mock(),Mock()); transfer=self.transfer()
        rx.completed(transfer)
        self.assertEqual(rx.read(0x82,4096),b'abc')
        transfer.submit.assert_called_once()

    def test_stall_does_not_submit_or_clear_in_callback(self):
        rx=AsyncUsbRx(Mock(),Mock()); transfer=self.transfer(usb1.TRANSFER_STALL)
        rx.completed(transfer)
        self.assertTrue(rx.paused.is_set())
        self.assertEqual(rx.fault,usb1.TRANSFER_STALL)
        transfer.submit.assert_not_called(); rx.handle.clearHalt.assert_not_called()

    def test_no_callback_resubmit_after_stop(self):
        rx=AsyncUsbRx(Mock(),Mock()); transfer=self.transfer()
        rx.stop.set(); rx.completed(transfer)
        transfer.submit.assert_not_called()
        self.assertTrue(rx.queue.empty())

    def test_full_queue_surfaces_error_instead_of_silent_drop(self):
        rx=AsyncUsbRx(Mock(),Mock()); transfer=self.transfer()
        rx.queue=queue.Queue(maxsize=1); rx.queue.put(b'old')
        rx.completed(transfer)
        with self.assertRaises(queue.Full):rx.read(0x82,4096)
        transfer.submit.assert_not_called()

    def test_pool_cancels_before_clearing_stall(self):
        rx=AsyncUsbRx(Mock(),Mock(),depth=2)
        trace=[]
        class Transfer:
            submitted=False
            def setBulk(self,*args,**kwargs):pass
            def submit(self):self.submitted=True; trace.append('submit')
            def isSubmitted(self):return self.submitted
            def cancel(self):self.submitted=False; trace.append('cancel')
            def close(self):pass
        rx.handle.getTransfer.side_effect=[Transfer(),Transfer()]
        def clear(endpoint):
            self.assertFalse(any(t.isSubmitted() for t in rx.transfers))
            trace.append('clear')
        rx.handle.clearHalt.side_effect=clear
        def events(*args):
            if 'clear' in trace:rx.stop.set()
            else:rx.fault=usb1.TRANSFER_STALL;rx.paused.set()
        rx.context.handleEventsTimeout.side_effect=events
        rx.run()
        self.assertIsNone(rx.error)
        self.assertEqual(trace,['submit','submit','cancel','cancel','clear','submit','submit','cancel','cancel'])
