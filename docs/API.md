# Contratos y convenciones

Los JSON Schema de `docs/tool-schemas.json` se generan de las herramientas reales.
La clave MCP `arguments` contiene un único objeto `request`; no campos sueltos.
Pydantic prohíbe campos extra, números no finitos, coordenadas como cadenas,
fechas inválidas y formatos de reloj distintos de HH:MM. No se admiten nombres,
apellidos, correo, IANA, offsets ni convenciones temporales alternativas.
Rango: 1800-01-02 a 2399-12-31. Se excluye 1800-01-01 porque la corrección de
tiempo de luz puede requerir datos anteriores al comienzo del archivo planetario;
no se permite que el motor sustituya esa cobertura por Moshier.

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "calculate_natal_chart",
    "arguments": {"request": {
      "birth_date": "1985-07-02", "birth_time": "08:05",
      "city": "Porto", "country": "Portugal",
      "latitude": 41.1579, "longitude": -8.6291,
      "time_precision": "exact"
    }}
  }
}
```

Otras entradas:

```json
{
  "resolve_birthplace": {"request": {"city": "Porto", "country": "Portugal"}},
  "calculate_transits": {"request": {"reference_date": "2026-11-03", "reference_time": "10:00"}},
  "get_ephemeris": {"request": {"reference_date": "2000-01-01", "reference_time": "12:00"}},
  "calculate_aspects": {"request": {"longitudes": {"Sun": 0, "Moon": 90, "Mars": 180}, "orbs": {"square": 6}}}
}
```

`input` conserva únicamente los campos originales efectivamente enviados, sin
reescribir espacios, nombres de localidad o reloj; los valores por defecto se
documentan en el esquema. Las fechas deben llegar en ISO: la conversión de la
presentación `02/07/1985` a `1985-07-02` corresponde al plugin, sin cambiar el día.

Cada resultado contiene `success`, `calculation_mode`, `input`,
`resolved_location`, `time_reference`, `precision_status`, `engine`,
`engine_version`, `ephemeris_source`, `zodiac`, `house_system`, `positions`,
`houses`, `angles`, `aspects`, `warnings`, `errors`. También candidatos,
ambigüedad, día juliano convencional, reloj efectivo y URL de fuente.
La geocodificación y los aspectos aislados tienen referencia/precisión
`not_applicable`; el modo identifica el servicio, no inventa una hora para ellos.

Las posiciones incluyen longitud [0,360), latitud eclíptica, signo, grado [0,30),
velocidad longitudinal en grados/día y retrogradación. Nodo sur = nodo norte +180°,
latitud invertida, misma velocidad y retrogradación. No se consultan asteroides.
El tipo de nodo `mean`/`true` y el sistema elegido nunca se sustituyen.
Solo tropical; una solicitud sidérea se rechaza en lugar de adivinar ayanamsa.

Placidus es el valor predeterminado. `WholeSign` y `Equal` requieren una selección
explícita en la entrada. Las casas planetarias usan los intervalos de longitudes
de cúspides, ignorando latitud eclíptica; esta convención aparece en las advertencias.
No se afirma equivalencia con una asignación tridimensional `swe_house_pos`.
Sin hora se omiten ángulos/casas/aspectos; las muestras del día no son cotas
matemáticas rigurosas ni una distribución de probabilidad. Una hora aproximada
no tiene margen cuantificado. Todas las casas y ángulos son convencionales.

Aspectos: distancia menor en el círculo, pares ordenados por nombre, límites de
orbe inclusivos. Conjunción 0°±8°, sextil 60°±4°, cuadratura 90°±6°, trígono
120°±6°, oposición 180°±8°. Cada orbe configurable está entre 0° y 15°.
No se infieren aspectos aplicativos/separativos de longitudes estáticas.
Máximo 32 cuerpos en `calculate_aspects`. Tránsitos significa aspectos entre
los planetas de la referencia solicitada; no sinastría con una carta natal.

Errores de dominio: `AMBIGUOUS_LOCATION`, `LOCATION_NOT_FOUND`,
`GEOCODER_NOT_CONFIGURED`, `GEOCODER_FAILURE`, `VERIFIED_INSTANT_UNAVAILABLE`,
`HOUSE_GEOMETRY_UNDEFINED`, `EPHEMERIS_DATA_UNAVAILABLE`,
`EPHEMERIS_FALLBACK_REJECTED`, `ENGINE_ERROR`, `CALCULATION_TIMEOUT`, `SERVICE_BUSY`.
Un fallo limpia todas las posiciones, casas, ángulos, aspectos y día juliano.
Los errores de validación pueden llegar como error MCP sin el envoltorio `Result`.

## Anotaciones

Todas: `readOnlyHint=true`, `destructiveHint=false`, `idempotentHint=true`.
Son consultas sin mutaciones del dominio ni historial. Logging y métricas
técnicas no equivalen a una operación de escritura accesible por MCP.
`openWorldHint=true` para resolución de lugares y carta natal porque pueden
consultar un proveedor externo. Es falso para aspectos, tránsitos y efemérides,
que solo usan datos locales. No existe acceso a archivos arbitrarios, ejecución
de código, comandos de shell ni descargas controladas por el usuario en las tools.
