"""
ingestion/montpellier_client.py
================================
Client Montpellier — Projet Mobilité Durable
Sources :
  - Vélos : GBFS Fifteen (gbfs.theta.fifteen.eu)
  - Air : Atmo Occitanie ArcGIS FeatureServer
  - Trafic : TomTom Traffic Flow Segment Data
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import requests

from config.settings import settings
from utils.logger import get_logger
from utils.tomtom_traffic import fetch_traffic

log = get_logger(__name__)

# Points de mesure trafic — axes principaux Montpellier
_MONTPELLIER_TRAFFIC_POINTS: list[dict[str, Any]] = [
    {"id": "montpellier_comedie", "nom": "Place de la Comédie", "lat": 43.6081, "lon": 3.8795},
    {"id": "montpellier_gare", "nom": "Gare Saint-Roch", "lat": 43.6056, "lon": 3.8838},
    {"id": "montpellier_corum", "nom": "Le Corum", "lat": 43.6120, "lon": 3.8820},
    {"id": "montpellier_jean_jaures", "nom": "Boulevard Jean-Jaurès", "lat": 43.6095, "lon": 3.8730},
    {"id": "montpellier_celleneuve", "nom": "Route de Celleneuve", "lat": 43.6170, "lon": 3.8550},
    {"id": "montpellier_mende", "nom": "Avenue de Mende", "lat": 43.6250, "lon": 3.8680},
    {"id": "montpellier_palavas", "nom": "Route de Palavas", "lat": 43.5800, "lon": 3.8900},
    {"id": "montpellier_sud_a9", "nom": "A9 Sud Montpellier", "lat": 43.5750, "lon": 3.9200},
    {"id": "montpellier_nord_a9", "nom": "A9 Nord Montpellier", "lat": 43.6380, "lon": 3.9100},
    {"id": "montpellier_clemenceau", "nom": "Avenue Clemenceau", "lat": 43.5960, "lon": 3.8820},
    {"id": "montpellier_millon", "nom": "Rue du Professeur Millon", "lat": 43.6010, "lon": 3.8700},
    {"id": "montpellier_antigone", "nom": "Quartier Antigone", "lat": 43.6050, "lon": 3.8920},
]


class MontpellierClient:
    """
    Client Montpellier utilisant :
      - GBFS pour les vélos VéloMagg (standard ouvert)
      - Portail open data M3M pour air/trafic (si disponible)
    """

    def __init__(self) -> None:
        self._gbfs_base = settings.montpellier_gbfs_base_url
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "MobiliteDurable-Pipeline/1.0",
            "Accept": "application/json",
        })

    def get_velos(self) -> list[dict[str, Any]]:
        """
        Disponibilité temps réel des stations VéloMagg via GBFS.
        Combine station_information (nom, localisation, capacité)
        et station_status (vélos disponibles, état).
        """
        try:
            # Récupérer les informations des stations
            info_resp = self._session.get(
                f"{self._gbfs_base}/en/station_information.json",
                timeout=settings.http_timeout_s,
            )
            info_resp.raise_for_status()
            info_data = info_resp.json().get("data", {}).get("stations", [])

            # Récupérer le statut des stations
            status_resp = self._session.get(
                f"{self._gbfs_base}/en/station_status.json",
                timeout=settings.http_timeout_s,
            )
            status_resp.raise_for_status()
            status_data = status_resp.json().get("data", {}).get("stations", [])

            # Fusionner info + status par station_id
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

            log.debug(f"MontpellierClient.get_velos : {len(records)} stations")
            return records
        except Exception as exc:
            log.error(f"MontpellierClient.get_velos erreur : {exc}")
            return []

    def get_qualite_air(self) -> list[dict[str, Any]]:
        """
        Mesures qualité de l'air pour Montpellier via Atmo Occitanie ArcGIS.
        Récupère les concentrations journalières des polluants principaux
        (PM2.5, PM10, NO2, O3) pour les stations de Montpellier.
        """
        try:
            params = {
                "where": "nom_com = 'MONTPELLIER' AND statut_valid = 't'",
                "outFields": "code_station,nom_station,nom_poll,valeur,unite,date_debut",
                "returnGeometry": "false",
                "f": "json",
                "resultRecordCount": 500,
                "orderByFields": "date_debut DESC",
            }
            resp = self._session.get(
                settings.montpellier_atmo_api_url,
                params=params,
                timeout=settings.http_timeout_s,
            )
            resp.raise_for_status()
            data = resp.json()

            features = data.get("features", [])
            if not features:
                log.debug("MontpellierClient.get_qualite_air : aucune mesure")
                return []

            # Regrouper par station+date : pivot polluant → valeur
            stations: dict[tuple[str, Any], dict[str, Any]] = {}
            for feat in features:
                attr = feat.get("attributes", {})
                code = attr.get("code_station", "")
                date_ms = attr.get("date_debut")
                key = (code, date_ms)

                if key not in stations:
                    stations[key] = {
                        "station_id": code,
                        "ville": "Montpellier",
                        "indice_atmo": None,
                        "pm25": None,
                        "pm10": None,
                        "no2": None,
                        "o3": None,
                        "timestamp": date_ms,
                    }

                poll = attr.get("nom_poll", "")
                val = attr.get("valeur")
                if poll == "PM2.5" and val is not None:
                    stations[key]["pm25"] = float(val)
                elif poll == "PM10" and val is not None:
                    stations[key]["pm10"] = float(val)
                elif poll == "NO2" and val is not None:
                    stations[key]["no2"] = float(val)
                elif poll == "O3" and val is not None:
                    stations[key]["o3"] = float(val)

            records = list(stations.values())
            log.debug(f"MontpellierClient.get_qualite_air : {len(records)} mesures")
            return records
        except Exception as exc:
            log.error(f"MontpellierClient.get_qualite_air erreur : {exc}")
            return []

    def get_trafic(self) -> list[dict[str, Any]]:
        """État du trafic temps réel sur le réseau montpelliérain via TomTom."""
        records = []
        for pt in _MONTPELLIER_TRAFFIC_POINTS:
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
                "ville": "Montpellier",
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

        log.debug(f"MontpellierClient.get_trafic : {len(records)} tronçons")
        return records
