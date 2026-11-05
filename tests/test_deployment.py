import hashlib
import importlib.util
import io
import json
import os
import subprocess
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("deployment", ROOT / "scripts/lib/common.py")
deployment = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deployment)


def config_file(root, env="demo", **changes):
    values = dict(
        deployment.DEFAULTS,
        PROJECT_NAME="carta-test",
        PUBLIC_ORIGIN="http://127.0.0.1:" + ("4200" if env == "demo" else "4100"),
        CANONICAL_ORIGIN="http://127.0.0.1:" + ("4200" if env == "demo" else "4100"),
        HOST_PORT="4200" if env == "demo" else "4100",
        LOCAL_TEST_ONLY="true",
    )
    values.update(changes)
    path = root / f".env.{env}"
    path.write_text("".join(k + "=" + v + "\n" for k, v in values.items()))
    path.chmod(0o600)
    return path


def test_config_read_as_data(tmp_path):
    path = config_file(tmp_path, MEMORY_LIMIT="1g")
    config = deployment.parse_config(path, "demo")
    assert config["HOST_PORT"] == "4200" and config["MEMORY_LIMIT"] == "1g"


@pytest.mark.parametrize(
    "line",
    [
        "UNKNOWN=value",
        "HOST_PORT=$(touch /tmp/must-not-execute)",
        'HOST_PORT="4200"',
        "METRICS_TOKEN=`whoami`",
        "HOST_PORT=65536",
        "HOST_PORT=-1",
        "CONTAINER_PORT=4000",
        "TRUST_PROXY=true",
        "PROJECT_NAME=../other",
        "PUBLIC_ORIGIN=https://user:pass@example.com",
        "BUILD_PLATFORM=linux/riscv64",
        "REMOTE_HOST=-oProxyCommand=evil",
        "REMOTE_PATH=/srv/../tmp",
        "GEOCODER=nominatim",
        "LOCAL_TEST_ONLY=TRUE",
    ],
)
def test_bad_config_rejected(tmp_path, line):
    path = config_file(tmp_path)
    key = line.split("=")[0]
    lines = [v for v in path.read_text().splitlines() if not v.startswith(key + "=")]
    path.write_text("\n".join(lines + [line]) + "\n")
    with pytest.raises(deployment.Failure):
        deployment.parse_config(path, "demo")


def test_duplicate_and_world_readable_config(tmp_path):
    path = config_file(tmp_path)
    path.write_text(path.read_text() + "HOST_PORT=4200\n")
    with pytest.raises(deployment.Failure, match="duplicate"):
        deployment.parse_config(path, "demo")
    path = config_file(tmp_path)
    path.chmod(0o644)
    with pytest.raises(deployment.Failure, match="private"):
        deployment.parse_config(path, "demo")


def test_explicit_config_symlink_rejected(tmp_path):
    path = config_file(tmp_path)
    link = tmp_path / "alias.env"
    link.symlink_to(path)
    with pytest.raises(deployment.Failure, match="symlink"):
        deployment.Deployment(tmp_path, "demo", link)


def test_lock_is_exclusive_and_not_auto_removed(tmp_path):
    path = tmp_path / "lock"
    with deployment.Lock(path):
        with pytest.raises(deployment.Failure, match="locked"):
            with deployment.Lock(path):
                pass
        assert json.loads((path / "owner.json").read_text())["pid"] == os.getpid()
    assert not path.exists()
    path.mkdir()
    with pytest.raises(deployment.Failure):
        with deployment.Lock(path):
            pass
    assert path.exists()


def test_atomic_private_writes_do_not_chmod_parent(tmp_path):
    tmp_path.chmod(0o755)
    deployment.atomic(tmp_path / "state", "ready")
    assert (tmp_path / "state").read_text() == "ready"
    assert (tmp_path / "state").stat().st_mode & 0o777 == 0o600
    assert tmp_path.stat().st_mode & 0o777 == 0o755


