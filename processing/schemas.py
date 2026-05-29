# processing/schemas.py
# ============================================================
# SCHÉMAS PYDANTIC — Validation & typage des données entrantes
# ============================================================

from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel, Field, field_validator


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


# ── Vélos en libre-service ───────────────────────────────────

class StationVelo(BaseModel):
    """Schéma normalisé pour une station de vélos (Lille V'Lille / Montpellier Vélomagg)."""

    station_id: str
    nom_station: Optional[str] = None
    ville: str
    velos_disponibles: int = Field(ge=0)
    capacite: int = Field(ge=0)
    en_service: bool = True
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    timestamp: datetime = Field(default_factory=_now_utc)


# ── Transports en commun (GTFS-RT) ──────────────────────────

class VehiculeTC(BaseModel):
    """Position temps réel d'un véhicule de transport en commun."""

    vehicle_id: str
    trip_id: Optional[str] = None
    route_id: Optional[str] = None
    ligne: Optional[str] = None
    ville: str
    latitude: float
    longitude: float
    vitesse_kmh: Optional[float] = Field(default=None, ge=0)
    bearing: Optional[float] = None     # cap en degrés
    occupancy: Optional[str] = None     # EMPTY | MANY_SEATS | FEW_SEATS | FULL
    collecte_ts: datetime = Field(default_factory=_now_utc)


class RetardTC(BaseModel):
    """Retard sur une course (GTFS-RT TripUpdate)."""

    vehicle_id: str = ""
    trip_id: str = ""
    ligne_id: str = "?"
    ville: str
    retard_s: int = 0
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    timestamp: datetime = Field(default_factory=_now_utc)


# ── Qualité de l'air ─────────────────────────────────────────

class QualiteAir(BaseModel):
    """Indice de qualité de l'air par station."""

    station_id: str = ""
    ville: str
    indice_atmo: Optional[float] = None
    pm25: Optional[float] = None
    pm10: Optional[float] = None
    no2: Optional[float] = None
    o3: Optional[float] = None
    timestamp: datetime = Field(default_factory=_now_utc)


# ── Trafic routier ───────────────────────────────────────────

class TronconTrafic(BaseModel):
    """État du trafic sur un tronçon routier."""

    troncon_id: str = ""
    nom_troncon: Optional[str] = None
    ville: str
    score_congestion: float = 0.0
    longueur_km: Optional[float] = None
    latitude_debut: Optional[float] = None
    longitude_debut: Optional[float] = None
    latitude_fin: Optional[float] = None
    longitude_fin: Optional[float] = None
    timestamp: datetime = Field(default_factory=_now_utc)


# ── Enveloppe de collecte ────────────────────────────────────

class CollecteResult(BaseModel):
    """Résultat d'une collecte : métadonnées + données."""

    source: str           # "lille_ckan" | "montpellier_ckan" | "lille_gtfsrt"
    dataset: str          # "velos" | "tc_positions" | "air" | "trafic"
    nb_enregistrements: int
    statut: str           # "OK" | "PARTIEL" | "ERREUR"
    erreur: Optional[str] = None
    collecte_ts: datetime = Field(default_factory=_now_utc)
    donnees: list = Field(default_factory=list)
