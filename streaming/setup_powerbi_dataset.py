"""
streaming/setup_powerbi_dataset.py
==================================
Script de setup one-shot — Crée les datasets Power BI Hybrid (pushStreaming)
pour Lille et Montpellier avec le schéma pivoté 18 colonnes.

USAGE :
    python streaming/setup_powerbi_dataset.py

PRÉREQUIS :
    - Mode OAuth2 : config/.env doit contenir AZURE_TENANT_ID, AZURE_CLIENT_ID,
      AZURE_CLIENT_SECRET, POWERBI_WORKSPACE_ID
    - Mode Push URL : config/.env doit contenir POWERBI_PUSH_URL_LILLE et/ou
      POWERBI_PUSH_URL_MONTPELLIER

CE QUE LE SCRIPT FAIT :
    1. Détecte le mode d'authentification (OAuth2 ou Push URL)
    2. Mode OAuth2 : crée/recrée les datasets pushStreaming via l'API REST
    3. Mode Push URL : affiche les colonnes à créer manuellement + teste les URLs
    4. Teste un premier push pour valider

SCHÉMA PIVOTÉ (18 colonnes, 1 ligne par cycle) :
    timestamp, ville, tc_ponctualite, tc_retard_moyen, tc_retard_fort, tc_couverture,
    velo_dispo_moy, velo_stations_vides, velo_stations_hs, velo_evolution,
    air_atmo_moyen, air_jours_alerte, air_pm25,
    trafic_congestion, trafic_troncons_fluides, trafic_fluidite,
    nb_alertes, score_global
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

# Ajoute la racine au path pour les imports du projet
sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import settings, patch_windows_encoding
from streaming.powerbi_pivoted import PIVOTED_SCHEMA
from utils.logger import get_logger

patch_windows_encoding()

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# API Power BI REST
# ---------------------------------------------------------------------------

BASE_API = "https://api.powerbi.com/v1.0/myorg"


def get_headers_oauth2() -> dict[str, str]:
    """Auth Azure AD via MSAL (mode production)."""
    try:
        import msal
    except ImportError:
        log.error("msal non installé — pip install msal")
        sys.exit(1)

    app = msal.ConfidentialClientApplication(
        client_id=settings.azure_client_id,
        client_credential=settings.azure_client_secret,
        authority=f"https://login.microsoftonline.com/{settings.azure_tenant_id}",
    )
    result = app.acquire_token_for_client(
        scopes=["https://analysis.windows.net/powerbi/api/.default"]
    )
    if "access_token" not in result:
        log.error(f"Auth Azure AD échouée : {result.get('error_description')}")
        sys.exit(1)
    return {
        "Authorization": f"Bearer {result['access_token']}",
        "Content-Type": "application/json",
    }


def get_workspace_id() -> str:
    if settings.powerbi_workspace_id:
        return settings.powerbi_workspace_id
    log.error("POWERBI_WORKSPACE_ID non configuré dans .env")
    sys.exit(1)


def list_datasets(headers: dict, workspace_id: str) -> list[dict]:
    url = f"{BASE_API}/groups/{workspace_id}/datasets"
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.json().get("value", [])


def delete_dataset(headers: dict, workspace_id: str, dataset_id: str, name: str) -> None:
    url = f"{BASE_API}/groups/{workspace_id}/datasets/{dataset_id}"
    resp = requests.delete(url, headers=headers, timeout=30)
    if resp.status_code == 200:
        log.info(f"  Dataset supprimé : {name} ({dataset_id})")
    else:
        log.warning(f"  Suppression échouée ({resp.status_code}) : {name}")


def create_dataset(headers: dict, workspace_id: str, ville: str) -> dict:
    body = json.loads(json.dumps(PIVOTED_SCHEMA))
    body["name"] = f"MobiliteDurable_{ville}"
    url = f"{BASE_API}/groups/{workspace_id}/datasets"
    resp = requests.post(url, headers=headers, json=body, timeout=30)
    if resp.status_code not in (200, 201):
        log.error(f"  Création dataset {ville} échouée : {resp.status_code} — {resp.text[:300]}")
        return {}
    return resp.json()


def get_push_url(workspace_id: str, dataset_id: str) -> str:
    return (
        f"https://api.powerbi.com/beta/{workspace_id}/datasets/{dataset_id}"
        f"/rows?experience=power-bi"
    )


def test_push(push_url: str, ville: str) -> bool:
    """Pousse une ligne de test pour valider le dataset."""
    test_row = [{
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "ville": ville,
        "tc_ponctualite": 85.0,
        "tc_retard_moyen": 2.1,
        "tc_retard_fort": 5.0,
        "tc_couverture": 92.0,
        "velo_dispo_moy": 74.0,
        "velo_stations_vides": 8.0,
        "velo_stations_hs": 2.0,
        "velo_evolution": 3.0,
        "air_atmo_moyen": 4.2,
        "air_jours_alerte": 0,
        "air_pm25": 11.5,
        "trafic_congestion": 28.0,
        "trafic_troncons_fluides": 9,
        "trafic_fluidite": 72.0,
        "nb_alertes": 1,
        "score_global": 78.5,
    }]
    resp = requests.post(push_url, json={"rows": test_row}, timeout=15)
    if resp.status_code == 200:
        log.info(f"  Test push [{ville}] : OK ✓")
        return True
    else:
        log.warning(f"  Test push [{ville}] : {resp.status_code} — {resp.text[:200]}")
        return False


# ---------------------------------------------------------------------------
# Mode Push URL directe (mode dev sans Azure AD)
# ---------------------------------------------------------------------------

def setup_push_url_mode() -> None:
    """
    Mode dev : les Push URLs sont déjà dans .env.
    Vérifie que les URLs fonctionnent et affiche les colonnes pour création manuelle.
    """
    log.info("Mode : Push URL directe (dev)")
    log.info("Les Push URLs sont gérées manuellement depuis Power BI Service.")
    log.info("")
    log.info("Pour créer un dataset streamé manuellement :")
    log.info("  1. Power BI Service → Espace de travail → + Nouveau → Dataset streamé")
    log.info("  2. API → Suivant")
    log.info(f"  3. Ajouter les {len(PIVOTED_SCHEMA['tables'][0]['columns'])} colonnes du schéma pivoté :")
    for col in PIVOTED_SCHEMA["tables"][0]["columns"]:
        log.info(f"     {col['name']:30s} → {col['dataType']}")
    log.info("  4. Activer 'Analyse des données d'historique' (= mode hybride pushStreaming)")
    log.info("  5. Créer → Copier la Push URL → Coller dans config/.env")
    log.info("")

    urls = {
        "Lille":       settings.powerbi_push_url_lille,
        "Montpellier": settings.powerbi_push_url_montpellier,
    }
    all_ok = True
    for ville, push_url in urls.items():
        if not push_url:
            log.warning(f"  [{ville}] POWERBI_PUSH_URL_{ville.upper()} non configurée dans .env")
            all_ok = False
        else:
            log.info(f"  [{ville}] Test de la Push URL...")
            ok = test_push(push_url, ville)
            if not ok:
                all_ok = False

    if all_ok:
        log.info("Toutes les Push URLs sont opérationnelles ✓")
    else:
        log.warning("Certaines Push URLs manquent ou sont invalides — voir les logs ci-dessus")


# ---------------------------------------------------------------------------
# Mode OAuth2 Azure AD (mode prod)
# ---------------------------------------------------------------------------

def setup_oauth2_mode() -> None:
    """Mode prod : crée/recrée les datasets via l'API REST Power BI."""
    log.info("Mode : OAuth2 Azure AD (prod)")
    headers = get_headers_oauth2()
    workspace_id = get_workspace_id()
    log.info(f"Workspace ID : {workspace_id}")

    datasets_existants = list_datasets(headers, workspace_id)
    log.info(f"{len(datasets_existants)} datasets existants dans le workspace")

    results = {}
    for ville in ["Lille", "Montpellier"]:
        log.info(f"\n{'='*50}")
        log.info(f"Setup dataset : {ville}")

        # Supprime l'ancien dataset si existant
        nom_attendu = f"MobiliteDurable_{ville}"
        for ds in datasets_existants:
            if ds["name"] == nom_attendu:
                log.info(f"  Suppression ancien dataset : {ds['id']}")
                delete_dataset(headers, workspace_id, ds["id"], ds["name"])

        # Crée le nouveau dataset pushStreaming
        log.info(f"  Création dataset pushStreaming : {nom_attendu}")
        dataset = create_dataset(headers, workspace_id, ville)
        if not dataset:
            log.error(f"  Échec création dataset {ville}")
            continue

        dataset_id = dataset["id"]
        log.info(f"  Dataset créé : {dataset_id}")

        # Test push
        push_url = get_push_url(workspace_id, dataset_id)
        test_push(push_url, ville)

        results[ville] = {
            "dataset_id": dataset_id,
            "push_url":   push_url,
        }

    # Affiche le résumé à ajouter dans .env
    if results:
        log.info("\n" + "="*60)
        log.info("RÉSUMÉ — Ajoute ces lignes dans config/.env :")
        log.info("="*60)
        for ville, info in results.items():
            log.info(f"POWERBI_DATASET_ID_{ville.upper()}={info['dataset_id']}")
        log.info("")
        log.info("Note : En mode OAuth2, le pipeline utilise l'API REST")
        log.info("directement — pas besoin de Push URL dans .env.")


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    log.info("="*60)
    log.info("Setup Power BI — Mobilité Durable (pushStreaming hybride)")
    log.info(f"Mode auth détecté : {settings.powerbi_auth_mode}")
    log.info("="*60)

    if settings.powerbi_auth_mode == "oauth2":
        setup_oauth2_mode()
    else:
        setup_push_url_mode()
