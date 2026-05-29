# Note d'Analyse — Évaluation des Politiques de Mobilité Durable

## Lille Métropole vs Montpellier 3M

---

## 1. Contexte

La transition vers une mobilité durable est un enjeu majeur des métropoles françaises. Lille et Montpellier ont chacune déployé des politiques publiques visant à réduire la dépendance à la voiture et promouvoir les transports en commun et les mobilités douces.

**Question centrale :** *Les politiques de mobilité durable mises en œuvre sont-elles efficaces ?*

Ce rapport propose une évaluation data-driven basée sur des indicateurs quantifiables, collectés en temps réel via un pipeline automatisé.

---

## 2. Méthodologie

### 2.1 Sources de données

| Source | Type | Fréquence | Couverture |
|--------|------|-----------|------------|
| Open Data Lille (CKAN) | API REST | 60s | Vélos, Air, Trafic |
| Open Data Montpellier (DKAN) | API REST | 60s | Vélos, Air, Trafic |
| GTFS-RT Ilévia / TAM | Protobuf | 20s | Retards TC temps réel |
| ATMO Hauts-de-France | ArcGIS REST | 60s | Indice ATMO, PM2.5 |
| ATMO Occitanie | ArcGIS REST | 60s | Indice ATMO, PM2.5 |

### 2.2 Pipeline de données

```
Ingestion (API) → Normalisation → Calcul KPIs → Stockage PostgreSQL → Évaluation politique
                                  ↓                                  ↓
                            Push Power BI                    Dashboard local
```

### 2.3 Modèle de données

- **Schéma en étoile** : table de faits `kpi_historique` + dimensions (ville, domaine, fenêtre temporelle)
- **Table d'évaluation** : `policy_scores` avec scores composites par dimension
- **Rétention** : 90 jours glissants

---

## 3. KPIs choisis — Et pourquoi

### 3.1 KPIs opérationnels (mesure de l'état du système)

| KPI | Domaine | Pourquoi |
|-----|---------|----------|
| Taux de ponctualité TC | Transport | Indicateur UITP — fiabilité du service public |
| Retard moyen TC | Transport | Impact direct sur l'attractivité des TC |
| Couverture réseau TC | Transport | Accessibilité géographique |
| Disponibilité vélos | Mobilité douce | Conditions d'usage du vélo |
| Stations vélos vides | Mobilité douce | Perte de confiance utilisateur |
| Indice ATMO moyen | Qualité de l'air | Impact sanitaire direct |
| Jours alerte ATMO | Qualité de l'air | Fréquence des épisodes pollués |
| Dépassements PM2.5 OMS | Qualité de l'air | Norme sanitaire internationale |
| Score de congestion | Trafic | Niveau de saturation routière |
| Indice de fluidité | Trafic | Inverse de la congestion — lisible |

### 3.2 KPIs de politique publique (mesure de l'efficacité)

| Dimension | Score | Logique |
|-----------|-------|---------|
| **Mobilité Douce** | 0–100 | Attractivité vélo+TC vs dissuasion voiture |
| **Qualité de l'Air** | 0–100 | ATMO inversé + PM2.5 - malus jours alerte |
| **Efficacité TC** | 0–100 | Ponctualité × couverture - malus retards |
| **Trafic Routier** | 0–100 | Fluidité + anti-congestion + tronçons fluides |
| **Score Global** | 0–100 | Composite pondéré (30% Douce, 25% Air, 25% TC, 20% Trafic) |

Chaque dimension inclut un **indicateur de tendance** (↑ amélioration / → stable / ↓ dégradation).

---

## 4. Résultats

### 4.1 Scores globaux

| Ville | Score Global | Tendance | Meilleure dimension | Dimension à améliorer |
|-------|-------------|----------|---------------------|----------------------|
| Lille | _[auto]_ | _[auto]_ | _[auto]_ | _[auto]_ |
| Montpellier | _[auto]_ | _[auto]_ | _[auto]_ | _[auto]_ |

