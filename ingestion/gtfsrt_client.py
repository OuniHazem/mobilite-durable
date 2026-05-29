"""
ingestion/gtfsrt_client.py
==========================
Client GTFS-RT — Projet Mobilité Durable
Sources : Ilévia (Lille) + TAM (Montpellier)
Fréquence : toutes les 20 secondes
Format : Protobuf GTFS-RT
"""

from __future__ import annotations

from typing import Any

import requests
from google.transit import gtfs_realtime_pb2
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from config.settings import settings
from utils.logger import get_logger

log = get_logger(__name__)


class GTFSRTClient:
    """
    Ingère les flux GTFS-RT temps réel des deux réseaux TC.
    Décode le Protobuf et retourne des dicts normalisables.
    """

    def __init__(self) -> None:
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "MobiliteDurable-Pipeline/1.0",
            "Accept": "application/x-protobuf",
        })

    def get_retards_lille(self) -> list[dict[str, Any]]:
        """Retards TC Ilévia (Lille)."""
        return self._fetch_trip_updates(
            url=settings.gtfsrt_ilevia_url,
            ville="Lille",
        )

    def get_retards_montpellier(self) -> list[dict[str, Any]]:
        """Retards TC TAM (Montpellier)."""
        return self._fetch_trip_updates(
            url=settings.gtfsrt_tam_url,
            ville="Montpellier",
        )

    def get_positions_lille(self) -> list[dict[str, Any]]:
        """Positions GPS des véhicules Ilévia en temps réel."""
        return self._fetch_vehicle_positions(
            url=settings.gtfsrt_ilevia_url,
            ville="Lille",
        )

    def get_positions_montpellier(self) -> list[dict[str, Any]]:
        """Positions GPS des véhicules TAM en temps réel."""
        return self._fetch_vehicle_positions(
            url=settings.gtfsrt_tam_url,
            ville="Montpellier",
        )

    def _fetch_trip_updates(self, url: str, ville: str) -> list[dict[str, Any]]:
        """Télécharge et décode un flux GTFS-RT (TripUpdate)."""
        try:
            resp = self._fetch_gtfsrt(url, ville)
            if resp is None:
                return []

            feed = gtfs_realtime_pb2.FeedMessage()
            feed.ParseFromString(resp.content)

            records = []
            for entity in feed.entity:
                if not entity.HasField("trip_update"):
                    continue
                trip_update = entity.trip_update
                trip = trip_update.trip
                vehicle = trip_update.vehicle

                retard_s = 0
                for stu in trip_update.stop_time_update:
                    if stu.HasField("departure"):
                        retard_s = stu.departure.delay
                    elif stu.HasField("arrival"):
                        retard_s = stu.arrival.delay

                records.append({
                    "vehicle_id": vehicle.id if vehicle.id else entity.id,
                    "trip_id": trip.trip_id,
                    "route_id": trip.route_id,
                    "ville": ville,
                    "delay": retard_s,
                    "latitude": None,
                    "longitude": None,
                    "timestamp": None,
                })

            log.debug(f"GTFS-RT [{ville}] : {len(records)} courses")
            return records

        except Exception as exc:
            log.error(f"GTFS-RT [{ville}] erreur : {exc}")
            return []

    def _fetch_vehicle_positions(self, url: str, ville: str) -> list[dict[str, Any]]:
        """Décode le flux GTFS-RT VehiclePosition."""
        try:
            resp = self._fetch_gtfsrt(url, ville)
            if resp is None:
                return []

            feed = gtfs_realtime_pb2.FeedMessage()
            feed.ParseFromString(resp.content)

            records = []
            for entity in feed.entity:
                if not entity.HasField("vehicle"):
                    continue
                vp = entity.vehicle
                records.append({
                    "vehicle_id": vp.vehicle.id if vp.vehicle.id else entity.id,
                    "trip_id": vp.trip.trip_id if vp.HasField("trip") else None,
                    "route_id": vp.trip.route_id if vp.HasField("trip") else None,
                    "ville": ville,
                    "latitude": vp.position.latitude,
                    "longitude": vp.position.longitude,
                    "vitesse_kmh": vp.position.speed * 3.6 if vp.position.speed else None,
                    "timestamp": None,
                })

            return records

        except Exception as exc:
            log.error(f"GTFS-RT positions [{ville}] erreur : {exc}")
            return []

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=10),
        retry=retry_if_exception_type((requests.ConnectionError, requests.Timeout, requests.HTTPError)),
        reraise=False,
    )
    def _fetch_gtfsrt(self, url: str, ville: str):
        """Télécharge un flux GTFS-RT avec retry automatique."""
        resp = self._session.get(url, timeout=settings.http_timeout_s)
        resp.raise_for_status()
        return resp
