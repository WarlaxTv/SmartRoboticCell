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
from datetime import datetime

from sqlalchemy import event
from sqlmodel import Field, Session, SQLModel, create_engine, select

# Les horodatages métier (``horodatage`` sur toutes les tables ci-dessous)
# sont enregistrés en heure LOCALE du serveur (datetime.now(), sans UTC),
# volontairement : ce POC tourne sur un seul poste, dans un seul fuseau
# horaire (celui de l'utilisateur), et un horodatage en UTC affiché tel quel
# sur le dashboard était perçu comme "en retard de 2h" par rapport à
# l'horloge réelle (été en France = UTC+2). Un vrai déploiement multi-site
# nécessiterait de revoir ce choix (stocker en UTC + convertir à
# l'affichage), mais ajouterait une complexité sans objet ici. Voir aussi
# INC-V2-022. La date d'expiration des jetons JWT (security.py), elle,
# reste volontairement en UTC : c'est une donnée de sécurité, pas un
# horodatage affiché à l'utilisateur.

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
    # Défaut concerné par cette action, quand elle en traite un précisément
    # (formulaire "Enregistrer une intervention" de la page Historique des
    # défauts). None pour les entrées génériques préexistantes (demande
    # d'intervention depuis le dashboard, actions du panneau de simulation)
    # qui ne visent pas un DefautHistorique en particulier.
    defaut_id: int | None = Field(default=None, foreign_key="defauthistorique.id")
    # État du problème tel que déclaré par la Maintenance à la clôture de
    # cette action : True si résolu, False si pris en charge mais toujours
    # actif, None si cette action ne clôt rien (simple demande, action du
    # panneau de simulation).
    probleme_resolu: bool | None = Field(default=None)


class MesureAxe(SQLModel, table=True):
    """Un relevé horodaté d'un axe moteur d'une cellule robotique.

    Persisté périodiquement (tâche de fond dans web_server.py, cf.
    ``_sampling_loop``) à partir des données OPC UA, pour constituer un
    historique exploitable (courbes de tendance sur la page de détail d'une
    cellule) plutôt qu'un simple instantané en mémoire.
    """

    id: int | None = Field(default=None, primary_key=True)
    horodatage: str
    cellule_id: int
    axe: int  # 1 à 6
    temperature_c: float
    courant_a: float
    couple_nm: float


class MesureCellule(SQLModel, table=True):
    """Un relevé horodaté des grandeurs globales d'une cellule (hors axes).

    Couvre la pression pneumatique et le niveau de lubrifiant, en complément
    de MesureAxe pour les données par axe.
    """

    id: int | None = Field(default=None, primary_key=True)
    horodatage: str
    cellule_id: int
    pneumatic_pressure_bar: float
    lubrix_level_pct: float


# Les 3 états possibles d'un DefautHistorique.statut. "actif" est aussi,
# implicitement, une demande d'intervention en attente : plutôt que de créer
# une table séparée pour ce concept, un défaut actif *est* la demande tant
# qu'aucune intervention ne l'a pris en charge (cf. journal des décisions,
# CHG-V2-057) — une intervention qui ne résout pas le problème le fait
# passer en "en_cours" (pris en charge, toujours actif), et seule une
# intervention qui le déclare résolu le fait passer en "resolu".
DEFAUT_STATUT_ACTIF = "actif"
DEFAUT_STATUT_EN_COURS = "en_cours"
DEFAUT_STATUT_RESOLU = "resolu"
DEFAUT_STATUTS = (DEFAUT_STATUT_ACTIF, DEFAUT_STATUT_EN_COURS, DEFAUT_STATUT_RESOLU)

# Sévérités valides pour DefautHistorique.severite (voir champ ci-dessous).
# Extrait en constante pour que web_server.py puisse valider un signalement
# manuel de la Maintenance (CHG-V2-065) sans dupliquer les valeurs en dur.
DEFAUT_SEVERITE_CRITIQUE = "critique"
DEFAUT_SEVERITE_AVERTISSEMENT = "avertissement"
DEFAUT_SEVERITES = (DEFAUT_SEVERITE_CRITIQUE, DEFAUT_SEVERITE_AVERTISSEMENT)


