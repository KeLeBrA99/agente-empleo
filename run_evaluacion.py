"""
Evalúa las vacantes pendientes y guarda el resultado.

    python run_evaluacion.py

El evaluador se elige con la variable EVALUADOR del .env:
    EVALUADOR=mock   -> heurísticas locales, sin costo
    EVALUADOR=real   -> llama al modelo
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

from evaluacion.mock import evaluar_mock

load_dotenv(override=True)
log = logging.getLogger(__name__)

MODO = os.environ.get("EVALUADOR", "mock").lower()

# Títulos que ni siquiera vale la pena evaluar
DESCARTE_TITULO = (
    "senior", "sr.", "líder técnico", "tech lead", "arquitecto", "gerente",
    "java", ".net", "php", "sap abap", "progress 4gl",
    "comercial", "asesor", "ejecutivo", "aprendiz", "contable", "vendedor",
)


def cargar_perfil(conexion) -> tuple[dict, int]:
    """Lee perfil.json y lo registra como versión activa si aún no está."""
    datos = json.loads(Path("perfil.json").read_text(encoding="utf-8"))
    version = datos.get("version", 1)

    existe = conexion.execute(
        text("SELECT 1 FROM perfil WHERE version = :v"), {"v": version}
    ).first()

    if not existe:
        conexion.execute(text("UPDATE perfil SET activo = FALSE WHERE activo"))
        conexion.execute(
            text(
                "INSERT INTO perfil (version, datos, activo) "
                "VALUES (:v, CAST(:d AS jsonb), TRUE)"
            ),
            {"v": version, "d": json.dumps(datos, ensure_ascii=False)},
        )
        log.info("Perfil versión %s registrado", version)

    return datos, version


PENDIENTES = text("""
    SELECT v.id, v.titulo, v.empresa, v.ubicacion, v.descripcion,
           v.salario_min, v.salario_max, v.modalidad
    FROM        vacantes     v
    LEFT JOIN   evaluaciones e
           ON   e.vacante_id = v.id AND e.perfil_version = :version
    WHERE       e.id IS NULL
      AND       v.descartada_en IS NULL
      AND       NOT v.cerrada
""")

GUARDAR = text("""
    INSERT INTO evaluaciones (
        vacante_id, perfil_version, puntaje, veredicto,
        cumple, brechas, excluyentes_fallan, gancho,
        senal_fraude, razonamiento, modelo
    ) VALUES (
        :vacante_id, :perfil_version, :puntaje, :veredicto,
        CAST(:cumple AS jsonb), CAST(:brechas AS jsonb),
        CAST(:excluyentes_fallan AS jsonb), :gancho,
        :senal_fraude, :razonamiento, :modelo
    )
    ON CONFLICT (vacante_id, perfil_version) DO NOTHING
""")

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if MODO == "real":
        from scoring import evaluar as evaluar_real  # import perezoso: requiere saldo

    motor = create_engine(os.environ["DATABASE_URL"])

    with motor.connect() as conexion:
        perfil, version = cargar_perfil(conexion)
        vacantes = conexion.execute(PENDIENTES, {"version": version}).mappings().all()
        log.info("Pendientes de evaluar: %s (modo %s)", len(vacantes), MODO)

        evaluadas = filtradas = 0
        

        for v in vacantes:
            vacante = dict(v)

            if any(t in vacante["titulo"].lower() for t in DESCARTE_TITULO):
                filtradas += 1
                continue

            if MODO == "real":
                resultado = evaluar_real(vacante, perfil)
                if resultado is None:
                    continue
                resultado = resultado.model_dump()
                modelo = "claude-sonnet-5"
            else:
                resultado = evaluar_mock(vacante, perfil)
                modelo = "mock-heuristico"

            conexion.execute(
                GUARDAR,
                {
                    "vacante_id": vacante["id"],
                    "perfil_version": version,
                    "puntaje": resultado["puntaje"],
                    "veredicto": resultado["veredicto"],
                    "cumple": json.dumps(resultado["cumple"], ensure_ascii=False),
                    "brechas": json.dumps(resultado["brechas"], ensure_ascii=False),
                    "excluyentes_fallan": json.dumps(
                        resultado["excluyentes_fallan"], ensure_ascii=False
                    ),
                    "gancho": resultado.get("gancho"),
                    "senal_fraude": resultado["senal_fraude"],
                    "razonamiento": resultado["razonamiento"],
                    "modelo": modelo,
                },
            )
            evaluadas += 1
            conexion.commit()

    log.info("Evaluadas: %s | Filtradas por título: %s", evaluadas, filtradas)


if __name__ == "__main__":
    main()
