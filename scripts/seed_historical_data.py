"""Génère un historique réaliste (plusieurs semaines) pour la démo/dossier RNCP.

Ce script est un outil ponctuel, exécuté manuellement contre une COPIE du
fichier smart_robotic_cell.db réel (jamais l'original directement) : il crée
les nouvelles tables (MesureAxe, MesureCellule, DefautHistorique) si besoin
via db.init_db() (idempotent, ne touche pas Utilisateur/HistoriqueMaintenance
existants) puis insère des relevés/défauts couvrant les 3 dernières semaines,
jusqu'à aujourd'hui.

Relançable sans danger même une fois le serveur déployé et utilisé : dès que
la tâche de fond d'échantillonnage (ou de vrais clics sur le panneau de
simulation) a commencé à écrire de vraies données, ce script ne les touche
plus jamais. Il ne fait que :
  - compléter les relevés (MesureAxe/MesureCellule) UNE SEULE FOIS, s'ils
    sont totalement absents (sinon il s'arrête pour ne rien dupliquer) ;
  - repasser en "résolu" ses propres défauts de démonstration (repérés par le
    marqueur SEED_MARKER dans la description), sans jamais toucher un défaut
    réellement déclenché depuis le panneau de simulation.

Usage (depuis la racine du dépôt) :
    SRC_DB_PATH=/chemin/vers/copie.db python scripts/seed_historical_data.py
"""

from __future__ import annotations

import os
import random
import sys
from datetime import UTC, datetime, timedelta

if "SRC_DB_PATH" not in os.environ:
    print("SRC_DB_PATH doit être défini (copie du .db réel), abandon.", file=sys.stderr)
    sys.exit(1)

# Le script vit maintenant dans scripts/ : on remonte d'un niveau pour
# retrouver la racine du dépôt (où se trouve le paquet src_v2), quel que
# soit le répertoire courant depuis lequel il est lancé.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src_v2 import db  # noqa: E402  (import après réglage de SRC_DB_PATH)

random.seed(20260819)  # reproductible

# Mêmes valeurs de référence par axe que la simulation OPC UA temps réel
# (src_v2/opcua_server.py), pour que l'historique soit cohérent avec ce que
# montre le dashboard en direct.
AXIS_TEMP_IDLE_C = [30.0, 29.0, 28.0, 26.0, 25.0, 24.0]
AXIS_TEMP_RUNNING_C = [55.0, 50.0, 45.0, 38.0, 34.0, 30.0]
AXIS_CURRENT_IDLE_A = [0.6, 0.5, 0.4, 0.3, 0.2, 0.15]
AXIS_CURRENT_RUNNING_A = [9.5, 8.0, 6.0, 3.0, 2.0, 1.2]
AXIS_TORQUE_HOLDING_NM = [65.0, 50.0, 30.0, 8.0, 4.0, 1.5]
AXIS_TORQUE_RUNNING_EXTRA_NM = [25.0, 18.0, 10.0, 3.0, 1.5, 0.5]

CELLS = [1, 2, 3]
DAYS_OF_HISTORY = 21
SAMPLE_INTERVAL_MINUTES = 15

# Marqueur distinctif des lignes créées par ce script, pour pouvoir les
# reconnaître plus tard (et elles seules) sans jamais toucher une vraie
# donnée produite par la tâche de fond ou par le panneau de simulation.
SEED_MARKER = "(jeu de données historique)"

FAULT_TYPES = [
    ("Défaut capteur température", "avertissement"),
    ("Surcharge moteur (courant élevé)", "critique"),
    ("Perte de communication OPC UA", "critique"),
    ("Pression pneumatique hors tolérance", "avertissement"),
    ("Niveau lubrifiant bas", "avertissement"),
    ("Collision détectée (arrêt d'urgence)", "critique"),
    ("Dérive de trajectoire (recalibrage requis)", "avertissement"),
    ("Défaut préhenseur / pince", "critique"),
]


def _is_running(moment: datetime) -> bool:
    """Modèle simple de cycle de production : actif en semaine, 6h-21h, ~80%."""

    if moment.weekday() >= 5:  # week-end : production très réduite
        return random.random() < 0.10
    if 6 <= moment.hour < 21:
        return random.random() < 0.80
    return random.random() < 0.05


