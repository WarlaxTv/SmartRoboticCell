import asyncio
import logging
import random

from asyncua import Server, ua

from src_v2 import db

logging.basicConfig(level=logging.INFO)
LOGGER = logging.getLogger("asyncua")

AXIS_COUNT = 6

# Bases physiques par axe (index 0 = Axe 1, base du robot ; index 5 = Axe 6,
# poignet). Un robot 6 axes porte plus de charge/chauffe/couple sur ses
# premiers axes (base, épaule) que sur les derniers (poignet) : ces valeurs
# décroissent volontairement de l'axe 1 à l'axe 6.
AXIS_TEMP_IDLE_C = [30.0, 29.0, 28.0, 26.0, 25.0, 24.0]
AXIS_TEMP_RUNNING_C = [55.0, 50.0, 45.0, 38.0, 34.0, 30.0]
AXIS_CURRENT_IDLE_A = [0.6, 0.5, 0.4, 0.3, 0.2, 0.15]
AXIS_CURRENT_RUNNING_A = [9.5, 8.0, 6.0, 3.0, 2.0, 1.2]
# Couple de maintien (gravité) : présent même à l'arrêt, moteurs sous tension.
AXIS_TORQUE_HOLDING_NM = [65.0, 50.0, 30.0, 8.0, 4.0, 1.5]
AXIS_TORQUE_RUNNING_EXTRA_NM = [25.0, 18.0, 10.0, 3.0, 1.5, 0.5]

# Vitesse de cycle (override programme, cf. $OV_PRO KUKA) : une valeur fixe
# parmi les paliers usuels d'exploitation, choisie une fois par cellule au
# démarrage plutôt qu'une vitesse de bras variable en continu.
CYCLE_SPEED_CHOICES = [50.0, 75.0, 100.0]


async def _update_axes(axes: list[dict], is_running: bool) -> float:
    """Fait évoluer les 6 axes d'une cellule d'un pas de simulation.

    La température de chaque axe glisse progressivement vers une cible
    (chauffe en production, refroidissement à l'arrêt) plutôt que de sauter
    brutalement, pour des courbes exploitables sur la page de détail.
    Retourne la température maximale des 6 axes (utilisée pour l'agrégat
    cellule TemperatureAxes).
    """

    max_temp = 0.0
    for axis_idx, axis in enumerate(axes):
        current_temp = await axis["temp"].read_value()
        target_temp = (
            AXIS_TEMP_RUNNING_C[axis_idx] if is_running else AXIS_TEMP_IDLE_C[axis_idx]
        )
        new_temp = current_temp + (target_temp - current_temp) * 0.15
        new_temp += random.uniform(-0.3, 0.3)
        await axis["temp"].write_value(float(round(new_temp, 1)))
        max_temp = max(max_temp, new_temp)

        if is_running:
            courant = AXIS_CURRENT_RUNNING_A[axis_idx] + random.uniform(-0.4, 0.4)
            couple = (
                AXIS_TORQUE_HOLDING_NM[axis_idx]
                + AXIS_TORQUE_RUNNING_EXTRA_NM[axis_idx] * random.uniform(0.6, 1.0)
                + random.uniform(-1.0, 1.0)
            )
        else:
            courant = AXIS_CURRENT_IDLE_A[axis_idx] + random.uniform(-0.05, 0.05)
            couple = AXIS_TORQUE_HOLDING_NM[axis_idx] + random.uniform(-0.5, 0.5)

        await axis["courant"].write_value(float(round(max(courant, 0.0), 2)))
        await axis["couple"].write_value(float(round(max(couple, 0.0), 1)))

    return max_temp


