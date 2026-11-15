"""Local occupied cells preserve disconnected regions and holes, unlike a hull."""
import numpy as np


def occupied_cells(points, resolution=.25, max_cells=8000):
    p = np.asarray(points, dtype=float).reshape(-1, 3)
    p = p[np.isfinite(p).all(axis=1)]
    if not len(p):
        return np.empty((0, 3), dtype=np.int64), float(resolution)
    # Only contour resolution adapts. Raw points are never sampled or dropped.
    step = max(float(resolution), .01)
    for _ in range(64):
        scaled = np.floor(p/step)
        if np.max(np.abs(scaled)) > 1e15:
            step *= max(2, np.max(np.abs(scaled))/1e15)
            continue
        cells = np.unique(scaled.astype(np.int64), axis=0)
        if len(cells) <= max_cells:
            return cells, step
        step *= 1.5
    raise ValueError('Contour coordinate range too large')


def exposed_faces(cells, step):
    """Draw only externally exposed voxel faces; no spanning between gaps."""
    occupied = set(map(tuple, cells))
    faces = []
    shifts = ((1,0,0),(-1,0,0),(0,1,0),(0,-1,0),(0,0,1),(0,0,-1))
    corners = (((1,0,0),(1,1,0),(1,1,1),(1,0,1)),
               ((0,0,0),(0,0,1),(0,1,1),(0,1,0)),
               ((0,1,0),(0,1,1),(1,1,1),(1,1,0)),
               ((0,0,0),(1,0,0),(1,0,1),(0,0,1)),
               ((0,0,1),(1,0,1),(1,1,1),(0,1,1)),
               ((0,0,0),(0,1,0),(1,1,0),(1,0,0)))
    for cell in occupied:
        for shift, vertices in zip(shifts, corners):
            if tuple(cell[i]+shift[i] for i in range(3)) not in occupied:
                faces.append((np.asarray(vertices)+cell)*step)
    return faces


def projected_boundary(cells, step, axes=(0,1)):
    occupied = set(map(tuple, cells[:, axes]))
    edges = []
    for x, y in occupied:
        for neighbor, a, b in (((x-1,y),(x,y),(x,y+1)), ((x+1,y),(x+1,y),(x+1,y+1)),
                               ((x,y-1),(x,y),(x+1,y)), ((x,y+1),(x,y+1),(x+1,y+1))):
            if neighbor not in occupied:
                edges.append(np.asarray((a,b))*step)
    return edges
