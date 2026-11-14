#!/usr/bin/env python3
"""
Stream a model's coloured point cloud (cloud.xyz) out of its MatterPak zip with HTTP range requests,
without downloading the mesh and textures. Keeps every Nth point.

    python3 pointcloud.py --model <sid> [--stride 4]    -> data/<sid>/cloud.npy  (float32 x y z r g b)

Coordinates are metres, Z up, in the same frame as the panoramas and floor plans.
"""
import argparse
import struct
import zlib

import numpy as np
import requests

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "shared"))  # shared/common.py
from common import DATA, mp

Q = """query($id: ID!) { model(id: $id) {
  bundle(id: "mp:matterpak") { availability assets { ... on Resource { status filename url } } } } }"""


def ranged(url, start, end):
    r = requests.get(url, headers={"Range": f"bytes={start}-{end}"}, timeout=120)
    r.raise_for_status()
    return r.content


def find_entry(url, name="cloud.xyz"):
    size = int(requests.get(url, headers={"Range": "bytes=0-0"}, timeout=60).headers["Content-Range"].split("/")[1])
    tail = ranged(url, max(0, size - 65536), size - 1)
    eocd = tail.rfind(b"PK\x05\x06")
    cd_size, cd_off = struct.unpack("<II", tail[eocd + 12:eocd + 20])
    cd = ranged(url, cd_off, cd_off + cd_size - 1)
    i, entries = 0, []
    while i < len(cd) and cd[i:i + 4] == b"PK\x01\x02":
        method, = struct.unpack("<H", cd[i + 10:i + 12])
        csize, usize, nlen, xlen, clen = struct.unpack("<IIHHH", cd[i + 20:i + 34])
        off, = struct.unpack("<I", cd[i + 42:i + 46])
        fname = cd[i + 46:i + 46 + nlen].decode()
        entries.append((fname, method, csize, usize, off))
        i += 46 + nlen + xlen + clen
    hit = next((e for e in entries if e[0].endswith(name)), None)
    return size, entries, hit


def stream_cloud(url, entry, stride):
    fname, method, csize, usize, off = entry
    head = ranged(url, off, off + 29)
    nlen, xlen = struct.unpack("<HH", head[26:30])
    start = off + 30 + nlen + xlen
    r = requests.get(url, headers={"Range": f"bytes={start}-{start + csize - 1}"}, stream=True, timeout=600)
    r.raise_for_status()
    dec = zlib.decompressobj(-15) if method == 8 else None
    rest, keep, n = b"", [], 0
    for chunk in r.iter_content(1 << 20):
        data = rest + (dec.decompress(chunk) if dec else chunk)
        lines = data.split(b"\n")
        rest = lines.pop()
        sel = lines[(-n) % stride::stride]
        n += len(lines)
        if sel:
            keep.append(np.loadtxt(sel, dtype=np.float32, usecols=range(6), ndmin=2))
    return np.concatenate(keep)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", required=True)
    ap.add_argument("--stride", type=int, default=4)
    a = ap.parse_args()
    b = mp(Q, id=a.model)["model"]["bundle"]
    url = b["assets"][0]["url"]
    size, entries, hit = find_entry(url)
    print(f"MatterPak {size / 1e6:.0f} MB; cloud.xyz {hit[3] / 1e6:.0f} MB ({hit[2] / 1e6:.0f} MB compressed)")
    pts = stream_cloud(url, hit, a.stride)
    out = DATA / a.model / "cloud.npy"
    np.save(out, pts)
    print(f"kept {len(pts):,} points (every {a.stride}th) -> {out}; extent {np.ptp(pts[:, :3], 0).round(1)} m")


if __name__ == "__main__":
    main()
