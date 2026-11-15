"""Single-frame density groups and estimated return envelopes, not object recognition."""
from dataclasses import dataclass
from itertools import product
import numpy as np


def convex_outline(points):
    """2D monotone-chain hull. Degenerate line/point data stays degenerate."""
    pts = sorted(set(map(tuple, np.asarray(points, dtype=float))))
    if len(pts) <= 2:
        return np.asarray(pts, dtype=float).reshape(-1, 2)
    def cross(a, b, c):
        return (b[0]-a[0])*(c[1]-a[1]) - (b[1]-a[1])*(c[0]-a[0])
    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return np.asarray(lower[:-1] + upper[:-1])


@dataclass
class ReturnGroup:
    points: np.ndarray  # display coordinates: right, forward, relative height

    @property
    def low(self): return self.points.min(axis=0)

    @property
    def high(self): return self.points.max(axis=0)

    @property
    def distance(self): return float(np.linalg.norm(self.points, axis=1).min())

    def outline(self, axes=(0, 1)):
        return convex_outline(self.points[:, axes])

    def envelope(self):
        """Extruded XY envelope; its faces are explicitly a range estimate."""
        hull = self.outline()
        lower = np.column_stack((hull, np.full(len(hull), self.low[2])))
        upper = np.column_stack((hull, np.full(len(hull), self.high[2])))
        edges = []
        faces = []
        if len(hull) > 1:
            for a, b in zip(range(len(hull)), np.roll(np.arange(len(hull)), -1)):
                edges.extend([(lower[a], lower[b]), (upper[a], upper[b]), (lower[a], upper[a])])
                if len(hull) > 2:
                    faces.append([lower[a], lower[b], upper[b], upper[a]])
        if len(hull) > 2:
            faces.extend([lower, upper])
        return faces, edges


def estimate_groups(points, radius=.65, min_neighbors=4, min_points=5, limit=6):
    """DBSCAN-like density grouping on unique 6 cm cells.

    Sparse noise cannot extend a group through a chain of non-core points.
    No protocol IDs are treated as target tracking IDs. No temporal fusion.
    """
    if not .15 <= radius <= 2:
        raise ValueError('Invalid grouping radius')
    p = np.asarray(points, dtype=float).reshape(-1, 3)
    p = p[np.isfinite(p).all(axis=1)]
    if len(p) < min_points:
        return []
    _, keep = np.unique(np.floor(p/.06).astype(np.int64), axis=0, return_index=True)
    p = p[np.sort(keep)]
    if len(p) > 2048:
        p = p[np.linspace(0, len(p)-1, 2048, dtype=int)]
    cells = np.floor(p/radius).astype(np.int64)
    grid = {}
    for i, cell in enumerate(cells):
        grid.setdefault(tuple(cell), []).append(i)
    shifts = tuple(product((-1,0,1), repeat=3))
    neighbors = []
    for i, cell in enumerate(cells):
        candidates = [j for delta in shifts for j in grid.get(tuple(cell+delta), ())]
        candidates = np.asarray(candidates, dtype=int)
        dist2 = np.sum((p[candidates]-p[i])**2, axis=1)
        neighbors.append(candidates[dist2 <= radius**2])
    core = np.array([len(n) >= min_neighbors for n in neighbors])
    labels = np.full(len(p), -1, dtype=int)
    group_id = 0
    groups = []
    for i in range(len(p)):
        if labels[i] != -1 or not core[i]:
            continue
        labels[i] = group_id
        pending = [i]
        while pending:
            index = pending.pop()
            if not core[index]:
                continue
            for j in neighbors[index]:
                if labels[j] == -1:
                    labels[j] = group_id
                    pending.append(j)
        members = p[labels == group_id]
        if len(members) >= min_points and np.ptp(members, axis=0).max() >= .12:
            groups.append(ReturnGroup(members))
        group_id += 1
    return sorted(groups, key=lambda group: group.distance)[:limit]
