import queue
import unittest
from ath6kl_win.udp_bridge import UdpBridge

class ReplyQueueTests(unittest.TestCase):
    def bridge(self):
        bridge = UdpBridge.__new__(UdpBridge)
        bridge.reply_queue = queue.Queue(maxsize=1)
        bridge.dropped = bridge.replies_sent = 0
        bridge.sockets = {}
        bridge.endpoint = 2
        bridge.next_arp = float('inf')
        return bridge

    def test_receive_enqueues_without_usb_call(self):
        bridge = self.bridge()
        sent = []
        bridge.bulk = lambda *args: sent.append(args)
        self.assertTrue(bridge.enqueue_reply(bytes(42)))
        self.assertEqual(sent, [])
        bridge.poll()
        self.assertEqual(len(sent), 1)
        self.assertEqual(bridge.replies_sent, 1)

    def test_full_queue_does_not_block_receiver(self):
        bridge = self.bridge()
        self.assertTrue(bridge.enqueue_reply(bytes(42)))
        self.assertFalse(bridge.enqueue_reply(bytes(42)))
        self.assertEqual(bridge.dropped, 1)
