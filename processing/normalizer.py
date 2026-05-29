"""
processing/normalizer.py
========================
Nettoyage et normalisation des données brutes — Projet Mobilité Durable

Transforme les dicts bruts issus des clients CKAN/GTFS-RT
en DataFrames pandas propres et homogènes,
prêts pour kpi_engine.py et storage/database.py.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pandas as pd

from processing.schemas import QualiteAir, RetardTC, StationVelo, TronconTrafic, VehiculeTC
from utils.logger import get_logger

log = get_logger(__name__)


class Normalizer:
    """
    Normalise les données brutes de chaque source.
    Chaque méthode retourne un DataFrame pandas avec des colonnes garanties.
    """

    # ------------------------------------------------------------------
    # Vélos
    # ------------------------------------------------------------------

    def normalize_velos(self, raw: list[dict[str, Any]], ville: str) -> pd.DataFrame:
        """
        Normalise les données de stations vélos.
        Retourne un DataFrame avec les colonnes de StationVelo.
        """
        records = []
        for item in raw:
            try:
                station = StationVelo(
                    station_id=str(item.get("station_id") or item.get("id") or item.get("number", "")),
                    nom_station=item.get("name") or item.get("nom") or item.get("address"),
                    ville=ville,
                    velos_disponibles=int(item.get("available_bikes") or item.get("velos_dispo") or item.get("nbVelosDispo", 0)),
                    capacite=int(item.get("bike_stands") or item.get("capacite") or item.get("nbPlacesDisponibles", 0) + int(item.get("available_bikes", 0))),
                    en_service=_parse_bool(item.get("status") or item.get("en_service", True)),
                    latitude=_parse_float(item.get("lat") or item.get("latitude") or item.get("position", {}).get("lat")),
                    longitude=_parse_float(item.get("lng") or item.get("longitude") or item.get("position", {}).get("lng")),
                    timestamp=_parse_ts(item.get("last_update") or item.get("timestamp")),
                )
                records.append(station.model_dump())
            except Exception as exc:
                log.warning(f"normalize_velos [{ville}] item ignoré : {exc}")
                continue

        df = pd.DataFrame(records) if records else pd.DataFrame(
            columns=["station_id", "nom_station", "ville", "velos_disponibles",
                     "capacite", "en_service", "latitude", "longitude", "timestamp"]
        )
        log.debug(f"normalize_velos [{ville}] : {len(df)} stations")
        return df

    # ------------------------------------------------------------------
    # Transports en commun
    # ------------------------------------------------------------------

    def normalize_tc(self, raw: list[dict[str, Any]], ville: str) -> pd.DataFrame:
        """
        Normalise les retards TC issus du GTFS-RT.
        Retourne un DataFrame avec les colonnes de RetardTC.
        """
        records = []
        for item in raw:
            try:
                retard = RetardTC(
                    vehicle_id=str(item.get("vehicle_id") or item.get("id", "")),
                    trip_id=str(item.get("trip_id") or ""),
                    ligne_id=str(item.get("route_id") or item.get("ligne_id") or item.get("line", "?")),
                    ville=ville,
                    retard_s=int(item.get("delay") or item.get("retard_s") or 0),
                    latitude=_parse_float(item.get("latitude") or item.get("lat")),
                    longitude=_parse_float(item.get("longitude") or item.get("lon")),
                    timestamp=_parse_ts(item.get("timestamp")),
                )
                records.append(retard.model_dump())
            except Exception as exc:
                log.warning(f"normalize_tc [{ville}] item ignoré : {exc}")
                continue

        df = pd.DataFrame(records) if records else pd.DataFrame(
            columns=["vehicle_id", "trip_id", "ligne_id", "ville",
                     "retard_s", "latitude", "longitude", "timestamp"]
        )
        log.debug(f"normalize_tc [{ville}] : {len(df)} véhicules")
        return df

    # ------------------------------------------------------------------
    # Qualité de l'air
    # ------------------------------------------------------------------

    def normalize_air(self, raw: list[dict[str, Any]], ville: str) -> pd.DataFrame:
        """
        Normalise les mesures de qualité de l'air.
        Retourne un DataFrame avec les colonnes de QualiteAir.
        """
        records = []
        for item in raw:
            try:
                mesure = QualiteAir(
                    station_id=str(item.get("station_id") or item.get("id") or ""),
                    ville=ville,
                    indice_atmo=_parse_float(item.get("indice_atmo") or item.get("indice") or item.get("valeur")),
                    pm25=_parse_float(item.get("pm25") or item.get("PM2.5") or item.get("pm2_5")),
                    pm10=_parse_float(item.get("pm10") or item.get("PM10")),
                    no2=_parse_float(item.get("no2") or item.get("NO2")),
                    o3=_parse_float(item.get("o3") or item.get("O3")),
                    timestamp=_parse_ts(item.get("date_debut") or item.get("timestamp")),
                )
                records.append(mesure.model_dump())
            except Exception as exc:
                log.warning(f"normalize_air [{ville}] item ignoré : {exc}")
                continue

        df = pd.DataFrame(records) if records else pd.DataFrame(
            columns=["station_id", "ville", "indice_atmo", "pm25",
                     "pm10", "no2", "o3", "timestamp"]
        )
        log.debug(f"normalize_air [{ville}] : {len(df)} mesures")
        return df

    # ------------------------------------------------------------------
    # Trafic
    # ------------------------------------------------------------------

    def normalize_trafic(self, raw: list[dict[str, Any]], ville: str) -> pd.DataFrame:
        """
        Normalise les données de trafic routier.
        Retourne un DataFrame avec les colonnes de TronconTrafic.
        """
        records = []
        for item in raw:
            try:
                troncon = TronconTrafic(
                    troncon_id=str(item.get("troncon_id") or item.get("id") or item.get("fid", "")),
                    nom_troncon=item.get("nom") or item.get("libelle") or item.get("name"),
                    ville=ville,
                    score_congestion=float(item.get("score_congestion") or item.get("taux_occupation") or item.get("vitesse_moyenne") or 0),
                    longueur_km=_parse_float(item.get("longueur_km") or item.get("longueur")),
                    latitude_debut=_parse_float(item.get("lat_debut") or item.get("lat")),
                    longitude_debut=_parse_float(item.get("lon_debut") or item.get("lon")),
                    latitude_fin=_parse_float(item.get("lat_fin")),
                    longitude_fin=_parse_float(item.get("lon_fin")),
                    timestamp=_parse_ts(item.get("horodatage") or item.get("timestamp")),
                )
                records.append(troncon.model_dump())
            except Exception as exc:
                log.warning(f"normalize_trafic [{ville}] item ignoré : {exc}")
                continue

        df = pd.DataFrame(records) if records else pd.DataFrame(
            columns=["troncon_id", "nom_troncon", "ville", "score_congestion",
                     "longueur_km", "latitude_debut", "longitude_debut",
                     "latitude_fin", "longitude_fin", "timestamp"]
        )
        log.debug(f"normalize_trafic [{ville}] : {len(df)} tronçons")
        return df


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_float(val: Any) -> float | None:
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _parse_bool(val: Any) -> bool:
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.lower() in ("true", "1", "open", "oui", "yes", "en_service")
    return bool(val)


def _parse_ts(val: Any) -> datetime:
    if val is None:
        return datetime.now(timezone.utc)
    if isinstance(val, datetime):
        return val if val.tzinfo else val.replace(tzinfo=timezone.utc)
    try:
        dt = pd.to_datetime(val, utc=True)
        return dt.to_pydatetime()
    except Exception:
        return datetime.now(timezone.utc)
