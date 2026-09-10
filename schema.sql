-- =====================================================================
-- Agente de empleo — esquema PostgreSQL (Fase 1)
-- =====================================================================

CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ---------------------------------------------------------------------
-- PERFIL: versionado. Cada evaluación queda atada a la versión de perfil
-- con la que se hizo, para poder re-evaluar cuando mejores la HV.
-- ---------------------------------------------------------------------
CREATE TABLE perfil (
    id              SERIAL PRIMARY KEY,
    version         INTEGER     NOT NULL UNIQUE,
    datos           JSONB       NOT NULL,   -- ver perfil.example.json
    activo          BOOLEAN     NOT NULL DEFAULT FALSE,
    creado_en       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Solo un perfil activo a la vez
CREATE UNIQUE INDEX perfil_unico_activo ON perfil (activo) WHERE activo;

-- ---------------------------------------------------------------------
-- VACANTES
-- ---------------------------------------------------------------------
CREATE TYPE fuente_vacante AS ENUM (
    'computrabajo', 'elempleo', 'magneto365', 'linkedin', 'manual'
);

CREATE TYPE modalidad_trabajo AS ENUM (
    'remoto', 'hibrido', 'presencial', 'desconocida'
);

CREATE TABLE vacantes (
    id              BIGSERIAL PRIMARY KEY,
    fuente          fuente_vacante    NOT NULL,
    id_externo      TEXT              NOT NULL,   -- id en el portal origen
    url             TEXT              NOT NULL,
    titulo          TEXT              NOT NULL,
    empresa         TEXT,
    ubicacion       TEXT,
    modalidad       modalidad_trabajo NOT NULL DEFAULT 'desconocida',
    salario_min     INTEGER,                      -- COP mensual, NULL si no publica
    salario_max     INTEGER,
    descripcion     TEXT              NOT NULL,
    hash_contenido  TEXT              NOT NULL,   -- sha256(titulo||descripcion)
    publicada_en    DATE,
    capturada_en    TIMESTAMPTZ       NOT NULL DEFAULT now(),
    cerrada         BOOLEAN           NOT NULL DEFAULT FALSE,
    descartada_en   TIMESTAMPTZ,                  -- descarte manual tuyo
    motivo_descarte TEXT,

    CONSTRAINT vacantes_origen_unico UNIQUE (fuente, id_externo)
);

-- Evita re-evaluar el mismo aviso republicado por otro portal
CREATE INDEX vacantes_hash_idx    ON vacantes (hash_contenido);
CREATE INDEX vacantes_captura_idx ON vacantes (capturada_en DESC);
CREATE INDEX vacantes_titulo_trgm ON vacantes USING gin (titulo gin_trgm_ops);

-- ---------------------------------------------------------------------
-- EVALUACIONES (salida del LLM)
-- ---------------------------------------------------------------------
CREATE TABLE evaluaciones (
    id                  BIGSERIAL PRIMARY KEY,
    vacante_id          BIGINT      NOT NULL REFERENCES vacantes(id) ON DELETE CASCADE,
    perfil_version      INTEGER     NOT NULL REFERENCES perfil(version),
    puntaje             SMALLINT    NOT NULL CHECK (puntaje BETWEEN 0 AND 100),
    veredicto           TEXT        NOT NULL,   -- postular / dudoso / descartar
    cumple              JSONB       NOT NULL DEFAULT '[]',
    brechas             JSONB       NOT NULL DEFAULT '[]',
    excluyentes_fallan  JSONB       NOT NULL DEFAULT '[]',
    gancho              TEXT,                   -- insumo para la carta (Fase 2)
    senal_fraude        SMALLINT    NOT NULL DEFAULT 0 CHECK (senal_fraude BETWEEN 0 AND 3),
    razonamiento        TEXT,
    modelo              TEXT        NOT NULL,
    creada_en           TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT eval_unica UNIQUE (vacante_id, perfil_version)
);

CREATE INDEX eval_puntaje_idx ON evaluaciones (puntaje DESC, creada_en DESC);

-- ---------------------------------------------------------------------
-- POSTULACIONES (Fase 3, pero la tabla va desde ya)
-- ---------------------------------------------------------------------
CREATE TYPE estado_postulacion AS ENUM (
    'borrador', 'enviada', 'vista', 'prueba_tecnica',
    'entrevista', 'oferta', 'rechazo', 'sin_respuesta'
);

CREATE TABLE postulaciones (
    id                  BIGSERIAL PRIMARY KEY,
    vacante_id          BIGINT             NOT NULL UNIQUE REFERENCES vacantes(id),
    estado              estado_postulacion NOT NULL DEFAULT 'borrador',
    enviada_en          TIMESTAMPTZ,
    canal               TEXT,               -- portal, correo directo, referido
    contacto            TEXT,
    ultimo_contacto_en  TIMESTAMPTZ,
    proximo_followup    DATE,
    notas               TEXT,
    actualizada_en      TIMESTAMPTZ        NOT NULL DEFAULT now()
);

CREATE INDEX postulaciones_followup_idx
    ON postulaciones (proximo_followup)
    WHERE estado IN ('enviada', 'vista');

-- ---------------------------------------------------------------------
-- DOCUMENTOS generados por vacante (Fase 2)
-- ---------------------------------------------------------------------
CREATE TABLE documentos (
    id              BIGSERIAL PRIMARY KEY,
    postulacion_id  BIGINT      NOT NULL REFERENCES postulaciones(id) ON DELETE CASCADE,
    tipo            TEXT        NOT NULL CHECK (tipo IN ('hv', 'carta', 'mensaje')),
    contenido_md    TEXT        NOT NULL,
    ruta_pdf        TEXT,
    creado_en       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------
-- Vista de trabajo: qué revisar hoy
-- ---------------------------------------------------------------------
CREATE VIEW v_bandeja AS
SELECT  v.id,
        v.titulo,
        v.empresa,
        v.ubicacion,
        v.modalidad,
        v.url,
        e.puntaje,
        e.veredicto,
        e.gancho,
        e.brechas,
        v.capturada_en
FROM        vacantes    v
JOIN        evaluaciones e ON e.vacante_id = v.id
LEFT JOIN   postulaciones p ON p.vacante_id = v.id
WHERE       p.id IS NULL
  AND       v.descartada_en IS NULL
  AND       NOT v.cerrada
  AND       e.senal_fraude < 2
ORDER BY    e.puntaje DESC, v.capturada_en DESC;
