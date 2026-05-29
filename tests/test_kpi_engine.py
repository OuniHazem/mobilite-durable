"""
tests/test_kpi_engine.py
========================
Tests unitaires — KPI Engine
"""

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from processing.kpi_engine import (
    AggregateurTemporel,
    KPIEngine,
    KPIQualiteAir,
    KPITrafic,
    KPITransportsCommun,
    KPIVelos,
    NiveauAlerte,
    WINDOW_1H,
    TC_SEUIL_RETARD_MIN_S,
    AIR_SEUIL_PM25_OMS,
)


# ---------------------------------------------------------------------------
# Fixtures communes
# ---------------------------------------------------------------------------

def _ts(offset_min: int = 0) -> datetime:
    return datetime.now(timezone.utc) - timedelta(minutes=offset_min)


def make_tc_df(n: int = 20, ville: str = "Lille",
               pct_retard: float = 0.20) -> pd.DataFrame:
    rows = []
    for i in range(n):
        en_retard = i < int(n * pct_retard)
        rows.append({
            "timestamp": _ts(i),
            "ville": ville,
            "ligne_id": f"L{i % 5 + 1}",
            "retard_s": 400 if en_retard else 60,
            "en_service": True,
        })
    return pd.DataFrame(rows)


def make_velo_df(n: int = 30, ville: str = "Lille",
                  pct_vide: float = 0.10) -> pd.DataFrame:
    rows = []
    for i in range(n):
        vide = i < int(n * pct_vide)
        rows.append({
            "timestamp": _ts(i % 10),
            "ville": ville,
            "station_id": f"S{i}",
            "velos_disponibles": 0 if vide else 11,
            "capacite": 15,
            "en_service": True,
        })
    return pd.DataFrame(rows)


def make_air_df(n: int = 10, ville: str = "Lille",
                 indice_atmo: float = 4.0,
                 pm25: float = 12.0) -> pd.DataFrame:
    return pd.DataFrame([{
        "timestamp": _ts(i * 60),
        "ville": ville,
        "indice_atmo": indice_atmo + (i % 3) * 0.5,
        "pm25": pm25 + (i % 4),
    } for i in range(n)])


def make_trafic_df(n: int = 20, ville: str = "Lille",
                    score_moy: float = 35.0) -> pd.DataFrame:
    return pd.DataFrame([{
        "timestamp": _ts(i),
        "ville": ville,
        "troncon_id": f"T{i}",
        "score_congestion": min(100, score_moy + (i % 20) - 10),
        "longueur_km": 1.0 + (i % 3) * 0.5,
    } for i in range(n)])


# ---------------------------------------------------------------------------
# Tests KPITransportsCommun
# ---------------------------------------------------------------------------

class TestKPITransportsCommun:

    def test_ponctualite_normale(self):
        df = make_tc_df(n=20, pct_retard=0.10)   # 10% en retard fort
        engine = KPITransportsCommun()
        results = engine.compute_all(df, "Lille")
        ponctu = next(r for r in results if "ponctualite_lille" in r.kpi_id
                      and "ligne" not in r.kpi_id)
        assert ponctu.valeur > 80
        assert ponctu.unite == "%"
        assert ponctu.alerte in (NiveauAlerte.OK, NiveauAlerte.ATTENTION)

    def test_ponctualite_alerte(self):
        df = make_tc_df(n=20, pct_retard=0.80)   # 80% en retard → alerte
        engine = KPITransportsCommun()
        results = engine.compute_all(df, "Lille")
        ponctu = next(r for r in results if "ponctualite_lille" in r.kpi_id
                      and "ligne" not in r.kpi_id)
        assert ponctu.alerte == NiveauAlerte.ALERTE

    def test_retard_moyen_calcul(self):
        df = make_tc_df(n=10, pct_retard=1.0)    # tous en retard de 400s ≈ 6.67 min
        engine = KPITransportsCommun()
        results = engine.compute_all(df, "Lille")
        retard = next(r for r in results if "retard_moyen" in r.kpi_id)
        assert abs(retard.valeur - 400 / 60) < 0.1
        assert retard.alerte == NiveauAlerte.ALERTE

    def test_retard_fort_zero(self):
        df = make_tc_df(n=20, pct_retard=0.0)    # aucun retard
        engine = KPITransportsCommun()
        results = engine.compute_all(df, "Lille")
        fort = next(r for r in results if "retard_fort" in r.kpi_id)
        assert fort.valeur == 0.0
        assert fort.alerte == NiveauAlerte.OK

    def test_ville_filtre(self):
        df_lille = make_tc_df(ville="Lille")
        df_mtp = make_tc_df(ville="Montpellier")
        df = pd.concat([df_lille, df_mtp], ignore_index=True)
        engine = KPITransportsCommun()
        results_lille = engine.compute_all(df, "Lille")
        assert all(r.ville == "Lille" for r in results_lille)

    def test_ponctualite_par_ligne(self):
        df = make_tc_df(n=25, pct_retard=0.2)
        engine = KPITransportsCommun()
        results = engine.compute_all(df, "Lille")
        lignes = [r for r in results if "ligne_" in r.kpi_id]
        assert len(lignes) > 0
        assert all("ligne_id" in r.metadata for r in lignes)


