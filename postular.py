"""
Seguimiento de postulaciones.

    python postular.py --bandeja                 ver vacantes con su id
    python postular.py 42                        registrar postulación a la vacante 42
    python postular.py 42 --canal correo --contacto "Ana Ruiz"
    python postular.py --lista                   ver todas las postulaciones
    python postular.py --pendientes              a quién hacer seguimiento hoy
    python postular.py --estado 42 entrevista    actualizar estado
"""

from __future__ import annotations

import argparse
import os
from datetime import date, timedelta

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv(override=True)

DIAS_PARA_SEGUIMIENTO = 6

ESTADOS = (
    "borrador", "enviada", "vista", "prueba_tecnica",
    "entrevista", "oferta", "rechazo", "sin_respuesta",
)


def motor():
    return create_engine(os.environ["DATABASE_URL"])


# --------------------------------------------------------------------------
def ver_bandeja(limite: int) -> None:
    consulta = text("""
        SELECT  v.id, v.titulo, v.empresa, e.puntaje, e.veredicto,
                (p.id IS NOT NULL) AS postulada
        FROM        vacantes     v
        LEFT JOIN   evaluaciones e ON e.vacante_id = v.id
        LEFT JOIN   postulaciones p ON p.vacante_id = v.id
        WHERE       v.descartada_en IS NULL
        ORDER BY    e.puntaje DESC NULLS LAST, v.capturada_en DESC
        LIMIT :limite
    """)
    with motor().connect() as c:
        filas = c.execute(consulta, {"limite": limite}).mappings().all()

    if not filas:
        print("No hay vacantes.")
        return

    print(f"\n{'id':>5}  {'pts':>4}  {'✓':^3} {'título':<45} empresa")
    print("-" * 100)
    for f in filas:
        marca = "✓" if f["postulada"] else ""
        puntaje = f["puntaje"] if f["puntaje"] is not None else "-"
        print(
            f"{f['id']:>5}  {puntaje:>4}  {marca:^3} "
            f"{(f['titulo'] or '')[:45]:<45} {(f['empresa'] or '-')[:30]}"
        )
    print()


# --------------------------------------------------------------------------
def registrar(vacante_id: int, canal: str, contacto: str | None, nota: str | None) -> None:
    hoy = date.today()
    seguimiento = hoy + timedelta(days=DIAS_PARA_SEGUIMIENTO)

    with motor().begin() as c:
        vacante = c.execute(
            text("SELECT titulo, empresa, url FROM vacantes WHERE id = :id"),
            {"id": vacante_id},
        ).mappings().first()

        if not vacante:
            print(f"No existe la vacante {vacante_id}.")
            return

        existe = c.execute(
            text("SELECT estado, enviada_en FROM postulaciones WHERE vacante_id = :id"),
            {"id": vacante_id},
        ).mappings().first()

        if existe:
            print(
                f"Ya estaba registrada: {vacante['titulo']} "
                f"({existe['estado']}, enviada {existe['enviada_en'].date()})"
            )
            return

        c.execute(
            text("""
                INSERT INTO postulaciones
                    (vacante_id, estado, enviada_en, canal, contacto,
                     ultimo_contacto_en, proximo_followup, notas)
                VALUES
                    (:id, 'enviada', now(), :canal, :contacto,
                     now(), :seguimiento, :nota)
            """),
            {
                "id": vacante_id,
                "canal": canal,
                "contacto": contacto,
                "seguimiento": seguimiento,
                "nota": nota,
            },
        )

    print(f"\nRegistrada: {vacante['titulo']} — {vacante['empresa'] or 'sin empresa'}")
    print(f"Canal: {canal}")
    print(f"Seguimiento el {seguimiento:%d de %B}")
    print(f"{vacante['url']}\n")


# --------------------------------------------------------------------------
def listar() -> None:
    consulta = text("""
        SELECT  p.vacante_id, v.titulo, v.empresa, p.estado,
                p.enviada_en::date AS enviada, p.proximo_followup
        FROM        postulaciones p
        JOIN        vacantes      v ON v.id = p.vacante_id
        ORDER BY    p.enviada_en DESC
    """)
    with motor().connect() as c:
        filas = c.execute(consulta).mappings().all()

    if not filas:
        print("Todavía no has registrado postulaciones.")
        return

    print(f"\n{'id':>5}  {'enviada':<12} {'estado':<15} {'título':<40} empresa")
    print("-" * 100)
    for f in filas:
        print(
            f"{f['vacante_id']:>5}  {str(f['enviada']):<12} {f['estado']:<15} "
            f"{(f['titulo'] or '')[:40]:<40} {(f['empresa'] or '-')[:25]}"
        )
    print(f"\nTotal: {len(filas)}\n")


