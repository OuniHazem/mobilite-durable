"""
config/settings.py
==================
Configuration centralisée — Projet Mobilité Durable
Chargement depuis config/.env via python-dotenv.
Expose un objet `settings` utilisé dans tout le projet.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Charge le fichier config/.env (chemin relatif au présent fichier)
load_dotenv(dotenv_path=Path(__file__).parent / ".env", override=False)


def _get(key: str, default: str = "") -> str:
    return os.getenv(key, default)


def _get_int(key: str, default: int = 0) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except ValueError:
        return default


def _get_float(key: str, default: float = 0.0) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except ValueError:
        return default


class Settings:
    """
    Objet de configuration unique partagé dans tout le projet.
    Toutes les valeurs sont lues depuis l'environnement (ou config/.env).
    """

    # ------------------------------------------------------------------
    # Général
    # ------------------------------------------------------------------
    env: str = _get("ENV", "development")
    log_level: str = _get("LOG_LEVEL", "INFO").upper()
    health_port: int = _get_int("HEALTH_PORT", 8080)

    # ------------------------------------------------------------------
    # Base de données
    # ------------------------------------------------------------------
    @property
    def database_url(self) -> str:
        """Construit l'URL PostgreSQL depuis les variables d'env."""
        direct = _get("DATABASE_URL")
        if direct:
            # Render fournit postgresql:// mais SQLAlchemy veut postgresql+psycopg2://
            if direct.startswith("postgresql://") and "+psycopg2" not in direct:
                direct = direct.replace("postgresql://", "postgresql+psycopg2://", 1)
            return direct
        host = _get("POSTGRES_HOST", "localhost")
        port = _get_int("POSTGRES_PORT", 5432)
        db   = _get("POSTGRES_DB", "mobilite_durable")
        user = _get("POSTGRES_USER", "mobilite")
        pwd  = _get("POSTGRES_PASSWORD", "secret")
        return f"postgresql+psycopg2://{user}:{pwd}@{host}:{port}/{db}"

    # ------------------------------------------------------------------
    # Sources Lille — GBFS (vélos) + ODS Explore (air/trafic, si disponible)
    # ------------------------------------------------------------------
    lille_gbfs_base_url: str = _get(
        "LILLE_GBFS_BASE_URL",
        "https://media.ilevia.fr/opendata",
    )
    lille_api_base_url: str = _get(
        "LILLE_API_BASE_URL",
        "https://data.lillemetropole.fr/api/explore/v2.1/catalog/datasets",
    )
    lille_atmo_api_url: str = _get(
        "LILLE_ATMO_API_URL",
        "https://services8.arcgis.com/rxZzohbySMKHTNcy/ArcGIS/rest/services/ind_hdf_3j/FeatureServer/0/query",
    )
    lille_dataset_velos: str = _get(
        "LILLE_DATASET_VELOS",
        "disponibilite-des-velos-v-lille-metropole",
    )
    lille_dataset_air: str = _get(
        "LILLE_DATASET_AIR",
        "indice-atmo-nord-pas-de-calais",
    )
    lille_dataset_trafic: str = _get(
        "LILLE_DATASET_TRAFIC",
        "etat-du-trafic-en-temps-reel",
    )

    # ------------------------------------------------------------------
    # Sources Montpellier — GBFS (vélos) + DKAN (air/trafic)
    # ------------------------------------------------------------------
    montpellier_gbfs_base_url: str = _get(
        "MONTPELLIER_GBFS_BASE_URL",
        "https://gbfs.theta.fifteen.eu/gbfs/2.2/montpellier",
    )
    montpellier_atmo_api_url: str = _get(
        "MONTPELLIER_ATMO_API_URL",
        "https://services9.arcgis.com/7Sr9Ek9c1QTKmbwr/arcgis/rest/services/mesures_occitanie_journaliere_poll_princ/FeatureServer/0/query",
    )
    montpellier_ckan_base_url: str = _get(
        "MONTPELLIER_CKAN_BASE_URL",
        "https://data.montpellier3m.fr",
    )
    montpellier_dataset_velos: str = _get(
        "MONTPELLIER_DATASET_VELOS",
        "tan-tan-disponibilite-temps-reel",
    )
    montpellier_dataset_air: str = _get(
        "MONTPELLIER_DATASET_AIR",
        "qualite-de-lair-sur-montpellier",
    )
    montpellier_dataset_trafic: str = _get(
        "MONTPELLIER_DATASET_TRAFIC",
        "etat-du-trafic-en-temps-reel-montpellier",
    )

    # ------------------------------------------------------------------
    # GTFS-RT
    # ------------------------------------------------------------------
    gtfsrt_ilevia_url: str = _get(
        "GTFSRT_ILEVIA_URL",
        "https://proxy.transport.data.gouv.fr/resource/ilevia-lille-gtfs-rt",
    )
    gtfsrt_tam_url: str = _get(
        "GTFSRT_TAM_URL",
        "https://data.montpellier3m.fr/GTFS/Urbain/TripUpdate.pb",
    )
    gtfsrt_refresh_s: int = _get_int("GTFSRT_REFRESH_S", 20)

    # ------------------------------------------------------------------
    # TomTom Traffic API
    # ------------------------------------------------------------------
    tomtom_api_key: str = _get("TOMTOM_API_KEY", "")
    tomtom_base_url: str = _get(
        "TOMTOM_BASE_URL",
        "https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/10/json",
    )

    # ------------------------------------------------------------------
    # HTTP Client
    # ------------------------------------------------------------------
    http_timeout_s: int     = _get_int("HTTP_TIMEOUT_S", 30)
    http_max_retries: int   = _get_int("HTTP_MAX_RETRIES", 3)
    http_retry_wait_s: float = _get_float("HTTP_RETRY_WAIT_S", 2.0)

    # ------------------------------------------------------------------
    # Scheduler
    # ------------------------------------------------------------------
    ckan_refresh_s: int = _get_int("CKAN_REFRESH_S", 60)

    # ------------------------------------------------------------------
    # Power BI — Mode dev (Push URL directe)
    # ------------------------------------------------------------------
    powerbi_push_url_lille: str        = _get("POWERBI_PUSH_URL_LILLE", "")
    powerbi_push_url_montpellier: str  = _get("POWERBI_PUSH_URL_MONTPELLIER", "")

    # ------------------------------------------------------------------
    # Power BI — Mode prod (OAuth2 Azure AD)
    # ------------------------------------------------------------------
    azure_tenant_id: str              = _get("AZURE_TENANT_ID", "")
    azure_client_id: str              = _get("AZURE_CLIENT_ID", "")
    azure_client_secret: str          = _get("AZURE_CLIENT_SECRET", "")
    powerbi_workspace_id: str         = _get("POWERBI_WORKSPACE_ID", "")
    powerbi_dataset_id_lille: str     = _get("POWERBI_DATASET_ID_LILLE", "")
    powerbi_dataset_id_montpellier: str = _get("POWERBI_DATASET_ID_MONTPELLIER", "")

    # ------------------------------------------------------------------
    # Power BI — Paramètres push
    # ------------------------------------------------------------------
    powerbi_chunk_size: int       = _get_int("POWERBI_CHUNK_SIZE", 9000)
    powerbi_dead_letter_max: int  = _get_int("POWERBI_DEAD_LETTER_MAX", 500)

    # ------------------------------------------------------------------
    # Rétention
    # ------------------------------------------------------------------
    retention_days: int = _get_int("RETENTION_DAYS", 90)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @property
    def is_production(self) -> bool:
        return self.env == "production"

    @property
    def is_test(self) -> bool:
        return self.env == "test"

    @property
    def powerbi_auth_mode(self) -> str:
        """
        Détecte automatiquement le mode d'auth Power BI.
        - 'oauth2'   : variables Azure AD renseignées
        - 'push_url' : sinon (mode dev)
        """
        if all([self.azure_tenant_id, self.azure_client_id, self.azure_client_secret]):
            return "oauth2"
        return "push_url"


# Instance unique partagée dans tout le projet
# Import : from config.settings import settings
settings = Settings()


# ---------------------------------------------------------------------------
# Patch Windows encoding — à appeler au démarrage (dans main.py)
# ---------------------------------------------------------------------------
def patch_windows_encoding() -> None:
    """
    Force l'encodage UTF-8 sur Windows pour éviter les UnicodeDecodeError.
    Sans effet sur Linux/Mac.
    """
    import sys
    import os
    if sys.platform == "win32":
        # Force l'encodage codec de l'interpréteur Python
        os.environ.setdefault("PYTHONIOENCODING", "utf-8")
        # Force l'encodage stdout/stderr
        if hasattr(sys.stdout, "reconfigure"):
            try:
                sys.stdout.reconfigure(encoding="utf-8", errors="replace")
                sys.stderr.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass
