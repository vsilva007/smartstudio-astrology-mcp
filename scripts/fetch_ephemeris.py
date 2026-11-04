"""Fetch pinned official data; no runtime downloads or unverified substitutions."""

import hashlib
import json
import os
import pathlib
import urllib.request

root = pathlib.Path(__file__).resolve().parents[1]
manifest = json.loads((root / "data/ephemeris-manifest.json").read_text())
destination = root / "data/ephemeris"
destination.mkdir(parents=True, exist_ok=True)
for entry in manifest["files"]:
    target = destination / entry["name"]
    if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == entry["sha256"]:
        continue
    with urllib.request.urlopen(entry["url"], timeout=60) as response:
        data = response.read(entry["bytes"] + 1)
    if len(data) != entry["bytes"] or hashlib.sha256(data).hexdigest() != entry["sha256"]:
        raise SystemExit(f"Data verification failed: {entry['name']}")
    temporary = target.with_suffix(".tmp")
    temporary.write_bytes(data)
    os.replace(temporary, target)
    print(f"Verified {entry['name']}")
