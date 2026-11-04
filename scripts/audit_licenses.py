import json
import pathlib
import subprocess
import sys
import tomllib

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
output = subprocess.check_output(
    [
        sys.executable,
        "-m",
        "piplicenses",
        "--format=json",
        "--with-urls",
        "--with-license-file",
        "--no-license-path",
    ]
)
rows = json.loads(output)


def normalize(value):
    return value.lower().replace("_", "-").replace(".", "-")


selected = [row for row in rows if normalize(row["Name"]) in runtime]
missing = runtime - {normalize(row["Name"]) for row in selected}
if missing:
    raise SystemExit(f"Uninspected runtime dependencies: {sorted(missing)}")
unknown = [
    row["Name"]
    for row in selected
    if row["License"] == "UNKNOWN" or row.get("LicenseText", "UNKNOWN") == "UNKNOWN"
]
(root / "legal/dependencies.json").write_text(
    json.dumps(selected, indent=2, ensure_ascii=False) + "\n"
)
if unknown:
    raise SystemExit(f"Unconfirmed licenses or missing notices: {unknown}")
print(f"Collected {len(selected)} runtime license notices; legal compatibility review is separate.")
