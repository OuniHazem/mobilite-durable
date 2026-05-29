"""
streaming/powerbi_pusher.py
===========================
Push des données vers Power BI REST API — Projet Mobilité Durable

2 modes d'authentification :
  - OAuth2 Azure AD  (production) : token MSAL, refresh automatique
  - Push URL directe (dev)        : URL copiée depuis Power BI

2 modes de push :
  - push()          → lignes plates (5 tables, schéma classique)
  - push_pivoted()  → 1 ligne pivotée par cycle (16 colonnes, mode hybride pushStreaming)

Fonctionnalités :
  - Chunking automatique (9 000 lignes / requête — limite PBI 10 000)
  - Dead letter queue en mémoire (500 items max) — re-tentative automatique
  - Retry exponentiel (tenacity)
  - Dataset mode PushStreaming : historique conservé + tiles temps réel
  - Score global calculé automatiquement dans le mode pivoté
"""

from __future__ import annotations

import time
from collections import deque
from datetime import datetime, timezone
from typing import Any

import requests
from tenacity import retry, stop_after_attempt, wait_exponential

from config.settings import settings
from processing.kpi_engine import KPIResult, NiveauAlerte
from utils.logger import get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

POWERBI_API_BASE = "https://api.powerbi.com/v1.0/myorg"
POWERBI_SCOPE = ["https://analysis.windows.net/powerbi/api/.default"]
CHUNK_SIZE = settings.powerbi_chunk_size          # 9 000 lignes
DEAD_LETTER_MAX = settings.powerbi_dead_letter_max  # 500 items


# ---------------------------------------------------------------------------
# PowerBIPusher
# ---------------------------------------------------------------------------

