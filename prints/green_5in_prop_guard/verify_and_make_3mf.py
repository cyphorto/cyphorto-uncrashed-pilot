"""Verify the exported STL and pack it as a 3MF for Bambu Studio.

Run with any Python 3 (uses only the standard library + numpy if present):
    python verify_and_make_3mf.py
Checks: bounding box, triangle count, watertight (every edge shared by
exactly 2 triangles), signed volume, and build-plate fit.
Writes green_5in_prop_guard.3mf next to the STL.
"""

import os
import struct
import zipfile
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
STL = os.path.join(HERE, "green_5in_prop_guard.stl")
TMF = os.path.join(HERE, "green_5in_prop_guard.3mf")


def read_binary_stl(path):
    with open(path, "rb") as fh:
        data = fh.read()
    (count,) = struct.unpack_from("<I", data, 80)
    tris = []
    off = 84
    for _ in range(count):
        vals = struct.unpack_from("<12fH", data, off)
        tris.append((vals[3:6], vals[6:9], vals[9:12]))
        off += 50
    return tris


def main():
    tris = read_binary_stl(STL)
    pts = [p for tri in tris for p in tri]
    xs, ys, zs = zip(*pts)
    size = (max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs))

    edges = Counter()
    volume = 0.0
    for a, b, c in tris:
        for e in ((a, b), (b, c), (c, a)):
            edges[tuple(sorted(e))] += 1
        volume += (
            a[0] * (b[1] * c[2] - b[2] * c[1])
            - a[1] * (b[0] * c[2] - b[2] * c[0])
            + a[2] * (b[0] * c[1] - b[1] * c[0])
        ) / 6.0

    watertight = all(v == 2 for v in edges.values())
    print(f"triangles: {len(tris)}")
    print(f"size_mm: X={size[0]:.1f} Y={size[1]:.1f} Z={size[2]:.1f}")
    print(f"min_z: {min(zs):.2f} (must be 0.00, flat on the plate)")
    print(f"watertight_manifold: {watertight}")
    print(f"volume_cm3: {abs(volume) / 1000.0:.1f} (~{abs(volume) / 1000.0 * 1.24:.0f} g PLA at 100% infill)")
    print(f"fits_A1_mini_180x180: {size[0] <= 180 and size[1] <= 180}")
    print(f"fits_A1_256x256: {size[0] <= 256 and size[1] <= 256}")
    assert watertight and abs(min(zs)) < 0.01 and size[0] <= 180, "CHECK FAILED"

    # --- pack a minimal, valid 3MF (unit = millimetre) -------------------
    verts, index = {}, []
    tri_idx = []
    for tri in tris:
        ids = []
        for p in tri:
            key = tuple(round(float(v), 4) for v in p)
            if key not in verts:
                verts[key] = len(verts)
            ids.append(verts[key])
        tri_idx.append(ids)
    vlist = sorted(verts, key=lambda k: verts[k])
    v_xml = "".join(f'<vertex x="{x}" y="{y}" z="{z}"/>' for x, y, z in vlist)
    t_xml = "".join(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in tri_idx)
    model = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<model unit="millimeter" xml:lang="en-US" '
        'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">'
        '<resources><object id="1" type="model"><mesh>'
        f"<vertices>{v_xml}</vertices><triangles>{t_xml}</triangles>"
        '</mesh></object></resources>'
        '<build><item objectid="1"/></build></model>'
    )
    with zipfile.ZipFile(TMF, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>'
            "</Types>",
        )
        z.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Target="/3D/3dmodel.model" Id="rel0" '
            'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>',
        )
        z.writestr("3D/3dmodel.model", model)
    print(f"wrote: {TMF} ({os.path.getsize(TMF)} bytes)")


if __name__ == "__main__":
    main()
