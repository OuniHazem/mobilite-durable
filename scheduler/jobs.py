"""
scheduler/jobs.py
=================
Définition et orchestration des jobs APScheduler — Projet Mobilité Durable

Jobs :
  1. job_ckan_lille        — CKAN Lille toutes les 60s
  2. job_ckan_montpellier  — CKAN Montpellier toutes les 60s
  3. job_gtfsrt            — GTFS-RT Ilévia + TAM toutes les 20s
  4. (Purge quotidienne ajoutée dans main.py)

Chaque job :
  - Ingère les données brutes
  - Normalise via normalizer.py
  - Calcule les KPIs via kpi_engine.py
  - Sauvegarde en base via database.py
  - Pousse vers Power BI via powerbi_pusher.py
  - Journalise dans pipeline_audit
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from config.settings import settings
from ingestion.lille_client import LilleClient
from ingestion.montpellier_client import MontpellierClient
from ingestion.gtfsrt_client import GTFSRTClient
from processing.normalizer import Normalizer
from processing.kpi_engine import KPIEngine
from storage.database import (
    close_audit,
    save_kpi_batch,
    save_policy_scores,
    save_tc_retards,
    save_velo_snapshots,
    save_qualite_air,
    save_trafic_troncons,
    start_audit,
    get_session,
)
from streaming.powerbi_pusher import PowerBIPusher
from utils.logger import get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Singletons partagés entre les jobs (instanciés une seule fois)
# ---------------------------------------------------------------------------

_lille_client = LilleClient()
_montpellier_client = MontpellierClient()
_gtfsrt_client = GTFSRTClient()
_normalizer = Normalizer()
_kpi_engine = KPIEngine()
_powerbi_pusher = PowerBIPusher()


# ---------------------------------------------------------------------------
# Job 1 — CKAN Lille
# ---------------------------------------------------------------------------

def job_ckan_lille() -> None:
    """
    Ingestion complète CKAN Lille :
      - Vélos (V'Lille)
      - Qualité de l'air (ATMO)
      - Trafic routier
    Fréquence : 60s
    """
    cycle_id = start_audit("ckan_lille", source_url=settings.lille_api_base_url)
    t0 = time.monotonic()
    nb_records = 0
    nb_errors = 0

    try:
        log.debug("job_ckan_lille — début")

        # --- Ingestion ---
        raw_velos = _safe_fetch(_lille_client.get_velos, "velos_lille")
        raw_air = _safe_fetch(_lille_client.get_qualite_air, "air_lille")
        raw_trafic = _safe_fetch(_lille_client.get_trafic, "trafic_lille")

        # --- Normalisation ---
        df_velos = _normalizer.normalize_velos(raw_velos, ville="Lille") if raw_velos else None
        df_air = _normalizer.normalize_air(raw_air, ville="Lille") if raw_air else None
        df_trafic = _normalizer.normalize_trafic(raw_trafic, ville="Lille") if raw_trafic else None

        # --- Sauvegarde DB ---
        if df_velos is not None and not df_velos.empty:
            n = save_velo_snapshots(df_velos.to_dict("records"))
            nb_records += n
            log.debug(f"Vélos Lille : {n} stations sauvegardées")

        if df_air is not None and not df_air.empty:
            n = save_qualite_air(df_air.to_dict("records"))
            nb_records += n

        if df_trafic is not None and not df_trafic.empty:
            n = save_trafic_troncons(df_trafic.to_dict("records"))
            nb_records += n

        # --- KPIs ---
        data_bundle = _build_bundle(
            velos=df_velos, air=df_air, trafic=df_trafic, ville="Lille"
        )
        kpi_results = _kpi_engine.compute(data_bundle)
        kpi_rows = _kpi_engine.to_powerbi_rows(kpi_results)

        save_kpi_batch([{**r, "metadata": None} for r in kpi_rows])

        # --- Power BI (pivoté, mode pushStreaming hybride) ---
        _powerbi_pusher.push_pivoted(kpi_results, "Lille")

        # --- Alertes ---
        alertes = _kpi_engine.get_alertes(kpi_results)
        if alertes:
            log.warning(f"[Lille] {len(alertes)} KPI(s) en alerte : "
                        f"{[a.kpi_id for a in alertes]}")

        duree_ms = int((time.monotonic() - t0) * 1000)
        close_audit(cycle_id, "SUCCESS", nb_records, nb_errors, duree_ms)
        log.info(f"job_ckan_lille OK — {nb_records} enregistrements, {duree_ms}ms")

    except Exception as exc:
        duree_ms = int((time.monotonic() - t0) * 1000)
        close_audit(cycle_id, "ERROR", nb_records, nb_errors + 1, duree_ms, str(exc))
        log.error(f"job_ckan_lille ERREUR : {exc}")


# ---------------------------------------------------------------------------
# Job 2 — CKAN Montpellier
# ---------------------------------------------------------------------------

def job_ckan_montpellier() -> None:
    """
    Ingestion complète CKAN Montpellier :
      - Vélos (VéloMagg)
      - Qualité de l'air
      - Trafic routier
    Fréquence : 60s
    """
    cycle_id = start_audit("ckan_montpellier", source_url=settings.montpellier_ckan_base_url)
    t0 = time.monotonic()
    nb_records = 0
    nb_errors = 0

    try:
        log.debug("job_ckan_montpellier — début")

        raw_velos = _safe_fetch(_montpellier_client.get_velos, "velos_montpellier")
        raw_air = _safe_fetch(_montpellier_client.get_qualite_air, "air_montpellier")
        raw_trafic = _safe_fetch(_montpellier_client.get_trafic, "trafic_montpellier")

        df_velos = _normalizer.normalize_velos(raw_velos, ville="Montpellier") if raw_velos else None
        df_air = _normalizer.normalize_air(raw_air, ville="Montpellier") if raw_air else None
        df_trafic = _normalizer.normalize_trafic(raw_trafic, ville="Montpellier") if raw_trafic else None

        if df_velos is not None and not df_velos.empty:
            nb_records += save_velo_snapshots(df_velos.to_dict("records"))

        if df_air is not None and not df_air.empty:
            nb_records += save_qualite_air(df_air.to_dict("records"))

        if df_trafic is not None and not df_trafic.empty:
            nb_records += save_trafic_troncons(df_trafic.to_dict("records"))

        data_bundle = _build_bundle(
            velos=df_velos, air=df_air, trafic=df_trafic, ville="Montpellier"
        )
        kpi_results = _kpi_engine.compute(data_bundle)
        kpi_rows = _kpi_engine.to_powerbi_rows(kpi_results)

        save_kpi_batch([{**r, "metadata": None} for r in kpi_rows])
        _powerbi_pusher.push_pivoted(kpi_results, "Montpellier")

        alertes = _kpi_engine.get_alertes(kpi_results)
        if alertes:
            log.warning(f"[Montpellier] {len(alertes)} KPI(s) en alerte : "
                        f"{[a.kpi_id for a in alertes]}")

        duree_ms = int((time.monotonic() - t0) * 1000)
        close_audit(cycle_id, "SUCCESS", nb_records, nb_errors, duree_ms)
        log.info(f"job_ckan_montpellier OK — {nb_records} enregistrements, {duree_ms}ms")

    except Exception as exc:
        duree_ms = int((time.monotonic() - t0) * 1000)
        close_audit(cycle_id, "ERROR", nb_records, nb_errors + 1, duree_ms, str(exc))
        log.error(f"job_ckan_montpellier ERREUR : {exc}")


# ---------------------------------------------------------------------------
# Job 3 — GTFS-RT (Ilévia Lille + TAM Montpellier)
# ---------------------------------------------------------------------------

def job_gtfsrt() -> None:
    """
    Ingestion GTFS-RT temps réel :
      - Positions véhicules + retards Ilévia (Lille)
      - Positions véhicules + retards TAM (Montpellier)
    Fréquence : 20s
    """
    cycle_id = start_audit("gtfsrt", source_url=settings.gtfsrt_ilevia_url)
    t0 = time.monotonic()
    nb_records = 0
    nb_errors = 0

    try:
        log.debug("job_gtfsrt — début")

        # --- Ingestion Lille ---
        raw_lille = _safe_fetch(_gtfsrt_client.get_retards_lille, "gtfsrt_lille")
        # --- Ingestion Montpellier ---
        raw_montpellier = _safe_fetch(_gtfsrt_client.get_retards_montpellier, "gtfsrt_montpellier")

        # --- Normalisation ---
        df_tc_lille = (
            _normalizer.normalize_tc(raw_lille, ville="Lille")
            if raw_lille else None
        )
        df_tc_montpellier = (
            _normalizer.normalize_tc(raw_montpellier, ville="Montpellier")
            if raw_montpellier else None
        )

        # --- Sauvegarde DB ---
        for df_tc, ville in [(df_tc_lille, "Lille"), (df_tc_montpellier, "Montpellier")]:
            if df_tc is not None and not df_tc.empty:
                n = save_tc_retards(df_tc.to_dict("records"))
                nb_records += n
                log.debug(f"TC {ville} : {n} observations sauvegardées")

        # --- KPIs TC ---
        import pandas as pd
        dfs = [df for df in [df_tc_lille, df_tc_montpellier] if df is not None]
        if dfs:
            df_tc_all = pd.concat(dfs, ignore_index=True)
            kpi_results = _kpi_engine.compute({"tc": df_tc_all})
            kpi_rows = _kpi_engine.to_powerbi_rows(kpi_results)

            save_kpi_batch([{**r, "metadata": None} for r in kpi_rows])

            # Push Power BI par ville
            for ville in ["Lille", "Montpellier"]:
                results_ville = [k for k in kpi_results if k.ville == ville]
                if results_ville:
                    _powerbi_pusher.push_pivoted(results_ville, ville)

            alertes = _kpi_engine.get_alertes(kpi_results)
            if alertes:
                log.warning(f"[TC] {len(alertes)} KPI(s) en alerte TC")

        duree_ms = int((time.monotonic() - t0) * 1000)
        close_audit(cycle_id, "SUCCESS", nb_records, nb_errors, duree_ms)
        log.debug(f"job_gtfsrt OK — {nb_records} enregistrements, {duree_ms}ms")

    except Exception as exc:
        duree_ms = int((time.monotonic() - t0) * 1000)
        close_audit(cycle_id, "ERROR", nb_records, nb_errors + 1, duree_ms, str(exc))
        log.error(f"job_gtfsrt ERREUR : {exc}")


# ---------------------------------------------------------------------------
# Job 4 — Évaluation politique publique (toutes les 5 min)
# ---------------------------------------------------------------------------

def job_policy_evaluation() -> None:
    """
    Calcule les scores de politique publique pour les deux villes.
    S'appuie sur les KPIs opérationnels stockés en base.
    Fréquence : 300s (5 min) — pas besoin de chaque cycle
    """
    from processing.policy_kpi_engine import PolicyKPIEngine

    cycle_id = start_audit("policy_evaluation")
    t0 = time.monotonic()
    nb_records = 0

    try:
        log.debug("job_policy_evaluation — début")

        with get_session() as session:
            engine = PolicyKPIEngine(session)

            for ville in ["Lille", "Montpellier"]:
                scores = engine.compute_all(ville)
                if scores:
                    n = save_policy_scores(scores)
                    nb_records += n
                    log.debug(f"Policy {ville} : {n} scores sauvegardés")

        duree_ms = int((time.monotonic() - t0) * 1000)
        close_audit(cycle_id, "SUCCESS", nb_records, 0, duree_ms)
        log.info(f"job_policy_evaluation OK — {nb_records} scores, {duree_ms}ms")

    except Exception as exc:
        duree_ms = int((time.monotonic() - t0) * 1000)
        close_audit(cycle_id, "ERROR", nb_records, 1, duree_ms, str(exc))
        log.error(f"job_policy_evaluation ERREUR : {exc}")


# ---------------------------------------------------------------------------
# Builder du scheduler
# ---------------------------------------------------------------------------

def build_scheduler() -> BackgroundScheduler:
    """
    Construit et configure le BackgroundScheduler APScheduler.
    Appelé depuis main.py — le scheduler n'est PAS démarré ici.

    Retourne un scheduler prêt à appeler .start() dessus.
    """
    scheduler = BackgroundScheduler(
        timezone="Europe/Paris",
        job_defaults={
            "coalesce": True,          # si un job est en retard, une seule exécution
            "max_instances": 1,        # pas de parallélisme sur le même job
            "misfire_grace_time": 30,  # tolérance 30s si le scheduler est occupé
        },
    )

    # Job 1 — CKAN Lille (60s)
    scheduler.add_job(
        func=job_ckan_lille,
        trigger=IntervalTrigger(seconds=settings.ckan_refresh_s),
        id="ckan_lille",
        name="Ingestion CKAN Lille",
        replace_existing=True,
        next_run_time=datetime.now(timezone.utc),  # exécution immédiate au démarrage
    )

    # Job 2 — CKAN Montpellier (60s, décalé de 5s pour éviter les pics)
    scheduler.add_job(
        func=job_ckan_montpellier,
        trigger=IntervalTrigger(seconds=settings.ckan_refresh_s, start_date=_offset_start(5)),
        id="ckan_montpellier",
        name="Ingestion CKAN Montpellier",
        replace_existing=True,
    )

    # Job 3 — GTFS-RT (20s)
    scheduler.add_job(
        func=job_gtfsrt,
        trigger=IntervalTrigger(seconds=settings.gtfsrt_refresh_s),
        id="gtfsrt",
        name="Ingestion GTFS-RT TC",
        replace_existing=True,
        next_run_time=datetime.now(timezone.utc),
    )

    # Job 4 — Évaluation politique publique (5 min)
    scheduler.add_job(
        func=job_policy_evaluation,
        trigger=IntervalTrigger(seconds=300),
        id="policy_evaluation",
        name="Évaluation politiques publiques",
        replace_existing=True,
        next_run_time=datetime.now(timezone.utc),
    )

    log.info(
        f"Scheduler configuré — "
        f"CKAN: {settings.ckan_refresh_s}s | "
        f"GTFS-RT: {settings.gtfsrt_refresh_s}s"
    )
    return scheduler


# ---------------------------------------------------------------------------
# Helpers internes
# ---------------------------------------------------------------------------

def _safe_fetch(func: Any, label: str) -> Any:
    """
    Appelle une fonction d'ingestion et capture les erreurs sans faire crasher le job.
    Retourne None si l'appel échoue.
    """
    try:
        return func()
    except Exception as exc:
        log.warning(f"Fetch échoué [{label}] : {exc}")
        return None


def _build_bundle(
    velos: Any = None,
    air: Any = None,
    trafic: Any = None,
    tc: Any = None,
    ville: str = "",
) -> dict:
    """Construit le data_bundle attendu par KPIEngine.compute()."""
    bundle = {}
    if tc is not None:
        bundle["tc"] = tc
    if velos is not None:
        bundle["velos"] = velos
    if air is not None:
        bundle["air"] = air
    if trafic is not None:
        bundle["trafic"] = trafic
    return bundle


def _offset_start(seconds: int) -> datetime:
    """Retourne un datetime décalé de N secondes dans le futur."""
    from datetime import timedelta
    return datetime.now(timezone.utc) + timedelta(seconds=seconds)
