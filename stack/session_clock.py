"""One steady session clock, anchored once to UTC and shared on the same boot.

Freshness is elapsed time, so a host wall-clock correction must neither age
valid observations nor make old ones fresh. Raw wall time and its offset remain
diagnostics. This clock never resets an existing frame's acquisition timestamp.
"""
from datetime import datetime, timezone
import math
import os
from pathlib import Path
import platform
import time


def boot_id():
    path=Path('/proc/sys/kernel/random/boot_id')
    return path.read_text().strip() if path.exists() else platform.node()+':'+os.name


class SessionClock:
    def __init__(self, record=None, *, monotonic=None, wall=None, host_boot=None):
        self.monotonic=monotonic or time.monotonic
        self.wall=wall or time.time
        self.boot=host_boot or boot_id()
        self.record=record or dict(kind='horus.steady-session-utc/1',boot_id=self.boot,
            anchor_monotonic_s=self.monotonic(),anchor_utc_s=self.wall())
        if self.record.get('kind')!='horus.steady-session-utc/1' or self.record.get('boot_id')!=self.boot:
            raise ValueError('Session clock belongs to a different host boot')
        for key in ('anchor_monotonic_s','anchor_utc_s'):
            value=self.record.get(key)
            if type(value) not in (int,float) or not math.isfinite(value):
                raise ValueError('Invalid session clock anchor')
        if self.monotonic()<self.record['anchor_monotonic_s']-.1:
            raise ValueError('Session clock anchor is in the future')

    def timestamp(self):
        return self.record['anchor_utc_s']+self.monotonic()-self.record['anchor_monotonic_s']

    def at_monotonic(self, value):
        return self.record['anchor_utc_s']+value-self.record['anchor_monotonic_s']

    def now(self):
        return datetime.fromtimestamp(self.timestamp(),timezone.utc)

    def iso(self):
        return self.now().isoformat()

    def diagnostics(self):
        wall=self.wall()
        return dict(raw_wall_utc=datetime.fromtimestamp(wall,timezone.utc).isoformat(),
                    wall_minus_session_s=wall-self.timestamp())
