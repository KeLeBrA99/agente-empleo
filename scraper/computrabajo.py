"""
Parser de Computrabajo Colombia.

Los SELECTORES están arriba y aislados a propósito: cuando el portal cambie su
HTML (va a pasar), este es el único bloque que hay que tocar.

Verificación rápida de selectores:
    python -m scraper.computrabajo --debug
Eso guarda la página en debug_lista.html para que la abras y compares.
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import date, timedelta
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .cliente import ClienteHTTP

log = logging.getLogger(__name__)

BASE = "https://co.computrabajo.com"

# --- Bloque frágil: verificar contra el HTML real antes de confiar ----------
SELECTORES = {
    "tarjeta": "article.box_offer",
    "titulo": "a.js-o-link",
    "empresa": "a.fc_base.t_ellipsis",
    "ubicacion": "span.mr10",
    "fecha": "p.fs13.fc_aux",
}

MESES = {
    "ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6,
    "jul": 7, "ago": 8, "sep": 9, "oct": 10, "nov": 11, "dic": 12,
}


def url_busqueda(termino: str, ciudad: str = "bogota-dc", pagina: int = 1) -> str:
    slug = termino.strip().lower().replace(" ", "-")
    base = f"{BASE}/trabajo-de-{slug}-en-{ciudad}"
    return base if pagina == 1 else f"{base}?p={pagina}"


def _texto(nodo, selector: str) -> str | None:
    if not nodo:
        return None
    encontrado = nodo.select_one(selector)
    return encontrado.get_text(strip=True) if encontrado else None


def _parsear_fecha(texto: str | None) -> date | None:
    """Computrabajo usa 'Hoy', 'Ayer' o '12 mar'. Devuelve None si no reconoce."""
    if not texto:
        return None
    t = texto.strip().lower()
    if "hace" in t and ("hora" in t or "minuto" in t):
        return date.today()
    if "hoy" in t:
        return date.today()
    if "ayer" in t:
        return date.today() - timedelta(days=1)
    m = re.search(r"(\d{1,2})\s+([a-záéíóú]{3})", t)
    if m and m.group(2)[:3] in MESES:
        dia, mes = int(m.group(1)), MESES[m.group(2)[:3]]
        anio = date.today().year
        candidata = date(anio, mes, dia)
        # Si sale en el futuro, era del año pasado
        return candidata if candidata <= date.today() else date(anio - 1, mes, dia)
    return None


def _parsear_salario(texto: str) -> tuple[int | None, int | None]:
    """Extrae montos en COP de textos tipo '$ 2.500.000 a $ 3.000.000'."""
    montos = [
        int(m.replace(".", "").replace(",", ""))
        for m in re.findall(r"\$?\s*([\d][\d.,]{5,})", texto)
    ]
    montos = [m for m in montos if 500_000 <= m <= 50_000_000]
    if not montos:
        return None, None
    return min(montos), (max(montos) if len(montos) > 1 else None)
def _ubicacion(tarjeta) -> str | None:
    """Entre los candidatos con clase mr10, descarta calificaciones (4,5) y
    devuelve el primero que parezca un lugar."""
    for nodo in tarjeta.select("span.mr10, p.mr10, span.mr5"):
        texto = nodo.get_text(strip=True)
        if not texto or re.fullmatch(r"\d[,.]\d", texto):
            continue
        if re.search(r"[A-Za-zÁÉÍÓÚáéíóúÑñ]{3,}", texto):
            return texto
    return None

def parsear_lista(html: str) -> list[dict]:
    """Extrae las vacantes de una página de resultados."""
    sopa = BeautifulSoup(html, "html.parser")
    tarjetas = sopa.select(SELECTORES["tarjeta"])
    if not tarjetas:
           log.info("Sin resultados en esta página (fin de la paginación o selector cambiado).")
           return []
    resultados = []
    for t in tarjetas:
        enlace = t.select_one(SELECTORES["titulo"])
        if not enlace or not enlace.get("href"):
            continue

        url = urljoin(BASE, enlace["href"]).split("#")[0]
        ultimo = url.rstrip("/").split("/")[-1].split("?")[0]
        coincidencia = re.search(r"([0-9A-F]{16,})$", ultimo)
        id_externo = coincidencia.group(1) if coincidencia else ultimo

        resultados.append(
            {
                "fuente": "computrabajo",
                "id_externo": id_externo,
                "url": url,
                "titulo": enlace.get_text(strip=True),
                "empresa": _texto(t, SELECTORES["empresa"]),
                "ubicacion": _ubicacion(t),
                "publicada_en": _parsear_fecha(_texto(t, SELECTORES["fecha"])),
            }
        )
    return resultados


def parsear_detalle(html: str) -> dict:
    """Extrae la descripción completa y el salario de la página de la vacante."""
    sopa = BeautifulSoup(html, "html.parser")

    for basura in sopa.select("script, style, nav, footer, header"):
        basura.decompose()

    cuerpo = sopa.select_one("div.box_detail, article, main") or sopa
    descripcion = cuerpo.get_text("\n", strip=True)
    descripcion = re.sub(r"\n{3,}", "\n\n", descripcion)

    salario_min, salario_max = _parsear_salario(descripcion[:2000])

    texto_bajo = descripcion.lower()
    if "remoto" in texto_bajo or "teletrabajo" in texto_bajo:
        modalidad = "remoto"
    elif "híbrid" in texto_bajo or "hibrid" in texto_bajo:
        modalidad = "hibrido"
    elif "presencial" in texto_bajo:
        modalidad = "presencial"
    else:
        modalidad = "desconocida"

    return {
        "descripcion": descripcion,
        "salario_min": salario_min,
        "salario_max": salario_max,
        "modalidad": modalidad,
    }


def hash_contenido(titulo: str, descripcion: str) -> str:
    return hashlib.sha256(f"{titulo}||{descripcion}".encode("utf-8")).hexdigest()


def recolectar(
    terminos: list[str],
    paginas_por_termino: int = 2,
    cliente: ClienteHTTP | None = None,
) -> list[dict]:
    """Recorre las búsquedas y devuelve vacantes con detalle completo."""
    cliente = cliente or ClienteHTTP()
    vistos: set[str] = set()
    vacantes: list[dict] = []

    for termino in terminos:
        for pagina in range(1, paginas_por_termino + 1):
            html = cliente.obtener(url_busqueda(termino, pagina=pagina))
            if not html:
                break

            encontradas = parsear_lista(html)
            log.info("'%s' pág.%s → %s vacantes", termino, pagina, len(encontradas))
            if not encontradas:
                break

            for v in encontradas:
                if v["id_externo"] in vistos:
                    continue
                vistos.add(v["id_externo"])

                detalle_html = cliente.obtener(v["url"])
                if not detalle_html:
                    continue

                v.update(parsear_detalle(detalle_html))
                v["hash_contenido"] = hash_contenido(v["titulo"], v["descripcion"])
                vacantes.append(v)

    return vacantes


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if "--debug" in sys.argv:
        html = ClienteHTTP().obtener(url_busqueda("desarrollador junior"))
        if html:
            with open("debug_lista.html", "w", encoding="utf-8") as f:
                f.write(html)
            print("Guardado debug_lista.html")
            print(f"Tarjetas detectadas: {len(parsear_lista(html))}")
    else:
        for v in recolectar(["desarrollador junior"], paginas_por_termino=1):
            print(f"[{v['id_externo']}] {v['titulo']} — {v['empresa']} — {v['ubicacion']}")
