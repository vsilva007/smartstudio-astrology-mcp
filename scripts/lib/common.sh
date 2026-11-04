#!/usr/bin/env bash
set -euo pipefail
umask 077
DEPLOY_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)"
run_deploy() {
    command -v python3 >/dev/null || { echo 'Python 3 is required' >&2; exit 1; }
    exec python3 "$DEPLOY_ROOT/scripts/lib/common.py" "$@"
}
