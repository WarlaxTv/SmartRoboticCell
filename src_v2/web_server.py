from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import uvicorn
from cryptography import x509
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlmodel import Session

from src_v2 import db
from src_v2.db import get_session
from src_v2.opcua_client import (
    apply_simulated_action,
    fetch_axis_data,
    fetch_opcua_data,
)
from src_v2.security import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    create_access_token,
    get_current_user,
    require_role,
    verify_password,
)

LOGGER = logging.getLogger(__name__)

# Intervalle d'échantillonnage de la tâche de fond (secondes) qui persiste les
# mesures OPC UA (axes + cellule) en base pour constituer un historique.
# Réduit de 60 à 15 secondes (demande utilisateur : courbes en direct trop
# clairsemées). Le simulateur OPC UA lui-même évolue chaque seconde
# (opcua_server.py), donc cette valeur ne fait que choisir la fréquence à
# laquelle cet état est *persisté* pour l'historique.
SAMPLING_INTERVAL_SECONDS = 15

FAULT_TYPE_MANUAL = "Défaut déclenché manuellement (simulation)"


def _load_ssl_cert_expiry() -> str | None:
    """Lit la date d'expiration réelle du certificat SSL du serveur.

    Retourne None si le certificat est introuvable ou illisible : le frontend
    affiche alors une mention neutre plutôt qu'une date fictive.
    """

    cert_base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cert_file_path = os.path.join(cert_base_dir, "certs", "web_cert.pem")
    try:
        with open(cert_file_path, "rb") as cert_file:
            cert = x509.load_pem_x509_certificate(cert_file.read())
        expiry = getattr(cert, "not_valid_after_utc", None) or cert.not_valid_after
        return expiry.strftime("%Y-%m-%d")
    except Exception:
        # Résilience volontaire : un certificat absent/illisible ne doit pas
        # empêcher le démarrage du serveur, cf. le même choix déjà fait pour
        # fetch_opcua_data() dans opcua_client.py.
        LOGGER.warning(
            "Impossible de lire l'expiration du certificat SSL (%s)", cert_file_path
        )
        return None


