# License and dependency audit

## Engine and wrapper

The exact PyPI sdist for PySwissEph 2.10.3.2 and its SHA-256 are recorded in
`pyswisseph-source.json`. Its `pyswisseph.c` explicitly grants AGPL version 3 or
later: **AGPL-3.0-or-later**, preserved verbatim in `PYSWISSEPH-NOTICE.txt`.
The bundled C library reports `2.10.03`; its original license and headers specify
the AGPL option or a separate professional license, linking to AGPL version 3.
We select version 3, with no unsupported claim of an “or later” Swiss grant.
The server's own SPDX expression is **AGPL-3.0-only**, compatible with selecting
version 3 under the wrapper's grant. `LICENSE` contains the complete AGPL v3 text.

Sources: [PyPI release](https://pypi.org/project/pyswisseph/2.10.3.2/),
[wrapper upstream](https://github.com/astrorigin/pyswisseph),
[Swiss license terms](https://www.astro.com/swisseph/swephprg.htm),
[AGPL v3](https://www.gnu.org/licenses/agpl-3.0.html).

## Astronomical data

Only `sepl_18.se1` and `semo_18.se1` are used. They are fetched from
`aloistr/swisseph` revision `94621aba9f3ff9c32cb721eac0380c30dbb153fe` with hashes
and byte sizes in `data/ephemeris-manifest.json`. Their original binary headers
identify data generated 2026-05-26 based on JPL DE441. These are **not** assumed
to be DE431 merely because that description appears in PySwissEph's metadata.

The upstream repository's license notice is preserved verbatim in
`data-upstream-LICENSE.txt`. A separate, explicit file-specific grant for these
two generated binary data files was not established in this inspection. Do not
infer public-domain status from NASA/JPL ancestry. Confirm that the upstream AGPL
option covers redistribution and network use of these exact compressed files,
and whether additional attribution or notices are required. Until resolved,
keep this component private and `CARTA_LICENSE_REVIEW_APPROVED=false`.
Local downloads and tests do not establish public licensing clearance.

No asteroid, star catalog, GeoNames dataset, timezone database, or historical
civil-time dataset is redistributed by the server.

## Dependency scope and compatibility

`uv.lock` fixes full resolution and artifact hashes; `requirements.lock` fixes
runtime packages with hashes. The direct latest versions were checked via PyPI.
`dependencies.json` retains license notices for 35 installed project/runtime
distributions, including indirect native dependencies at the Python-package level.
MIT, BSD, Apache-2.0, PSF and the documented AGPL grants present no identified
incompatibility in this inventory. Keep certifi's MPL-2.0 code and notices intact;
its source distribution is retained. Final legal review must consider the actual
combined distribution and native components, not only metadata names.

The runtime vulnerability scan (`pip-audit` 2.10.1, pinned requirements, PyPI
advisory service) examined 34 external dependencies and found no known
vulnerabilities on this date. Results: `vulnerability-audit.json`. This does not
prove absence of vulnerabilities, and excludes OS packages and the standalone
reference CLI. Refresh the audit for each release.

The corporate Angular lockfile was inspected read-only. Declared licenses include
MIT, Apache-2.0, BSD, ISC, BlueOak-1.0.0, Python-2.0 and CC variants; two packages
use `SEE LICENSE IN LICENSE`, and one offers BSD-3-Clause OR GPL-2.0. No blanket
compatibility conclusion is made for that private application or its assets.
It is **not linked, copied or bundled** into this AGPL service.

## Source offer and release obligations

`scripts/build_source.py` assembles original source, models, tests, deployment
files, lockfiles, licenses and upstream runtime sdists in a deterministic archive.
`SOURCE-MANIFEST.json` records file hashes. `/source.tar.gz` serves this exact local
artifact; `/source` exposes the revision, license and download location.
Before activation, verify the public source download without authentication,
retain each deployed image digest and matching source artifact, and publish the
independent Smart Studio repository. Do not serve a moving `main` branch as the
only source offer for an older deployment.

Production startup fails unless the operator explicitly records completed legal
review, provides a source archive/HTTPS URL, a release revision and a metrics
token, and uses explicit Host/Origin lists. This is a fail-closed release control,
not an automatic license validator. The remaining image-level/native and data
reviews must actually be performed before setting the approval flag.
