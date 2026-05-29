# 🚲 Mobilité Durable — Pipeline Data Lille & Montpellier

> **Évaluer l'efficacité des politiques de mobilité durable dans les métropoles de Lille et Montpellier**

Pipeline end-to-end de collecte, traitement, stockage et visualisation de données de mobilité durable en temps réel.

---

## 📋 Contexte

L'État souhaite évaluer l'efficacité des politiques de mobilité durable dans les métropoles de Lille et Montpellier. Ce projet construit des indicateurs de performance (KPI) à partir de données hétérogènes open data, et les restitue via un dashboard Power BI en temps réel.

---

## 🏗 Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        SOURCES OPEN DATA                        │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌───────────────┐   │
│  │ GBFS     │  │ GTFS-RT  │  │ ArcGIS   │  │ TomTom        │   │
│  │ V'Lille  │  │ Ilévia   │  │ Atmo HDF │  │ Traffic API   │   │
│  │ VéloMagg │  │ TAM      │  │ Atmo Occ │  │               │   │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └──────┬────────┘   │
└───────┼──────────────┼──────────────┼──────────────┼────────────┘
        │              │              │              │
┌───────▼──────────────▼──────────────▼──────────────▼────────────┐
│                      INGESTION (Python)                          │
│  ┌─────────────────┐  ┌──────────────────┐  ┌────────────────┐  │
│  │ LilleClient      │  │ MontpellierClient│  │ GTFSRTClient   │  │
│  │  • get_velos()   │  │  • get_velos()   │  │  • Lille       │  │
│  │  • get_air()     │  │  • get_air()     │  │  • Montpellier │  │
│  │  • get_trafic()  │  │  • get_trafic()  │  │                │  │
│  └────────┬─────────┘  └────────┬─────────┘  └───────┬────────┘  │
└───────────┼──────────────────────┼────────────────────┼──────────┘
            │                      │                    │
┌───────────▼──────────────────────▼────────────────────▼──────────┐
│                    PROCESSING (Normalizer + KPI Engine)          │
│  ┌─────────────────┐  ┌──────────────────────────────────────┐   │
│  │ Normalizer       │  │ KPI Engine                           │   │
│  │  → DataFrame     │  │  • TC : ponctualité, retards         │   │
│  │    propre &       │  │  • Vélos : dispo, stations vides    │   │
│  │    validé         │  │  • Air : ATMO, PM2.5 OMS            │   │
│  │                  │  │  • Trafic : congestion, fluidité     │   │
│  └────────┬─────────┘  └────────────────┬───────────────────┘   │
└───────────┼───────────────────────────────┼───────────────────────┘
            │                               │
┌───────────▼───────────────────────────────▼───────────────────────┐
│                    STOCKAGE & STREAMING                          │
│  ┌─────────────────┐  ┌──────────────────────────────────────┐   │
│  │ PostgreSQL 16    │  │ Power BI Streaming                   │   │
│  │  • 6 tables      │  │  • Push URL (dev)                    │   │
│  │  • Audit pipeline │  │  • OAuth2 Azure AD (prod)           │   │
│  │  • Purge 90j     │  │  • 5 tables + mesures DAX           │   │
│  └─────────────────┘  └──────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────┘
```

---

## 📊 Sources de données

| Source | Ville | Format | Fréquence | Données |
|---|---|---|---|---|
| **GBFS ilévia** | Lille | JSON (GBFS 2.2) | 60s | 268 stations V'Lille |
| **GBFS Fifteen** | Montpellier | JSON (GBFS 2.2) | 60s | 52 stations VéloMagg |
| **GTFS-RT Ilévia** | Lille | Protobuf | 20s | ~290 courses TC |
| **GTFS-RT TAM** | Montpellier | Protobuf | 20s | ~250 courses TC |
| **ArcGIS Atmo HDF** | Lille | JSON | 60s | 500 mesures air (indice ATMO) |
| **ArcGIS Atmo Occitanie** | Montpellier | JSON | 60s | 118 mesures air (polluants) |
| **TomTom Flow Segment** | Les 2 | JSON | 60s | 12+12 tronçons trafic |

---

## 📈 KPIs calculés

### Transports en commun (TC)
| KPI | Formule | Seuil alerte |
|---|---|---|
| Taux de ponctualité | courses \|retard\| < 3min / total | < 85% |
| Retard moyen | moyenne(retard positif) en min | > 6 min |
| Courses retard fort | % courses retard > 6 min | > 20% |
| Couverture réseau | lignes actives / total | < 90% |

### Vélos en libre-service
| KPI | Formule | Seuil alerte |
|---|---|---|
| Disponibilité moyenne | Σ vélos_dispo / Σ capacité | < 70% |
| Stations vides | % stations avec 0 vélo | > 15% |
| Stations hors service | % stations non en_service | > 10% |

### Qualité de l'air
| KPI | Formule | Seuil alerte |
|---|---|---|
| Indice ATMO moyen | moyenne indice (1-10) | ≥ 7 |
| Jours alerte ATMO | nb jours ATMO ≥ 7 | ≥ 3 |
| Dépassements PM2.5 OMS | nb jours PM2.5 > 15 µg/m³ | ≥ 3 |

### Trafic routier
| KPI | Formule | Seuil alerte |
|---|---|---|
| Score congestion moyen | (1 - current_speed/free_flow) × 100 | > 60 |
| Tronçons fluides/bloqués | % score < 40 / % score > 80 | > 30% bloqués |
| Indice de fluidité | 100 - congestion_moyenne | < 60 |

---

## 🗃 Schéma de base de données

```
PostgreSQL — mobilite_durable
├── kpi_historique      → toutes les valeurs KPI horodatées
├── tc_retards          → retards TC par course (GTFS-RT)
├── velo_stations       → snapshots stations vélos (60s)
├── qualite_air         → mesures air (ATMO + polluants)
├── trafic_troncons     → scores congestion (TomTom)
└── pipeline_audit      → journal des cycles d'ingestion
```

---

## 🚀 Installation

### Prérequis
- Python 3.11+
- Docker & Docker Compose
- Clé API TomTom ([developer.tomtom.com](https://developer.tomtom.com) — gratuit 2500 req/jour)

### 1. Clone & config

```bash
git clone <repo>
cd mobilite-durable
cp config/.env.example config/.env
```

Éditer `config/.env` — au minimum :
```dotenv
TOMTOM_API_KEY=votre_cle_tomtom
DATABASE_URL=postgresql+psycopg2://mobilite:secret@localhost:5432/mobilite_durable
```

### 2. Docker (recommandé)

```bash
docker compose up -d          # PostgreSQL + pipeline
docker compose --profile dev up -d  # + Adminer (DB UI)
```

### 3. Local (sans Docker)

```bash
python -m venv .venv
source .venv/bin/activate     # Linux/Mac
.venv\Scripts\activate        # Windows

