"""G-NetTrack walk-test logs -> clean, campus-frame RSRP epochs (#5 -> #6 v1).

Target format: G-NetTrack Pro / Lite measurement logs (tab-delimited .txt in
G-NetTrack_Logs/; comma/semicolon exports are accepted too). Column semantics
per the G-NetTrack Pro manual:

  Operator    MCC+MNC (e.g. 45005 = SKT)        Node       eNodeB ID on 4G
  CellID      serving cell id (LTE: sector)      RAWCELLID  raw (full) cell id
  NetworkTech 2G / 3G / 4G (5G on newer builds)  Level      RxLev / RSCP / RSRP (dBm)
  PSC         PSC on 3G, PCI on 4G                Location   G = GPS, N = network
  Accuracy    location accuracy (m)               NCell1..6  neighbour PCI on 4G
  NRxLev1..6  neighbour level (dBm)               NTech/NARFCN/NCellid  (if present)

Every row is screened, and every rejection is counted by reason (the evidence
report prints the table), so nothing is dropped silently:

  * technology: only LTE (4G) and NR (5G) rows; 3G RSCP / 2G RxLev never enter
    an RSRP fit. NSA rows are the LTE anchor.
  * position: Location must be G (GPS) when the column exists; Accuracy <=
    max_accuracy_m; finite, non-zero, within 20 km of campus.
  * level: finite and inside the RAT's reported range. LTE -44 is retained;
    the joint (-44, -3, -113) RSRP/RSRQ/RSSI tuple is flagged for contextual
    review, not treated as a proven post-handover placeholder.
  * cell identity: LTE cells are keyed on (RAT, MCC, MNC, ECI) with ECI =
    eNB*256 + sector (Node + CellID), or RAWCELLID when that is the full ECI -
    never on CellID alone (CellID is the local sector id, repeated across eNBs).

Required headers missing -> LogFormatError (a ValueError) that lists what was
found and what each field accepts. Stdlib only.
"""

import csv
import io
import json
import math
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

SITES_FILE = Path(__file__).resolve().parents[2] / "data" / "opencellid" / "kumoh-cells.json"

RSRP_RANGE = (-140.0, -43.0)        # Android CellSignalStrengthLte.getRsrp
RAT_RANGES = {"LTE": RSRP_RANGE, "NR": (-156.0, -31.0)}
MAX_ACCURACY_M = 20.0
MAX_CAMPUS_DIST_M = 20_000.0
N_NEIGHBOURS = 18

# Normalised header (lower-case, no spaces/underscores/dashes/brackets) -> field.
ALIASES = {
    "time": ("timestamp", "time", "datetime", "date"),
    "lat": ("latitude", "lat"),
    "lon": ("longitude", "lon", "lng", "long"),
    "level": ("level", "rsrp", "rsrpdbm", "signal"),
    "operator": ("operator", "plmn", "mccmnc"),
    "mcc": ("mcc",),
    "mnc": ("mnc",),
    "node": ("node", "enb", "enodeb", "enbid", "gnb", "gnbid"),
    "cellid": ("cellid", "ci", "cell"),
    "rawcellid": ("rawcellid", "eci", "nci"),
    "tech": ("networktech", "tech", "rat"),
    "mode": ("networkmode", "mode"),
    "pci": ("psc", "pci"),
    "earfcn": ("arfcn", "earfcn", "nrarfcn"),
    "accuracy": ("accuracy", "gpsaccuracy"),
    "location": ("location", "locationsource", "fix"),
    "nr_rsrp": ("ssrsrp", "nrssrsrp", "nrrsrp", "5grsrp", "nrlevel", "csirsrp"),
    "rsrq": ("qual", "rsrq"),
    "rssi": ("lterssi", "rssi"),
    "speed": ("speed",),
    "new_age": ("updatenewf",),
    "old_age": ("updateoldf",),
    "band": ("band",),
}
REQUIRED = ("lat", "lon", "level")
NEIGHBOUR_FIELDS = {          # per-index neighbour columns, e.g. NRxLev3
    "n_level": ("nrxlev",),
    "n_pci": ("ncell",),
    "n_cellid": ("ncellid",),
    "n_tech": ("ntech",),
    "n_earfcn": ("narfcn",),
}
INVALID_TOKENS = {"", "-", "--", "nan", "null", "none", "n/a", "na", "inf", "-inf", "+inf"}


