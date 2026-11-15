import unittest
from unittest.mock import Mock
import usb1
from ath6kl_win.usb_bulk import UsbBulk


class BulkTests(unittest.TestCase):
    def test_out_policy_set_for_first_and_boundary_packets(self):
        for size in (18,512,1024):
            handle=Mock(); transfer=handle.getTransfer.return_value
            transfer.isSubmitted.side_effect=[True,False,False]
            transfer.getStatus.return_value=usb1.TRANSFER_COMPLETED
            transfer.getActualLength.return_value=size
            context=Mock()
            self.assertEqual(UsbBulk(handle,context=context)(2,bytes(size)),b'')
            handle.getTransfer.assert_called_once_with(add_zero_packet=True)
            transfer.submit.assert_called_once()
            transfer.close.assert_called_once()
            handle.bulkWrite.assert_not_called()

    def test_terminated_out_failure_not_replayed(self):
        handle=Mock(); transfer=handle.getTransfer.return_value
        transfer.isSubmitted.return_value=False
        transfer.getStatus.return_value=usb1.TRANSFER_STALL
        with self.assertRaises(usb1.USBErrorPipe):
            UsbBulk(handle,context=Mock())(2,bytes(512))
        transfer.submit.assert_called_once()
        transfer.close.assert_called_once()

    def test_stall_clear_then_read(self):
        handle = Mock()
        handle.bulkRead.side_effect = [usb1.USBErrorPipe(), b'packet']
        bulk = UsbBulk(handle)
        self.assertEqual(bulk(0x82, 16384), b'packet')
        handle.clearHalt.assert_called_once_with(0x82)
        self.assertEqual(bulk.stall_recoveries, 1)

    def test_persistent_stall_propagates_without_loop(self):
        handle = Mock()
        handle.bulkRead.side_effect = usb1.USBErrorPipe()
        with self.assertRaises(usb1.USBErrorPipe):
            UsbBulk(handle)(0x82, 16384)
        self.assertEqual(handle.bulkRead.call_count, 2)
        handle.clearHalt.assert_called_once()

    def test_repeated_stall_is_rate_limited(self):
        handle = Mock()
        handle.bulkRead.side_effect = [usb1.USBErrorPipe(), b'ok'] * 3 + [usb1.USBErrorPipe()]
        bulk = UsbBulk(handle, clock=lambda: 100)
        bulk(0x82, 100)
        bulk(0x82, 100)
        bulk(0x82, 100)
        with self.assertRaises(usb1.USBErrorPipe):
            bulk(0x82, 100)
        self.assertEqual(handle.clearHalt.call_count, 3)

    def test_out_command_never_replayed(self):
        handle = Mock()
        handle.bulkWrite.side_effect = usb1.USBErrorPipe()
        with self.assertRaises(usb1.USBErrorPipe):
            UsbBulk(handle)(1, b'command')
        handle.bulkWrite.assert_called_once()
        handle.clearHalt.assert_not_called()

    def test_timeout_remains_recoverable_and_device_loss_propagates(self):
        handle = Mock()
        handle.bulkRead.side_effect = [usb1.USBErrorTimeout(), usb1.USBErrorNoDevice()]
        bulk = UsbBulk(handle)
        with self.assertRaises(TimeoutError):
            bulk(0x82, 100)
        with self.assertRaises(usb1.USBErrorNoDevice):
            bulk(0x82, 100)
        handle.clearHalt.assert_not_called()
