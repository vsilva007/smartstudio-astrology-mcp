import hashlib
import json
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_source_archive_uses_existing_checkout_files(tmp_path):
    for path in ROOT.iterdir():
        if path.is_file() and not path.name.startswith(".env"):
            shutil.copy2(path, tmp_path / path.name)
    for path in ROOT.glob(".env*.example"):
        shutil.copy2(path, tmp_path / path.name)
    for name in ("scripts/build_source.py", "data/ephemeris-manifest.json"):
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / name, target)
    (tmp_path / "uv.lock").write_text('[[package]]\nname = "smartstudio-astrology-mcp"\n')

    subprocess.run([sys.executable, tmp_path / "scripts/build_source.py"], check=True)

    source = tmp_path / "artifacts/source.tar.gz"
    prefix = "smartstudio-astrology-mcp/"
    with tarfile.open(source) as archive:
        manifest = json.load(archive.extractfile(prefix + "SOURCE-MANIFEST.json"))
        assert {"LICENSE", "NOTICE", "scripts/build_source.py"} <= manifest.keys()
        for name, digest in manifest.items():
            assert hashlib.sha256(archive.extractfile(prefix + name).read()).hexdigest() == digest
    assert (source.parent / "source.sha256").read_text() == (
        hashlib.sha256(source.read_bytes()).hexdigest() + "  source.tar.gz\n"
    )
