"""API HTTP ponta a ponta (SPEC §9, §15.6)."""

import pytest


def _create(client, module="MODULE_2", **kw):
    body = {"module": module, "event_count": 1000, "participants_count": 2, "duration_seconds": 60, "test_mode": True}
    if module == "MODULE_1":
        body["target"] = 1
    body.update(kw)
    r = client.post("/api/sessions", json=body)
    assert r.status_code == 201, r.text
    assert r.json()["message"] == "Seu protocolo foi registrado."
    return r.json()["session"]["session_id"]


def _finish_intention(client, sid):
    assert client.post(f"/api/sessions/{sid}/intention/start").status_code == 200
    client.clock.advance(61)
    r = client.post(f"/api/sessions/{sid}/intention/complete")
    assert r.status_code == 200, r.text


BLOCKED = ["result", "events.csv", "export.json", "report.html"]


def _assert_blind(client, sid):
    for path in BLOCKED:
        r = client.get(f"/api/sessions/{sid}/{path}")
        assert r.status_code == 423, (path, r.status_code)
    s = client.get(f"/api/sessions/{sid}").json()
    assert s["observed_proportion"] is None and s["p_value"] is None
    assert "zeros" not in s and "ones" not in s


def test_module2_full_flow(client):
    sid = _create(client)
    r = client.get(f"/api/sessions/{sid}/preregistration")
    assert r.status_code == 200 and r.json()["planned_target"] is None and len(r.headers["X-SHA256"]) == 64

    assert client.post(f"/api/sessions/{sid}/generate").status_code == 202
    s = client.get(f"/api/sessions/{sid}").json()
    assert s["state"] == "SEALED" and len(s["events_sha256"]) == 64
    _assert_blind(client, sid)

    assert client.post(f"/api/sessions/{sid}/target", json={"target": 0}).json()["target"] == 0
    _assert_blind(client, sid)
    _finish_intention(client, sid)
    assert client.get(f"/api/sessions/{sid}").json()["state"] == "REVEAL_PENDING"
    _assert_blind(client, sid)

    r = client.post(f"/api/sessions/{sid}/reveal").json()
    assert r["valid"] is True
    a = r["analysis"]
    assert a["zeros"] + a["ones"] == 1000 and a["target"] == 0
    assert client.get(f"/api/sessions/{sid}/result").json()["analysis"]["p_value"] == a["p_value"]
    assert client.get(f"/api/sessions/{sid}/events.csv").status_code == 200
    report = client.get(f"/api/sessions/{sid}/report.html").text
    assert "não estabelece uma explicação causal" in report
    assert client.get(f"/api/sessions/{sid}/export.json").json()["integrity"]["ok"] is True
    assert client.get(f"/api/sessions/{sid}/verify").json()["ok"] is True


def test_module1_full_flow(client):
    sid = _create(client, "MODULE_1")
    assert client.get(f"/api/sessions/{sid}").json()["state"] == "TARGET_SELECTED"
    assert client.post(f"/api/sessions/{sid}/generate").status_code == 409  # sem intenção ainda
    _finish_intention(client, sid)  # dispara a coleta em background
    s = client.get(f"/api/sessions/{sid}").json()
    assert s["state"] == "REVEAL_PENDING"
    _assert_blind(client, sid)
    assert client.post(f"/api/sessions/{sid}/reveal").json()["valid"] is True


def test_control_full_flow(client):
    sid = _create(client, "CONTROL")
    client.post(f"/api/sessions/{sid}/generate")
    s = client.get(f"/api/sessions/{sid}").json()
    assert s["state"] == "TARGET_SELECTED" and s["target"] is None
    _finish_intention(client, sid)
    _assert_blind(client, sid)
    r = client.post(f"/api/sessions/{sid}/reveal").json()
    assert r["valid"] is True and r["session"]["target"] in (0, 1)


def test_reveal_before_time_is_rejected(client):
    sid = _create(client)
    client.post(f"/api/sessions/{sid}/generate")
    client.post(f"/api/sessions/{sid}/target", json={"target": 1})
    client.post(f"/api/sessions/{sid}/intention/start")
    client.clock.advance(59)
    assert client.post(f"/api/sessions/{sid}/intention/complete").status_code == 409
    assert client.post(f"/api/sessions/{sid}/reveal").status_code == 409
    _assert_blind(client, sid)


def test_illegal_operations_return_409(client):
    sid = _create(client)
    assert client.post(f"/api/sessions/{sid}/intention/start").status_code == 409
    assert client.post(f"/api/sessions/{sid}/target", json={"target": 1}).status_code == 409
    client.post(f"/api/sessions/{sid}/generate")
    assert client.post(f"/api/sessions/{sid}/generate").status_code == 409
    assert client.post(f"/api/sessions/{sid}/cancel").status_code == 409


def test_no_delete_or_edit_routes(client):
    sid = _create(client)
    for method in ("delete", "put", "patch"):
        r = getattr(client, method)(f"/api/sessions/{sid}")
        assert r.status_code == 405


def test_quantum_unavailable_returns_503_without_creating(client):
    r = client.post("/api/sessions", json={"module": "MODULE_2", "event_count": 1000, "participants_count": 1,
                                           "duration_seconds": 60, "test_mode": False})
    assert r.status_code == 503
    assert client.get("/api/history").json()["sessions"] == []


def test_system_info_does_not_leak_api_key(client):
    client.service.settings.qrng_api_key = "super-secret"
    r = client.get("/api/system/info")
    assert r.json()["quantum_source"]["api_key_configured"] is True
    assert "super-secret" not in r.text


@pytest.mark.parametrize(
    "body",
    [
        {"module": "MODULE_2", "event_count": 1000, "participants_count": 1, "duration_seconds": 60, "target": 1},
        {"module": "MODULE_1", "event_count": 1000, "participants_count": 1, "duration_seconds": 60},
        {"module": "CONTROL", "event_count": 1000, "participants_count": 1, "duration_seconds": 60, "target": 0},
        {"module": "MODULE_2", "event_count": 5, "participants_count": 1, "duration_seconds": 60},
        {"module": "MODULE_2", "event_count": 1000, "participants_count": 0, "duration_seconds": 60},
    ],
)
def test_invalid_creation_is_rejected(client, body):
    body["test_mode"] = True
    assert client.post("/api/sessions", json=body).status_code == 400


def test_path_traversal_is_rejected(client):
    assert client.get("/api/sessions/..%2F..%2Fetc").status_code == 404
    assert client.get("/api/sessions/DAL-2026-zzzzzzzz").status_code == 404


def test_history_and_csv(client):
    sid = _create(client)
    client.post(f"/api/sessions/{sid}/generate")
    rows = client.get("/api/history?test_mode=true").json()["sessions"]
    assert rows[0]["session_id"] == sid and rows[0]["observed_proportion"] is None
    csv = client.get("/api/history.csv?test_mode=true").text
    assert csv.splitlines()[0].startswith("session_id,data_utc,modulo")
    assert sid in csv


def test_frontend_is_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "DALDEGAN" in r.text
