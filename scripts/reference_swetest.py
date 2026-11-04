"""Rebuild a reference with the original C CLI, without using the Python wrapper."""

import hashlib
import json
import pathlib
import subprocess
import tarfile
import urllib.request

root = pathlib.Path(__file__).resolve().parents[1]
metadata = json.loads((root / "legal/pyswisseph-source.json").read_text())
source = root / "artifacts/pyswisseph-2.10.3.2.tar.gz"
source.parent.mkdir(exist_ok=True)
if not source.exists():
    with urllib.request.urlopen(metadata["url"], timeout=60) as response:
        source.write_bytes(response.read())
if hashlib.sha256(source.read_bytes()).hexdigest() != metadata["sha256"]:
    raise SystemExit("Source integrity failure")
destination = root / "artifacts/swiss-reference"
with tarfile.open(source) as archive:
    for entry in archive.getmembers():
        if entry.isfile() and "/libswe/" in entry.name:
            name = pathlib.Path(entry.name.split("/libswe/", 1)[1])
            if name.is_absolute() or ".." in name.parts:
                raise SystemExit("Invalid archive path")
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.extractfile(entry).read())
subprocess.run(["make", "-C", str(destination), "swetest"], check=True)
arguments = [
    "-edirdata/ephemeris",
    "-b2.7.1985",
    "-ut8:05",
    "-p0123456789m",
    "-eswe",
    "-house-8.6291,41.1579,p",
    "-fPls",
    "-g,",
    "-head",
]
output = subprocess.check_output([str(destination / "swetest"), *arguments], cwd=root, text=True)
values = {
    row.split(",")[0].strip(): [float(v) for v in row.split(",")[1:]]
    for row in output.splitlines()
    if row.strip()
}
document = {
    "source": metadata,
    "engine_version": "2.10.03",
    "arguments": arguments,
    "reference": "supplied_clock_used_as_ut",
    "values": values,
}
target = root / "tests/fixtures/porto-swetest.json"
target.parent.mkdir(exist_ok=True)
target.write_text(json.dumps(document, indent=2) + "\n")
print("Wrote C reference fixture; review numerical changes before accepting.")
