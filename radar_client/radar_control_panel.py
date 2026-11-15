#!/usr/bin/env python3
"""Compact native Windows control panel for the DJI T40 radar."""

from __future__ import annotations

import queue
import json
import select
import socket
import struct
import threading
import time
import tkinter as tk
import errno
import os
import sys
from collections import deque, OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from tkinter import ttk
from typing import Any

if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

import numpy as np
from matplotlib import rcParams
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
from cloud_view import CloudView
from cloud_buffer import PointHistory
from workspace_ui import WorkspaceLayout
from sector_cloud import SectorReceiver

from radar_min_client import (
    ClientConfig,
    MOTOR_CMD_IDS,
    RadarClient,
    build_flight_ctrl_payload,
    build_v1_frame,
    decode_avoidance_result,
    decode_perception_1e61_entries,
    parse_v1_frame,
    parse_v2_frame,
)


BG = "#0b0e11"
SURFACE = "#12171c"
SURFACE_2 = "#192027"
BORDER = "#2a353f"
TEXT = "#e8eef0"
MUTED = "#8d9aa4"
ACCENT = "#21c7a8"
ACCENT_DARK = "#126c5d"
WARNING = "#e39a45"
DANGER = "#d85c5c"

rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial Unicode MS", "DejaVu Sans"]
rcParams["axes.unicode_minus"] = False


def temporary_udp_error(exc):
    codes = {errno.EAGAIN, errno.EWOULDBLOCK, errno.ENOBUFS, errno.ENETDOWN,
             errno.ENETUNREACH, errno.EHOSTUNREACH, errno.ECONNRESET, errno.ECONNREFUSED,
             10050, 10051, 10054, 10061, 10065}
    return exc.errno in codes or getattr(exc, 'winerror', None) in codes


@dataclass
class Telemetry:
    lock: threading.RLock = field(default_factory=threading.RLock)
    ground: list[tuple[float, float, float, int, int]] = field(default_factory=list)
    wire: list[tuple[float, float, float, int, int]] = field(default_factory=list)
    pcla: list[tuple[float, float, float, int, int]] = field(default_factory=list)
    frame_times: deque[float] = field(default_factory=lambda: deque(maxlen=60))
    frame_total: int = 0
    can_total: int = 0
    last_udp_at: float = 0.0
    last_can_at: float = 0.0
    last_rpm_at: float = 0.0
    layer_updated: dict[str, float] = field(default_factory=dict)
    history: PointHistory = field(default_factory=PointHistory)
    history_seconds: float = 5.0
    sector_history: PointHistory = field(default_factory=PointHistory)
    sector_at: float = 0.0
    sector_frames: int = 0
    sector_status: str = '尚未连接'
    sector_stats: dict = field(default_factory=dict)
    cloud_source: str = 'perception'
    actual_rpm: int = 0
    target_rpm: int = 900
    motor_running: bool = False
    worker_ready: bool = False
    error: str = ""
    transport_error: str = ""
    echo_loops_blocked: int = 0
    btm_avoid_m: float | None = None
    height_m: float | None = None

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            now = time.monotonic()
            fps = 0.0
            if len(self.frame_times) >= 2 and now - self.frame_times[-1] < 2.5:
                span = self.frame_times[-1] - self.frame_times[0]
                if span > 0:
                    fps = (len(self.frame_times) - 1) / span
            point_layers = self.history.collect(now, self.history_seconds) if self.history.sequence else {
                'ground': list(self.ground), 'wire': list(self.wire), 'pcla': list(self.pcla)}
            snapshot = {
                **point_layers,
                'latest_counts': {name: len(getattr(self, name)) for name in ('ground','wire','pcla')},
                'history_seconds': self.history_seconds,
                'received_points': self.history.received,
                'invalid_points': self.history.invalid,
                'capacity_evicted': self.history.evicted,
                'history_capacity': self.history.max_points,
                "layer_ages": {name: now - stamp for name, stamp in self.layer_updated.items()},
                "fps": fps,
                "frame_total": self.frame_total,
                "can_total": self.can_total,
                "udp_age": now - self.last_udp_at if self.last_udp_at else None,
                "can_age": now - self.last_can_at if self.last_can_at else None,
                "rpm_age": now - self.last_rpm_at if self.last_rpm_at else None,
                "actual_rpm": self.actual_rpm,
                "target_rpm": self.target_rpm,
                "motor_running": self.motor_running,
                "worker_ready": self.worker_ready,
                "error": self.error or self.transport_error,
                "transport_error": self.transport_error,
                "echo_loops_blocked": self.echo_loops_blocked,
                "btm_avoid_m": self.btm_avoid_m,
                "height_m": self.height_m,
            }
            snapshot.update(cloud_source=self.cloud_source,sector_status=self.sector_status,sector_stats=dict(self.sector_stats),
                            perception_age=snapshot['udp_age'],perception_counts=snapshot['latest_counts'])
            if self.cloud_source=='sectors':
                history=self.sector_history
                point_layers=history.collect(now,self.history_seconds)
                age=now-self.sector_at if self.sector_at else None
                if self.actual_rpm<=0 or not self.last_can_at or now-self.last_can_at>=2.5:age=None
                snapshot.update(**point_layers,latest_counts={name:len(pts) for name,pts in history.latest.items()},
                                frame_total=self.sector_frames,udp_age=age,layer_ages={'pcla':age},
                                received_points=history.received,invalid_points=history.invalid,capacity_evicted=history.evicted)
            return snapshot


