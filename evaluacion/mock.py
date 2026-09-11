"""
Evaluador simulado. Aplica heurísticas simples en lugar de llamar al modelo,
para poder probar todo el flujo sin gastar saldo.

Devuelve exactamente la misma estructura que el evaluador real, así que
intercambiarlos no requiere tocar el resto del código.
"""

from __future__ import annotations

import re

# Señales de que la vacante pide más experiencia de la que hay
PATRON_ANIOS = re.compile(r"(\d+)\s*(?:\+|o m[áa]s)?\s*a[ñn]os?\s+de\s+experiencia", re.I)

STACK_PROPIO = {
    "python": 12, "django": 12, "fastapi": 12, "react": 10,
    "postgresql": 6, "mysql": 6, "docker": 5, "git": 3,
    "rest": 5, "api": 4, "power bi": 4, "sql": 4,
}

STACK_AJENO = {"java", "spring", ".net", "c#", "php", "angular", "laravel", "abap"}

SENALES_FRAUDE = (
    "multinivel", "independiente sin jefe", "solo comisión", "solo comision",
    "inversión inicial", "inversion inicial", "libertad financiera",
    "network marketing", "reclutamiento de personas",
)


def evaluar_mock(vacante: dict, perfil: dict) -> dict:
    texto = f"{vacante['titulo']} {vacante['descripcion']}".lower()

    puntaje = 50
    cumple: list[dict] = []
    brechas: list[dict] = []
    excluyentes: list[str] = []

    # Coincidencias de stack
    for tecnologia, peso in STACK_PROPIO.items():
        if tecnologia in texto:
            puntaje += peso
            cumple.append(
                {"requisito": tecnologia, "evidencia": "aparece en habilidades del perfil"}
            )

    # Stack ajeno
    ajenas = [t for t in STACK_AJENO if t in texto]
    if ajenas:
        puntaje -= 25
        brechas.append(
            {
                "requisito": f"stack {', '.join(ajenas)}",
                "excluyente": True,
                "como_mitigar": None,
            }
        )
        excluyentes.append(f"stack {ajenas[0]}")

    # Años de experiencia exigidos
    encontrados = [int(a) for a in PATRON_ANIOS.findall(texto)]
    if encontrados:
        exigidos = max(encontrados)
        if exigidos >= 2:
            puntaje -= 30
            excluyentes.append(f"{exigidos} años de experiencia")
            brechas.append(
                {
                    "requisito": f"{exigidos} años de experiencia",
                    "excluyente": True,
                    "como_mitigar": "proyectos propios como argumento parcial",
                }
            )

    # Nivel del cargo
    if any(p in texto for p in ("senior", "líder", "lider", "arquitecto", "jefe")):
        puntaje -= 20
        excluyentes.append("cargo de nivel superior")

    if any(p in texto for p in ("junior", "jr", "trainee", "sin experiencia")):
        puntaje += 15

    # Salario contra el piso del perfil
    piso = perfil.get("restricciones", {}).get("salario_minimo_aceptable_cop")
    if isinstance(piso, int) and vacante.get("salario_max"):
        if vacante["salario_max"] < piso:
            puntaje -= 20
            brechas.append(
                {
                    "requisito": "salario bajo el piso definido",
                    "excluyente": False,
                    "como_mitigar": "negociar o descartar",
                }
            )

    # Fraude
    fraude = sum(1 for s in SENALES_FRAUDE if s in texto)
    if not vacante.get("empresa"):
        fraude += 1
    fraude = min(fraude, 3)
    if fraude >= 2:
        puntaje = min(puntaje, 20)

    puntaje = max(0, min(100, puntaje))

    if excluyentes:
        puntaje = min(puntaje, 35)

    if puntaje >= 60:
        veredicto = "postular"
    elif puntaje >= 40:
        veredicto = "dudoso"
    else:
        veredicto = "descartar"

    return {
        "puntaje": puntaje,
        "veredicto": veredicto,
        "cumple": cumple[:6],
        "brechas": brechas,
        "excluyentes_fallan": excluyentes,
        "gancho": None,  # el mock no inventa texto: eso es trabajo del modelo real
        "senal_fraude": fraude,
        "razonamiento": "Evaluación simulada por heurísticas, sin modelo.",
    }