class LogFormatError(ValueError):
    pass


def _norm(h):
    return re.sub(r"[\s_\-()./\[\]]", "", (h or "").strip().lower())


def local_xy(lat, lon, centre):
    """Same projection as data/opencellid/build_sites.py (campus centre = 0,0)."""
    x = (lon - centre["lon"]) * 111_320.0 * math.cos(math.radians(centre["lat"]))
    y = (lat - centre["lat"]) * 110_574.0
    return x, y


def load_sites(path=SITES_FILE):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _num(v):
    """finite float, or None for G-NetTrack's empty / '-' / NaN cells."""
    if v is None:
        return None
    s = str(v).strip()
    if s.lower() in INVALID_TOKENS:
        return None
    try:
        f = float(s)
    except ValueError:
        return None
    return f if math.isfinite(f) else None


def _int(v):
    f = _num(v)
    return int(f) if f is not None and f == int(f) else None


def _time(v, fallback, utc_offset_hours=9):
    """G-NetTrack wall time (KIT defaults to KST), retaining fractions.

    Numeric epochs and explicit ISO offsets are preserved. Missing/unparseable
    values retain legacy fallback behavior and are flagged by the parser.
    """
    s = (v or "").strip()
    zone = timezone(timedelta(hours=utc_offset_hours))
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return (d if d.tzinfo else d.replace(tzinfo=zone)).timestamp()
    except ValueError:
        pass
    for fmt in ("%Y.%m.%d_%H.%M.%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S",
                "%Y.%m.%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%d.%m.%Y %H:%M:%S"):
        for suffix in (".%f", ""):
            try:
                return datetime.strptime(s, fmt + suffix).replace(tzinfo=zone).timestamp()
            except ValueError:
                pass
    f = _num(s)
    return f if f is not None else (float(fallback) if fallback is not None else None)


def classify_rat(tech, mode):
    """-> 'LTE' | 'NR' | None (2G/3G/unknown). NetworkTech decides when it is
    set; NetworkMode only breaks ties. NSA (EN-DC) reports the LTE anchor as the
    serving cell, and Android often labels NSA as 'NR' in the mode field, so
    tech=4G always means LTE."""
    def rat_of(s):
        s = s.upper()
        if "NSA" in s or "ENDC" in s or "EN-DC" in s:
            return "LTE"
        if "4G" in s or "LTE" in s:
            return "LTE"
        if "5G" in s or re.search(r"\bNR\b|\bSA\b|^NR", s):
            return "NR"
        if re.search(r"2G|3G|GSM|EDGE|GPRS|UMTS|WCDMA|HSPA|HSDPA|HSUPA|CDMA|EVDO|TD-?SCDMA", s):
            return "LEGACY"
        return None
    t, m = rat_of(tech or ""), rat_of(mode or "")
    if t == "NR" and m == "LTE":          # 5G tech + NSA mode -> anchor
        t = "LTE"
    r = t or m
    return None if r == "LEGACY" else r


def split_operator(op):
    """'45005' / '450 05' / '450-05' -> (450, 5); unknown -> (None, None)."""
    digits = re.sub(r"\D", "", op or "")
    if len(digits) in (5, 6):
        return int(digits[:3]), int(digits[3:])
    return None, None


def lte_eci(node, cellid, raw):
    """Full 28-bit ECI from G-NetTrack's Node (eNB) + CellID (sector), or the
    raw id. -> (eci, enb, sector) or (None, None, None)."""
    if node is not None and cellid is not None and 0 <= cellid < 256 and node > 0:
        return node * 256 + cellid, node, cellid
    for full in (raw, cellid):
        if full is not None and full >= 256:
            return full, full >> 8, full & 0xFF
    return None, None, None


