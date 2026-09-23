"""Offline compact contact hull construction; requires NumPy and SciPy.

The directed Hausdorff bound is computed for EVERY vertex of all four original
hulls, not just sampled orientations. Distance to a convex set is convex, so the
largest vertex distance bounds the complete original convex hull and therefore
its support-function error in any orientation. Runtime builds only read JSON.
"""
import argparse, hashlib, json
from pathlib import Path
import numpy as np
from scipy.spatial import ConvexHull


def distances(points, compact):
    # Distance to each triangle's plane when projection lies in the triangle,
    # otherwise to its edges. Works for points inside/outside the closed hull.
    hull = ConvexHull(compact)
    result = np.full(len(points), np.inf)
    inside = np.max(points @ hull.equations[:, :3].T + hull.equations[:, 3], axis=1) <= 1e-9
    for face in hull.simplices:
        a, b, c = compact[face]; u, v = b-a, c-a; w = points-a
        uu, uv, vv = u@u, u@v, v@v; wu, wv = w@u, w@v
        den = uu*vv-uv*uv
        s, t = (wu*vv-wv*uv)/den, (wv*uu-wu*uv)/den
        projected = w-s[:, None]*u-t[:, None]*v
        plane = np.sum(projected*projected, axis=1)
        result = np.minimum(result, np.where((s >= 0) & (t >= 0) & (s+t <= 1), plane, np.inf))
        for start, end in ((a,b),(b,c),(c,a)):
            edge = end-start; along = np.clip((points-start)@edge/(edge@edge), 0, 1)
            delta = points-start-along[:,None]*edge
            result = np.minimum(result, np.sum(delta*delta, axis=1))
    result[inside] = 0
    return np.sqrt(result)


def generate(root):
    geometry = root/'geometry.json'; contacts = root/'motions/locomotion/contact-hulls.json'
    cfg = json.loads(geometry.read_text()); full = json.loads(contacts.read_text())
    profiles, certificates = {}, {}
    for kind in ('walk','crawl'):
        points = np.unique(np.concatenate([np.asarray(cfg['legs'][leg]['sole_hull_local_mm'] if kind == 'walk' else full['soles'][leg]) for leg in cfg['leg_order']]), axis=0)
        chosen = list(ConvexHull(points).vertices[::max(1, len(ConvexHull(points).vertices)//12)])
        while True:
            error = distances(points, points[chosen]); worst = int(error.argmax())
            if error[worst] <= .15: break
            chosen.append(worst)
        profiles[kind] = points[chosen].tolist()
        # Float storage introduces < 0.00002 mm at this robot's scale.
        certificates[kind] = dict(original_vertices=len(points), compact_vertices=len(chosen), directed_hausdorff_mm=float(error.max()))
        assert len(chosen) <= 128, certificates[kind]
    return dict(schema='ainekio.compact-sole.v1', geometry_sha256=hashlib.sha256(geometry.read_bytes()).hexdigest(), contact_source_sha256=hashlib.sha256(contacts.read_bytes()).hexdigest(), support_allowance_mm=.151, maximum_support_error_mm=.15, certificates=certificates, profiles=profiles)


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1]);parser.add_argument('--out',type=Path)
    args=parser.parse_args();result=generate(args.root)
    (args.out or args.root/'motions/locomotion/sole-profile.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result['certificates'],indent=2))
