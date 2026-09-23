from test_v1_api import client, login


def test_evaluation_api_scope_csrf_and_cancellation(client):
    c, run = client
    headers = login(c)
    state = c.get("/api/state", params={"run": run}).json()
    assert (
        c.post(
            "/api/evaluations",
            params={"run": run},
            json=dict(expected_revision=0, suite="case"),
        ).status_code
        == 403
    )
    assert (
        c.post(
            "/api/evaluations",
            params={"run": run},
            headers=headers,
            json=dict(expected_revision=99, suite="case"),
        ).status_code
        == 409
    )
    r = c.post(
        "/api/evaluations",
        params={"run": run},
        headers=headers,
        json=dict(expected_revision=0, suite="case"),
    )
    assert r.status_code == 202, r.text
    eid = r.json()["id"]
    assert (
        c.get("/api/evaluations/" + eid, params={"run": "not-this-run"}).status_code
        == 409
    )
    assert (
        c.post(
            "/api/evaluations/" + eid + "/cancel",
            params={"run": run},
            headers=headers,
            json={},
        ).status_code
        == 200
    )
    report = c.get("/api/evaluations/" + eid, params={"run": run}).json()
    assert report["status"] == "cancelled" and not report["complete"]
    assert (
        c.get("/api/state", params={"run": run}).json()["revision"] == state["revision"]
    )

    reply=c.post('/api/assistant',params={'run':run},headers=headers,json={'question':'Show evaluation results','evaluation_id':eid})
    assert reply.status_code==200,reply.text
    assert reply.json()['citations'][0]['evaluation_id']==eid