def _header_map(fieldnames, path):
    norm = {}
    for raw in fieldnames or []:
        norm.setdefault(_norm(raw), raw)
    cols = {}
    for field, aliases in ALIASES.items():
        for a in aliases:
            if a in norm:
                cols[field] = norm[a]
                break
    neigh = {}
    for field, prefixes in NEIGHBOUR_FIELDS.items():
        for i in range(1, N_NEIGHBOURS + 1):
            for p in prefixes:
                if f"{p}{i}" in norm:
                    neigh.setdefault(i, {})[field] = norm[f"{p}{i}"]
    has_id = bool({"node", "cellid", "rawcellid"} & set(cols))
    missing = [f for f in REQUIRED if f not in cols] + ([] if has_id else ["cell identity"])
    if missing:
        raise LogFormatError(
            f"{path}: not a recognised G-NetTrack log - missing {missing}.\n"
            f"  headers found: {list(fieldnames or [])}\n"
            "  accepted names (case/space-insensitive): " + "; ".join(
                f"{f}={'/'.join(ALIASES[f])}" for f in (*REQUIRED, "node", "cellid", "rawcellid")) +
            "\n  Export the measurement log (text) from G-NetTrack Pro - see data/walktest/README.md"
            "\n  (G-NetTrack Lite logs carry no cell identity: Timestamp/position/Level only)")
    known = set(cols.values()) | {c for d in neigh.values() for c in d.values()}
    unused = [f for f in (fieldnames or []) if f not in known]
    return cols, neigh, unused


def _sniff_delimiter(head):
    counts = {d: head.count(d) for d in ("\t", ";", ",")}
    return max(counts, key=counts.get)