# --------------------------------------------------------------------------
def pendientes() -> None:
    consulta = text("""
        SELECT  p.vacante_id, v.titulo, v.empresa, p.contacto, p.canal,
                p.enviada_en::date AS enviada,
                (CURRENT_DATE - p.enviada_en::date) AS dias
        FROM        postulaciones p
        JOIN        vacantes      v ON v.id = p.vacante_id
        WHERE       p.estado IN ('enviada', 'vista')
          AND       p.proximo_followup <= CURRENT_DATE
        ORDER BY    p.proximo_followup
    """)
    with motor().connect() as c:
        filas = c.execute(consulta).mappings().all()

    if not filas:
        print("\nNada pendiente de seguimiento hoy.\n")
        return

    print(f"\nSeguimiento pendiente ({len(filas)}):\n")
    for f in filas:
        saludo = f"Hola {f['contacto'].split()[0]}" if f["contacto"] else "Buen día"
        print(f"  [{f['vacante_id']}] {f['titulo']} — {f['empresa'] or 'sin empresa'}")
        print(f"      enviada hace {f['dias']} días por {f['canal']}")
        print(f"      Mensaje sugerido:")
        print(
            f'      "{saludo}, hace {f["dias"]} días apliqué a la vacante de '
            f'{f["titulo"]}. Sigo muy interesado en la posición y quedo atento '
            f'a cualquier información sobre el proceso. Gracias."\n'
        )

    print("Después de escribir, actualiza con:  python postular.py --estado <id> vista\n")


# --------------------------------------------------------------------------
def cambiar_estado(vacante_id: int, estado: str) -> None:
    if estado not in ESTADOS:
        print(f"Estado inválido. Opciones: {', '.join(ESTADOS)}")
        return

    # Los estados vivos reprograman el seguimiento; los cerrados lo quitan
    reprograma = estado in ("enviada", "vista", "prueba_tecnica", "entrevista")
    nuevo_followup = date.today() + timedelta(days=DIAS_PARA_SEGUIMIENTO) if reprograma else None

    with motor().begin() as c:
        resultado = c.execute(
            text("""
                UPDATE postulaciones
                SET    estado = :estado,
                       ultimo_contacto_en = now(),
                       proximo_followup = :followup,
                       actualizada_en = now()
                WHERE  vacante_id = :id
                RETURNING vacante_id
            """),
            {"estado": estado, "followup": nuevo_followup, "id": vacante_id},
        ).first()

    if resultado:
        extra = f", próximo seguimiento el {nuevo_followup:%d/%m}" if nuevo_followup else ""
        print(f"Vacante {vacante_id} → {estado}{extra}")
    else:
        print(f"No hay postulación registrada para la vacante {vacante_id}.")


# --------------------------------------------------------------------------
def main() -> None:
    p = argparse.ArgumentParser(description="Seguimiento de postulaciones")
    p.add_argument("vacante_id", nargs="?", type=int, help="id de la vacante")
    p.add_argument("--canal", default="portal",
                   help="portal, correo, linkedin, referido (por defecto: portal)")
    p.add_argument("--contacto", help="nombre del reclutador, si lo conoces")
    p.add_argument("--nota", help="cualquier detalle que quieras recordar")
    p.add_argument("--bandeja", action="store_true", help="ver vacantes con su id")
    p.add_argument("--limite", type=int, default=25, help="filas en --bandeja")
    p.add_argument("--lista", action="store_true", help="ver postulaciones registradas")
    p.add_argument("--pendientes", action="store_true", help="seguimientos de hoy")
    p.add_argument("--estado", nargs=2, metavar=("ID", "ESTADO"),
                   help="actualizar estado de una postulación")

    args = p.parse_args()

    if args.bandeja:
        ver_bandeja(args.limite)
    elif args.lista:
        listar()
    elif args.pendientes:
        pendientes()
    elif args.estado:
        cambiar_estado(int(args.estado[0]), args.estado[1])
    elif args.vacante_id is not None:
        registrar(args.vacante_id, args.canal, args.contacto, args.nota)
    else:
        p.print_help()


if __name__ == "__main__":
    main()
