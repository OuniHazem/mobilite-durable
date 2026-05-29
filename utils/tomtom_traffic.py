"""
utils/tomtom_traffic.py
======================
Client TomTom Traffic Flow Segment Data — Projet Mobilité Durable
Récupère les données de trafic temps réel pour un point GPS donné.
"""

from __future__ import annotations

from typing import Any

import requests

from config.settings import settings
from utils.logger import get_logger

log = get_logger(__name__)


def fetch_traffic(lat: float, lon: float) -> dict[str, Any] | None:
    """
    Interroge TomTom Flow Segment Data pour un point GPS.
    Retourne un dict avec : current_speed, free_flow_speed, confidence,
    congestion_ratio, frc, road_closure, coordinates.
    Retourne None si l'appel échoue.
    """
    try:
        params = {
            "key": settings.tomtom_api_key,
            "point": f"{lat},{lon}",
            "unit": "kmph",
        }
        resp = requests.get(
            settings.tomtom_base_url,
            params=params,
            timeout=settings.http_timeout_s,
        )
        resp.raise_for_status()

        data = resp.json().get("flowSegmentData")
        if data is None:
            log.warning(f"TomTom: pas de flowSegmentData pour ({lat},{lon})")
            return None

        current = data.get("currentSpeed", 0)
        free_flow = data.get("freeFlowSpeed", 1)
        congestion_ratio = round(
            (1 - current / free_flow) * 100 if free_flow > 0 else 0, 1
        )
        # Borné [0, 100]
        congestion_ratio = max(0.0, min(100.0, congestion_ratio))

        coords = data.get("coordinates", {}).get("coordinate", [])

        return {
            "current_speed": current,
            "free_flow_speed": free_flow,
            "confidence": data.get("confidence", 0),
            "congestion_ratio": congestion_ratio,
            "frc": data.get("frc", ""),
            "road_closure": data.get("roadClosure", False),
            "coordinates": coords,
        }

    except Exception as exc:
        log.error(f"TomTom fetch_traffic({lat},{lon}) erreur : {exc}")
        return None
