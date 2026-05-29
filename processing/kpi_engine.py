"""
processing/kpi_engine.py
========================
Moteur de calcul des KPIs — Projet Mobilité Durable Lille/Montpellier
Consultant Senior — Partie 4

Périmètre :
  - KPIs Transports en Commun (GTFS-RT)
  - KPIs Vélos en libre-service (CKAN)
  - KPIs Qualité de l'air (CKAN)
  - KPIs Trafic / Congestion (CKAN)
  - Agrégations temporelles (fenêtre glissante 15min, 1h, 1j)
  - Seuils d'alerte par KPI
  - Mapping vers les champs Power BI (5 tables)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any

import pandas as pd

# ---------------------------------------------------------------------------
# Constantes métier
# ---------------------------------------------------------------------------

# TC — standard UITP
TC_SEUIL_RETARD_MIN_S = 180          # 3 min → course "en retard"
TC_SEUIL_RETARD_FORT_S = 360         # 6 min → retard fort
TC_SEUIL_PONCTUALITE_ALERTE = 0.85   # < 85 % → alerte

# Vélos
VELO_SEUIL_DISPO_ALERTE = 0.70       # < 70 % disponibilité → alerte
VELO_SEUIL_STATIONS_VIDES = 0.15     # > 15 % stations vides → alerte

# Qualité de l'air — indice ATMO (1–10)
AIR_SEUIL_ALERTE_ATMO = 7            # ≥ 7 → mauvaise qualité
AIR_SEUIL_PM25_OMS = 15.0            # µg/m³ — recommandation OMS 2021

# Trafic
TRAFIC_SEUIL_CONGESTION_ALERTE = 60  # > 60/100 → congestion significative
TRAFIC_SEUIL_BLOQUE = 80             # > 80/100 → tronçon bloqué

# Fenêtres temporelles (minutes)
WINDOW_15MIN = 15
WINDOW_1H = 60
WINDOW_1J = 1440


# ---------------------------------------------------------------------------
# Modèles de sortie KPI
# ---------------------------------------------------------------------------

class NiveauAlerte(str, Enum):
    OK = "OK"
    ATTENTION = "ATTENTION"
    ALERTE = "ALERTE"
    CRITIQUE = "CRITIQUE"


@dataclass
class KPIResult:
    """Résultat d'un KPI calculé — prêt pour Power BI."""
    kpi_id: str                    # identifiant unique ex: "tc_ponctualite_lille"
    kpi_label: str                 # libellé lisible
    valeur: float                  # valeur numérique principale
    unite: str                     # "%", "min", "µg/m³", "score"…
    ville: str                     # "Lille" | "Montpellier" | "Global"
    domaine: str                   # "TC" | "VELO" | "AIR" | "TRAFIC"
    fenetre: str                   # "15min" | "1h" | "1j"
    alerte: NiveauAlerte
    timestamp_calcul: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_powerbi_row(self) -> dict[str, Any]:
        """Sérialise pour la table KPIs_Temps_Reel Power BI."""
        return {
            "kpi_id": self.kpi_id,
            "kpi_label": self.kpi_label,
            "valeur": float(round(self.valeur, 4)),
            "unite": self.unite,
            "ville": self.ville,
            "domaine": self.domaine,
            "fenetre": self.fenetre,
            "alerte": self.alerte.value,
            "timestamp_calcul": self.timestamp_calcul.isoformat(),
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _fenetre_label(minutes: int) -> str:
    if minutes == WINDOW_15MIN:
        return "15min"
    if minutes == WINDOW_1H:
        return "1h"
    if minutes == WINDOW_1J:
        return "1j"
    return f"{minutes}min"


def _filter_window(df: pd.DataFrame, col_ts: str, window_min: int) -> pd.DataFrame:
    """Filtre un DataFrame sur une fenêtre glissante."""
    if df.empty:
        return df
    cutoff = _now_utc() - timedelta(minutes=window_min)
    ts = pd.to_datetime(df[col_ts], utc=True)
    return df[ts >= cutoff].copy()


def _alerte_seuil(valeur: float, seuil_attention: float, seuil_alerte: float,
                  inverse: bool = False) -> NiveauAlerte:
    """
    Calcule le niveau d'alerte par rapport à deux seuils.
    inverse=False (défaut) : valeur haute = bon (ex: ponctualité, disponibilité).
                              seuil_attention > seuil_alerte.
    inverse=True            : valeur basse = bon (ex: congestion, % stations vides).
                              seuil_attention < seuil_alerte.
    """
    if not inverse:
        if valeur >= seuil_attention:
            return NiveauAlerte.OK
        if valeur >= seuil_alerte:
            return NiveauAlerte.ATTENTION
        return NiveauAlerte.ALERTE
    else:
        if valeur <= seuil_attention:
            return NiveauAlerte.OK
        if valeur <= seuil_alerte:
            return NiveauAlerte.ATTENTION
        return NiveauAlerte.ALERTE


# ---------------------------------------------------------------------------
# Module 1 — KPIs Transports en Commun
# ---------------------------------------------------------------------------

class KPITransportsCommun:
    """
    Calcule les KPIs TC à partir des données GTFS-RT normalisées.

    DataFrame attendu (colonnes minimales) :
        - timestamp       : datetime UTC
        - ville           : str ("Lille" | "Montpellier")
        - ligne_id        : str
        - retard_s        : int   (secondes, positif = en retard)
        - en_service      : bool
    """

    DOMAINE = "TC"

    def compute_all(self, df: pd.DataFrame, ville: str,
                    window_min: int = WINDOW_1H) -> list[KPIResult]:
        """Point d'entrée principal — renvoie tous les KPIs TC pour une ville."""
        fenetre = _fenetre_label(window_min)
        df_v = df[df["ville"] == ville].copy()
        df_w = _filter_window(df_v, "timestamp", window_min)

        results: list[KPIResult] = []

        if df_w.empty:
            return results

        results.append(self._ponctualite(df_w, ville, fenetre))
        results.append(self._retard_moyen(df_w, ville, fenetre))
        results.append(self._retard_fort(df_w, ville, fenetre))
        results.append(self._couverture_reseau(df_w, ville, fenetre))
        results += self._ponctualite_par_ligne(df_w, ville, fenetre)

        return results

    # --- formules -----------------------------------------------------------

    def _ponctualite(self, df: pd.DataFrame, ville: str, fenetre: str) -> KPIResult:
        """
        Taux de ponctualité = nb courses avec |retard| < seuil / nb total courses.
        Standard UITP : seuil = 3 min.
        """
        total = len(df)
        ponctuelles = (df["retard_s"].abs() < TC_SEUIL_RETARD_MIN_S).sum()
        taux = ponctuelles / total if total > 0 else 0.0

        return KPIResult(
            kpi_id=f"tc_ponctualite_{ville.lower()}",
            kpi_label=f"Taux de ponctualité TC — {ville}",
            valeur=taux * 100,
            unite="%",
            ville=ville,
            domaine=self.DOMAINE,
            fenetre=fenetre,
            alerte=_alerte_seuil(taux, TC_SEUIL_PONCTUALITE_ALERTE, 0.75),
            metadata={"total_courses": total, "courses_ponctuelles": int(ponctuelles)},
        )

    def _retard_moyen(self, df: pd.DataFrame, ville: str, fenetre: str) -> KPIResult:
        """
        Retard moyen en minutes (uniquement les courses en retard positif).
        """
        en_retard = df[df["retard_s"] > 0]["retard_s"]
        retard_moy_min = en_retard.mean() / 60 if len(en_retard) > 0 else 0.0

        alerte = NiveauAlerte.OK
        if retard_moy_min > 6:
            alerte = NiveauAlerte.ALERTE
        elif retard_moy_min > 3:
            alerte = NiveauAlerte.ATTENTION

        return KPIResult(
            kpi_id=f"tc_retard_moyen_{ville.lower()}",
            kpi_label=f"Retard moyen TC — {ville}",
            valeur=round(retard_moy_min, 2),
            unite="min",
            ville=ville,
            domaine=self.DOMAINE,
            fenetre=fenetre,
            alerte=alerte,
            metadata={"nb_courses_retard": int(len(en_retard))},
        )

    def _retard_fort(self, df: pd.DataFrame, ville: str, fenetre: str) -> KPIResult:
        """
        Nombre de courses avec retard fort (> 6 min).
        """
        nb_fort = (df["retard_s"] > TC_SEUIL_RETARD_FORT_S).sum()
        pct_fort = nb_fort / len(df) * 100 if len(df) > 0 else 0.0

        alerte = NiveauAlerte.OK
        if pct_fort > 20:
            alerte = NiveauAlerte.ALERTE
        elif pct_fort > 10:
            alerte = NiveauAlerte.ATTENTION

        return KPIResult(
            kpi_id=f"tc_retard_fort_{ville.lower()}",
            kpi_label=f"Courses retard fort (> 6 min) — {ville}",
            valeur=pct_fort,
            unite="%",
            ville=ville,
            domaine=self.DOMAINE,
            fenetre=fenetre,
            alerte=alerte,
            metadata={"nb_retard_fort": int(nb_fort), "total": int(len(df))},
        )

    def _couverture_reseau(self, df: pd.DataFrame, ville: str, fenetre: str) -> KPIResult:
        """
        Taux de couverture = lignes actives / total lignes référencées.
        On considère une ligne active si ≥ 1 course observée dans la fenêtre.
        """
        lignes_actives = df["ligne_id"].nunique()
        # Hypothèse : total lignes théoriques portée par la colonne metadata (ou valeur de ref)
        # En l'absence de référentiel, on utilise une fenêtre glissante plus longue (1j) comme base
        # → le caller peut passer un total_lignes_ref dans les metadata
        total_ref = df.attrs.get("total_lignes_ref", lignes_actives)
        taux = lignes_actives / total_ref if total_ref > 0 else 1.0
        taux = min(taux, 1.0)

        return KPIResult(
            kpi_id=f"tc_couverture_{ville.lower()}",
            kpi_label=f"Couverture réseau TC — {ville}",
            valeur=taux * 100,
            unite="%",
            ville=ville,
            domaine=self.DOMAINE,
            fenetre=fenetre,
            alerte=_alerte_seuil(taux, 0.90, 0.75),
            metadata={"lignes_actives": int(lignes_actives), "total_ref": int(total_ref)},
        )

    def _ponctualite_par_ligne(self, df: pd.DataFrame,
                                ville: str, fenetre: str) -> list[KPIResult]:
        """KPI ponctualité décliné par ligne — pour drill-down Power BI."""
        results = []
        for ligne_id, grp in df.groupby("ligne_id"):
            total = len(grp)
            if total < 3:           # pas assez de données — ignorer
                continue
            ponctuelles = (grp["retard_s"].abs() < TC_SEUIL_RETARD_MIN_S).sum()
            taux = ponctuelles / total

            results.append(KPIResult(
                kpi_id=f"tc_ponctualite_{ville.lower()}_ligne_{ligne_id}",
                kpi_label=f"Ponctualité ligne {ligne_id} — {ville}",
                valeur=taux * 100,
                unite="%",
                ville=ville,
                domaine=self.DOMAINE,
                fenetre=fenetre,
                alerte=_alerte_seuil(taux, TC_SEUIL_PONCTUALITE_ALERTE, 0.75),
                metadata={"ligne_id": str(ligne_id), "total": total},
            ))
        return results


# ---------------------------------------------------------------------------
# Module 2 — KPIs Vélos
# ---------------------------------------------------------------------------

class KPIVelos:
    """
    KPIs vélos en libre-service.

    DataFrame attendu :
        - timestamp          : datetime UTC
        - ville              : str
        - station_id         : str
        - velos_disponibles  : int
        - capacite           : int
        - en_service         : bool
    """

    DOMAINE = "VELO"

    def compute_all(self, df: pd.DataFrame, ville: str,
                    window_min: int = WINDOW_1H) -> list[KPIResult]:
        fenetre = _fenetre_label(window_min)
        df_v = df[df["ville"] == ville].copy()
        df_w = _filter_window(df_v, "timestamp", window_min)

        if df_w.empty:
            return []

        # Snapshot le plus récent par station
        df_snap = (
            df_w.sort_values("timestamp")
                .groupby("station_id")
                .last()
                .reset_index()
        )

        return [
            self._disponibilite_moyenne(df_snap, ville, fenetre),
            self._stations_vides(df_snap, ville, fenetre),
            self._stations_hors_service(df_snap, ville, fenetre),
            self._evolution_horaire(df_w, ville, fenetre),
        ]

    # --- formules -----------------------------------------------------------

    def _disponibilite_moyenne(self, df_snap: pd.DataFrame,
                                ville: str, fenetre: str) -> KPIResult:
        """
        Taux de disponibilité = Σ(vélos_dispo) / Σ(capacité) — stations en service.
        """
        df_actives = df_snap[df_snap["en_service"]]
        total_velos = df_actives["velos_disponibles"].sum()
        total_capa = df_actives["capacite"].sum()
        taux = total_velos / total_capa if total_capa > 0 else 0.0

        return KPIResult(
            kpi_id=f"velo_dispo_moy_{ville.lower()}",
            kpi_label=f"Disponibilité moyenne vélos — {ville}",
            valeur=taux * 100,
            unite="%",
            ville=ville,
            domaine=self.DOMAINE,
            fenetre=fenetre,
            alerte=_alerte_seuil(taux, VELO_SEUIL_DISPO_ALERTE, 0.50),
            metadata={
                "velos_disponibles": int(total_velos),
                "capacite_totale": int(total_capa),
                "nb_stations": len(df_actives),
            },
        )

    def _stations_vides(self, df_snap: pd.DataFrame,
                         ville: str, fenetre: str) -> KPIResult:
        """
        % stations vides = stations avec 0 vélo disponible / total stations en service.
        """
        df_actives = df_snap[df_snap["en_service"]]
        total = len(df_actives)
        vides = (df_actives["velos_disponibles"] == 0).sum()
        pct = vides / total * 100 if total > 0 else 0.0

        pct_vides_ratio = vides / total if total > 0 else 0.0
        alerte = _alerte_seuil(
            pct_vides_ratio,
            VELO_SEUIL_STATIONS_VIDES,   # <= 15% vides → OK
            0.30,                         # <= 30% → ATTENTION, > 30% → ALERTE
            inverse=True,
        )

        return KPIResult(
            kpi_id=f"velo_stations_vides_{ville.lower()}",
            kpi_label=f"Stations vélos vides — {ville}",
            valeur=pct,
            unite="%",
            ville=ville,
            domaine=self.DOMAINE,
            fenetre=fenetre,
            alerte=alerte,
            metadata={"nb_vides": int(vides), "total_actives": total},
        )

    def _stations_hors_service(self, df_snap: pd.DataFrame,
                                 ville: str, fenetre: str) -> KPIResult:
        """
        % stations hors service = stations non en_service / total stations.
        """
        total = len(df_snap)
        hs = (~df_snap["en_service"]).sum()
        pct = hs / total * 100 if total > 0 else 0.0

        alerte = NiveauAlerte.OK
        if pct > 20:
            alerte = NiveauAlerte.ALERTE
        elif pct > 10:
            alerte = NiveauAlerte.ATTENTION

        return KPIResult(
            kpi_id=f"velo_stations_hs_{ville.lower()}",
            kpi_label=f"Stations vélos hors service — {ville}",
            valeur=pct,
            unite="%",
            ville=ville,
            domaine=self.DOMAINE,
            fenetre=fenetre,
            alerte=alerte,
            metadata={"nb_hs": int(hs), "total": total},
        )

    def _evolution_horaire(self, df: pd.DataFrame,
                            ville: str, fenetre: str) -> KPIResult:
        """
        Variation de disponibilité sur la fenêtre :
        (dispo_fin - dispo_debut) / dispo_debut * 100
        Indicateur de tendance — positif = amélioration.
        """
        df_s = df.sort_values("timestamp")
        if len(df_s) < 2:
            return KPIResult(
                kpi_id=f"velo_evolution_{ville.lower()}",
                kpi_label=f"Évolution disponibilité vélos — {ville}",
                valeur=0.0, unite="%", ville=ville,
                domaine=self.DOMAINE, fenetre=fenetre,
                alerte=NiveauAlerte.OK,
            )

        def _dispo_mean(sub: pd.DataFrame) -> float:
            capa = sub["capacite"].sum()
            return sub["velos_disponibles"].sum() / capa if capa > 0 else 0.0

        mid = len(df_s) // 2
        debut = _dispo_mean(df_s.iloc[:mid])
        fin = _dispo_mean(df_s.iloc[mid:])
        evolution = (fin - debut) / debut * 100 if debut > 0 else 0.0

        alerte = NiveauAlerte.OK
        if evolution < -20:
            alerte = NiveauAlerte.ALERTE
        elif evolution < -10:
            alerte = NiveauAlerte.ATTENTION

        return KPIResult(
            kpi_id=f"velo_evolution_{ville.lower()}",
            kpi_label=f"Évolution disponibilité vélos — {ville}",
            valeur=round(evolution, 2),
            unite="%",
            ville=ville,
            domaine=self.DOMAINE,
            fenetre=fenetre,
            alerte=alerte,
            metadata={"dispo_debut": round(debut, 4), "dispo_fin": round(fin, 4)},
        )


# ---------------------------------------------------------------------------
# Module 3 — KPIs Qualité de l'Air
# ---------------------------------------------------------------------------

class KPIQualiteAir:
    """
    KPIs qualité de l'air.

    DataFrame attendu :
        - timestamp   : datetime UTC
        - ville       : str
        - indice_atmo : float  (1–10, source : ATMO)
        - pm25        : float  (µg/m³)
        - pm10        : float  (µg/m³, optionnel)
        - no2         : float  (µg/m³, optionnel)
    """

    DOMAINE = "AIR"

    def compute_all(self, df: pd.DataFrame, ville: str,
                    window_min: int = WINDOW_1J) -> list[KPIResult]:
        fenetre = _fenetre_label(window_min)
        df_v = df[df["ville"] == ville].copy()
        df_w = _filter_window(df_v, "timestamp", window_min)

        if df_w.empty:
            return []

        return [
            self._indice_atmo_moyen(df_w, ville, fenetre),
            self._jours_alerte_atmo(df_w, ville, fenetre),
            self._depassements_pm25(df_w, ville, fenetre),
        ]

    # --- formules -----------------------------------------------------------

    def _indice_atmo_moyen(self, df: pd.DataFrame,
                            ville: str, fenetre: str) -> KPIResult:
        """
        Indice ATMO moyen — moyenne arithmétique sur la fenêtre.
        Indice 1 = excellent, 10 = très mauvais.
        """
        indice_moy = df["indice_atmo"].mean()

        alerte = NiveauAlerte.OK
        if indice_moy >= AIR_SEUIL_ALERTE_ATMO:
            alerte = NiveauAlerte.ALERTE
        elif indice_moy >= 5:
            alerte = NiveauAlerte.ATTENTION

        return KPIResult(
            kpi_id=f"air_atmo_moyen_{ville.lower()}",
            kpi_label=f"Indice ATMO moyen — {ville}",
            valeur=round(indice_moy, 2),
            unite="indice/10",
            ville=ville,
            domaine=self.DOMAINE,
            fenetre=fenetre,
            alerte=alerte,
            metadata={
                "indice_min": float(df["indice_atmo"].min()),
                "indice_max": float(df["indice_atmo"].max()),
            },
        )

    def _jours_alerte_atmo(self, df: pd.DataFrame,
                             ville: str, fenetre: str) -> KPIResult:
        """
        Nombre de jours avec indice ATMO ≥ 7 (mauvaise qualité).
        Agrégation : max journalier de l'indice.
        """
        df_copy = df.copy()
        df_copy["date"] = pd.to_datetime(df_copy["timestamp"], utc=True).dt.date
        jours_max = df_copy.groupby("date")["indice_atmo"].max()
        nb_jours_alerte = (jours_max >= AIR_SEUIL_ALERTE_ATMO).sum()
        total_jours = len(jours_max)

        pct = nb_jours_alerte / total_jours * 100 if total_jours > 0 else 0.0

        alerte = NiveauAlerte.OK
        if nb_jours_alerte >= 3:
            alerte = NiveauAlerte.ALERTE
        elif nb_jours_alerte >= 1:
            alerte = NiveauAlerte.ATTENTION

        return KPIResult(
            kpi_id=f"air_jours_alerte_{ville.lower()}",
            kpi_label=f"Jours ATMO ≥ 7 — {ville}",
            valeur=nb_jours_alerte,
            unite="jours",
            ville=ville,
            domaine=self.DOMAINE,
            fenetre=fenetre,
            alerte=alerte,
            metadata={"pct_jours_alerte": round(pct, 1), "total_jours": total_jours},
        )

    def _depassements_pm25(self, df: pd.DataFrame,
                             ville: str, fenetre: str) -> KPIResult:
        """
        Nombre de dépassements du seuil OMS PM2.5 (> 15 µg/m³).
        Recommandation OMS 2021 : 15 µg/m³ en moyenne sur 24h.
        """
        if "pm25" not in df.columns:
            return KPIResult(
                kpi_id=f"air_pm25_{ville.lower()}",
                kpi_label=f"Dépassements PM2.5 OMS — {ville}",
                valeur=0.0, unite="dépassements", ville=ville,
                domaine=self.DOMAINE, fenetre=fenetre,
                alerte=NiveauAlerte.OK,
                metadata={"info": "colonne pm25 absente"},
            )

        df_copy = df.copy()
        df_copy["date"] = pd.to_datetime(df_copy["timestamp"], utc=True).dt.date
        # Moyenne 24h par jour
        moy_24h = df_copy.groupby("date")["pm25"].mean()
        nb_depass = (moy_24h > AIR_SEUIL_PM25_OMS).sum()
        pm25_moy = df_copy["pm25"].mean()

        alerte = NiveauAlerte.OK
        if nb_depass >= 3 or pm25_moy > 25:
            alerte = NiveauAlerte.ALERTE
        elif nb_depass >= 1 or pm25_moy > AIR_SEUIL_PM25_OMS:
            alerte = NiveauAlerte.ATTENTION

        return KPIResult(
            kpi_id=f"air_pm25_{ville.lower()}",
            kpi_label=f"Dépassements PM2.5 OMS (> {AIR_SEUIL_PM25_OMS} µg/m³) — {ville}",
            valeur=nb_depass,
            unite="dépassements",
            ville=ville,
            domaine=self.DOMAINE,
            fenetre=fenetre,
            alerte=alerte,
            metadata={"pm25_moyen": round(pm25_moy, 2), "seuil_oms": AIR_SEUIL_PM25_OMS},
        )


# ---------------------------------------------------------------------------
# Module 4 — KPIs Trafic / Congestion
# ---------------------------------------------------------------------------

class KPITrafic:
    """
    KPIs trafic routier.

    DataFrame attendu :
        - timestamp        : datetime UTC
        - ville            : str
        - troncon_id       : str
        - score_congestion : float  (0–100)
        - longueur_km      : float  (optionnel — pondération)
    """

    DOMAINE = "TRAFIC"

    def compute_all(self, df: pd.DataFrame, ville: str,
                    window_min: int = WINDOW_1H) -> list[KPIResult]:
        fenetre = _fenetre_label(window_min)
        df_v = df[df["ville"] == ville].copy()
        df_w = _filter_window(df_v, "timestamp", window_min)

        if df_w.empty:
            return []

        # Snapshot le plus récent par tronçon
        df_snap = (
            df_w.sort_values("timestamp")
                .groupby("troncon_id")
                .last()
                .reset_index()
        )

        return [
            self._score_congestion_moyen(df_snap, ville, fenetre),
            self._troncons_fluides_bloques(df_snap, ville, fenetre),
            self._indice_fluidite_pondere(df_snap, ville, fenetre),
        ]

    # --- formules -----------------------------------------------------------

    def _score_congestion_moyen(self, df_snap: pd.DataFrame,
                                 ville: str, fenetre: str) -> KPIResult:
        """
        Score de congestion moyen (0 = fluide, 100 = bloqué).
        Pondéré par longueur_km si disponible.
        """
        if "longueur_km" in df_snap.columns and df_snap["longueur_km"].sum() > 0:
            score = (
                (df_snap["score_congestion"] * df_snap["longueur_km"]).sum()
                / df_snap["longueur_km"].sum()
            )
        else:
            score = df_snap["score_congestion"].mean()

        alerte = NiveauAlerte.OK
        if score > TRAFIC_SEUIL_BLOQUE:
            alerte = NiveauAlerte.ALERTE
        elif score > TRAFIC_SEUIL_CONGESTION_ALERTE:
            alerte = NiveauAlerte.ATTENTION

        return KPIResult(
            kpi_id=f"trafic_congestion_moy_{ville.lower()}",
            kpi_label=f"Score de congestion moyen — {ville}",
            valeur=round(score, 2),
            unite="score/100",
            ville=ville,
            domaine=self.DOMAINE,
            fenetre=fenetre,
            alerte=alerte,
            metadata={"nb_troncons": len(df_snap)},
        )

    def _troncons_fluides_bloques(self, df_snap: pd.DataFrame,
                                   ville: str, fenetre: str) -> KPIResult:
        """
        Distribution : % tronçons fluides / modérés / bloqués.
        Fluide : score < 40 | Modéré : 40–80 | Bloqué : > 80
        """
        total = len(df_snap)
        fluides = (df_snap["score_congestion"] < 40).sum()
        bloques = (df_snap["score_congestion"] > TRAFIC_SEUIL_BLOQUE).sum()
        pct_bloques = bloques / total * 100 if total > 0 else 0.0
        pct_fluides = fluides / total * 100 if total > 0 else 0.0

        alerte = NiveauAlerte.OK
        if pct_bloques > 30:
            alerte = NiveauAlerte.ALERTE
        elif pct_bloques > 15:
            alerte = NiveauAlerte.ATTENTION

        return KPIResult(
            kpi_id=f"trafic_troncons_{ville.lower()}",
            kpi_label=f"Tronçons fluides / bloqués — {ville}",
            valeur=pct_fluides,
            unite="% fluides",
            ville=ville,
            domaine=self.DOMAINE,
            fenetre=fenetre,
            alerte=alerte,
            metadata={
                "pct_bloques": round(pct_bloques, 1),
                "pct_fluides": round(pct_fluides, 1),
                "nb_bloques": int(bloques),
                "nb_fluides": int(fluides),
                "total": total,
            },
        )

    def _indice_fluidite_pondere(self, df_snap: pd.DataFrame,
                                  ville: str, fenetre: str) -> KPIResult:
        """
        Indice de fluidité = 100 - score_congestion_moyen_ponderé.
        Mesure inverse de la congestion — plus lisible pour les décideurs.
        """
        if "longueur_km" in df_snap.columns and df_snap["longueur_km"].sum() > 0:
            congestion = (
                (df_snap["score_congestion"] * df_snap["longueur_km"]).sum()
                / df_snap["longueur_km"].sum()
            )
        else:
            congestion = df_snap["score_congestion"].mean()

        fluidite = 100 - congestion

        alerte = _alerte_seuil(fluidite / 100, 0.60, 0.40)

        return KPIResult(
            kpi_id=f"trafic_fluidite_{ville.lower()}",
            kpi_label=f"Indice de fluidité — {ville}",
            valeur=round(fluidite, 2),
            unite="indice/100",
            ville=ville,
            domaine=self.DOMAINE,
            fenetre=fenetre,
            alerte=alerte,
        )


# ---------------------------------------------------------------------------
# Module 5 — Agrégations temporelles
# ---------------------------------------------------------------------------

class AggregateurTemporel:
    """
    Calcule les agrégations glissantes sur 3 fenêtres : 15min, 1h, 1j.
    Retourne un DataFrame consolidé pour Power BI (table KPIs_Historique).
    """

    def aggregate(
        self,
        df: pd.DataFrame,
        ville: str,
        domaine: str,
        col_valeur: str,
        col_ts: str = "timestamp",
    ) -> pd.DataFrame:
        """
        Construit les statistiques glissantes pour un signal donné.

        Retourne un DataFrame avec :
            timestamp | ville | domaine | fenetre | moyenne | min | max | ecart_type | tendance
        """
        rows = []
        for window_min in [WINDOW_15MIN, WINDOW_1H, WINDOW_1J]:
            df_w = _filter_window(df[df["ville"] == ville], col_ts, window_min)
            if df_w.empty:
                continue

            serie = df_w[col_valeur].dropna()
            if len(serie) < 2:
                continue

            # Tendance linéaire simple (coeff de régression sur index temporel)
            x = pd.to_datetime(df_w[col_ts], utc=True).astype("int64") / 1e9
            x_norm = (x - x.min()) / (x.max() - x.min() + 1e-9)
            tendance = float(pd.Series(serie.values).corr(pd.Series(x_norm.values)))

            rows.append({
                "timestamp": _now_utc().isoformat(),
                "ville": ville,
                "domaine": domaine,
                "fenetre": _fenetre_label(window_min),
                "col_valeur": col_valeur,
                "moyenne": round(float(serie.mean()), 4),
                "min": round(float(serie.min()), 4),
                "max": round(float(serie.max()), 4),
                "ecart_type": round(float(serie.std()), 4),
                "tendance": round(tendance, 4),   # -1 = dégradation, +1 = amélioration
                "nb_observations": len(serie),
            })

        return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Orchestrateur principal
# ---------------------------------------------------------------------------

class KPIEngine:
    """
    Point d'entrée unique du moteur KPI.
    Appelé par scheduler/jobs.py après chaque cycle d'ingestion.

    Usage :
        engine = KPIEngine()
        kpis = engine.compute(data_bundle)
        # → liste de KPIResult prête pour powerbi_pusher.py
    """

    def __init__(self) -> None:
        self.tc = KPITransportsCommun()
        self.velos = KPIVelos()
        self.air = KPIQualiteAir()
        self.trafic = KPITrafic()
        self.agregateur = AggregateurTemporel()

    def compute(self, data_bundle: dict[str, pd.DataFrame]) -> list[KPIResult]:
        """
        Calcule tous les KPIs pour toutes les villes et toutes les fenêtres.

        data_bundle = {
            "tc"     : DataFrame GTFS-RT normalisé,
            "velos"  : DataFrame stations vélos,
            "air"    : DataFrame qualité de l'air,
            "trafic" : DataFrame tronçons trafic,
        }
        """
        results: list[KPIResult] = []
        villes = ["Lille", "Montpellier"]

        for ville in villes:
            # Calcul pour chaque fenêtre temporelle pertinente
            for window_min in [WINDOW_15MIN, WINDOW_1H]:
                if "tc" in data_bundle and not data_bundle["tc"].empty:
                    results += self.tc.compute_all(data_bundle["tc"], ville, window_min)

                if "velos" in data_bundle and not data_bundle["velos"].empty:
                    results += self.velos.compute_all(data_bundle["velos"], ville, window_min)

                if "trafic" in data_bundle and not data_bundle["trafic"].empty:
                    results += self.trafic.compute_all(data_bundle["trafic"], ville, window_min)

            # Qualité de l'air : fenêtre journalière uniquement
            if "air" in data_bundle and not data_bundle["air"].empty:
                results += self.air.compute_all(data_bundle["air"], ville, WINDOW_1J)

        return results

    def to_powerbi_rows(self, results: list[KPIResult]) -> list[dict[str, Any]]:
        """Sérialise les KPIResult pour push vers Power BI (table KPIs_Temps_Reel)."""
        return [r.to_powerbi_row() for r in results]

    def get_alertes(self, results: list[KPIResult],
                     niveau_min: NiveauAlerte = NiveauAlerte.ATTENTION) -> list[KPIResult]:
        """Filtre les KPIs en alerte — pour logs / notifications."""
        niveaux = {NiveauAlerte.OK: 0, NiveauAlerte.ATTENTION: 1,
                   NiveauAlerte.ALERTE: 2, NiveauAlerte.CRITIQUE: 3}
        seuil = niveaux[niveau_min]
        return [r for r in results if niveaux[r.alerte] >= seuil]


# ---------------------------------------------------------------------------
# Mapping KPI → Power BI (documentation)
# ---------------------------------------------------------------------------

POWERBI_MAPPING: dict[str, dict] = {
    # Table : KPIs_Temps_Reel
    # Colonnes : kpi_id | kpi_label | valeur | unite | ville | domaine | fenetre | alerte | timestamp_calcul

    # --- TC ---
    "tc_ponctualite_*": {
        "table_pbi": "KPIs_Temps_Reel",
        "visuel_recommande": "Gauge / Card",
        "mesure_dax": "Taux Ponctualité = AVERAGE(KPIs_Temps_Reel[valeur])",
        "filtre_recommande": "domaine = TC AND fenetre = 1h",
    },
    "tc_retard_moyen_*": {
        "table_pbi": "KPIs_Temps_Reel",
        "visuel_recommande": "Line chart (tendance)",
        "mesure_dax": "Retard Moyen = AVERAGE(KPIs_Temps_Reel[valeur])",
    },
    # --- Vélos ---
    "velo_dispo_moy_*": {
        "table_pbi": "KPIs_Temps_Reel",
        "visuel_recommande": "Gauge",
        "mesure_dax": "Dispo Vélos = AVERAGE(KPIs_Temps_Reel[valeur])",
    },
    # --- Air ---
    "air_atmo_moyen_*": {
        "table_pbi": "KPIs_Temps_Reel",
        "visuel_recommande": "Card + conditional formatting",
        "mesure_dax": "Indice ATMO = AVERAGE(KPIs_Temps_Reel[valeur])",
    },
    # --- Trafic ---
    "trafic_congestion_moy_*": {
        "table_pbi": "KPIs_Temps_Reel",
        "visuel_recommande": "Heatmap / Filled map",
        "mesure_dax": "Score Congestion = AVERAGE(KPIs_Temps_Reel[valeur])",
    },
}
