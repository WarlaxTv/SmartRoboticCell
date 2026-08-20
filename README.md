# Smart Robotic Cell V2 - Supervision Multi-Cellules

Bienvenue dans la version 2 du projet. Cette version a été reconstruite de zéro pour répondre à de nouveaux enjeux industriels :

- **Supervision multi-cellules** via OPC UA.
- **Sécurité et sûreté de fonctionnement** (Read-Only) pour prévenir les accidents liés à la prise de contrôle à distance.
- **Conformité stricte à la norme NF EN 9100** (Qualité Aéronautique & Défense).
- **Sécurisation SSL/TLS** des communications serveur.

## Prérequis & installation

### Prérequis

- Python 3.12+
- Windows PowerShell (pour les scripts `scripts/run_servers.ps1` / `scripts/run_quality.ps1`)

### Installation (portable)

À exécuter à la racine du projet :

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## Sécurité & certificats (SSL/TLS)

Le projet utilise des certificats auto-signés pour :

- **OPC UA (OT)** : échanges chiffrés avec politique *Sign & Encrypt*.
- **Web (IT)** : accès au dashboard via **HTTPS**.

Génération des certificats (stockés dans `certs/`) :

```powershell
python scripts/generate_certs.py
```

## Architecture du projet

- `src_v2/` : code source (Serveur Web FastAPI, client/serveur OPC UA, sécurité JWT/RBAC, persistance SQLite).
- `src_v2/templates/` : pages HTML (vue principale, détail cellule, historiques, comparaison de données).
- `src_v2/static/` : assets front-end partagés (thème, navigation, popups, Chart.js vendorisé en local).
- `scripts/` : scripts PowerShell/Python ponctuels (génération de certificats, démo/qualité "one-click", jeu de données historique, tests de charge) — voir sections ci-dessous.
- `certs/` : certificats X.509 et clés privées générés localement.
- `tests/` : tests unitaires (Pytest) pour valider la logique métier et la sécurité.
- `docs_v2/` : documentation technique, conformité et journaux de traçabilité.

## Pages disponibles

Une fois connecté, la navigation se fait via le menu déroulant en haut de chaque page :

- `/` — Vue principale (les 3 cellules).
- `/cell/{id}` — Détail d'une cellule (rôle MAINTENANCE) : diagnostics, historique des défauts et de maintenance, courbes par axe.
- `/historique-maintenance` — Historique des interventions, toutes cellules (rôle MAINTENANCE).
- `/historique-pannes` — Historique des défauts, toutes cellules, filtrable par cellule (rôle MAINTENANCE).
- `/donnees` — Comparaison des 3 cellules (rôle MAINTENANCE).

## Lancement

### Scripts PowerShell (démo & qualité)

```powershell
# Lance les deux serveurs (OPC UA + Web) + génère les certs si besoin
./scripts/run_servers.ps1

# Lance les preuves qualité (tests, coverage, lint, format)
./scripts/run_quality.ps1
```

Ensuite, ouvre le dashboard :

- https://127.0.0.1:8082

Accepte le certificat auto-signé si ton navigateur l'affiche comme non reconnu.

### Lancement manuel (si besoin)

Dans deux terminaux séparés :

```powershell
# Serveur OPC UA (simulateur)
python -m src_v2.opcua_server
```

```powershell
# Serveur Web FastAPI (HTTPS)
python -m uvicorn src_v2.web_server:app --host 0.0.0.0 --port 8082 `
  --ssl-keyfile certs/web_key.pem `
  --ssl-certfile certs/web_cert.pem
```

## Qualité (PEP8, tests, sécurité)

Commandes utiles (à lancer à la racine du projet) :

```powershell
# Tests unitaires
python -m pytest

# Couverture (le serveur OT opcua_server.py est exclu car boucle infinie)
python -m pytest --cov=src_v2 --cov-report=term-missing

# Lint PEP8 / qualité
python -m ruff check .

# Formatage
python -m black --check .
python -m black .

# Analyse statique PyLint (config projet)
python -m pylint src_v2 --rcfile .\.pylintrc --score=y
```

## Tests de charge (Locust)

```powershell
python -m pip install locust
locust -f scripts/locustfile.py --host=https://127.0.0.1:8082
```

Ouvre ensuite http://localhost:8089 pour piloter la simulation (nombre d'utilisateurs, montée en charge).

## Comptes de démonstration

| Identifiant | Mot de passe | Rôle        |
|-------------|---------------|-------------|
| jean_ope    | ope123        | OPERATEUR   |
| luc_maint   | maint123      | MAINTENANCE |

## Données de démonstration (optionnel)

Pour peupler la base d'un historique réaliste (3 semaines de mesures et de défauts) avant une démonstration :

```powershell
$env:SRC_DB_PATH = "smart_robotic_cell.db"
python scripts/seed_historical_data.py
```

Le script est idempotent et non-destructif : relancé sur une base déjà peuplée (par la tâche de fond du serveur ou un lancement précédent), il ne duplique ni ne supprime jamais aucune donnée réelle.
