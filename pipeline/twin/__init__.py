"""HORUS digital twin (Track B): fast campus-in-software for handover policy work.

Gym-style env (reset/step) over a cellular radio map. v0 (#3): grid mobility,
placeholder path-loss map, A3 baseline controller, per-episode metrics.
The radio map is swappable (#6: opencellid geometry, walk-test calibrated) —
the map-name strings deliberately match the frozen policy_artifact schema's
trained_on.radio_map enum: placeholder | opencellid | measured.

Core is stdlib-only on purpose: `python -m twin.run` must work anywhere
without an install step. ML dependencies arrive with the DQN work (#8).
"""
