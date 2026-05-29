"""
streaming/powerbi_pivoted.py
============================
Schéma pivoté Power BI — une colonne par KPI, pas de filtrage nécessaire.

Mode pushStreaming (hybride) :
  - Tiles dashboard → mise à jour INSTANTANÉE ⚡
  - Rapports interactifs → historique complet 📊

Colonnes du dataset pivoté (18 colonnes) :
  timestamp               DateTime
  ville                   String
  tc_ponctualite          Double   (%)
  tc_retard_moyen         Double   (min)
  tc_retard_fort          Double   (%)
  tc_couverture           Double   (%)
  velo_dispo_moy          Double   (%)
  velo_stations_vides     Double   (%)
  velo_stations_hs        Double   (%)
  velo_evolution          Double   (%)
  air_atmo_moyen          Double   (indice/10)
  air_jours_alerte        Double   (jours)
  air_pm25                Double   (dépassements)
  trafic_congestion       Double   (score/100)
  trafic_troncons_fluides Double   (% fluides)
  trafic_fluidite         Double   (indice/100)
  nb_alertes              Int64    (compteur)
  score_global            Double   (score composite)

Usage :
  python streaming/powerbi_pivoted.py          # créer les datasets (mode OAuth2)
  Le push est assuré par PowerBIPusher.push_pivoted() dans powerbi_pusher.py
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import requests

from config.settings import settings
from processing.kpi_engine import KPIEngine, KPIResult, NiveauAlerte
from utils.logger import get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Schéma pivoté — une colonne par KPI (source de vérité)
# ---------------------------------------------------------------------------

PIVOTED_SCHEMA = {
    "name": "MobiliteDurable_Pivote",
    "defaultMode": "PushStreaming",           # hybride : temps réel + historique
    "tables": [
        {
            "name": "KPIs",
            "columns": [
                {"name": "timestamp",              "dataType": "datetime"},
                {"name": "ville",                  "dataType": "string"},
                # TC
                {"name": "tc_ponctualite",         "dataType": "double"},
                {"name": "tc_retard_moyen",        "dataType": "double"},
                {"name": "tc_retard_fort",         "dataType": "double"},
                {"name": "tc_couverture",          "dataType": "double"},
                # Vélos
                {"name": "velo_dispo_moy",         "dataType": "double"},
                {"name": "velo_stations_vides",    "dataType": "double"},
                {"name": "velo_stations_hs",       "dataType": "double"},
                {"name": "velo_evolution",         "dataType": "double"},
                # Air
                {"name": "air_atmo_moyen",         "dataType": "double"},
                {"name": "air_jours_alerte",       "dataType": "double"},
                {"name": "air_pm25",               "dataType": "double"},
                # Trafic
                {"name": "trafic_congestion",      "dataType": "double"},
                {"name": "trafic_troncons_fluides","dataType": "double"},
                {"name": "trafic_fluidite",        "dataType": "double"},
                # Meta
                {"name": "nb_alertes",             "dataType": "int64"},
                {"name": "score_global",           "dataType": "double"},
            ],
        },
    ],
}

# Mapping kpi_id → nom de colonne pivotée
_KPI_MAP: dict[str, str] = {
    "tc_ponctualite":       "tc_ponctualite",
    "tc_retard_moyen":      "tc_retard_moyen",
    "tc_retard_fort":       "tc_retard_fort",
    "tc_couverture":        "tc_couverture",
    "velo_dispo_moy":       "velo_dispo_moy",
    "velo_stations_vides":  "velo_stations_vides",
    "velo_stations_hs":     "velo_stations_hs",
    "velo_evolution":       "velo_evolution",
    "air_atmo_moyen":       "air_atmo_moyen",
    "air_jours_alerte":    "air_jours_alerte",
    "air_pm25":             "air_pm25",
    "trafic_congestion_moy": "trafic_congestion",
    "trafic_troncons":      "trafic_troncons_fluides",
    "trafic_fluidite":      "trafic_fluidite",
}


def pivot_kpi_rows(rows: list[dict[str, Any]], ville: str = "") -> dict[str, Any]:
    """
    Transforme une liste de lignes KPI plates en une seule ligne pivotée.
    Exclut les KPIs par ligne (drill-down) pour garder un agrégat propre.

    Args :
        rows  : liste de dicts issus de KPIEngine.to_powerbi_rows()
        ville : nom de la ville (ajouté dans la colonne ville)
    """
    pivoted: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "ville": ville,
        "tc_ponctualite": None,
        "tc_retard_moyen": None,
        "tc_retard_fort": None,
        "tc_couverture": None,
        "velo_dispo_moy": None,
        "velo_stations_vides": None,
        "velo_stations_hs": None,
        "velo_evolution": None,
        "air_atmo_moyen": None,
        "air_jours_alerte": None,
        "air_pm25": None,
        "trafic_congestion": None,
        "trafic_troncons_fluides": None,
        "trafic_fluidite": None,
        "nb_alertes": 0,
        "score_global": None,
    }

    nb_alertes = 0

    for row in rows:
        kpi_id: str = row.get("kpi_id", "")
        valeur: float = row.get("valeur", 0)
        alerte: str = row.get("alerte", "")

        # Ignorer les KPIs par ligne (trop détaillés pour le dashboard)
        if "_ligne_" in kpi_id:
            continue

        # Compter les alertes
        if alerte in ("ALERTE", "CRITIQUE"):
            nb_alertes += 1

        # Mapper kpi_id → colonne
        for prefix, col in _KPI_MAP.items():
            if kpi_id.startswith(prefix):
                pivoted[col] = valeur
                break

    pivoted["nb_alertes"] = nb_alertes

    # Score global : moyenne des KPIs positifs disponibles
    positifs = [
        pivoted["tc_ponctualite"],
        pivoted["velo_dispo_moy"],
        (100 - (pivoted["air_atmo_moyen"] * 10)) if pivoted["air_atmo_moyen"] is not None else None,
        pivoted["trafic_fluidite"],
    ]
    valides = [v for v in positifs if v is not None]
    pivoted["score_global"] = round(sum(valides) / len(valides), 2) if valides else None

    return pivoted


def push_pivoted(ville: str, kpi_rows: list[dict[str, Any]]) -> bool:
    """
    Pousse une ligne pivotée vers le dataset Power BI d'une ville.
    Délègue au PowerBIPusher.push_pivoted() pour réutiliser l'infrastructure HTTP.

    Retourne True si succès.
    """
    from streaming.powerbi_pusher import PowerBIPusher

    pusher = PowerBIPusher()

    url = (
        settings.powerbi_push_url_lille
        if ville == "Lille"
        else settings.powerbi_push_url_montpellier
    )

    if not url:
        log.warning(f"Push URL non configurée pour {ville}")
        return False

    pivoted_row = pivot_kpi_rows(kpi_rows, ville=ville)
    payload = {"rows": [pivoted_row]}

    try:
        resp = requests.post(url, json=payload, timeout=30)
        resp.raise_for_status()
        log.debug(f"Push pivoté [{ville}] OK — {len(kpi_rows)} KPIs → 1 ligne")
        return True
    except Exception as exc:
        log.error(f"Push pivoté [{ville}] échoué : {exc}")
        return False


# ---------------------------------------------------------------------------
# Script de provisioning
# ---------------------------------------------------------------------------

def create_pivoted_datasets() -> None:
    """
    Crée les datasets pivotés dans Power BI via l'API REST.
    Prérequis : mode OAuth2 configuré.
    """
    from streaming.powerbi_pusher import PowerBIPusher

    pusher = PowerBIPusher()
    token = pusher._get_token()

    for ville in ["Lille", "Montpellier"]:
        schema = json.loads(json.dumps(PIVOTED_SCHEMA))
        schema["name"] = f"MobiliteDurable_{ville}"

        url = (
            f"https://api.powerbi.com/v1.0/myorg/groups/"
            f"{settings.powerbi_workspace_id}/datasets"
        )
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        resp = requests.post(url, json=schema, headers=headers, timeout=30)

        if resp.status_code in (200, 201):
            dataset_id = resp.json().get("id")
            print(f"✅ Dataset {ville} créé — ID : {dataset_id}")
        else:
            print(f"❌ Erreur {ville} : {resp.status_code} — {resp.text[:200]}")


if __name__ == "__main__":
    if settings.powerbi_auth_mode != "oauth2":
        print("⚠️  Mode OAuth2 non configuré.")
        print("Crée manuellement le dataset dans Power BI avec les colonnes :")
        print(json.dumps(PIVOTED_SCHEMA["tables"][0]["columns"], indent=2))
    else:
        create_pivoted_datasets()
