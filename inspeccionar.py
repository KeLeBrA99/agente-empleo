"""
Imprime la estructura de la primera tarjeta de resultados para identificar
los selectores correctos de empresa y ubicación.

    python inspeccionar.py
"""

from bs4 import BeautifulSoup

from scraper.cliente import ClienteHTTP
from scraper.computrabajo import url_busqueda

html = ClienteHTTP().obtener(url_busqueda("desarrollador junior"))
if not html:
    raise SystemExit("No se pudo descargar la página")

sopa = BeautifulSoup(html, "html.parser")
tarjeta = sopa.select_one("article.box_offer")

if not tarjeta:
    raise SystemExit("No se encontró la tarjeta")

print("=" * 70)
print("HTML DE LA PRIMERA TARJETA")
print("=" * 70)
print(tarjeta.prettify()[:4000])

print("\n" + "=" * 70)
print("TODOS LOS NODOS CON TEXTO")
print("=" * 70)
for nodo in tarjeta.find_all(["a", "p", "span", "h1", "h2", "h3", "div"]):
    texto = nodo.get_text(strip=True)
    if texto and len(texto) < 90 and not nodo.find(["a", "p", "span", "h2"]):
        clases = ".".join(nodo.get("class", [])) or "(sin clase)"
        print(f"{nodo.name:5} | {clases:35} | {texto}")
