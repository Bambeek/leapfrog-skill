#!/usr/bin/env python3
"""Layout diff between screenshots that ignores colour. Standard library only.

    layout_diff.py one original.png clone.png [--out diff.png] [--json]
    layout_diff.py batch leapfrog/screens leapfrog/clone-screens --json leapfrog/diffs/layout.json
    layout_diff.py batch A B --since HEAD~3 --map leapfrog/screen-map.json   # changed screens only
    layout_diff.py one a.png b.png --mode pixel                              # exact, for your own regressions

Layout mode scales both images to the same width, turns them into edge maps
and compares a grid of cells: edge density and edge position with 1px
tolerance. Only cells with something in them count. A new palette does not
lower the score; moved, missing or extra blocks do. Score 90+ matches, 75+
close, 50+ partly, under 50 different. Regions are given in the original's
pixels, biggest first.

PNG only (8 or 16 bit, any colour type, not interlaced). Take screenshots at
device scale 1 to keep it fast.
"""

import argparse
import fnmatch
import json
import os
import struct
import subprocess
import sys
import zlib

WIDTH = 480      # compare at this width
CELL = 12        # grid cell size at that width
EDGE = 24        # gradient threshold, 0-510
ACTIVE = 0.02    # cell edge density that counts as "something there"


# ---------- PNG ----------

