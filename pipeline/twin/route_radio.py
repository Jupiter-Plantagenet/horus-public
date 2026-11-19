"""Measured, cell/channel-specific RSRP surface with explicit local support.

This adapter deliberately does not pretend observed cells are nine catalogue
sites. Call predict(cell_key, x, y) or measure(x, y); unknown/out-of-support
cells return None or are omitted. Coordinates are metres from campus centre.
No fabricated noise-floor fallback and no target-action remapping are applied.
"""
import json
import math
from collections import defaultdict
from pathlib import Path

import numpy as np


def link_key(epoch):
    return tuple(epoch["cell"]) + (epoch["earfcn"],)


def spatial_points(epochs, bin_m=5):
    """Collapse approximate repeated radio frames, then equalize spatial bins.

    Modem timestamps joined by logger time are only a cache proxy. Aggregate
    them without counting each repeated row as independent spatial evidence.
    """
    frames=defaultdict(list)
    for e in epochs:
        modem=(e.get("source_link") or {}).get("modem_timestamp_ns")
        token=(e["session"],modem) if modem else (e["session"],"unlinked",e["t"],e.get("row"))
        frames[(link_key(e),token)].append(e)
    bins=defaultdict(list)
    for (key,_),group in frames.items():
        x=float(np.median([e["x"] for e in group]));y=float(np.median([e["y"] for e in group]))
        bins[(key,math.floor(x/bin_m),math.floor(y/bin_m))].append([x,y,float(np.median([e["rsrp"] for e in group]))])
    return [dict(key=list(k[0]),x=float(np.median([v[0] for v in values])),
                 y=float(np.median([v[1] for v in values])),rsrp=float(np.median([v[2] for v in values])),
                 acquisition_groups=len(values)) for k,values in sorted(bins.items())]


class RouteRadioMap:
    def __init__(self, model):
        if model.get("format")!="horus-route-radio-v1":
            raise ValueError("Unsupported measured-route model")
        self.model=model
        params=model["parameters"]
        if (not isinstance(params["k"],int) or not isinstance(params["minimum_points"],int)
                or not 1<=params["minimum_points"]<=params["k"]
                or not math.isfinite(params["power"]) or params["power"]<=0
                or not math.isfinite(params["support_radius_m"]) or params["support_radius_m"]<=0):
            raise ValueError("Invalid route model support/interpolation parameters")
        self.points=defaultdict(list)
        for p in model["points"]:
            if len(p["key"])!=5 or not all(math.isfinite(p[k]) for k in ("x","y","rsrp")):
                raise ValueError("Invalid route model point")
            self.points[tuple(p["key"])].append(p)

    @classmethod
    def load(cls,path):
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))

    def predict(self,key,x,y):
        pts=self.points.get(tuple(key),[])
        if not pts:return None
        p=self.model["parameters"]
        near=sorted((math.hypot(x-a["x"],y-a["y"]),i,a["rsrp"]) for i,a in enumerate(pts))
        near=[a for a in near if a[0]<=p["support_radius_m"]][:p["k"]]
        if len(near)<p["minimum_points"]:return None
        d=np.array([a[0] for a in near]);v=np.array([a[2] for a in near]);w=1/np.maximum(d,1)**p["power"]
        return dict(rsrp=float(np.dot(w,v)/w.sum()),nearest_m=float(d.min()),neighbors=len(near),
                    local_spread_db=float(1.4826*np.median(np.abs(v-np.median(v)))),
                    development_cv_mae_db=self.model["metadata"].get("lap1_blocked_cv_mae_db"))

    def measure(self,x,y):
        """Only supported cell/channel predictions; no invented transmitter sites."""
        return {key:p["rsrp"] for key in self.points if (p:=self.predict(key,x,y)) is not None}


def model_document(points,params,metadata=None):
    return dict(format="horus-route-radio-v1",parameters=params,points=points,metadata=metadata or {},
                semantics="Empirical conditional serving-cell RSRP, not a complete network radio field; missing predictions mean unsupported.",
                uncertainty="local_spread_db is neighbor-value dispersion, not a calibrated prediction interval.")