async def _sampling_loop() -> None:
    """Échantillonne périodiquement les mesures OPC UA (axes + cellule) en base.

    Tourne en tâche de fond pendant toute la durée de vie du serveur, pour
    constituer un historique exploitable (page de détail, courbes de
    tendance) plutôt qu'un instantané perdu à chaque rafraîchissement du
    dashboard. Une erreur ponctuelle (OPC UA indisponible) ne doit pas
    arrêter la boucle : elle est journalisée puis on retente au tour suivant.
    """

    while True:
        try:
            cells = await fetch_opcua_data()
            with Session(db.engine) as session:
                for cell in cells:
                    db.add_cell_measure(
                        session,
                        cellule_id=cell["id"],
                        pneumatic_pressure_bar=cell["pneumatic_pressure"],
                        lubrix_level_pct=cell["lubrix_level"],
                    )
                    for axe in await fetch_axis_data(cell["id"]):
                        db.add_axis_measure(
                            session,
                            cellule_id=cell["id"],
                            axe=axe["axe"],
                            temperature_c=axe["temperature_c"],
                            courant_a=axe["courant_a"],
                            couple_nm=axe["couple_nm"],
                        )
        except Exception:
            # Résilience volontaire : une itération en échec (OPC UA
            # momentanément indisponible) ne doit pas arrêter la boucle de
            # fond pour toute la durée de vie du serveur.
            LOGGER.exception("Échec d'une itération de la boucle d'échantillonnage")
        await asyncio.sleep(SAMPLING_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Démarre/arrête la tâche de fond d'échantillonnage avec le serveur."""

    task = asyncio.create_task(_sampling_loop())
    try:
        yield
    finally:
        task.cancel()


app = FastAPI(title="Supervision Smart Robotic Cell V2 (NF EN 9100)", lifespan=lifespan)

# Initialisation de la base SQLite (comptes + historique persistés).
# Idempotent : peut être appelée à chaque import (y compris sous pytest).
db.init_db()

SSL_CERT_EXPIRY = _load_ssl_cert_expiry()

# Configuration des templates HTML
templates_dir = os.path.join(os.path.dirname(__file__), "templates")
os.makedirs(templates_dir, exist_ok=True)
templates = Jinja2Templates(directory=templates_dir)

# Assets statiques (Chart.js) servis localement plutôt que depuis un CDN
# externe : un poste de supervision industrielle peut tourner sur un réseau
# sans accès Internet sortant (voire volontairement cloisonné), et un CDN
# indisponible ne doit jamais empêcher l'affichage des courbes de tendance.
static_dir = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Appels opérateurs actifs (état transitoire, volontairement en mémoire)
active_maintenance_requests: dict[int, str] = {}  # {cell_id: "username"}


def _html_page(request: Request, template_name: str, context: dict | None = None):
    """Rend un template HTML avec les en-têtes anti-cache communs à toutes les
    pages du site (le dashboard doit toujours refléter l'état réel du système,
    jamais une version mise en cache par le navigateur).
    """

    response = templates.TemplateResponse(request, template_name, context or {})
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    """Serve the supervision dashboard (Read-Only)."""
    return _html_page(request, "dashboard.html")


@app.get("/cell/{cell_id}", response_class=HTMLResponse)
async def read_cell_detail(request: Request, cell_id: int):
    """Serve the per-cell detail page (courbes, mesures par axe)."""
    return _html_page(request, "cell_detail.html", {"cell_id": cell_id})


@app.get("/historique-maintenance", response_class=HTMLResponse)
async def read_maintenance_history_page(request: Request):
    """Serve la page dédiée à l'historique des interventions de maintenance."""
    return _html_page(request, "maintenance_history.html")


@app.get("/historique-pannes", response_class=HTMLResponse)
async def read_fault_history_page(request: Request):
    """Serve la page dédiée à l'historique des défauts (toutes cellules)."""
    return _html_page(request, "fault_history.html")


@app.get("/donnees", response_class=HTMLResponse)
async def read_data_comparison_page(request: Request):
    """Serve la page de comparaison des données entre les 3 cellules."""
    return _html_page(request, "data_comparison.html")


@app.post("/token")
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    session: Session = Depends(get_session),
):
    """OAuth2 password flow endpoint returning a JWT."""

    user = db.get_user(session, form_data.username)
    if not user or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Identifiant ou mot de passe incorrect",
            headers={"WWW-Authenticate": "Bearer"},
        )
    role = user.role

    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": form_data.username, "role": role},
        expires_delta=access_token_expires,
    )
    return {"access_token": access_token, "token_type": "bearer", "role": role}


@app.get("/api/status")
async def get_status(current_user: dict = Depends(get_current_user)):
    """API sécurisée renvoyant l'état des cellules depuis OPC UA"""
    data = await fetch_opcua_data()
    return {
        "status": "ok",
        "cells": data,
        "role": current_user["role"],
        "maint_requests": active_maintenance_requests,
        "ssl_cert_expiry": SSL_CERT_EXPIRY,
    }


@app.get("/api/cell/{cell_id}/axes")
async def get_cell_axes(
    cell_id: int,
    current_user: dict = Depends(require_role("MAINTENANCE")),
):
    """Retourne l'état instantané des 6 axes moteurs d'une cellule.

    Réservé au rôle MAINTENANCE, comme le reste des diagnostics avancés déjà
    exposés uniquement à ce rôle sur le dashboard principal.
    """
    axes = await fetch_axis_data(cell_id)
    return {"status": "ok", "cell_id": cell_id, "axes": axes}


