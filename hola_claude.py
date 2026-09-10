"""
Paso 1: verificar que tu equipo le habla al modelo.
Ejecutar con:  python hola_claude.py
"""

import os

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()  # lee el archivo .env

client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

respuesta = client.messages.create(
    model="claude-sonnet-5",
    max_tokens=300,
    system="Responde en español, en dos frases máximo.",
    messages=[
        {
            "role": "user",
            "content": "Salúdame y dime en una frase qué es un agente de IA.",
        }
    ],
)

print(respuesta.content[0].text)
print("---")
print(f"Tokens entrada: {respuesta.usage.input_tokens}")
print(f"Tokens salida:  {respuesta.usage.output_tokens}")