def parse_gnettrack(path, centre, max_accuracy_m=MAX_ACCURACY_M, rats=("LTE", "NR"),
                   *, text=None, utc_offset_hours=9):
    """-> (epochs, report). One epoch per accepted log row:

    {log, row, t, lat, lon, x, y, acc, rat, mcc, mnc, cell, enb, sector, eci,
     pci, earfcn, rsrp, nr_rsrp, neighbours: [{pci, earfcn, cellid, rsrp}]}

    `cell` = (rat, mcc, mnc, eci-or-nci). report = {rows, accepted, rejected:
    {reason: n}, columns, neighbour stats, which optional columns existed}.
    """
    path = Path(path)
    rejected = Counter()
    out = []
    n_neigh = n_neigh_bad = 0
    flags_count = Counter()
    row_widths = Counter()
    with (io.StringIO(text.lstrip("\ufeff")) if text is not None else
          open(path, newline="", encoding="utf-8-sig", errors="replace")) as fh:
        head = fh.readline()
        fh.seek(0)
        reader = csv.DictReader(fh, delimiter=_sniff_delimiter(head))
        cols, neigh_cols, unused = _header_map(reader.fieldnames, path)

        def get(row, f):
            return row.get(cols[f]) if f in cols else None

        has_tech = "tech" in cols or "mode" in cols
        n_rows = 0
        for i, row in enumerate(reader):
            n_rows += 1
            row_widths[len(reader.fieldnames) + len(row.get(None) or [])
                       - sum(v is None for k, v in row.items() if k is not None)] += 1
            rat = classify_rat(get(row, "tech"), get(row, "mode")) if has_tech else "LTE"
            if rat is None:
                rejected[f"tech not LTE/NR ({(get(row, 'tech') or '?').strip() or '?'})"] += 1
                continue
            if rat not in rats:
                rejected[f"RAT {rat} excluded"] += 1
                continue
            if "location" in cols and (get(row, "location") or "").strip().upper()[:1] != "G":
                rejected["network (non-GPS) location fix"] += 1
                continue
            acc = _num(get(row, "accuracy"))
            if "accuracy" in cols and (acc is None or acc > max_accuracy_m):
                rejected[f"GPS accuracy missing or > {max_accuracy_m:g} m"] += 1
                continue
            lat, lon = _num(get(row, "lat")), _num(get(row, "lon"))
            if lat is None or lon is None or (lat == 0.0 and lon == 0.0):
                rejected["no position"] += 1
                continue
            x, y = local_xy(lat, lon, centre)
            if math.hypot(x, y) > MAX_CAMPUS_DIST_M:
                rejected["position > 20 km from campus"] += 1
                continue
            level = _num(get(row, "level"))
            if level is None:
                rejected["level missing / NaN"] += 1
                continue
            limits = RAT_RANGES[rat]
            if not limits[0] <= level <= limits[1]:
                rejected[f"level outside {limits} dBm (e.g. -201 no coverage)"] += 1
                continue
            mcc, mnc = split_operator(get(row, "operator"))
            if mcc is None and "mcc" in cols:
                mcc, mnc = _int(get(row, "mcc")), _int(get(row, "mnc"))
            node, cellid, raw = _int(get(row, "node")), _int(get(row, "cellid")), _int(get(row, "rawcellid"))
            if rat == "LTE":
                eci, enb, sector = lte_eci(node, cellid, raw)
            else:
                eci = raw if raw is not None else (cellid if cellid is not None and cellid >= 256 else None)
                enb, sector = node, None
            if eci is None:
                rejected["no usable cell identity (Node+CellID / RAWCELLID)"] += 1
                continue
            neighbours = []
            neighbour_reports = []
            for idx in sorted(neigh_cols):
                nc = neigh_cols[idx]
                nl = _num(row.get(nc.get("n_level")))
                npci = _int(row.get(nc.get("n_pci")))
                if nl is None and npci is None:
                    continue
                n_neigh += 1
                ntech = (row.get(nc["n_tech"]) or "").strip() if "n_tech" in nc else ""
                nrat = classify_rat(ntech, "") if ntech else rat
                # Retain unresolved/legacy reports for audit, but never pool
                # 3G RSCP into an LTE/NR RSRP fit.
                nr = {"slot": idx, "rat": nrat, "reported_technology": ntech,
                      "pci": npci, "rsrp": nl,
                      "earfcn": _int(row.get(nc.get("n_earfcn"))),
                      "cellid": _int(row.get(nc.get("n_cellid")))}
                neighbour_reports.append(nr)
                if (nl is None or nrat != rat or not limits[0] <= nl <= limits[1] or npci is None
                        or not 0 <= npci <= (503 if rat == "LTE" else 1007)):
                    n_neigh_bad += 1
                    continue
                neighbours.append(dict(nr))
            nr_rsrp = _num(get(row, "nr_rsrp"))
            if nr_rsrp is not None and not RAT_RANGES["NR"][0] <= nr_rsrp <= RAT_RANGES["NR"][1]:
                nr_rsrp = None
            flags = []
            if (level, _num(get(row, "rsrq")), _num(get(row, "rssi"))) == (-44, -3, -113):
                flags.append("joint_signal_tuple_review")
            if mcc is None or mnc is None:
                flags.append("operator_unknown")
            t = _time(get(row, "time"), None, utc_offset_hours)
            if t is None:
                flags.append("timestamp_fallback")
                t = float(i)
            flags_count.update(flags)
            out.append({
                "log": path.name, "row": i, "t": t,
                "timestamp": get(row, "time"),
                "lat": lat, "lon": lon, "x": x, "y": y, "acc": acc, "rat": rat,
                "mcc": mcc, "mnc": mnc, "cell": (rat, mcc, mnc, eci),
                "enb": enb, "sector": sector, "eci": eci, "pci": _int(get(row, "pci")),
                "earfcn": _int(get(row, "earfcn")), "rsrp": level, "nr_rsrp": nr_rsrp,
                "rsrq": _num(get(row, "rsrq")), "rssi": _num(get(row, "rssi")),
                "speed_kmh": _num(get(row, "speed")), "band": get(row, "band"),
                "new_age_s": _num(get(row, "new_age")), "old_age_s": _num(get(row, "old_age")),
                "flags": flags, "neighbours": neighbours, "neighbour_reports": neighbour_reports,
            })
    report = {
        "log": path.name, "rows": n_rows, "accepted": len(out), "rejected": dict(rejected),
        "columns": cols, "neighbour_slots": len(neigh_cols), "unused_columns": len(unused),
        "neighbours_seen": n_neigh, "neighbours_rejected": n_neigh_bad,
        "has_accuracy": "accuracy" in cols, "has_location_source": "location" in cols,
        "has_operator": "operator" in cols or "mcc" in cols, "has_tech": has_tech,
        "flags": dict(flags_count), "row_widths": dict(row_widths),
        "utc_offset_hours": utc_offset_hours,
    }
    return out, report


