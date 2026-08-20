from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

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
    is_maintenance_due,
    report_manual_fault,
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

# Type fixe utilisé pour un défaut signalé manuellement par la Maintenance
# (POST /api/maintenance/report-issue), pour le distinguer d'un défaut
# remonté par l'automate ou déclenché depuis le panneau de simulation.
MAINTENANCE_REPORTED_ISSUE_TYPE = "Anomalie signalée par la Maintenance"


def _active_issues_by_cell(session: Session) -> dict[int, dict[str, object]]:
    """Regroupe par cellule les défauts non résolus (compte + sévérité max).

    Alimente le badge d'alerte affiché directement sur les cartes du
    dashboard (Maintenance ET Opérateur), pour qu'une anomalie signalée par
    la Maintenance — critique ou simple avertissement — soit visible sans
    ouvrir la vue détaillée de la cellule (cf. demande utilisateur round 6).
    """

    issues: dict[int, dict[str, object]] = {}
    for defaut in db.list_defauts(session):
        if defaut.statut == db.DEFAUT_STATUT_RESOLU:
            continue
        entry = issues.setdefault(
            defaut.cellule_id,
            {"count": 0, "max_severity": db.DEFAUT_SEVERITE_AVERTISSEMENT},
        )
        entry["count"] += 1
        if defaut.severite == db.DEFAUT_SEVERITE_CRITIQUE:
            entry["max_severity"] = db.DEFAUT_SEVERITE_CRITIQUE
    return issues


def _has_active_manual_critical_issue(session: Session, cell_id: int) -> bool:
    """Indique si une anomalie CRITIQUE signalée par la Maintenance (via
    /api/maintenance/report-issue) est encore active sur cette cellule.

    Utilisé pour distinguer un défaut OPC UA "réel" (signalé par la
    Maintenance) d'un défaut simulé via le panneau POC (force_fault) : les
    deux écrivent le même état OPC UA (cf. opcua_client._write_fault_state),
    donc seule cette vérification en base permet de savoir si l'action
    "Acquitter le défaut" du POC doit être bloquée (cf. CHG-V2 round 6 :
    "je ne veux pas" que ce bouton lève une alerte critique de Maintenance).
    """

    return any(
        f.type_defaut == MAINTENANCE_REPORTED_ISSUE_TYPE
        and f.severite == db.DEFAUT_SEVERITE_CRITIQUE
        and f.statut != db.DEFAUT_STATUT_RESOLU
        for f in db.list_defauts(session, cellule_id=cell_id)
    )


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


def _static_url(filename: str) -> str:
    """URL d'un fichier de /static suffixée par un paramètre de version basé
    sur sa date de modification sur disque.

    _html_page() ci-dessus met des en-têtes anti-cache sur les PAGES HTML,
    mais pas sur les fichiers de /static (common.js, theme.css) : le
    navigateur peut donc continuer à servir une copie mise en cache de
    common.js même après une mise à jour du code, alors que la page HTML
    (elle, rechargée) appelle déjà de nouvelles fonctions qui n'existent pas
    encore dans cette copie obsolète — ReferenceError silencieuse côté
    client (attrapée par les try/catch existants), qui s'est traduite par
    des courbes et téléchargements qui ne fonctionnaient plus du tout après
    une mise à jour de common.js (cf. CHG-V2-085). Faire varier l'URL dès
    que le fichier change force le navigateur à le re-télécharger.
    """
    path = os.path.join(static_dir, filename)
    try:
        version = int(os.path.getmtime(path))
    except OSError:
        version = 0
    return f"/static/{filename}?v={version}"


templates.env.globals["static_v"] = _static_url