class F9EchoGuard:
    """Let the ESC's first F9 reply through, suppress its UDP reflection.

    The ESC echoes F9 with unchanged sender/receiver/seq/flags. Forwarding
    that same packet back to CAN after the radar reflects it creates a loop.
    Other command ACKs and new F9 sequence numbers remain unaffected.
    """
    def __init__(self):
        self.returned = OrderedDict()

    def remember(self, raw, now):
        self.returned[raw] = now
        self.returned.move_to_end(raw)
        while len(self.returned) > 2048:
            self.returned.popitem(last=False)

    def is_reflection(self, raw, now):
        while self.returned and next(iter(self.returned.values())) < now - 60:
            self.returned.popitem(last=False)
        return raw in self.returned


class PanelRadarClient(RadarClient):
    """RadarClient with quiet telemetry callbacks and queued motor control."""

    def __init__(self, config: ClientConfig, telemetry: Telemetry) -> None:
        self.telemetry = telemetry
        self.commands: queue.Queue[tuple[str, int | None]] = queue.Queue()
        self.stop_event = threading.Event()
        self.f9_echo_guard = F9EchoGuard()
        super().__init__(config)
        with self.telemetry.lock:
            self.telemetry.worker_ready = True

    @staticmethod
    def clamp_rpm(value: int) -> int:
        return max(0, min(1800, int(value)))

    def request(self, command: str, value: int | None = None) -> None:
        self.commands.put((command, value))

    def send_v1(
        self,
        msg_id: int,
        payload: bytes,
        label: str,
        sender: int | None = None,
        receiver: int | None = None,
        flags: int | None = None,
        seq: int | None = None,
    ) -> None:
        """Send a V1 frame without high-rate console logging."""
        frame = build_v1_frame(
            msg_id=msg_id,
            payload=payload,
            seq=seq if seq is not None else self._next_seq(),
            sender=sender if sender is not None else self.config.sender,
            receiver=receiver if receiver is not None else self.config.receiver,
            flags=flags if flags is not None else self.config.flags,
        )
        try:
            self.control_sock.sendto(
                frame,
                (self.config.radar_ip, self.config.control_remote_port),
            )
        except ConnectionResetError:
            # Windows reports an earlier UDP ICMP port-unreachable here or
            # on recvfrom when the local bridge restarts. Keep CAN alive.
            pass
        except OSError as exc:
            if not temporary_udp_error(exc):
                raise

    def _send_can_speed(self, rpm: int) -> None:
        if self.can_device is None:
            return
        rpm = self.clamp_rpm(rpm)
        frame = build_v1_frame(
            msg_id=0x1E80,
            payload=struct.pack("<H", rpm),
            seq=self._next_seq(),
            sender=0x78,
            receiver=0x18,
            flags=0x00,
        )
        for offset in range(0, len(frame), 8):
            chunk = frame[offset : offset + 8]
            self.can_device.send_can(self.config.can_tx_id, chunk)
            self._log_can_raw(self.config.can_tx_id, chunk)
        self._log_can_duml("UDP_TO_CAN", self.config.can_tx_id, frame)

    def _process_commands(self) -> None:
        while True:
            try:
                command, value = self.commands.get_nowait()
            except queue.Empty:
                return
            if command == "quit":
                self.stop_event.set()
                return
            if command == "speed" and value is not None:
                rpm = self.clamp_rpm(value)
                with self.telemetry.lock:
                    if self.telemetry.motor_running:
                        continue
                    self.telemetry.target_rpm = rpm
            elif command == "start":
                rpm = self.clamp_rpm(value if value is not None else 900)
                with self.telemetry.lock:
                    if self.telemetry.motor_running or self.telemetry.transport_error or self.telemetry.error:
                        continue
                    self.telemetry.target_rpm = rpm
                    self.telemetry.motor_running = True
                self.send_v1(
                    0x1E22,
                    build_flight_ctrl_payload(self.config.motor_start_subid, True),
                    "panel_motor_start",
                )
                self._send_can_speed(rpm)
            elif command == "stop":
                with self.telemetry.lock:
                    self.telemetry.motor_running = False
                self._send_can_speed(0)
                self.send_v1(
                    0x1E22,
                    build_flight_ctrl_payload(self.config.motor_start_subid, False),
                    "panel_motor_stop",
                )

    def _forward_motor_frame(self, frame: Any, raw: bytes, cmd_id: int) -> bool:
        if self.can_device is None:
            return False
        if cmd_id == 0xF9 and self.f9_echo_guard.is_reflection(raw, time.monotonic()):
            with self.telemetry.lock:
                self.telemetry.echo_loops_blocked += 1
            return True
        is_response = (frame.flags & 0x80) != 0
        outgoing = raw
        if cmd_id == 0x80 and not is_response and len(frame.payload) == 2:
            with self.telemetry.lock:
                desired = self.telemetry.target_rpm if self.telemetry.motor_running else 0
            outgoing = build_v1_frame(
                msg_id=frame.msg_id,
                payload=struct.pack("<H", self.clamp_rpm(desired)),
                seq=frame.seq,
                sender=frame.sender,
                receiver=frame.receiver,
                flags=frame.flags,
            )
        for offset in range(0, len(outgoing), 8):
            chunk = outgoing[offset : offset + 8]
            self.can_device.send_can(self.config.can_tx_id, chunk)
            self._log_can_raw(self.config.can_tx_id, chunk)
        self._log_can_duml("UDP_TO_CAN", self.config.can_tx_id, outgoing)
        return True

    def handle_v1_datagram(self, data: bytes, peer: tuple[str, int]) -> None:
        frame = parse_v1_frame(data)
        if frame is None:
            return
        cmd_set = (frame.msg_id >> 8) & 0xFF
        cmd_id = frame.msg_id & 0xFF
        if cmd_set == 0x1E and cmd_id in MOTOR_CMD_IDS:
            try:
                if self._forward_motor_frame(frame, data, cmd_id):
                    return
            except OSError as exc:
                with self.telemetry.lock:
                    self.telemetry.error = f"CAN 发送失败: {exc}"
                return
        if frame.msg_id in (0x1E62, 0x1E32) and len(frame.payload) == 116:
            try:
                status = decode_avoidance_result(frame.payload)
            except ValueError:
                return
            with self.telemetry.lock:
                self.telemetry.btm_avoid_m = status.btm_avoid_m
                self.telemetry.height_m = status.height_kalman_m

    def handle_v2_datagram(self, data: bytes, peer: tuple[str, int]) -> None:
        frame = parse_v2_frame(data)
        if frame is None or frame.msg_id != 0x1E61:
            return
        try:
            subtype, entries = decode_perception_1e61_entries(frame.payload)
        except ValueError:
            return
        if subtype not in (0, 1, 2):
            return
        points = [
            (
                float(item["x_m"]),
                float(item["y_m"]),
                float(item["z_m"]),
                int(item.get("metric", 0)),
                int(item.get("id", 0)),
            )
            for item in entries
        ]
        now = time.monotonic()
        with self.telemetry.lock:
            name = {0: 'ground', 1: 'wire', 2: 'pcla'}[subtype]
            self.telemetry.history.append(name, points, now)
            points = self.telemetry.history.latest[name]
            self.telemetry.layer_updated[{0: 'ground', 1: 'wire', 2: 'pcla'}[subtype]] = now
            if subtype == 0:
                self.telemetry.ground = points
            elif subtype == 1:
                self.telemetry.wire = points
            elif subtype == 2:
                self.telemetry.pcla = points
            self.telemetry.last_udp_at = now
            self.telemetry.frame_times.append(now)
            self.telemetry.frame_total += 1

    def _handle_can_readable(self) -> None:
        while True:
            try:
                can_id, dlc, data, _, _, is_err = self.can_device.recv()
            except BlockingIOError:
                break
            except OSError as exc:
                with self.telemetry.lock:
                    self.telemetry.error = f"CAN 接收失败: {exc}"
                break
            if is_err or not data:
                continue
            chunk = data[:dlc]
            self._log_can_raw(can_id, chunk)
            now = time.monotonic()
            with self.telemetry.lock:
                self.telemetry.last_can_at = now
                self.telemetry.can_total += 1
            for duml_frame in self.can_parser.feed(chunk):
                parsed = parse_v1_frame(duml_frame)
                if parsed is not None and parsed.msg_id == 0x1EF9:
                    self.f9_echo_guard.remember(duml_frame, time.monotonic())
                self._log_can_duml("CAN_TO_UDP", can_id, duml_frame)
                # Actual speed belongs to CAN, even when forwarding to Wi-Fi fails.
                if parsed is not None and parsed.msg_id == 0x1E0F and len(parsed.payload) == 44:
                    actual = struct.unpack_from("<H", parsed.payload, 29)[0]
                    with self.telemetry.lock:
                        # Out-of-range words (e.g. 65531 while stopped) must not
                        # be treated as real rotation or fresh stop confirmation.
                        if actual <= 3600:
                            self.telemetry.actual_rpm = actual
                            self.telemetry.last_rpm_at = now
                try:
                    self.control_sock.sendto(
                        duml_frame,
                        (self.config.radar_ip, self.config.control_remote_port),
                    )
                except ConnectionResetError:
                    continue
                except OSError as exc:
                    if not temporary_udp_error(exc):
                        with self.telemetry.lock:
                            self.telemetry.error = f"UDP 转发失败: {exc}"
                    continue

    def run_panel(self) -> None:
        try:
            while not self.stop_event.is_set():
                self._process_commands()
                now = time.monotonic()
                timeout = 0.05
                for task in self.tasks:
                    if now >= task.next_at:
                        self.send_v1(
                            task.msg_id,
                            task.builder(),
                            task.name,
                            sender=task.sender,
                            receiver=task.receiver,
                            flags=task.flags,
                        )
                        task.next_at = now + task.interval
                    timeout = min(timeout, max(0.0, task.next_at - now))
                read_socks = [self.control_sock, self.v2_sock]
                if self.can_device is not None and self.can_device.sock is not None:
                    read_socks.append(self.can_device.sock)
                readable, _, _ = select.select(read_socks, [], [], timeout)
                for sock_obj in readable:
                    if self.can_device is not None and sock_obj is self.can_device.sock:
                        self._handle_can_readable()
                    else:
                        try:
                            payload, peer = sock_obj.recvfrom(65535)
                        except (ConnectionResetError, BlockingIOError):
                            continue
                        if sock_obj is self.control_sock:
                            self.handle_v1_datagram(payload, peer)
                        else:
                            self.handle_v2_datagram(payload, peer)
                if self.can_device is not None and self.can_device.sock is None:
                    self._handle_can_readable()
        finally:
            with self.telemetry.lock:
                self.telemetry.motor_running = False
                self.telemetry.worker_ready = False
            self.close()


