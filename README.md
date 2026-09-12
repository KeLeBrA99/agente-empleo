# Agente de búsqueda de empleo

Recolecta vacantes de portales colombianos, las evalúa contra mi perfil con un LLM
y genera hoja de vida adaptada por vacante. Incluye seguimiento de postulaciones.

## Puesta en marcha

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env        # rellenar ANTHROPIC_API_KEY y POSTGRES_PASSWORD
docker compose up -d          # Postgres en 5433, Adminer en 8081
```

Adminer: `localhost:8081` · servidor `db` · usuario `agente` · base `agente_empleo`

## Uso diario

```bash
python run_ingesta.py                  # scrapea Computrabajo y guarda lo nuevo
python run_evaluacion.py               # evalúa lo pendiente (ver EVALUADOR)
python postular.py --bandeja           # vacantes ordenadas por puntaje, con id
python generar.py <id> --sin-carta     # HV adaptada, sin costo de API
python postular.py <id>                # registrar que postulé
python postular.py --pendientes        # a quién hacer seguimiento hoy
python postular.py --estado <id> entrevista
```

## Cómo está armado

| Archivo | Qué hace |
|---|---|
| `scraper/cliente.py` | HTTP con pausas de 3-6s y reintentos |
| `scraper/computrabajo.py` | Parser del portal. **Selectores aislados arriba** |
| `run_ingesta.py` | Orquesta scraping y guarda sin duplicar |
| `evaluacion/mock.py` | Evaluador por heurísticas, sin costo |
| `scoring.py` | Evaluador real contra la API |
| `run_evaluacion.py` | Elige evaluador según `EVALUADOR` del .env |
| `generar.py` | HV en HTML + carta por vacante |
| `postular.py` | Seguimiento de postulaciones |
| `perfil.json` | Mi perfil estructurado. Versionado en la tabla `perfil` |
| `schema.sql` | Esquema Postgres, se ejecuta al crear el contenedor |

## Decisiones que conviene recordar

- **Los selectores del scraper se rompen.** Cuando la ingesta traiga 0 resultados,
  correr `python inspeccionar.py` y ajustar el diccionario `SELECTORES`.
  Ya pasó con `empresa` (era `<a>`, no `<span>`) y con `ubicacion`
  (`span.mr10` a veces trae la calificación, no la ciudad).
- **El `id_externo` se saca del hash hexadecimal de la URL**, no del último
  segmento: el portal agrega `#lc=ListOffers-Score...` que cambia por búsqueda
  y rompía la deduplicación.
- **Cada evaluación hace commit propio.** Con una transacción única, un fallo de
  red al final borraba todo el lote ya pagado.
- **Nunca lanzar un lote sin probar una unidad primero:** `python scoring.py`
  hace una sola llamada y muestra el JSON.
- **La respuesta del modelo trae bloques mixtos.** Hay que filtrar por
  `type == "text"`; el primero puede ser razonamiento interno, que además se
  cobra como tokens de salida.
- **El filtro previo por título** (`DESCARTE_TITULO`) descarta ~1/3 de las
  vacantes sin gastar llamadas.

## Hallazgo del mercado (sep 2026)

De 116 vacantes recolectadas en Computrabajo con términos de desarrollo junior:
39 descartadas por título, y de las evaluadas ninguna superó 45 puntos. La causa
recurrente es el requisito de 2+ años como excluyente. Conclusión: Computrabajo
no es la fuente adecuada para este perfil. Pendiente agregar elempleo y
Magneto365.

## Pendiente

- Scraper de elempleo y Magneto365
- Programar la ingesta diaria (Task Scheduler)
- Probar Haiku vs Sonnet para el scoring y comparar costo/calidad
- Batch API para la evaluación nocturna (50% más barato)
