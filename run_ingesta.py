"""
Guarda las vacantes recolectadas en Postgres, sin duplicar.

Uso:
    python run_ingesta.py
"""

from __future__ import annotations

import logging
import os

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

from scraper.computrabajo import recolectar

load_dotenv(override=True)
log = logging.getLogger(__name__)

# Términos de búsqueda. Ajusta esta lista a tu perfil.
TERMINOS = [
    "desarrollador junior",
    "desarrollador python",
    "desarrollador backend",
    "desarrollador full stack",
    "programador junior",
    "django",
    "fastapi",
]

INSERTAR = text("""
    INSERT INTO vacantes (
        fuente, id_externo, url, titulo, empresa, ubicacion,
        modalidad, salario_min, salario_max, descripcion,
        hash_contenido, publicada_en
    ) VALUES (
        :fuente, :id_externo, :url, :titulo, :empresa, :ubicacion,
        :modalidad, :salario_min, :salario_max, :descripcion,
        :hash_contenido, :publicada_en
    )
    ON CONFLICT (fuente, id_externo) DO NOTHING
    RETURNING id
""")

# Un mismo aviso se publica en varios portales; evitamos evaluarlo dos veces
YA_EXISTE_CONTENIDO = text("SELECT 1 FROM vacantes WHERE hash_contenido = :h LIMIT 1")


def guardar(vacantes: list[dict]) -> tuple[int, int]:
    motor = create_engine(os.environ["DATABASE_URL"])
    nuevas = repetidas = 0

    with motor.begin() as conexion:
        for v in vacantes:
            if conexion.execute(YA_EXISTE_CONTENIDO, {"h": v["hash_contenido"]}).first():
                repetidas += 1
                continue

            fila = conexion.execute(INSERTAR, v).first()
            if fila:
                nuevas += 1
            else:
                repetidas += 1

    return nuevas, repetidas


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    log.info("Recolectando (%s términos)...", len(TERMINOS))
    vacantes = recolectar(TERMINOS, paginas_por_termino=2)
    log.info("Recolectadas: %s", len(vacantes))

    if not vacantes:
        log.warning("Nada que guardar. Revisa los selectores con --debug.")
        return

    nuevas, repetidas = guardar(vacantes)
    log.info("Nuevas: %s | Ya conocidas: %s", nuevas, repetidas)


if __name__ == "__main__":
    main()
