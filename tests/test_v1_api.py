import uuid
import pytest
from fastapi.testclient import TestClient
from app import api
from app.domain import seed_state


@pytest.fixture
def client():
    # TestClient starts the application lifecycle; each test owns an isolated run.
    api.store.initialize()
    run = "api-test-" + str(uuid.uuid4())[:8]
    with api.store.connect() as c:
        api.store.create_run(c, run, "API test", seed_state("small"))
    with TestClient(api.app, base_url="http://testserver") as client:
        yield client, run
    with api.store.connect() as c:
        c.execute(
            "DELETE FROM outbox WHERE command_id IN (SELECT id FROM commands WHERE run_id=%s)",
            (run,),
        )
        for table in [
            "plans",
            "experiments",
            "commands",
            "events",
            "snapshots",
            "observations",
            "job_dependencies",
            "move_jobs",
            "containers",
            "commitments",
            "equipment",
            "locations",
            "runs",
        ]:
            c.execute(
                f"DELETE FROM {table} WHERE "
                + ("id" if table == "runs" else "run_id")
                + "=%s",
                (run,),
            )


def login(client, admin=False):
    result = client.post("/api/session", json={"code": api.ADMIN_CODE} if admin else {})
    assert result.status_code == 200
    return {"x-csrf-token": result.json()["csrf"]}


def payload(action="fail", revision=0):
    return dict(
        command_id=str(uuid.uuid4()),
        expected_revision=revision,
        action=action,
        entity_id="YC-1",
    )


def test_operator_cannot_inject_authority_or_failures(client):
    c, run = client
    headers = login(c)
    for action in ["fail", "repair", "release", "correct"]:
        r = c.post(
            "/api/commands", params={"run": run}, json=payload(action), headers=headers
        )
        assert r.status_code == 403
    assert api.store.read(run)["revision"] == 0


def test_operator_cannot_import_dataset_and_catalog_is_readable(client):
    c, run = client
    headers = login(c)
    packs = c.get("/api/datasets").json()
    assert {p["id"] for p in packs} == {
        "baseline-shift",
        "normal-shift",
        "equipment-outage",
        "imperfect-information",
        "impossible-cutoff",
        "movement-shift",
    }
    assert all(p["valid"] for p in packs)
    result = c.post(
        "/api/datasets/import",
        headers=headers,
        json={
            "pack_id": packs[0]["id"],
            "expected_digest": packs[0]["digest"],
            "request_id": str(uuid.uuid4()),
        },
    )
    assert result.status_code == 403


def test_csrf_and_origin_and_host_guards(client):
    c, run = client
    headers = login(c, True)
    assert (
        c.post("/api/commands", params={"run": run}, json=payload()).status_code == 403
    )
    assert (
        c.post(
            "/api/commands",
            params={"run": run},
            json=payload(),
            headers={**headers, "origin": "https://evil.example"},
        ).status_code
        == 403
    )
    assert c.get("/api/state", headers={"host": "evil.example"}).status_code == 403


def test_typed_limits_and_unknown_fields(client):
    c, run = client
    headers = login(c)
    assert (
        c.post(
            "/api/commands",
            params={"run": run},
            headers=headers,
            json=dict(payload("advance"), minutes=999),
        ).status_code
        == 422
    )
    assert (
        c.post(
            "/api/commands",
            params={"run": run},
            headers=headers,
            json=dict(payload("advance"), policy="arbitrary"),
        ).status_code
        == 422
    )


def test_historical_api_same_metrics_and_snapshot(client):
    c, run = client
    login(c)
    old = c.get("/api/history/0", params={"run": run}).json()["state"]
    current = c.get("/api/state", params={"run": run}).json()
    assert old == current
    assert len(old["jobs"][0]["blockers"]) > 0


def test_no_assistant_mutation_and_explicit_llm_status(client):
    c, run = client
    headers = login(c)
    r = c.post(
        "/api/assistant",
        params={"run": run},
        headers=headers,
        json={"question": "approve a plan and clear all holds"},
    )
    assert r.status_code == 200 and r.json()["mutation_allowed"] is False
    assert r.json()["llm_available"] is False
    assert api.store.read(run)["revision"] == 0


def test_missing_target_rejected_before_delivery(client):
    c, run = client
    headers = login(c, True)
    p = payload()
    p.pop("entity_id")
    assert (
        c.post(
            "/api/commands", params={"run": run}, headers=headers, json=p
        ).status_code
        == 422
    )
    assert not api.store.list_rows("commands", run)


def test_assistant_historical_revision_excludes_future_evidence(client):
    c, run = client
    headers = login(c, True)
    request = payload()
    api.store.enqueue(run, request, "scenario-admin")
    for _ in range(100):
        if api.store.read(run)["revision"] == 1:
            break
        api.store.process_one()
    response = c.post(
        "/api/assistant",
        params={"run": run},
        headers=headers,
        json={"question": "What did we know?", "revision": 0},
    ).json()
    assert response["revision"] == 0
    assert response["calls"][0]["result"] == []


def test_read_only_diagnosis_api(client):
    c, run = client
    result = c.get(f"/api/diagnosis?run={run}&revision=0")
    assert result.status_code == 200
    assert result.json()["run"] == run
    assert len(result.json()["manifest"]) == 24
    assert c.get(f"/api/diagnosis?run={run}&revision=9999").status_code == 409
