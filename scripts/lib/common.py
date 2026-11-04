"""Registry-free deployment. Configuration is data, never shell code."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import shlex
import shutil
import socket
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

PROJECT_LABEL = "dev.smartstudio.project"
ENV_LABEL = "dev.smartstudio.environment"
REV_LABEL = "org.opencontainers.image.revision"
ROOT = Path(__file__).resolve().parents[2]
ENVIRONMENTS = ("production", "demo")
ACTIONS = (
    "build",
    "package",
    "local",
    "remote",
    "install",
    "verify",
    "rollback",
    "cleanup",
    "status",
    "logs",
    "isolation",
)
REMOTE_ACTIONS = ("deploy", "verify", "rollback", "cleanup", "status", "logs")
STATE_REFS = ("built-image", "current-image", "previous-image", "pending-image", "pending-previous")
DEFAULTS = dict(
    CONTAINER_PORT="8000",
    TRUST_PROXY="false",
    MEMORY_LIMIT="768m",
    HEALTH_TIMEOUT="120",
    BUILD_PLATFORM="linux/amd64",
    REMOTE_HOST="",
    REMOTE_PORT="22",
    REMOTE_PATH="/srv/smartstudio-astrology-mcp",
    LICENSE_REVIEW_APPROVED="false",
    LOCAL_TEST_ONLY="false",
    METRICS_TOKEN="",
    OPENAI_CHALLENGE_TOKEN="",
    RATE_PER_MINUTE="60",
    GLOBAL_RATE_PER_MINUTE="600",
    GEOCODER="disabled",
    GEOCODER_URL="",
)
REQUIRED = {"PROJECT_NAME", "PUBLIC_ORIGIN", "CANONICAL_ORIGIN", "HOST_PORT"}
KEYS = REQUIRED | DEFAULTS.keys()


class Failure(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise Failure(message)


def digest_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def private_dir(path):
    path = Path(path)
    require(not path.is_symlink(), "Refusing symlink directory")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)


def atomic(path, value):
    path = Path(path)
    require(not path.is_symlink(), "Refusing symlink state/configuration")
    private_dir(path.parent)
    fd, name = tempfile.mkstemp(prefix="." + path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as file:
            file.write(value)
            file.flush()
            os.fsync(file.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


class Lock:
    def __init__(self, path):
        self.path = Path(path)

    def __enter__(self):
        private_dir(self.path.parent)
        try:
            self.path.mkdir(mode=0o700)
        except FileExistsError as exc:
            raise Failure(
                f"Operation locked: {self.path}. Verify owner/process before manual removal."
            ) from exc
        try:
            atomic(
                self.path / "owner.json",
                json.dumps(
                    {
                        "pid": os.getpid(),
                        "host": socket.gethostname(),
                        "started": datetime.now(UTC).isoformat(),
                    }
                ),
            )
        except BaseException:
            shutil.rmtree(self.path)
            raise
        return self

    def __exit__(self, *_):
        (self.path / "owner.json").unlink()
        self.path.rmdir()


def parse_config(path, environment, private=True):
    path = Path(path)
    require(environment in ENVIRONMENTS, "Unknown environment")
    require(path.is_file() and not path.is_symlink(), "Configuration file missing or symlinked")
    require(path.stat().st_size <= 16384, "Configuration too large")
    if private:
        require(
            stat.S_IMODE(path.stat().st_mode) & 0o077 == 0,
            "Configuration must be private: chmod 600 FILE",
        )
    config, seen = dict(DEFAULTS), set()
    for number, line in enumerate(path.read_text().splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        require("=" in line, f"Invalid configuration line {number}")
        key, value = line.split("=", 1)
        require(
            key in KEYS and key not in seen,
            f"Unknown or duplicate configuration key at line {number}",
        )
        require(value == value.strip() and len(value) <= 2048, f"Invalid value at line {number}")
        require(
            not any(c in value for c in "$`\\'\"\r\n") and all(ord(c) >= 32 for c in value),
            f"Quotes, expansions and escapes are forbidden at line {number}",
        )
        seen.add(key)
        config[key] = value
    require(REQUIRED <= seen, "Missing required configuration keys")
    require(re.fullmatch(r"[a-z][a-z0-9-]{2,47}", config["PROJECT_NAME"]), "Invalid PROJECT_NAME")
    for key, minimum, maximum in [
        ("HOST_PORT", 1024, 65535),
        ("CONTAINER_PORT", 8000, 8000),
        ("REMOTE_PORT", 1, 65535),
        ("HEALTH_TIMEOUT", 5, 900),
        ("RATE_PER_MINUTE", 1, 10000),
        ("GLOBAL_RATE_PER_MINUTE", 1, 100000),
    ]:
        require(config[key].isdigit() and minimum <= int(config[key]) <= maximum, f"Invalid {key}")
    require(
        config["TRUST_PROXY"] == "false",
        "TRUST_PROXY must remain false; enforce client limits at HTTPS proxy",
    )
    require(re.fullmatch(r"[1-9][0-9]{0,4}[mg]", config["MEMORY_LIMIT"]), "Invalid MEMORY_LIMIT")
    require(config["BUILD_PLATFORM"] in ("linux/amd64", "linux/arm64"), "Invalid BUILD_PLATFORM")
    for key in ("LICENSE_REVIEW_APPROVED", "LOCAL_TEST_ONLY"):
        require(config[key] in ("true", "false"), f"Invalid {key}")
    require(
        config["PUBLIC_ORIGIN"] == config["CANONICAL_ORIGIN"],
        "Canonical must belong to this environment",
    )
    for key in ("PUBLIC_ORIGIN", "CANONICAL_ORIGIN"):
        url = urlparse(config[key])
        require(
            url.hostname
            and not url.username
            and not url.password
            and not url.query
            and not url.fragment
            and url.path == ""
            and re.fullmatch(r"[A-Za-z0-9.:-]+", url.netloc),
            f"Invalid {key}",
        )
        if config["LOCAL_TEST_ONLY"] == "true":
            require(
                url.scheme == "http"
                and url.hostname == "127.0.0.1"
                and url.port == int(config["HOST_PORT"]),
                "Local tests require matching HTTP loopback origin/port",
            )
        else:
            require(url.scheme == "https", "Public origins require HTTPS")
            require(url.port in (None, 443), "Public origins use HTTPS port 443")
    require(
        not config["REMOTE_HOST"]
        or re.fullmatch(
            r"(?:[A-Za-z0-9_][A-Za-z0-9_.-]*@)?[A-Za-z0-9][A-Za-z0-9_.-]*", config["REMOTE_HOST"]
        ),
        "Invalid REMOTE_HOST",
    )
    remote_path = config["REMOTE_PATH"]
    require(
        re.fullmatch(r"/[A-Za-z0-9_./-]+", remote_path)
        and ".." not in Path(remote_path).parts
        and remote_path not in ("/", "/tmp", "/srv", "/home")
        and not remote_path.endswith("/"),
        "Invalid REMOTE_PATH",
    )
    for key in ("METRICS_TOKEN", "OPENAI_CHALLENGE_TOKEN"):
        require(
            not config[key] or re.fullmatch(r"[A-Za-z0-9_.:=+/-]{1,512}", config[key]),
            f"Invalid {key}",
        )
    require(config["GEOCODER"] in ("disabled", "nominatim"), "Invalid GEOCODER")
    require(
        environment != "demo" or config["GEOCODER"] == "disabled",
        "Demo external integrations must be disabled",
    )
    if config["GEOCODER"] == "nominatim":
        url = urlparse(config["GEOCODER_URL"])
        require(
            url.scheme == "https"
            and url.hostname
            and not url.username
            and not url.password
            and url.hostname != "nominatim.openstreetmap.org",
            "Configure an authorized HTTPS geocoder",
        )
    else:
        require(not config["GEOCODER_URL"], "Disabled geocoder must not have a URL")
    return config


def command(args, *, cwd=None, env=None, capture=True, check=True, stdin=None, stdout=None):
    try:
        result = subprocess.run(
            [str(a) for a in args],
            cwd=cwd,
            env=env,
            stdin=stdin,
            stdout=stdout if stdout is not None else (subprocess.PIPE if capture else None),
            stderr=subprocess.PIPE if capture else None,
            text=stdout is None,
        )
    except OSError as exc:
        raise Failure(f"Cannot execute {args[0]}") from exc
    if check and result.returncode:
        # Compose can include configuration in diagnostics; do not echo raw stderr.
        raise Failure(f"{args[0]} command failed (exit {result.returncode})")
    return result


def operator_python():
    require(sys.version_info >= (3, 11), "Operational scripts require Python >=3.11")


def build_python(root):
    expected = (root / ".python-version").read_text().strip()
    for executable in [
        root / ".venv312/bin/python",
        root / ".venv/bin/python",
        shutil.which("python3.12"),
        shutil.which("python3"),
    ]:
        if executable and Path(executable).is_file():
            result = command(
                [executable, "-c", "import platform; print(platform.python_version())"], check=False
            )
            if result.returncode == 0 and result.stdout.strip() == expected:
                return str(executable)
    raise Failure(
        f"Python {expected} must already be installed in .venv312, .venv or PATH; no automatic download"
    )


def package_paths(environment):
    return [
        "scripts/deploy.sh",
        "scripts/lib/common.sh",
        "scripts/lib/common.py",
        "scripts/lib/python.sh",
        "scripts/deploy/receive.py",
        *[
            f"scripts/deploy/{name}.sh"
            for name in ["deploy-local", "deploy-remote", "install", "rollback", "cleanup"]
        ],
        "scripts/verify/verify.sh",
        "scripts/verify/verify-http.py",
        "scripts/verify/verify-isolation.sh",
        "docker/compose.yaml",
        f"docker/compose.{environment}.yaml",
    ]


class Deployment:
    def __init__(self, root, environment, config_path=None):
        self.root, self.environment = Path(root).resolve(), environment
        self.config_path = (
            Path(config_path).absolute() if config_path else self.root / f".env.{environment}"
        )
        self.config = parse_config(self.config_path, environment)
        self.state = self.root / ".deploy" / environment
        private_dir(self.state)
        self.project = self.config["PROJECT_NAME"]
        self.compose_project = f"{self.project}-{environment}"
        sibling = self.root / f".env.{'demo' if environment == 'production' else 'production'}"
        if sibling.exists() and sibling != self.config_path:
            other = parse_config(sibling, "demo" if environment == "production" else "production")
            require(
                other["HOST_PORT"] != self.config["HOST_PORT"], "Environment host ports must differ"
            )
            require(
                other["PUBLIC_ORIGIN"] != self.config["PUBLIC_ORIGIN"],
                "Environment origins must differ",
            )
        owner = self.state / "identity.json"
        if owner.exists():
            require(
                json.loads(owner.read_text()) == self.identity,
                "State belongs to another project/environment",
            )

    @property
    def identity(self):
        return {"project": self.project, "environment": self.environment}

    def locked(self):
        return Lock(self.state / "lock")

    def ref(self, name):
        path = self.state / name
        require(not path.is_symlink(), "Refusing symlink state")
        return path.read_text().strip() if path.exists() else ""

    def save(self, name, value):
        atomic(self.state / name, value + "\n")

    def requirements(self, remote=False):
        for executable in ("docker", "bash", "python3", "curl", "tar") + (
            ("ssh",) if remote else ()
        ):
            require(shutil.which(executable), f"Missing required command: {executable}")
        command(["docker", "info"])
        version = command(["docker", "compose", "version", "--short"]).stdout.strip().lstrip("v")
        require(version.split(".")[0] == "2", "Docker Compose v2 is required")

    def image_info(self, reference, required=True):
        result = command(["docker", "image", "inspect", reference], check=False)
        if result.returncode:
            require(not required, "Image not present locally; no implicit pull is performed")
            return None
        return json.loads(result.stdout)[0]

    def validate_image(self, reference):
        require(
            re.fullmatch(
                re.escape(self.project) + ":" + self.environment + r"-[a-zA-Z0-9_.-]+", reference
            ),
            "Image reference must be project:environment-version; latest and foreign images are forbidden",
        )
        info = self.image_info(reference)
        labels = info["Config"].get("Labels") or {}
        require(
            labels.get(PROJECT_LABEL) == self.project and labels.get(ENV_LABEL) == self.environment,
            "Image ownership/environment labels do not match",
        )
        require(
            re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", labels.get(REV_LABEL, "")),
            "Image revision label missing",
        )
        require(
            f"{info['Os']}/{info['Architecture']}" == self.config["BUILD_PLATFORM"],
            "Image platform mismatch",
        )
        return info

    def compose_env(self, reference):
        info = self.validate_image(reference)
        clean = {
            k: v
            for k, v in os.environ.items()
            if k not in KEYS and not k.startswith(("COMPOSE_", "CARTA_", "DEPLOY_"))
        }
        origin = urlparse(self.config["PUBLIC_ORIGIN"])
        clean.update(self.config)
        clean.update(
            DEPLOY_ENV=self.environment,
            DEPLOY_IMAGE=reference,
            RELEASE_REVISION=info["Config"]["Labels"][REV_LABEL],
            ALLOWED_HOSTS_JSON=json.dumps([origin.netloc]),
            ALLOWED_ORIGINS_JSON=json.dumps([self.config["PUBLIC_ORIGIN"], "https://chatgpt.com"]),
            SOURCE_URL=self.config["CANONICAL_ORIGIN"] + "/source.tar.gz",
        )
        return clean

    def compose(self, reference, *args, capture=True):
        return command(
            [
                "docker",
                "compose",
                "--env-file",
                "/dev/null",
                "--project-directory",
                self.root,
                "-p",
                self.compose_project,
                "-f",
                self.root / "docker/compose.yaml",
                "-f",
                self.root / f"docker/compose.{self.environment}.yaml",
                *args,
            ],
            cwd=self.root,
            env=self.compose_env(reference),
            capture=capture,
        )

    def containers(self):
        result = command(
            [
                "docker",
                "ps",
                "-aq",
                "--filter",
                f"label=com.docker.compose.project={self.compose_project}",
                "--filter",
                "label=com.docker.compose.service=mcp",
            ]
        )
        ids = result.stdout.split()
        require(len(ids) <= 1, "Expected at most one application container for this environment")
        return ids

    def inspect_container(self):
        ids = self.containers()
        if not ids:
            return None
        info = json.loads(command(["docker", "inspect", ids[0]]).stdout)[0]
        labels = info["Config"].get("Labels") or {}
        require(
            labels.get(PROJECT_LABEL) == self.project and labels.get(ENV_LABEL) == self.environment,
            "Container ownership mismatch",
        )
        return info

    def active_image(self):
        container = self.inspect_container()
        if container and container["State"]["Running"]:
            reference = container["Config"]["Image"]
            require(
                self.validate_image(reference)["Id"] == container["Image"],
                "Running tag has been moved",
            )
            return reference
        return ""

    def check_activation(self):
        if self.config["LOCAL_TEST_ONLY"] != "true":
            require(
                self.config["LICENSE_REVIEW_APPROVED"] == "true",
                "Public deployment blocked: complete documented license review",
            )
            require(
                len(self.config["METRICS_TOKEN"]) >= 32,
                "Public deployment requires METRICS_TOKEN of at least 32 characters",
            )

    def await_healthy(self, reference):
        expected = self.validate_image(reference)["Id"]
        deadline = time.monotonic() + int(self.config["HEALTH_TIMEOUT"])
        while time.monotonic() < deadline:
            container = self.inspect_container()
            if container:
                require(container["Image"] == expected, "Unexpected image running")
                state = container["State"]
                if state.get("Health", {}).get("Status") == "healthy":
                    return container
                if (
                    state["Status"] in ("exited", "dead")
                    or state.get("Health", {}).get("Status") == "unhealthy"
                ):
                    raise Failure("Container failed startup/healthcheck")
            time.sleep(1)
        raise Failure("Healthcheck timeout")

    def verify(self, reference=None):
        reference = reference or self.ref("current-image") or self.active_image()
        require(reference, "No current image to verify")
        container = self.await_healthy(reference)
        host = container["HostConfig"]
        require(container["Config"]["User"] == "1000:1000", "Runtime must use UID/GID 1000")
        require(
            host["ReadonlyRootfs"] is True and host["Init"] is True,
            "Runtime must be read-only with init",
        )
        require(
            all(m["Type"] == "tmpfs" for m in container.get("Mounts", [])),
            "Persistent/bind mounts are forbidden",
        )
        require(
            "ALL" in host.get("CapDrop", [])
            and any(v.startswith("no-new-privileges") for v in host.get("SecurityOpt", [])),
            "Missing runtime hardening",
        )
        require(
            host.get("PidsLimit") == 128 and host.get("Memory", 0) > 0,
            "Missing process/memory limits",
        )
        bindings = host.get("PortBindings", {}).get("8000/tcp", [])
        require(
            bindings == [{"HostIp": "127.0.0.1", "HostPort": self.config["HOST_PORT"]}],
            "Unexpected published ports",
        )
        networks = container["NetworkSettings"]["Networks"]
        require(
            set(networks) == {self.compose_project + "-network"}, "Unexpected network attachment"
        )
        info = self.validate_image(reference)
        result = command(
            [
                sys.executable,
                self.root / "scripts/verify/verify-http.py",
                "--base",
                "http://127.0.0.1:" + self.config["HOST_PORT"],
                "--origin",
                self.config["PUBLIC_ORIGIN"],
                "--env",
                self.environment,
                "--revision",
                info["Config"]["Labels"][REV_LABEL],
            ],
            env={
                **os.environ,
                "VERIFY_GEOCODER": self.config["GEOCODER"],
                "VERIFY_CHALLENGE": self.config["OPENAI_CHALLENGE_TOKEN"],
            },
            check=False,
        )
        if result.returncode:
            message = result.stderr.strip()[-1000:]
            for key in ("METRICS_TOKEN", "OPENAI_CHALLENGE_TOKEN"):
                if self.config[key]:
                    message = message.replace(self.config[key], "[REDACTED]")
            raise Failure(message or "Functional HTTP verification failed")
        print(f"Verified {self.compose_project}: {reference}")
        return container

    def logs(self, failure=False):
        container = self.inspect_container()
        value = ""
        if container:
            result = command(["docker", "logs", "--tail", "200", container["Id"]], check=False)
            value = (result.stdout or "") + (result.stderr or "")
        for key in ("METRICS_TOKEN", "OPENAI_CHALLENGE_TOKEN"):
            if self.config[key]:
                value = value.replace(self.config[key], "[REDACTED]")
        if failure:
            self.save(
                "failure.log",
                value or "Container unavailable; inspect Docker/Compose on this host.",
            )
        else:
            print(value, end="")

    def deploy(self, reference):
        self.check_activation()
        self.validate_image(reference)
        self.compose(reference, "config", "--quiet")
        require(
            not self.ref("pending-image"),
            "Interrupted transaction exists; inspect pending refs and recover before retrying",
        )
        previous = self.active_image()
        self.save("pending-image", reference)
        self.save("pending-previous", previous)
        try:
            self.compose(reference, "up", "-d", "--no-build", "--pull", "never", "mcp")
            self.verify(reference)
        except (Exception, KeyboardInterrupt) as error:
            self.logs(failure=True)
            message = str(error)
            for key in ("METRICS_TOKEN", "OPENAI_CHALLENGE_TOKEN"):
                if self.config[key]:
                    message = message.replace(self.config[key], "[REDACTED]")
            self.save("failure.log", message + "\n" + self.ref("failure.log"))
            recovered = False
            try:
                if previous:
                    self.compose(previous, "up", "-d", "--no-build", "--pull", "never", "mcp")
                    self.verify(previous)
                    recovered = True
                else:
                    self.compose(reference, "stop", "mcp")
                    recovered = True
            except Exception:
                print(
                    "Recovery could not be verified; pending references retained.", file=sys.stderr
                )
            if recovered:
                self.clear_pending()
            raise Failure(
                "Deployment failed; see private failure.log. Previous image recovery attempted."
            ) from None
        if previous and previous != reference:
            self.save("previous-image", previous)
        self.save("current-image", reference)
        atomic(self.state / "identity.json", json.dumps(self.identity))
        self.clear_pending()
        print(f"Confirmed {self.compose_project}")

    def clear_pending(self):
        for name in ("pending-image", "pending-previous"):
            (self.state / name).unlink(missing_ok=True)

    def rollback(self):
        target = self.ref("previous-image")
        require(target, "No previous image available")
        require(
            not self.ref("pending-image"),
            "Unresolved transaction; inspect pending state before rollback",
        )
        self.deploy(target)

    def build(self):
        require(
            (self.root / "docker/Dockerfile").is_file(),
            "Build requires the source checkout; not available in installed packages",
        )
        with Lock(self.root / ".deploy/build.lock"):
            base_python = build_python(self.root)
            environment = self.root / ".deploy/build-venv"
            command([base_python, "-m", "venv", environment])
            python = str(environment / "bin/python")
            command(
                [
                    python,
                    "-m",
                    "pip",
                    "install",
                    "--require-hashes",
                    "-r",
                    self.root / "requirements-dev.lock",
                ],
                capture=False,
            )
            for args in [
                ["-m", "compileall", "-q", "src"],
                ["scripts/fetch_ephemeris.py"],
                ["-m", "pytest", "-q"],
                ["scripts/export_schemas.py", "--check"],
                ["scripts/build_source.py"],
            ]:
                command(
                    [python, *args],
                    cwd=self.root,
                    env={**os.environ, "PYTHONPATH": str(self.root / "src")},
                    capture=False,
                )
            revision = command(
                ["git", "-C", self.root, "rev-parse", "--short=12", "HEAD"], check=False
            ).stdout.strip()
            snapshot = digest_file(self.root / "artifacts/source.tar.gz")[:12]
            dirty = command(
                ["git", "-C", self.root, "status", "--porcelain"], check=False
            ).stdout.strip()
            revision = (
                revision + "-dirty-" + snapshot if revision and dirty else revision
            ) or "snapshot-" + snapshot
            tag = f"{self.environment}-{datetime.now(UTC):%Y%m%dT%H%M%S%fZ}-{revision}"
            reference = f"{self.project}:{tag}"
            require(
                not self.image_info(reference, required=False), "Versioned image already exists"
            )
            command(
                [
                    "docker",
                    "build",
                    "--platform",
                    self.config["BUILD_PLATFORM"],
                    "-f",
                    self.root / "docker/Dockerfile",
                    "--build-arg",
                    "PROJECT_NAME=" + self.project,
                    "--build-arg",
                    "DEPLOY_ENV=" + self.environment,
                    "--build-arg",
                    "RELEASE_REVISION=" + revision,
                    "-t",
                    reference,
                    self.root,
                ],
                capture=False,
            )
            self.validate_image(reference)
            self.save("built-image", reference)
            print(reference)
            return reference

    def package(self, reference=None, output=None):
        reference = reference or self.ref("built-image")
        info = self.validate_image(reference)
        target = (
            Path(output).resolve()
            if output
            else self.root / "artifacts" / (reference.split(":")[1] + ".tar.gz")
        )
        require(not target.exists(), "Refusing to overwrite an existing release package")
        private_dir(target.parent)
        with tempfile.TemporaryDirectory(prefix=".release-", dir=self.state) as temporary:
            stage = Path(temporary)
            command(["docker", "image", "save", "-o", stage / "image.tar", reference])
            for name in package_paths(self.environment):
                source = self.root / name
                require(
                    source.is_file() and not source.is_symlink(), f"Missing package file: {name}"
                )
                dest = stage / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, dest)
            (stage / "release-image").write_text(reference + "\n")
            (stage / "release-image-id").write_text(info["Id"] + "\n")
            (stage / f".env.{self.environment}").write_text(
                "".join(k + "=" + v + "\n" for k, v in self.config.items())
            )
            files = sorted(p for p in stage.rglob("*") if p.is_file())
            manifest = {str(p.relative_to(stage)): digest_file(p) for p in files}
            (stage / "release-manifest.json").write_text(json.dumps(manifest, sort_keys=True))
            fd, temporary_archive = tempfile.mkstemp(prefix="." + target.name, dir=target.parent)
            os.close(fd)
            try:
                with tarfile.open(temporary_archive, "w:gz") as archive:
                    for path in sorted(p for p in stage.rglob("*") if p.is_file()):
                        entry = archive.gettarinfo(path, str(path.relative_to(stage)))
                        entry.mode = 0o700 if path.suffix == ".sh" else 0o600
                        entry.uid = entry.gid = 0
                        entry.uname = entry.gname = ""
                        with path.open("rb") as stream:
                            archive.addfile(entry, stream)
                os.replace(temporary_archive, target)
            finally:
                Path(temporary_archive).unlink(missing_ok=True)
        print(f"Private release package: {target}")
        return target

    def install(self):
        reference = (self.root / "release-image").read_text().strip()
        expected = (self.root / "release-image-id").read_text().strip()
        require(re.fullmatch(r"sha256:[0-9a-f]{64}", expected), "Invalid expected image ID")
        existing = self.image_info(reference, required=False)
        require(
            not existing or existing["Id"] == expected,
            "Existing image tag points to different content",
        )
        image_tar = self.root / "image.tar"
        if image_tar.exists():
            verify_image_archive(image_tar, reference, expected, self.identity)
            command(["docker", "image", "load", "-i", image_tar])
        loaded = self.validate_image(reference)
        require(loaded["Id"] == expected, "Loaded image ID mismatch")
        self.compose(reference, "config", "--quiet")
        self.save("built-image", reference)
        image_tar.unlink(missing_ok=True)
        self.deploy(reference)

    def cleanup(self):
        protected = {self.ref(name) for name in STATE_REFS} - {""}
        ids = command(["docker", "ps", "-aq"]).stdout.split()
        containers = json.loads(command(["docker", "inspect", *ids]).stdout) if ids else []
        for container in containers:
            labels = container["Config"].get("Labels") or {}
            reference = container["Config"]["Image"]
            if (
                labels.get(PROJECT_LABEL) == self.project
                and labels.get(ENV_LABEL) == self.environment
            ):
                if not container["State"]["Running"] and reference not in protected:
                    command(["docker", "container", "rm", container["Id"]])
        ids = command(["docker", "ps", "-aq"]).stdout.split()
        in_use = (
            {c["Image"] for c in json.loads(command(["docker", "inspect", *ids]).stdout)}
            if ids
            else set()
        )
        protected_ids = {
            i["Id"] for ref in protected if (i := self.image_info(ref, required=False))
        }
        images = command(
            [
                "docker",
                "image",
                "ls",
                "--format",
                "{{.Repository}}:{{.Tag}}",
                "--filter",
                f"label={PROJECT_LABEL}={self.project}",
                "--filter",
                f"label={ENV_LABEL}={self.environment}",
            ]
        ).stdout.splitlines()
        for reference in images:
            if "<none>" in reference or reference in protected:
                continue
            info = self.validate_image(reference)
            if info["Id"] not in in_use | protected_ids:
                command(["docker", "image", "rm", reference])
        print(f"Cleanup limited to {self.compose_project}")

    def status(self):
        container = self.inspect_container()
        print(
            json.dumps(
                {
                    "project": self.compose_project,
                    "references": {name: self.ref(name) for name in STATE_REFS},
                    "container": None
                    if not container
                    else {
                        "id": container["Id"],
                        "status": container["State"]["Status"],
                        "health": container["State"].get("Health", {}).get("Status"),
                    },
                },
                indent=2,
            )
        )

    def remote(self, action="deploy", reference=None):
        require(self.config["REMOTE_HOST"], "REMOTE_HOST is required")
        require(
            self.config["LOCAL_TEST_ONLY"] == "false",
            "Local-only test configurations cannot be sent over SSH",
        )
        target = self.config["REMOTE_PATH"] + "/" + self.environment
        ssh = [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            "ConnectTimeout=15",
            "-p",
            self.config["REMOTE_PORT"],
            self.config["REMOTE_HOST"],
        ]
        if action != "deploy":
            command(
                [
                    *ssh,
                    shlex.join(
                        ["bash", target + "/scripts/deploy.sh", action, "--env", self.environment]
                    ),
                ],
                capture=False,
            )
            return
        self.check_activation()
        with tempfile.TemporaryDirectory(prefix="transfer-", dir=self.state) as temporary:
            package = self.package(reference, Path(temporary) / "release.tar.gz")
            receiver = (self.root / "scripts/deploy/receive.py").read_text()
            remote_command = shlex.join(["python3", "-c", receiver, target, self.environment])
            with package.open("rb") as stream:
                command([*ssh, remote_command], stdin=stream, capture=False)


def verify_image_archive(path, reference, expected, identity):
    with tarfile.open(path, "r:") as archive:
        manifest = json.load(archive.extractfile("manifest.json"))
        require(
            len(manifest) == 1 and manifest[0].get("RepoTags") == [reference],
            "Image archive must contain exactly the selected tag",
        )
        config_bytes = archive.extractfile(manifest[0]["Config"]).read()
        require(
            "sha256:" + hashlib.sha256(config_bytes).hexdigest() == expected,
            "Image archive config digest mismatch",
        )
        config = json.loads(config_bytes)
        labels = config.get("config", {}).get("Labels") or {}
        require(
            labels.get(PROJECT_LABEL) == identity["project"]
            and labels.get(ENV_LABEL) == identity["environment"],
            "Archive ownership mismatch",
        )


def safe_extract(path, destination, environment):
    allowed = set(package_paths(environment)) | {
        "image.tar",
        "release-image",
        "release-image-id",
        "release-manifest.json",
        f".env.{environment}",
    }
    with tarfile.open(path, "r:gz") as archive:
        seen, total = set(), 0
        for member in archive.getmembers():
            require(
                member.isfile() and member.name in allowed and member.name not in seen,
                "Release contains invalid, duplicate, symlink or unexpected entries",
            )
            seen.add(member.name)
            total += member.size
            require(total <= 8 * 1024**3, "Release exceeds size limit")
        require(seen == allowed, "Release package is incomplete")
        for member in archive.getmembers():
            target = destination / member.name
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.extractfile(member) as stream, target.open("wb") as output:
                shutil.copyfileobj(stream, output)
            os.chmod(target, 0o700 if target.suffix == ".sh" else 0o600)
    manifest = json.loads((destination / "release-manifest.json").read_text())
    require(
        set(manifest) == allowed - {"release-manifest.json"}, "Invalid release checksum manifest"
    )
    for name, expected in manifest.items():
        require(digest_file(destination / name) == expected, "Release checksum mismatch")


def receive_release(package, root, environment):
    root = Path(root)
    private_dir(root)
    with tempfile.TemporaryDirectory(prefix=".incoming-", dir=root) as temporary:
        stage = Path(temporary)
        safe_extract(package, stage, environment)
        incoming = Deployment(stage, environment)
        with Lock(root / ".deploy" / environment / "lock"):
            reference = (stage / "release-image").read_text().strip()
            expected = (stage / "release-image-id").read_text().strip()
            verify_image_archive(stage / "image.tar", reference, expected, incoming.identity)
            existing = incoming.image_info(reference, required=False)
            require(
                not existing or existing["Id"] == expected,
                "Existing image tag has different content",
            )
            current_config = root / f".env.{environment}"
            if current_config.exists():
                current = Deployment(root, environment)
                require(
                    current.project == incoming.project, "Installation belongs to another project"
                )
                require(
                    not current.ref("pending-image"),
                    "Interrupted transaction exists; recover before transferring an update",
                )
            for name in package_paths(environment) + [
                "release-image",
                "release-image-id",
                "release-manifest.json",
                f".env.{environment}",
            ]:
                target = root / name
                require(
                    not any(p.is_symlink() for p in [target, *target.parents]),
                    "Refusing installed symlink",
                )
                private_dir(target.parent)
                temporary_target = target.with_name("." + target.name + ".new")
                require(not temporary_target.exists(), "Incomplete previous file transfer")
                shutil.copyfile(stage / name, temporary_target)
                os.chmod(temporary_target, 0o700 if target.suffix == ".sh" else 0o600)
                os.replace(temporary_target, target)
            os.replace(stage / "image.tar", root / "image.tar")
            installed = Deployment(root, environment)
            installed.requirements()
            installed.install()


def isolation(root, production_config=None, demo_config=None, image=None, build=False):
    production = Deployment(root, "production", production_config)
    demo = Deployment(root, "demo", demo_config)
    require(production.project == demo.project, "Isolation test requires the same project")
    require(
        production.config["HOST_PORT"] != demo.config["HOST_PORT"]
        and production.config["PUBLIC_ORIGIN"] != demo.config["PUBLIC_ORIGIN"],
        "Environment endpoints overlap",
    )
    with production.locked(), demo.locked():
        before = production.verify()
        reference = demo.build() if build else image or demo.ref("built-image")
        demo.deploy(reference)
        after = production.verify()
        require(
            (before["Id"], before["State"]["StartedAt"], before["RestartCount"])
            == (after["Id"], after["State"]["StartedAt"], after["RestartCount"]),
            "Production was restarted during demo deployment",
        )
        demo_container = demo.verify()
        require(
            set(before["NetworkSettings"]["Networks"]).isdisjoint(
                demo_container["NetworkSettings"]["Networks"]
            ),
            "Networks overlap",
        )
        print("Isolation verified: production container unchanged; both environments functional")


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("command", choices=ACTIONS)
    result.add_argument("--env", required=True, choices=ENVIRONMENTS)
    result.add_argument("--config")
    result.add_argument("--image")
    result.add_argument("--output")
    result.add_argument("--action", choices=REMOTE_ACTIONS)
    result.add_argument("--build", action="store_true")
    result.add_argument("--production-config")
    return result


def main(argv=None, root=ROOT):
    os.umask(0o077)
    operator_python()
    args = parser().parse_args(argv)
    require(
        not args.build or args.command in ("local", "remote"),
        "--build is only valid for local or remote",
    )
    require(not args.build or not args.image, "--build cannot be combined with --image")
    require(not args.action or args.command == "remote", "--action is only valid for remote")
    require(
        not args.build or args.action in (None, "deploy"),
        "--build requires the remote deploy action",
    )
    require(not args.output or args.command == "package", "--output is only valid for package")
    require(
        not args.image or args.command in ("local", "remote", "package", "verify", "isolation"),
        "--image is not supported for this action",
    )
    require(
        not args.image or not args.action or args.action == "deploy",
        "Remote operational actions do not accept an image",
    )
    require(
        not args.production_config or args.command == "isolation",
        "--production-config is only valid for isolation",
    )
    if args.command == "isolation":
        require(args.env == "demo", "Isolation action must target demo")
        isolation(root, args.production_config, args.config, args.image)
        return
    deploy = Deployment(root, args.env, args.config)
    # Remote operational actions only require SSH and Python locally, not Docker.
    if args.command == "remote" and args.action not in (None, "deploy"):
        deploy.remote(args.action)
        return
    deploy.requirements(remote=args.command == "remote")
    lock = deploy.locked() if args.command not in ("status", "logs") else contextlib.nullcontext()
    with lock:
        reference = deploy.build() if args.build else args.image
        if args.command == "build":
            deploy.build()
        elif args.command == "package":
            deploy.package(reference, args.output)
        elif args.command == "local":
            deploy.deploy(reference or deploy.ref("built-image"))
        elif args.command == "remote":
            deploy.remote(args.action or "deploy", reference)
        elif args.command == "install":
            deploy.install()
        elif args.command == "verify":
            deploy.verify(reference)
        elif args.command == "rollback":
            deploy.rollback()
        elif args.command == "cleanup":
            deploy.cleanup()
        elif args.command == "status":
            deploy.status()
        elif args.command == "logs":
            deploy.logs()


if __name__ == "__main__":
    try:
        main()
    except (Failure, OSError, ValueError, KeyError, tarfile.TarError) as error:
        print(f"Deployment error: {error}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("Interrupted; inspect lock/pending state before retrying.", file=sys.stderr)
        sys.exit(130)