@pytest.mark.parametrize(
    "args",
    [
        ["build"],
        ["build", "--env", "staging"],
        ["package", "--env", "demo", "--build"],
        ["local", "--env", "demo", "--build", "--image", "x"],
        ["remote", "--env", "demo", "--build", "--action", "rollback"],
        ["local", "--env", "demo", "--action", "logs"],
        ["build", "--env", "demo", "--output", "/tmp/x"],
        ["remote", "--env", "demo", "--image", "x", "--action", "logs"],
    ],
)
def test_invalid_cli_never_calls_docker(args, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Invalid CLI executed a subprocess")

    monkeypatch.setattr(deployment, "command", forbidden)
    with pytest.raises((deployment.Failure, SystemExit)):
        deployment.main(args)


def test_entrypoint_works_outside_checkout(tmp_path):
    result = subprocess.run(
        ["bash", ROOT / "scripts/deploy.sh", "--help"], cwd=tmp_path, capture_output=True, text=True
    )
    assert result.returncode == 0 and "--env" in result.stdout
    result = subprocess.run(
        ["bash", ROOT / "scripts/deploy/rollback.sh", "--help"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0


class Simulation(deployment.Deployment):
    def __init__(self, root):
        super().__init__(root, "demo")
        self.running = "carta-test:demo-old"
        self.bad = set()
        self.calls = []

    def check_activation(self):
        pass

    def validate_image(self, ref):
        deployment.require(ref, "Missing image")
        return {"Id": ref}

    def active_image(self):
        return self.running

    def compose(self, ref, *args, **kwargs):
        self.calls.append((ref, args))
        if args[0] == "up":
            self.running = ref
        elif args[0] == "stop":
            self.running = ""

    def verify(self, ref=None):
        self.calls.append(("verify", ref))
        if ref in self.bad:
            raise deployment.Failure("Functional check failed")

    def logs(self, failure=False):
        self.save("failure.log", "sanitized failure")


def test_success_commits_only_after_verification(tmp_path):
    config_file(tmp_path)
    app = Simulation(tmp_path)
    app.save("current-image", app.running)
    app.deploy("carta-test:demo-new")
    assert app.ref("current-image") == "carta-test:demo-new"
    assert app.ref("previous-image") == "carta-test:demo-old"
    assert not app.ref("pending-image")
    app.rollback()
    assert app.ref("current-image") == "carta-test:demo-old"
    assert app.ref("previous-image") == "carta-test:demo-new"
    app.rollback()
    assert app.ref("current-image") == "carta-test:demo-new"


def test_failed_upgrade_recovers_previous_and_preserves_history(tmp_path):
    config_file(tmp_path)
    app = Simulation(tmp_path)
    app.save("current-image", app.running)
    app.save("previous-image", "carta-test:demo-older")
    app.bad.add("carta-test:demo-bad")
    with pytest.raises(deployment.Failure):
        app.deploy("carta-test:demo-bad")
    assert app.running == app.ref("current-image") == "carta-test:demo-old"
    assert app.ref("previous-image") == "carta-test:demo-older"
    assert not app.ref("pending-image") and (app.state / "failure.log").exists()


def test_failed_recovery_retains_pending_refs(tmp_path):
    config_file(tmp_path)
    app = Simulation(tmp_path)
    app.bad.update({"carta-test:demo-bad", app.running})
    with pytest.raises(deployment.Failure):
        app.deploy("carta-test:demo-bad")
    assert app.ref("pending-image") == "carta-test:demo-bad"
    assert app.ref("pending-previous") == "carta-test:demo-old"
    with pytest.raises(deployment.Failure, match="transaction"):
        app.deploy("carta-test:demo-other")


def test_first_install_failure_stops_container(tmp_path):
    config_file(tmp_path)
    app = Simulation(tmp_path)
    app.running = ""
    app.bad.add("carta-test:demo-bad")
    with pytest.raises(deployment.Failure):
        app.deploy("carta-test:demo-bad")
    assert not app.running and not app.ref("current-image")


def test_build_failure_cannot_deploy(tmp_path, monkeypatch):
    config_file(tmp_path)
    monkeypatch.setattr(deployment.Deployment, "requirements", lambda *a, **k: None)

    def failed(_):
        raise deployment.Failure("Build failed")

    monkeypatch.setattr(deployment.Deployment, "build", failed)
    monkeypatch.setattr(
        deployment.Deployment, "deploy", lambda *a: pytest.fail("Deployment after failed build")
    )
    with pytest.raises(deployment.Failure, match="Build failed"):
        deployment.main(["local", "--env", "demo", "--build"], root=tmp_path)


@pytest.mark.parametrize("version", ["2.38.2", "v5.1.3"])
def test_required_compose_major_reports_installed_version(tmp_path, monkeypatch, version):
    config_file(tmp_path)
    app = deployment.Deployment(tmp_path, "demo")
    monkeypatch.setattr(deployment.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(
        deployment,
        "command",
        lambda args: subprocess.CompletedProcess(
            args,
            0,
            version + "\n" if args == ["docker", "compose", "version", "--short"] else "",
            "",
        ),
    )
    if version.startswith("v5"):
        with pytest.raises(deployment.Failure, match=r"detected 5\.1\.3"):
            app.requirements()
    else:
        app.requirements()


def test_compose_ignores_ambient_dotenv_and_variables(tmp_path, monkeypatch):
    config_file(tmp_path)
    app = deployment.Deployment(tmp_path, "demo")
    monkeypatch.setenv("COMPOSE_FILE", "/tmp/evil.yaml")
    monkeypatch.setenv("CARTA_GEOCODER", "nominatim")
    monkeypatch.setenv("HOST_PORT", "9999")
    monkeypatch.setattr(
        app, "validate_image", lambda _: {"Config": {"Labels": {deployment.REV_LABEL: "abc"}}}
    )
    calls = []
    monkeypatch.setattr(deployment, "command", lambda args, **kw: calls.append((args, kw)))
    app.compose("carta-test:demo-one", "config", "--quiet")
    args, kw = calls[0]
    assert args[args.index("--env-file") + 1] == "/dev/null"
    assert args[args.index("-p") + 1] == "carta-test-demo"
    assert "COMPOSE_FILE" not in kw["env"] and "CARTA_GEOCODER" not in kw["env"]
    assert kw["env"]["HOST_PORT"] == "4200"


def test_reject_sibling_port_and_origin_collision(tmp_path):
    config_file(tmp_path, "production")
    config_file(
        tmp_path,
        HOST_PORT="4100",
        PUBLIC_ORIGIN="http://127.0.0.1:4100",
        CANONICAL_ORIGIN="http://127.0.0.1:4100",
    )
    with pytest.raises(deployment.Failure, match="ports"):
        deployment.Deployment(tmp_path, "demo")


def test_remote_uses_strict_ssh_and_no_transfer_for_operations(tmp_path, monkeypatch):
    config_file(
        tmp_path,
        LOCAL_TEST_ONLY="false",
        PUBLIC_ORIGIN="https://demo.example.org",
        CANONICAL_ORIGIN="https://demo.example.org",
        REMOTE_HOST="ops@example.org",
    )
    calls = []
    monkeypatch.setattr(deployment, "command", lambda args, **kw: calls.append(args))
    deployment.Deployment(tmp_path, "demo").remote("rollback")
    assert len(calls) == 1
    assert "BatchMode=yes" in calls[0] and "StrictHostKeyChecking=yes" in calls[0]
    assert "/srv/smartstudio-astrology-mcp/demo/scripts/deploy.sh" in calls[0][-1]
    assert "rollback" in calls[0][-1]


def test_local_only_config_cannot_be_sent_remote(tmp_path):
    config_file(tmp_path, REMOTE_HOST="ops@example.org")
    with pytest.raises(deployment.Failure, match="Local-only"):
        deployment.Deployment(tmp_path, "demo").remote("deploy")


def test_existing_tag_id_mismatch_rejected_before_load(tmp_path, monkeypatch):
    config_file(tmp_path)
    (tmp_path / "release-image").write_text("carta-test:demo-one")
    (tmp_path / "release-image-id").write_text("sha256:" + "a" * 64)
    app = deployment.Deployment(tmp_path, "demo")
    monkeypatch.setattr(app, "image_info", lambda *a, **k: {"Id": "sha256:" + "b" * 64})
    monkeypatch.setattr(
        deployment, "command", lambda *a, **k: pytest.fail("Loading conflicting tag")
    )
    with pytest.raises(deployment.Failure, match="different content"):
        app.install()


def test_receiver_rejects_collision_before_replacing_configuration(tmp_path, monkeypatch):
    root = tmp_path / "installed"
    root.mkdir()
    config = config_file(root)
    original = config.read_bytes()

    def extract(package, destination, environment):
        config_file(destination, RATE_PER_MINUTE="100")
        (destination / "release-image").write_text("carta-test:demo-one")
        (destination / "release-image-id").write_text("sha256:" + "a" * 64)

    monkeypatch.setattr(deployment, "safe_extract", extract)
    monkeypatch.setattr(deployment, "verify_image_archive", lambda *a: None)
    monkeypatch.setattr(
        deployment.Deployment, "image_info", lambda *a, **kw: {"Id": "sha256:" + "b" * 64}
    )
    with pytest.raises(deployment.Failure, match="different content"):
        deployment.receive_release(tmp_path / "release.tar.gz", root, "demo")
    assert config.read_bytes() == original
    assert not (root / "scripts").exists()
    assert not (root / ".deploy/demo/lock").exists()


@pytest.mark.parametrize(
    "name,link", [("../outside", False), ("/absolute", False), ("image.tar", True)]
)
def test_unsafe_release_archives_rejected(tmp_path, name, link):
    path = tmp_path / "release.tar.gz"
    with tarfile.open(path, "w:gz") as archive:
        member = tarfile.TarInfo(name)
        if link:
            member.type = tarfile.SYMTYPE
            member.linkname = "/etc/passwd"
        archive.addfile(member, io.BytesIO())
    with pytest.raises(deployment.Failure):
        deployment.safe_extract(path, tmp_path / "unpacked", "demo")


@pytest.mark.parametrize("corrupt", [False, True])
def test_release_checksums_and_private_extraction(tmp_path, corrupt):
    config = config_file(tmp_path)
    files = {name: b"fixture" for name in deployment.package_paths("demo")}
    files.update(
        {
            "image.tar": b"image fixture",
            "release-image": b"carta-test:demo-one",
            "release-image-id": b"sha256:" + b"a" * 64,
            ".env.demo": config.read_bytes(),
        }
    )
    manifest = {name: hashlib.sha256(value).hexdigest() for name, value in files.items()}
    files["release-manifest.json"] = json.dumps(manifest).encode()
    if corrupt:
        files["image.tar"] = b"modified after checksum"
    package = tmp_path / "release.tar.gz"
    with tarfile.open(package, "w:gz") as archive:
        for name, data in files.items():
            member = tarfile.TarInfo(name)
            member.size = len(data)
            archive.addfile(member, io.BytesIO(data))
    destination = tmp_path / "received"
    if corrupt:
        with pytest.raises(deployment.Failure, match="checksum"):
            deployment.safe_extract(package, destination, "demo")
    else:
        deployment.safe_extract(package, destination, "demo")
        assert (destination / ".env.demo").stat().st_mode & 0o777 == 0o600
        assert (destination / "scripts/deploy.sh").stat().st_mode & 0o777 == 0o700
        assert not (destination / "docker/Dockerfile").exists()


def test_image_archive_labels_and_content_digest(tmp_path):
    config = json.dumps(
        {
            "config": {
                "Labels": {deployment.PROJECT_LABEL: "carta-test", deployment.ENV_LABEL: "demo"}
            }
        }
    ).encode()
    expected = "sha256:" + hashlib.sha256(config).hexdigest()
    image = tmp_path / "image.tar"
    with tarfile.open(image, "w") as archive:
        for name, data in [
            (
                "manifest.json",
                json.dumps(
                    [{"RepoTags": ["carta-test:demo-one"], "Config": "config.json"}]
                ).encode(),
            ),
            ("config.json", config),
        ]:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    deployment.verify_image_archive(
        image, "carta-test:demo-one", expected, {"project": "carta-test", "environment": "demo"}
    )
    with pytest.raises(deployment.Failure):
        deployment.verify_image_archive(
            image,
            "carta-test:demo-one",
            "sha256:" + "b" * 64,
            {"project": "carta-test", "environment": "demo"},
        )


def test_cleanup_protects_state_and_foreign_container_images(tmp_path, monkeypatch):
    config_file(tmp_path)
    app = deployment.Deployment(tmp_path, "demo")
    protected = []
    for name in deployment.STATE_REFS:
        ref = "carta-test:demo-" + name
        app.save(name, ref)
        protected.append(ref)
    in_use, stale = "carta-test:demo-shared", "carta-test:demo-unused"
    calls = []

    def command(args, **kwargs):
        calls.append(args)
        if args[:3] == ["docker", "ps", "-aq"]:
            value = "foreign-container"
        elif args[:2] == ["docker", "inspect"]:
            value = json.dumps(
                [
                    {
                        "Id": "foreign-container",
                        "Image": in_use,
                        "Config": {"Image": in_use, "Labels": {}},
                        "State": {"Running": False},
                    }
                ]
            )
        elif args[:3] == ["docker", "image", "ls"]:
            value = "\n".join(protected + [in_use, stale])
        else:
            value = ""
        return subprocess.CompletedProcess(args, 0, value, "")

    monkeypatch.setattr(deployment, "command", command)
    monkeypatch.setattr(app, "image_info", lambda ref, **kw: {"Id": ref})
    monkeypatch.setattr(app, "validate_image", lambda ref: {"Id": ref})
    app.cleanup()
    assert [c for c in calls if c[:3] == ["docker", "image", "rm"]] == [
        ["docker", "image", "rm", stale]
    ]
    assert not any(c[:3] == ["docker", "container", "rm"] for c in calls)


@pytest.mark.parametrize("restarted", [False, True])
def test_isolation_detects_production_restart(tmp_path, monkeypatch, restarted):
    config_file(tmp_path, "production")
    config_file(tmp_path)
    production_checks = 0

    def verify(self, reference=None):
        nonlocal production_checks
        if self.environment == "production":
            production_checks += 1
        return {
            "Id": self.environment,
            "State": {
                "StartedAt": "changed" if restarted and production_checks == 2 else "original"
            },
            "RestartCount": 0,
            "NetworkSettings": {"Networks": {self.environment: {}}},
        }

    monkeypatch.setattr(deployment.Deployment, "verify", verify)
    monkeypatch.setattr(deployment.Deployment, "deploy", lambda self, ref: None)
    if restarted:
        with pytest.raises(deployment.Failure, match="restarted"):
            deployment.isolation(tmp_path, image="carta-test:demo-new")
    else:
        deployment.isolation(tmp_path, image="carta-test:demo-new")