# Appels opérateurs actifs (état transitoire, volontairement en mémoire).
# Valeur = {"username": ..., "message": ...} : le message optionnel saisi par
# l'opérateur doit rester visible sur la demande en attente elle-même (pas
# seulement enfoui dans l'historique une fois la demande traitée) — cf.
# CHG-V2-064.
active_maintenance_requests: dict[int, dict[str, str]] = {}


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
async def get_status(
    current_user: dict = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """API sécurisée renvoyant l'état des cellules depuis OPC UA"""
    data = await fetch_opcua_data()
    return {
        "status": "ok",
        "cells": data,
        "role": current_user["role"],
        "maint_requests": active_maintenance_requests,
        "active_issues": _active_issues_by_cell(session),
        "ssl_cert_expiry": SSL_CERT_EXPIRY,
    }


@app.get("/api/cell/{cell_id}/axes")
async def get_cell_axes(
    cell_id: int,
    current_user: dict = Depends(require_role("MAINTENANCE", "OPERATEUR")),
):
    """Retourne l'état instantané des 6 axes moteurs d'une cellule.

    Ouvert en lecture à l'Opérateur (en plus de la Maintenance) : la vue
    détaillée de la cellule (/cell/{id}) est désormais accessible aux deux
    rôles (cf. décision utilisateur round 6 — "il faudrait que les
    opérateurs aient accès aux vues détaillées des cellules"). Reste en
    lecture seule : les actions de résolution restent réservées à la
    Maintenance.
    """
    axes = await fetch_axis_data(cell_id)
    return {"status": "ok", "cell_id": cell_id, "axes": axes}


@app.get("/api/cell/{cell_id}/measures")
async def get_cell_measures(
    cell_id: int,
    hours: int = 24,
    current_user: dict = Depends(require_role("MAINTENANCE", "OPERATEUR")),
    session: Session = Depends(get_session),
):
    """Retourne l'historique persisté (axes + cellule) sur les N dernières heures."""
    # Heure locale, cohérente avec db.py::horodatage (voir commentaire db.py
    # sur le choix local vs UTC) : comparer un "since" en UTC à des
    # horodatages stockés en heure locale aurait décalé la fenêtre filtrée.
    since = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
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
    fault_status: str | None = None,
    since: str | None = None,
    until: str | None = None,
    current_user: dict = Depends(require_role("MAINTENANCE", "OPERATEUR")),
    session: Session = Depends(get_session),
):
    """Retourne l'historique des défauts, du plus récent au plus ancien.

    ``fault_status`` filtre sur un statut exact ("actif" / "en_cours" /
    "resolu", cf. db.DEFAUT_STATUTS) : un défaut "actif" représente aussi une
    demande d'intervention non encore prise en charge (cf. CHG-V2-057).
    ``since``/``until`` filtrent sur une plage de dates (bornes incluses).
    Nommé ``fault_status`` (et non ``status``) pour ne pas entrer en
    collision avec la clé "status" ("ok") de l'enveloppe de réponse.

    Ouvert en lecture à l'Opérateur (en plus de la Maintenance) — il doit
    pouvoir consulter l'historique des défauts de ses cellules, sans limite
    de cellule ou de date (cf. CHG-V2-066). Reste en lecture seule : les
    actions d'intervention restent réservées à la Maintenance.
    """
    faults = db.list_defauts(
        session, cellule_id=cell_id, statut=fault_status, since=since, until=until
    )
    return {
        "status": "ok",
        "faults": [
            {
                "id": f.id,
                "time": f.horodatage,
                "cell_id": f.cellule_id,
                "type": f.type_defaut,
                "severity": f.severite,
                "description": f.description,
                "fault_status": f.statut,
            }
            for f in faults
        ],
    }


