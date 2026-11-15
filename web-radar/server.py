"""Read-only T40 sector bridge for the local browser view.

The desktop application remains responsible for hardware setup and motor
control. This companion only checks its panel status, reads the existing full
sector snapshot over the project's SSH path, and exposes compact JSON locally.
"""
from __future__ import annotations

import argparse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import os
from pathlib import Path
import struct
import sys
import threading
import time
from urllib.parse import urlparse


HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
sys.path.insert(0, str(PROJECT / "radar_client"))

from sector_cloud import (  # noqa: E402
    DEGREES_PER_ENCODER,
    SECTORS,
    SIZE,
    STRIDE,
    SectorReceiver,
)


PANEL_PATH = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "T40Radar" / "runtime" / "panel.json"


def decode_sector_xyz(raw: bytes) -> tuple[list[list[float | int]], dict]:
    """Decode full-sector records into body-relative XYZ.

    The elevation field matches the project's reverse-engineered side-array
    transform: reinterpret record+4 after flipping its sign bit, then project
    slant range with sin/cos. Invalid elevation encodings remain visible on the
    horizontal plane but are tagged so ground calibration never uses them.
    """
    if len(raw) != SIZE:
        raise ValueError("扇区快照长度错误")
    points: list[list[float | int]] = []
    invalid_distance = 0
    invalid_elevation = 0
    sectors_with_returns = 0
    for index in range(SECTORS):
        sector = raw[index * STRIDE:(index + 1) * STRIDE]
        active, count = sector[:2]
        if active not in (0, 1) or count > 125:
            raise ValueError("扇区布局与此固件不匹配")
        if not active or not count:
            continue
        sectors_with_returns += 1
        encoder = struct.unpack_from("<H", sector, 5)[0] & 1023
        bearing = math.radians((180 - encoder * DEGREES_PER_ENCODER) % 360)
        cos_az = math.cos(bearing)
        sin_az = math.sin(bearing)
        for slot in range(count):
            offset = 15 + slot * 20
            distance = struct.unpack_from("<f", sector, offset)[0]
            if not math.isfinite(distance) or distance <= 0 or distance > 120:
                invalid_distance += 1
                continue
            elevation_bits = struct.unpack_from("<I", sector, offset + 4)[0] ^ 0x80000000
            elevation = struct.unpack("<f", struct.pack("<I", elevation_bits))[0]
            elevation_valid = math.isfinite(elevation) and abs(elevation) <= math.pi / 2
            if not elevation_valid:
                invalid_elevation += 1
                elevation = 0.0
            strength = struct.unpack_from("<H", sector, offset + 16)[0]
            horizontal = math.cos(elevation) * distance
            points.append([
                round(horizontal * cos_az, 3),
                round(horizontal * sin_az, 3),
                round(math.sin(elevation) * distance, 3),
                int(strength),
                int(index),
                1 if elevation_valid else 0,
            ])
    return points, {
        "points": len(points),
        "sectors_with_returns": sectors_with_returns,
        "invalid_distance": invalid_distance,
        "invalid_elevation": invalid_elevation,
        "elevation_valid": len(points) - invalid_elevation,
    }


class _TelemetryStub:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.sector_status = ""


class LiveCloud:
    def __init__(self, host: str = "192.168.8.2", local: str = "192.168.8.1") -> None:
        self.host = host
        self.local = local
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.reader = SectorReceiver(_TelemetryStub(), host, local)
        self.thread = threading.Thread(target=self._run, name="web-sector-reader", daemon=True)
        self.payload = {
            "state": "waiting",
            "message": "等待 T40 雷达控制台",
            "points": [],
            "point_count": 0,
            "updated": 0.0,
            "rpm": 0,
            "radar_height_m": None,
            "read_seconds": 0.0,
        }

    def start(self) -> None:
        self.thread.start()

    def close(self) -> None:
        self.stop.set()
        try:
            self.reader.close()
        except Exception:
            pass
        self.thread.join(timeout=2)

    def snapshot(self) -> dict:
        with self.lock:
            return dict(self.payload)

    def _publish(self, **values) -> None:
        with self.lock:
            self.payload.update(values)

    @staticmethod
    def _panel_state() -> dict:
        try:
            state = json.loads(PANEL_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if time.time() - float(state.get("updated", 0)) > 3:
            return {}
        return state

    def _wait(self, seconds: float, message: str, rpm: int = 0) -> bool:
        self._publish(state="waiting", message=message, rpm=rpm, point_count=0, points=[])
        return self.stop.wait(seconds)

    def _run(self) -> None:
        connection = None
        try:
            while not self.stop.is_set():
                panel = self._panel_state()
                if not panel:
                    if self._wait(0.5, "等待 T40 雷达控制台"): break
                    continue
                rpm = int(panel.get("actual_rpm") or 0)
                if rpm < 150:
                    if connection:
                        connection.close(); connection = None
                    if self._wait(0.35, "等待雷达开始旋转", rpm): break
                    continue
                if panel.get("error"):
                    if connection:
                        connection.close(); connection = None
                    if self._wait(0.5, "雷达控制台报告异常：" + str(panel["error"]), rpm): break
                    continue
                try:
                    if connection is None:
                        self._publish(state="connecting", message="正在连接只读点云通道", rpm=rpm)
                        connection, pid = self.reader.connect()
                    started = time.monotonic()
                    raw = self.reader.read_snapshot(connection, pid)
                    compact, stats = decode_sector_xyz(raw)
                    elapsed = time.monotonic() - started
                    radar_height = panel.get("height_m")
                    radar_height = float(radar_height) if isinstance(radar_height, (int, float)) and math.isfinite(radar_height) else None
                    shared_reader = panel.get("cloud_source") == "sectors"
                    self._publish(
                        state="live",
                        message="实时三维扇区回波（与原软件共享只读）" if shared_reader else "实时三维扇区回波",
                        points=compact,
                        point_count=len(compact),
                        updated=time.time(),
                        rpm=rpm,
                        radar_height_m=radar_height,
                        read_seconds=round(elapsed, 3),
                        sectors_with_returns=int(stats.get("sectors_with_returns", 0)),
                        invalid=int(stats.get("invalid_distance", 0)),
                        invalid_elevation=int(stats.get("invalid_elevation", 0)),
                        elevation_valid=int(stats.get("elevation_valid", 0)),
                    )
                    cadence = 1.5 if shared_reader else 1.0
                    if self.stop.wait(max(0.1, cadence - elapsed)): break
                except Exception as exc:
                    if connection:
                        try: connection.close()
                        except Exception: pass
                        connection = None
                    self._publish(state="error", message="点云读取待恢复：" + str(exc), rpm=rpm, points=[], point_count=0)
                    if self.stop.wait(4): break
        finally:
            if connection:
                try: connection.close()
                except Exception: pass


class Handler(SimpleHTTPRequestHandler):
    cloud: LiveCloud

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(HERE), **kwargs)

    def do_GET(self):
        if urlparse(self.path).path == "/api/points":
            body = json.dumps(self.cloud.snapshot(), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def log_message(self, fmt, *args):
        if self.path != "/api/points":
            super().log_message(fmt, *args)


def main() -> None:
    parser = argparse.ArgumentParser(description="T40 read-only browser point cloud")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8768)
    args = parser.parse_args()
    cloud = LiveCloud()
    Handler.cloud = cloud
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    cloud.start()
    print(f"http://{args.host}:{args.port}/", flush=True)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        cloud.close()


if __name__ == "__main__":
    main()