class PowerBIPusher:
    """
    Pousse les données KPI vers les datasets Power BI des deux villes.

    Usage dans jobs.py :
        pusher = PowerBIPusher()
        pusher.push("Lille", kpi_rows)
    """

    def __init__(self) -> None:
        self._token: str | None = None
        self._token_expiry: float = 0.0
        self._dead_letter: deque[dict] = deque(maxlen=DEAD_LETTER_MAX)
        self._session = requests.Session()
        self._session.headers.update({"Content-Type": "application/json"})
        log.info(f"PowerBIPusher initialisé — mode : {settings.powerbi_auth_mode}")

    # ------------------------------------------------------------------
    # Point d'entrée principal — lignes plates (5 tables)
    # ------------------------------------------------------------------

    def push(self, ville: str, rows: list[dict[str, Any]]) -> bool:
        """
        Pousse une liste de lignes vers le dataset Power BI de la ville.
        Retourne True si succès, False sinon (données mises en dead letter queue).
        """
        if not rows:
            return True

        # Retry depuis la dead letter queue d'abord
        self._flush_dead_letter()

        # Chunking
        chunks = [rows[i:i + CHUNK_SIZE] for i in range(0, len(rows), CHUNK_SIZE)]
        success = True

        for chunk in chunks:
            try:
                self._push_chunk(ville, chunk)
            except Exception as exc:
                log.error(f"Push Power BI [{ville}] échoué : {exc}")
                self._dead_letter.append({"ville": ville, "rows": chunk, "ts": time.time()})
                success = False

        return success

    # ------------------------------------------------------------------
    # Push d'un chunk
    # ------------------------------------------------------------------

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    def _push_chunk(self, ville: str, rows: list[dict[str, Any]]) -> None:
        """Pousse un chunk vers Power BI — avec retry automatique."""
        if settings.powerbi_auth_mode == "oauth2":
            self._push_oauth2(ville, rows)
        else:
            self._push_url_directe(ville, rows)

    # ------------------------------------------------------------------
    # Mode Push URL directe (dev)
    # ------------------------------------------------------------------

    def _push_url_directe(self, ville: str, rows: list[dict[str, Any]]) -> None:
        """Pousse via Push URL copiée depuis Power BI (mode dev)."""
        url = (
            settings.powerbi_push_url_lille
            if ville == "Lille"
            else settings.powerbi_push_url_montpellier
        )

        if not url:
            log.warning(f"Push URL non configurée pour {ville} — push ignoré")
            return

        payload = {"rows": rows}
        resp = self._session.post(url, json=payload, timeout=30)
        resp.raise_for_status()
        log.debug(f"Push URL [{ville}] : {len(rows)} lignes → HTTP {resp.status_code}")

    # ------------------------------------------------------------------
    # Mode OAuth2 Azure AD (prod)
    # ------------------------------------------------------------------

    def _push_oauth2(self, ville: str, rows: list[dict[str, Any]]) -> None:
        """Pousse via l'API REST Power BI avec token OAuth2."""
        token = self._get_token()
        dataset_id = (
            settings.powerbi_dataset_id_lille
            if ville == "Lille"
            else settings.powerbi_dataset_id_montpellier
        )

        if not dataset_id:
            log.warning(f"Dataset ID non configuré pour {ville} — push ignoré")
            return

        url = (
            f"{POWERBI_API_BASE}/groups/{settings.powerbi_workspace_id}"
            f"/datasets/{dataset_id}/tables/KPIs_Temps_Reel/rows"
        )

        headers = {"Authorization": f"Bearer {token}"}
        payload = {"rows": rows}

        resp = self._session.post(url, json=payload, headers=headers, timeout=30)
        resp.raise_for_status()
        log.debug(f"OAuth2 [{ville}] : {len(rows)} lignes → HTTP {resp.status_code}")

    # ------------------------------------------------------------------
    # Gestion token OAuth2 (MSAL)
    # ------------------------------------------------------------------

    def _get_token(self) -> str:
        """Retourne un token valide — le rafraîchit si expiré."""
        now = time.time()
        if self._token and now < self._token_expiry - 60:
            return self._token

        try:
            import msal
        except ImportError:
            raise RuntimeError("msal non installé — pip install msal")

        app = msal.ConfidentialClientApplication(
            client_id=settings.azure_client_id,
            client_credential=settings.azure_client_secret,
            authority=f"https://login.microsoftonline.com/{settings.azure_tenant_id}",
        )

        result = app.acquire_token_for_client(scopes=POWERBI_SCOPE)

        if "access_token" not in result:
            error = result.get("error_description", "Token Azure AD non obtenu")
            raise RuntimeError(f"Erreur auth Azure AD : {error}")

        self._token = result["access_token"]
        self._token_expiry = now + result.get("expires_in", 3600)
        log.debug("Token Azure AD rafraîchi")
        return self._token

    # ------------------------------------------------------------------
    # Point d'entrée — mode pivoté (1 ligne par cycle, pushStreaming hybride)
    # ------------------------------------------------------------------

    def push_pivoted(self, kpi_results: list[KPIResult], ville: str) -> bool:
        """
        Pousse les KPIs pivotés vers Power BI — 1 ligne par cycle de calcul.
        Mode pushStreaming (hybride) : tiles temps réel + historique + rapports.

        Args :
            kpi_results : liste de KPIResult produits par KPIEngine.compute()
            ville       : "Lille" | "Montpellier"
        """
        if not kpi_results:
            return True

        row = self._pivot(kpi_results, ville)

        if settings.powerbi_auth_mode == "oauth2":
            return self._push_pivoted_oauth2(row, ville)
        else:
            return self._push_pivoted_url(row, ville)

    # ------------------------------------------------------------------
    # Pivot : liste KPIResult → 1 dict avec 1 colonne par KPI
    # ------------------------------------------------------------------

    def _pivot(self, kpi_results: list[KPIResult], ville: str) -> dict[str, Any]:
        """
        Transforme une liste de KPIResult en une seule ligne pivotée.
        kpi_id "tc_ponctualite_lille" → colonne "tc_ponctualite"
        """
        row: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "ville": ville,
            # TC
            "tc_ponctualite":          None,
            "tc_retard_moyen":         None,
            "tc_retard_fort":          None,
            "tc_couverture":           None,
            # Vélos
            "velo_dispo_moy":          None,
            "velo_stations_vides":     None,
            "velo_stations_hs":        None,
            "velo_evolution":          None,
            # Air
            "air_atmo_moyen":          None,
            "air_jours_alerte":        None,
            "air_pm25":                None,
            # Trafic
            "trafic_congestion":       None,
            "trafic_troncons_fluides": None,
            "trafic_fluidite":         None,
            # Meta
            "nb_alertes":              0,
            "score_global":            None,
        }

        # Mapping kpi_id (sans suffixe ville) → nom de colonne
        _KPI_COL_MAP: dict[str, str] = {
            "tc_ponctualite":       "tc_ponctualite",
            "tc_retard_moyen":      "tc_retard_moyen",
            "tc_retard_fort":       "tc_retard_fort",
            "tc_couverture":        "tc_couverture",
            "velo_dispo_moy":       "velo_dispo_moy",
            "velo_stations_vides":  "velo_stations_vides",
            "velo_stations_hs":     "velo_stations_hs",
            "velo_evolution":       "velo_evolution",
            "air_atmo_moyen":       "air_atmo_moyen",
            "air_jours_alerte":     "air_jours_alerte",
            "air_pm25":             "air_pm25",
            "trafic_congestion_moy": "trafic_congestion",
            "trafic_troncons":      "trafic_troncons_fluides",
            "trafic_fluidite":      "trafic_fluidite",
        }

        ville_lower = ville.lower()
        nb_alertes = 0

        for kpi in kpi_results:
            # Ignore les KPIs par ligne (drill-down trop détaillé pour le dashboard)
            if "_ligne_" in kpi.kpi_id:
                continue

            # Nettoie le kpi_id : "velo_dispo_moy_lille" → "velo_dispo_moy"
            col_key = kpi.kpi_id.replace(f"_{ville_lower}", "")

            if col_key in _KPI_COL_MAP:
                col_name = _KPI_COL_MAP[col_key]
                row[col_name] = round(float(kpi.valeur), 4) if kpi.valeur is not None else None

            # Compte les alertes (ATTENTION + ALERTE + CRITIQUE)
            if kpi.alerte in (NiveauAlerte.ATTENTION, NiveauAlerte.ALERTE, NiveauAlerte.CRITIQUE):
                nb_alertes += 1

        row["nb_alertes"] = nb_alertes

        # Score global : moyenne des KPIs positifs disponibles
        positifs = [
            row["tc_ponctualite"],
            row["velo_dispo_moy"],
            (100 - (row["air_atmo_moyen"] * 10)) if row["air_atmo_moyen"] is not None else None,
            row["trafic_fluidite"],
        ]
        valides = [v for v in positifs if v is not None]
        row["score_global"] = round(sum(valides) / len(valides), 2) if valides else None

        return row

    # ------------------------------------------------------------------
    # Push pivoté — mode Push URL (dev)
    # ------------------------------------------------------------------

    def _push_pivoted_url(self, row: dict[str, Any], ville: str) -> bool:
        push_url = (
            settings.powerbi_push_url_lille
            if ville == "Lille"
            else settings.powerbi_push_url_montpellier
        )
        if not push_url:
            log.warning(f"Push URL non configurée pour {ville} — push pivoté ignoré")
            return False
        return self._do_pivoted_push(push_url, row, ville, headers=None)

    # ------------------------------------------------------------------
    # Push pivoté — mode OAuth2 (prod)
    # ------------------------------------------------------------------

    def _push_pivoted_oauth2(self, row: dict[str, Any], ville: str) -> bool:
        try:
            token = self._get_token()
        except Exception as exc:
            log.error(f"OAuth2 token failed : {exc}")
            return False

        dataset_id = (
            settings.powerbi_dataset_id_lille
            if ville == "Lille"
            else settings.powerbi_dataset_id_montpellier
        )
        if not dataset_id:
            log.error(f"POWERBI_DATASET_ID_{ville.upper()} non configuré dans .env")
            return False

        url = (
            f"{POWERBI_API_BASE}/groups/{settings.powerbi_workspace_id}"
            f"/datasets/{dataset_id}/tables/KPIs/rows"
        )
        headers = {"Authorization": f"Bearer {token}"}
        return self._do_pivoted_push(url, row, ville, headers=headers)

    # ------------------------------------------------------------------
    # Push HTTP réel pivoté avec retry
    # ------------------------------------------------------------------

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=False,
    )
    def _do_pivoted_push(self, url: str, row: dict[str, Any], ville: str,
                          headers: dict[str, str] | None = None) -> bool:
        payload = {"rows": [row]}
        resp = self._session.post(url, json=payload, headers=headers, timeout=30)
        if resp.status_code == 200:
            log.debug(f"Push pivoté [{ville}] OK — score={row.get('score_global')}")
            return True
        else:
            log.error(f"Push pivoté [{ville}] HTTP {resp.status_code} : {resp.text[:200]}")
            self._dead_letter.append({"ville": ville, "rows": [row], "ts": time.time(), "pivoted": True})
            return False

    # ------------------------------------------------------------------
    # Dead letter queue
    # ------------------------------------------------------------------

    def _flush_dead_letter(self) -> None:
        """
        Tente de re-pousser les items en attente dans la dead letter queue.
        Appelé au début de chaque push().
        """
        if not self._dead_letter:
            return

        nb = len(self._dead_letter)
        log.info(f"Dead letter queue : tentative de re-push de {nb} item(s)")

        to_retry = list(self._dead_letter)
        self._dead_letter.clear()

        for item in to_retry:
            age_min = (time.time() - item["ts"]) / 60
            try:
                self._push_chunk(item["ville"], item["rows"])
                log.info(f"Dead letter re-push OK [{item['ville']}] — âge : {age_min:.1f} min")
            except Exception as exc:
                log.warning(f"Dead letter re-push échoué [{item['ville']}] : {exc}")
                # Remet en queue si toujours en échec
                self._dead_letter.append(item)

    @property
    def dead_letter_size(self) -> int:
        return len(self._dead_letter)
