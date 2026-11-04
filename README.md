# Smart Studio Astrology MCP

Servidor independiente de **Carta y Arcano**, creado por Victor Silva (Smart Studio).
AGPL-3.0-only. Cálculos numéricos con Swiss Ephemeris, sin LLM ni historial natal.

**Estado:** implementación local y configuración de despliegue. Publicación del
repositorio, DNS/TLS, despliegue y conexión ChatGPT pendientes de las indicaciones
del titular.
La activación pública está bloqueada también por la revisión de datos descrita
en [la auditoría](legal/AUDIT.md).

## Convención temporal obligatoria


Toda carta incluye `calculation_mode=literal_no_timezone`,
`time_reference=supplied_clock_used_as_ut` y
`precision_status=civil_time_not_utc_verified`. “Hora exacta” describe el dato del
usuario; no cambia esta advertencia. Sin hora se utiliza mediodía declarado,
se muestran muestras cada 30 minutos y se omiten casas, ángulos y aspectos natales.

## Instalación y ejecución

Python 3.11+, compilador C para PySwissEph cuando no haya wheel. Entorno probado:
Python 3.12.16; versión del SDK MCP 2.3.0, wrapper 2.10.3.2, motor 2.10.03.

```bash
python3 -m pip install uv==0.13.7
uv sync --frozen --python 3.12
uv run python scripts/fetch_ephemeris.py
uv run uvicorn smartstudio_mcp.server:create_app --factory --host 127.0.0.1 --port 8000 --no-access-log --no-proxy-headers
```

El script verifica hashes y no cambia de datos. Fechas admitidas: 1800-01-02–2399-12-31,
calendario gregoriano, longitudes planetarias geocéntricas tropicales aparentes
en grados de fecha, `FLG_SWIEPH | FLG_SPEED`. Se usa `calc_ut`; su conversión
interna UT→TT mediante ΔT pertenece al cálculo astronómico, no a una conversión
de hora civil ni de zona horaria. No hay fallback a Moshier/JPL u otro sistema.

```bash
uv run pytest -q
uv run ruff check src tests scripts
uv run ruff format --check src tests scripts
uv run python scripts/export_schemas.py --check
uv run python scripts/smoke_mcp.py http://127.0.0.1:8000/mcp
```

## Herramientas

Todas reciben `{"request": {...}}` y devuelven un resultado Pydantic estructurado.

| Herramienta | Modelo de entrada | Operación |
|---|---|---|
| `resolve_birthplace` | `PlaceInput` | Localidad→candidatos/coordenadas; nunca desambigua silenciosamente |
| `calculate_natal_chart` | `NatalInput` | Planetas, nodos, ángulos, casas, aspectos e incertidumbre |
| `calculate_transits` | `ReferenceInput` | Planetas y aspectos mutuos de la referencia literal |
| `calculate_aspects` | `AspectInput` | Separaciones deterministas y orbes configurables |
| `get_ephemeris` | `ReferenceInput` | Posiciones y procedencia del motor y datos |

Esquemas completos: [tool-schemas.json](docs/tool-schemas.json).
Ejemplos y errores: [contrato API](docs/API.md). `success=false` nunca devuelve
valores astronómicos parciales. Entradas inválidas se rechazan por el protocolo
MCP antes de ejecutar la herramienta.

## Arquitectura y operación

SDK MCP oficial → validación Pydantic → servicio asíncrono → ejecutor de un hilo
para Swiss Ephemeris. Las llamadas se serializan para proteger el estado nativo.
ASGI/Uvicorn sirve Streamable HTTP sin sesiones y con respuestas JSON.
Un proxy HTTPS independiente termina TLS.

Sin coordenadas, configure un proveedor autorizado Nominatim; de lo contrario se
devuelve `GEOCODER_NOT_CONFIGURED`. El adaptador consulta solo ciudad/país/región,
limita frecuencia, tiempo y tamaño, no sigue redirects y no almacena consultas.
Se bloquea el endpoint público de OSMF. Para usar un proveedor propio, revise
su contrato y configure `CARTA_GEOCODER=nominatim` y `CARTA_GEOCODER_URL`.

Variables en [.env.example](.env.example), despliegue/rollback en
[DEPLOYMENT.md](docs/DEPLOYMENT.md), privacidad en [PRIVACY.md](docs/PRIVACY.md), evidencia en [VERIFICATION.md](docs/VERIFICATION.md).

## Licencias y fuente correspondiente

Consulte [LICENSE](LICENSE), [NOTICE](NOTICE), [avisos de terceros](legal/THIRD-PARTY.md)
y [auditoría](legal/AUDIT.md). El servidor publica `/license`, `/notice`, `/source`
y `/source.tar.gz`. Para construir la oferta de código:

```bash
uv run python scripts/build_source.py
docker build -f docker/Dockerfile -t smartstudio-astrology-mcp:demo-manual .
```

No active producción hasta resolver los bloqueos documentados. El nombre
propuesto del repositorio público es `smartstudio-astrology-mcp`; la organización
y la URL pública aún no están configuradas.

## Despliegue sin registro

La CLI `scripts/deploy.sh` prepara imágenes distintas para producción y demo,
las transporta por SSH y confirma o recupera tras comprobar MCP. Consulte
[instalación, configuración, aislamiento y recuperación](docs/deployment/README.md).
Ejemplos privados: `.env.production.example` y `.env.demo.example`.
No se ha ejecutado un despliegue remoto ni se ha autorizado aún activación pública.
