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
# Réduit de 15 à 5 minutes (demande utilisateur : courbes historiques trop
# clairsemées). ~127k relevés d'axes sur 21 jours / 3 cellules, ce qui reste
# largement raisonnable pour SQLite et pour le temps d'exécution du script.
SAMPLE_INTERVAL_MINUTES = 5

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


# Probabilité de bascule d'état (production <-> arrêt) à chaque pas
# d'échantillonnage. Avec SAMPLE_INTERVAL_MINUTES minutes par pas, une
# bascule moyenne toutes les BLOCK_TICKS pas donne des blocs continus d'une
# durée réaliste (~1h) plutôt qu'un état qui change à chaque point.
BLOCK_TICKS = 12
SWITCH_PROBABILITY = 1.0 / BLOCK_TICKS


def _running_share(moment: datetime) -> float:
    """Probabilité cible de production à cet instant (tendance de fond)."""

    if moment.weekday() >= 5:  # week-end : production très réduite
        return 0.10
    if 6 <= moment.hour < 21:
        return 0.80
    return 0.05


def _next_running_state(target_share: float, currently_running: bool | None) -> bool:
    """Fait évoluer l'état production/arrêt par blocs persistants.

    Ancien modèle (bug remonté par l'utilisateur, voir
    JOURNAL_ERREURS_ET_FIXES_FR.md → INC-V2-020) : chaque point tirait un
    nouvel état production/arrêt de façon totalement indépendante du point
    précédent. Combiné à l'interpolation progressive des axes (qui ne
    convergeait donc jamais complètement vers sa cible avant qu'elle ne
    change à nouveau), cela produisait des allers-retours erratiques
    ("retours en arrière") sur les courbes température/courant/couple,
    visibles y compris hors de toute anomalie réelle.

    Ce modèle ne réévalue l'état qu'avec une faible probabilité à chaque
    pas (``SWITCH_PROBABILITY``), ce qui donne des blocs continus de
    plusieurs dizaines de minutes à quelques heures — comme une vraie
    ligne de production qui tourne en continu puis s'arrête, plutôt que de
    changer d'état à chaque relevé.
    """

    if currently_running is None or random.random() < SWITCH_PROBABILITY:
        return random.random() < target_share
    return currently_running


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
    # État production/arrêt persistant par cellule (voir _next_running_state) :
    # chaque cellule a sa propre ligne, indépendante des deux autres.
    running_state: dict[int, bool | None] = dict.fromkeys(CELLS)

    with db.Session(db.engine) as session:
        moment = start
        step = timedelta(minutes=SAMPLE_INTERVAL_MINUTES)
        while moment <= now:
            horodatage = moment.strftime("%Y-%m-%d %H:%M:%S")
            target_share = _running_share(moment)

            for cell_id in CELLS:
                running_now = _next_running_state(target_share, running_state[cell_id])
                running_state[cell_id] = running_now
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
                statut=db.DEFAUT_STATUT_RESOLU,
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
            if row.statut != db.DEFAUT_STATUT_RESOLU:
                row.statut = db.DEFAUT_STATUT_RESOLU
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