def _seed_measures() -> tuple[int, int]:
    now = datetime.now(UTC)
    start = now - timedelta(days=DAYS_OF_HISTORY)

    axis_count = 0
    cell_count = 0

    axis_state = {
        cell_id: [
            {
                "temp": AXIS_TEMP_IDLE_C[a],
                "courant": AXIS_CURRENT_IDLE_A[a],
                "couple": AXIS_TORQUE_HOLDING_NM[a],
            }
            for a in range(6)
        ]
        for cell_id in CELLS
    }
    lubrix_state = {cell_id: 96.0 for cell_id in CELLS}

    with db.Session(db.engine) as session:
        moment = start
        step = timedelta(minutes=SAMPLE_INTERVAL_MINUTES)
        while moment <= now:
            horodatage = moment.strftime("%Y-%m-%d %H:%M:%S")
            running_now = _is_running(moment)

            for cell_id in CELLS:
                pressure = 6.2 + random.uniform(-0.15, 0.15)
                # Usure lente et régulière du lubrifiant sur 3 semaines, avec un
                # léger bruit ; jamais remonté (pas de "maintenance" simulée ici).
                lubrix_state[cell_id] = max(
                    60.0, lubrix_state[cell_id] - random.uniform(0.0, 0.03)
                )

                db.add_cell_measure(
                    session,
                    cellule_id=cell_id,
                    pneumatic_pressure_bar=round(pressure, 2),
                    lubrix_level_pct=round(lubrix_state[cell_id], 1),
                    horodatage=horodatage,
                )
                cell_count += 1

                for a in range(6):
                    target_temp = (
                        AXIS_TEMP_RUNNING_C[a] if running_now else AXIS_TEMP_IDLE_C[a]
                    )
                    target_courant = (
                        AXIS_CURRENT_RUNNING_A[a]
                        if running_now
                        else AXIS_CURRENT_IDLE_A[a]
                    )
                    target_couple = AXIS_TORQUE_HOLDING_NM[a] + (
                        AXIS_TORQUE_RUNNING_EXTRA_NM[a] * random.uniform(0.6, 1.0)
                        if running_now
                        else random.uniform(-0.5, 0.5)
                    )

                    state = axis_state[cell_id][a]
                    # Interpolation progressive (comme la simulation temps réel)
                    # plutôt qu'un saut net idle<->running, pour des courbes lisses.
                    state["temp"] += (target_temp - state["temp"]) * 0.15
                    state["temp"] += random.uniform(-0.3, 0.3)
                    state["courant"] += (
                        target_courant - state["courant"]
                    ) * 0.25 + random.uniform(-0.1, 0.1)
                    state["couple"] += (
                        target_couple - state["couple"]
                    ) * 0.25 + random.uniform(-0.4, 0.4)

                    db.add_axis_measure(
                        session,
                        cellule_id=cell_id,
                        axe=a + 1,
                        temperature_c=round(state["temp"], 1),
                        courant_a=round(max(0.0, state["courant"]), 2),
                        couple_nm=round(max(0.0, state["couple"]), 1),
                        horodatage=horodatage,
                    )
                    axis_count += 1

            moment += step

    return axis_count, cell_count


def _seed_faults() -> int:
    now = datetime.now(UTC)
    start = now - timedelta(days=DAYS_OF_HISTORY)
    total_span_seconds = int((now - start).total_seconds())

    # Une quinzaine d'événements variés, répartis sur les 3 semaines et les 3
    # cellules. Tous sont marqués résolus : ce sont des incidents historiques
    # déjà clos, pas l'état courant des robots. Laisser un défaut "actif" ici
    # sans que le robot correspondant ne soit réellement en défaut (l'état
    # live vient d'OPC UA, pas de cette table) créait une incohérence visible
    # entre l'historique et le dashboard — un défaut vraiment actif ne doit
    # apparaître que via une action réelle (force_fault sur le panneau de
    # simulation), jamais via ce jeu de données de démonstration.
    events = []
    for _ in range(15):
        offset = timedelta(seconds=random.randint(0, total_span_seconds))
        moment = start + offset
        cell_id = random.choice(CELLS)
        type_defaut, severite = random.choice(FAULT_TYPES)
        events.append((moment, cell_id, type_defaut, severite))

    events.sort(key=lambda e: e[0])

    count = 0
    with db.Session(db.engine) as session:
        for moment, cell_id, type_defaut, severite in events:
            entry = db.DefautHistorique(
                horodatage=moment.strftime("%Y-%m-%d %H:%M:%S"),
                cellule_id=cell_id,
                type_defaut=type_defaut,
                severite=severite,
                description=f"{type_defaut} — Cellule {cell_id} {SEED_MARKER}",
                resolu=True,
            )
            session.add(entry)
            count += 1
        session.commit()

    return count


def _resolve_seeded_faults() -> int:
    """Repasse en "résolu" les défauts créés par CE script, et eux seuls.

    Un défaut historique (semaines passées) ne doit jamais apparaître "actif"
    sans qu'aucun robot ne soit réellement en défaut : ça a été un vrai bug
    signalé sur le dashboard. On ne touche qu'aux lignes portant SEED_MARKER
    dans leur description ; un défaut réellement déclenché depuis le panneau
    de simulation (POC) n'a jamais ce marqueur et garde son état réel.
    """

    count = 0
    with db.Session(db.engine) as session:
        rows = session.exec(
            db.select(db.DefautHistorique).where(
                db.DefautHistorique.description.contains(SEED_MARKER)
            )
        )
        for row in rows:
            if not row.resolu:
                row.resolu = True
                session.add(row)
                count += 1
        session.commit()
    return count


def main() -> None:
    db.init_db()

    with db.Session(db.engine) as session:
        already_has_measures = (
            session.exec(db.select(db.MesureAxe).limit(1)).first() is not None
        )
        already_has_faults = (
            session.exec(db.select(db.DefautHistorique).limit(1)).first() is not None
        )

    if already_has_measures:
        print(
            "MesureAxe/MesureCellule contiennent déjà des données (relevés "
            "réels de la tâche de fond et/ou de ce script) : backfill ignoré "
            "pour ne rien dupliquer."
        )
        axis_count, cell_count = 0, 0
    else:
        axis_count, cell_count = _seed_measures()

    if already_has_faults:
        fixed = _resolve_seeded_faults()
        print(
            f"DefautHistorique contient déjà des données : pas de nouveaux "
            f"défauts de démonstration ajoutés, {fixed} défaut(s) de "
            f"démonstration repassé(s) en résolu."
        )
        fault_count = 0
    else:
        fault_count = _seed_faults()

    print(
        f"OK — {axis_count} relevés d'axes, {cell_count} relevés cellule, "
        f"{fault_count} nouveaux défauts insérés dans {os.environ['SRC_DB_PATH']}"
    )


if __name__ == "__main__":
    main()
