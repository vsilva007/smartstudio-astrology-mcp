#!/usr/bin/env bash
set -euo pipefail
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)/common.sh"
python3 - "$DEPLOY_ROOT" <<'PY'
import importlib.util, pathlib, sys
root = pathlib.Path(sys.argv[1])
spec = importlib.util.spec_from_file_location('deployment', root / 'scripts/lib/common.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
try:
    print(module.build_python(root))
except module.Failure as error:
    sys.exit(str(error))
PY
