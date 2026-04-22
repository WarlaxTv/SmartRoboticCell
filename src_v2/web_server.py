from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from typing import Any

import uvicorn
from asyncua import Client, ua
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.templating import Jinja2Templates

from src_v2.security import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    USERS_DB,
    create_access_token,
    get_current_user,
    require_role,
    verify_password,
)

LOGGER = logging.getLogger(__name__)

app = FastAPI(title="Supervision Smart Robotic Cell V2 (NF EN 9100)")

# Configuration des templates HTML
templates_dir = os.path.join(os.path.dirname(__file__), "templates")
os.makedirs(templates_dir, exist_ok=True)
templates = Jinja2Templates(directory=templates_dir)

# Historique de maintenance simulé
maintenance_history: list[dict[str, Any]] = []
# Appels opérateurs actifs
active_maintenance_requests: dict[int, str] = {}  # {cell_id: "username"}

# OPC UA Client configuration
OPCUA_URL = "opc.tcp://127.0.0.1:4840/freeopcua/server/"

async def fetch_opcua_data() -> list[dict[str, Any]]:
    """Fetch cell states from the OPC UA server.

    Returns an empty list on connection errors.
    """

    try:
        async with Client(url=OPCUA_URL) as client:
            idx = await client.get_namespace_index("http://smart-robotic-cell.local")
            supervision_node = await client.nodes.objects.get_child(
                f"{idx}:SupervisionUsine"
            )

            cells_data: list[dict[str, Any]] = []
            for i in range(1, 4):
                cell_node = await supervision_node.get_child(
                    f"{idx}:CelluleRobotique_{i}"
                )

                state = await (await cell_node.get_child(f"{idx}:Etat")).read_value()
                fault = await (
                    await cell_node.get_child(f"{idx}:EnDefaut")
                ).read_value()
                robot_type = await (
                    await cell_node.get_child(f"{idx}:TypeRobot")
                ).read_value()
                cell_name = await (
                    await cell_node.get_child(f"{idx}:NomCellule")
                ).read_value()
                ip = await (
                    await cell_node.get_child(f"{idx}:AdresseIP")
                ).read_value()
                progress = await (
                    await cell_node.get_child(f"{idx}:ProgressionCycle")
                ).read_value()
                alarms = await (
                    await cell_node.get_child(f"{idx}:AlarmesActives")
                ).read_value()
                maint_req = await (
                    await cell_node.get_child(f"{idx}:MaintenanceRequise")
                ).read_value()
                time_to_maint = await (
                    await cell_node.get_child(f"{idx}:HeuresAvantMaintenance")
                ).read_value()

                pneumatic_pressure = await (
                    await cell_node.get_child(f"{idx}:PressionPneumatique")
                ).read_value()
                pneumatic_state = await (
                    await cell_node.get_child(f"{idx}:BridageActif")
                ).read_value()
                lubrix_level = await (
                    await cell_node.get_child(f"{idx}:NiveauLubrifiant")
                ).read_value()

                temp_axes = 0.0
                vibration = 0.0
                try:
                    temp_axes = await (
                        await cell_node.get_child(f"{idx}:TemperatureAxes")
                    ).read_value()
                    vibration = await (
                        await cell_node.get_child(f"{idx}:NiveauVibration")
                    ).read_value()
                except Exception:
                    LOGGER.debug("Diagnostics nodes missing for cell %s", i)

                speed = 0.0
                try:
                    speed = await (
                        await cell_node.get_child(f"{idx}:VitesseBras")
                    ).read_value()
                except Exception:
                    LOGGER.debug("Speed node missing for cell %s", i)

                cells_data.append(
                    {
                        "id": i,
                        "name": cell_name,
                        "type": robot_type,
                        "ip": ip,
                        "state": state,
                        "fault": fault,
                        "progress": progress,
                        "alarms": alarms,
                        "maint_req": maint_req,
                        "time_to_maint": time_to_maint,
                        "pneumatic_pressure": pneumatic_pressure,
                        "pneumatic_state": pneumatic_state,
                        "lubrix_level": lubrix_level,
                        "temp_axes": temp_axes,
                        "vibration": vibration,
                        "speed": speed,
                    }
                )

            return cells_data
    except Exception:
        LOGGER.exception("OPC UA read failure")
        return []

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    """Serve the supervision dashboard (Read-Only)."""
    response = templates.TemplateResponse(request, "dashboard.html")
    # Désactivation du cache navigateur pour forcer la mise à jour visuelle
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

