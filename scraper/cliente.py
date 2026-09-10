"""
Cliente HTTP educado: cabeceras de navegador, pausa entre peticiones y
reintentos con espera creciente. Todo el scraping pasa por aquí.
"""

from __future__ import annotations

import logging
import random
import time

import requests

log = logging.getLogger(__name__)

CABECERAS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-CO,es;q=0.9,en;q=0.8",
    "Connection": "keep-alive",
}


class ClienteHTTP:
    def __init__(self, pausa_min: float = 3.0, pausa_max: float = 6.0):
        self.sesion = requests.Session()
        self.sesion.headers.update(CABECERAS)
        self.pausa_min = pausa_min
        self.pausa_max = pausa_max
        self._ultima_peticion = 0.0

    def _esperar(self) -> None:
        """Pausa aleatoria entre peticiones. La aleatoriedad evita el patrón
        exacto que delata a un bot."""
        transcurrido = time.time() - self._ultima_peticion
        espera = random.uniform(self.pausa_min, self.pausa_max) - transcurrido
        if espera > 0:
            time.sleep(espera)

    def obtener(self, url: str, intentos: int = 3) -> str | None:
        for intento in range(intentos):
            self._esperar()
            try:
                r = self.sesion.get(url, timeout=20)
                self._ultima_peticion = time.time()

                if r.status_code == 200:
                    return r.text

                if r.status_code in (403, 429):
                    espera = 30 * (intento + 1)
                    log.warning("Bloqueo %s en %s. Esperando %ss", r.status_code, url, espera)
                    time.sleep(espera)
                    continue

                if 500 <= r.status_code < 600:
                    time.sleep(5 * (intento + 1))
                    continue

                log.error("HTTP %s en %s", r.status_code, url)
                return None

            except requests.RequestException as e:
                log.warning("Fallo de red (%s). Reintento %s/%s", e, intento + 1, intentos)
                time.sleep(5 * (intento + 1))
                self._ultima_peticion = time.time()

        log.error("Agotados los intentos para %s", url)
        return None