def clean_track(epochs, max_speed_mps=12.0):
    """Per log: sort by time, drop duplicate timestamps and GPS jumps (implied
    speed > max_speed_mps from the last kept fix; walking is ~1.4 m/s).
    -> (kept, n_duplicates, n_jumps)."""
    by_log = {}
    for e in epochs:
        by_log.setdefault(e["log"], []).append(e)
    kept, dupes, jumps = [], 0, 0
    for log in sorted(by_log):
        last = None
        for e in sorted(by_log[log], key=lambda e: (e["t"], e["row"])):
            if last is not None:
                dt = e["t"] - last["t"]
                if dt <= 0:
                    dupes += 1
                    continue
                if math.hypot(e["x"] - last["x"], e["y"] - last["y"]) / dt > max_speed_mps:
                    jumps += 1
                    continue
            kept.append(e)
            last = e
    return kept, dupes, jumps


PRIVATE_COLUMNS = ("imei", "imsi", "msisdn", "ip", "iccid")
RAW_DIAGNOSTIC_COLUMNS = {"signalstring", "oldfunctions", "newfunctions", "cellinfo"}


def _private_column(header):
    h = _norm(header)
    return (any(h == p or re.fullmatch(re.escape(p) + r"\d+", h) for p in PRIVATE_COLUMNS)
            or h in RAW_DIAGNOSTIC_COLUMNS or h in {"ipv4", "ipv6", "subscriberid", "deviceid"})


def scrub_identifiers(path):
    """Blank subscriber/device identifiers (IMEI, IMSI, MSISDN, IP) in a log, in
    place, before it is committed. -> number of non-empty values blanked."""
    path = Path(path)
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    lines = text.splitlines()
    if not lines:
        return 0
    delim = _sniff_delimiter(lines[0])
    header = lines[0].split(delim)
    # Unstructured telephony dumps and unlabelled trailing fields are unsafe to
    # publish. The structured importer extracts allowlisted facts before scrub.
    idx = [i for i, h in enumerate(header) if _private_column(h)]
    n = 0
    out = [lines[0]]
    for line in lines[1:]:
        f = line.split(delim)
        for i in idx + list(range(len(header), len(f))):
            if i < len(f) and f[i].strip() not in ("", "-"):
                f[i] = "-"
                n += 1
        out.append(delim.join(f))
    if n:
        path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return n


def private_values(path):
    """How many non-empty IMEI/IMSI/MSISDN/IP values the log carries."""
    with open(path, newline="", encoding="utf-8-sig", errors="replace") as fh:
        head = fh.readline()
        fh.seek(0)
        reader = csv.DictReader(fh, delimiter=_sniff_delimiter(head))
        cols = [c for c in (reader.fieldnames or []) if _private_column(c)]
        return sum(sum((row.get(c) or "").strip() not in ("", "-") for c in cols)
                   + sum(v.strip() not in ("", "-") for v in (row.get(None) or []))
                   for row in reader)
