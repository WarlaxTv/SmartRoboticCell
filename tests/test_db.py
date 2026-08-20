"""Tests de la couche de persistance SQLite (src_v2.db).

Complète les tests d'API existants : ceux-ci vérifient déjà que
/api/maintenance/history reflète une action déclenchée via /api/maintenance
/request (test_maintenance_can_read_history_after_request). Les tests
ci-dessous vérifient directement le module db, notamment le fait que
l'historique *survit* à la fermeture d'une session (persistance réelle,
pas juste un état en mémoire de la durée du process).
"""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from src_v2 import db


def test_init_db_seeds_demo_users() -> None:
    db.init_db()
    with Session(db.engine) as session:
        jean = db.get_user(session, "jean_ope")
        luc = db.get_user(session, "luc_maint")

    assert jean is not None
    assert jean.role == "OPERATEUR"
    assert luc is not None
    assert luc.role == "MAINTENANCE"


def test_history_entry_persists_across_sessions() -> None:
    db.init_db()

    with Session(db.engine) as session:
        db.add_history_entry(
            session,
            action="Test unitaire : entrée de persistance",
            username_auteur="luc_maint",
            cellule_id=3,
        )

    # Nouvelle session indépendante : si la donnée n'était qu'en mémoire
    # (comme l'ancienne liste Python), elle serait invisible ici.
    with Session(db.engine) as session:
        history = db.list_history(session)

    assert any(
        entry.action == "Test unitaire : entrée de persistance"
        and entry.cellule_id == 3
        and entry.username_auteur == "luc_maint"
        for entry in history
    )


def test_list_history_filters_by_cellule_id() -> None:
    """La page de détail d'une cellule doit pouvoir ne récupérer que ses
    propres interventions, sans affecter l'appel existant sans filtre.
    """

    db.init_db()

    with Session(db.engine) as session:
        db.add_history_entry(
            session,
            action="Intervention cellule isolée 40",
            username_auteur="luc_maint",
            cellule_id=40,
        )
        db.add_history_entry(
            session,
            action="Intervention cellule isolée 41",
            username_auteur="luc_maint",
            cellule_id=41,
        )

    with Session(db.engine) as session:
        filtered = db.list_history(session, cellule_id=40)
        unfiltered = db.list_history(session)

    assert all(entry.cellule_id == 40 for entry in filtered)
    assert any(entry.action == "Intervention cellule isolée 40" for entry in filtered)
    assert not any(
        entry.action == "Intervention cellule isolée 41" for entry in filtered
    )
    assert any(entry.action == "Intervention cellule isolée 41" for entry in unfiltered)


def test_get_user_unknown_returns_none() -> None:
    db.init_db()
    with Session(db.engine) as session:
        assert db.get_user(session, "inconnu_xyz") is None


def test_history_rejects_unknown_author_foreign_key() -> None:
    """La contrainte FK sur username_auteur est réellement appliquée par SQLite.

    Sans le PRAGMA foreign_keys=ON (voir db._enable_sqlite_foreign_keys),
    SQLite accepterait silencieusement une référence vers un utilisateur
    inexistant : ce test échouerait alors silencieusement en laissant passer
    une ligne orpheline.
    """

    db.init_db()
    with pytest.raises(IntegrityError):
        with Session(db.engine) as session:
            db.add_history_entry(
                session,
                action="Ne doit jamais être persistée",
                username_auteur="utilisateur_qui_nexiste_pas",
                cellule_id=1,
            )


def test_axis_measure_persists_and_is_filtered_by_cell_and_time() -> None:
    db.init_db()

    with Session(db.engine) as session:
        db.add_axis_measure(
            session,
            cellule_id=1,
            axe=3,
            temperature_c=42.5,
            courant_a=1.8,
            couple_nm=12.0,
            horodatage="2026-08-01 10:00:00",
        )
        db.add_axis_measure(
            session,
            cellule_id=1,
            axe=3,
            temperature_c=43.0,
            courant_a=1.9,
            couple_nm=12.1,
            horodatage="2026-08-19 10:00:00",
        )
        # Autre cellule : ne doit jamais apparaître dans les résultats filtrés
        # sur cellule_id=1 ci-dessous.
        db.add_axis_measure(
            session,
            cellule_id=2,
            axe=3,
            temperature_c=99.0,
            courant_a=9.9,
            couple_nm=99.0,
            horodatage="2026-08-19 10:00:00",
        )

    with Session(db.engine) as session:
        recent = db.list_axis_measures(
            session, cellule_id=1, since="2026-08-10 00:00:00"
        )
        everything = db.list_axis_measures(
            session, cellule_id=1, since="2026-01-01 00:00:00"
        )

    assert len(recent) == 1
    assert recent[0].temperature_c == 43.0
    assert len(everything) == 2
    assert all(m.cellule_id == 1 for m in everything)


