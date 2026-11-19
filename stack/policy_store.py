#!/usr/bin/env python3
"""Promoted-policy store — the A1 shim (issue #11).

The bridge from Track B's safety gate to the live xApp: a gate-promoted policy
artifact becomes the one the xApp is running, with no restart. This stands in for
the O-RAN **A1** interface (Non-RT RIC delivers a policy to the Near-RT RIC/xApp);
here the "store" is just a directory of accepted artifacts and the xApp polls it.
Labelled honestly as an interim shim — real A1 lands with loop closure (#12).

Two roles in one file:

  * CLI (admission control) — the *store refuses rejected artifacts*:
        python3 policy_store.py submit <artifact.json> [--store DIR]
        python3 policy_store.py list [--store DIR]
        python3 policy_store.py current [--store DIR]
    `submit` validates the artifact against the frozen policy_artifact.schema.json
    AND requires gate.verdict == "promote"; anything else is REFUSED (non-zero
    exit, nothing written). Accepted artifacts are written atomically as
    <version>.json into the store.

  * Importable (the xApp uses this) — select_active(store) returns the highest
    promoted semver in the store as (version, artifact_dict), or (None, None).
    This path is dependency-light on purpose (no jsonschema) so importing it into
    the xApp never drags in heavy deps; it re-checks gate.verdict defensively.
"""
import os
import re
import sys
import json
import glob

VERSION_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")


def parse_version(v):
    """'v1.2.3' -> (1, 2, 3); None if it doesn't match the frozen schema pattern."""
    m = VERSION_RE.match(v) if isinstance(v, str) else None
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def is_promoted(artifact):
    """True only if gate.verdict == 'promote' (defensive: tolerates missing keys)."""
    return isinstance(artifact, dict) and \
        isinstance(artifact.get("gate"), dict) and \
        artifact["gate"].get("verdict") == "promote"


def _read_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def promoted_artifacts(store_dir):
    """All (version_tuple, version_str, artifact) in the store that are promote-
    verdict with a schema-valid version, skipping anything unreadable/ineligible."""
    out = []
    for path in glob.glob(os.path.join(store_dir, "*.json")):
        try:
            art = _read_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        if not is_promoted(art):
            continue
        vt = parse_version(art.get("version", ""))
        if vt is None:
            continue
        out.append((vt, art["version"], art))
    return out


def select_active(store_dir):
    """(version_str, artifact) of the highest promoted semver in the store, or
    (None, None) if the store is empty/absent/has nothing promoted."""
    promoted = promoted_artifacts(store_dir)
    if not promoted:
        return None, None
    vt, version, art = max(promoted, key=lambda t: t[0])
    return version, art


# --------------------------------------------------------------------------- #
# Admission control (CLI). Uses jsonschema (imported lazily so the xApp's import
# of this module stays dependency-light).
# --------------------------------------------------------------------------- #
def _schema_path_default():
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, "..", "schemas", "policy_artifact.schema.json")


def _validate_schema(artifact, schema_path):
    """Return a list of human-readable schema errors ([] if valid)."""
    from datetime import datetime
    from jsonschema import Draft202012Validator, FormatChecker

    fmt = FormatChecker()

    @fmt.checks("date-time", raises=ValueError)
    def _rfc3339(value):
        if not isinstance(value, str):
            return True
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return True

    with open(schema_path, "r", encoding="utf-8") as f:
        schema = json.load(f)
    validator = Draft202012Validator(schema, format_checker=fmt)
    return [e.message for e in sorted(validator.iter_errors(artifact), key=lambda e: list(e.path))]


def admit(artifact_path, store_dir, schema_path=None):
    """Validate + gate-check an artifact and, if it passes, write it into the
    store as <version>.json. Returns (accepted: bool, version: str|None, reason).
    Rejected/invalid artifacts are NOT written."""
    schema_path = schema_path or _schema_path_default()
    try:
        artifact = _read_json(artifact_path)
    except (OSError, json.JSONDecodeError) as e:
        return False, None, f"cannot read artifact: {e}"

    if not isinstance(artifact, dict):
        return False, None, "schema-invalid: policy artifact must be a JSON object"

    errors = _validate_schema(artifact, schema_path)
    if errors:
        return False, artifact.get("version"), "schema-invalid: " + "; ".join(errors)

    verdict = artifact["gate"]["verdict"]
    if verdict != "promote":
        return False, artifact["version"], f"gate.verdict is '{verdict}', not 'promote' — store refuses it"

    # Accepted. Write atomically as <version>.json so the xApp never reads a
    # half-written file (write temp in the same dir, then os.replace).
    version = artifact["version"]
    # Defence-in-depth: the schema already enforces ^v\d+\.\d+\.\d+$, so `version`
    # is path-safe here — but assert it locally so building a filename from it can
    # never depend on validation happening earlier/elsewhere.
    if parse_version(version) is None:
        return False, version, f"version {version!r} is not vX.Y.Z — refusing to build a store path from it"
    os.makedirs(store_dir, exist_ok=True)
    dest = os.path.join(store_dir, f"{version}.json")
    tmp = dest + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(artifact, f, indent=2)
        f.write("\n")
    os.replace(tmp, dest)
    return True, version, f"admitted -> {os.path.basename(dest)}"


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _parse_args(argv):
    """Pull `--store DIR` out from anywhere in argv (order-independent) and return
    (store, positionals). Default store from POLICY_STORE_DIR or ../working/policies."""
    store = os.environ.get("POLICY_STORE_DIR",
                           os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                        "..", "working", "policies"))
    positionals, i = [], 0
    while i < len(argv):
        if argv[i] == "--store" and i + 1 < len(argv):
            store = argv[i + 1]
            i += 2
            continue
        positionals.append(argv[i])
        i += 1
    return store, positionals


def main(argv):
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        return 0
    cmd = argv[0]
    store, positionals = _parse_args(argv[1:])   # --store may appear before or after the file

    if cmd == "submit":
        if not positionals:
            print("usage: policy_store.py submit <artifact.json> [--store DIR]", file=sys.stderr)
            return 2
        accepted, version, reason = admit(positionals[0], store)
        tag = "ACCEPTED" if accepted else "REFUSED"
        print(f"[policy-store] {tag}: version={version} ({reason})")
        print(f"[policy-store] store: {os.path.abspath(store)}")
        return 0 if accepted else 1

    if cmd == "list":
        promoted = promoted_artifacts(store)
        if not promoted:
            print(f"[policy-store] no promoted artifacts in {os.path.abspath(store)}")
            return 0
        for vt, version, art in sorted(promoted, key=lambda t: t[0]):
            print(f"  {version}\talgo={art.get('algo')}\ttrained_on={art.get('trained_on', {}).get('radio_map')}")
        return 0

    if cmd == "current":
        version, art = select_active(store)
        print(version if version else "(none)")
        return 0

    print(f"[policy-store] unknown command: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
