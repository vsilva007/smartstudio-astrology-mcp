# Despliegue independiente de Carta y Arcano

Flujo sin registro: checkout → validación Python → imagen Docker versionada →
paquete privado → SSH → `docker image load` → Compose → health/MCP → confirmación
(o recuperación). Demo y producción tienen imagen, proyecto Compose, red,
contenedor, configuración, puerto e historial propios. Hay una interrupción breve
al sustituir el contenedor; no se promete disponibilidad sin cortes.

## Adaptación al proyecto

Python **3.12.16**, fijado en `.python-version` y en `docker/Dockerfile`, con
imagen Debian slim fijada por digest. `scripts/lib/python.sh` sustituye al helper
Node: busca esa versión exacta ya instalada en `.venv312`, `.venv` o PATH, sin
instalar intérpretes ni alterar la terminal. El build crea su entorno de trabajo
privado `.deploy/build-venv`; instala `requirements-dev.lock` con hashes, compila
bytecode, verifica efemérides/esquemas y ejecuta pytest. El stage `build` repite
la compilación y un cálculo real dentro de Docker. No hay frontend ni npm.

Tres etapas Docker: `dependencies` instala los paquetes de ejecución con hashes;
`build` valida código y datos; `runtime` contiene Python/Uvicorn, el servidor,
las efemérides fijadas y la oferta de fuentes AGPL. Se elimina pip del runtime.
Usuario 1000:1000, raíz read-only, tmpfs 32 MiB noexec/nosuid, sin capacidades,
no-new-privileges, init, 128 PIDs, 768 MiB configurables, una CPU y logs rotados.
HEALTHCHECK `/healthz`: 15 s, timeout 3 s, start period 20 s, tres reintentos.
La verificación de despliegue comprueba además `/readyz` y cálculos MCP reales.

El puerto interno permanece **8000**. Producción publica `127.0.0.1:4100`, demo
`127.0.0.1:4200`. Compose usa `smartstudio-astrology-mcp-production` y
`smartstudio-astrology-mcp-demo`, con redes explícitas del mismo nombre más
`-network`. Servicio Compose: `mcp`. No se conecta a la red de la web corporativa.

El proxy HTTPS está fuera de los contenedores. Las plantillas en
`docs/deployment/apache.example.conf` y `deploy/Caddyfile` no se instalan ni
recargan automáticamente. DNS, certificados y dominio OpenAI se gestionan aparte.
El dominio demo propuesto `mcp-demo.smartstudio.dev` debe configurarse realmente.

## Requisitos y configuración privada

Desarrollo: Bash, Python 3.11+ para la CLI, Python 3.12.16 instalado para build,
Git, compilador C si PySwissEph lo requiere, Docker y Compose v2, curl, tar; SSH
para transferencias. El servidor remoto solo necesita Docker, Compose v2, Bash,
Python **3.11+**, curl y tar. No necesita Git, compiladores, Node, npm o el checkout.
Instalar las herramientas por el procedimiento de administración del host.

```bash
cp .env.production.example .env.production
cp .env.demo.example .env.demo
chmod 600 .env.production .env.demo
```

Archivos de datos `CLAVE=valor`: sin `export`, comillas, interpolaciones, escapes,
comandos, claves desconocidas o duplicadas. Los valores no se imprimen completos.
Se rechazan archivos compartidos con grupo/otros y symlinks. No se usa `source`
ni `eval` con configuración; los únicos `source` de Bash cargan código propio.
Compose siempre recibe `--env-file /dev/null`, ambos YAML y `-p` explícito;
se descartan variables ambientales `COMPOSE_*`, `CARTA_*` y claves de configuración.