@app.post("/api/maintenance/intervention")
async def record_maintenance_intervention(
    defaut_id: int,
    probleme_resolu: bool,
    notes: str = "",
    current_user: dict = Depends(require_role("MAINTENANCE")),
    session: Session = Depends(get_session),
):
    """Enregistre une intervention de Maintenance sur un défaut précis.

    Choix explicite de la Maintenance (menu déroulant côté frontend, limité
    aux défauts actifs/en cours de la cellule concernée) plutôt qu'une
    résolution implicite du "dernier défaut" : trace qui est intervenu, sur
    quel défaut exactement, et si le problème est résolu ou toujours actif.
    Répercute automatiquement le résultat sur le statut du défaut.
    """
    try:
        entry = db.add_maintenance_intervention(
            session,
            username_auteur=current_user["username"],
            defaut_id=defaut_id,
            notes=notes,
            probleme_resolu=probleme_resolu,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if probleme_resolu:
        # Le problème est résolu : si l'opérateur avait signalé une demande
        # d'aide active pour cette cellule, elle n'a plus lieu d'être (même
        # comportement que les actions "ack_fault"/"ack_maint" du panneau de
        # simulation).
        active_maintenance_requests.pop(entry.cellule_id, None)

        # Si le défaut résolu est une anomalie critique signalée par la
        # Maintenance elle-même (cf. /api/maintenance/report-issue), elle
        # avait mis la cellule à l'arrêt côté OPC UA (CHG-V2-070) : on lève
        # cet état seulement si aucune AUTRE anomalie critique signalée par
        # la Maintenance n'est encore active sur cette même cellule, pour ne
        # pas rouvrir à tort une cellule qui a encore un problème en cours.
        resolved_defaut = db.get_defaut(session, defaut_id)
        if (
            resolved_defaut is not None
            and resolved_defaut.type_defaut == MAINTENANCE_REPORTED_ISSUE_TYPE
            and resolved_defaut.severite == db.DEFAUT_SEVERITE_CRITIQUE
        ):
            cell_still_critical = _has_active_manual_critical_issue(
                session, resolved_defaut.cellule_id
            )
            if not cell_still_critical:
                try:
                    await apply_simulated_action(
                        resolved_defaut.cellule_id, "ack_fault"
                    )
                except Exception:
                    LOGGER.exception(
                        "Impossible de lever l'état de défaut OPC UA après "
                        "résolution du défaut #%s",
                        resolved_defaut.id,
                    )

    return {"status": "ok", "cell_id": entry.cellule_id}


@app.post("/api/maintenance/request")
async def request_maintenance(
    cell_id: int,
    message: str = "",
    current_user: dict = Depends(require_role("OPERATEUR")),
    session: Session = Depends(get_session),
):
    """Permet à un Opérateur de demander une maintenance.

    ``message`` est un commentaire libre optionnel saisi par l'opérateur
    (ex. nature du problème observé) — répercuté dans l'historique ET gardé
    sur la demande active elle-même, pour rester visible tant qu'elle n'est
    pas prise en charge (cf. CHG-V2-064).
    """
    # On ajoute la cellule aux requêtes actives
    active_maintenance_requests[cell_id] = {
        "username": current_user["username"],
        "message": message,
    }

    action = f"Demande d'intervention sur Cellule {cell_id}"
    if message:
        action = f"{action}. Message : {message}"

    db.add_history_entry(
        session,
        action=action,
        username_auteur=current_user["username"],
        cellule_id=cell_id,
    )
    return {"status": "ok", "msg": "Demande enregistrée"}


@app.post("/api/maintenance/acknowledge-request")
async def acknowledge_maintenance_request(
    cell_id: int,
    message: str = "",
    current_user: dict = Depends(require_role("MAINTENANCE")),
    session: Session = Depends(get_session),
):
    """Permet à la Maintenance de prendre en charge une demande générique.

    Une demande générique (bouton "Demander une intervention" côté
    opérateur, cf. /api/maintenance/request) n'est liée à aucun défaut
    précis — elle vit uniquement dans ``active_maintenance_requests``. Ce
    endpoint la retire de la liste des demandes actives et journalise la
    prise en charge, sans toucher à un éventuel défaut (voir
    /api/maintenance/intervention pour ce cas). ``message`` (optionnel) est
    le commentaire de la Maintenance sur son intervention ; le message
    éventuel de l'opérateur (saisi à la demande) est repris dans la même
    ligne pour garder une trace complète de l'échange (cf. CHG-V2-064).
    """
    request_info = active_maintenance_requests.pop(cell_id, None)
    if request_info is None:
        raise HTTPException(
            status_code=404, detail="Aucune demande active pour cette cellule"
        )

    action = f"Prise en charge de la demande d'intervention sur Cellule {cell_id}"
    original_message = (
        request_info.get("message") if isinstance(request_info, dict) else None
    )
    if original_message:
        action += f" (message opérateur : {original_message})"
    if message:
        action += f". Notes maintenance : {message}"

    db.add_history_entry(
        session,
        action=action,
        username_auteur=current_user["username"],
        cellule_id=cell_id,
    )
    return {"status": "ok"}


@app.post("/api/maintenance/report-issue")
async def report_issue(
    cell_id: int,
    description: str,
    severity: str = "avertissement",
    current_user: dict = Depends(require_role("MAINTENANCE")),
    session: Session = Depends(get_session),
):
    """Permet à la Maintenance de signaler elle-même un problème sur une
    cellule, sans attendre un défaut OPC UA ou un appel opérateur.

    Crée un défaut réel (statut "actif") via ``db.add_defaut`` — visible
    partout où les défauts le sont déjà (historique des défauts, panneau
    "en attente"), avec un type fixe permettant de le distinguer d'un défaut
    remonté par l'automate (cf. CHG-V2-065).
    """
    if severity not in db.DEFAUT_SEVERITES:
        raise HTTPException(status_code=422, detail="Sévérité invalide")
    if not description.strip():
        raise HTTPException(status_code=422, detail="Description requise")

    defaut = db.add_defaut(
        session,
        cellule_id=cell_id,
        type_defaut=MAINTENANCE_REPORTED_ISSUE_TYPE,
        severite=severity,
        description=description.strip(),
    )

    if severity == db.DEFAUT_SEVERITE_CRITIQUE:
        # Une anomalie critique signalée par la Maintenance doit mettre la
        # cellule à l'arrêt comme un défaut réel (cf. décision utilisateur
        # CHG-V2-070). Résilient à une indisponibilité ponctuelle de l'OPC
        # UA : le défaut est déjà persisté en base, source de vérité pour
        # l'historique/l'audit, même si l'état OT n'a pas pu être répercuté.
        try:
            await report_manual_fault(cell_id, description.strip())
        except Exception:
            LOGGER.exception(
                "Impossible de répercuter l'anomalie critique #%s sur l'état OPC UA",
                defaut.id,
            )

    return {"status": "ok", "id": defaut.id}


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
        if action == "ack_maint" and not await is_maintenance_due(cell_id):
            # CHG-V2-070 : "Faire la maintenance" / "Maintenance effectuée"
            # ne doit fonctionner que quand le compteur a réellement atteint
            # 0 — avant, ce bouton "réalisait" la maintenance à tout moment,
            # y compris pour masquer à tort un arrêt en cours.
            raise HTTPException(
                status_code=409,
                detail=(
                    "La maintenance n'est pas encore requise sur cette "
                    "cellule (le compteur n'a pas atteint 0)."
                ),
            )

        blocked_ack_fault = action == "ack_fault" and _has_active_manual_critical_issue(
            session, cell_id
        )
        if blocked_ack_fault:
            # CHG-V2 round 6 : une anomalie CRITIQUE signalée par la
            # Maintenance (report-issue) ne doit être levée que via le
            # bouton "Intervenir" dédié à cette anomalie (vue détaillée de
            # la cellule), jamais par "Acquitter le défaut" du panneau de
            # simulation POC — réservé aux défauts de test (force_fault).
            raise HTTPException(
                status_code=409,
                detail=(
                    "Cette cellule a une anomalie critique signalée par la "
                    'Maintenance : utilisez le bouton "Intervenir" dédié '
                    "dans la vue détaillée de la cellule, pas l'acquittement "
                    "du panneau de simulation."
                ),
            )

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
            # Ne PAS toucher à active_maintenance_requests ici : une demande
            # générique d'intervention lancée par l'Opérateur (bouton
            # "Demander une intervention") est indépendante du compteur de
            # maintenance préventive — clore la maintenance (compteur à 0)
            # ne signifie pas que la demande de l'opérateur a été traitée
            # (cf. bug signalé round 6 : "ça dit que j'ai aussi fait la
            # demande de maintenance de l'opérateur ce qui n'est pas
            # forcément le cas"). Cette demande reste visible tant qu'elle
            # n'est pas explicitement prise en charge via
            # /api/maintenance/acknowledge-request.
            db.add_history_entry(
                session,
                action=f"Intervention terminée sur Cellule {cell_id}",
                username_auteur=current_user["username"],
                cellule_id=cell_id,
            )

        return {"status": "ok"}
    except HTTPException:
        # Ne pas re-envelopper une HTTPException volontaire (ex. 409 ci-dessus
        # si la maintenance n'est pas encore due) dans un 500 générique.
        raise
    except Exception as exc:
        LOGGER.exception("Simulation action failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/maintenance/history")
async def get_maintenance_history(
    cell_id: int | None = None,
    since: str | None = None,
    until: str | None = None,
    current_user: dict = Depends(require_role("MAINTENANCE", "OPERATEUR")),
    session: Session = Depends(get_session),
):
    """Retourne l'historique de maintenance (persisté en base SQLite).

    Filtre sur ``cell_id``/``since``/``until`` si fournis (utilisé par la
    page de détail d'une cellule et par les filtres de la page dédiée
    /historique-maintenance), sinon retourne l'historique complet.

    Un Opérateur ne voit que ses propres demandes (lignes qu'il a
    lui-même créées) : le filtre par auteur est forcé côté serveur dès que
    le rôle n'est pas MAINTENANCE, sans dépendre d'un paramètre envoyé par
    le client (cf. CHG-V2-066).
    """
    username_filter = (
        None if current_user["role"] == "MAINTENANCE" else current_user["username"]
    )
    history = [
        {
            "time": entry.horodatage,
            "action": entry.action,
            "user": entry.username_auteur,
            "cell_id": entry.cellule_id,
            "defaut_id": entry.defaut_id,
            "probleme_resolu": entry.probleme_resolu,
        }
        for entry in db.list_history(
            session,
            cellule_id=cell_id,
            since=since,
            until=until,
            username_auteur=username_filter,
        )
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
