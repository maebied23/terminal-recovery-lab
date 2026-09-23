"""Offline authoring of explicit, synthetic metric edges. Never run on application startup."""

import json, hashlib
from pathlib import Path
from app.datasets import load_pack

root = Path(__file__).resolve().parents[1] / "datasets"
s = load_pack("baseline-shift")["state"]
nodes = [dict(id=l["id"], x=l["x"], y=l["y"]) for l in s["locations"]]
# Four junctions form a dedicated two-way service road. Lengths are authored assumptions.
xs = [180, 420, 660, 900]
for i, x in enumerate(xs):
    nodes.append(dict(id=f"J{i}", x=x, y=405))
edges = []


def pair(a, b, metres):
    for source, target in ((a, b), (b, a)):
        edges.append(
            dict(
                id=f"{source}>{target}",
                source=source,
                target=target,
                metres=metres,
                loaded_mpm=120,
                empty_mpm=180,
                compatible=["tractor"],
                closed=False,
            )
        )


for i in range(3):
    pair(f"J{i}", f"J{i+1}", 240)
for i, l in enumerate(s["locations"]):
    nearest = min(range(4), key=lambda k: abs(l["x"] - xs[k]))
    pair(l["id"], f"J{nearest}", 80 + (i % 6) * 30)
net = dict(
    version="staged-routes-v1",
    units="metres/minutes",
    nodes=nodes,
    edges=edges,
    pickup_minutes=2,
    setdown_minutes=2,
    initial_positions={
        e["id"]: "J0" if i % 2 == 0 else "J3"
        for i, e in enumerate(s["equipment"])
        if e["kind"] == "tractor"
    },
    provenance="Authored synthetic service road: 240m junction spacing; 80–230m spurs; not inferred physical geography",
)
folder = root / "movement-shift"
folder.mkdir(exist_ok=True)
(folder / "movement.json").write_text(json.dumps(net, indent=2) + "\n")
(folder / "changes.json").write_text("[]\n")
(folder / "events.jsonl").write_text("")
m = json.loads((root / "baseline-shift/manifest.json").read_text())
m.update(
    pack_id="movement-shift",
    title="Connected movement shift",
    description="Metric routes, empty tractor travel, temporal placement and executable handovers.",
    generator="movement-inputs-v1",
    movement_version=net["version"],
)
m["files"] = {
    f: hashlib.sha256((folder / f).read_bytes()).hexdigest()
    for f in ("changes.json", "events.jsonl", "movement.json")
}
m["assumptions"] = [
    "Synthetic data and authored metric lengths, not terminal telemetry.",
    "One vertical stack per yard location; one receiving transfer point per destination.",
    "Handling and travel rates are uncalibrated; minute-resolution simulation.",
]
(folder / "manifest.json").write_text(json.dumps(m, indent=2) + "\n")