| Variable | Tratamiento |
|---|---|
| PROJECT_NAME | Propietario de imágenes/contenedores/estado; minúsculas y guiones |
| PUBLIC_ORIGIN / CANONICAL_ORIGIN | Mismo origen HTTPS del entorno; demo distinto de producción |
| HOST_PORT | Puerto loopback del host; distinto por entorno |
| CONTAINER_PORT | 8000; no se acepta el 4000 del ejemplo Angular |
| TRUST_PROXY | Solo `false`; cabeceras de clientes no fiables no cambian la IP |
| MEMORY_LIMIT | Límite Docker con sufijo `m` o `g`, por defecto 768m |
| HEALTH_TIMEOUT | Espera máxima de salud, 5–900 s, por defecto 120 |
| BUILD_PLATFORM | `linux/amd64` o `linux/arm64`; requiere soporte de Docker para el destino |
| REMOTE_HOST / REMOTE_PORT | Alias SSH o user@host, puerto 22 por defecto |
| REMOTE_PATH | Raíz remota absoluta, p. ej. `/srv/smartstudio-astrology-mcp` |
| LICENSE_REVIEW_APPROVED | `false` hasta completar realmente `legal/AUDIT.md` |
| METRICS_TOKEN | Secreto de al menos 32 caracteres para despliegue público |
| OPENAI_CHALLENGE_TOKEN | Token exacto del portal, vacío mientras no exista |
| RATE_PER_MINUTE / GLOBAL_RATE_PER_MINUTE | Límites del servicio, 60/600 por defecto |
| GEOCODER / GEOCODER_URL | Desactivado por defecto; demo exige desactivado |
| LOCAL_TEST_ONLY | Solo pruebas privadas en HTTP 127.0.0.1 con puerto coincidente; nunca SSH ni proxy público |

No hay variables frontend incorporadas en compilación. Origen, tokens, límites
son de ejecución; cambiar Python, código, lockfiles, datos o etiquetas de
propiedad/entorno requiere una nueva imagen. No usar una imagen de demo para
producción. Las etiquetas validan proyecto, entorno, revisión y plataforma.

Para pruebas locales sin afirmar esa aprobación, `LOCAL_TEST_ONLY=true` exige
`PUBLIC_ORIGIN=CANONICAL_ORIGIN=http://127.0.0.1:<HOST_PORT>`. La CLI prohíbe enviar
esa configuración por SSH. No publicar ese puerto mediante un proxy o túnel;
esta opción solo acredita pruebas privadas y no declara el release público listo.

## Comandos

Se pueden ejecutar desde cualquier directorio usando la ruta al script. `--env`
es obligatorio. `--config` acepta un archivo privado alternativo. `--image`
selecciona una referencia local versionada; nunca se hace pull implícito.

```bash
./scripts/deploy.sh local --env demo --build
./scripts/deploy.sh remote --env production --build
./scripts/deploy.sh build --env demo
./scripts/deploy.sh package --env demo --output /tmp/release-demo.tar.gz
./scripts/deploy.sh install --env demo
./scripts/deploy.sh verify --env production
./scripts/deploy.sh remote --env production --action rollback
./scripts/deploy.sh remote --env demo --action logs
./scripts/deploy.sh cleanup --env demo
./scripts/deploy.sh status --env production
./scripts/deploy.sh logs --env demo
```

`--build` solo se admite con local/remote, sin `--image` y únicamente con la
acción remota deploy. Un fallo de validación/build no inicia despliegue. Los
builds de un mismo checkout se serializan además del bloqueo por entorno.
Etiquetas: `<proyecto>:<entorno>-<fechaUTC>-<commit>`. Cambios sin commit se marcan
`dirty-<hash>`; sin primer commit se usa `snapshot-<hash>` de la oferta de fuente.
No se usa `latest` ni se sobrescriben etiquetas. El ID Docker se verifica al cargar.
Para releases públicos, hacer commit/tag y conservar el paquete/hash originales.

## Paquetes y SSH

