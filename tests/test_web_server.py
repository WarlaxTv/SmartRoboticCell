from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from src_v2 import db, opcua_client, web_server


def _auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _make_token(username: str, role: str) -> str:
    return web_server.create_access_token({"sub": username, "role": role})


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    async def _fake_fetch_opcua_data() -> list[dict[str, Any]]:
        return [
            {
                "id": 1,
                "name": "CELL1",
                "type": "ROBOT",
                "ip": "127.0.0.1",
                "state": "EN_PRODUCTION",
                "fault": False,
                "progress": 10.0,
                "alarms": "",
                "maint_req": False,
                "time_to_maint": 100,
                "pneumatic_pressure": 6.2,
                "pneumatic_state": True,
                "lubrix_level": 90,
                "temp_axes": 40.0,
                "vibration": 1.0,
                "speed": 90.0,
            }
        ]

    monkeypatch.setattr(web_server, "fetch_opcua_data", _fake_fetch_opcua_data)
    return TestClient(web_server.app)


def test_token_success(client: TestClient) -> None:
    resp = client.post(
        "/token",
        data={"username": "jean_ope", "password": "ope123"},
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "access_token" in body
    assert body["role"] == "OPERATEUR"


def test_token_invalid_credentials(client: TestClient) -> None:
    resp = client.post(
        "/token",
        data={"username": "jean_ope", "password": "wrong"},
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 401


def test_status_requires_auth(client: TestClient) -> None:
    resp = client.get("/api/status")
    assert resp.status_code in {401, 403}


def test_status_ok(client: TestClient) -> None:
    token = _make_token("jean_ope", "OPERATEUR")
    resp = client.get("/api/status", headers=_auth_header(token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert isinstance(body["cells"], list)


def test_status_ok_when_opcua_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _failing_fetch() -> list[dict[str, Any]]:
        raise RuntimeError("opcua down")

    async def _safe_fetch() -> list[dict[str, Any]]:
        try:
            return await _failing_fetch()
        except Exception:
            return []

    monkeypatch.setattr(web_server, "fetch_opcua_data", _safe_fetch)
    client = TestClient(web_server.app)

    token = _make_token("jean_ope", "OPERATEUR")
    resp = client.get("/api/status", headers=_auth_header(token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["cells"] == []


def test_read_root_serves_dashboard(client: TestClient) -> None:
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")


def test_simu_action_forbidden_for_operator(client: TestClient) -> None:
    token = _make_token("jean_ope", "OPERATEUR")
    resp = client.post(
        "/api/simu/action?cell_id=1&action=force_maint",
        headers=_auth_header(token),
    )
    assert resp.status_code == 403


def test_simu_action_allowed_for_maintenance(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeNode:
        async def get_child(self, *_args: Any, **_kwargs: Any) -> _FakeNode:
            return self

        async def write_value(self, *_args: Any, **_kwargs: Any) -> None:
            return None

    class _FakeClient:
        def __init__(self, url: str):
            self.url = url
            self.nodes = type("_Nodes", (), {"objects": _FakeNode()})()

        async def __aenter__(self) -> _FakeClient:
            return self

        async def __aexit__(self, *_exc: Any) -> None:
            return None

        async def get_namespace_index(self, *_args: Any, **_kwargs: Any) -> int:
            return 2

    monkeypatch.setattr(opcua_client, "Client", _FakeClient)
    client = TestClient(web_server.app)

    token = _make_token("luc_maint", "MAINTENANCE")
    resp = client.post(
        "/api/simu/action?cell_id=1&action=force_maint",
        headers=_auth_header(token),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_simu_action_all_branches(monkeypatch: pytest.MonkeyPatch) -> None:
    class _VarNode:
        def __init__(self, name: str, values: dict[str, Any]):
            self._name = name
            self._values = values

        async def write_value(self, data_value: Any) -> None:
            # asyncua.DataValue/Variant est opaque ici.
            # On vérifie juste qu'une écriture a eu lieu.
            self._values[self._name] = data_value

    class _CellNode:
        def __init__(self, values: dict[str, Any]):
            self._values = values

        async def get_child(self, child: str) -> _VarNode:
            # child looks like "2:Etat"; keep the browse name after ':'
            name = child.split(":", 1)[1] if ":" in child else child
            return _VarNode(name, self._values)

    class _ObjectsNode:
        def __init__(self, cell_values: dict[str, Any]):
            self._cell_values = cell_values

        async def get_child(self, path: list[str]) -> _CellNode:
            # path ends with "2:CelluleRobotique_<id>"
            cell_browse = path[-1]
            cell_id = int(cell_browse.rsplit("_", 1)[1])
            key = f"cell_{cell_id}"
            self._cell_values.setdefault(key, {})
            return _CellNode(self._cell_values[key])

    class _FakeClient:
        def __init__(self, url: str):
            self.url = url
            self._values: dict[str, Any] = {}
            self.nodes = type("_Nodes", (), {"objects": _ObjectsNode(self._values)})()

        async def __aenter__(self) -> _FakeClient:
            return self

        async def __aexit__(self, *_exc: Any) -> None:
            return None

        async def get_namespace_index(self, *_args: Any, **_kwargs: Any) -> int:
            return 2

    monkeypatch.setattr(opcua_client, "Client", _FakeClient)
    client = TestClient(web_server.app)
    token = _make_token("luc_maint", "MAINTENANCE")

    # "ack_maint" est exclu de cette boucle générique : depuis CHG-V2-070, il
    # exige que la maintenance soit réellement due (cf. tests dédiés
    # test_simu_action_ack_maint_*), ce que ce fake client ne simule pas.
    for action in ("force_fault", "force_maint", "ack_fault"):
        resp = client.post(
            f"/api/simu/action?cell_id=1&action={action}",
            headers=_auth_header(token),
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


def test_simu_action_ack_maint_rejected_when_not_due(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CHG-V2-070 : "Faire la maintenance" / "Maintenance effectuée" ne doit
    pas fonctionner tant que le compteur n'a pas réellement atteint 0."""

    async def _not_due(_cell_id: int) -> bool:
        return False

    async def _apply(_cell_id: int, _action: str) -> None:
        raise AssertionError(
            "apply_simulated_action ne doit pas être appelé quand la "
            "maintenance n'est pas due"
        )

    monkeypatch.setattr(web_server, "is_maintenance_due", _not_due)
    monkeypatch.setattr(web_server, "apply_simulated_action", _apply)
    client = TestClient(web_server.app)
    token = _make_token("luc_maint", "MAINTENANCE")

    resp = client.post(
        "/api/simu/action?cell_id=1&action=ack_maint",
        headers=_auth_header(token),
    )
    assert resp.status_code == 409


def test_simu_action_ack_maint_allowed_when_due(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _due(_cell_id: int) -> bool:
        return True

    calls: list[tuple[int, str]] = []

    async def _apply(cell_id: int, action: str) -> None:
        calls.append((cell_id, action))

    monkeypatch.setattr(web_server, "is_maintenance_due", _due)
    monkeypatch.setattr(web_server, "apply_simulated_action", _apply)
    client = TestClient(web_server.app)
    token = _make_token("luc_maint", "MAINTENANCE")

    resp = client.post(
        "/api/simu/action?cell_id=1&action=ack_maint",
        headers=_auth_header(token),
    )
    assert resp.status_code == 200
    assert calls == [(1, "ack_maint")]


def test_status_includes_active_issues_grouped_by_cell(client: TestClient) -> None:
    """Round 6 : le badge d'alerte du dashboard (visible sans ouvrir la vue
    détaillée) s'appuie sur data.active_issues, une agrégation par cellule
    des défauts non résolus (compte + sévérité max)."""

    with Session(db.engine) as session:
        db.add_defaut(
            session,
            cellule_id=131,
            type_defaut=web_server.MAINTENANCE_REPORTED_ISSUE_TYPE,
            severite="avertissement",
            description="Bruit anormal",
        )
        resolved_id = db.add_defaut(
            session,
            cellule_id=131,
            type_defaut=web_server.MAINTENANCE_REPORTED_ISSUE_TYPE,
            severite="critique",
            description="Déjà réglé",
        ).id
        db.set_defaut_statut(session, resolved_id, db.DEFAUT_STATUT_RESOLU)

    token = _make_token("jean_ope", "OPERATEUR")
    resp = client.get("/api/status", headers=_auth_header(token))
    assert resp.status_code == 200
    active_issues = resp.json()["active_issues"]
    # Le défaut résolu ne doit pas compter ; seul l'avertissement actif reste.
    assert active_issues["131"] == {"count": 1, "max_severity": "avertissement"}


def test_ack_maint_does_not_clear_operator_generic_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Round 6 : "Faire la maintenance" (ack_maint, compteur à 0) est
    indépendant d'une demande générique d'intervention lancée par
    l'Opérateur — clore l'un ne doit pas effacer l'autre (bug signalé :
    "ça dit que j'ai aussi fait la demande de maintenance de l'opérateur
    ce qui n'est pas forcément le cas")."""

    async def _due(_cell_id: int) -> bool:
        return True

    async def _apply(_cell_id: int, _action: str) -> None:
        return None

    monkeypatch.setattr(web_server, "is_maintenance_due", _due)
    monkeypatch.setattr(web_server, "apply_simulated_action", _apply)
    client = TestClient(web_server.app)

    op_token = _make_token("jean_ope", "OPERATEUR")
    client.post(
        "/api/maintenance/request?cell_id=32&message=Bruit",
        headers=_auth_header(op_token),
    )

    maint_token = _make_token("luc_maint", "MAINTENANCE")
    resp = client.post(
        "/api/simu/action?cell_id=32&action=ack_maint",
        headers=_auth_header(maint_token),
    )
    assert resp.status_code == 200

    status_after = client.get("/api/status", headers=_auth_header(op_token)).json()
    assert status_after["maint_requests"].get("32") == {
        "username": "jean_ope",
        "message": "Bruit",
    }


def test_ack_fault_blocked_when_manual_critical_issue_active(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Round 6 : "Acquitter le défaut" du panneau de simulation POC ne doit
    PAS lever une anomalie critique signalée par la Maintenance — seul le
    bouton "Intervenir" dédié doit pouvoir le faire."""

    async def _apply(_cell_id: int, _action: str) -> None:
        raise AssertionError(
            "apply_simulated_action ne doit pas être appelé : ack_fault doit "
            "être bloqué par une anomalie critique Maintenance active"
        )

    monkeypatch.setattr(web_server, "apply_simulated_action", _apply)

    with Session(db.engine) as session:
        db.add_defaut(
            session,
            cellule_id=33,
            type_defaut=web_server.MAINTENANCE_REPORTED_ISSUE_TYPE,
            severite="critique",
            description="Fuite hydraulique critique",
        )

    client = TestClient(web_server.app)
    token = _make_token("luc_maint", "MAINTENANCE")
    resp = client.post(
        "/api/simu/action?cell_id=33&action=ack_fault",
        headers=_auth_header(token),
    )
    assert resp.status_code == 409


def test_ack_fault_allowed_for_poc_test_fault(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un défaut simulé via le panneau POC (force_fault) reste bien
    acquittable normalement : seule une anomalie critique signalée par la
    Maintenance bloque ack_fault."""

    calls: list[tuple[int, str]] = []

    async def _apply(cell_id: int, action: str) -> None:
        calls.append((cell_id, action))

    monkeypatch.setattr(web_server, "apply_simulated_action", _apply)

    with Session(db.engine) as session:
        db.add_defaut(
            session,
            cellule_id=34,
            type_defaut=web_server.FAULT_TYPE_MANUAL,
            severite="critique",
            description="Défaut forcé depuis le panneau de simulation (POC).",
        )

    client = TestClient(web_server.app)
    token = _make_token("luc_maint", "MAINTENANCE")
    resp = client.post(
        "/api/simu/action?cell_id=34&action=ack_fault",
        headers=_auth_header(token),
    )
    assert resp.status_code == 200
    assert calls == [(34, "ack_fault")]


def test_report_issue_critical_triggers_opcua_fault(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CHG-V2-070 : un signalement critique doit mettre la cellule à l'arrêt
    côté OPC UA (comme un défaut réel), pas seulement créer une ligne
    d'historique."""

    calls: list[tuple[int, str]] = []

    async def _fake_report_manual_fault(cell_id: int, alarm_text: str) -> None:
        calls.append((cell_id, alarm_text))

    monkeypatch.setattr(web_server, "report_manual_fault", _fake_report_manual_fault)
    token = _make_token("luc_maint", "MAINTENANCE")

    resp = client.post(
        "/api/maintenance/report-issue"
        "?cell_id=7&description=Fuite%20critique&severity=critique",
        headers=_auth_header(token),
    )
    assert resp.status_code == 200
    assert calls == [(7, "Fuite critique")]


def test_report_issue_warning_does_not_trigger_opcua_fault(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[int, str]] = []

    async def _fake_report_manual_fault(cell_id: int, alarm_text: str) -> None:
        calls.append((cell_id, alarm_text))

    monkeypatch.setattr(web_server, "report_manual_fault", _fake_report_manual_fault)
    token = _make_token("luc_maint", "MAINTENANCE")

    resp = client.post(
        "/api/maintenance/report-issue"
        "?cell_id=7&description=Petit%20souci&severity=avertissement",
        headers=_auth_header(token),
    )
    assert resp.status_code == 200
    assert calls == []


def test_report_issue_critical_resilient_to_opcua_failure(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Une panne OPC UA ponctuelle ne doit pas empêcher la persistance du
    défaut en base (source de vérité pour l'audit)."""

    async def _failing(_cell_id: int, _alarm_text: str) -> None:
        raise RuntimeError("opcua down")

    monkeypatch.setattr(web_server, "report_manual_fault", _failing)
    token = _make_token("luc_maint", "MAINTENANCE")

    resp = client.post(
        "/api/maintenance/report-issue"
        "?cell_id=7&description=Fuite&severity=critique",
        headers=_auth_header(token),
    )
    assert resp.status_code == 200


def test_intervention_resolves_critical_maintenance_issue_clears_opcua_fault(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Résoudre le dernier signalement critique de la Maintenance doit lever
    l'état de défaut OPC UA qu'il avait déclenché (CHG-V2-070)."""

    calls: list[tuple[int, str]] = []

    async def _fake_apply(cell_id: int, action: str) -> None:
        calls.append((cell_id, action))

    monkeypatch.setattr(web_server, "apply_simulated_action", _fake_apply)

    with Session(db.engine) as session:
        defaut_id = db.add_defaut(
            session,
            cellule_id=21,
            type_defaut=web_server.MAINTENANCE_REPORTED_ISSUE_TYPE,
            severite="critique",
            description="Fuite hydraulique",
        ).id

    token = _make_token("luc_maint", "MAINTENANCE")
    resp = client.post(
        f"/api/maintenance/intervention?defaut_id={defaut_id}"
        "&probleme_resolu=true&notes=Réparée",
        headers=_auth_header(token),
    )
    assert resp.status_code == 200
    assert calls == [(21, "ack_fault")]


def test_intervention_does_not_clear_opcua_fault_if_other_critical_issue_remains(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[int, str]] = []

    async def _fake_apply(cell_id: int, action: str) -> None:
        calls.append((cell_id, action))

    monkeypatch.setattr(web_server, "apply_simulated_action", _fake_apply)

    with Session(db.engine) as session:
        first_id = db.add_defaut(
            session,
            cellule_id=22,
            type_defaut=web_server.MAINTENANCE_REPORTED_ISSUE_TYPE,
            severite="critique",
            description="Problème A",
        ).id
        db.add_defaut(
            session,
            cellule_id=22,
            type_defaut=web_server.MAINTENANCE_REPORTED_ISSUE_TYPE,
            severite="critique",
            description="Problème B",
        )

    token = _make_token("luc_maint", "MAINTENANCE")
    resp = client.post(
        f"/api/maintenance/intervention?defaut_id={first_id}&probleme_resolu=true",
        headers=_auth_header(token),
    )
    assert resp.status_code == 200
    assert calls == []


def test_intervention_resolving_non_critical_type_does_not_touch_opcua(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[int, str]] = []

    async def _fake_apply(cell_id: int, action: str) -> None:
        calls.append((cell_id, action))

    monkeypatch.setattr(web_server, "apply_simulated_action", _fake_apply)

    with Session(db.engine) as session:
        defaut_id = db.add_defaut(
            session,
            cellule_id=23,
            type_defaut="Autre type de défaut",
            severite="critique",
            description="Test",
        ).id

    token = _make_token("luc_maint", "MAINTENANCE")
    resp = client.post(
        f"/api/maintenance/intervention?defaut_id={defaut_id}&probleme_resolu=true",
        headers=_auth_header(token),
    )
    assert resp.status_code == 200
    assert calls == []


def test_opcua_report_manual_fault_writes_expected_nodes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Vérifie au niveau OPC UA que report_manual_fault() écrit bien le même
    état qu'un défaut classique (EnDefaut/Etat/AlarmesActives/
    ProgressionCycle), avec le texte d'alarme fourni (CHG-V2-070)."""

    class _VarNode:
        def __init__(self, name: str, values: dict[str, Any]):
            self._name = name
            self._values = values

        async def write_value(self, data_value: Any) -> None:
            self._values[self._name] = data_value.Value.Value

    class _CellNode:
        def __init__(self, values: dict[str, Any]):
            self._values = values

        async def get_child(self, child: str) -> _VarNode:
            name = child.split(":", 1)[1] if ":" in child else child
            return _VarNode(name, self._values)

    class _ObjectsNode:
        def __init__(self, values: dict[str, Any]):
            self._values = values

        async def get_child(self, _path: list[str]) -> _CellNode:
            return _CellNode(self._values)

    class _FakeClient:
        def __init__(self, url: str):
            self.url = url
            self.written: dict[str, Any] = {}
            self.nodes = type("_Nodes", (), {"objects": _ObjectsNode(self.written)})()

        async def __aenter__(self) -> _FakeClient:
            return self

        async def __aexit__(self, *_exc: Any) -> None:
            return None

        async def get_namespace_index(self, *_args: Any, **_kwargs: Any) -> int:
            return 2

    captured: dict[str, Any] = {}

    class _CapturingClient(_FakeClient):
        def __init__(self, url: str):
            super().__init__(url)
            captured["instance"] = self

    monkeypatch.setattr(opcua_client, "Client", _CapturingClient)

    asyncio.run(opcua_client.report_manual_fault(5, "Fuite hydraulique visible"))

    written = captured["instance"].written
    assert written["EnDefaut"] is True
    assert written["Etat"] == "DEFAUT"
    assert written["AlarmesActives"] == "Fuite hydraulique visible"
    assert written["ProgressionCycle"] == 0.0


def test_opcua_is_maintenance_due(monkeypatch: pytest.MonkeyPatch) -> None:
    class _ReadVar:
        def __init__(self, value: Any):
            self._value = value

        async def read_value(self) -> Any:
            return self._value

    class _CellNode:
        def __init__(self, value: Any):
            self._value = value

        async def get_child(self, _child: str) -> _ReadVar:
            return _ReadVar(self._value)

    class _ObjectsNode:
        def __init__(self, value: Any):
            self._value = value

        async def get_child(self, _path: list[str]) -> _CellNode:
            return _CellNode(self._value)

    def _make_client(value: bool) -> type:
        class _FakeClient:
            def __init__(self, url: str):
                self.url = url
                self.nodes = type("_Nodes", (), {"objects": _ObjectsNode(value)})()

            async def __aenter__(self) -> _FakeClient:
                return self

            async def __aexit__(self, *_exc: Any) -> None:
                return None

            async def get_namespace_index(self, *_args: Any, **_kwargs: Any) -> int:
                return 2

        return _FakeClient

    monkeypatch.setattr(opcua_client, "Client", _make_client(True))
    assert asyncio.run(opcua_client.is_maintenance_due(1)) is True

    monkeypatch.setattr(opcua_client, "Client", _make_client(False))
    assert asyncio.run(opcua_client.is_maintenance_due(1)) is False


def test_opcua_is_maintenance_due_defaults_false_on_read_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FailingClient:
        def __init__(self, url: str):
            self.url = url

        async def __aenter__(self) -> _FailingClient:
            return self

        async def __aexit__(self, *_exc: Any) -> None:
            return None

        async def get_namespace_index(self, *_args: Any, **_kwargs: Any) -> int:
            raise RuntimeError("opcua down")

    monkeypatch.setattr(opcua_client, "Client", _FailingClient)
    assert asyncio.run(opcua_client.is_maintenance_due(1)) is False


def test_fetch_opcua_data_success(monkeypatch: pytest.MonkeyPatch) -> None:
    class _ReadVar:
        def __init__(self, value: Any):
            self._value = value

        async def read_value(self) -> Any:
            return self._value

    class _CellNode:
        def __init__(self, cell_id: int):
            self._cell_id = cell_id

        async def get_child(self, child: str) -> _ReadVar:
            name = child.split(":", 1)[1] if ":" in child else child
            mapping: dict[str, Any] = {
                "Etat": "EN_PRODUCTION",
                "EnDefaut": False,
                "TypeRobot": "ROBOT",
                "NomCellule": f"CELL{self._cell_id}",
                "AdresseIP": "127.0.0.1",
                "ProgressionCycle": 50.0,
                "AlarmesActives": "",
                "MaintenanceRequise": False,
                "HeuresAvantMaintenance": 123,
                "PressionPneumatique": 6.2,
                "BridageActif": True,
                "NiveauLubrifiant": 90,
                "TemperatureAxes": 40.0,
                "NiveauVibration": 1.2,
                "VitesseCycle": 95.0,
            }
            return _ReadVar(mapping[name])

    class _SupervisionNode:
        async def get_child(self, child: str) -> _CellNode:
            cell_id = int(child.rsplit("_", 1)[1])
            return _CellNode(cell_id)

    class _ObjectsNode:
        async def get_child(self, _child: str) -> _SupervisionNode:
            return _SupervisionNode()

    class _FakeClient:
        def __init__(self, url: str):
            self.url = url
            self.nodes = type("_Nodes", (), {"objects": _ObjectsNode()})()

        async def __aenter__(self) -> _FakeClient:
            return self

        async def __aexit__(self, *_exc: Any) -> None:
            return None

        async def get_namespace_index(self, *_args: Any, **_kwargs: Any) -> int:
            return 2

    monkeypatch.setattr(opcua_client, "Client", _FakeClient)
    data = asyncio.run(web_server.fetch_opcua_data())
    assert len(data) == 3
    assert data[0]["name"] == "CELL1"
    assert data[2]["id"] == 3
    assert data[0]["speed"] == 95.0


def test_operator_can_request_maintenance(client: TestClient) -> None:
    token = _make_token("jean_ope", "OPERATEUR")
    resp = client.post(
        "/api/maintenance/request?cell_id=1",
        headers=_auth_header(token),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"


def test_operator_can_read_only_their_own_maintenance_history(
    client: TestClient,
) -> None:
    """CHG-V2-066 : un Opérateur peut lire /api/maintenance/history, mais ne
    doit voir que les lignes qu'il a lui-même créées, jamais celles d'un
    autre utilisateur (opérateur ou Maintenance).
    """
    with Session(db.engine) as session:
        session.add(
            db.Utilisateur(
                username="marie_ope",
                password_hash="unused-in-test",  # noqa: S106 - not a real credential
                role="OPERATEUR",
            )
        )
        session.commit()

    jean_token = _make_token("jean_ope", "OPERATEUR")
    marie_token = _make_token("marie_ope", "OPERATEUR")
    client.post("/api/maintenance/request?cell_id=1", headers=_auth_header(jean_token))
    client.post("/api/maintenance/request?cell_id=2", headers=_auth_header(marie_token))

    resp = client.get("/api/maintenance/history", headers=_auth_header(jean_token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert len(body["history"]) > 0
    assert all(item["user"] == "jean_ope" for item in body["history"])
    assert not any(item["user"] == "marie_ope" for item in body["history"])


def test_maintenance_can_read_history_after_request(client: TestClient) -> None:
    op_token = _make_token("jean_ope", "OPERATEUR")
    client.post(
        "/api/maintenance/request?cell_id=2",
        headers=_auth_header(op_token),
    )

    maint_token = _make_token("luc_maint", "MAINTENANCE")
    resp = client.get("/api/maintenance/history", headers=_auth_header(maint_token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert isinstance(body["history"], list)
    assert any("Cellule 2" in item.get("action", "") for item in body["history"])


def test_maintenance_history_filters_by_cell_id(client: TestClient) -> None:
    """La page de détail d'une cellule ne doit voir que ses propres
    interventions : /api/maintenance/history?cell_id=X doit filtrer, sans
    casser l'appel sans filtre (utilisé par la page dédiée toutes cellules).
    """

    op_token = _make_token("jean_ope", "OPERATEUR")
    client.post("/api/maintenance/request?cell_id=1", headers=_auth_header(op_token))
    client.post("/api/maintenance/request?cell_id=3", headers=_auth_header(op_token))

    maint_token = _make_token("luc_maint", "MAINTENANCE")
    resp = client.get(
        "/api/maintenance/history?cell_id=1", headers=_auth_header(maint_token)
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert len(body["history"]) > 0
    assert all(item["cell_id"] == 1 for item in body["history"])
    assert not any("Cellule 3" in item.get("action", "") for item in body["history"])


def test_operator_can_request_maintenance_with_message(client: TestClient) -> None:
    op_token = _make_token("jean_ope", "OPERATEUR")
    resp = client.post(
        "/api/maintenance/request?cell_id=7&message=Bruit anormal sur l'axe 3",
        headers=_auth_header(op_token),
    )
    assert resp.status_code == 200

    maint_token = _make_token("luc_maint", "MAINTENANCE")
    history = client.get(
        "/api/maintenance/history", headers=_auth_header(maint_token)
    ).json()
    assert any(
        "Bruit anormal sur l'axe 3" in item.get("action", "")
        for item in history["history"]
    )


def test_generic_request_appears_in_status_until_acknowledged(
    client: TestClient,
) -> None:
    op_token = _make_token("jean_ope", "OPERATEUR")
    client.post(
        "/api/maintenance/request?cell_id=8&message=Bruit%20suspect",
        headers=_auth_header(op_token),
    )

    status_before = client.get("/api/status", headers=_auth_header(op_token)).json()
    assert status_before["maint_requests"].get("8") == {
        "username": "jean_ope",
        "message": "Bruit suspect",
    }

    maint_token = _make_token("luc_maint", "MAINTENANCE")
    ack_resp = client.post(
        "/api/maintenance/acknowledge-request?cell_id=8&message=Vérifié%2C%20RAS",
        headers=_auth_header(maint_token),
    )
    assert ack_resp.status_code == 200
    assert ack_resp.json()["status"] == "ok"

    status_after = client.get("/api/status", headers=_auth_header(op_token)).json()
    assert "8" not in status_after["maint_requests"]

    history = client.get(
        "/api/maintenance/history", headers=_auth_header(maint_token)
    ).json()
    ack_entry = next(
        (
            item
            for item in history["history"]
            if "Prise en charge" in item.get("action", "") and item.get("cell_id") == 8
        ),
        None,
    )
    assert ack_entry is not None
    assert "Bruit suspect" in ack_entry["action"]
    assert "Vérifié, RAS" in ack_entry["action"]


def test_acknowledge_request_forbidden_for_operator(client: TestClient) -> None:
    op_token = _make_token("jean_ope", "OPERATEUR")
    resp = client.post(
        "/api/maintenance/acknowledge-request?cell_id=8",
        headers=_auth_header(op_token),
    )
    assert resp.status_code == 403


def test_acknowledge_unknown_request_returns_404(client: TestClient) -> None:
    maint_token = _make_token("luc_maint", "MAINTENANCE")
    resp = client.post(
        "/api/maintenance/acknowledge-request?cell_id=42",
        headers=_auth_header(maint_token),
    )
    assert resp.status_code == 404


def test_read_cell_detail_serves_html(client: TestClient) -> None:
    resp = client.get("/cell/1")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")


def test_read_maintenance_history_page_serves_html(client: TestClient) -> None:
    resp = client.get("/historique-maintenance")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")


def test_read_fault_history_page_serves_html(client: TestClient) -> None:
    resp = client.get("/historique-pannes")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")


def test_read_data_comparison_page_serves_html(client: TestClient) -> None:
    resp = client.get("/donnees")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")


def test_static_chart_js_is_served_locally(client: TestClient) -> None:
    """Chart.js doit être servi localement (pas via un CDN externe) : un poste
    de supervision industrielle peut tourner sans accès Internet sortant."""
    resp = client.get("/static/chart.umd.js")
    assert resp.status_code == 200
    assert "Chart" in resp.text


def test_get_cell_axes_readable_by_operator(
    monkeypatch: pytest.MonkeyPatch, client: TestClient
) -> None:
    """Round 6 : la vue détaillée de la cellule (dont les axes moteurs en
    direct) est ouverte en lecture à l'Opérateur, comme le reste de la page
    /cell/{id} (cf. décision utilisateur : "il faudrait que les opérateurs
    aient accès aux vues détaillées des cellules")."""

    async def _fake_fetch_axis_data(_cell_id: int) -> list[dict[str, Any]]:
        return [{"axe": 1, "temperature_c": 30.0, "courant_a": 1.0, "couple_nm": 5.0}]

    monkeypatch.setattr(web_server, "fetch_axis_data", _fake_fetch_axis_data)
    token = _make_token("jean_ope", "OPERATEUR")
    resp = client.get("/api/cell/1/axes", headers=_auth_header(token))
    assert resp.status_code == 200


def test_get_cell_axes_ok(monkeypatch: pytest.MonkeyPatch, client: TestClient) -> None:
    async def _fake_fetch_axis_data(_cell_id: int) -> list[dict[str, Any]]:
        return [
            {
                "axe": i,
                "temperature_c": 30.0 + i,
                "courant_a": 1.0 + i * 0.1,
                "couple_nm": 5.0 + i,
            }
            for i in range(1, 7)
        ]

    monkeypatch.setattr(web_server, "fetch_axis_data", _fake_fetch_axis_data)
    token = _make_token("luc_maint", "MAINTENANCE")
    resp = client.get("/api/cell/1/axes", headers=_auth_header(token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert len(body["axes"]) == 6
    assert body["axes"][0]["axe"] == 1


def test_get_cell_measures_ok(client: TestClient) -> None:
    with Session(db.engine) as session:
        db.add_axis_measure(
            session,
            cellule_id=7,
            axe=1,
            temperature_c=41.0,
            courant_a=1.2,
            couple_nm=8.0,
            horodatage="2026-08-19 08:00:00",
        )
        db.add_cell_measure(
            session,
            cellule_id=7,
            pneumatic_pressure_bar=6.0,
            lubrix_level_pct=80.0,
            horodatage="2026-08-19 08:00:00",
        )

    token = _make_token("luc_maint", "MAINTENANCE")
    # hours volontairement énorme pour couvrir la mesure insérée ci-dessus
    # quelle que soit la date système au moment du test.
    resp = client.get("/api/cell/7/measures?hours=999999", headers=_auth_header(token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert len(body["axis_measures"]) == 1
    assert body["axis_measures"][0]["temperature_c"] == 41.0
    assert len(body["cell_measures"]) == 1
    assert body["cell_measures"][0]["pneumatic_pressure_bar"] == 6.0


def test_get_cell_measures_readable_by_operator(client: TestClient) -> None:
    """Round 6 : mêmes raisons que test_get_cell_axes_readable_by_operator —
    les courbes de la vue détaillée doivent aussi être consultables par
    l'Opérateur (lecture seule, aucune action de résolution)."""
    token = _make_token("jean_ope", "OPERATEUR")
    resp = client.get("/api/cell/1/measures", headers=_auth_header(token))
    assert resp.status_code == 200


def test_get_faults_history_ok(client: TestClient) -> None:
    with Session(db.engine) as session:
        db.add_defaut(
            session,
            cellule_id=8,
            type_defaut="Test défaut historique",
            severite="critique",
            description="Créé par test_get_faults_history_ok",
            horodatage="2026-08-19 08:00:00",
        )

    token = _make_token("luc_maint", "MAINTENANCE")
    resp = client.get("/api/faults/history?cell_id=8", headers=_auth_header(token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert any(f["type"] == "Test défaut historique" for f in body["faults"])


def test_get_faults_history_readable_by_operator(client: TestClient) -> None:
    """CHG-V2-066 : l'Opérateur doit pouvoir consulter l'historique des
    défauts (lecture seule) ; seules les actions d'intervention restent
    réservées à la Maintenance.
    """
    token = _make_token("jean_ope", "OPERATEUR")
    resp = client.get("/api/faults/history", headers=_auth_header(token))
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_get_faults_history_filters_by_status_and_date(client: TestClient) -> None:
    with Session(db.engine) as session:
        db.add_defaut(
            session,
            cellule_id=9,
            type_defaut="Défaut filtré par statut",
            severite="critique",
            description="...",
            horodatage="2026-08-19 08:00:00",
        )
        resolu_id = db.add_defaut(
            session,
            cellule_id=9,
            type_defaut="Défaut déjà résolu",
            severite="avertissement",
            description="...",
            horodatage="2026-01-01 08:00:00",
        ).id
        db.set_defaut_statut(session, resolu_id, db.DEFAUT_STATUT_RESOLU)

    token = _make_token("luc_maint", "MAINTENANCE")

    resp = client.get(
        "/api/faults/history?cell_id=9&fault_status=actif",
        headers=_auth_header(token),
    )
    assert resp.status_code == 200
    types = {f["type"] for f in resp.json()["faults"]}
    assert types == {"Défaut filtré par statut"}

    resp = client.get(
        "/api/faults/history?cell_id=9&since=2026-08-01%2000:00:00",
        headers=_auth_header(token),
    )
    assert resp.status_code == 200
    types = {f["type"] for f in resp.json()["faults"]}
    assert types == {"Défaut filtré par statut"}


def test_maintenance_intervention_resolves_defaut_and_appears_in_history(
    client: TestClient,
) -> None:
    """Le workflow bout en bout de la TODO list ("Autre") : la Maintenance
    choisit un défaut précis, le déclare résolu via l'API, et cela doit se
    répercuter à la fois sur /api/faults/history (statut) et
    /api/maintenance/history (nouvelle ligne tracée)."""

    with Session(db.engine) as session:
        defaut_id = db.add_defaut(
            session,
            cellule_id=11,
            type_defaut="Défaut pour intervention API",
            severite="critique",
            description="...",
        ).id

    token = _make_token("luc_maint", "MAINTENANCE")
    resp = client.post(
        f"/api/maintenance/intervention?defaut_id={defaut_id}"
        "&probleme_resolu=true&notes=Capteur remplacé",
        headers=_auth_header(token),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

    faults_resp = client.get(
        "/api/faults/history?cell_id=11", headers=_auth_header(token)
    )
    faults = faults_resp.json()["faults"]
    assert any(f["id"] == defaut_id and f["fault_status"] == "resolu" for f in faults)

    history_resp = client.get(
        "/api/maintenance/history?cell_id=11", headers=_auth_header(token)
    )
    history = history_resp.json()["history"]
    assert any(
        item["defaut_id"] == defaut_id and item["probleme_resolu"] is True
        for item in history
    )


def test_maintenance_intervention_forbidden_for_operator(client: TestClient) -> None:
    token = _make_token("jean_ope", "OPERATEUR")
    resp = client.post(
        "/api/maintenance/intervention?defaut_id=1&probleme_resolu=true",
        headers=_auth_header(token),
    )
    assert resp.status_code == 403


def test_maintenance_intervention_unknown_defaut_returns_404(
    client: TestClient,
) -> None:
    token = _make_token("luc_maint", "MAINTENANCE")
    resp = client.post(
        "/api/maintenance/intervention?defaut_id=999999&probleme_resolu=true",
        headers=_auth_header(token),
    )
    assert resp.status_code == 404


def test_maintenance_can_report_issue(client: TestClient) -> None:
    """CHG-V2-065 : la Maintenance peut signaler elle-même un problème sur
    une cellule (sans attendre un défaut OPC UA ou une demande opérateur) ;
    le défaut créé apparaît ensuite dans l'historique des défauts.
    """
    token = _make_token("luc_maint", "MAINTENANCE")
    resp = client.post(
        "/api/maintenance/report-issue"
        "?cell_id=9&description=Fuite%20hydraulique%20visible&severity=critique",
        headers=_auth_header(token),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["id"] is not None

    faults = client.get(
        "/api/faults/history?cell_id=9", headers=_auth_header(token)
    ).json()
    assert any(
        f["description"] == "Fuite hydraulique visible"
        and f["severity"] == "critique"
        and f["fault_status"] == "actif"
        for f in faults["faults"]
    )


def test_report_issue_rejects_invalid_severity(client: TestClient) -> None:
    token = _make_token("luc_maint", "MAINTENANCE")
    resp = client.post(
        "/api/maintenance/report-issue?cell_id=9&description=Test&severity=grave",
        headers=_auth_header(token),
    )
    assert resp.status_code == 422


def test_report_issue_rejects_empty_description(client: TestClient) -> None:
    token = _make_token("luc_maint", "MAINTENANCE")
    resp = client.post(
        "/api/maintenance/report-issue?cell_id=9&description=%20%20&severity=critique",
        headers=_auth_header(token),
    )
    assert resp.status_code == 422


def test_report_issue_forbidden_for_operator(client: TestClient) -> None:
    token = _make_token("jean_ope", "OPERATEUR")
    resp = client.post(
        "/api/maintenance/report-issue?cell_id=9&description=Test&severity=critique",
        headers=_auth_header(token),
    )
    assert resp.status_code == 403


def test_simu_action_force_fault_then_ack_fault_updates_db(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeNode:
        async def get_child(self, *_args: Any, **_kwargs: Any) -> _FakeNode:
            return self

        async def write_value(self, *_args: Any, **_kwargs: Any) -> None:
            return None

    class _FakeClient:
        def __init__(self, url: str):
            self.url = url
            self.nodes = type("_Nodes", (), {"objects": _FakeNode()})()

        async def __aenter__(self) -> _FakeClient:
            return self

        async def __aexit__(self, *_exc: Any) -> None:
            return None

        async def get_namespace_index(self, *_args: Any, **_kwargs: Any) -> int:
            return 2

    monkeypatch.setattr(opcua_client, "Client", _FakeClient)
    client = TestClient(web_server.app)
    token = _make_token("luc_maint", "MAINTENANCE")

    resp = client.post(
        "/api/simu/action?cell_id=42&action=force_fault",
        headers=_auth_header(token),
    )
    assert resp.status_code == 200

    with Session(db.engine) as session:
        faults = db.list_defauts(session, cellule_id=42)
    assert len(faults) == 1
    assert faults[0].statut == db.DEFAUT_STATUT_ACTIF
    assert faults[0].severite == "critique"

    resp = client.post(
        "/api/simu/action?cell_id=42&action=ack_fault",
        headers=_auth_header(token),
    )
    assert resp.status_code == 200

    with Session(db.engine) as session:
        faults = db.list_defauts(session, cellule_id=42)
    assert faults[0].statut == db.DEFAUT_STATUT_RESOLU


def test_fetch_axis_data_success(monkeypatch: pytest.MonkeyPatch) -> None:
    class _ReadVar:
        def __init__(self, value: Any):
            self._value = value

        async def read_value(self) -> Any:
            return self._value

    class _AxeNode:
        def __init__(self, axe_num: int):
            self._axe_num = axe_num

        async def get_child(self, child: str) -> _ReadVar:
            name = child.split(":", 1)[1] if ":" in child else child
            mapping: dict[str, Any] = {
                "Temperature": 30.0 + self._axe_num,
                "Courant": 1.0 + self._axe_num * 0.1,
                "Couple": 5.0 + self._axe_num,
            }
            return _ReadVar(mapping[name])

    class _CellNode:
        async def get_child(self, child: str) -> _AxeNode:
            name = child.split(":", 1)[1] if ":" in child else child
            axe_num = int(name.rsplit("_", 1)[1])
            return _AxeNode(axe_num)

    class _ObjectsNode:
        async def get_child(self, _path: list[str]) -> _CellNode:
            return _CellNode()

    class _FakeClient:
        def __init__(self, url: str):
            self.url = url
            self.nodes = type("_Nodes", (), {"objects": _ObjectsNode()})()

        async def __aenter__(self) -> _FakeClient:
            return self

        async def __aexit__(self, *_exc: Any) -> None:
            return None

        async def get_namespace_index(self, *_args: Any, **_kwargs: Any) -> int:
            return 2

    monkeypatch.setattr(opcua_client, "Client", _FakeClient)
    data = asyncio.run(opcua_client.fetch_axis_data(1))
    assert len(data) == 6
    assert data[0]["axe"] == 1
    assert data[0]["temperature_c"] == 31.0
    assert data[5]["axe"] == 6


def test_fetch_axis_data_connection_failure_returns_empty_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FailingClient:
        def __init__(self, url: str):
            self.url = url

        async def __aenter__(self) -> _FailingClient:
            raise RuntimeError("opcua down")

        async def __aexit__(self, *_exc: Any) -> None:
            return None

    monkeypatch.setattr(opcua_client, "Client", _FailingClient)
    data = asyncio.run(opcua_client.fetch_axis_data(1))
    assert data == []


def test_load_ssl_cert_expiry_reads_real_sandbox_cert() -> None:
    """Vérifie que le parsing du certificat réel (cryptography.x509) fonctionne.

    Le certificat présent dans certs/web_cert.pem de cet environnement est un
    certificat de test généré localement, mais la fonction sous test lit et
    parse un vrai fichier PEM x509 exactement comme elle le ferait en
    production : ce test valide donc le chemin réel, pas une valeur simulée.
    """

    expiry = web_server._load_ssl_cert_expiry()  # pylint: disable=protected-access
    assert expiry is not None
    # Lève ValueError si le format n'est pas "YYYY-MM-DD" : le test échoue alors.
    datetime.strptime(expiry, "%Y-%m-%d")


def test_load_ssl_cert_expiry_returns_none_on_parse_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(*_args: Any, **_kwargs: Any) -> Any:
        raise ValueError("certificat illisible (test)")

    monkeypatch.setattr(web_server.x509, "load_pem_x509_certificate", _boom)
    assert (
        web_server._load_ssl_cert_expiry() is None
    )  # pylint: disable=protected-access


def test_simu_action_returns_500_when_opcua_write_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _failing_apply(_cell_id: int, _action: str) -> None:
        raise RuntimeError("écriture OPC UA impossible (test)")

    monkeypatch.setattr(web_server, "apply_simulated_action", _failing_apply)
    client = TestClient(web_server.app)
    token = _make_token("luc_maint", "MAINTENANCE")

    resp = client.post(
        "/api/simu/action?cell_id=1&action=force_fault",
        headers=_auth_header(token),
    )
    assert resp.status_code == 500
    assert "écriture OPC UA impossible" in resp.json()["detail"]


def test_sampling_loop_persists_one_iteration_then_stops(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Vérifie le corps réel de _sampling_loop (persistance axes + cellule).

    La boucle est infinie (while True + asyncio.sleep) par conception : pour
    la tester sans bloquer, on remplace asyncio.sleep par une exception
    "sentinelle" qui met fin proprement à la boucle juste après la première
    itération, une fois les écritures en base effectuées.
    """

    async def _fake_fetch_opcua_data() -> list[dict[str, Any]]:
        return [
            {
                "id": 9,
                "pneumatic_pressure": 6.4,
                "lubrix_level": 77.0,
            }
        ]

    async def _fake_fetch_axis_data(_cell_id: int) -> list[dict[str, Any]]:
        return [
            {"axe": 1, "temperature_c": 33.0, "courant_a": 1.1, "couple_nm": 9.0},
        ]

    class _StopLoop(Exception):
        pass

    async def _sleep_once_then_stop(_seconds: float) -> None:
        raise _StopLoop()

    monkeypatch.setattr(web_server, "fetch_opcua_data", _fake_fetch_opcua_data)
    monkeypatch.setattr(web_server, "fetch_axis_data", _fake_fetch_axis_data)
    monkeypatch.setattr(web_server.asyncio, "sleep", _sleep_once_then_stop)

    with pytest.raises(_StopLoop):
        asyncio.run(web_server._sampling_loop())  # pylint: disable=protected-access

    with Session(db.engine) as session:
        cell_measures = db.list_cell_measures(
            session, cellule_id=9, since="2000-01-01 00:00:00"
        )
        axis_measures = db.list_axis_measures(
            session, cellule_id=9, since="2000-01-01 00:00:00"
        )

    assert len(cell_measures) == 1
    assert cell_measures[0].pneumatic_pressure_bar == 6.4
    assert len(axis_measures) == 1
    assert axis_measures[0].temperature_c == 33.0


def test_sampling_loop_survives_fetch_error_and_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Une itération en échec (OPC UA indisponible) ne doit pas arrêter la
    boucle de fond : elle est journalisée puis on retente au tour suivant.
    """

    async def _failing_fetch() -> list[dict[str, Any]]:
        raise RuntimeError("OPC UA indisponible (test)")

    class _StopLoop(Exception):
        pass

    async def _sleep_once_then_stop(_seconds: float) -> None:
        raise _StopLoop()

    monkeypatch.setattr(web_server, "fetch_opcua_data", _failing_fetch)
    monkeypatch.setattr(web_server.asyncio, "sleep", _sleep_once_then_stop)

    # La boucle doit atteindre asyncio.sleep (donc lever _StopLoop) malgré
    # l'échec de fetch_opcua_data, preuve que l'exception a été absorbée.
    with pytest.raises(_StopLoop):
        asyncio.run(web_server._sampling_loop())  # pylint: disable=protected-access


def test_lifespan_starts_and_cancels_sampling_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def _fake_sampling_loop() -> None:
        started.set()
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    monkeypatch.setattr(web_server, "_sampling_loop", _fake_sampling_loop)

    async def _run() -> None:
        async with web_server.lifespan(web_server.app):
            await asyncio.wait_for(started.wait(), timeout=1)
        await asyncio.wait_for(cancelled.wait(), timeout=1)

    asyncio.run(_run())
