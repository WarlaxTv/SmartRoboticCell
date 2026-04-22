# Smart Robotic Cell V2 - Supervision Multi-Cellules

Bienvenue dans la version 2 du projet. Cette version a été reconstruite de zéro pour répondre à de nouveaux enjeux industriels :

- **Supervision multi-cellules** via OPC UA.
- **Sécurité et sûreté de fonctionnement** (Read-Only) pour prévenir les accidents liés à la prise de contrôle à distance.
- **Conformité stricte à la norme NF EN 9100** (Qualité Aéronautique & Défense).
- **Sécurisation SSL/TLS** des communications serveur.

## Démarrage rapide

1. **Générer les certificats SSL** (requis pour HTTPS et OPC UA sécurisé) :
   ```bash
   python generate_certs.py
   ```

2. **Démarrer le serveur OPC UA** (Simulateur des cellules) :
   ```bash
   python src_v2/opcua_server.py
   ```

3. **Démarrer l'interface de supervision Web (FastAPI)** :
   Ouvrez un autre terminal et exécutez :
   ```bash
   python src_v2/web_server.py
   ```
   Accédez au dashboard sur **https://127.0.0.1:8443** (Acceptez le certificat auto-signé).

### Scripts PowerShell (démo & qualité)

```powershell
# Lance les deux serveurs (OPC UA + Web) + génère les certs si besoin
./run_servers.ps1

# Lance les preuves qualité (tests, coverage, lint, format)
./run_quality.ps1
```

## Architecture V2

- `src_v2/opcua_server.py` : Serveur OPC UA (Python asyncua) simulant plusieurs robots de production.
- `src_v2/web_server.py` : Serveur FastAPI sécurisé par SSL, exposant l'API et le frontend de supervision.
- `certs/` : Dossier contenant les clés privées et certificats (générés localement).
- `docs_v2/` : Documentation d'architecture et de conformité.

## Qualité (PEP8, tests, sécurité)

Commandes utiles (à lancer à la racine du projet) :

```bash
# Tests unitaires
python -m pytest

# Couverture (le serveur OT opcua_server.py est exclu car boucle infinie)
python -m pytest --cov=src_v2 --cov-report=term-missing

# Lint PEP8 / qualité
python -m ruff check .

# Formatage
python -m black --check .
python -m black .
```
