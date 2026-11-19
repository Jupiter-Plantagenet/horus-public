#!/usr/bin/env python3
"""Re-fetch the raw OpenCellID tiles around Kumoh (#6) -> raw-tile*.json.

getInArea is capped at 4 km^2 per request, so the 4 km x 4 km area around the
campus centre is pulled as 4 tiles of 2 km x 2 km (the same 4 tiles behind the
committed kumoh-cells.json). Raw tiles are NOT committed (.gitignore); the
committed artefacts are kumoh-cells.json (sites, IDs frozen) and
kumoh-cell-ids.json (per-cell identifiers -> site), both built by build_sites.py.

Token: $OPENCELLID, else the `OPENCELLID=...` line of the repo-root `env` file
(git-ignored). The token is never printed or written anywhere.

Usage (from this directory):  python3 fetch_tiles.py && python3 build_sites.py
"""

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
CAMPUS_LAT, CAMPUS_LON = 36.1446, 128.3936
HALF_LAT, HALF_LON = 0.0180, 0.0222          # ~2 km each way
PAGE = 50                                      # getInArea page size
API = "https://opencellid.org/cell/getInArea"


def token():
    tok = os.environ.get("OPENCELLID")
    if tok:
        return tok.strip()
    for root in (HERE.parents[1], Path.cwd()):
        env = root / "env"
        if env.exists():
            for line in env.read_text(encoding="utf-8").splitlines():
                if line.strip().startswith("OPENCELLID"):
                    return line.split("=", 1)[1].strip().strip("'\"")
    sys.exit("no OpenCellID token: set $OPENCELLID or add OPENCELLID=... to the "
             "repo-root env file (git-ignored)")


def tiles():
    """4 quadrant tiles: (name, lat_min, lon_min, lat_max, lon_max)."""
    out = []
    for i, dlat in enumerate((-HALF_LAT, 0.0)):
        for j, dlon in enumerate((-HALF_LON, 0.0)):
            la, lo = CAMPUS_LAT + dlat, CAMPUS_LON + dlon
            out.append((f"raw-tile{i}{j}", la, lo, la + HALF_LAT, lo + HALF_LON))
    return out


def get(tok, bbox, offset):
    q = urllib.parse.urlencode({"key": tok, "BBOX": ",".join(f"{v:.6f}" for v in bbox),
                                "format": "json", "limit": PAGE, "offset": offset})
    # opencellid.org answers 403 to the default urllib User-Agent
    req = urllib.request.Request(f"{API}?{q}", headers={"User-Agent": "Mozilla/5.0 horus-twin"})
    try:
        return json.loads(urllib.request.urlopen(req, timeout=60).read())
    except urllib.error.HTTPError as e:   # never echo the URL (it carries the token)
        sys.exit(f"OpenCellID HTTP {e.code} for bbox {bbox}")


def main():
    tok = token()
    for name, *bbox in tiles():
        cells, offset = [], 0
        while True:
            d = get(tok, bbox, offset)
            page = d.get("cells", [])
            cells += page
            if len(page) < PAGE:
                break
            offset += PAGE
            time.sleep(1.0)
        (HERE / f"{name}.json").write_text(
            json.dumps({"bbox": bbox, "fetched_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        "count": len(cells), "cells": cells}, indent=1) + "\n", encoding="utf-8")
        print(f"{name}: {len(cells)} cells")
        time.sleep(1.0)


if __name__ == "__main__":
    main()
