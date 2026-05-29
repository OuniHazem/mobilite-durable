"""
storage/models.py
=================
Modèles SQLAlchemy — Projet Mobilité Durable
Tables :
  - kpi_historique    : valeurs KPI horodatées (série temporelle)
  - tc_retards        : détail des retards TC par course
  - velo_stations     : snapshots stations vélos
  - qualite_air       : mesures qualité de l'air
  - trafic_troncons   : scores de congestion par tronçon
  - pipeline_audit    : journal des cycles d'ingestion
  - policy_scores     : scores d'évaluation des politiques publiques
"""

from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Table 1 — KPI Historique (série temporelle principale)
# ---------------------------------------------------------------------------

class KPIHistorique(Base):
    """
    Stockage de toutes les valeurs KPI calculées.
    Partition naturelle : (ville, domaine, fenetre).
    Rétention recommandée : 90 jours → archivage S3.
    """
    __tablename__ = "kpi_historique"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    kpi_id = Column(String(128), nullable=False, index=True)
    kpi_label = Column(String(256), nullable=False)
    valeur = Column(Float, nullable=False)
    unite = Column(String(32), nullable=False)
    ville = Column(String(64), nullable=False, index=True)
    domaine = Column(String(32), nullable=False, index=True)   # TC|VELO|AIR|TRAFIC
    fenetre = Column(String(16), nullable=False)                # 15min|1h|1j
    alerte = Column(String(16), nullable=False)                 # OK|ATTENTION|ALERTE|CRITIQUE
    metadata_json = Column(JSON, nullable=True)
    timestamp_calcul = Column(DateTime(timezone=True), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), default=_now, nullable=False)

    __table_args__ = (
        Index("ix_kpi_ville_domaine_ts", "ville", "domaine", "timestamp_calcul"),
        Index("ix_kpi_id_ts", "kpi_id", "timestamp_calcul"),
    )

    def __repr__(self) -> str:
        return f"<KPIHistorique {self.kpi_id}={self.valeur}{self.unite} @{self.timestamp_calcul}>"


# ---------------------------------------------------------------------------
# Table 2 — Retards TC
# ---------------------------------------------------------------------------

class TCRetard(Base):
    """
    Détail des retards par course — source GTFS-RT.
    Granularité : 1 ligne = 1 véhicule observé à 1 instant.
    """
    __tablename__ = "tc_retards"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    ville = Column(String(64), nullable=False, index=True)
    ligne_id = Column(String(64), nullable=False, index=True)
    vehicle_id = Column(String(128), nullable=True)
    trip_id = Column(String(256), nullable=True)
    retard_s = Column(Integer, nullable=False)                  # secondes
    retard_min = Column(Float, nullable=False)                  # minutes (calc)
    en_retard = Column(Boolean, nullable=False)                 # retard > 3 min
    retard_fort = Column(Boolean, nullable=False)               # retard > 6 min
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    timestamp_observation = Column(DateTime(timezone=True), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), default=_now, nullable=False)

    __table_args__ = (
        Index("ix_tc_ville_ligne_ts", "ville", "ligne_id", "timestamp_observation"),
    )


# ---------------------------------------------------------------------------
# Table 3 — Stations Vélos (snapshots)
# ---------------------------------------------------------------------------

class VeloStation(Base):
    """
    Snapshots des stations vélos en libre-service.
    1 ligne = 1 station à 1 instant (snapshot toutes les 60s).
    """
    __tablename__ = "velo_stations"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    ville = Column(String(64), nullable=False, index=True)
    station_id = Column(String(128), nullable=False, index=True)
    nom_station = Column(String(256), nullable=True)
    velos_disponibles = Column(Integer, nullable=False)
    capacite = Column(Integer, nullable=False)
    en_service = Column(Boolean, nullable=False)
    taux_dispo = Column(Float, nullable=True)                    # velos/capacite
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    timestamp_observation = Column(DateTime(timezone=True), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), default=_now, nullable=False)

    __table_args__ = (
        Index("ix_velo_station_ts", "station_id", "timestamp_observation"),
        Index("ix_velo_ville_ts", "ville", "timestamp_observation"),
    )


# ---------------------------------------------------------------------------
# Table 4 — Qualité de l'air
# ---------------------------------------------------------------------------

