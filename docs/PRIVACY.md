# Privacidad técnica de Carta y Arcano

El MCP procesa fecha, reloj, ciudad/país/región, coordenadas y opciones de cálculo.
No solicita nombre completo, correo ni cuenta. No hay LLM en el backend,
base de datos natal, escritura MCP ni historial persistente de cartas.
La respuesta reproduce los datos de entrada para hacer trazable el cálculo.

Con coordenadas no se geocodifica. El adaptador externo, si se habilita,
recibe exclusivamente ciudad, país y región; nunca la fecha, hora, nombre o tarot.
El servicio no conserva una caché geográfica ni un registro de consultas.

Los logs de aplicación contienen fecha operativa, nivel, tipo de evento, ruta
de un conjunto fijo, estado HTTP y duración. El formateador descarta mensajes
de excepciones, cuerpos, query strings, IP, cabeceras y valores de parámetros,
incluidos los mensajes de bibliotecas. Uvicorn se ejecuta sin access log.
Las métricas usan etiquetas fijas de ruta/herramienta/código de resultado,
sin datos natales. `/metrics` requiere un token de operador.

El rate limiter mantiene direcciones del cliente de transporte en memoria,
con capacidad máxima de 4096 entradas, eliminadas por reemplazo o reinicio.
No se escriben a disco. No se promete un plazo temporal de eliminación por
inactividad. Tras el proxy propuesto, esa dirección es la del proxy; no se
confía en cabeceras X-Forwarded-For proporcionadas por el cliente.

Compose limita logs Docker a tres archivos de 10 MiB por contenedor. Esto es
una rotación por tamaño, **no** una garantía de retención temporal ni de borrado
de copias. El ejemplo Caddy no habilita access logs; pueden existir registros
de error, TLS, host, proveedor, firewall, DNS, CDN, copias o monitorización.
No se han inspeccionado esos sistemas productivos. Nunca afirme retención nula
sin verificarlos. ChatGPT y el proveedor de alojamiento tienen además sus
propias prácticas, independientes del historial que este backend no implementa.

Las herramientas de despliegue conservan referencias de imágenes, identificación
del proceso de operación y logs de fallo en `.deploy/<entorno>`, con permisos
privados. No se eliminan por plazo automáticamente. Los paquetes de instalación
contienen la configuración operativa y pueden incluir tokens; deben protegerse
y excluirse de descargas públicas. Demo tiene los mismos requisitos de privacidad.

Antes de activación: inventariar cada registro, responsable, acceso, ubicación,
retención, eliminación y copia; publicar los valores confirmados y el canal
para ejercer derechos. No activar exportadores de trazas con payloads ni
logging de cuerpo HTTP al integrar monitorización.
