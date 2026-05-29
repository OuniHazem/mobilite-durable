"""
processing/policy_kpi_engine.py
================================
Moteur d'évaluation des politiques publiques de mobilité durable.

Transforme les KPIs opérationnels en indicateurs de politique publique :
  - Score par dimension (Mobilité Douce, Qualité de l'Air, Efficacité TC, Trafic)
  - Tendance (amélioration / stable / dégradation)
  - Comparaison Lille vs Montpellier
  - Analyse avant/après politique
  - Score composite global

Usage :
    engine = PolicyKPIEngine(session)
    scores = engine.compute_all(ville="Lille")
    # → liste de PolicyScore prêts pour la base
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from utils.logger import get_logger

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Modèles de sortie
# ---------------------------------------------------------------------------

class Dimension(str, Enum):
    """4 dimensions d'évaluation des politiques de mobilité."""
    DOUCE = "MOBILITE_DOUCE"       # Vélos + TC vs voiture
    AIR = "QUALITE_AIR"            # Santé publique
    TRANSPORT = "EFFICACITE_TC"    # Service public
    TRAFIC = "TRAFIC_ROUTIER"      # Congestion
    GLOBAL = "SCORE_GLOBAL"        # Composite


class Tendance(str, Enum):
    AMELIORATION = "UP"
    STABLE = "STABLE"
    DEGRADATION = "DOWN"
    INSUFFISANT = "NA"


