import asyncio
import logging
import random

from asyncua import Server, ua

logging.basicConfig(level=logging.INFO)
LOGGER = logging.getLogger("asyncua")

async def main():
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

    # Types de robots disponibles
    robot_types = ["ROBOT KUKA KR210", "ROBOT KUKA KR210", "ROBOT KUKA KR210"]
    cell_names = ["PERÇAGE AÉRO", "ASSEMBLAGE", "CONTRÔLE QUALITÉ"]
    cell_ips = ["192.168.1.10", "192.168.1.20", "192.168.1.30"]

    # Création de trois cellules simulées
    cells = []
    for i in range(1, 4):
        cell_obj = await supervision_node.add_object(idx, f"CelluleRobotique_{i}")

        # Variables d'état existantes
        state_var = await cell_obj.add_variable(idx, "Etat", "EN_PRODUCTION")
        fault_var = await cell_obj.add_variable(idx, "EnDefaut", False)

        # Nouvelles variables industrielles
        type_var = await cell_obj.add_variable(idx, "TypeRobot", robot_types[i-1])
        name_var = await cell_obj.add_variable(idx, "NomCellule", cell_names[i-1])
        ip_var = await cell_obj.add_variable(idx, "AdresseIP", cell_ips[i-1])
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
        )  # en °C
        vibration_var = await cell_obj.add_variable(
            idx,
            "NiveauVibration",
            random.uniform(0.5, 1.5),
        )  # en mm/s

        # Vitesse
        speed_var = await cell_obj.add_variable(idx, "VitesseBras", 0.0) # en %

        # Rend certaines variables "writable" pour le panneau de test/simulation Web
        await state_var.set_writable(True)
        await fault_var.set_writable(True)
        await type_var.set_writable(False)
        await name_var.set_writable(False)
        await ip_var.set_writable(False)
        await progress_var.set_writable(False)
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

                    # Simulation des variables de diagnostic
                    # (chauffe et vibre plus en prod)
                    await cell["temp_axes"].write_value(
                        float(round(random.uniform(45.0, 65.0), 1))
                    )
                    await cell["vibration"].write_value(
                        float(round(random.uniform(1.0, 3.5), 2))
                    )

                    # Simulation de la vitesse du bras
                    await cell["speed"].write_value(
                        float(round(random.uniform(85.0, 100.0), 1))
                    )

                    # Usure de la machine (décrémente le temps avant maintenance)
                    current_time_to_maint = await cell["time_to_maint"].read_value()
                    new_time_to_maint = current_time_to_maint - 1
                    if new_time_to_maint <= 0:
                        new_time_to_maint = 0
                        await cell["maint_req"].write_value(True)
                    await cell["time_to_maint"].write_value(int(new_time_to_maint))
                else:
                    # Refroidissement et arrêt des vibrations et de la vitesse
                    current_temp = await cell["temp_axes"].read_value()
                    if current_temp > 25.0:
                        await cell["temp_axes"].write_value(
                            float(round(current_temp - 2.0, 1))
                        )
                    await cell["vibration"].write_value(0.0)
                    await cell["speed"].write_value(0.0)

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
