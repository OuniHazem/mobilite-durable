"""
ingestion/lille_client.py
=========================
Client API Lille — Projet Mobilité Durable
Sources :
  - Vélos V'Lille : GBFS ilévia (media.ilevia.fr/opendata)
  - Qualité de l'air : Atmo HDF ArcGIS FeatureServer (ind_hdf_3j)
  - Trafic : TomTom Traffic Flow Segment Data
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import requests

from config.settings import settings
from ingestion.base_client import BaseClient
from utils.logger import get_logger
from utils.tomtom_traffic import fetch_traffic

log = get_logger(__name__)

# Code qualité air Atmo HDF → mapping indices
_ATMO_CODE_TO_INDICE = {
    1: "Bon",
    2: "Moyen",
    3: "Dégradé",
    4: "Mauvais",
    5: "Très mauvais",
    6: "Extrêmement mauvais",
}

# Points de mesure trafic — axes principaux Lille Métropole
_LILLE_TRAFFIC_POINTS: list[dict[str, Any]] = [
    {"id": "lille_gare", "nom": "Gare Lille Flandres", "lat": 50.6369, "lon": 3.0729},
    {"id": "lille_grande_place", "nom": "Grand'Place", "lat": 50.6360, "lon": 3.0640},
    {"id": "lille_mairie", "nom": "Mairie de Lille", "lat": 50.6329, "lon": 3.0586},
    {"id": "lille_porte_douai", "nom": "Porte de Douai", "lat": 50.6235, "lon": 3.0560},
    {"id": "lille_vaubaix", "nom": "Boulevard Vauban", "lat": 50.6390, "lon": 3.0435},
    {"id": "lille_roubaix_rd", "nom": "Route de Roubaix", "lat": 50.6550, "lon": 3.0850},
    {"id": "lille_periph_nord", "nom": "Périphérique Nord", "lat": 50.6500, "lon": 3.0950},
    {"id": "lille_periph_sud", "nom": "Périphérique Sud", "lat": 50.6100, "lon": 3.1000},
    {"id": "villeneuve_centre", "nom": "Villeneuve-d'Ascq Centre", "lat": 50.6320, "lon": 3.1300},
    {"id": "roubaix_centre", "nom": "Roubaix Centre", "lat": 50.6940, "lon": 3.1750},
    {"id": "tourcoing_centre", "nom": "Tourcoing Centre", "lat": 50.7240, "lon": 3.1610},
    {"id": "lambersart_pont", "nom": "Lambersart Pont", "lat": 50.6510, "lon": 3.0280},
]


class LilleClient(BaseClient):
    """
    Client API Lille utilisant :
      - GBFS pour les vélos V'Lille (media.ilevia.fr)
      - Atmo HDF ArcGIS pour la qualité de l'air
      - ODS Explore v2.1 pour le trafic (si disponible)
    """

    base_url = settings.lille_api_base_url

    def __init__(self) -> None:
        super().__init__()
        self._gbfs_base = settings.lille_gbfs_base_url

    def get_velos(self) -> list[dict[str, Any]]:
        """
        Disponibilité temps réel des stations V'Lille via GBFS.
        Combine station_information (nom, localisation, capacité)
        et station_status (vélos disponibles, état).
        """
        try:
            info_resp = self._session.get(
                f"{self._gbfs_base}/station_information.json",
                timeout=settings.http_timeout_s,
            )
            info_resp.raise_for_status()
            info_data = info_resp.json().get("data", {}).get("stations", [])

            status_resp = self._session.get(
                f"{self._gbfs_base}/station_status.json",
                timeout=settings.http_timeout_s,
            )
            status_resp.raise_for_status()
            status_data = status_resp.json().get("data", {}).get("stations", [])

            status_map = {s["station_id"]: s for s in status_data}
            records = []
            for station in info_data:
                sid = station.get("station_id", "")
                status = status_map.get(sid, {})
                records.append({
                    "station_id": sid,
                    "name": station.get("name", ""),
                    "lat": station.get("lat"),
                    "lon": station.get("lon"),
                    "capacity": station.get("capacity", 0),
                    "available_bikes": status.get("num_bikes_available", 0),
                    "available_docks": status.get("num_docks_available", 0),
                    "is_installed": status.get("is_installed", False),
                    "is_renting": status.get("is_renting", False),
                    "is_returning": status.get("is_returning", False),
                    "last_reported": status.get("last_reported"),
                })

            log.debug(f"LilleClient.get_velos : {len(records)} stations")
            return records
        except Exception as exc:
            log.error(f"LilleClient.get_velos erreur : {exc}")
            return []

    def get_qualite_air(self) -> list[dict[str, Any]]:
        """
        Indice de qualité de l'air via Atmo HDF ArcGIS FeatureServer.
        Récupère l'indice ATMO 3 jours (J-1, J, J+1) pour les communes
        de la MEL (code_zone commençant par 59).
        """
        try:
            params = {
                "where": "code_zone LIKE '59%'",
                "outFields": "date_dif,date_ech,code_zone,lib_zone,code_qual,lib_qual,coul_qual",
                "returnGeometry": "false",
                "f": "json",
                "resultRecordCount": 500,
                "orderByFields": "date_ech DESC",
            }
            resp = self._session.get(
                settings.lille_atmo_api_url,
                params=params,
                timeout=settings.http_timeout_s,
            )
            resp.raise_for_status()
            data = resp.json()

            features = data.get("features", [])
            records = []
            for feat in features:
                attr = feat.get("attributes", {})
                date_ech_ms = attr.get("date_ech")
                date_dif_ms = attr.get("date_dif")
                code_qual = attr.get("code_qual")

                records.append({
                    "station_id": attr.get("code_zone", ""),
                    "ville": "Lille",
                    "indice_atmo": float(code_qual) if code_qual else None,
                    "lib_qual": attr.get("lib_qual", ""),
                    "lib_zone": attr.get("lib_zone", ""),
                    "pm25": None,
                    "pm10": None,
                    "no2": None,
                    "o3": None,
                    "timestamp": (
                        datetime.fromtimestamp(date_ech_ms / 1000, tz=timezone.utc)
                        if date_ech_ms
                        else None
                    ),
                })

            log.debug(f"LilleClient.get_qualite_air : {len(records)} mesures")
            return records
        except Exception as exc:
            log.error(f"LilleClient.get_qualite_air erreur : {exc}")
            return []

    def get_trafic(self) -> list[dict[str, Any]]:
        """État du trafic temps réel sur le réseau routier lillois via TomTom."""
        records = []
        for pt in _LILLE_TRAFFIC_POINTS:
            data = fetch_traffic(pt["lat"], pt["lon"])
            if data is None:
                continue
            coords = data.get("coordinates", [])
            lat_debut = coords[0]["latitude"] if len(coords) > 0 else pt["lat"]
            lon_debut = coords[0]["longitude"] if len(coords) > 0 else pt["lon"]
            lat_fin = coords[-1]["latitude"] if len(coords) > 1 else None
            lon_fin = coords[-1]["longitude"] if len(coords) > 1 else None

            records.append({
                "troncon_id": pt["id"],
                "nom": pt["nom"],
                "ville": "Lille",
                "score_congestion": data["congestion_ratio"],
                "current_speed": data["current_speed"],
                "free_flow_speed": data["free_flow_speed"],
                "confidence": data["confidence"],
                "road_closure": data["road_closure"],
                "lat": lat_debut,
                "lon": lon_debut,
                "lat_fin": lat_fin,
                "lon_fin": lon_fin,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

        log.debug(f"LilleClient.get_trafic : {len(records)} tronçons")
        return records

    def _get_ods(self, dataset_id: str, limit: int = 100) -> list[dict[str, Any]]:
        """
        Appel ODS Explore v2.1 :
        GET /catalog/datasets/<dataset_id>/records?limit=<n>
        Retourne la liste des records (dicts plats).
        """
        url = f"{self.base_url}/{dataset_id}/records"
        params = {"limit": limit}
        try:
            data = self._get(url, params=params)
        except Exception as exc:
            log.error(f"ODS request failed {url}: {exc}")
            return []

        results = data.get("results", [])
        return results
