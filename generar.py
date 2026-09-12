"""
Genera hoja de vida adaptada y carta para una vacante concreta.

    python generar.py 356              HV + carta (la carta requiere saldo)
    python generar.py 356 --sin-carta  solo HV, sin costo

Los archivos quedan en salidas/. La HV es HTML: ábrela en el navegador y usa
Ctrl+P -> "Guardar como PDF" para adjuntarla.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv(override=True)

SALIDAS = Path("salidas")
PALABRAS_VACIAS = {
    "para", "con", "los", "las", "del", "que", "una", "por", "como", "más",
    "sus", "este", "esta", "años", "experiencia", "trabajo", "empresa",
}


# --------------------------------------------------------------------------
def datos_vacante(vacante_id: int) -> dict | None:
    consulta = text("""
        SELECT  v.id, v.titulo, v.empresa, v.ubicacion, v.modalidad,
                v.descripcion, v.url, v.salario_min, v.salario_max,
                e.puntaje, e.gancho, e.cumple, e.brechas
        FROM        vacantes     v
        LEFT JOIN   evaluaciones e ON e.vacante_id = v.id
        WHERE       v.id = :id
    """)
    motor = create_engine(os.environ["DATABASE_URL"])
    with motor.connect() as c:
        fila = c.execute(consulta, {"id": vacante_id}).mappings().first()
    return dict(fila) if fila else None


def guardar_documento(vacante_id: int, tipo: str, contenido: str, ruta: str | None) -> None:
    """Se guarda solo si ya registraste la postulación con postular.py."""
    motor = create_engine(os.environ["DATABASE_URL"])
    with motor.begin() as c:
        postulacion = c.execute(
            text("SELECT id FROM postulaciones WHERE vacante_id = :id"),
            {"id": vacante_id},
        ).first()

        if not postulacion:
            return

        c.execute(
            text("""
                INSERT INTO documentos (postulacion_id, tipo, contenido_md, ruta_pdf)
                VALUES (:pid, :tipo, :contenido, :ruta)
            """),
            {"pid": postulacion[0], "tipo": tipo, "contenido": contenido, "ruta": ruta},
        )


# --------------------------------------------------------------------------
def terminos_del_aviso(descripcion: str) -> set[str]:
    palabras = re.findall(r"[a-záéíóúñ]{4,}", (descripcion or "").lower())
    return {p for p in palabras if p not in PALABRAS_VACIAS}


def relevancia(texto: str, terminos: set[str]) -> int:
    """Cuántos términos del aviso aparecen en este bloque del perfil."""
    propios = set(re.findall(r"[a-záéíóúñ]{4,}", texto.lower()))
    return len(propios & terminos)


def ordenar_proyectos(perfil: dict, terminos: set[str]) -> list[dict]:
    proyectos = [p for p in perfil.get("proyectos", []) if p.get("estado") != "en construcción"]
    return sorted(
        proyectos,
        key=lambda p: relevancia(json.dumps(p, ensure_ascii=False), terminos),
        reverse=True,
    )


def habilidades_destacadas(perfil: dict, descripcion: str) -> tuple[list[str], list[str]]:
    """Separa las habilidades que el aviso menciona de las que no.
    Se compara contra el texto completo, no contra palabras sueltas, para que
    funcionen los nombres de varias palabras y los de menos de cuatro letras."""
    texto = (descripcion or "").lower()
    todas = (
        perfil["habilidades"].get("dominio_solido", [])
        + perfil["habilidades"].get("dominio_intermedio", [])
    )

    coinciden, resto = [], []
    for h in todas:
        nombre = h.lower()
        # Un alias corto ayuda: "Django REST Framework" aparece como "django"
        clave = nombre.split()[0]
        if nombre in texto or (len(clave) >= 3 and clave in texto):
            coinciden.append(h)
        else:
            resto.append(h)
    return coinciden, resto


def _fecha_legible(iso: str | None) -> str:
    """2024-08-20 -> ago 2024"""
    if not iso:
        return "actualidad"
    meses = ["ene", "feb", "mar", "abr", "may", "jun",
             "jul", "ago", "sep", "oct", "nov", "dic"]
    partes = str(iso).split("-")
    if len(partes) >= 2 and partes[1].isdigit():
        return f"{meses[int(partes[1]) - 1]} {partes[0]}"
    return str(iso)


# --------------------------------------------------------------------------
PLANTILLA = """<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<title>{nombre} — {titulo_vacante}</title>
<style>
  @page {{ size: letter; margin: 1.2cm; }}
  body {{ font-family: -apple-system, "Segoe UI", Roboto, sans-serif;
         font-size: 9.8pt; line-height: 1.35; color: #1a1a1a; max-width: 19cm;
         margin: 0 auto; padding: 1cm; }}
  h1 {{ font-size: 17pt; margin: 0 0 2px; letter-spacing: -0.3px; }}
  .cargo {{ color: #555; font-size: 10.5pt; margin-bottom: 5px; }}
  .contacto {{ color: #555; font-size: 9pt; margin-bottom: 12px;
              border-bottom: 1.5px solid #1a1a1a; padding-bottom: 9px; }}
  .resumen {{ margin-bottom: 4px; }}
  h2 {{ font-size: 9.5pt; text-transform: uppercase; letter-spacing: 1.1px;
       color: #1a1a1a; margin: 13px 0 6px; border-bottom: 1px solid #ddd;
       padding-bottom: 2px; }}
  .item {{ margin-bottom: 9px; }}
  .item-titulo {{ font-weight: 600; }}
  .item-meta {{ color: #666; font-size: 9pt; }}
  ul {{ margin: 3px 0 0; padding-left: 16px; }}
  li {{ margin-bottom: 2px; }}
  a {{ color: #1a1a1a; }}
  .tag {{ display: inline-block; background: #f0f0f0; padding: 1px 6px;
         border-radius: 3px; margin: 0 3px 3px 0; font-size: 9pt; }}
  .tag.on {{ background: #1a1a1a; color: #fff; }}
  @media print {{ body {{ padding: 0; }} }}
</style></head><body>

<h1>{nombre}</h1>
<div class="cargo">{cargo}</div>
<div class="contacto">{contacto}</div>
<div class="resumen">{resumen}</div>

{secciones}

</body></html>
"""


def construir_hv(perfil: dict, vacante: dict) -> str:
    terminos = terminos_del_aviso(vacante["descripcion"])
    ident = perfil["identificacion"]

    contacto = " · ".join(
        filter(None, [ident.get("ciudad"), ident.get("celular"),
                      ident.get("email"), ident.get("github")])
    )

    partes = []

    # Experiencia
    partes.append("<h2>Experiencia</h2>")
    for exp in perfil.get("experiencia_tecnica_formal", []):
        logros = "".join(
            f"<li>{html.escape(l)}</li>"
            for l in exp.get("logros", [])
            if not l.startswith(("PENDIENTE", "POR CONFIRMAR"))
        )
        tec = ", ".join(exp.get("tecnologias", []))
        periodo = f"{_fecha_legible(exp.get('inicio'))} – {_fecha_legible(exp.get('fin'))}"
        partes.append(
            f'<div class="item">'
            f'<div class="item-titulo">{html.escape(exp["cargo"])} — {html.escape(exp["empresa"])}</div>'
            f'<div class="item-meta">{periodo} · {tec}</div>'
            f"<ul>{logros}</ul></div>"
        )

    # Proyectos, ordenados por relevancia para este aviso
    partes.append("<h2>Proyectos</h2>")
    for proy in ordenar_proyectos(perfil, terminos):
        stack = ", ".join(proy.get("stack", []))
        caracteristicas = "".join(
            f"<li>{html.escape(c)}</li>"
            for c in proy.get("caracteristicas_tecnicas", [])[:3]
        )
        url = proy.get("url") or proy.get("repo") or ""
        enlace = f' · <a href="{url}">{url}</a>' if url else ""
        partes.append(
            f'<div class="item">'
            f'<div class="item-titulo">{html.escape(proy["nombre"])}</div>'
            f'<div class="item-meta">{stack} · {proy.get("estado", "")}{enlace}</div>'
            f'<div>{html.escape(proy["resumen"])}</div>'
            f"<ul>{caracteristicas}</ul></div>"
        )

    # Habilidades: primero las que pide el aviso
    coinciden, resto = habilidades_destacadas(perfil, vacante["descripcion"])
    tags = "".join(f'<span class="tag on">{html.escape(h)}</span>' for h in coinciden)
    tags += "".join(f'<span class="tag">{html.escape(h)}</span>' for h in resto)
    partes.append(f"<h2>Habilidades técnicas</h2><div>{tags}</div>")

    # Formación
    partes.append("<h2>Formación</h2>")
    for f in perfil.get("formacion", []):
        if f.get("semestre"):
            detalle = f"{f['semestre'].split()[0]}° semestre de 8 · en curso"
        elif f.get("fecha_grado"):
            detalle = f"graduado {_fecha_legible(f['fecha_grado'])}"
        else:
            detalle = f.get("estado", "")
        partes.append(
            f'<div class="item">'
            f'<div class="item-titulo">{html.escape(f["titulo"])}</div>'
            f'<div class="item-meta">{html.escape(f["institucion"])} · {detalle}</div></div>'
        )

    idiomas = " · ".join(f"{i['idioma']}: {i['nivel']}" for i in perfil.get("idiomas", []))
    partes.append(f'<h2>Idiomas</h2><div>{html.escape(idiomas)}</div>')

    return PLANTILLA.format(
        nombre=html.escape(ident["nombre"]),
        cargo=html.escape(vacante["titulo"]),
        titulo_vacante=html.escape(vacante["titulo"]),
        contacto=html.escape(contacto),
        resumen=html.escape(perfil.get("resumen_profesional", "")),
        secciones="\n".join(partes),
    )


# --------------------------------------------------------------------------
def construir_carta(perfil: dict, vacante: dict) -> str | None:
    from anthropic import APIConnectionError, APIStatusError

    from scoring import cliente, MODELO

    sistema = Path("prompts/system_carta.txt").read_text(encoding="utf-8")

    mensaje = (
        "<perfil>\n"
        f"{json.dumps(perfil, ensure_ascii=False, indent=2)}\n"
        "</perfil>\n\n"
        "<vacante>\n"
        f"Título: {vacante['titulo']}\n"
        f"Empresa: {vacante['empresa'] or 'no publicada'}\n"
        f"Descripción:\n{(vacante['descripcion'] or '')[:8000]}\n"
        "</vacante>\n\n"
        "Escribe la carta de presentación."
    )

    try:
        respuesta = cliente().messages.create(
            model=MODELO,
            max_tokens=700,
            system=sistema,
            messages=[{"role": "user", "content": mensaje}],
        )
    except (APIStatusError, APIConnectionError) as e:
        print(f"\nNo se pudo generar la carta: {e}")
        return None

    textos = [b.text for b in respuesta.content if getattr(b, "type", None) == "text"]
    return "\n".join(textos).strip() if textos else None


# --------------------------------------------------------------------------
def main() -> None:
    p = argparse.ArgumentParser(description="Genera HV y carta para una vacante")
    p.add_argument("vacante_id", type=int)
    p.add_argument("--sin-carta", action="store_true", help="solo la HV, sin costo")
    args = p.parse_args()

    vacante = datos_vacante(args.vacante_id)
    if not vacante:
        print(f"No existe la vacante {args.vacante_id}.")
        return

    perfil = json.loads(Path("perfil.json").read_text(encoding="utf-8"))
    SALIDAS.mkdir(exist_ok=True)

    print(f"\n{vacante['titulo']} — {vacante['empresa'] or 'sin empresa'}")
    if vacante.get("puntaje") is not None:
        print(f"Puntaje: {vacante['puntaje']}")

    # Hoja de vida
    hv = construir_hv(perfil, vacante)
    ruta_hv = SALIDAS / f"{args.vacante_id}_hv.html"
    ruta_hv.write_text(hv, encoding="utf-8")
    guardar_documento(args.vacante_id, "hv", hv, str(ruta_hv))
    print(f"\nHV:    {ruta_hv}")

    # Carta
    if args.sin_carta:
        print("Carta: omitida (--sin-carta)")
    else:
        carta = construir_carta(perfil, vacante)
        if carta:
            ruta_carta = SALIDAS / f"{args.vacante_id}_carta.txt"
            ruta_carta.write_text(carta, encoding="utf-8")
            guardar_documento(args.vacante_id, "carta", carta, str(ruta_carta))
            print(f"Carta: {ruta_carta}\n")
            print("-" * 60)
            print(carta)
            print("-" * 60)

    print("\nAbre el HTML en el navegador y usa Ctrl+P -> Guardar como PDF.\n")


if __name__ == "__main__":
    main()