> *Les scores sont mis à jour automatiquement toutes les 5 minutes par le pipeline.*

### 4.2 Comparaison par dimension

| Dimension | Lille | Montpellier | Écart | Leader |
|-----------|-------|-------------|-------|--------|
| Mobilité Douce | _[auto]_ | _[auto]_ | _[auto]_ | _[auto]_ |
| Qualité de l'Air | _[auto]_ | _[auto]_ | _[auto]_ | _[auto]_ |
| Efficacité TC | _[auto]_ | _[auto]_ | _[auto]_ | _[auto]_ |
| Trafic Routier | _[auto]_ | _[auto]_ | _[auto]_ | _[auto]_ |

### 4.3 Analyse avant / après politique

| Politique | Ville | Dimension | Avant | Après | Delta |
|-----------|-------|-----------|-------|-------|-------|
| Plan Climat Lille | Lille | _[auto]_ | _[auto]_ | _[auto]_ | _[auto]_ |
| Extension V'Lille | Lille | _[auto]_ | _[auto]_ | _[auto]_ | _[auto]_ |
| Plan Mobilités 3M | Montpellier | _[auto]_ | _[auto]_ | _[auto]_ | _[auto]_ |
| Lignes gratuites TAM | Montpellier | _[auto]_ | _[auto]_ | _[auto]_ | _[auto]_ |

> *L'analyse avant/après nécessite un historique suffisant (minimum 30 jours de données).*

---

## 5. Recommandations

### 5.1 Sur la méthode

- **Pérenniser le collecte** : les tendances ne sont fiables qu'avec un historique suffisant
- **Ajouter des données de fréquentation TC** (validation billets) pour mesurer le report modal réel
- **Intégrer les données CO2** (émission par habitant) via ATMO ou CITEPA
- **Benchmark avec une 3e ville** (Paris, Lyon) pour contextualiser les scores

### 5.2 Sur les politiques

> _[À compléter avec les résultats observés après 30 jours de collecte]_

**Hypothèses à tester :**

1. La gratuité TC à Montpellier a-t-elle augmenté la fréquentation sans dégrader la ponctualité ?
2. L'extension V'Lille en périphérie a-t-elle augmenté l'usage du vélo en zone périurbaine ?
3. Les plans climat ont-ils un effet mesurable sur la qualité de l'air à 6 mois ?

---

## 6. Modèle d'évaluation

```
┌─────────────────────────────────────────────────────────┐
│              SCORE GLOBAL (0-100)                       │
│                                                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │  MOBILITÉ    │  │  QUALITÉ     │  │  EFFICACITÉ  │  │
│  │  DOUCE (30%) │  │  AIR (25%)   │  │  TC (25%)    │  │
│  │              │  │              │  │              │  │
│  │  • Vélos     │  │  • ATMO      │  │  • Ponctual. │  │
│  │  • TC attract│  │  • PM2.5     │  │  • Couverture│  │
│  │  • Voiture   │  │  • Jours     │  │  • Retards   │  │
│  │    pénalisée │  │    alerte    │  │    forts     │  │
│  └──────────────┘  └──────────────┘  └──────────────┘  │
│                                                         │
│              ┌──────────────┐                           │
│              │  TRAFIC (20%)│                           │
│              │              │                           │
│              │  • Fluidité  │                           │
│              │  • Congestion│                           │
│              │  • Tronçons  │                           │
│              └──────────────┘                           │
└─────────────────────────────────────────────────────────┘
```

---

## 7. Limites et perspectives

| Limite | Mitigation |
|--------|-----------|
| Données open data pas toujours disponibles | Fallback gracieux, logs d'audit |
| Pas de données de fréquentation TC réelles | Peut être ajouté via API opérateur |
| Pas d'estimation CO2 directe | Modèle d'émission basé sur modal shift (à venir) |
| Avant/après nécessite un historique long | Score de tendance en attendant |
| Pas de données socio-démographiques | Permettraient une analyse d'équité |

---

*Note générée automatiquement par le pipeline Mobilité Durable — [Date]*