class DefautHistorique(SQLModel, table=True):
    """Une ligne = un défaut survenu sur une cellule (distinct de l'historique
    de maintenance : ceci trace l'événement technique lui-même — type, gravité
    — indépendamment de l'intervention humaine qui peut y répondre.
    """

    id: int | None = Field(default=None, primary_key=True)
    horodatage: str
    cellule_id: int
    type_defaut: str
    severite: str  # "critique" ou "avertissement"
    description: str
    # "actif" (pas encore pris en charge = demande d'intervention implicite),
    # "en_cours" (une intervention a eu lieu mais le problème persiste) ou
    # "resolu". Remplace l'ancien booléen "resolu" (cf. CHG-V2-057).
    statut: str = Field(default=DEFAUT_STATUT_ACTIF)


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
    session: Session,
    action: str,
    username_auteur: str,
    cellule_id: int,
    defaut_id: int | None = None,
    probleme_resolu: bool | None = None,
) -> HistoriqueMaintenance:
    """Ajoute et persiste une ligne d'historique de maintenance.

    ``defaut_id``/``probleme_resolu`` restent optionnels pour ne rien changer
    au comportement des appelants existants (demande d'intervention depuis le
    dashboard, actions du panneau de simulation) qui ne visent pas un défaut
    précis.
    """

    entry = HistoriqueMaintenance(
        horodatage=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        action=action,
        username_auteur=username_auteur,
        cellule_id=cellule_id,
        defaut_id=defaut_id,
        probleme_resolu=probleme_resolu,
    )
    session.add(entry)
    session.commit()
    session.refresh(entry)
    return entry


def list_history(
    session: Session,
    cellule_id: int | None = None,
    since: str | None = None,
    until: str | None = None,
    username_auteur: str | None = None,
) -> list[HistoriqueMaintenance]:
    """Retourne l'historique de maintenance, dans l'ordre chronologique.

    Filtre sur une cellule si ``cellule_id`` est fourni, et/ou sur une plage
    de dates (bornes incluses, format identique à ``horodatage``) si
    ``since``/``until`` sont fournis. Sans filtre, retourne l'historique
    complet de toutes les cellules (comportement inchangé pour les appelants
    existants). ``username_auteur`` restreint aux lignes créées par un
    utilisateur précis — utilisé pour qu'un Opérateur ne voie que ses propres
    demandes (cf. CHG-V2-066), le filtrage étant appliqué côté serveur (pas
    par le client) pour rester fiable.
    """

    query = select(HistoriqueMaintenance)
    if cellule_id is not None:
        query = query.where(HistoriqueMaintenance.cellule_id == cellule_id)
    if since is not None:
        query = query.where(HistoriqueMaintenance.horodatage >= since)
    if until is not None:
        query = query.where(HistoriqueMaintenance.horodatage <= until)
    if username_auteur is not None:
        query = query.where(HistoriqueMaintenance.username_auteur == username_auteur)
    query = query.order_by(HistoriqueMaintenance.id)
    return list(session.exec(query))


def add_axis_measure(
    session: Session,
    cellule_id: int,
    axe: int,
    temperature_c: float,
    courant_a: float,
    couple_nm: float,
    horodatage: str | None = None,
) -> MesureAxe:
    """Ajoute et persiste un relevé pour un axe d'une cellule."""

    entry = MesureAxe(
        horodatage=horodatage or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        cellule_id=cellule_id,
        axe=axe,
        temperature_c=temperature_c,
        courant_a=courant_a,
        couple_nm=couple_nm,
    )
    session.add(entry)
    session.commit()
    session.refresh(entry)
    return entry


def add_cell_measure(
    session: Session,
    cellule_id: int,
    pneumatic_pressure_bar: float,
    lubrix_level_pct: float,
    horodatage: str | None = None,
) -> MesureCellule:
    """Ajoute et persiste un relevé des grandeurs globales d'une cellule."""

    entry = MesureCellule(
        horodatage=horodatage or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        cellule_id=cellule_id,
        pneumatic_pressure_bar=pneumatic_pressure_bar,
        lubrix_level_pct=lubrix_level_pct,
    )
    session.add(entry)
    session.commit()
    session.refresh(entry)
    return entry


def list_axis_measures(
    session: Session, cellule_id: int, since: str
) -> list[MesureAxe]:
    """Retourne les relevés d'axes d'une cellule postérieurs à ``since``."""

    return list(
        session.exec(
            select(MesureAxe)
            .where(MesureAxe.cellule_id == cellule_id)
            .where(MesureAxe.horodatage >= since)
            .order_by(MesureAxe.horodatage)
        )
    )


def list_cell_measures(
    session: Session, cellule_id: int, since: str
) -> list[MesureCellule]:
    """Retourne les relevés globaux d'une cellule postérieurs à ``since``."""

    return list(
        session.exec(
            select(MesureCellule)
            .where(MesureCellule.cellule_id == cellule_id)
            .where(MesureCellule.horodatage >= since)
            .order_by(MesureCellule.horodatage)
        )
    )


def add_defaut(
    session: Session,
    cellule_id: int,
    type_defaut: str,
    severite: str,
    description: str,
    horodatage: str | None = None,
) -> DefautHistorique:
    """Ajoute et persiste un défaut dans l'historique."""

    entry = DefautHistorique(
        horodatage=horodatage or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        cellule_id=cellule_id,
        type_defaut=type_defaut,
        severite=severite,
        description=description,
        statut=DEFAUT_STATUT_ACTIF,
    )
    session.add(entry)
    session.commit()
    session.refresh(entry)
    return entry


