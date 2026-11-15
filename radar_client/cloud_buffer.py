"""Receive every decoded point independently of drawing frequency."""
from collections import deque
import math

LAYERS = ('ground', 'wire', 'pcla')


class PointHistory:
    def __init__(self, max_points=250_000, max_seconds=10):
        self.frames = deque()
        self.max_points = max_points
        self.max_seconds = max_seconds
        self.retained = 0
        self.received = self.invalid = self.evicted = 0
        self.latest = {name: [] for name in LAYERS}
        self.updated = {}
        self.sequence = 0

    def append(self, name, points, now):
        self.received += len(points)
        valid = [p for p in points if all(math.isfinite(float(v)) for v in p[:3])]
        self.invalid += len(points)-len(valid)
        self.latest[name] = valid
        self.updated[name] = now
        self.sequence += 1
        # A telemetry gap invalidates previous temporal integration.
        if self.frames and now-self.frames[-1][0] > 2.5:
            self.frames.clear()
            self.retained = 0
        if valid:
            self.frames.append((now, name, valid))
            self.retained += len(valid)
        self.prune(now)
        while self.retained > self.max_points and self.frames:
            stamp, layer, pts = self.frames.popleft()
            excess = min(len(pts), self.retained-self.max_points)
            self.retained -= excess
            self.evicted += excess
            if excess < len(pts):
                self.frames.appendleft((stamp, layer, pts[excess:]))

    def prune(self, now):
        while self.frames and self.frames[0][0] < now-self.max_seconds:
            self.retained -= len(self.frames.popleft()[2])

    def collect(self, now, seconds):
        self.prune(now)
        if not seconds:
            return {k: list(v) for k, v in self.latest.items()}
        result = {k: [] for k in LAYERS}
        for stamp, name, points in self.frames:
            if stamp >= now-min(seconds, self.max_seconds):
                result[name].extend(points)
        return result

    def clear(self):
        self.frames.clear()
        self.retained = 0