# ---------------------------------------------------------------------------
# Tests KPIVelos
# ---------------------------------------------------------------------------

class TestKPIVelos:

    def test_disponibilite_normale(self):
        df = make_velo_df(n=30, pct_vide=0.05)
        engine = KPIVelos()
        results = engine.compute_all(df, "Lille")
        dispo = next(r for r in results if "dispo_moy" in r.kpi_id)
        assert dispo.valeur > 70
        assert dispo.unite == "%"

    def test_stations_vides_alerte(self):
        df = make_velo_df(n=30, pct_vide=0.40)
        engine = KPIVelos()
        results = engine.compute_all(df, "Lille")
        vides = next(r for r in results if "stations_vides" in r.kpi_id)
        assert vides.alerte == NiveauAlerte.ALERTE

    def test_stations_hors_service(self):
        df = make_velo_df(n=30)
        # Marquer 5 stations comme HS
        df.loc[df["station_id"].isin(["S0", "S1", "S2", "S3", "S4"]), "en_service"] = False
        engine = KPIVelos()
        results = engine.compute_all(df, "Lille")
        hs = next(r for r in results if "stations_hs" in r.kpi_id)
        # 5/30 ≈ 16.7% → ATTENTION
        assert hs.valeur > 0
        assert hs.alerte in (NiveauAlerte.ATTENTION, NiveauAlerte.OK)

    def test_evolution_horaire_stable(self):
        df = make_velo_df(n=20, pct_vide=0.05)
        engine = KPIVelos()
        results = engine.compute_all(df, "Lille")
        evo = next(r for r in results if "evolution" in r.kpi_id)
        assert evo.unite == "%"


# ---------------------------------------------------------------------------
# Tests KPIQualiteAir
# ---------------------------------------------------------------------------

class TestKPIQualiteAir:

    def test_atmo_bonne_qualite(self):
        df = make_air_df(indice_atmo=3.0)
        engine = KPIQualiteAir()
        results = engine.compute_all(df, "Lille")
        atmo = next(r for r in results if "atmo_moyen" in r.kpi_id)
        assert atmo.alerte == NiveauAlerte.OK

    def test_atmo_alerte(self):
        df = make_air_df(indice_atmo=8.0)
        engine = KPIQualiteAir()
        results = engine.compute_all(df, "Lille")
        atmo = next(r for r in results if "atmo_moyen" in r.kpi_id)
        assert atmo.alerte == NiveauAlerte.ALERTE

    def test_pm25_depassements_oms(self):
        # PM2.5 > 15 sur plusieurs jours
        df = make_air_df(n=30, pm25=20.0, indice_atmo=6.0)
        engine = KPIQualiteAir()
        results = engine.compute_all(df, "Lille")
        pm25 = next(r for r in results if "pm25" in r.kpi_id)
        assert pm25.alerte in (NiveauAlerte.ATTENTION, NiveauAlerte.ALERTE)

    def test_pm25_absente(self):
        df = make_air_df().drop(columns=["pm25"])
        engine = KPIQualiteAir()
        results = engine.compute_all(df, "Lille")
        pm25 = next(r for r in results if "pm25" in r.kpi_id)
        assert pm25.metadata.get("info") == "colonne pm25 absente"


# ---------------------------------------------------------------------------
# Tests KPITrafic
# ---------------------------------------------------------------------------

