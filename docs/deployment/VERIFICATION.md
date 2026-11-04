# Verificación del despliegue — 2026-11-03

Pruebas locales sobre Docker 20.10.24 / Compose 2.17.2, plataforma linux/amd64.
Proyecto exclusivo `carta-deploy-check`; producción de prueba en 127.0.0.1:14100
y demo en 127.0.0.1:14200. `LOCAL_TEST_ONLY=true`, sin aprobación jurídica ficticia
ni geocodificación externa. Estos puertos no representan despliegue público.

| Comprobación | Resultado observado |
|---|---|
| Suite Python completa | 106 tests superados: unidad, integración, SDK HTTP y operación |
| Ruff y sintaxis Bash | Sin errores; 12 scripts Bash comprobados |
| CLI y configuración | Flags incompatibles rechazados antes de Docker; ejecución desde otra carpeta; configuración nunca ejecutada; symlinks/permisos/expansiones rechazados |
| Doble compilación | Validación del checkout y build Docker de tres etapas completados |
| Ambas instalaciones | Imágenes separadas, salud y cinco herramientas MCP comprobadas |
| Restricciones Docker | UID/GID 1000:1000, read-only, tmpfs, sin volúmenes persistentes, límites y loopback verificados |
| Aislamiento | Actualizar demo conservó ID, StartedAt y RestartCount de producción; redes disjuntas |
| Rollback y vuelta adelante | Ambas direcciones verificadas con MCP real |
| Fallo inducido | Imagen con HEALTHCHECK fallido rechazada; recuperación verificada, historial confirmado intacto y pendientes retirados |
| Primer arranque fallido | Contenedor detenido sin confirmar current-image al detectar licencia incorrecta |
| LICENSE | Corregido a AGPL v3 desde la raíz del sdist PySwissEph; el verificador exige el texto AGPL en /license |
| Paquete | 20 archivos, modo 600, SHA-256 por archivo; sin checkout/Dockerfile/credenciales SSH |
| Recepción/instalación | Bootstrap ejecutado localmente con paquete por stdin; image load, validación de ID/etiquetas, Compose y MCP completados |
| Reinstalación | Conservó estado y archivo testigo en .deploy; image.tar eliminado y temporales limpiados |
| Limpieza | Ejecutada solo para demo; imágenes current/previous/built y usadas por contenedores conservadas |
| Concurrencia | Segundo comando durante empaquetado rechazado por lock, sin alterar el servicio |

Imágenes utilizadas para el ensayo:

- Demo inicial válida: `carta-deploy-check:demo-20261103T204705370693Z-snapshot-b1da6abe8500`.
- Demo actualizada: `carta-deploy-check:demo-20261103T204821188068Z-snapshot-96b2ad94d9fa`.
- Producción de prueba: `carta-deploy-check:production-20261103T204732346156Z-snapshot-b1da6abe8500`.

Son snapshots de la implementación durante el ensayo, no versiones publicadas.
Cada imagen conserva su propio archivo de fuentes. Cambios posteriores en docs
y pruebas requieren otra compilación para formar parte de una nueva imagen.
No se etiquetó ninguna como latest. Se conservaron imágenes e historial; los
contenedores/redes exclusivos del ensayo se retiraron al finalizar.

Evidencia local privada en `artifacts/`: `tests-deployment-final.xml`,
`deploy-isolation.log`, `deploy-rollback.log`, `deploy-recovery.log`,
`deploy-install-package.log`, `deploy-cleanup.log` y logs de compilación.
Los artefactos no se versionan; el paquete puede contener configuración privada.
Los tests se reproducen con `pytest`; el ensayo de aislamiento con
`scripts/verify/verify-isolation.sh`, según el README de despliegue.

No comprobado todavía: conexión a un servidor SSH real, instalación del proxy,
DNS/TLS, ejecución de GitHub Actions, plataforma ARM64, revisión jurídica de los
datos, publicación del repositorio, token OpenAI ni descubrimiento desde ChatGPT.
La recepción probada localmente no acredita el transporte SSH del futuro host.
