"""Create an allowlisted source offer, including pinned runtime dependency sources."""

import gzip
import hashlib
import io
import json
import pathlib
import tarfile
import tomllib
import urllib.request

root = pathlib.Path(__file__).resolve().parents[1]
packages = {p["name"]: p for p in tomllib.loads((root / "uv.lock").read_text())["package"]}
runtime = set()


def visit(name):
    if name in runtime:
        return
    runtime.add(name)
    for dependency in packages[name].get("dependencies", []):
        if dependency["name"] in {"pywin32", "httpx2-jsfetch"}:
            continue
        visit(dependency["name"])
        for extra in dependency.get("extra", []):
            for optional in (
                packages[dependency["name"]].get("optional-dependencies", {}).get(extra, [])
            ):
                visit(optional["name"])


visit("smartstudio-astrology-mcp")
files = {}
for directory in [
    "src",
    "tests",
    "scripts",
    "docs",
    "legal",
    "deploy",
    "docker",
    "plugin",
    ".github",
]:
    for path in (root / directory).rglob("*"):
        if path.is_file() and not path.is_symlink() and "__pycache__" not in path.parts:
            if path.name.startswith(".env") and not path.name.endswith(".example"):
                continue
            if path.suffix not in {".pyc", ".pyo"}:
                files[str(path.relative_to(root))] = path.read_bytes()
for name in [
    "pyproject.toml",
    "uv.lock",
    "requirements.lock",
    "requirements-dev.lock",
    ".python-version",
    ".env.production.example",
    ".env.demo.example",
    ".dockerignore",
    ".gitignore",
    ".env.example",
    "LICENSE",
    "NOTICE",
    "README.md",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "data/ephemeris-manifest.json",
]:
    files[name] = (root / name).read_bytes()
cache = root / "artifacts/upstream-sources"
cache.mkdir(parents=True, exist_ok=True)
for name in sorted(runtime - {"smartstudio-astrology-mcp"}):
    entry = packages[name].get("sdist")
    if not entry:
        raise SystemExit(f"Cannot supply corresponding source for {name}")
    filename = entry["url"].rsplit("/", 1)[1]
    target = cache / filename
    bundled = root / "upstream-sources" / filename
    if not target.exists() and bundled.is_file():
        target.write_bytes(bundled.read_bytes())
    if not target.exists():
        with urllib.request.urlopen(entry["url"], timeout=60) as response:
            target.write_bytes(response.read())
    data = target.read_bytes()
    if "sha256:" + hashlib.sha256(data).hexdigest() != entry["hash"]:
        raise SystemExit(f"Source integrity failure: {name}")
    files["upstream-sources/" + filename] = data
manifest = {name: hashlib.sha256(data).hexdigest() for name, data in sorted(files.items())}
files["SOURCE-MANIFEST.json"] = (json.dumps(manifest, indent=2) + "\n").encode()
destination = root / "artifacts/source.tar.gz"
with destination.open("wb") as output:
    with gzip.GzipFile(filename="", fileobj=output, mode="wb", mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode="w") as archive:
            for name, data in sorted(files.items()):
                info = tarfile.TarInfo("smartstudio-astrology-mcp/" + name)
                info.size, info.mode, info.mtime = (
                    len(data),
                    0o755 if name.endswith(".sh") else 0o644,
                    0,
                )
                archive.addfile(info, io.BytesIO(data))
digest = hashlib.sha256(destination.read_bytes()).hexdigest()
(root / "artifacts/source.sha256").write_text(digest + "  source.tar.gz\n")
print(f"Source offer: {len(files)} files, sha256:{digest}")
