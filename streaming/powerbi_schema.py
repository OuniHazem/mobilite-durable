"""
streaming/powerbi_schema.py
===========================
Définition du schéma dataset Power BI — Projet Mobilité Durable

Contenu :
  - Schéma des 5 tables Power BI (colonnes + types)
  - Mesures DAX préconfigurées
  - Script de provisioning automatique via API REST
  - Mode PushStreaming : historique conservé + tiles temps réel

Utilisation :
  python streaming/powerbi_schema.py
  → crée les datasets Lille et Montpellier dans Power BI
"""

from __future__ import annotations

import json

import requests

from config.settings import settings
from streaming.powerbi_pusher import PowerBIPusher
from utils.logger import get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Schéma des tables
# ---------------------------------------------------------------------------

POWERBI_SCHEMA = {
    "name": "MobiliteDurable",
    "defaultMode": "PushStreaming",   # historique conservé + streaming tiles
    "tables": [

        # Table 1 — KPIs temps réel (table principale)
        {
            "name": "KPIs_Temps_Reel",
            "columns": [
                {"name": "kpi_id",          "dataType": "string"},
                {"name": "kpi_label",       "dataType": "string"},
                {"name": "valeur",          "dataType": "double"},
                {"name": "unite",           "dataType": "string"},
                {"name": "ville",           "dataType": "string"},
                {"name": "domaine",         "dataType": "string"},
                {"name": "fenetre",         "dataType": "string"},
                {"name": "alerte",          "dataType": "string"},
                {"name": "timestamp_calcul","dataType": "datetime"},
            ],
            "measures": [
                {
                    "name": "Taux Ponctualité TC (%)",
                    "expression": (
                        "CALCULATE("
                        "AVERAGE(KPIs_Temps_Reel[valeur]),"
                        "KPIs_Temps_Reel[domaine] = \"TC\","
                        "SEARCH(\"ponctualite\", KPIs_Temps_Reel[kpi_id], 1, 0) > 0"
                        ")"
                    ),
                },
                {
                    "name": "Disponibilité Vélos (%)",
                    "expression": (
                        "CALCULATE("
                        "AVERAGE(KPIs_Temps_Reel[valeur]),"
                        "KPIs_Temps_Reel[domaine] = \"VELO\","
                        "SEARCH(\"dispo_moy\", KPIs_Temps_Reel[kpi_id], 1, 0) > 0"
                        ")"
                    ),
                },
                {
                    "name": "Indice ATMO Moyen",
                    "expression": (
                        "CALCULATE("
                        "AVERAGE(KPIs_Temps_Reel[valeur]),"
                        "KPIs_Temps_Reel[domaine] = \"AIR\","
                        "SEARCH(\"atmo_moyen\", KPIs_Temps_Reel[kpi_id], 1, 0) > 0"
                        ")"
                    ),
                },
                {
                    "name": "Score Congestion Moyen",
                    "expression": (
                        "CALCULATE("
                        "AVERAGE(KPIs_Temps_Reel[valeur]),"
                        "KPIs_Temps_Reel[domaine] = \"TRAFIC\","
                        "SEARCH(\"congestion_moy\", KPIs_Temps_Reel[kpi_id], 1, 0) > 0"
                        ")"
                    ),
                },
                {
                    "name": "Nb KPIs en Alerte",
                    "expression": (
                        "CALCULATE("
                        "COUNTROWS(KPIs_Temps_Reel),"
                        "KPIs_Temps_Reel[alerte] IN {\"ALERTE\", \"CRITIQUE\"}"
                        ")"
                    ),
                },
            ],
        },

        # Table 2 — Retards TC
        {
            "name": "TC_Retards",
            "columns": [
                {"name": "ville",                   "dataType": "string"},
                {"name": "ligne_id",                "dataType": "string"},
                {"name": "vehicle_id",              "dataType": "string"},
                {"name": "retard_s",                "dataType": "int64"},
                {"name": "retard_min",              "dataType": "double"},
                {"name": "en_retard",               "dataType": "bool"},
                {"name": "retard_fort",             "dataType": "bool"},
                {"name": "latitude",                "dataType": "double"},
                {"name": "longitude",               "dataType": "double"},
                {"name": "timestamp_observation",   "dataType": "datetime"},
            ],
            "measures": [
                {
                    "name": "Retard Moyen (min)",
                    "expression": (
                        "CALCULATE("
                        "AVERAGE(TC_Retards[retard_min]),"
                        "TC_Retards[en_retard] = TRUE()"
                        ")"
                    ),
                },
                {
                    "name": "Taux Ponctualité Ligne (%)",
                    "expression": (
                        "DIVIDE("
                        "CALCULATE(COUNTROWS(TC_Retards), TC_Retards[en_retard] = FALSE()),"
                        "COUNTROWS(TC_Retards)"
                        ") * 100"
                    ),
                },
            ],
        },

        # Table 3 — Stations Vélos
        {
            "name": "Velo_Stations",
            "columns": [
                {"name": "ville",                   "dataType": "string"},
                {"name": "station_id",              "dataType": "string"},
                {"name": "nom_station",             "dataType": "string"},
                {"name": "velos_disponibles",       "dataType": "int64"},
                {"name": "capacite",                "dataType": "int64"},
                {"name": "en_service",              "dataType": "bool"},
                {"name": "taux_dispo",              "dataType": "double"},
                {"name": "latitude",                "dataType": "double"},
                {"name": "longitude",               "dataType": "double"},
                {"name": "timestamp_observation",   "dataType": "datetime"},
            ],
            "measures": [
                {
                    "name": "Dispo Moyenne Globale (%)",
                    "expression": "AVERAGE(Velo_Stations[taux_dispo]) * 100",
                },
                {
                    "name": "Nb Stations Vides",
                    "expression": (
                        "CALCULATE("
                        "COUNTROWS(Velo_Stations),"
                        "Velo_Stations[velos_disponibles] = 0,"
                        "Velo_Stations[en_service] = TRUE()"
                        ")"
                    ),
                },
            ],
        },

        # Table 4 — Qualité de l'air
        {
            "name": "Qualite_Air",
            "columns": [
                {"name": "ville",                   "dataType": "string"},
                {"name": "station_id",              "dataType": "string"},
                {"name": "indice_atmo",             "dataType": "double"},
                {"name": "pm25",                    "dataType": "double"},
                {"name": "pm10",                    "dataType": "double"},
                {"name": "no2",                     "dataType": "double"},
                {"name": "alerte_atmo",             "dataType": "bool"},
                {"name": "depassement_oms_pm25",    "dataType": "bool"},
                {"name": "timestamp_observation",   "dataType": "datetime"},
            ],
            "measures": [
                {
                    "name": "Indice ATMO Actuel",
                    "expression": "LASTNONBLANK(Qualite_Air[indice_atmo], 1)",
                },
                {
                    "name": "Jours Alerte ATMO",
                    "expression": (
                        "CALCULATE("
                        "DISTINCTCOUNT(Qualite_Air[timestamp_observation]),"
                        "Qualite_Air[alerte_atmo] = TRUE()"
                        ")"
                    ),
                },
            ],
        },

        # Table 5 — Trafic
        {
            "name": "Trafic_Troncons",
            "columns": [
                {"name": "ville",                   "dataType": "string"},
                {"name": "troncon_id",              "dataType": "string"},
                {"name": "nom_troncon",             "dataType": "string"},
                {"name": "score_congestion",        "dataType": "double"},
                {"name": "longueur_km",             "dataType": "double"},
                {"name": "fluide",                  "dataType": "bool"},
                {"name": "bloque",                  "dataType": "bool"},
                {"name": "latitude_debut",          "dataType": "double"},
                {"name": "longitude_debut",         "dataType": "double"},
                {"name": "timestamp_observation",   "dataType": "datetime"},
            ],
            "measures": [
                {
                    "name": "Score Congestion Moyen",
                    "expression": "AVERAGE(Trafic_Troncons[score_congestion])",
                },
                {
                    "name": "% Tronçons Fluides",
                    "expression": (
                        "DIVIDE("
                        "CALCULATE(COUNTROWS(Trafic_Troncons), Trafic_Troncons[fluide] = TRUE()),"
                        "COUNTROWS(Trafic_Troncons)"
                        ") * 100"
                    ),
                },
            ],
        },
    ],
}


