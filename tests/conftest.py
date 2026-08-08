"""Pytest configuration: isolate the SQLite test database.

Ce conftest s'exécute avant l'import de src_v2.web_server / src_v2.security
par les modules de test (pytest importe les conftest.py avant de collecter
les tests du répertoire). On force SRC_DB_PATH vers un fichier temporaire
*avant* que src_v2.db ne crée son moteur SQLAlchemy, pour ne jamais toucher
au fichier smart_robotic_cell.db utilisé par le serveur réel.
"""

from __future__ import annotations

import os
import tempfile

_TMP_DB_FD, _TMP_DB_PATH = tempfile.mkstemp(suffix=".db", prefix="src_v2_test_")
os.close(_TMP_DB_FD)
os.environ["SRC_DB_PATH"] = _TMP_DB_PATH