@app.get("/api/cell/{cell_id}/measures")
async def get_cell_measures(
    cell_id: int,
    hours: int = 24,
    current_user: dict = Depends(require_role("MAINTENANCE")),
    session: Session = Depends(get_session),
):
    """Retourne l'historique persisté (axes + cellule) sur les N dernières heures."""
    since = (datetime.now(UTC) - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
    axis_measures = db.list_axis_measures(session, cell_id, since)
    cell_measures = db.list_cell_measures(session, cell_id, since)
    return {
        "status": "ok",
        "cell_id": cell_id,
        "axis_measures": [
            {
                "time": m.horodatage,
                "axe": m.axe,
                "temperature_c": m.temperature_c,
                "courant_a": m.courant_a,
                "couple_nm": m.couple_nm,
            }
            for m in axis_measures
        ],
        "cell_measures": [
            {
                "time": m.horodatage,
                "pneumatic_pressure_bar": m.pneumatic_pressure_bar,
                "lubrix_level_pct": m.lubrix_level_pct,
            }
            for m in cell_measures
        ],
    }


@app.get("/api/faults/history")
async def get_faults_history(
    cell_id: int | None = None,
    current_user: dict = Depends(require_role("MAINTENANCE")),
    session: Session = Depends(get_session),
):
    """Retourne l'historique des défauts, du plus récent au plus ancien."""
    faults = db.list_defauts(session, cellule_id=cell_id)
    return {
        "status": "ok",
        "faults": [
            {
                "time": f.horodatage,
                "cell_id": f.cellule_id,
                "type": f.type_defaut,
                "severity": f.severite,
                "description": f.description,
                "resolved": f.resolu,
            }
            for f in faults
        ],
    }


@app.post("/api/maintenance/request")
async def request_maintenance(
    cell_id: int,
    current_user: dict = Depends(require_role("OPERATEUR")),
    session: Session = Depends(get_session),
):
    """Permet à un Opérateur de demander une maintenance."""
    # On ajoute la cellule aux requêtes actives
    active_maintenance_requests[cell_id] = current_user["username"]

    db.add_history_entry(
        session,
        action=f"Demande d'intervention sur Cellule {cell_id}",
        username_auteur=current_user["username"],
        cellule_id=cell_id,
    )
    return {"status": "ok", "msg": "Demande enregistrée"}


@app.post("/api/simu/action")
async def simu_action(
    cell_id: int,
    action: str,
    current_user: dict = Depends(require_role("MAINTENANCE")),
    session: Session = Depends(get_session),
):
    """API secrète pour le POC permettant de forcer des états sur le serveur OPC UA.

    L'écriture des noeuds OPC UA est déléguée à la couche service
    (src_v2.opcua_client.apply_simulated_action) ; ce contrôleur ne gère que
    les effets applicatifs (état des demandes actives, historique persisté).
    """
    try:
        await apply_simulated_action(cell_id, action)

        if action == "force_fault":
            db.add_defaut(
                session,
                cellule_id=cell_id,
                type_defaut=FAULT_TYPE_MANUAL,
                severite="critique",
                description="Défaut forcé depuis le panneau de simulation (POC).",
            )

        elif action == "ack_fault":
            active_maintenance_requests.pop(cell_id, None)
            db.resolve_last_defaut(session, cell_id)

        elif action == "ack_maint":
            active_maintenance_requests.pop(cell_id, None)
            db.add_history_entry(
                session,
                action=f"Intervention terminée sur Cellule {cell_id}",
                username_auteur=current_user["username"],
                cellule_id=cell_id,
            )

        return {"status": "ok"}
    except Exception as exc:
        LOGGER.exception("Simulation action failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/maintenance/history")
async def get_maintenance_history(
    cell_id: int | None = None,
    current_user: dict = Depends(require_role("MAINTENANCE")),
    session: Session = Depends(get_session),
):
    """Permet à la Maintenance de voir l'historique (persisté en base SQLite).

    Filtre sur ``cell_id`` si fourni (utilisé par la page de détail d'une
    cellule), sinon retourne l'historique de toutes les cellules (page dédiée
    /historique-maintenance).
    """
    history = [
        {
            "time": entry.horodatage,
            "action": entry.action,
            "user": entry.username_auteur,
            "cell_id": entry.cellule_id,
        }
        for entry in db.list_history(session, cellule_id=cell_id)
    ]
    return {"status": "ok", "history": history}


if __name__ == "__main__":
    print("Démarrage du serveur web de supervision (HTTPS)...")

    # Résolution des chemins absolus pour éviter les problèmes
    # selon d'où on lance le script
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    key_path = os.path.join(base_dir, "certs", "web_key.pem")
    cert_path = os.path.join(base_dir, "certs", "web_cert.pem")

    uvicorn.run(
        "src_v2.web_server:app",
        host="0.0.0.0",
        port=8082,  # Nouveau changement de port pour contrer le cache persistant
        ssl_keyfile=key_path,
        ssl_certfile=cert_path,
        reload=os.environ.get("SRC_UVICORN_RELOAD", "0") == "1",
        app_dir=base_dir,
    )
