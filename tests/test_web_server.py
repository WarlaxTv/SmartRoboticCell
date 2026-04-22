from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastapi.testclient import TestClient

from src_v2 import web_server


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

    monkeypatch.setattr(web_server, "Client", _FakeClient)
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

    monkeypatch.setattr(web_server, "Client", _FakeClient)
    client = TestClient(web_server.app)
    token = _make_token("luc_maint", "MAINTENANCE")

    for action in ("force_fault", "force_maint", "ack_fault", "ack_maint"):
        resp = client.post(
            f"/api/simu/action?cell_id=1&action={action}",
            headers=_auth_header(token),
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


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
                "VitesseBras": 95.0,
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

    monkeypatch.setattr(web_server, "Client", _FakeClient)
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


def test_operator_cannot_read_maintenance_history(client: TestClient) -> None:
    token = _make_token("jean_ope", "OPERATEUR")
    resp = client.get("/api/maintenance/history", headers=_auth_header(token))
    assert resp.status_code == 403


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