def resolve_last_defaut(session: Session, cellule_id: int) -> DefautHistorique | None:
    """Marque le défaut non résolu le plus récent d'une cellule comme résolu.

    Utilisé par l'action "ack_fault" du panneau de simulation (POC), qui ne
    cible pas un défaut précis mais le plus récent non résolu de la cellule.
    Pour clôturer un défaut précis avec traçabilité de qui/pourquoi, voir
    ``add_maintenance_intervention``. Retourne l'entrée modifiée, ou None si
    aucun défaut non résolu n'existe pour cette cellule.
    """

    # DefautHistorique.id est un descripteur résolu à l'exécution : pylint
    # l'analyse statiquement comme un simple FieldInfo et ne voit donc pas sa
    # méthode .desc() (faux positif connu avec SQLModel).
    # pylint: disable=no-member
    entry = session.exec(
        select(DefautHistorique)
        .where(DefautHistorique.cellule_id == cellule_id)
        .where(DefautHistorique.statut != DEFAUT_STATUT_RESOLU)
        .order_by(DefautHistorique.id.desc())
    ).first()
    # pylint: enable=no-member
    if entry is None:
        return None
    entry.statut = DEFAUT_STATUT_RESOLU
    session.add(entry)
    session.commit()
    session.refresh(entry)
    return entry


def get_defaut(session: Session, defaut_id: int) -> DefautHistorique | None:
    """Recherche un défaut par son identifiant."""

    return session.get(DefautHistorique, defaut_id)


def set_defaut_statut(
    session: Session, defaut_id: int, statut: str
) -> DefautHistorique | None:
    """Force le statut d'un défaut précis. Retourne None si l'id est inconnu."""

    entry = session.get(DefautHistorique, defaut_id)
    if entry is None:
        return None
    entry.statut = statut
    session.add(entry)
    session.commit()
    session.refresh(entry)
    return entry


def add_maintenance_intervention(
    session: Session,
    username_auteur: str,
    defaut_id: int,
    notes: str,
    probleme_resolu: bool,
) -> HistoriqueMaintenance:
    """Enregistre une intervention de Maintenance sur un défaut précis.

    Crée la ligne d'historique traçant qui est intervenu, sur quel défaut, et
    avec quel résultat, ET met à jour le statut du défaut en conséquence :
    "resolu" si ``probleme_resolu`` est vrai, "en_cours" sinon (pris en
    charge mais toujours actif — cf. décision utilisateur CHG-V2-057).

    Lève ValueError si ``defaut_id`` ne correspond à aucun défaut existant :
    le contrôleur web_server.py traduit ceci en 404.
    """

    defaut = session.get(DefautHistorique, defaut_id)
    if defaut is None:
        raise ValueError(f"Défaut #{defaut_id} introuvable")

    resultat_label = "résolu" if probleme_resolu else "toujours actif"
    action = (
        f"Intervention sur le défaut #{defaut_id} ({defaut.type_defaut}) "
        f"— {resultat_label}"
    )
    if notes:
        action = f"{action}. Notes : {notes}"

    entry = add_history_entry(
        session,
        action=action,
        username_auteur=username_auteur,
        cellule_id=defaut.cellule_id,
        defaut_id=defaut_id,
        probleme_resolu=probleme_resolu,
    )

    defaut.statut = DEFAUT_STATUT_RESOLU if probleme_resolu else DEFAUT_STATUT_EN_COURS
    session.add(defaut)
    session.commit()
    # Ce second commit expire (par défaut SQLAlchemy) tous les objets déjà
    # chargés dans la session, y compris `entry` déjà retourné par
    # add_history_entry ci-dessus : sans ce refresh, le premier accès à un
    # attribut de `entry` par l'appelant lèverait DetachedInstanceError dès
    # que la session appelante se referme.
    session.refresh(entry)

    return entry


def list_defauts(
    session: Session,
    cellule_id: int | None = None,
    statut: str | None = None,
    since: str | None = None,
    until: str | None = None,
) -> list[DefautHistorique]:
    """Retourne l'historique des défauts, du plus récent au plus ancien.

    Filtre sur une cellule (``cellule_id``), un statut exact (``statut``,
    parmi DEFAUT_STATUTS) et/ou une plage de dates (bornes incluses) si ces
    paramètres sont fournis. Sans filtre, retourne l'historique complet de
    toutes les cellules (comportement inchangé pour les appelants existants).
    """

    query = select(DefautHistorique)
    if cellule_id is not None:
        query = query.where(DefautHistorique.cellule_id == cellule_id)
    if statut is not None:
        query = query.where(DefautHistorique.statut == statut)
    if since is not None:
        query = query.where(DefautHistorique.horodatage >= since)
    if until is not None:
        query = query.where(DefautHistorique.horodatage <= until)
    query = query.order_by(DefautHistorique.id.desc())  # pylint: disable=no-member
    return list(session.exec(query))