def test_cell_measure_persists_and_is_filtered_by_cell_and_time() -> None:
    db.init_db()

    with Session(db.engine) as session:
        db.add_cell_measure(
            session,
            cellule_id=2,
            pneumatic_pressure_bar=6.1,
            lubrix_level_pct=88.0,
            horodatage="2026-08-01 08:00:00",
        )
        db.add_cell_measure(
            session,
            cellule_id=2,
            pneumatic_pressure_bar=6.3,
            lubrix_level_pct=87.5,
            horodatage="2026-08-19 08:00:00",
        )

    with Session(db.engine) as session:
        recent = db.list_cell_measures(
            session, cellule_id=2, since="2026-08-10 00:00:00"
        )

    assert len(recent) == 1
    assert recent[0].pneumatic_pressure_bar == 6.3


def test_add_defaut_and_list_defauts_most_recent_first() -> None:
    db.init_db()

    with Session(db.engine) as session:
        db.add_defaut(
            session,
            cellule_id=10,
            type_defaut="Défaut capteur température",
            severite="avertissement",
            description="Premier défaut du test",
            horodatage="2026-08-01 09:00:00",
        )
        db.add_defaut(
            session,
            cellule_id=10,
            type_defaut="Collision détectée",
            severite="critique",
            description="Second défaut du test",
            horodatage="2026-08-19 09:00:00",
        )

    with Session(db.engine) as session:
        faults = db.list_defauts(session, cellule_id=10)

    assert len(faults) == 2
    # Le plus récent (par id croissant / insertion) doit arriver en premier.
    assert faults[0].type_defaut == "Collision détectée"
    assert faults[0].statut == db.DEFAUT_STATUT_ACTIF


def test_resolve_last_defaut_marks_most_recent_unresolved_as_resolved() -> None:
    db.init_db()

    with Session(db.engine) as session:
        db.add_defaut(
            session,
            cellule_id=5,
            type_defaut="Défaut ancien",
            severite="avertissement",
            description="Ne doit pas être touché",
            horodatage="2026-08-01 09:00:00",
        )
        db.add_defaut(
            session,
            cellule_id=5,
            type_defaut="Défaut récent",
            severite="critique",
            description="Doit être résolu",
            horodatage="2026-08-19 09:00:00",
        )

    with Session(db.engine) as session:
        resolved = db.resolve_last_defaut(session, cellule_id=5)

    assert resolved is not None
    assert resolved.type_defaut == "Défaut récent"
    assert resolved.statut == db.DEFAUT_STATUT_RESOLU

    with Session(db.engine) as session:
        faults = db.list_defauts(session, cellule_id=5)

    still_unresolved = [f for f in faults if f.statut != db.DEFAUT_STATUT_RESOLU]
    assert len(still_unresolved) == 1
    assert still_unresolved[0].type_defaut == "Défaut ancien"


def test_resolve_last_defaut_returns_none_when_nothing_to_resolve() -> None:
    db.init_db()
    with Session(db.engine) as session:
        assert db.resolve_last_defaut(session, cellule_id=999) is None


def test_list_defauts_without_cell_filter_returns_all_cells() -> None:
    db.init_db()

    with Session(db.engine) as session:
        db.add_defaut(
            session,
            cellule_id=30,
            type_defaut="Défaut cellule 30",
            severite="critique",
            description="...",
        )
        db.add_defaut(
            session,
            cellule_id=31,
            type_defaut="Défaut cellule 31",
            severite="avertissement",
            description="...",
        )

    with Session(db.engine) as session:
        faults = db.list_defauts(session)

    assert {f.cellule_id for f in faults} >= {30, 31}


