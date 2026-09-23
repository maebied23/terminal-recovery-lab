"""Bounded read-only tools shared by the assistant and direct API clients.

This v1 uses an explicit intent router, not an undisclosed LLM. No tool mutates
operations; the UI's approval endpoint is the sole command entry point.
"""

from .domain import by_id, blockers, metrics


def inspect_entity(s, entity_id):
    from .domain import enrich

    view = enrich(s)
    co = by_id(s["commitments"], entity_id)
    cargo = next(
        (
            c
            for c in s["containers"]
            if c["id"] == entity_id or c["visit_id"] == entity_id
        ),
        None,
    )
    roots = {entity_id}
    if co:
        roots.add(co["location_id"])
    if cargo:
        roots.add(cargo["id"])
    ids = {
        e["source"]
        for e in view["relationships"]["edges"]
        if e["target"] in roots
        and e["relation"]
        in (
            "moves",
            "for visit",
            "picks up at",
            "delivers to",
            "assigned to",
            "reserved",
            "used resource",
        )
    }
    jobs = [
        j
        for j in view["jobs"]
        if j["id"] in ids or j["id"] in roots or j["commitment_id"] == entity_id
    ]
    return dict(
        entity=next(
            (n for n in view["relationships"]["nodes"] if n["id"] == entity_id), None
        ),
        jobs=jobs,
        relationships=[
            e
            for e in view["relationships"]["edges"]
            if e["source"] in roots or e["target"] in roots
        ],
        revision=s["revision"],
    )


def assistant(store, run, question, selected, revision=None):
    s = (
        store.history(run, revision)["state"]
        if revision is not None
        else store.read(run)
    )
    q = question.lower()
    calls = []
    if any(x in q for x in ["confidence", "risk", "predict", "range"]):
        text = "Risk labels are rule-based: completed, missed cutoff, blocked, tight (<15 minutes of simple slack), or ready. They are not learned probabilities. Recovery compares paired simulations with synthetic handling-time variation. The P10–P90 band is a scenario range, not calibrated confidence."
        calls = [
            dict(
                tool="read_rule",
                arguments={"id": "R-DURATION"},
                result="Synthetic ±20% handling duration, per-job deterministic noise",
            )
        ]
    elif any(x in q for x in ["history", "evidence", "know", "source"]):
        with store.connect() as c:
            events = c.execute(
                "SELECT * FROM events WHERE run_id=%s AND revision<=%s ORDER BY id DESC LIMIT 12",
                (run, s["revision"]),
            ).fetchall()
        calls = [
            dict(
                tool="recent_events",
                arguments={"limit": 12},
                result=[
                    dict(kind=e["kind"], revision=e["revision"], entity=e["entity_id"])
                    for e in events
                ],
            )
        ]
        text = f'The selected knowledge state is revision {s["revision"]}, simulation minute {s["minute"]}. Evidence keeps occurrence minutes separate from recording revisions. Open a revision in Evidence to inspect the exact prior snapshot; a late correction never edits that snapshot.'
    elif selected and "needs attention" not in q:
        result = inspect_entity(s, selected)
        calls = [
            dict(
                tool="inspect_entity", arguments={"entity_id": selected}, result=result
            )
        ]
        reasons = sorted({b for j in result["jobs"] for b in j["blockers"]})
        text = (
            f'{selected} is linked to {len(result["jobs"])} handling moves at revision {s["revision"]}. '
            + (
                "Current blockers: " + "; ".join(reasons) + "."
                if reasons
                else "No current blocker is reported for its linked moves."
            )
            + " Recovery can compare reachable crane assignments and priorities; it cannot clear authority holds or transfer an in-flight load."
        )
    else:
        m = metrics(s)
        failed = [e["id"] for e in s["equipment"] if e["status"] == "failed"]
        calls = [
            dict(
                tool="terminal_summary",
                arguments={},
                result=dict(m, failed_equipment=failed, revision=s["revision"]),
            )
        ]
        text = (
            f'{m["on_time"]} of {m["total"]} outbound cargo obligations are completed on time; {m["missed"]} have missed their cutoff. '
            + ("Unavailable equipment: " + ", ".join(failed) + ". " if failed else "")
            + "Select cargo or equipment for a dependency trace. Pause the clock and use Compare plans to test recovery choices before approval."
        )
    return dict(
        mode="deterministic tool assistant",
        llm_available=False,
        answer=text,
        calls=calls,
        revision=s["revision"],
        mutation_allowed=False,
    )
