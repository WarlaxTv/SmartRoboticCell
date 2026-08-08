"""Persistence layer for Smart Robotic Cell V2.

Remplace le stockage en mémoire (dict/list) par une vraie base SQLite via
SQLModel, pour les données qui doivent survivre à un redémarrage du serveur :
les comptes utilisateurs et l'historique de maintenance.

Le champ ``active_maintenance_requests`` de web_server.py reste volontairement
en mémoire : c'est un état opérationnel transitoire (« qui est en train de
demander quoi, là, maintenant »), pas une donnée à archiver. C'est
l'historique (maintenance_history) qui a besoin de traçabilité durable au
sens NF EN 9100 (chapitre 8.1.2) — c'est celui-ci qui est persisté.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

from sqlalchemy import event
from sqlmodel import Field, Session, SQLModel, create_engine, select

DB_PATH = os.environ.get("SRC_DB_PATH", "smart_robotic_cell.db")
DATABASE_URL = f"sqlite:///{DB_PATH}"

# check_same_thread=False : nécessaire car FastAPI peut servir une requête
# par thread différent de celui qui a créé la connexion (voir doc SQLModel).
engine = create_engine(
    DATABASE_URL, echo=False, connect_args={"check_same_thread": False}
)


@event.listens_for(engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
    """Active l'application réelle des clés étrangères sous SQLite.

    SQLite accepte une colonne ``foreign_key`` dans son schéma sans jamais la
    faire respecter, sauf si ``PRAGMA foreign_keys=ON`` est exécuté sur
    *chaque* connexion (ce n'est pas un réglage persistant du fichier .db).
    Sans cette ligne, la contrainte déclarée sur ``HistoriqueMaintenance.
    username_auteur`` serait purement documentaire.
    """

    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


class Utilisateur(SQLModel, table=True):
    """Compte utilisateur de l'application (Opérateur / Maintenance / Manager)."""

    username: str = Field(primary_key=True)
    password_hash: str
    role: str


class HistoriqueMaintenance(SQLModel, table=True):
    """Une ligne = une action tracée (demande ou intervention de maintenance).

    Persistée en base pour survivre à un redémarrage du serveur et répondre à
    l'exigence de traçabilité NF EN 9100 (chapitre 8.1.2 : Configuration et
    Traçabilité), déjà citée dans NF_EN_9100_CONFORMITE.md.
    """

    id: int | None = Field(default=None, primary_key=True)
    horodatage: str
    action: str
    # Contrainte d'intégrité référentielle réelle (clé étrangère SQL) :
    # une ligne d'historique ne peut référencer qu'un utilisateur existant.
    username_auteur: str = Field(foreign_key="utilisateur.username")
    cellule_id: int


# Hashs bcrypt réels (générés via la librairie bcrypt, pas des chaînes
# fictives) pour "ope123" et "maint123", utilisés uniquement pour amorcer la
# base de démo au premier lancement.
_SEED_USERS = [
    {
        "username": "jean_ope",
        "password_hash": "$2b$12$d5cDFOkFybsniTKjh10/B.bRYf/73LTgAReB3rlpde8odpW/rYhzS",
        "role": "OPERATEUR",
    },
    {
        "username": "luc_maint",
        "password_hash": "$2b$12$Ly00nWgwH5s0iKXBCNSv5uI/cBTGpK7qU.P7vhUBOzg7hyo.b2ZjG",
        "role": "MAINTENANCE",
    },
]


def init_db() -> None:
    """Crée les tables si nécessaire et amorce les comptes de démo.

    Idempotent : peut être appelée à chaque démarrage (module-level, y
    compris sous pytest/TestClient) sans dupliquer les données.
    """

    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        if session.exec(select(Utilisateur)).first() is None:
            for user in _SEED_USERS:
                session.add(Utilisateur(**user))
            session.commit()


def get_session():
    """Dépendance FastAPI fournissant une session DB par requête."""

    with Session(engine) as session:
        yield session


def get_user(session: Session, username: str) -> Utilisateur | None:
    """Recherche un utilisateur par son identifiant."""

    return session.get(Utilisateur, username)


def add_history_entry(
    session: Session, action: str, username_auteur: str, cellule_id: int
) -> HistoriqueMaintenance:
    """Ajoute et persiste une ligne d'historique de maintenance."""

    entry = HistoriqueMaintenance(
        horodatage=datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S"),
        action=action,
        username_auteur=username_auteur,
        cellule_id=cellule_id,
    )
    session.add(entry)
    session.commit()
    session.refresh(entry)
    return entry


def list_history(session: Session) -> list[HistoriqueMaintenance]:
    """Retourne l'historique de maintenance complet, dans l'ordre chronologique."""

    return list(
        session.exec(select(HistoriqueMaintenance).order_by(HistoriqueMaintenance.id))
    )