@dataclass
class PolicyScore:
    """Score de politique publique — 1 par dimension par ville par cycle."""
    ville: str
    dimension: Dimension
    score: float                          # 0–100
    tendance: Tendance
    nb_kpis: int                          # KPIs utilisés dans le calcul
    details: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return {
            "ville": self.ville,
            "dimension": self.dimension.value,
            "score": round(self.score, 2),
            "tendance": self.tendance.value,
            "nb_kpis": self.nb_kpis,
            "details": self.details,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class VilleComparison:
    """Comparaison Lille vs Montpellier sur une dimension."""
    dimension: Dimension
    score_lille: float
    score_montpellier: float
    ecart: float                          # positif = Lille meilleur
    leader: str                           # "Lille" | "Montpellier" | "Égal"


@dataclass
class BeforeAfter:
    """Analyse avant/après politique."""
    dimension: Dimension
    ville: str
    score_avant: float | None
    score_apres: float | None
    delta: float | None                   # positif = amélioration
    politique: str                        # nom de la politique


# ---------------------------------------------------------------------------
# Dates de politiques de référence (configurable)
# ---------------------------------------------------------------------------

POLITIQUES_REFERENCE: dict[str, dict[str, Any]] = {
    "Lille": [
        {
            "nom": "Plan Climat Lille Métropole",
            "date": "2024-01-01",
            "description": "Plan climat territorial — objectifs mobilité douce",
        },
        {
            "nom": "Extension réseau V'Lille",
            "date": "2024-06-01",
            "description": "Nouvelles stations V'Lille en périphérie",
        },
    ],
    "Montpellier": [
        {
            "nom": "Plan Mobilités Montpellier 3M",
            "date": "2024-03-01",
            "description": "Réorganisation réseau TAM + vélos",
        },
        {
            "nom": "Lignes gratuites TAM",
            "date": "2024-09-01",
            "description": "Gratuité TC certaines lignes",
        },
    ],
}


# ---------------------------------------------------------------------------
# Moteur d'évaluation
# ---------------------------------------------------------------------------

class PolicyKPIEngine:
    """
    Évalue l'efficacité des politiques publiques de mobilité
    à partir des KPIs opérationnels stockés en base.

    Usage :
        engine = PolicyKPIEngine(session)
        scores = engine.compute_all("Lille")
        comparison = engine.compare_cities()
        before_after = engine.before_after_analysis("Lille")
    """

    # Pondérations des dimensions pour le score global
    POIDS = {
        Dimension.DOUCE: 0.30,
        Dimension.AIR: 0.25,
        Dimension.TRANSPORT: 0.25,
        Dimension.TRAFIC: 0.20,
    }

    def __init__(self, session: Session) -> None:
        self.session = session

    # ------------------------------------------------------------------
    # Point d'entrée principal
    # ------------------------------------------------------------------

    def compute_all(self, ville: str) -> list[PolicyScore]:
        """Calcule les scores de politique pour une ville."""
        scores: list[PolicyScore] = []

        # Récupère les derniers KPIs opérationnels
        kpis = self._get_latest_kpis(ville)

        if not kpis:
            log.warning(f"Aucun KPI opérationnel pour {ville} — scores non calculés")
            return []

        # Score par dimension
        scores.append(self._score_mobilite_douce(ville, kpis))
        scores.append(self._score_qualite_air(ville, kpis))
        scores.append(self._score_efficacite_tc(ville, kpis))
        scores.append(self._score_trafic(ville, kpis))

        # Score global composite
        scores.append(self._score_global(ville, scores))

        return scores

    # ------------------------------------------------------------------
    # Dimension 1 — Mobilité Douce
    # ------------------------------------------------------------------

    def _score_mobilite_douce(self, ville: str, kpis: dict[str, float]) -> PolicyScore:
        """
        Mesure la part de la mobilité douce (vélos + TC) vs la voiture.

        Logique :
          - vélo_dispo_moy élevé → bonnes conditions pour les vélos
          - tc_ponctualite élevé → TC attractif
          - trafic_congestion élevé → la voiture est pénalisante
          → Plus les conditions douce sont bonnes et la voiture est pénalisée,
            plus le score est élevé (incitation au report modal)
        """
        dispo_velo = kpis.get("velo_dispo_moy", 50)
        ponctu_tc = kpis.get("tc_ponctualite", 50)
        couverture_tc = kpis.get("tc_couverture", 50)
        congestion = kpis.get("trafic_congestion", 30)

        # Score attractivité mobilité douce (0–100)
        attractivite_douce = (
            dispo_velo * 0.35 +
            ponctu_tc * 0.35 +
            couverture_tc * 0.30
        )

        # Facteur de dissuasion voiture : plus de congestion → plus d'incitation
        # à quitter la voiture (0–100 normalisé)
        dissuasion_voiture = min(congestion * 1.5, 100)

        # Score composite
        score = attractivite_douce * 0.65 + dissuasion_voiture * 0.35

        tendance = self._calc_tendance(ville, Dimension.DOUCE, score)

        return PolicyScore(
            ville=ville,
            dimension=Dimension.DOUCE,
            score=score,
            tendance=tendance,
            nb_kpis=4,
            details={
                "attractivite_douce": round(attractivite_douce, 1),
                "dissuasion_voiture": round(dissuasion_voiture, 1),
                "dispo_velo": round(dispo_velo, 1),
                "ponctualite_tc": round(ponctu_tc, 1),
                "couverture_tc": round(couverture_tc, 1),
                "congestion": round(congestion, 1),
            },
        )

    # ------------------------------------------------------------------
    # Dimension 2 — Qualité de l'Air
    # ------------------------------------------------------------------

    def _score_qualite_air(self, ville: str, kpis: dict[str, float]) -> PolicyScore:
        """
        Évalue l'impact des politiques sur la qualité de l'air.

        ATMO 1–10 → inversé et normalisé sur 100.
        Plus l'air est pur, plus le score est élevé.
        """
        atmo_moyen = kpis.get("air_atmo_moyen", 5)
        jours_alerte = kpis.get("air_jours_alerte", 0)
        pm25 = kpis.get("air_pm25", 10)

        # Score ATMO inversé : ATMO 1 → 100, ATMO 10 → 0
        score_atmo = max(0, (10 - atmo_moyen) * 10)

        # Pénalité jours alerte (0–30 points de malus)
        malus_alerte = min(jours_alerte * 10, 30)

        # Score PM2.5 : < 15 OMS → 100, > 40 → 0
        score_pm25 = max(0, min(100, (40 - pm25) / 25 * 100))

        score = max(0, (score_atmo + score_pm25) / 2 - malus_alerte)

        tendance = self._calc_tendance(ville, Dimension.AIR, score)

        return PolicyScore(
            ville=ville,
            dimension=Dimension.AIR,
            score=score,
            tendance=tendance,
            nb_kpis=3,
            details={
                "score_atmo": round(score_atmo, 1),
                "score_pm25": round(score_pm25, 1),
                "malus_jours_alerte": round(malus_alerte, 1),
                "atmo_moyen": round(atmo_moyen, 2),
                "jours_alerte": jours_alerte,
                "pm25": round(pm25, 2),
            },
        )

    # ------------------------------------------------------------------
    # Dimension 3 — Efficacité Transports en Commun
    # ------------------------------------------------------------------

    def _score_efficacite_tc(self, ville: str, kpis: dict[str, float]) -> PolicyScore:
        """
        Mesure la qualité du service public de transport.

        Indicateurs : ponctualité, couverture réseau, retard fort.
        """
        ponctualite = kpis.get("tc_ponctualite", 50)
        couverture = kpis.get("tc_couverture", 50)
        retard_fort = kpis.get("tc_retard_fort", 10)
        retard_moyen = kpis.get("tc_retard_moyen", 3)

        # Score ponctualité directement en %
        score_ponctu = ponctualite

        # Score couverture (0–100)
        score_couverture = couverture

        # Malus retards : retard_fort en % → pénalité
        malus_retard_fort = min(retard_fort, 30)

        # Malus retard moyen : > 3 min = problème
        malus_retard_moyen = min(retard_moyen * 5, 20)

        score = max(0,
            score_ponctu * 0.40 +
            score_couverture * 0.30 +
            (100 - malus_retard_fort) * 0.15 +
            (100 - malus_retard_moyen) * 0.15
        )

        tendance = self._calc_tendance(ville, Dimension.TRANSPORT, score)

        return PolicyScore(
            ville=ville,
            dimension=Dimension.TRANSPORT,
            score=score,
            tendance=tendance,
            nb_kpis=4,
            details={
                "ponctualite": round(ponctualite, 1),
                "couverture": round(couverture, 1),
                "retard_fort_pct": round(retard_fort, 1),
                "retard_moyen_min": round(retard_moyen, 2),
            },
        )

    # ------------------------------------------------------------------
    # Dimension 4 — Trafic Routier
    # ------------------------------------------------------------------

    def _score_trafic(self, ville: str, kpis: dict[str, float]) -> PolicyScore:
        """
        Mesure la réduction de la congestion automobile.

        Plus la fluidité est haute et la congestion basse, meilleur le score.
        """
        fluidite = kpis.get("trafic_fluidite", 60)
        congestion = kpis.get("trafic_congestion", 40)
        troncons_fluides = kpis.get("trafic_troncons_fluides", 50)

        # Score fluidité directement
        score_fluidite = fluidite

        # Score anti-congestion (inverse)
        score_anti_congestion = 100 - congestion

        # Score tronçons fluides
        score_troncons = min(troncons_fluides, 100)

        score = (
            score_fluidite * 0.40 +
            score_anti_congestion * 0.35 +
            score_troncons * 0.25
        )

        tendance = self._calc_tendance(ville, Dimension.TRAFIC, score)

        return PolicyScore(
            ville=ville,
            dimension=Dimension.TRAFIC,
            score=score,
            tendance=tendance,
            nb_kpis=3,
            details={
                "fluidite": round(fluidite, 1),
                "congestion": round(congestion, 1),
                "troncons_fluides_pct": round(troncons_fluides, 1),
            },
        )

    # ------------------------------------------------------------------
    # Score Global Composite
    # ------------------------------------------------------------------

    def _score_global(self, ville: str, dimension_scores: list[PolicyScore]) -> PolicyScore:
        """Score composite pondéré des 4 dimensions."""
        score_map: dict[Dimension, float] = {}
        for s in dimension_scores:
            if s.dimension != Dimension.GLOBAL:
                score_map[s.dimension] = s.score

        score = sum(
            score_map.get(dim, 50) * poids
            for dim, poids in self.POIDS.items()
        )

        # Tendance dominante
        tendances = [s.tendance for s in dimension_scores if s.dimension != Dimension.GLOBAL]
        ameliorations = sum(1 for t in tendances if t == Tendance.AMELIORATION)
        degradations = sum(1 for t in tendances if t == Tendance.DEGRADATION)

        if ameliorations > degradations:
            tendance = Tendance.AMELIORATION
        elif degradations > ameliorations:
            tendance = Tendance.DEGRADATION
        elif ameliorations > 0 and degradations > 0:
            tendance = Tendance.STABLE
        else:
            tendance = Tendance.INSUFFISANT

        details = {
            f"poids_{dim.value}": poids
            for dim, poids in self.POIDS.items()
        }
        details.update({
            f"score_{dim.value}": round(score_map.get(dim, 0), 1)
            for dim in self.POIDS
        })

        return PolicyScore(
            ville=ville,
            dimension=Dimension.GLOBAL,
            score=score,
            tendance=tendance,
            nb_kpis=sum(s.nb_kpis for s in dimension_scores if s.dimension != Dimension.GLOBAL),
            details=details,
        )

    # ------------------------------------------------------------------
    # Comparaison Lille vs Montpellier
    # ------------------------------------------------------------------

    def compare_cities(self) -> list[VilleComparison]:
        """Compare les scores politiques des deux villes."""
        comparisons: list[VilleComparison] = []

        for dim in [Dimension.DOUCE, Dimension.AIR, Dimension.TRANSPORT,
                     Dimension.TRAFIC, Dimension.GLOBAL]:
            score_lille = self._get_latest_dimension_score("Lille", dim)
            score_mtp = self._get_latest_dimension_score("Montpellier", dim)

            ecart = score_lille - score_mtp
            if abs(ecart) < 2:
                leader = "Égal"
            elif ecart > 0:
                leader = "Lille"
            else:
                leader = "Montpellier"

            comparisons.append(VilleComparison(
                dimension=dim,
                score_lille=round(score_lille, 1),
                score_montpellier=round(score_mtp, 1),
                ecart=round(ecart, 1),
                leader=leader,
            ))

        return comparisons

    # ------------------------------------------------------------------
    # Analyse Avant / Après
    # ------------------------------------------------------------------

    def before_after_analysis(self, ville: str) -> list[BeforeAfter]:
        """
        Compare les scores avant et après les politiques de référence.
        Période "avant" = 30j avant la politique, "après" = 30j après.
        """
        results: list[BeforeAfter] = []
        politiques = POLITIQUES_REFERENCE.get(ville, [])

        for pol in politiques:
            date_pol = datetime.fromisoformat(pol["date"] + "T00:00:00+00:00")

            avant_start = date_pol - timedelta(days=30)
            apres_end = date_pol + timedelta(days=30)

            for dim in [Dimension.DOUCE, Dimension.AIR, Dimension.TRANSPORT, Dimension.TRAFIC]:
                score_avant = self._avg_dimension_score(ville, dim, avant_start, date_pol)
                score_apres = self._avg_dimension_score(ville, dim, date_pol, apres_end)

                delta = None
                if score_avant is not None and score_apres is not None:
                    delta = round(score_apres - score_avant, 1)

                results.append(BeforeAfter(
                    dimension=dim,
                    ville=ville,
                    score_avant=round(score_avant, 1) if score_avant else None,
                    score_apres=round(score_apres, 1) if score_apres else None,
                    delta=delta,
                    politique=pol["nom"],
                ))

        return results

    # ------------------------------------------------------------------
    # Helpers — lecture base
    # ------------------------------------------------------------------

    def _get_latest_kpis(self, ville: str) -> dict[str, float]:
        """
        Récupère les dernières valeurs KPI opérationnelles pour une ville.
        Retourne un dict {kpi_id_sans_ville: valeur}.
        """
        try:
            result = self.session.execute(text("""
                SELECT DISTINCT ON (kpi_id)
                    kpi_id, valeur
                FROM kpi_historique
                WHERE ville = :ville
                  AND fenetre IN ('1h', '1j')
                ORDER BY kpi_id, timestamp_calcul DESC
            """), {"ville": ville})

            kpis: dict[str, float] = {}
            for row in result:
                # Nettoie le kpi_id : "tc_ponctualite_lille" → "tc_ponctualite"
                kpi_id: str = row[0]
                clean_id = kpi_id.replace(f"_{ville.lower()}", "")
                # Ignore les KPIs par ligne (trop détaillés)
                if "_ligne_" in kpi_id:
                    continue
                kpis[clean_id] = float(row[1])

            return kpis
        except Exception as exc:
            log.warning(f"Erreur lecture KPIs pour {ville} : {exc}")
            return {}

    def _calc_tendance(self, ville: str, dimension: Dimension, score_actuel: float) -> Tendance:
        """
        Calcule la tendance en comparant avec le score précédent de la même dimension.
        """
        try:
            result = self.session.execute(text("""
                SELECT score
                FROM policy_scores
                WHERE ville = :ville AND dimension = :dimension
                ORDER BY timestamp DESC
                LIMIT 1
            """), {"ville": ville, "dimension": dimension.value})

            row = result.first()
            if row is None:
                return Tendance.INSUFFISANT

            score_precedent = float(row[0])
            delta = score_actuel - score_precedent

            if delta > 3:
                return Tendance.AMELIORATION
            elif delta < -3:
                return Tendance.DEGRADATION
            else:
                return Tendance.STABLE

        except Exception:
            return Tendance.INSUFFISANT

    def _get_latest_dimension_score(self, ville: str, dimension: Dimension) -> float:
        """Récupère le dernier score d'une dimension pour une ville."""
        try:
            result = self.session.execute(text("""
                SELECT score
                FROM policy_scores
                WHERE ville = :ville AND dimension = :dimension
                ORDER BY timestamp DESC
                LIMIT 1
            """), {"ville": ville, "dimension": dimension.value})

            row = result.first()
            return float(row[0]) if row else 50.0
        except Exception:
            return 50.0

    def _avg_dimension_score(self, ville: str, dimension: Dimension,
                              date_from: datetime, date_to: datetime) -> float | None:
        """Moyenne des scores d'une dimension sur une période."""
        try:
            result = self.session.execute(text("""
                SELECT AVG(score)
                FROM policy_scores
                WHERE ville = :ville
                  AND dimension = :dimension
                  AND timestamp BETWEEN :date_from AND :date_to
            """), {
                "ville": ville,
                "dimension": dimension.value,
                "date_from": date_from.isoformat(),
                "date_to": date_to.isoformat(),
            })

            row = result.first()
            return float(row[0]) if row and row[0] is not None else None
        except Exception:
            return None
