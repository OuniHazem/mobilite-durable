"""
ingestion/base_client.py
========================
Client HTTP abstrait — Projet Mobilité Durable
Gère : session poolée, retry tenacity backoff exponentiel, logging.
Tous les clients CKAN héritent de cette classe.
"""

from __future__ import annotations

from typing import Any

import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from config.settings import settings
from utils.logger import get_logger

log = get_logger(__name__)


class BaseClient:
    """
    Client HTTP abstrait avec retry automatique.
    Hériter et surcharger base_url + les méthodes métier.
    """

    base_url: str = ""

    def __init__(self) -> None:
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "MobiliteDurable-Pipeline/1.0",
            "Accept": "application/json",
        })

    @retry(
        stop=stop_after_attempt(settings.http_max_retries),
        wait=wait_exponential(
            multiplier=settings.http_retry_wait_s,
            min=settings.http_retry_wait_s,
            max=30,
        ),
        retry=retry_if_exception_type((requests.ConnectionError, requests.Timeout)),
        reraise=True,
    )
    def _get(self, url: str, params: dict[str, Any] | None = None) -> Any:
        """
        GET HTTP avec retry automatique sur ConnectionError et Timeout.
        Retourne le JSON parsé.
        """
        log.debug(f"GET {url} params={params}")
        resp = self._session.get(
            url,
            params=params,
            timeout=settings.http_timeout_s,
        )
        resp.raise_for_status()
        return resp.json()

    def _get_ckan(self, endpoint: str, dataset_id: str,
                  limit: int = 100) -> list[dict[str, Any]]:
        """
        Appel CKAN standard : GET /action/<endpoint>?resource_id=<id>&limit=<n>
        Retourne la liste des records.
        """
        url = f"{self.base_url}/{endpoint}"
        params = {"resource_id": dataset_id, "limit": limit}
        try:
            data = self._get(url, params=params)
        except Exception as exc:
            log.error(f"CKAN request failed {url}: {exc}")
            return []

        if not data.get("success"):
            log.warning(f"CKAN réponse non-success : {data.get('error')}")
            return []

        return data.get("result", {}).get("records", [])
