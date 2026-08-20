"""OT access layer for Smart Robotic Cell V2.

Isole toute la logique de lecture/écriture OPC UA (couche "Service" au sens
de la Compétence 3 — Concevoir une architecture fiable) du reste de
l'application. web_server.py (couche API/Contrôleur) importe et appelle les
fonctions de ce module sans jamais manipuler directement un client OPC UA.

Extrait de web_server.py dans le cadre du refactoring identifié comme axe
d'amélioration en Compétence 9 — Code propre et maintenable (Clean Code) :
les fonctions fetch_opcua_data() et le corps de l'endpoint /api/simu/action
étaient auparavant définies directement dans le contrôleur, mélangeant accès
OT et logique HTTP.
"""

from __future__ import annotations

import logging
from typing import Any

from asyncua import Client, ua

LOGGER = logging.getLogger(__name__)

OPCUA_URL = "opc.tcp://127.0.0.1:4840/freeopcua/server/"
NAMESPACE_URI = "http://smart-robotic-cell.local"

# Champs lus systématiquement pour chaque cellule (clé exposée -> nom du noeud OPC UA).
CELL_NODE_FIELDS: dict[str, str] = {
    "state": "Etat",
    "fault": "EnDefaut",
    "type": "TypeRobot",
    "name": "NomCellule",
    "ip": "AdresseIP",
    "progress": "ProgressionCycle",
    "alarms": "AlarmesActives",
    "maint_req": "MaintenanceRequise",
    "time_to_maint": "HeuresAvantMaintenance",
    "pneumatic_pressure": "PressionPneumatique",
    "pneumatic_state": "BridageActif",
    "lubrix_level": "NiveauLubrifiant",
}

# Groupes de diagnostics optionnels : si un noeud du groupe est absent (matériel
# plus ancien / non simulé), tout le groupe retombe sur des valeurs par défaut
# plutôt que de faire échouer la lecture de la cellule entière.
OPTIONAL_DIAGNOSTIC_GROUPS: list[dict[str, str]] = [
    {"temp_axes": "TemperatureAxes", "vibration": "NiveauVibration"},
    {"speed": "VitesseCycle"},
]

AXIS_COUNT = 6
# Champs lus pour chaque axe moteur (clé exposée -> nom du noeud OPC UA, enfant
# de l'objet Axe_N).
AXIS_NODE_FIELDS: dict[str, str] = {
    "temperature_c": "Temperature",
    "courant_a": "Courant",
    "couple_nm": "Couple",
}


async def _read_node_value(cell_node: Any, idx: int, node_name: str) -> Any:
    """Lit la valeur d'un noeud OPC UA enfant de ``cell_node``."""

    child = await cell_node.get_child(f"{idx}:{node_name}")
    return await child.read_value()


async def _read_optional_group(
    cell_node: Any, idx: int, fields: dict[str, str], cell_id: int
) -> dict[str, float]:
    """Lit un groupe de noeuds de diagnostic optionnels.

    Retourne 0.0 pour chaque champ du groupe si l'un des noeuds est absent,
    plutôt que de propager l'exception (les diagnostics avancés ne sont pas
    disponibles sur toutes les cellules simulées).
    """

    try:
        return {
            key: await _read_node_value(cell_node, idx, name)
            for key, name in fields.items()
        }
    except Exception:
        LOGGER.debug(
            "Optional diagnostics nodes missing for cell %s: %s",
            cell_id,
            list(fields.values()),
        )
        return dict.fromkeys(fields, 0.0)


async def fetch_opcua_data() -> list[dict[str, Any]]:
    """Fetch cell states from the OPC UA server.

    Returns an empty list on connection errors.
    """

    try:
        async with Client(url=OPCUA_URL) as client:
            idx = await client.get_namespace_index(NAMESPACE_URI)
            supervision_node = await client.nodes.objects.get_child(
                f"{idx}:SupervisionUsine"
            )

            cells_data: list[dict[str, Any]] = []
            for i in range(1, 4):
                cell_node = await supervision_node.get_child(
                    f"{idx}:CelluleRobotique_{i}"
                )

                values: dict[str, Any] = {
                    key: await _read_node_value(cell_node, idx, name)
                    for key, name in CELL_NODE_FIELDS.items()
                }
                for group in OPTIONAL_DIAGNOSTIC_GROUPS:
                    values.update(await _read_optional_group(cell_node, idx, group, i))

                cells_data.append({"id": i, **values})

            return cells_data
    except Exception:
        LOGGER.exception("OPC UA read failure")
        return []


async def fetch_axis_data(cell_id: int) -> list[dict[str, Any]]:
    """Fetch the 6 motor-axis measurements (temperature, current, torque) for
    a single cell from the OPC UA server.

    Returns an empty list on connection errors, matching fetch_opcua_data()'s
    behaviour.
    """

    try:
        async with Client(url=OPCUA_URL) as client:
            idx = await client.get_namespace_index(NAMESPACE_URI)
            cell_node = await client.nodes.objects.get_child(
                [f"{idx}:SupervisionUsine", f"{idx}:CelluleRobotique_{cell_id}"]
            )

            axes_data: list[dict[str, Any]] = []
            for axe_num in range(1, AXIS_COUNT + 1):
                axe_node = await cell_node.get_child(f"{idx}:Axe_{axe_num}")
                values: dict[str, Any] = {
                    key: await _read_node_value(axe_node, idx, name)
                    for key, name in AXIS_NODE_FIELDS.items()
                }
                axes_data.append({"axe": axe_num, **values})

            return axes_data
    except Exception:
        LOGGER.exception("OPC UA axis read failure for cell %s", cell_id)
        return []


async def apply_simulated_action(cell_id: int, action: str) -> None:
    """Applique une action de simulation en écrivant les noeuds OPC UA associés.

    Actions supportées : force_fault, force_maint, ack_fault, ack_maint. Une
    action inconnue est silencieusement ignorée (comportement hérité du POC).
    Les effets de bord applicatifs (mise à jour de active_maintenance_requests,
    écriture de l'historique en base) restent de la responsabilité de
    l'appelant (couche contrôleur) : cette fonction ne touche que l'état OT.
    """

    async with Client(url=OPCUA_URL) as client:
        idx = await client.get_namespace_index(NAMESPACE_URI)
        cell_node = await client.nodes.objects.get_child(
            [f"{idx}:SupervisionUsine", f"{idx}:CelluleRobotique_{cell_id}"]
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
            await (await cell_node.get_child(f"{idx}:ProgressionCycle")).write_value(
                ua.DataValue(ua.Variant(0.0, ua.VariantType.Double))
            )

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

        elif action == "ack_maint":
            # Réaliser la maintenance : remet le compteur à 500
            await (
                await cell_node.get_child(f"{idx}:HeuresAvantMaintenance")
            ).write_value(ua.DataValue(ua.Variant(500, ua.VariantType.Int64)))
            await (await cell_node.get_child(f"{idx}:MaintenanceRequise")).write_value(
                ua.DataValue(ua.Variant(False, ua.VariantType.Boolean))
            )
