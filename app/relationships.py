"""Typed relationship projection shared by all pages. No physical writes."""


def dependency_detail(s, job, predecessor):
    saved = job.get("dependency_details", {}).get(predecessor["id"])
    if saved:
        return saved
    same = job["container_id"] == predecessor["container_id"]
    return dict(
        reason=(
            f"Deliver {job['container_id']} to {job['source_id']} before pickup"
            if same
            else f"Clear access to {job['container_id']} by relocating {predecessor['container_id']}"
        ),
        kind="sequence" if same else "access",
        origin="legacy recorded plan",
        basis_revision=0,
    )


def project(s):
    from .domain import requirements, by_id

    nodes, edges = [], []
    for collection, kind in [
        ("locations", "location"),
        ("equipment", "equipment"),
        ("containers", "container"),
        ("jobs", "job"),
        ("commitments", "commitment"),
    ]:
        for row in s[collection]:
            nodes.append(
                dict(id=row["id"], kind=kind, label=row.get("label", row["id"]))
            )

    def edge(a, relation, b, state="planned", **extra):
        if b:
            edges.append(
                dict(source=a, relation=relation, target=b, state=state, **extra)
            )

    for c in s["containers"]:
        nodes.append(dict(id=c["visit_id"], kind="visit", label=c["visit_id"]))
        edge(c["id"], "has visit", c["visit_id"], "recorded")
        edge(c["visit_id"], "committed to", c["commitment_id"])
        edge(c["id"], "committed to", c["commitment_id"])
        edge(c["id"], "located at", c["location_id"], "observed in simulator")
        edge(c["id"], "in transit on", c["job_id"], "observed in simulator")
        if c.get("custody", {}).get("kind") == "equipment":
            edge(c["id"], "held by", c["custody"]["id"], "observed in simulator")
    for co in s["commitments"]:
        edge(co["id"], "served at", co["location_id"])
    for j in s["jobs"]:
        edge(j["id"], "moves", j["container_id"])
        edge(
            j["id"], "for visit", by_id(s["containers"], j["container_id"])["visit_id"]
        )
        edge(j["id"], "picks up at", j["source_id"])
        edge(j["id"], "delivers to", j["target_id"])
        edge(j["id"], "assigned to", j["equipment_id"])
        for r in (
            j.get("assigned_resources", j.get("resources", []))
            if j["status"] == "completed"
            else j.get("resources", [])
        ):
            edge(
                j["id"],
                "reserved" if j["status"] == "running" else "used resource",
                r,
                "observed in simulator",
            )
        for d in j["dependencies"]:
            edge(
                j["id"], "waits for", d, **dependency_detail(s, j, by_id(s["jobs"], d))
            )
        for req in requirements(s, j):
            for eid in req["eligible"]:
                edge(j["id"], "eligible resource", eid, requirement=req["role"])
    nodes.sort(key=lambda n: n["id"])
    edges.sort(key=lambda e: (e["source"], e["relation"], e["target"]))
    return dict(nodes=nodes, edges=edges)


def describe(s, j):
    from .domain import by_id, requirements, location

    cargo = by_id(s["containers"], j["container_id"])
    successors = [x for x in s["jobs"] if j["id"] in x["dependencies"]]
    purpose = (
        f"Clear access for {', '.join(x['container_id'] for x in successors if x['container_id'] != j['container_id'])}"
        if j["kind"] == "rehandle"
        else f"Progress {cargo['visit_id']} toward {cargo['commitment_id'] or 'yard storage'}"
    )
    source, target = location(s, j["source_id"]), location(s, j["target_id"])
    stages = [
        dict(
            name="Pickup / admission",
            location=source["id"],
            capability=(
                "quay"
                if source["kind"] == "vessel"
                else "yard" if source["kind"] == "yard" else "gate"
            ),
        ),
        dict(
            name="Internal transfer",
            location=f"{source['id']} → {target['id']}",
            capability="tractor",
        ),
        dict(
            name="Placement / handoff",
            location=target["id"],
            capability=(
                "yard"
                if target["kind"] == "yard"
                else (
                    "quay"
                    if target["kind"] == "vessel"
                    else "external handoff (abstract)"
                )
            ),
        ),
    ]
    return dict(
        purpose=purpose,
        visit_id=cargo["visit_id"],
        commitment_id=cargo["commitment_id"],
        requirements=requirements(s, j),
        predecessors=[
            dict(id=d, **dependency_detail(s, j, by_id(s["jobs"], d)))
            for d in j["dependencies"]
        ],
        successors=[x["id"] for x in successors],
        stages=stages,
    )
