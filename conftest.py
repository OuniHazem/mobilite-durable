"""
conftest.py
===========
Configuration pytest globale — Projet Mobilité Durable

Fixtures partagées entre tous les modules de tests.
"""
import os
import sys

import pytest

# ---------------------------------------------------------------------------
# S'assurer que le répertoire racine est dans le PYTHONPATH
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.dirname(__file__))


# ---------------------------------------------------------------------------
# Fixture : forcer l'environnement "test" pour éviter les effets de bord
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def set_test_env(monkeypatch):
    """Force ENV=test pour tous les tests — désactive les appels réels."""
    monkeypatch.setenv("ENV", "test")
    monkeypatch.setenv("DATABASE_URL", "postgresql://test:test@localhost:5432/test_db")
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