def read_png(path):
    with open(path, "rb") as f:
        data = f.read()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("%s: not a PNG" % path)
    pos, idat, palette = 8, [], None
    w = h = depth = ctype = interlace = None
    while pos < len(data):
        length, kind = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + length]
        pos += 12 + length
        if kind == b"IHDR":
            w, h, depth, ctype, _, _, interlace = struct.unpack(">IIBBBBB", body)
        elif kind == b"PLTE":
            palette = [tuple(body[i:i + 3]) for i in range(0, len(body), 3)]
        elif kind == b"IDAT":
            idat.append(body)
        elif kind == b"IEND":
            break
    if interlace:
        raise ValueError("%s: interlaced PNG not supported, re-save without interlacing" % path)
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[ctype]
    bits = channels * depth
    stride = (w * bits + 7) // 8
    bpp = max(1, bits // 8)
    raw = zlib.decompress(b"".join(idat))
    rows, prev, i = [], bytearray(stride), 0
    for _ in range(h):
        ft = raw[i]
        cur = bytearray(raw[i + 1:i + 1 + stride])
        i += 1 + stride
        if ft == 1:
            for x in range(bpp, stride):
                cur[x] = (cur[x] + cur[x - bpp]) & 255
        elif ft == 2:
            for x in range(stride):
                cur[x] = (cur[x] + prev[x]) & 255
        elif ft == 3:
            for x in range(stride):
                left = cur[x - bpp] if x >= bpp else 0
                cur[x] = (cur[x] + ((left + prev[x]) >> 1)) & 255
        elif ft == 4:
            for x in range(stride):
                a = cur[x - bpp] if x >= bpp else 0
                b = prev[x]
                c = prev[x - bpp] if x >= bpp else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                cur[x] = (cur[x] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        rows.append(cur)
        prev = cur
    return {"w": w, "h": h, "rows": rows, "depth": depth, "ctype": ctype, "channels": channels, "palette": palette}


def gray_at(img, x, y):
    row, d, ch = img["rows"][y], img["depth"], img["channels"]
    if d < 8:
        per = 8 // d
        v = (row[x // per] >> (8 - d * (x % per + 1))) & ((1 << d) - 1)
        if img["ctype"] == 3:
            r, g, b = img["palette"][v]
            return (r * 299 + g * 587 + b * 114) // 1000
        return v * 255 // ((1 << d) - 1)
    step = d // 8
    o = x * ch * step
    if img["ctype"] == 3:
        r, g, b = img["palette"][row[o]]
        return (r * 299 + g * 587 + b * 114) // 1000
    if ch >= 3:
        return (row[o] * 299 + row[o + step] * 587 + row[o + 2 * step] * 114) // 1000
    return row[o]


def shrink(img, width=WIDTH):
    """Grey image scaled to `width` by averaging a 2x2 sample per target pixel."""
    w, h = img["w"], img["h"]
    width = min(width, w)
    s = w / float(width)
    height = max(1, int(round(h / s)))
    out = []
    for ty in range(height):
        y0 = min(h - 1, int(ty * s))
        y1 = min(h - 1, int(ty * s + s / 2))
        line = []
        for tx in range(width):
            x0 = min(w - 1, int(tx * s))
            x1 = min(w - 1, int(tx * s + s / 2))
            line.append((gray_at(img, x0, y0) + gray_at(img, x1, y0) + gray_at(img, x0, y1) + gray_at(img, x1, y1)) >> 2)
        out.append(line)
    return out, s


def write_png(path, rgb_rows):
    h, w = len(rgb_rows), len(rgb_rows[0]) // 3
    raw = b"".join(b"\x00" + bytes(r) for r in rgb_rows)

    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)

    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


# ---------- compare ----------

def edges(g):
    h, w = len(g), len(g[0])
    e = [[0] * w for _ in range(h)]
    for y in range(h - 1):
        r, rn = g[y], g[y + 1]
        er = e[y]
        for x in range(w - 1):
            if abs(r[x + 1] - r[x]) + abs(rn[x] - r[x]) > EDGE:
                er[x] = 1
    return e


def dilate(e):
    h, w = len(e), len(e[0])
    d = [[0] * w for _ in range(h)]
    for y in range(h):
        for x in range(w):
            if e[y][x]:
                for yy in (y - 1, y, y + 1):
                    if 0 <= yy < h:
                        row = d[yy]
                        for xx in (x - 1, x, x + 1):
                            if 0 <= xx < w:
                                row[xx] = 1
    return d


def cell_sims(ea, eb):
    h = min(len(ea), len(eb))
    w = min(len(ea[0]), len(eb[0]))
    da, db = dilate(ea), dilate(eb)
    rows, cols = (h + CELL - 1) // CELL, (w + CELL - 1) // CELL
    grid = [[None] * cols for _ in range(rows)]
    for cy in range(rows):
        for cx in range(cols):
            na = nb = hit_a = hit_b = n = 0
            for y in range(cy * CELL, min(h, (cy + 1) * CELL)):
                ra, rb, rda, rdb = ea[y], eb[y], da[y], db[y]
                for x in range(cx * CELL, min(w, (cx + 1) * CELL)):
                    n += 1
                    if ra[x]:
                        na += 1
                        hit_a += rdb[x]
                    if rb[x]:
                        nb += 1
                        hit_b += rda[x]
            dens_a, dens_b = na / float(n), nb / float(n)
            if max(dens_a, dens_b) < ACTIVE:
                continue
            dens = 1 - abs(dens_a - dens_b) / max(dens_a, dens_b)
            p = hit_a / float(na) if na else 0.0
            r = hit_b / float(nb) if nb else 0.0
            f1 = 2 * p * r / (p + r) if p + r else 0.0
            grid[cy][cx] = 0.5 * dens + 0.5 * f1
    return grid


def regions(grid, scale, threshold=0.5):
    rows, cols = len(grid), len(grid[0]) if grid else 0
    seen, out = set(), []
    for y in range(rows):
        for x in range(cols):
            v = grid[y][x]
            if v is None or v >= threshold or (y, x) in seen:
                continue
            stack, cells = [(y, x)], []
            seen.add((y, x))
            while stack:
                cy, cx = stack.pop()
                cells.append((cy, cx))
                for ny, nx in ((cy + 1, cx), (cy - 1, cx), (cy, cx + 1), (cy, cx - 1)):
                    if 0 <= ny < rows and 0 <= nx < cols and (ny, nx) not in seen:
                        nv = grid[ny][nx]
                        if nv is not None and nv < threshold:
                            seen.add((ny, nx))
                            stack.append((ny, nx))
            ys, xs = [c[0] for c in cells], [c[1] for c in cells]
            box = [int(min(xs) * CELL * scale), int(min(ys) * CELL * scale),
                   int((max(xs) + 1) * CELL * scale), int((max(ys) + 1) * CELL * scale)]
            out.append({"box": box, "cells": len(cells)})
    out.sort(key=lambda r: -r["cells"])
    return out[:8]


def label(score):
    return "matches" if score >= 90 else "close" if score >= 75 else "partly" if score >= 50 else "different"


def compare_layout(a_path, b_path, out_png=None):
    a, b = read_png(a_path), read_png(b_path)
    ga, sa = shrink(a)
    gb, _ = shrink(b, len(ga[0]))
    ea, eb = edges(ga), edges(gb)
    grid = cell_sims(ea, eb)
    vals = [v for row in grid for v in row if v is not None]
    hr = min(len(ga), len(gb)) / float(max(len(ga), len(gb)))
    score = 100.0 * sum(vals) / len(vals) if vals else 100.0
    if hr < 0.85:
        score *= 0.5 + 0.5 * hr
    res = {"original": a_path, "clone": b_path, "score": round(score, 1), "label": label(score),
           "cells": len(vals), "height_ratio": round(hr, 2), "regions": regions(grid, sa)}
    if out_png:
        rgb = []
        for y, row in enumerate(ga):
            line = bytearray()
            for x, v in enumerate(row):
                cy, cx = y // CELL, x // CELL
                s = grid[cy][cx] if cy < len(grid) and cx < len(grid[0]) else None
                if s is not None and s < 0.5:
                    line += bytes((255, v // 3, v // 3))
                else:
                    line += bytes((v, v, v))
            rgb.append(line)
        write_png(out_png, rgb)
    return res


def compare_pixel(a_path, b_path):
    a, b = read_png(a_path), read_png(b_path)
    if (a["w"], a["h"]) != (b["w"], b["h"]):
        return {"original": a_path, "clone": b_path, "score": 0.0, "label": "different",
                "note": "sizes differ: %dx%d vs %dx%d" % (a["w"], a["h"], b["w"], b["h"])}
    diff = 0
    for y in range(a["h"]):
        for x in range(a["w"]):
            if abs(gray_at(a, x, y) - gray_at(b, x, y)) > 8:
                diff += 1
    score = 100.0 * (1 - diff / float(a["w"] * a["h"]))
    return {"original": a_path, "clone": b_path, "score": round(score, 2), "label": label(score), "changed_pixels": diff}


# ---------- batch ----------

def changed_screens(since, map_path, repo="."):
    with open(map_path, encoding="utf-8") as f:
        mapping = json.load(f)
    files = subprocess.run(["git", "diff", "--name-only", since], cwd=repo, capture_output=True,
                           text=True, check=True).stdout.split()
    return {s for s, globs in mapping.items() if any(fnmatch.fnmatch(p, g) for p in files for g in globs)}


def batch(dir_a, dir_b, only=None, mode="layout", diff_dir=None):
    names = sorted(n for n in os.listdir(dir_a) if n.lower().endswith(".png"))
    results, missing = [], []
    for n in names:
        sid = os.path.splitext(n)[0]
        if only is not None and sid not in only:
            continue
        b = os.path.join(dir_b, n)
        if not os.path.exists(b):
            missing.append(sid)
            continue
        a = os.path.join(dir_a, n)
        if mode == "pixel":
            r = compare_pixel(a, b)
        else:
            out = None
            if diff_dir:
                os.makedirs(diff_dir, exist_ok=True)
                out = os.path.join(diff_dir, sid + ".diff.png")
            r = compare_layout(a, b, out)
            if out and r["score"] >= 75 and os.path.exists(out):
                os.remove(out)  # keep diff images only for screens worth opening
        r["screen"] = sid
        results.append(r)
    return results, missing


def fmt(r):
    reg = r.get("regions") or []
    where = "  worst %s" % reg[0]["box"] if reg else ""
    extra = "  height x%.2f" % r["height_ratio"] if r.get("height_ratio", 1) < 0.85 else ""
    return "%-10s %5.1f %-9s%s%s%s" % (r.get("screen", os.path.basename(r["clone"])), r["score"], r["label"],
                                       extra, where, ("  " + r["note"]) if r.get("note") else "")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Layout diff that ignores colour")
    sub = ap.add_subparsers(dest="cmd", required=True)
    o = sub.add_parser("one")
    o.add_argument("original")
    o.add_argument("clone")
    o.add_argument("--out", help="diff image (red = differs)")
    o.add_argument("--mode", choices=["layout", "pixel"], default="layout")
    o.add_argument("--json", action="store_true")
    b = sub.add_parser("batch")
    b.add_argument("originals")
    b.add_argument("clones")
    b.add_argument("--json", metavar="FILE", help="write results here (merged when --since or --only is used)")
    b.add_argument("--diffs", metavar="DIR", help="write diff images for screens under 75")
    b.add_argument("--mode", choices=["layout", "pixel"], default="layout")
    b.add_argument("--only", help="comma-separated screen ids")
    b.add_argument("--since", help="git ref: only screens whose mapped files changed")
    b.add_argument("--map", help="screen-map.json for --since")
    b.add_argument("--repo", default=".")
    args = ap.parse_args(argv)

    if args.cmd == "one":
        r = compare_pixel(args.original, args.clone) if args.mode == "pixel" else compare_layout(args.original, args.clone, args.out)
        print(json.dumps(r, indent=1) if args.json else fmt(r))
        return 0

    only = set(args.only.split(",")) if args.only else None
    if args.since:
        if not args.map:
            ap.error("--since needs --map")
        changed = changed_screens(args.since, args.map, args.repo)
        only = changed if only is None else only & changed
        print("changed since %s: %s" % (args.since, ", ".join(sorted(only)) or "none"))
    results, missing = batch(args.originals, args.clones, only, args.mode, args.diffs)
    for r in results:
        print(fmt(r))
    if results:
        print("avg %.1f over %d screens" % (sum(r["score"] for r in results) / len(results), len(results)))
    if missing:
        print("no clone screenshot: " + ", ".join(missing))
    if args.json:
        merged = {}
        if only is not None and os.path.exists(args.json):
            with open(args.json, encoding="utf-8") as f:
                merged = {s["screen"]: s for s in json.load(f).get("screens", [])}
        merged.update({r["screen"]: r for r in results})
        os.makedirs(os.path.dirname(os.path.abspath(args.json)), exist_ok=True)
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump({"screens": [merged[k] for k in sorted(merged)]}, f, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
