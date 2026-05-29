# Guide Power BI — Projet Mobilité Durable
> Configuration complète : Azure AD → Dataset → Dashboard

---

## Vue d'ensemble

Le pipeline pousse les données vers Power BI de deux façons :

| Mode | Quand | Comment |
|------|-------|---------|
| **Push URL directe** | Développement / test | URL copiée depuis Power BI, sans Azure AD |
| **OAuth2 Azure AD** | Production | App enregistrée, token automatique |

Commence par le **mode Push URL** (5 minutes) pour valider que ça fonctionne, puis passe au mode OAuth2 si besoin.

---

## Option A — Push URL directe (recommandé pour commencer)

### Étape 1 — Créer un dataset Streaming dans Power BI

1. Connecte-toi sur https://app.powerbi.com
2. Dans ton workspace, clique **+ Nouveau → Dataset**
3. Choisis **API**
4. Active **"Analyse des données historiques"** (indispensable pour les graphiques)
5. Définis les colonnes du dataset **KPIs_Temps_Reel** :

| Nom du champ | Type |
|---|---|
| kpi_id | Texte |
| kpi_label | Texte |
| valeur | Nombre décimal |
| unite | Texte |
| ville | Texte |
| domaine | Texte |
| fenetre | Texte |
| alerte | Texte |
| timestamp_calcul | DateTime |

6. Clique **Créer** → Power BI affiche la **Push URL**
7. Copie cette URL

### Étape 2 — Coller dans .env

```dotenv
POWERBI_PUSH_URL_LILLE=https://api.powerbi.com/beta/XXXX/datasets/XXXX/rows?...
POWERBI_PUSH_URL_MONTPELLIER=https://api.powerbi.com/beta/XXXX/datasets/XXXX/rows?...
```

Fais ça pour les deux villes (crée deux datasets séparés).

### Étape 3 — Redémarrer le pipeline

```bash
docker compose restart pipeline
```

Les données arrivent dans Power BI dans la minute qui suit.

---

## Option B — OAuth2 Azure AD (production)

### Étape 1 — Enregistrer une application Azure AD

1. Va sur https://portal.azure.com
2. **Azure Active Directory → Inscriptions d'applications → Nouvelle inscription**
3. Nom : `MobiliteDurable-Pipeline`
4. Type de compte : **Comptes dans cet annuaire uniquement**
5. Clique **S'inscrire**

### Étape 2 — Récupérer les identifiants

Sur la page de l'application :
- Copie **l'ID d'application (client)** → `AZURE_CLIENT_ID`
- Copie **l'ID de l'annuaire (locataire)** → `AZURE_TENANT_ID`

### Étape 3 — Créer un secret client

1. **Certificats et secrets → Nouveau secret client**
2. Description : `pipeline-secret`
3. Expiration : 24 mois
4. Copie la **Valeur** immédiatement → `AZURE_CLIENT_SECRET`
   ⚠️ Elle ne s'affiche qu'une seule fois

### Étape 4 — Ajouter les permissions Power BI

1. **Autorisations d'API → Ajouter une autorisation**
2. Choisis **Power BI Service**
3. Autorisations déléguées : coche `Dataset.ReadWrite.All` et `Workspace.Read.All`
4. Clique **Accorder le consentement administrateur**

### Étape 5 — Récupérer le Workspace ID Power BI

1. Va sur https://app.powerbi.com
2. Ouvre ton workspace
3. L'URL ressemble à : `https://app.powerbi.com/groups/XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX/`
4. Le GUID dans l'URL = ton `POWERBI_WORKSPACE_ID`

### Étape 6 — Ajouter le service principal au workspace

1. Dans Power BI, ouvre les paramètres du workspace
2. **Accès → Ajouter des membres**
3. Cherche le nom de ton app (`MobiliteDurable-Pipeline`)
4. Rôle : **Contributeur**

### Étape 7 — Créer les datasets via le script

```bash
# Depuis la racine du projet (avec le .env renseigné)
python streaming/powerbi_schema.py
```

Le script crée les deux datasets (Lille + Montpellier) et affiche les Dataset IDs.

### Étape 8 — Compléter le .env

```dotenv
AZURE_TENANT_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
AZURE_CLIENT_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
AZURE_CLIENT_SECRET=votre-secret
POWERBI_WORKSPACE_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
POWERBI_DATASET_ID_LILLE=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
POWERBI_DATASET_ID_MONTPELLIER=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
```

---

## Construction du Dashboard

### 5 pages recommandées

**Page 1 — Vue d'ensemble**
- 4 cartes KPI : Ponctualité TC | Dispo Vélos | Indice ATMO | Congestion
- Filtre : Ville (Lille / Montpellier)
- Indicateur couleur : rouge si alerte, vert si OK

**Page 2 — Transports en commun**
- Graphique en courbes : ponctualité par ligne dans le temps
- Tableau : retard moyen par ligne
- Carte géographique : positions véhicules (latitude/longitude de TC_Retards)

**Page 3 — Vélos en libre-service**
- Carte : stations (latitude/longitude de Velo_Stations), couleur selon taux_dispo
- Gauge : disponibilité globale (%)
- Histogramme : distribution des taux de disponibilité par station

**Page 4 — Qualité de l'air**
- Courbe temporelle : indice ATMO sur 7 jours
- Carte : niveau ATMO par ville
- Indicateur : dépassements OMS PM2.5 (compteur)

**Page 5 — Trafic**
- Carte choroplèthe : score de congestion par tronçon
- Jauge : congestion globale (0–100)
- Courbe : évolution congestion sur 24h

### Mesures DAX clés à créer manuellement

Dans Power BI Desktop, ajoute ces mesures sur la table `KPIs_Temps_Reel` :

```dax
-- Dernière valeur ponctualité Lille
Ponctualité Lille =
CALCULATE(
    LASTNONBLANKVALUE(KPIs_Temps_Reel[timestamp_calcul], AVERAGE(KPIs_Temps_Reel[valeur])),
    KPIs_Temps_Reel[kpi_id] = "tc_ponctualite_lille",
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
Delta Ponctualité =
VAR lille = CALCULATE(AVERAGE(KPIs_Temps_Reel[valeur]),
    KPIs_Temps_Reel[ville] = "Lille",
    SEARCH("ponctualite", KPIs_Temps_Reel[kpi_id], 1, 0) > 0)
VAR mtp = CALCULATE(AVERAGE(KPIs_Temps_Reel[valeur]),
    KPIs_Temps_Reel[ville] = "Montpellier",
    SEARCH("ponctualite", KPIs_Temps_Reel[kpi_id], 1, 0) > 0)
RETURN lille - mtp
```

---

## Vérification que les données arrivent

1. Dans Power BI, ouvre le dataset
2. Clique sur les **3 points → Actualiser maintenant**
3. Ou attends le prochain cycle (max 60s)
4. Dans un rapport, ajoute un **tableau** avec toutes les colonnes de `KPIs_Temps_Reel`
5. Tu dois voir les lignes apparaître en temps réel

---

## Dépannage

| Problème | Solution |
|----------|----------|
| Données n'arrivent pas | Vérifie les logs : `docker compose logs -f pipeline` |
| `401 Unauthorized` | Token Azure AD expiré ou permissions manquantes |
| `400 Bad Request` | Colonnes du dataset ne correspondent pas au schéma |
| Push URL ne fonctionne plus | Les Push URLs expirent — recrée le dataset |
| Dataset vide dans Power BI | Vérifie que "Analyse des données historiques" est activé |
