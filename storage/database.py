"""
storage/database.py
===================
Couche d'accès PostgreSQL — Projet Mobilité Durable

Stratégie :
  - Engine synchrone (compatible APScheduler threadpool)
  - Session factory avec context manager
  - Upsert batch pour les snapshots (idempotent)
  - Purge automatique des données > 90 jours
  - Health check exposé pour main.py
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from config.settings import settings
from storage.models import (
    Base,
    KPIHistorique,
    PipelineAudit,
    PolicyScoreModel,
    QualiteAir,
    TCRetard,
    TraficTroncon,
    VeloStation,
)
from utils.logger import get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Engine & Session factory
# ---------------------------------------------------------------------------

_engine = None
_SessionLocal = None


def init_db() -> None:
    """
    Initialise l'engine PostgreSQL et crée les tables si elles n'existent pas.
    Appelé une seule fois au démarrage dans main.py.
    """
    global _engine, _SessionLocal

    # Force UTF-8 — évite UnicodeDecodeError sur Windows (psycopg2 + cp1252).
    import sys
    connect_args: dict = {
        "options": "-c client_encoding=UTF8",
        "client_encoding": "utf8",
    }

    _engine = create_engine(
        settings.database_url,
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,
        pool_recycle=1800,
        echo=False,
        connect_args=connect_args,
    )

    _SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False)

    # Création des tables (Alembic gère les migrations en prod)
    Base.metadata.create_all(bind=_engine)
    log.info("Base de données initialisée — tables créées/vérifiées")


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """Context manager de session — rollback automatique sur erreur."""
    if _SessionLocal is None:
        raise RuntimeError("Base de données non initialisée. Appeler init_db() d'abord.")
    session: Session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def health_check() -> bool:
    """Retourne True si la base est joignable."""
    try:
        with get_session() as session:
            session.execute(text("SELECT 1"))
        return True
    except Exception as exc:
        log.error(f"Health check DB échoué : {exc}")
        return False


# ---------------------------------------------------------------------------
# Écriture — KPI Historique
# ---------------------------------------------------------------------------

def save_kpi_batch(kpi_rows: list[dict[str, Any]]) -> int:
    """
    Insère un batch de KPIs en base.
    kpi_rows : liste de dicts issus de KPIResult.to_powerbi_row() + metadata_json

    Retourne le nombre de lignes insérées.
    """
    if not kpi_rows:
        return 0

    objects = []
    for row in kpi_rows:
        objects.append(KPIHistorique(
            kpi_id=row["kpi_id"],
            kpi_label=row["kpi_label"],
            valeur=row["valeur"],
            unite=row["unite"],
            ville=row["ville"],
            domaine=row["domaine"],
            fenetre=row["fenetre"],
            alerte=row["alerte"],
            metadata_json=row.get("metadata"),
            timestamp_calcul=datetime.fromisoformat(row["timestamp_calcul"]),
        ))

    with get_session() as session:
        session.bulk_save_objects(objects)

    log.debug(f"KPI batch sauvegardé : {len(objects)} lignes")
    return len(objects)


# ---------------------------------------------------------------------------
# Écriture — Données sources
# ---------------------------------------------------------------------------

def save_tc_retards(records: list[dict[str, Any]]) -> int:
    """Insère les retards TC — source GTFS-RT normalisée."""
    if not records:
        return 0

    objects = [
        TCRetard(
            ville=r["ville"],
            ligne_id=r["ligne_id"],
            vehicle_id=r.get("vehicle_id"),
            trip_id=r.get("trip_id"),
            retard_s=int(r["retard_s"]),
            retard_min=r["retard_s"] / 60,
            en_retard=abs(r["retard_s"]) > 180,
            retard_fort=r["retard_s"] > 360,
            latitude=r.get("latitude"),
            longitude=r.get("longitude"),
            timestamp_observation=_parse_ts(r["timestamp"]),
        )
        for r in records
    ]

    with get_session() as session:
        session.bulk_save_objects(objects)

    return len(objects)


def save_velo_snapshots(records: list[dict[str, Any]]) -> int:
    """Insère les snapshots stations vélos."""
    if not records:
        return 0

    objects = []
    for r in records:
        capa = r.get("capacite", 0)
        velos = r.get("velos_disponibles", 0)
        objects.append(VeloStation(
            ville=r["ville"],
            station_id=r["station_id"],
            nom_station=r.get("nom_station"),
            velos_disponibles=velos,
            capacite=capa,
            en_service=bool(r.get("en_service", True)),
            taux_dispo=velos / capa if capa > 0 else None,
            latitude=r.get("latitude"),
            longitude=r.get("longitude"),
            timestamp_observation=_parse_ts(r["timestamp"]),
        ))

    with get_session() as session:
        session.bulk_save_objects(objects)

    return len(objects)


def save_qualite_air(records: list[dict[str, Any]]) -> int:
    """Insère les mesures de qualité de l'air."""
    if not records:
        return 0

    objects = []
    for r in records:
        indice = r.get("indice_atmo")
        pm25 = r.get("pm25")
        objects.append(QualiteAir(
            ville=r["ville"],
            station_id=r.get("station_id"),
            indice_atmo=indice,
            pm25=pm25,
            pm10=r.get("pm10"),
            no2=r.get("no2"),
            o3=r.get("o3"),
            alerte_atmo=(indice >= 7) if indice is not None else None,
            depassement_oms_pm25=(pm25 > 15.0) if pm25 is not None else None,
            timestamp_observation=_parse_ts(r["timestamp"]),
        ))

    with get_session() as session:
        session.bulk_save_objects(objects)

    return len(objects)