async def main() -> None:
    """Démarre le serveur OPC UA simulateur et boucle indéfiniment.

    Expose trois cellules robotiques simulées (Etat, défauts, diagnostics)
    et fait évoluer leurs variables toutes les secondes pour imiter un
    comportement de production réel (couche OT, indépendante de web_server.py).
    """
    # Configuration du serveur
    server = Server()
    await server.init()

    server.set_endpoint("opc.tcp://0.0.0.0:4840/freeopcua/server/")

    # Sécurité avec certificats SSL
    try:
        await server.load_certificate("certs/opcua_cert.pem")
        await server.load_private_key("certs/opcua_key.pem")
        # On autorise None (pas de chiffrement) pour permettre au client web
        # de se connecter facilement en dev
        server.set_security_policy(
            [
                ua.SecurityPolicyType.NoSecurity,
                ua.SecurityPolicyType.Basic256Sha256_SignAndEncrypt,
                ua.SecurityPolicyType.Basic256Sha256_Sign,
            ]
        )
    except Exception as exc:
        LOGGER.warning(
            "Certificats SSL introuvables ou invalides, le serveur tournera sans "
            "chiffrement. Erreur: %s",
            exc,
        )

    # Espace de noms (Namespace)
    uri = "http://smart-robotic-cell.local"
    idx = await server.register_namespace(uri)

    # Noeud principal de supervision
    supervision_node = await server.nodes.objects.add_object(idx, "SupervisionUsine")

    # Liste des cellules à simuler : lue depuis la base de données (table
    # Cellule) plutôt que codée en dur, depuis que l'Administrateur peut en
    # créer de nouvelles depuis la page /administration (cf. CHG-V2-088). Ce
    # module tourne dans un processus séparé de web_server.py (cf. docstring
    # d'opcua_client.py) : la base SQLite est leur seul point de partage.
    # db.init_db() est idempotent (crée les tables/amorce les cellules par
    # défaut si absentes) et sûr à appeler ici même si web_server.py l'a déjà
    # fait dans son propre processus.
    db.init_db()
    with db.Session(db.engine) as _session:
        cellules = db.list_cellules(_session)
    LOGGER.info("Cellules chargées depuis la base : %s", [c.nom for c in cellules])

    # Création des cellules simulées
    cells = []
    for cellule in cellules:
        i = cellule.id
        cell_obj = await supervision_node.add_object(idx, f"CelluleRobotique_{i}")

        # Variables d'état existantes
        state_var = await cell_obj.add_variable(idx, "Etat", "EN_PRODUCTION")
        fault_var = await cell_obj.add_variable(idx, "EnDefaut", False)

        # Nouvelles variables industrielles
        type_var = await cell_obj.add_variable(idx, "TypeRobot", cellule.type_robot)
        name_var = await cell_obj.add_variable(idx, "NomCellule", cellule.nom)
        ip_var = await cell_obj.add_variable(idx, "AdresseIP", cellule.adresse_ip)
        progress_var = await cell_obj.add_variable(
            idx,
            "ProgressionCycle",
            0.0,
        )  # 0 à 100%
        alarms_var = await cell_obj.add_variable(
            idx,
            "AlarmesActives",
            "",
        )  # Chaîne contenant les codes d'alarme
        maintenance_req_var = await cell_obj.add_variable(
            idx,
            "MaintenanceRequise",
            False,
        )
        time_to_maint_var = await cell_obj.add_variable(
            idx,
            "HeuresAvantMaintenance",
            random.randint(10, 500),
        )

        # Sous-systèmes (Pneumatique, Lubrix)
        pneumatic_pressure_var = await cell_obj.add_variable(
            idx,
            "PressionPneumatique",
            6.2,
        )  # en bar
        pneumatic_state_var = await cell_obj.add_variable(idx, "BridageActif", True)
        lubrix_level_var = await cell_obj.add_variable(
            idx,
            "NiveauLubrifiant",
            random.randint(80, 100),
        )  # en %

        # Diagnostics Avancés (Maintenance)
        temp_axes_var = await cell_obj.add_variable(
            idx,
            "TemperatureAxes",
            random.uniform(35.0, 45.0),
        )  # en °C (agrégat = max des 6 axes)
        vibration_var = await cell_obj.add_variable(
            idx,
            "NiveauVibration",
            random.uniform(0.5, 1.5),
        )  # en mm/s

        # Vitesse de cycle (override programme), fixe pour la cellule.
        speed_var = await cell_obj.add_variable(
            idx, "VitesseCycle", random.choice(CYCLE_SPEED_CHOICES)
        )  # en %

        # Axes moteurs (1 à 6) : température, courant, couple. Un objet par
        # axe pour rester lisible dans l'espace de noms OPC UA.
        axes = []
        for axe_num in range(1, AXIS_COUNT + 1):
            axis_idx = axe_num - 1
            axe_obj = await cell_obj.add_object(idx, f"Axe_{axe_num}")
            temp_var = await axe_obj.add_variable(
                idx, "Temperature", AXIS_TEMP_IDLE_C[axis_idx]
            )
            courant_var = await axe_obj.add_variable(
                idx, "Courant", AXIS_CURRENT_IDLE_A[axis_idx]
            )
            couple_var = await axe_obj.add_variable(
                idx, "Couple", AXIS_TORQUE_HOLDING_NM[axis_idx]
            )
            await temp_var.set_writable(False)
            await courant_var.set_writable(False)
            await couple_var.set_writable(False)
            axes.append(
                {"temp": temp_var, "courant": courant_var, "couple": couple_var}
            )

        # Rend certaines variables "writable" pour le panneau de test/simulation Web
        await state_var.set_writable(True)
        await fault_var.set_writable(True)
        await type_var.set_writable(False)
        await name_var.set_writable(False)
        await ip_var.set_writable(False)
        # Doit rester writable : force_fault (web_server.py) réinitialise
        # ProgressionCycle à 0.0 lors de l'activation manuelle d'un défaut.
        # False ici provoque un BadUserAccessDenied sur cette écriture précise
        # (les 3 précédentes du même appel ayant déjà réussi).
        await progress_var.set_writable(True)
        await alarms_var.set_writable(True)
        await maintenance_req_var.set_writable(True)
        await time_to_maint_var.set_writable(True)
        await pneumatic_pressure_var.set_writable(True)
        await pneumatic_state_var.set_writable(True)
        await lubrix_level_var.set_writable(True)
        await temp_axes_var.set_writable(False)
        await vibration_var.set_writable(False)
        await speed_var.set_writable(False)

        cells.append(
            {
                "state": state_var,
                "fault": fault_var,
                "type": type_var,
                "name": name_var,
                "ip": ip_var,
                "progress": progress_var,
                "alarms": alarms_var,
                "maint_req": maintenance_req_var,
                "time_to_maint": time_to_maint_var,
                "pneumatic_pressure": pneumatic_pressure_var,
                "pneumatic_state": pneumatic_state_var,
                "lubrix_level": lubrix_level_var,
                "temp_axes": temp_axes_var,
                "vibration": vibration_var,
                "speed": speed_var,
                "axes": axes,
                "cycle_step": 0.0,
                "operating_hours": 0.0,
            }
        )

    LOGGER.info("Démarrage du serveur OPC UA sur opc.tcp://0.0.0.0:4840 ...")

    async with server:
        while True:
            await asyncio.sleep(1)
            # Simulation du comportement des cellules
            for cell in cells:

                # Simulation de la progression du cycle
                is_running = (
                    not await cell["fault"].read_value()
                    and await cell["state"].read_value() == "EN_PRODUCTION"
                )

                if is_running:
                    # Avance le cycle
                    cell["cycle_step"] += random.uniform(2.0, 8.0)
                    cell["operating_hours"] += 1.0  # 1 seconde = 1 heure de prod

                    if cell["cycle_step"] >= 100.0:
                        cell["cycle_step"] = 0.0  # Fin du cycle, on recommence

                    await cell["progress"].write_value(
                        float(round(cell["cycle_step"], 1))
                    )

                    await cell["vibration"].write_value(
                        float(round(random.uniform(1.0, 3.5), 2))
                    )

                    # Usure de la machine (décrémente le temps avant maintenance)
                    current_time_to_maint = await cell["time_to_maint"].read_value()
                    new_time_to_maint = current_time_to_maint - 1
                    if new_time_to_maint <= 0:
                        new_time_to_maint = 0
                        await cell["maint_req"].write_value(True)
                    await cell["time_to_maint"].write_value(int(new_time_to_maint))
                else:
                    # Arrêt des vibrations (la vitesse de cycle reste affichée :
                    # c'est un réglage programme, pas une vitesse instantanée).
                    await cell["vibration"].write_value(0.0)

                max_axis_temp = await _update_axes(cell["axes"], is_running)
                await cell["temp_axes"].write_value(float(round(max_axis_temp, 1)))

                # Génération aléatoire d'alarmes désactivée pour POC
                # On ne déclenche plus les alarmes ou auto-acquittements aléatoires pour
                # laisser l'utilisateur jouer avec le menu de test manuel.

                # Mise à jour conditionnelle si maintenance atteinte manuellement
                if (
                    await cell["time_to_maint"].read_value() <= 0
                    and not await cell["maint_req"].read_value()
                ):
                    await cell["maint_req"].write_value(True)


if __name__ == "__main__":
    asyncio.run(main())
