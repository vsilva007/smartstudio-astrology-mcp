"""SSH bootstrap; only stdlib, no shell expansion or unsafe tar extraction."""

import hashlib
import importlib.util
import json
import os
import pathlib
import sys
import tarfile
import tempfile

os.umask(0o077)
if sys.version_info < (3, 11):  # noqa: UP036 -- bootstrap may run on an older remote host
    sys.exit("Python >=3.11 required")
root, environment = pathlib.Path(sys.argv[1]), sys.argv[2]
if environment not in ("production", "demo") or not root.is_absolute() or root.is_symlink():
    sys.exit("Invalid destination")
root.mkdir(parents=True, exist_ok=True, mode=0o700)
with tempfile.TemporaryDirectory(prefix=".transfer-", dir=root) as temporary:
    stage = pathlib.Path(temporary)
    package = stage / "release.tar.gz"
    with package.open("wb") as output:
        total = 0
        while block := sys.stdin.buffer.read(1024 * 1024):
            total += len(block)
            if total > 8 * 1024**3:
                sys.exit("Package too large")
            output.write(block)
    with tarfile.open(package, "r:gz") as archive:
        manifest_member = archive.getmember("release-manifest.json")
        code_member = archive.getmember("scripts/lib/common.py")
        if (
            not manifest_member.isfile()
            or not code_member.isfile()
            or manifest_member.size > 65536
            or code_member.size > 262144
        ):
            sys.exit("Invalid bootstrap files")
        manifest = json.load(archive.extractfile(manifest_member))
        code = archive.extractfile(code_member).read()
        if hashlib.sha256(code).hexdigest() != manifest["scripts/lib/common.py"]:
            sys.exit("Bootstrap checksum mismatch")
    destination = stage / "bootstrap/scripts/lib/common.py"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(code)
    spec = importlib.util.spec_from_file_location("deployment", destination)
    deployment = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(deployment)
    try:
        deployment.receive_release(package, root, environment)
    except Exception as error:
        sys.exit(f"Remote installation failed: {error}")