def save_trafic_troncons(records: list[dict[str, Any]]) -> int:
    """Insère les snapshots trafic."""
    if not records:
        return 0

    objects = []
    for r in records:
        score = r.get("score_congestion", 0)
        objects.append(TraficTroncon(
            ville=r["ville"],
            troncon_id=r["troncon_id"],
            nom_troncon=r.get("nom_troncon"),
            score_congestion=score,
            longueur_km=r.get("longueur_km"),
            fluide=score < 40,
            bloque=score > 80,
            latitude_debut=r.get("latitude_debut"),
            longitude_debut=r.get("longitude_debut"),
            latitude_fin=r.get("latitude_fin"),
            longitude_fin=r.get("longitude_fin"),
            timestamp_observation=_parse_ts(r["timestamp"]),
        ))

    with get_session() as session:
        session.bulk_save_objects(objects)

    return len(objects)


# ---------------------------------------------------------------------------
# Écriture — Scores de politique publique
# ---------------------------------------------------------------------------

def save_policy_scores(policy_scores: list[Any]) -> int:
    """
    Insère les scores de politique publique en base.
    policy_scores : liste de PolicyScore (processing/policy_kpi_engine.py)

    Retourne le nombre de lignes insérées.
    """
    if not policy_scores:
        return 0

    objects = []
    for ps in policy_scores:
        d = ps.to_dict() if hasattr(ps, "to_dict") else ps
        objects.append(PolicyScoreModel(
            ville=d["ville"],
            dimension=d["dimension"],
            score=d["score"],
            tendance=d["tendance"],
            nb_kpis=d["nb_kpis"],
            details=d.get("details"),
            timestamp=_parse_ts(d["timestamp"]),
        ))

    with get_session() as session:
        session.bulk_save_objects(objects)

    log.debug(f"Policy scores sauvegardés : {len(objects)} lignes")
    return len(objects)


# ---------------------------------------------------------------------------
# Audit pipeline
# ---------------------------------------------------------------------------

def start_audit(job_name: str, source_url: str | None = None) -> str:
    """
    Crée une entrée d'audit et retourne le cycle_id.
    À appeler au début de chaque job scheduler.
    """
    cycle_id = str(uuid.uuid4())
    audit = PipelineAudit(
        cycle_id=cycle_id,
        job_name=job_name,
        statut="RUNNING",
        source_url=source_url,
        timestamp_debut=datetime.now(timezone.utc),
    )
    with get_session() as session:
        session.add(audit)

    return cycle_id


def close_audit(
    cycle_id: str,
    statut: str,
    nb_enregistrements: int = 0,
    nb_erreurs: int = 0,
    duree_ms: int | None = None,
    message_erreur: str | None = None,
) -> None:
    """Met à jour l'entrée d'audit à la fin d'un job."""
    with get_session() as session:
        audit = (
            session.query(PipelineAudit)
            .filter(PipelineAudit.cycle_id == cycle_id)
            .first()
        )
        if audit:
            audit.statut = statut
            audit.nb_enregistrements = nb_enregistrements
            audit.nb_erreurs = nb_erreurs
            audit.duree_ms = duree_ms
            audit.message_erreur = message_erreur
            audit.timestamp_fin = datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Maintenance — purge automatique
# ---------------------------------------------------------------------------

def purge_old_data(retention_days: int = 90) -> dict[str, int]:
    """
    Supprime les données plus anciennes que retention_days.
    À appeler 1x/jour via APScheduler.
    Retourne le nombre de lignes supprimées par table.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    deleted: dict[str, int] = {}

    tables = [
        (KPIHistorique, "timestamp_calcul"),
        (TCRetard, "timestamp_observation"),
        (VeloStation, "timestamp_observation"),
        (QualiteAir, "timestamp_observation"),
        (TraficTroncon, "timestamp_observation"),
        (PolicyScoreModel, "timestamp"),
    ]

    with get_session() as session:
        for model, ts_col in tables:
            col = getattr(model, ts_col)
            count = session.query(model).filter(col < cutoff).delete(
                synchronize_session=False
            )
            deleted[model.__tablename__] = count
            log.info(f"Purge {model.__tablename__} : {count} lignes supprimées")

    # Audit pipeline : garder 30 jours
    audit_cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    with get_session() as session:
        count = session.query(PipelineAudit).filter(
            PipelineAudit.timestamp_debut < audit_cutoff
        ).delete(synchronize_session=False)
        deleted["pipeline_audit"] = count

    log.info(f"Purge terminée : {sum(deleted.values())} lignes total")
    return deleted


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_ts(value: Any) -> datetime:
    """Parse un timestamp issu du normalizer (str ISO ou datetime)."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    return datetime.fromisoformat(str(value)).replace(tzinfo=timezone.utc)
