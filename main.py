"""
main.py
=======
Point d'entrée du pipeline Mobilité Durable — Lille & Montpellier

Responsabilités :
  1. Init configuration, logger, DB
  2. Démarrage de l'APScheduler (jobs définis en Partie 2)
  3. Health check HTTP sur /health (port 8080)
  4. Gestion propre SIGTERM / SIGINT (graceful shutdown)
  5. Boucle principale keep-alive
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Patch encodage Windows — DOIT être exécuté avant tout autre import
# Évite UnicodeDecodeError psycopg2 sur Windows (pgpassfile en cp1252)
# ---------------------------------------------------------------------------
from config.settings import patch_windows_encoding
patch_windows_encoding()

import signal
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

from config.settings import settings
from processing.kpi_engine import KPIEngine, NiveauAlerte
from scheduler.jobs import build_scheduler
from storage.database import health_check, init_db, purge_old_data
from utils.logger import get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# État global du pipeline
# ---------------------------------------------------------------------------

_shutdown_event = threading.Event()
_startup_time = datetime.now(timezone.utc)
_last_cycle_info: dict[str, Any] = {
    "last_run": None,
    "last_status": "STARTING",
    "cycles_ok": 0,
    "cycles_error": 0,
}


# ---------------------------------------------------------------------------
# Health Check HTTP (GET /health)
# ---------------------------------------------------------------------------

class HealthHandler(BaseHTTPRequestHandler):
    """
    Endpoint HTTP minimal pour liveness/readiness probes (Kubernetes / Docker).

    GET /health  → 200 OK  si pipeline opérationnel
                 → 503     si DB inaccessible ou scheduler arrêté
    GET /metrics → 200     métriques texte simples (uptime, cycles…)
    """

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._handle_health()
        elif self.path == "/metrics":
            self._handle_metrics()
        else:
            self.send_response(404)
            self.end_headers()

    def _handle_health(self) -> None:
        db_ok = health_check()
        scheduler_ok = not _shutdown_event.is_set()

        if db_ok and scheduler_ok:
            status_code = 200
            body = b'{"status":"ok"}'
        else:
            status_code = 503
            reason = []
            if not db_ok:
                reason.append("db_unavailable")
            if not scheduler_ok:
                reason.append("scheduler_stopped")
            body = f'{{"status":"error","reasons":{reason}}}'.encode()

        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def _handle_metrics(self) -> None:
        uptime_s = (datetime.now(timezone.utc) - _startup_time).total_seconds()
        lines = [
            f"pipeline_uptime_seconds {uptime_s:.0f}",
            f"pipeline_cycles_ok {_last_cycle_info['cycles_ok']}",
            f"pipeline_cycles_error {_last_cycle_info['cycles_error']}",
            f"pipeline_db_healthy {1 if health_check() else 0}",
        ]
        body = "\n".join(lines).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        pass  # Silencer les logs HTTP dans stdout


def _start_health_server(port: int = 8080) -> threading.Thread:
    """Lance le serveur HTTP health check dans un thread daemon."""
    server = HTTPServer(("0.0.0.0", port), HealthHandler)

    thread = threading.Thread(target=server.serve_forever, daemon=True, name="health-server")
    thread.start()
    log.info(f"Health check HTTP démarré sur le port {port}")
    return thread


# ---------------------------------------------------------------------------
# Gestion des signaux — graceful shutdown
# ---------------------------------------------------------------------------

def _handle_signal(signum: int, frame: Any) -> None:
    sig_name = signal.Signals(signum).name
    log.warning(f"Signal reçu : {sig_name} — arrêt propre en cours…")
    _shutdown_event.set()


def _register_signals() -> None:
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)
    log.debug("Handlers SIGTERM / SIGINT enregistrés")


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------

def _init_pipeline() -> None:
    """Séquence d'initialisation complète — fail-fast si erreur critique."""
    log.info("=" * 60)
    log.info("Démarrage — Pipeline Mobilité Durable")
    log.info(f"  Environnement : {settings.env}")
    log.info(f"  Villes        : Lille + Montpellier")
    log.info(f"  DB            : {settings.database_url.split('@')[-1]}")  # masque creds
    log.info("=" * 60)

    # Base de données
    log.info("Initialisation de la base de données…")
    init_db()

    if not health_check():
        log.critical("Impossible de joindre PostgreSQL — arrêt.")
        sys.exit(1)

    log.info("Base de données : OK")


# ---------------------------------------------------------------------------
# Boucle principale
# ---------------------------------------------------------------------------

def main() -> None:
    _register_signals()
    _init_pipeline()

    # Health check HTTP
    _start_health_server(port=settings.health_port)

    # Scheduler APScheduler (jobs définis en Partie 2 + purge journalière)
    scheduler = build_scheduler()

    # Job de purge quotidien
    scheduler.add_job(
        func=_purge_job,
        trigger="cron",
        hour=3,
        minute=0,
        id="purge_daily",
        name="Purge données > 90j",
        replace_existing=True,
    )

    scheduler.start()
    log.info("Scheduler démarré — jobs actifs :")
    for job in scheduler.get_jobs():
        log.info(f"  [{job.id}] {job.name}")

    log.info("Pipeline opérationnel — en attente d'événements…")

    # Boucle keep-alive — se termine proprement sur SIGTERM/SIGINT
    try:
        while not _shutdown_event.is_set():
            _shutdown_event.wait(timeout=5)
    finally:
        log.info("Arrêt du scheduler…")
        scheduler.shutdown(wait=True)
        log.info("Pipeline arrêté proprement.")


def _purge_job() -> None:
    """Job APScheduler — purge des données anciennes."""
    try:
        deleted = purge_old_data(retention_days=90)
        log.info(f"Purge quotidienne terminée : {deleted}")
    except Exception as exc:
        log.error(f"Erreur purge quotidienne : {exc}")


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    main()
