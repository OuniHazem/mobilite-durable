"""gunicorn.conf.py — Configuration gunicorn pour Render"""

import os

workers = int(os.environ.get("WEB_CONCURRENCY", 1))
threads = 4
worker_class = "gthread"
timeout = 120
bind = "0.0.0.0:" + os.environ.get("PORT", "10000")


def on_starting(server):
    """Hook appelé une seule fois au démarrage du serveur gunicorn."""
    from render_dashboard import _ensure_pipeline
    _ensure_pipeline()