pip install -r requirements.txt
python main.py
```

---

## 🧪 Tests

```bash
pytest tests/ -v
# 26 tests — KPI Engine (TC, Vélos, Air, Trafic, Agrégations)
```

---

## 📂 Structure du projet

```
mobilite-durable/
├── main.py                    # Point d'entrée (scheduler + health check)
├── config/
│   ├── settings.py            # Configuration centralisée (dotenv)
│   └── .env                   # Variables d'environnement
├── ingestion/
│   ├── base_client.py         # Client HTTP abstrait (retry, session)
│   ├── lille_client.py        # Client Lille (GBFS + ArcGIS + TomTom)
│   ├── montpellier_client.py  # Client Montpellier (GBFS + ArcGIS + TomTom)
│   └── gtfsrt_client.py      # Client GTFS-RT (Protobuf)
├── processing/
│   ├── normalizer.py          # Normalisation → DataFrames
│   ├── schemas.py             # Schémas Pydantic (validation)
│   └── kpi_engine.py          # Moteur de calcul des KPIs
├── storage/
│   ├── models.py              # Modèles SQLAlchemy (6 tables)
│   └── database.py            # Couche d'accès PostgreSQL
├── streaming/
│   ├── powerbi_pusher.py      # Push REST API Power BI (OAuth2 + Push URL)
│   ├── powerbi_schema.py      # Schéma des datasets Power BI
│   └── GUIDE_POWERBI.md      # Guide de configuration Power BI
├── scheduler/
│   └── jobs.py                # Jobs APScheduler (CKAN 60s, GTFS-RT 20s)
├── utils/
│   ├── logger.py              # Loguru (rotation, compression)
│   └── tomtom_traffic.py      # Client TomTom Flow Segment Data
├── tests/
│   └── test_kpi_engine.py    # 26 tests unitaires
├── docker/
│   └── postgres/init.sql      # Init PostgreSQL
├── Dockerfile                 # Multi-stage (builder + runner)
├── docker-compose.yml         # Stack complète
├── requirements.txt           # Dépendances verrouillées
└── docs/
    ├── note_analyse.md        # Note d'analyse comparative
    └── DASHBOARD.md           # Documentation du dashboard Power BI
```

---

## 🔧 Choix techniques

| Composant | Choix | Justification |
|---|---|---|
| Langage | Python 3.11 | Écosystème data, APIs, protocole GBFS/GTFS-RT |
| Base de données | PostgreSQL 16 | Robuste, JSON, time-series, open source |
| Scheduler | APScheduler | Léger, pas de broker externe, compatible threads |
| Vélos | GBFS 2.2 | Standard ouvert, temps réel, couverture mondiale |
| TC | GTFS-RT (Protobuf) | Standard de facto transports, données retard |
| Air | ArcGIS FeatureServer | Seule source fiable (Atmo HDF / Atmo Occitanie) |
| Trafic | TomTom Flow API | Données réelles, couverture mondiale, gratuit 2500 req/j |
| Validation | Pydantic v2 | Validation stricte, typage, sérialisation |
| ORM | SQLAlchemy 2.0 | Type-safe, async-ready, migrations Alembic |
| Streaming PBI | REST API Push | Mode dev (Push URL) + prod (OAuth2 Azure AD) |
| Logging | Loguru | Rotation auto, thread-safe, compression |
| Conteneurisation | Docker multi-stage | Image légère, sécurité (user non-root) |

---

## 📡 Endpoints

| Endpoint | Port | Description |
|---|---|---|
| `GET /health` | 8080 | Health check (DB + scheduler) |
| `GET /metrics` | 8080 | Métriques (uptime, cycles, DB) |
| Adminer | 8888 | UI PostgreSQL (dev uniquement) |

---

## 📝 Livrables

- [Note d'analyse comparative](docs/note_analyse.md) — Évaluation des politiques de mobilité durable
- [Documentation Dashboard](docs/DASHBOARD.md) — Structure et configuration Power BI