# ---------------------------------------------------------------------------
# Script de provisioning
# ---------------------------------------------------------------------------

def create_dataset(ville: str) -> str | None:
    """
    Crée le dataset Power BI pour une ville via l'API REST.
    Retourne le dataset_id créé, ou None en cas d'erreur.

    Prérequis : variables Azure AD renseignées dans .env
    """
    pusher = PowerBIPusher()
    token = pusher._get_token()

    schema = dict(POWERBI_SCHEMA)
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
        log.info(f"Dataset créé pour {ville} — ID : {dataset_id}")
        print(f"\n✅ Dataset {ville} créé avec succès !")
        print(f"   Dataset ID : {dataset_id}")
        print(f"   → Ajoute dans .env : POWERBI_DATASET_ID_{ville.upper()}={dataset_id}\n")
        return dataset_id
    else:
        log.error(f"Erreur création dataset {ville} : {resp.status_code} — {resp.text}")
        print(f"\n❌ Erreur création dataset {ville} : {resp.status_code}")
        print(f"   Détail : {resp.text}\n")
        return None


def print_schema() -> None:
    """Affiche le schéma JSON formaté — utile pour debug."""
    print(json.dumps(POWERBI_SCHEMA, indent=2, ensure_ascii=False))


# ---------------------------------------------------------------------------
# Exécution directe : python streaming/powerbi_schema.py
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 60)
    print("Provisioning datasets Power BI — Mobilité Durable")
    print("=" * 60)

    if settings.powerbi_auth_mode != "oauth2":
        print("\n⚠️  Variables Azure AD non configurées dans .env")
        print("   Configure AZURE_TENANT_ID, AZURE_CLIENT_ID, AZURE_CLIENT_SECRET")
        print("   puis relance ce script.\n")
        print("Schéma JSON du dataset :")
        print_schema()
    else:
        print(f"\nWorkspace ID : {settings.powerbi_workspace_id}")
        print("Création des datasets...\n")

        id_lille = create_dataset("Lille")
        id_mtp = create_dataset("Montpellier")

        if id_lille and id_mtp:
            print("\n📋 Ajoute ces lignes dans config/.env :")
            print(f"POWERBI_DATASET_ID_LILLE={id_lille}")
            print(f"POWERBI_DATASET_ID_MONTPELLIER={id_mtp}")