`package` utiliza `--image` o `built-image`. Produce un tar.gz modo 600 con
`image.tar`, referencia/ID, manifiesto SHA-256, scripts de operación, Compose común
y override del entorno, y la configuración seleccionada. **El paquete puede
contener tokens de ejecución: trátelo como secreto y no lo publiques como fuente.**
No incluye credenciales SSH, claves, checkout de desarrollo ni Dockerfile. El
código Python y la oferta AGPL sí están dentro de la imagen por necesidad del
servicio; la oferta pública no incluye los archivos privados de despliegue.

SSH usa BatchMode, StrictHostKeyChecking y la configuración/agente existentes.
Registrar previamente la huella del host por un canal fiable; no se acepta
`StrictHostKeyChecking=no`. El destino es `<REMOTE_PATH>/<entorno>`. No se modifica
`known_hosts` ni se generan/instalan claves. La cuenta requiere acceso Docker;
ese acceso tiene privilegios altos sobre el host y debe administrarse aparte.

El receptor recibe en un directorio temporal privado, rechaza traversal,
symlinks, archivos no esperados y checksums incorrectos. Completa extracción
antes de copiar archivos. Bloquea el entorno y mantiene `.deploy/<entorno>` y las
rutas instaladas; no elimina la instalación para actualizarla. Carga únicamente
la referencia esperada, rechaza colisiones de tag/ID y valida etiquetas antes
del arranque. Después elimina `image.tar`; los temporales se limpian al terminar.
Los paquetes son del operador autorizado: los hashes detectan corrupción, no
sustituyen firma/autenticidad; SSH autentica la transferencia.

Mantener una sola ruta de instalación autoritativa por proyecto/entorno en cada
host. Ejecutar operaciones desde dos copias del checkout con el mismo proyecto
Compose compartiría contenedores pero no locks ni historial; no es un despliegue
independiente. La transferencia siempre reutiliza la ruta remota configurada.

Las acciones remote verify/rollback/cleanup/status/logs ejecutan lo ya instalado
sin transferir imágenes. Para instalación manual, extraer **un paquete propio
verificado** en la raíz de instalación privada, conservando `.deploy`, y ejecutar
`bash scripts/deploy.sh install --env demo`. No extraer paquetes ajenos con tar.

## Confirmación, recuperación y estado

Estado externo al contenedor, `.deploy/<entorno>/`: `built-image`, `current-image`,
`previous-image`, `pending-image`, `pending-previous`, `failure.log`, `lock` y
`identity.json`. Archivos privados, escritura temporal+fsync+rename y locks mkdir.
Primero se captura la imagen realmente activa; después se anotan referencias
pendientes y se ejecuta `compose up -d --no-build --pull never mcp`. Solo tras
salud y verificación funcional se confirman current/previous. La verificación
revisa la imagen real, no solo que exista un contenedor saludable.

Si falla: guardar logs técnicos privados y tratar de recuperar/verificar la
imagen anterior. En primera instalación se detiene el servicio fallido. Si
la recuperación no se verifica, se conservan las referencias pendientes y
se rechazan nuevas transacciones hasta intervención. `rollback` despliega
previous y, tras verificar, intercambia current/previous, permitiendo volver
adelante. Un rollback fallido intenta restaurar la imagen activa. **No restaura
configuración ni datos:** guardar versiones privadas de configuración compatibles
antes de cambiarla. Las configuraciones nuevas se aplican también al rollback.

Tras caída o SIGKILL: leer `lock/owner.json`, confirmar host y PID, inspeccionar
Docker y comprobar que ningún despliegue/transferencia sigue activo. Solo entonces
retirar el lock abandonado. No se elimina por edad automáticamente. Inspeccionar
pending/current y elegir la imagen a recuperar; guardar una copia del estado,
verificar manualmente la imagen y configuración, retirar referencias pendientes
solo cuando se haya resuelto la transacción y ejecutar local con `--image` para
establecer un estado confirmado. No adivinar que el último comando terminó bien.

