# Contribuciones

Contribuir bajo AGPL-3.0-only, conservando avisos de terceros. No copiar código
propietario ni incluir datos natales reales, secretos o términos incompatibles.
Enviar cambios pequeños con pruebas de comportamiento y evidencia reproducible.

La convención literal es un requisito del producto: no añadir conversiones de
husos, IANA, DST ni correcciones de reloj por coordenadas. Toda modificación de
motor, datos, nodos, casas o precisión debe ser explícita y actualizar contratos.

Ejecutar `uv sync --frozen`, `uv run python scripts/fetch_ephemeris.py`,
`uv run pytest`, `uv run ruff check src tests scripts`,
`uv run ruff format --check src tests scripts` y comprobación de esquemas.
Actualizar CHANGELOG y regenerar auditoría/fuentes al cambiar dependencias.
No modificar silenciosamente fixtures de referencia para hacer pasar pruebas.
