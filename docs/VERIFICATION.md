# Verificación de implementación

Fecha de referencia: 2026-11-03. Entorno local aislado, sin publicación.

| Comprobación | Estado |
|---|---|
| Motor Swiss y archivos fijados | Instalados y cálculos locales comprobados |
| Herramientas y esquemas MCP | Cinco herramientas, contratos JSON validados en pruebas |
| Cliente oficial MCP sobre HTTP real | Probado en loopback |
| Tests de unidad/integración/E2E | 106 pruebas superadas tras adaptar despliegue; artifacts/tests-deployment-final.xml |
| Lint/formato y deriva de esquemas | Superados |
| MCP Inspector 2.13.0 CLI | tools/list: cinco tools; tools/call: carta Porto con éxito |
| Imagen Docker | Construida localmente con Python fijado por digest; publicación pendiente |
| Contenedor restringido | MCP y rutas legales/health/fuentes responden; UID 1000, read-only, 768 MiB |
| Oferta de fuentes | Descarga desde contenedor con SHA-256 idéntico al artefacto local |
| Referencia C swetest | Compilada del mismo sdist; misma referencia UT y parámetros |
| Geocodificación | Adaptador probado con transporte simulado; proveedor productivo pendiente |
| Vulnerabilidades Python runtime | 34 dependencias, ninguna conocida en consulta PyPI |
| DNS/TLS público | Subdominio sin resolver durante inspección; no verificado |
| Repositorio público | No creado; destino de cuenta/organización pendiente |
| Despliegue productivo | Patrón sin registro implementado y probado en loopback; host/SSH/DNS pendientes |
| Dominio OpenAI | Token no recibido; no verificado |

Las pruebas de SDK/HTTP se ejecutan con un puerto local, no mediante un túnel
público. No confundirlas con una invocación desde ChatGPT. La comparación C usa
el mismo Swiss Ephemeris; comprueba el wrapper y el servicio, no es una validación
independiente de la teoría astronómica ni del instante natal real.

Los tests cubren formato y rango, modos temporales, desconocida/aproximada,
variación lunar, nodos, geometría polar, fallback rechazado, errores del motor,
proveedor fallido/ambiguo, concurrencia, Host/Origin, límites y challenge exacto.
Los resultados numéricos no se comparan contra una carta convertida de hora civil.
Salida real de ejemplo: `docs/examples/porto-literal.json`, obtenida con Inspector
en loopback. Los datos son el caso de prueba solicitado, sin nombres personales.