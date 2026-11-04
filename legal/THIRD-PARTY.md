# Third-party notices

The service's original code is **AGPL-3.0-only**. Dependencies retain their own
licenses; this notice does not relicense third-party code.

| Component | Exact selected version | License / evidence |
|---|---|---|
| PySwissEph | 2.10.3.2 | AGPL-3.0-or-later; original C header in PYSWISSEPH-NOTICE.txt |
| Swiss Ephemeris bundled C | 2.10.03 | AGPL v3 option of dual license; original SWISSEPH-LICENSE.txt |
| Official MCP SDK / mcp-types | 2.3.0 | MIT |
| Pydantic | 2.14.2 | MIT |
| pydantic-settings | 2.16.2 | MIT |
| Uvicorn | 0.54.0 | BSD-3-Clause |
| HTTPX | 0.28.1 | BSD-3-Clause |
| certifi trust store | 2026.10.23 | MPL-2.0; preserve its file notices and source |

`dependencies.json` contains the complete runtime inventory and original texts
collected from installed distributions, including indirect dependencies. It covers
Linux/macOS runtime resolution; Windows and WebAssembly are not deployment targets.
The release source archive includes SHA-256-verified source distributions of these
dependencies, including PySwissEph's bundled C sources and original notices.

Geocoding is disabled by default. The Nominatim adapter labels responses
`© OpenStreetMap contributors (ODbL)`; display this attribution when using that
data. Review the chosen host's terms and [OSM copyright](https://www.openstreetmap.org/copyright).
No geographic database is bundled or persisted. The public OSMF endpoint is explicitly
blocked; configure an authorized or self-hosted instance. See the
[Nominatim usage policy](https://operations.osmfoundation.org/policies/nominatim/).

Container base components retain Debian, Python and bundled system-library licenses.
Before distributing production images, inventory the final image, retain
`/usr/share/doc/*/copyright`, and review native wheel dependencies; the Python audit
does not constitute an OS/container SBOM or a legal opinion.
