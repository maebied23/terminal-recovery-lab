import assert from "node:assert/strict";
import fs from "node:fs";
import {
  cargoReadiness,
  taskChain,
  equipmentActivity,
  placeName,
  equipmentName,
} from "../src/departure.ts";
const s = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const cargo = s.containers.find((c) => c.id === "CT-0121");
const readiness = (state = s, c = cargo) =>
  cargoReadiness(state, c, "RAIL-1", 42);
assert.deepEqual(
  taskChain(s, cargo.id).jobs.map((j) => j.id),
  ["MV-013", "MV-001"],
);
assert.equal(readiness().next.container_id, "CT-0122");
assert.equal(readiness().label, "Next move ready");
assert.equal(placeName(s, "A1"), "Yard A · stack 1");
assert.equal(equipmentName(s, "YC-1"), "Yard crane 1");
assert.equal(equipmentActivity(s, "YC-1").length, 0);
const changed = structuredClone(s);
changed.jobs.find((j) => j.id === "MV-013").blockers = ["YC-1 unavailable"];
assert.equal(readiness(changed).label, "Waiting / blocked");
changed.jobs.find((j) => j.id === "MV-013").status = "running";
assert.equal(readiness(changed).label, "Work interrupted");
changed.jobs.find((j) => j.id === "MV-013").blockers = [];
assert.equal(readiness(changed).label, "Work underway");
changed.minute = 43;
assert.equal(readiness(changed).label, "Cutoff missed");
const final = changed.jobs.find((j) => j.id === "MV-001");
final.status = "completed";
final.completed_at = 42;
assert.equal(readiness(changed).label, "Delivered on time");
final.completed_at = 43;
assert.equal(readiness(changed).label, "Delivered late");
final.completed_at = null;
assert.equal(readiness(changed).label, "Needs review");
changed.jobs = changed.jobs.filter((j) => j.id !== "MV-001");
assert.equal(readiness(changed).label, "Needs review");
const bad = structuredClone(s);
bad.jobs.find((j) => j.id === "MV-013").dependencies = ["MV-001"];
assert.equal(readiness(bad).label, "Needs review");
assert(taskChain(bad, cargo.id).issues[0].includes("cycle"));
bad.jobs.find((j) => j.id === "MV-013").dependencies = ["MISSING"];
assert(taskChain(bad, cargo.id).issues[0].includes("Missing"));
const active = structuredClone(s);
active.minute = 5;
const job = active.jobs.find((j) => j.id === "MV-013");
Object.assign(job, {
  status: "running",
  started_at: 1,
  resources: ["YC-1"],
  remaining: 9,
});
assert.equal(equipmentActivity(active, "YC-1")[0].end, 5); // Not a forecast at 14.
assert.equal(equipmentActivity(active, "TT-1").length, 0); // Eligibility isn't use.
console.log("19 departure selector assertions passed");
