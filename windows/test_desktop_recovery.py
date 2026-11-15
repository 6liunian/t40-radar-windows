import json
import queue
import struct
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'desktop'))
import app
from radar_control_panel import Telemetry, PanelRadarClient
from radar_min_client import build_v1_frame, ClientConfig


class RecoveryTests(unittest.TestCase):
    def launcher(self):
        obj = app.Launcher.__new__(app.Launcher)
        obj.cancelled = threading.Event()
        obj.panel = Mock()
        obj.panel.telemetry = Telemetry(last_can_at=time.monotonic(), last_rpm_at=time.monotonic(), actual_rpm=0)
        obj.recovery_attempts = 1
        obj.stop_child = Mock()
        obj.check = Mock(return_value={'ok': True, 'guid': 'test'})
        return obj

    def test_recovered_transport_requires_fresh_radar_and_keeps_motor_stopped(self):
        obj = self.launcher()
        obj.cancelled.wait = Mock(return_value=False)
        calls = 0
        def state():
            nonlocal calls
            calls += 1
            if calls == 3:
                obj.panel.telemetry.last_udp_at = obj.backend_started + .01
            return {'state': 'running', 'udp_rx': calls}
        obj.backend_state = state
        with tempfile.TemporaryDirectory() as tmp, patch.object(app, 'RUNTIME', Path(tmp)), \
             patch.object(app.subprocess, 'run'), patch.object(app.subprocess, 'Popen') as spawn:
            spawn.return_value.poll.return_value = None
            obj.recover_backend()
        self.assertEqual(calls, 3)
        self.assertEqual(obj.panel.telemetry.transport_error, '')
        obj.panel.client.request.assert_called_once_with('stop')
        self.assertFalse(obj.panel.telemetry.motor_running)

    def test_cancel_does_not_reset_device(self):
        obj = self.launcher()
        obj.cancelled.set()
        with patch.object(app.subprocess, 'run') as reset:
            obj.recover_backend()
        reset.assert_not_called()
        obj.stop_child.assert_not_called()

    def test_stale_zero_rpm_cannot_authorize_reset(self):
        obj = self.launcher()
        obj.panel.telemetry.last_rpm_at = 1
        obj.cancelled.wait = Mock(return_value=False)
        with patch.object(app.time, 'monotonic', side_effect=[100, 100, 113]), \
             patch.object(app.subprocess, 'run') as reset:
            obj.recover_backend()
        reset.assert_not_called()
        self.assertIn('0 RPM', obj.panel.telemetry.transport_error)

    def test_failed_reset_is_bounded_and_visible(self):
        obj = self.launcher()
        obj.cancelled.wait = Mock(return_value=False)
        with patch.object(app.subprocess, 'run', side_effect=RuntimeError('test USB failure')):
            obj.recover_backend()
        self.assertEqual(obj.recovery_attempts, 2)
        self.assertIn('test USB failure', obj.panel.telemetry.transport_error)

    def test_old_pid_or_old_status_is_not_success(self):
        obj = self.launcher()
        obj.child = Mock(pid=123)
        with tempfile.TemporaryDirectory() as tmp, patch.object(app, 'RUNTIME', Path(tmp)):
            path = Path(tmp) / 'status.json'
            path.write_text(json.dumps({'pid': 122, 'updated': time.time()}))
            self.assertEqual(obj.backend_state(), {})
            path.write_text(json.dumps({'pid': 123, 'updated': time.time()-30}))
            self.assertEqual(obj.backend_state(), {})

    def test_start_queued_during_recovery_cannot_spin_motor(self):
        client = PanelRadarClient.__new__(PanelRadarClient)
        client.telemetry = Telemetry(transport_error='recovering')
        client.commands = queue.Queue()
        client.commands.put(('start', 900))
        client.send_v1 = Mock()
        client._send_can_speed = Mock()
        client._process_commands()
        client.send_v1.assert_not_called()
        client._send_can_speed.assert_not_called()
        self.assertFalse(client.telemetry.motor_running)

    def test_can_rpm_updates_when_wireless_send_fails(self):
        client = PanelRadarClient.__new__(PanelRadarClient)
        client.telemetry = Telemetry(actual_rpm=900)
        client.config = ClientConfig()
        client.can_device = Mock()
        client.can_device.recv.side_effect = [(0xA3, 1, b'X', 0, 0, False), BlockingIOError()]
        payload = bytearray(44)
        struct.pack_into('<H', payload, 29, 0)
        frame = build_v1_frame(msg_id=0x1E0F, payload=payload, seq=1, sender=0x0A, receiver=0x78, flags=0)
        client.can_parser = Mock()
        client.can_parser.feed.return_value = [frame]
        client._log_can_raw = client._log_can_duml = Mock()
        client.control_sock = Mock()
        client.control_sock.sendto.side_effect = OSError(10065, 'host unreachable')
        client._handle_can_readable()
        self.assertEqual(client.telemetry.actual_rpm, 0)
        self.assertGreater(client.telemetry.last_rpm_at, 0)
        self.assertEqual(client.telemetry.error, '')
