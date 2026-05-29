# Dashboard Power BI — Mobilité Durable

> Structure, configuration et mesures du dashboard temps réel Lille & Montpellier

---

## 1. Architecture du dashboard

Le dashboard est alimenté en **temps réel** via le streaming Power BI REST API. Le pipeline pousse les KPIs calculés toutes les 20s (GTFS-RT) et 60s (vélos, air, trafic).

```
Pipeline Python ──push──▶ Power BI Streaming Dataset ──▶ Dashboard (5 pages)
```

---

## 2. Configuration rapide (5 min)

### Mode Push URL (recommandé pour démarrer)

1. Aller sur [app.powerbi.com](https://app.powerbi.com)
2. Créer un **nouveau dataset** → **API**
3. Activer **"Analyse des données historiques"** ✅
4. Définir les colonnes (voir schéma ci-dessous)
5. Copier la **Push URL** générée
6. Coller dans `config/.env` :
   ```
   POWERBI_PUSH_URL_LILLE=https://api.powerbi.com/beta/.../rows?...
   POWERBI_PUSH_URL_MONTPELLIER=https://api.powerbi.com/beta/.../rows?...
   ```
7. Redémarrer le pipeline

> 📖 Guide détaillé : [streaming/GUIDE_POWERBI.md](../streaming/GUIDE_POWERBI.md)

---

## 3. Schéma des datasets

### Table principale : KPIs_Temps_Reel

| Colonne | Type Power BI | Description |
|---|---|---|
| kpi_id | Texte | Identifiant unique du KPI |
| kpi_label | Texte | Libellé lisible |
| valeur | Nombre décimal | Valeur numérique |
| unite | Texte | Unité (% , min, µg/m³, score) |
| ville | Texte | "Lille" ou "Montpellier" |
| domaine | Texte | "TC", "VELO", "AIR", "TRAFIC" |
| fenetre | Texte | "15min", "1h", "1j" |
| alerte | Texte | "OK", "ATTENTION", "ALERTE", "CRITIQUE" |
| timestamp_calcul | DateTime | Horodatage du calcul |

### Tables détaillées (5 tables au total)

Les tables `TC_Retards`, `Velo_Stations`, `Qualite_Air` et `Trafic_Troncons` sont définies dans `streaming/powerbi_schema.py` et provisionnées automatiquement via `python streaming/powerbi_schema.py` (mode OAuth2).

---

## 4. Structure du dashboard (5 pages)

### Page 1 — Vue d'ensemble 🏠

```
┌──────────────────────────────────────────────────┐
│  FILTRE : Ville (Lille / Montpellier)            │
├─────────┬──────────┬──────────┬──────────────────┤
│  Carte  │  Carte   │  Carte   │     Carte        │
│  TC     │  Vélos   │  Air     │    Trafic        │
│  Ponct. │  Dispo   │  ATMO    │  Congestion      │
│  100%   │  93,7%   │  3,87    │   6,6/100       │
│  🟢     │  🟢      │  🟡      │    🟢            │
├─────────┴──────────┴──────────┴──────────────────┤
│  Carte France : Lille 📍 / Montpellier 📍        │
│  → Indicateurs couleur selon niveau d'alerte     │
└──────────────────────────────────────────────────┘
```

**Visuels** :
- 4 cartes KPI avec mise en forme conditionnelle (vert/orange/rouge selon alerte)
- Segmenteur ville
- Indicateur du nombre de KPIs en alerte

### Page 2 — Transports en commun 🚌

```
┌──────────────────────────────────────────────────┐
│  Courbe : Ponctualité par ligne dans le temps    │
│  ─── Ligne 1  ─── Ligne 2  ─── Ligne 3          │
├─────────────────────┬────────────────────────────┤
│  Tableau : Retard  │  Carte : Positions          │
│  moyen par ligne   │  véhicules (lat/lon)         │
│  Ligne 10: 8min ⚠️ │  ● ● ●                      │
│  Ligne 11: 3min    │  ● ●                         │
├─────────────────────┤                             │
│  Jauge : Ponct.    │                             │
│  globale 88,9%     │                             │
└─────────────────────┴────────────────────────────┘
```

**Visuels** :
- Graphique en courbes : ponctualité temporelle
- Tableau : retard moyen par ligne
- Jauge : ponctualité globale
- Carte : positions véhicules (si données dispo)

### Page 3 — Vélos en libre-service 🚲

```
┌──────────────────────────────────────────────────┐
│  Carte : Stations (bulles, couleur = taux_dispo) │
│  🟢 Dispo  🟡 Faible  🔴 Vide                   │
├─────────────────────┬────────────────────────────┤
│  Jauge : Dispo      │  Histogramme :             │
│  moyenne 93,7%      │  distribution taux dispo   │
│                     │  par station                 │
├─────────────────────┼────────────────────────────┤
│  Compteur :         │  Courbe : Évolution         │
│  17 stations vides  │  disponibilité sur 24h       │
└─────────────────────┴────────────────────────────┘
```

**Visuels** :
- Carte à bulles : stations avec couleur selon taux_dispo
- Jauge : disponibilité globale
- Histogramme : distribution des taux
- Compteur : stations vides

### Page 4 — Qualité de l'air 🌬️

```
┌──────────────────────────────────────────────────┐
│  Courbe : Indice ATMO sur 7 jours                │
│  ─── Lille  ─── Seuil alerte (7)                  │
├─────────────────────┬────────────────────────────┤
│  Carte : Niveau     │  Compteur :                 │
│  ATMO par ville     │  Dépassements OMS PM2.5     │
│  Lille 🟡 3,87     │  0                          │
│  Montpellier 🟢     │                              │
├─────────────────────┼────────────────────────────┤
│  Barres : PM2.5,   │  Indicateur :              │
│  PM10, NO2, O3     │  ATMO actuel + tendance      │
└─────────────────────┴────────────────────────────┘
```

**Visuels** :
- Courbe temporelle ATMO
- Carte par ville
- Barres : concentrations polluants
- Indicateur ATMO actuel

### Page 5 — Trafic routier 🚗

```
┌──────────────────────────────────────────────────┐
│  Carte : Tronçons (couleur = congestion)         │
│  🟢 Fluide  🟡 Modéré  🔴 Bloqué                │
├─────────────────────┬────────────────────────────┤
│  Jauge : Congestion │  Courbe : Évolution         │
│  globale 6,6/100    │  congestion sur 24h          │
├─────────────────────┼────────────────────────────┤
│  Donut :            │  Tableau :                  │
│  Fluide/Modéré/     │  Détail par tronçon         │
│  Bloqué             │  Gare: 36% 🔴               │
└─────────────────────┴────────────────────────────┘
```

**Visuels** :
- Carte choroplèthe : tronçons avec score de congestion
- Jauge : congestion globale
- Donut : répartition fluide/modéré/bloqué
- Tableau : détail par tronçon

---

## 5. Mesures DAX à créer

```dax
-- Dernière valeur ponctualité
Ponctualité TC =
CALCULATE(
    AVERAGE(KPIs_Temps_Reel[valeur]),
    KPIs_Temps_Reel[domaine] = "TC",
    SEARCH("ponctualite", KPIs_Temps_Reel[kpi_id], 1, 0) > 0,
    KPIs_Temps_Reel[fenetre] = "1h"
)

-- Couleur alerte dynamique
Couleur Alerte =
SWITCH(
    SELECTEDVALUE(KPIs_Temps_Reel[alerte]),
    "OK", "#27AE60",
    "ATTENTION", "#F39C12",
    "ALERTE", "#E74C3C",
    "CRITIQUE", "#8E44AD",
    "#95A5A6"
)

-- Comparaison Lille vs Montpellier
Delta Congestion =
VAR lille = CALCULATE(AVERAGE(KPIs_Temps_Reel[valeur]),
    KPIs_Temps_Reel[ville] = "Lille",
    KPIs_Temps_Reel[domaine] = "TRAFIC",
    SEARCH("congestion_moy", KPIs_Temps_Reel[kpi_id], 1, 0) > 0)
VAR mtp = CALCULATE(AVERAGE(KPIs_Temps_Reel[valeur]),
    KPIs_Temps_Reel[ville] = "Montpellier",
    KPIs_Temps_Reel[domaine] = "TRAFIC",
    SEARCH("congestion_moy", KPIs_Temps_Reel[kpi_id], 1, 0) > 0)
RETURN lille - mtp

-- Nombre de KPIs en alerte
Nb Alertes =
CALCULATE(
    COUNTROWS(KPIs_Temps_Reel),
    KPIs_Temps_Reel[alerte] IN {"ALERTE", "CRITIQUE"}
)
```

---

## 6. Vérification que les données arrivent

1. Après démarrage du pipeline, attendre 60s maximum
2. Dans Power BI : ouvrir le dataset → **3 points → Actualiser**
3. Ajouter un tableau avec toutes les colonnes de `KPIs_Temps_Reel`
4. Les lignes doivent apparaître en temps réel

**Dépannage** : voir [streaming/GUIDE_POWERBI.md](../streaming/GUIDE_POWERBI.md)

---

## 7. KPIs disponibles dans le dashboard

| kpi_id | Libellé | Domaine | Unité |
|---|---|---|---|
| `tc_ponctualite_{ville}` | Taux de ponctualité TC | TC | % |
| `tc_retard_moyen_{ville}` | Retard moyen TC | TC | min |
| `tc_retard_fort_{ville}` | Courses retard fort | TC | % |
| `tc_couverture_{ville}` | Couverture réseau TC | TC | % |
| `tc_ponctualite_{ville}_ligne_{n}` | Ponctualité par ligne | TC | % |
| `velo_dispo_moy_{ville}` | Disponibilité moyenne vélos | VELO | % |
| `velo_stations_vides_{ville}` | Stations vélos vides | VELO | % |
| `velo_stations_hs_{ville}` | Stations hors service | VELO | % |
| `velo_evolution_{ville}` | Évolution disponibilité | VELO | % |
| `air_atmo_moyen_{ville}` | Indice ATMO moyen | AIR | indice/10 |
| `air_jours_alerte_{ville}` | Jours ATMO ≥ 7 | AIR | jours |
| `air_pm25_{ville}` | Dépassements PM2.5 OMS | AIR | dépassements |
| `trafic_congestion_moy_{ville}` | Score congestion moyen | TRAFIC | score/100 |
| `trafic_troncons_{ville}` | Tronçons fluides / bloqués | TRAFIC | % |
| `trafic_fluidite_{ville}` | Indice de fluidité | TRAFIC | indice/100 |
