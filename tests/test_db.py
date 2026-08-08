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