class RadarControlPanel(WorkspaceLayout):
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("DJI T40 雷达控制台")
        self.root.geometry("1380x820")
        self.root.minsize(1080, 680)
        self.root.configure(bg=BG)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

        self.telemetry = Telemetry()
        self.client: PanelRadarClient | None = None
        self.worker: threading.Thread | None = None
        self.closing = False
        self.range_m = 10.0

        self._configure_style()
        self._build_layout()
        self._start_worker()
        self.sector_receiver=None
        if not os.environ.get('RADAR_TEST_WINDOW'):
            self.sector_receiver=SectorReceiver(self.telemetry,os.environ.get('RADAR_REMOTE_IP','192.168.8.2'),
                                                os.environ.get('RADAR_LOCAL_IP','192.168.8.1'))
            self.sector_receiver.start()
            self.source_box.set('避障候选');self._source_changed()
        self.root.after(100, self._refresh)

    def _configure_style(self) -> None:
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("TFrame", background=BG)
        style.configure("Panel.TFrame", background=SURFACE)
        style.configure("TLabel", background=BG, foreground=TEXT, font=("Microsoft YaHei UI", 10))
        style.configure("Muted.TLabel", background=SURFACE, foreground=MUTED, font=("Microsoft YaHei UI", 9))
        style.configure("Value.TLabel", background=SURFACE, foreground=TEXT, font=("Consolas", 17, "bold"))
        style.configure("Header.TLabel", background=BG, foreground=TEXT, font=("Microsoft YaHei UI", 17, "bold"))
        style.configure("Horizontal.TScale", background=SURFACE, troughcolor=SURFACE_2)
        style.configure("TCombobox", fieldbackground=SURFACE_2, foreground=TEXT)
        style.map('TCombobox', fieldbackground=[('readonly', SURFACE_2)], foreground=[('readonly', TEXT)],
                  selectbackground=[('readonly', SURFACE_2)], selectforeground=[('readonly', TEXT)])
        self.root.option_add('*TCombobox*Listbox.background', SURFACE_2)
        self.root.option_add('*TCombobox*Listbox.foreground', TEXT)









    def _start_worker(self) -> None:
        def worker_main() -> None:
            try:
                project = Path(__file__).resolve().parents[1]
                config = ClientConfig(
                    local_ip=os.environ.get("RADAR_LOCAL_IP", "192.168.1.3"),
                    radar_ip=os.environ.get("RADAR_REMOTE_IP", "192.168.1.100"),
                    can_bridge="PCAN_USBBUS1",
                    capture_dir=os.environ.get("RADAR_CAPTURE_DIR", str(project / "captures")),
                    plot=False,
                    send_motor_start=False,
                )
                self.client = PanelRadarClient(config, self.telemetry)
                self.client.run_panel()
            except Exception as exc:
                with self.telemetry.lock:
                    self.telemetry.error = str(exc)
                    self.telemetry.worker_ready = False

        self.worker = threading.Thread(target=worker_main, name="radar-worker", daemon=True)
        self.worker.start()


    def _refresh(self) -> None:
        if self.closing:
            return
        snap = self.telemetry.snapshot()
        telemetry_path = os.environ.get('RADAR_TELEMETRY_PATH')
        if telemetry_path and time.monotonic() - getattr(self, '_last_export', 0) >= 1:
            self._last_export = time.monotonic()
            exported = {k: v for k, v in snap.items() if k not in ('ground', 'wire', 'pcla')}
            exported.update(updated=time.time(), pid=os.getpid(),
                            ground_count=len(snap['ground']), wire_count=len(snap['wire']),
                            pcla_count=len(snap['pcla']), display=self.cloud.last_stats,
                            display_frozen=self.frozen_snapshot is not None)
            try:
                temporary = Path(telemetry_path + '.tmp')
                temporary.write_text(json.dumps(exported), encoding='utf-8')
                temporary.replace(telemetry_path)
            except OSError:
                pass  # Diagnostic output must not interrupt the panel.
        udp_ok = snap["udp_age"] is not None and snap["udp_age"] < 2.5
        self._refresh_cloud(snap)

        self.rpm_value.configure(text=str(snap["actual_rpm"]))
        can_ok = snap["can_age"] is not None and snap["can_age"] < 2.5
        running = snap["motor_running"] or snap["actual_rpm"] > 0
        self.start_button.configure(state="normal" if snap["worker_ready"] and can_ok and not running and not snap['error'] else "disabled")
        self.apply_button.configure(state="disabled" if running else "normal",
                                    text="请停止后调速" if running else "应用转速")
        self.rpm_scale.configure(state="disabled" if running else "normal")
        if snap["error"]:
            self.header_status.configure(text="连接错误", bg="#3a2022", fg="#f2a4a4")
            self.status_text.configure(text=snap["error"], fg=DANGER)
        elif snap["worker_ready"] and udp_ok and can_ok:
            self.header_status.configure(text="雷达在线", bg="#12382f", fg=ACCENT)
            state = "运行中" if snap["motor_running"] else "已停止"
            self.status_text.configure(text=f"{state}  |  UDP 正常  |  CAN 正常", fg=MUTED)
        elif snap["worker_ready"]:
            self.header_status.configure(text="等待雷达数据", bg=SURFACE_2, fg=WARNING)
            self.status_text.configure(text="PCAN 已打开，等待 UDP/CAN 数据", fg=MUTED)
        else:
            self.header_status.configure(text="正在连接", bg=SURFACE_2, fg=MUTED)
        if snap.get('cloud_source')=='sectors' and snap['worker_ready'] and can_ok and not snap['error']:
            self.header_status.configure(text='扇区数据在线' if udp_ok else ('待启动旋转' if not running else '等待扇区更新'),
                                         bg='#12382f' if udp_ok else SURFACE_2,fg=ACCENT if udp_ok else WARNING)
            self.status_text.configure(text=snap['sector_status'],fg=MUTED)

        btm = snap["btm_avoid_m"]
        height = snap["height_m"]
        extra = ""
        if btm is not None:
            extra += f"\n下避障 {btm:.2f} m"
        if height is not None:
            extra += f"  高度 {height:.2f} m"
        self.metrics.configure(
            text=(
                f"数据 {snap['fps']:.1f} 帧/秒  总帧 {snap['frame_total']}\n"
                f"地面 {len(snap['ground'])}  障碍 {len(snap['pcla'])}  线状 {len(snap['wire'])}\n"
                '各类回波分别更新；过期目标隐藏'
                f"{extra}"
            )
        )
        if snap.get('cloud_source')=='sectors':
            raw=snap.get('sector_stats',{})
            self.metrics.configure(text=(snap['sector_status']+f"\n读取耗时 {raw.get('read_seconds',0):.2f} s\n本次有效 {raw.get('points',0)} 点\n编码器 {raw.get('encoder_min',0)}～{raw.get('encoder_max',0)}\n旧 7 点截断会漏 {raw.get('beyond_old_limit',0)} 点\n无效距离 {raw.get('invalid',0)} 点\n避障通道 {snap['fps']:.1f} 帧/秒"))
        self.root.after(100, self._refresh)

    def _rpm_changed(self, _value: str) -> None:
        rpm = int(round(self.rpm_var.get() / 10.0) * 10)
        self.target_value.configure(text=f"{rpm} RPM")

    def set_preset(self, rpm: int) -> None:
        snap = self.telemetry.snapshot()
        if snap["motor_running"] or snap["actual_rpm"] > 0:
            return
        self.rpm_var.set(rpm)
        self._rpm_changed(str(rpm))
        self.apply_speed()

    def apply_speed(self) -> None:
        snap = self.telemetry.snapshot()
        if snap["motor_running"] or snap["actual_rpm"] > 0:
            return
        rpm = int(round(self.rpm_var.get() / 10.0) * 10)
        if self.client is not None:
            self.client.request("speed", rpm)

    def start_motor(self) -> None:
        rpm = int(round(self.rpm_var.get() / 10.0) * 10)
        if self.client is not None:
            self.client.request("start", rpm)

    def stop_motor(self) -> None:
        if self.client is not None:
            self.client.request("stop")



    def close(self) -> None:
        if self.closing:
            return
        self.closing = True
        if self.client is not None:
            self.client.request("stop")
            time.sleep(0.12)
            self.client.request("quit")
        if self.sector_receiver is not None:self.sector_receiver.close()
        if self.worker is not None:
            self.worker.join(timeout=1.5)
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    panel = RadarControlPanel(root)
    try:
        root.mainloop()
    except KeyboardInterrupt:
        panel.close()


if __name__ == "__main__":
    main()