@app.post("/token")
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    """OAuth2 password flow endpoint returning a JWT."""

    user_dict = USERS_DB.get(form_data.username)
    if not user_dict or not verify_password(
        form_data.password, user_dict["password_hash"]
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Identifiant ou mot de passe incorrect",
            headers={"WWW-Authenticate": "Bearer"},
        )
    role = user_dict["role"]

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
    }

@app.post("/api/maintenance/request")
async def request_maintenance(
    cell_id: int,
    current_user: dict = Depends(require_role("OPERATEUR")),
):
    """Permet à un Opérateur de demander une maintenance."""
    # On ajoute la cellule aux requêtes actives
    active_maintenance_requests[cell_id] = current_user["username"]

    maintenance_history.append(
        {
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "action": f"Demande d'intervention sur Cellule {cell_id}",
            "user": current_user["username"],
        }
    )
    return {"status": "ok", "msg": "Demande enregistrée"}

@app.post("/api/simu/action")
async def simu_action(
    cell_id: int,
    action: str,
    current_user: dict = Depends(require_role("MAINTENANCE")),
):
    """API secrète pour le POC permettant de forcer des états sur le serveur OPC UA."""
    try:
        async with Client(url=OPCUA_URL) as client:
            idx = await client.get_namespace_index("http://smart-robotic-cell.local")
            cell_node = await client.nodes.objects.get_child(
                [
                    f"{idx}:SupervisionUsine",
                    f"{idx}:CelluleRobotique_{cell_id}",
                ]
            )

            if action == "force_fault":
                await (await cell_node.get_child(f"{idx}:EnDefaut")).write_value(
                    ua.DataValue(ua.Variant(True, ua.VariantType.Boolean))
                )
                await (await cell_node.get_child(f"{idx}:Etat")).write_value(
                    ua.DataValue(ua.Variant("DEFAUT", ua.VariantType.String))
                )
                await (await cell_node.get_child(f"{idx}:AlarmesActives")).write_value(
                    ua.DataValue(
                        ua.Variant("ERR-MANUELLE-SIMULATION", ua.VariantType.String)
                    )
                )
                await (
                    await cell_node.get_child(f"{idx}:ProgressionCycle")
                ).write_value(ua.DataValue(ua.Variant(0.0, ua.VariantType.Double)))

            elif action == "force_maint":
                # On met le compteur à 9 heures pour déclencher l'alerte
                await (
                    await cell_node.get_child(f"{idx}:HeuresAvantMaintenance")
                ).write_value(ua.DataValue(ua.Variant(9, ua.VariantType.Int64)))

            elif action == "ack_fault":
                await (await cell_node.get_child(f"{idx}:EnDefaut")).write_value(
                    ua.DataValue(ua.Variant(False, ua.VariantType.Boolean))
                )
                await (await cell_node.get_child(f"{idx}:Etat")).write_value(
                    ua.DataValue(ua.Variant("EN_PRODUCTION", ua.VariantType.String))
                )
                await (await cell_node.get_child(f"{idx}:AlarmesActives")).write_value(
                    ua.DataValue(ua.Variant("", ua.VariantType.String))
                )
                if cell_id in active_maintenance_requests:
                    del active_maintenance_requests[cell_id]

            elif action == "ack_maint":
                # Réaliser la maintenance : remet le compteur à 500
                # et efface les demandes
                await (
                    await cell_node.get_child(f"{idx}:HeuresAvantMaintenance")
                ).write_value(ua.DataValue(ua.Variant(500, ua.VariantType.Int64)))
                await (
                    await cell_node.get_child(f"{idx}:MaintenanceRequise")
                ).write_value(ua.DataValue(ua.Variant(False, ua.VariantType.Boolean)))
                if cell_id in active_maintenance_requests:
                    del active_maintenance_requests[cell_id]
                maintenance_history.append(
                    {
                        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "action": f"Intervention terminée sur Cellule {cell_id}",
                        "user": current_user["username"],
                    }
                )

        return {"status": "ok"}
    except Exception as exc:
        LOGGER.exception("Simulation action failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

@app.get("/api/maintenance/history")
async def get_maintenance_history(
    current_user: dict = Depends(require_role("MAINTENANCE")),
):
    """Permet à la Maintenance de voir l'historique."""
    return {"status": "ok", "history": maintenance_history}

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