class TestKPITrafic:

    def test_congestion_faible(self):
        df = make_trafic_df(score_moy=25.0)
        engine = KPITrafic()
        results = engine.compute_all(df, "Lille")
        cong = next(r for r in results if "congestion_moy" in r.kpi_id)
        assert cong.valeur < 40
        assert cong.alerte == NiveauAlerte.OK

    def test_congestion_alerte(self):
        df = make_trafic_df(score_moy=85.0)
        engine = KPITrafic()
        results = engine.compute_all(df, "Lille")
        cong = next(r for r in results if "congestion_moy" in r.kpi_id)
        assert cong.alerte == NiveauAlerte.ALERTE

    def test_troncons_distribution(self):
        df = make_trafic_df(n=20, score_moy=30.0)
        engine = KPITrafic()
        results = engine.compute_all(df, "Lille")
        troncons = next(r for r in results if "troncons" in r.kpi_id)
        assert "pct_bloques" in troncons.metadata
        assert troncons.metadata["pct_bloques"] >= 0

    def test_fluidite_inverse_congestion(self):
        df = make_trafic_df(score_moy=40.0)
        engine = KPITrafic()
        results = engine.compute_all(df, "Lille")
        cong = next(r for r in results if "congestion_moy" in r.kpi_id)
        fluid = next(r for r in results if "fluidite" in r.kpi_id)
        assert abs(fluid.valeur + cong.valeur - 100) < 2.0   # fluidité ≈ 100 - congestion


# ---------------------------------------------------------------------------
# Tests KPIEngine (orchestrateur)
# ---------------------------------------------------------------------------

class TestKPIEngine:

    def _make_bundle(self) -> dict:
        return {
            "tc": pd.concat([make_tc_df(ville="Lille"), make_tc_df(ville="Montpellier")]),
            "velos": pd.concat([make_velo_df(ville="Lille"), make_velo_df(ville="Montpellier")]),
            "air": pd.concat([make_air_df(ville="Lille"), make_air_df(ville="Montpellier")]),
            "trafic": pd.concat([make_trafic_df(ville="Lille"), make_trafic_df(ville="Montpellier")]),
        }

    def test_compute_non_vide(self):
        engine = KPIEngine()
        results = engine.compute(self._make_bundle())
        assert len(results) > 0

    def test_deux_villes(self):
        engine = KPIEngine()
        results = engine.compute(self._make_bundle())
        villes = {r.ville for r in results}
        assert "Lille" in villes
        assert "Montpellier" in villes

    def test_powerbi_rows_serializables(self):
        engine = KPIEngine()
        results = engine.compute(self._make_bundle())
        rows = engine.to_powerbi_rows(results)
        assert all(isinstance(r, dict) for r in rows)
        assert all("kpi_id" in r and "valeur" in r for r in rows)

    def test_alertes_filtre(self):
        engine = KPIEngine()
        bundle = {
            "tc": make_tc_df(n=20, pct_retard=0.90, ville="Lille"),
        }
        results = engine.compute(bundle)
        alertes = engine.get_alertes(results, NiveauAlerte.ATTENTION)
        assert len(alertes) > 0
        assert all(r.alerte != NiveauAlerte.OK for r in alertes)

    def test_bundle_vide(self):
        engine = KPIEngine()
        results = engine.compute({})
        assert results == []

    def test_bundle_partiel(self):
        engine = KPIEngine()
        results = engine.compute({"tc": make_tc_df(ville="Lille")})
        assert any(r.domaine == "TC" for r in results)
        assert not any(r.domaine == "VELO" for r in results)


# ---------------------------------------------------------------------------
# Tests AggregateurTemporel
# ---------------------------------------------------------------------------

class TestAggregateurTemporel:

    def test_agregation_retourne_dataframe(self):
        df = make_tc_df(n=50)
        df = df.rename(columns={"retard_s": "valeur_test"})
        agg = AggregateurTemporel()
        result = agg.aggregate(df, "Lille", "TC", "valeur_test")
        assert isinstance(result, pd.DataFrame)
        assert "fenetre" in result.columns
        assert "moyenne" in result.columns

    def test_colonnes_presentes(self):
        df = make_velo_df(n=40)
        df["valeur_test"] = df["velos_disponibles"]
        agg = AggregateurTemporel()
        result = agg.aggregate(df, "Lille", "VELO", "valeur_test")
        expected_cols = {"fenetre", "moyenne", "min", "max", "ecart_type", "tendance"}
        assert expected_cols.issubset(set(result.columns))
