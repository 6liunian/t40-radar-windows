"""Regression checks without opening CAN or touching the physical radar."""
import socket
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'radar_client'))
from radar_control_panel import F9EchoGuard, PanelRadarClient, Telemetry
from radar_min_client import ClientConfig, build_v1_frame, parse_v1_frame


class PanelReconnectTests(unittest.TestCase):
    def test_running_motor_rejects_speed_changes_and_duplicate_start(self):
        import queue
        client = PanelRadarClient.__new__(PanelRadarClient)
        client.telemetry = Telemetry(motor_running=True, target_rpm=900)
        client.config = ClientConfig()
        client.commands = queue.Queue()
        client._send_can_speed = Mock()
        client.send_v1 = Mock()
        client.commands.put(('speed', 1200))
        client.commands.put(('start', 1200))
        client._process_commands()
        self.assertEqual(client.telemetry.target_rpm, 900)
        client._send_can_speed.assert_not_called()
        client.send_v1.assert_not_called()
        client.commands.put(('stop', None))
        client.commands.put(('speed', 1200))
        client._process_commands()
        self.assertFalse(client.telemetry.motor_running)
        self.assertEqual(client.telemetry.target_rpm, 1200)
        client._send_can_speed.assert_called_once_with(0)

    def test_f9_first_reply_allowed_reflection_blocked(self):
        client = PanelRadarClient.__new__(PanelRadarClient)
        client.config = ClientConfig()
        client.can_device = Mock()
        client.telemetry = Telemetry()
        client.f9_echo_guard = F9EchoGuard()
        client._log_can_raw = Mock()
        client._log_can_duml = Mock()
        raw = bytes.fromhex('550e0466780ab347001ef900791c')
        client._forward_motor_frame(parse_v1_frame(raw), raw, 0xF9)
        self.assertEqual(client.can_device.send_can.call_count, 2)
        # The real ESC reply is returned once over UDP, then the radar
        # reflects the same bytes. None of those reflections may re-enter CAN.
        client.f9_echo_guard.remember(raw, time.monotonic())
        for _ in range(1000):
            client._forward_motor_frame(parse_v1_frame(raw), raw, 0xF9)
        self.assertEqual(client.can_device.send_can.call_count, 2)
        self.assertEqual(client.telemetry.echo_loops_blocked, 1000)
        new = build_v1_frame(msg_id=0x1EF9, payload=b'\0', seq=18356,
                             sender=0x78, receiver=0x0A, flags=0)
        client._forward_motor_frame(parse_v1_frame(new), new, 0xF9)
        self.assertEqual(client.can_device.send_can.call_count, 4)
        ack = build_v1_frame(msg_id=0x1E83, payload=b'\0\1', seq=18357,
                             sender=0x18, receiver=0x78, flags=0x80)
        client._forward_motor_frame(parse_v1_frame(ack), ack, 0x83)
        self.assertEqual(client.can_device.send_can.call_count, 6)
        self.assertFalse(client.f9_echo_guard.is_reflection(raw, time.monotonic() + 61))

    def test_worker_survives_closed_reopened_udp_peer(self):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as old:
            old.bind(('127.0.0.1', 0))
            peer = old.getsockname()
        client = PanelRadarClient(ClientConfig(local_ip='127.0.0.1', radar_ip='127.0.0.1',
                                  control_local_port=0, control_remote_port=peer[1],
                                  v2_local_port=0), Telemetry())
        worker = threading.Thread(target=client.run_panel)
        worker.start()
        try:
            time.sleep(.3)
            self.assertTrue(worker.is_alive())
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as new:
                new.bind(peer)
                new.settimeout(1)
                data, sender = new.recvfrom(65535)
                self.assertTrue(data)
                self.assertEqual(sender, client.control_sock.getsockname())
                new.sendto(b'ignored malformed packet', sender)
            time.sleep(.2)
            self.assertTrue(worker.is_alive())
        finally:
            client.request('quit')
            worker.join(2)
            self.assertFalse(worker.is_alive())

    def test_expired_frames_report_zero_fps(self):
        telemetry = Telemetry()
        telemetry.frame_times.extend([time.monotonic() - 10, time.monotonic() - 9])
        self.assertEqual(telemetry.snapshot()['fps'], 0)


if __name__ == '__main__':
    unittest.main()
