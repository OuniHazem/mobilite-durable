"""
render_dashboard.py
====================
Point d'entrée pour le déploiement Render.

Combine le pipeline (scheduler) et le dashboard Flask en un seul processus :
  1. Initialise la base de données
  2. Lance le scheduler APScheduler en arrière-plan (ingestion + KPIs)
  3. Expose l'app Flask pour gunicorn

Usage Render : gunicorn render_dashboard:app --bind 0.0.0.0:$PORT --workers 1
"""

from __future__ import annotations

import os

from config.settings import patch_windows_encoding

patch_windows_encoding()

from dashboard import app  # noqa: E402


# ---------------------------------------------------------------------------
# Initialisation différée — lancée une seule fois au 1er worker gunicorn
# ---------------------------------------------------------------------------

_scheduler_started = False


def _ensure_pipeline() -> None:
    """Initialise la DB et le scheduler une seule fois."""
    global _scheduler_started
    if _scheduler_started:
        return
    _scheduler_started = True

    from storage.database import health_check, init_db
    from scheduler.jobs import build_scheduler
    from utils.logger import get_logger

    log = get_logger(__name__)
    log.info("Initialisation Render — Pipeline + Dashboard")

    init_db()

    if not health_check():
        log.error("Base de données indisponible — le dashboard démarrera sans données")
        return

    log.info("Base de données : OK")

    scheduler = build_scheduler()
    scheduler.start()
    log.info("Scheduler démarré — jobs actifs :")
    for job in scheduler.get_jobs():
        log.info(f"  [{job.id}] {job.name}")


# ---------------------------------------------------------------------------
# Gunicorn server hook — appelé une seule fois avant le bind
# ---------------------------------------------------------------------------

def on_starting(server):  # noqa: ARG001
    """Hook gunicorn : initialise DB + scheduler avant le 1er bind."""
    _ensure_pipeline()


if __name__ == "__main__":
    _ensure_pipeline()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