`cleanup` es una acción explícita: elimina solo contenedores detenidos y tags
prescindibles del proyecto/entorno. Protege todas las referencias de estado,
sus IDs, y cualquier imagen usada por cualquier contenedor. No usa prune global
ni force. Si se ejecuta después de un despliegue, su fallo no revoca la confirmación
ni modifica current/previous. Los volúmenes y redes ajenos nunca se limpian.

## Verificación real y aislamiento

`verify-http.py` usa stdlib: health y revisión/entorno correctos, readiness de
efemérides, Host/Origin, 404, métricas protegidas, avisos/fuentes, challenge exacto,
initialize/tools/list, anotaciones/esquemas y llamadas numéricas reales. Verifica
Porto literal, aspectos, tránsitos, efemérides, hora desconocida y rechazo de
instante UTC certificado. No se disparan consultas geográficas externas durante
un despliegue: con geocodificador desactivado se prueba su error explícito.
Cuando se habilite uno en producción, comprobarlo aparte con permiso del operador.

Demo se identifica con `[DEMO]` en MCP, `environment`/`demo` en health, warning DEMO
en resultados y cabecera X-Carta-Environment. Añade `X-Robots-Tag: noindex, nofollow,
noarchive`; no existe HTML que necesite un banner. El proxy también puede restringir
acceso a demo. Noindex no es autenticación ni protección de datos.

```bash
./scripts/verify/verify-isolation.sh --env demo
# Configuraciones de pruebas alternativas:
./scripts/verify/verify-isolation.sh --env demo --config /ruta/demo.env --production-config /ruta/production.env
```

Esta prueba **despliega la built-image de demo**. Requiere producción ya activa,
bloquea ambos entornos, verifica ambos servicios y compara ID/StartedAt/RestartCount
de producción antes/después. Comprueba redes disjuntas, UID 1000, read-only,
sin bind mounts/volúmenes, límite de recursos y puerto loopback correcto.
No ejecutes esta prueba contra instalaciones que no estés autorizado a operar.

CI ejecuta la suite en Python 3.11/3.12/3.14 y construye ambas imágenes
con Python exacto de `.python-version`. No despliega, publica imágenes ni genera
paquetes de instalación. La verificación de aislamiento se ejecuta manualmente
fuera de GitHub Actions. Resultados locales: `docs/deployment/VERIFICATION.md`.

Los jobs usan explícitamente `ubuntu-24.04`, cuya imagen incluye Docker Compose
v2. La migración de `ubuntu-latest` a Ubuntu 26.04 introduce Compose v5, que no
cumple el requisito actual del despliegue. Las acciones checkout/setup-python/
upload-artifact utilizan versiones con Node 24. El job de imagen muestra las
versiones de Python, Docker y Compose antes de compilar.
Referencias: [Ubuntu 24.04](https://github.com/actions/runner-images/blob/main/images/ubuntu/Ubuntu2404-Readme.md)
y [Ubuntu 26.04](https://github.com/actions/runner-images/blob/main/images/ubuntu/Ubuntu2604-Readme.md).

## Persistencia, privacidad y reproducibilidad

El servicio no guarda cartas ni necesita volúmenes. No hay base de datos ni
migraciones. Conservar fuera del contenedor paquetes, fuentes públicas, versiones
de configuración privadas y `.deploy` con acceso limitado y copias cifradas.
Los logs se rotan por tamaño, no por tiempo; revisar también proxy/host/SSH y su
retención. Los `.env` y paquetes privados no deben entrar en backups públicos.

Conservar cada image ID y paquete permite restaurar el mismo binario sin registro.
Las dependencias y la base están fijadas; APT y las herramientas de build del
stage temporal no son un snapshot hermético. No se afirma que reconstruir años
más tarde produzca el mismo digest. El rollback reproducible usa la imagen
transportada y preservada, junto con su oferta de fuente correspondiente.

Referencias oficiales: [docker image save](https://docs.docker.com/reference/cli/docker/image/save/)
y [precedencia de variables Compose](https://docs.docker.com/compose/how-tos/environment-variables/variable-interpolation/).
