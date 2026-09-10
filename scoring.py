"""
Servicio de scoring: vacante + perfil -> evaluación validada.

Dependencias:
    pip install anthropic pydantic sqlalchemy psycopg[binary]
Variable de entorno:
    ANTHROPIC_API_KEY
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal

from anthropic import Anthropic
from pydantic import BaseModel, Field, ValidationError

MODELO = "claude-sonnet-4-6"
client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

SYSTEM_PROMPT = Path("prompts/system_scoring.txt").read_text(encoding="utf-8")
USER_TEMPLATE = Path("prompts/user_scoring.txt").read_text(encoding="utf-8")

# Títulos que no vale la pena mandar al modelo
DESCARTE_TITULO = (
    "senior", "sr.", "líder técnico", "tech lead", "arquitecto", "gerente",
    "java", ".net", "php", "sap abap", "progress 4gl",
    "comercial", "asesor", "ejecutivo", "aprendiz", "practicante", "contable",
)

# --------------------------------------------------------------------------
# Contrato de salida
# --------------------------------------------------------------------------
class Cumplido(BaseModel):
    requisito: str
    evidencia: str


class Brecha(BaseModel):
    requisito: str
    excluyente: bool
    como_mitigar: str | None = None


class Evaluacion(BaseModel):
    puntaje: int = Field(ge=0, le=100)
    veredicto: Literal["postular", "dudoso", "descartar"]
    cumple: list[Cumplido] = []
    brechas: list[Brecha] = []
    excluyentes_fallan: list[str] = []
    gancho: str | None = None
    senal_fraude: int = Field(ge=0, le=3, default=0)
    razonamiento: str


# --------------------------------------------------------------------------
# Filtro barato: evita gastar llamadas
# --------------------------------------------------------------------------
def vale_la_pena_evaluar(vacante: dict) -> bool:
    titulo = vacante["titulo"].lower()
    return not any(t in titulo for t in DESCARTE_TITULO)


# --------------------------------------------------------------------------
# Llamada al modelo
# --------------------------------------------------------------------------
def evaluar(vacante: dict, perfil: dict, reintentos: int = 1) -> Evaluacion | None:
    mensaje = USER_TEMPLATE.format(
        perfil_json=json.dumps(perfil, ensure_ascii=False, indent=2),
        titulo=vacante["titulo"],
        empresa=vacante.get("empresa") or "no publicada",
        ubicacion=vacante.get("ubicacion") or "no publicada",
        modalidad=vacante.get("modalidad") or "no publicada",
        salario=_formatear_salario(vacante),
        descripcion=vacante["descripcion"][:12_000],
    )

    for intento in range(reintentos + 1):
        respuesta = client.messages.create(
            model=MODELO,
            max_tokens=1500,
            temperature=0,
            system=SYSTEM_PROMPT,
            messages=[
                {"role": "user", "content": mensaje},
                # Prellenar la llave fuerza JSON desde el primer token
                {"role": "assistant", "content": "{"},
            ],
        )

        crudo = "{" + respuesta.content[0].text
        try:
            return Evaluacion.model_validate_json(crudo)
        except (ValidationError, json.JSONDecodeError):
            if intento == reintentos:
                return None  # se guarda la vacante sin evaluación
    return None


def _formatear_salario(vacante: dict) -> str:
    lo, hi = vacante.get("salario_min"), vacante.get("salario_max")
    if not lo and not hi:
        return "no publicado"
    if lo and hi:
        return f"${lo:,} - ${hi:,} COP"
    return f"${(lo or hi):,} COP"


# --------------------------------------------------------------------------
# Uso desde el job diario
# --------------------------------------------------------------------------
def procesar_lote(vacantes: list[dict], perfil: dict, perfil_version: int) -> list[dict]:
    """Devuelve filas listas para insertar en la tabla `evaluaciones`."""
    filas = []
    for v in vacantes:
        if not vale_la_pena_evaluar(v):
            continue
        ev = evaluar(v, perfil)
        if ev is None:
            continue
        filas.append(
            {
                "vacante_id": v["id"],
                "perfil_version": perfil_version,
                "puntaje": ev.puntaje,
                "veredicto": ev.veredicto,
                "cumple": [c.model_dump() for c in ev.cumple],
                "brechas": [b.model_dump() for b in ev.brechas],
                "excluyentes_fallan": ev.excluyentes_fallan,
                "gancho": ev.gancho,
                "senal_fraude": ev.senal_fraude,
                "razonamiento": ev.razonamiento,
                "modelo": MODELO,
            }
        )
    return filas