def test_list_defauts_filters_by_statut_and_date_range() -> None:
    db.init_db()

    # On récupère les ids (valeurs primitives) plutôt que de garder les
    # objets ORM d'une session déjà fermée : un objet SQLModel/SQLAlchemy est
    # "expiré" par le commit() d'un appel ultérieur partageant la même
    # session (même celui d'un *autre* défaut), et lever une exception dès
    # qu'on relit un de ses attributs après coup (DetachedInstanceError).
    with Session(db.engine) as session:
        ancien_id = db.add_defaut(
            session,
            cellule_id=50,
            type_defaut="Défaut ancien",
            severite="avertissement",
            description="...",
            horodatage="2026-08-01 09:00:00",
        ).id
        recent_id = db.add_defaut(
            session,
            cellule_id=50,
            type_defaut="Défaut récent",
            severite="critique",
            description="...",
            horodatage="2026-08-19 09:00:00",
        ).id

    # On résout explicitement le récent (et laisse l'ancien "actif") pour que
    # le scénario ne dépende pas de l'ordre implicite de resolve_last_defaut.
    with Session(db.engine) as session:
        db.set_defaut_statut(session, recent_id, db.DEFAUT_STATUT_RESOLU)

    with Session(db.engine) as session:
        actifs = db.list_defauts(session, cellule_id=50, statut=db.DEFAUT_STATUT_ACTIF)
        resolus = db.list_defauts(
            session, cellule_id=50, statut=db.DEFAUT_STATUT_RESOLU
        )
        depuis_le_10 = db.list_defauts(
            session, cellule_id=50, since="2026-08-10 00:00:00"
        )

    assert {f.id for f in actifs} == {ancien_id}
    assert {f.id for f in resolus} == {recent_id}
    assert {f.id for f in depuis_le_10} == {recent_id}


def test_list_history_filters_by_date_range() -> None:
    db.init_db()

    with Session(db.engine) as session:
        entry = db.add_history_entry(
            session,
            action="Intervention filtrée par date",
            username_auteur="luc_maint",
            cellule_id=60,
        )

    with Session(db.engine) as session:
        depuis_hier = db.list_history(
            session, cellule_id=60, since="2000-01-01 00:00:00"
        )
        avant_creation = db.list_history(
            session, cellule_id=60, until="2000-01-01 00:00:00"
        )

    assert any(e.id == entry.id for e in depuis_hier)
    assert not any(e.id == entry.id for e in avant_creation)


def test_get_defaut_returns_none_for_unknown_id() -> None:
    db.init_db()
    with Session(db.engine) as session:
        assert db.get_defaut(session, 999999) is None


def test_set_defaut_statut_updates_existing_defaut() -> None:
    db.init_db()

    with Session(db.engine) as session:
        created = db.add_defaut(
            session,
            cellule_id=70,
            type_defaut="Défaut pour set_defaut_statut",
            severite="critique",
            description="...",
        )

    with Session(db.engine) as session:
        updated = db.set_defaut_statut(session, created.id, db.DEFAUT_STATUT_EN_COURS)

    assert updated is not None
    assert updated.statut == db.DEFAUT_STATUT_EN_COURS


def test_add_maintenance_intervention_resolves_defaut_and_traces_author() -> None:
    """Le coeur du workflow "Autre" de la TODO list : la Maintenance choisit
    un défaut précis, déclare le problème résolu, et cela doit à la fois
    créer une ligne d'historique traçable ET faire passer le défaut à
    "resolu" — automatiquement, sans étape manuelle supplémentaire.
    """

    db.init_db()

    with Session(db.engine) as session:
        created = db.add_defaut(
            session,
            cellule_id=80,
            type_defaut="Défaut pour intervention",
            severite="critique",
            description="...",
        )

    with Session(db.engine) as session:
        entry = db.add_maintenance_intervention(
            session,
            username_auteur="luc_maint",
            defaut_id=created.id,
            notes="Remplacement du capteur.",
            probleme_resolu=True,
        )

    assert entry.defaut_id == created.id
    assert entry.probleme_resolu is True
    assert entry.username_auteur == "luc_maint"
    assert "Remplacement du capteur." in entry.action

    with Session(db.engine) as session:
        defaut = db.get_defaut(session, created.id)

    assert defaut.statut == db.DEFAUT_STATUT_RESOLU


def test_add_maintenance_intervention_keeps_defaut_en_cours_when_not_resolved() -> None:
    db.init_db()

    with Session(db.engine) as session:
        created = db.add_defaut(
            session,
            cellule_id=81,
            type_defaut="Défaut pris en charge mais pas résolu",
            severite="avertissement",
            description="...",
        )

    with Session(db.engine) as session:
        entry = db.add_maintenance_intervention(
            session,
            username_auteur="luc_maint",
            defaut_id=created.id,
            notes="",
            probleme_resolu=False,
        )

    assert entry.probleme_resolu is False

    with Session(db.engine) as session:
        defaut = db.get_defaut(session, created.id)

    assert defaut.statut == db.DEFAUT_STATUT_EN_COURS


def test_add_maintenance_intervention_rejects_unknown_defaut_id() -> None:
    db.init_db()
    with Session(db.engine) as session:
        with pytest.raises(ValueError):
            db.add_maintenance_intervention(
                session,
                username_auteur="luc_maint",
                defaut_id=999999,
                notes="",
                probleme_resolu=True,
            )