class QualiteAir(Base):
    """
    Mesures de qualité de l'air — source CKAN (ATMO).
    """
    __tablename__ = "qualite_air"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    ville = Column(String(64), nullable=False, index=True)
    station_id = Column(String(128), nullable=True)
    indice_atmo = Column(Float, nullable=True)                  # 1–10
    pm25 = Column(Float, nullable=True)                         # µg/m³
    pm10 = Column(Float, nullable=True)                         # µg/m³
    no2 = Column(Float, nullable=True)                          # µg/m³
    o3 = Column(Float, nullable=True)                           # µg/m³
    alerte_atmo = Column(Boolean, nullable=True)                # indice >= 7
    depassement_oms_pm25 = Column(Boolean, nullable=True)       # PM2.5 > 15
    timestamp_observation = Column(DateTime(timezone=True), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), default=_now, nullable=False)

    __table_args__ = (
        Index("ix_air_ville_ts", "ville", "timestamp_observation"),
    )


# ---------------------------------------------------------------------------
# Table 5 — Trafic / Tronçons
# ---------------------------------------------------------------------------

class TraficTroncon(Base):
    """
    Scores de congestion par tronçon routier.
    """
    __tablename__ = "trafic_troncons"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    ville = Column(String(64), nullable=False, index=True)
    troncon_id = Column(String(128), nullable=False, index=True)
    nom_troncon = Column(String(256), nullable=True)
    score_congestion = Column(Float, nullable=False)            # 0–100
    longueur_km = Column(Float, nullable=True)
    fluide = Column(Boolean, nullable=True)                     # score < 40
    bloque = Column(Boolean, nullable=True)                     # score > 80
    latitude_debut = Column(Float, nullable=True)
    longitude_debut = Column(Float, nullable=True)
    latitude_fin = Column(Float, nullable=True)
    longitude_fin = Column(Float, nullable=True)
    timestamp_observation = Column(DateTime(timezone=True), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), default=_now, nullable=False)

    __table_args__ = (
        Index("ix_trafic_troncon_ts", "troncon_id", "timestamp_observation"),
        Index("ix_trafic_ville_ts", "ville", "timestamp_observation"),
    )


# ---------------------------------------------------------------------------
# Table 6 — Audit Pipeline
# ---------------------------------------------------------------------------

class PipelineAudit(Base):
    """
    Journal de chaque cycle d'ingestion.
    Permet de détecter les dérives, interruptions, et erreurs.
    """
    __tablename__ = "pipeline_audit"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    cycle_id = Column(String(64), nullable=False, index=True)   # UUID du cycle
    job_name = Column(String(128), nullable=False)              # ckan_lille, gtfsrt…
    statut = Column(String(32), nullable=False)                 # SUCCESS|ERROR|PARTIAL
    nb_enregistrements = Column(Integer, nullable=True)
    nb_erreurs = Column(Integer, default=0)
    duree_ms = Column(Integer, nullable=True)
    message_erreur = Column(Text, nullable=True)
    source_url = Column(String(512), nullable=True)
    timestamp_debut = Column(DateTime(timezone=True), nullable=False)
    timestamp_fin = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=_now, nullable=False)

    __table_args__ = (
        Index("ix_audit_job_ts", "job_name", "timestamp_debut"),
        Index("ix_audit_statut", "statut"),
    )

    def __repr__(self) -> str:
        return f"<PipelineAudit {self.job_name} {self.statut} @{self.timestamp_debut}>"


# ---------------------------------------------------------------------------
# Table 7 — Scores d'évaluation des politiques publiques
# ---------------------------------------------------------------------------

class PolicyScoreModel(Base):
    """
    Scores de politique publique par dimension et par ville.
    1 ligne = 1 score pour 1 dimension pour 1 ville à 1 instant.

    Dimensions :
      - MOBILITÉ_DOUCE   : attractivité vélos + TC vs voiture
      - QUALITÉ_AIR      : impact sur la santé publique
      - EFFICACITÉ_TC    : qualité du service public transport
      - TRAFIC_ROUTIER   : réduction de la congestion
      - SCORE_GLOBAL     : composite pondéré

    Tendances :
      ↑ amélioration | → stable | ↓ dégradation | — insuffisant
    """
    __tablename__ = "policy_scores"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    ville = Column(String(64), nullable=False, index=True)
    dimension = Column(String(64), nullable=False, index=True)
    score = Column(Float, nullable=False)                         # 0–100
    tendance = Column(String(16), nullable=False)                 # UP/STABLE/DOWN/NA
    nb_kpis = Column(Integer, nullable=False)                    # KPIs utilisés
    details = Column(JSON, nullable=True)                        # détail du calcul
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), default=_now, nullable=False)

    __table_args__ = (
        Index("ix_policy_ville_dim_ts", "ville", "dimension", "timestamp"),
        Index("ix_policy_dim_ts", "dimension", "timestamp"),
    )

    def __repr__(self) -> str:
        return f"<PolicyScoreModel {self.ville} {self.dimension}={self.score}{self.tendance}>"
