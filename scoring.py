"""
Evaluador real: manda vacante + perfil al modelo y valida la respuesta.

Requiere ANTHROPIC_API_KEY en el .env y saldo en la cuenta.

Prueba de una sola vacante (sin tocar la base):
    python scoring.py
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Literal

from anthropic import Anthropic, APIConnectionError, APIStatusError
from dotenv import load_dotenv
from pydantic import BaseModel, Field, ValidationError

load_dotenv(override=True)
log = logging.getLogger(__name__)

MODELO = os.environ.get("MODELO_SCORING", "claude-sonnet-5")

SYSTEM_PROMPT = Path("prompts/system_scoring.txt").read_text(encoding="utf-8")

_cliente: Anthropic | None = None


def cliente() -> Anthropic:
    """Se crea una sola vez, y solo cuando de verdad se va a usar."""
    global _cliente
    if _cliente is None:
        _cliente = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _cliente


# --------------------------------------------------------------------------
# Contrato de salida
# --------------------------------------------------------------------------
class Cumplido(BaseModel):
    requisito: str
    evidencia: str


class Brecha(BaseModel):
    requisito: str
    excluyente: bool = False
    como_mitigar: str | None = None


class Evaluacion(BaseModel):
    puntaje: int = Field(ge=0, le=100)
    veredicto: Literal["postular", "dudoso", "descartar"]
    cumple: list[Cumplido] = []
    brechas: list[Brecha] = []
    excluyentes_fallan: list[str] = []
    gancho: str | None = None
    senal_fraude: int = Field(ge=0, le=3, default=0)
    razonamiento: str = ""


def _salario(vacante: dict) -> str:
    lo, hi = vacante.get("salario_min"), vacante.get("salario_max")
    if not lo and not hi:
        return "no publicado"
    if lo and hi:
        return f"${lo:,} - ${hi:,} COP"
    return f"${(lo or hi):,} COP"


def _mensaje(vacante: dict, perfil: dict) -> str:
    """Se construye con f-string en lugar de .format() porque el texto de las
    vacantes suele traer llaves y simbolos que rompen el formateo."""
    perfil_json = json.dumps(perfil, ensure_ascii=False, indent=2)
    descripcion = (vacante.get("descripcion") or "")[:12_000]

    return (
        "<perfil>\n"
        f"{perfil_json}\n"
        "</perfil>\n\n"
        "<vacante>\n"
        f"Titulo: {vacante.get('titulo')}\n"
        f"Empresa: {vacante.get('empresa') or 'no publicada'}\n"
        f"Ubicacion: {vacante.get('ubicacion') or 'no publicada'}\n"
        f"Modalidad publicada: {vacante.get('modalidad') or 'no publicada'}\n"
        f"Salario publicado: {_salario(vacante)}\n"
        "Descripcion:\n"
        f"{descripcion}\n"
        "</vacante>\n\n"
        "Evalua el encaje y responde solo con el objeto JSON."
    )


def _texto_de(respuesta) -> str | None:
    """La respuesta trae varios bloques y el primero puede ser el razonamiento
    interno del modelo. Hay que filtrar por tipo, nunca por posicion."""
    textos = [b.text for b in respuesta.content if getattr(b, "type", None) == "text"]
    if not textos:
        return None

    crudo = "\n".join(textos).strip()
    if crudo.startswith("```"):
        crudo = crudo.split("```")[1].removeprefix("json").strip()
    return crudo


def evaluar(vacante: dict, perfil: dict, reintentos: int = 1) -> Evaluacion | None:
    mensaje = _mensaje(vacante, perfil)

    for intento in range(reintentos + 1):
        try:
            respuesta = cliente().messages.create(
                model=MODELO,
                max_tokens=1200,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": mensaje}],
            )
        except (APIStatusError, APIConnectionError) as e:
            log.warning("Fallo de API (intento %s): %s", intento + 1, e)
            if intento < reintentos:
                time.sleep(5 * (intento + 1))
                continue
            return None

        uso = respuesta.usage
        log.info("Tokens -> entrada: %s | salida: %s", uso.input_tokens, uso.output_tokens)

        crudo = _texto_de(respuesta)
        if crudo is None:
            log.warning("La respuesta no trajo bloque de texto")
            continue

        try:
            return Evaluacion.model_validate_json(crudo)
        except (ValidationError, json.JSONDecodeError) as e:
            log.warning("JSON invalido (intento %s): %s", intento + 1, e)
            log.debug("Respuesta cruda: %s", crudo[:500])

    return None


# --------------------------------------------------------------------------
# Prueba de humo: una sola llamada, sin base de datos
# --------------------------------------------------------------------------
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    perfil = json.loads(Path("perfil.json").read_text(encoding="utf-8"))

    vacante_prueba = {
        "titulo": "Desarrollador Backend Junior Python",
        "empresa": "Empresa de prueba",
        "ubicacion": "Bogota",
        "modalidad": "hibrido",
        "salario_min": 3000000,
        "salario_max": None,
        "descripcion": (
            "Buscamos desarrollador backend junior con conocimientos en Python "
            "y Django REST Framework para unirse al equipo de producto. "
            "Requisitos: manejo de bases de datos relacionales (PostgreSQL o MySQL), "
            "control de versiones con Git, y consumo de APIs REST. "
            "Deseable experiencia con Docker. Se valora formacion tecnica o "
            "tecnologica en desarrollo de software. Minimo 6 meses de experiencia."
        ),
    }

    resultado = evaluar(vacante_prueba, perfil)

    if resultado is None:
        print("\nFALLO: la evaluacion devolvio None. Revisa los mensajes de arriba.")
    else:
        print("\n--- EVALUACION ---")
        print(json.dumps(resultado.model_dump(), ensure_ascii=False, indent=2))
