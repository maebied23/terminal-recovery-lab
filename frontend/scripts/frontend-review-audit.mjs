import { chromium, request } from "playwright";
import fs from "node:fs/promises";
const base = "http://127.0.0.1:8790",
  out = "../docs/frontend-redesign";
const check = (v, m) => {
  if (!v) throw Error(m);
};
const api = await request.newContext({ baseURL: base });
const login = await api.post("/api/session", {
  data: { code: (await fs.readFile("../.local/admin-code", "utf8")).trim() },
});
const { csrf } = await login.json();
const headers = { "X-CSRF-Token": csrf };
const packs = await (await api.get("/api/datasets")).json();
const pack = packs.find((p) => p.id === "baseline-shift");
const res = await api.post("/api/datasets/import", {
  headers,
  data: {
    pack_id: pack.id,
    expected_digest: pack.digest,
    request_id: crypto.randomUUID(),
  },
});
check(res.ok(), await res.text());
const run = (await res.json()).id;
await fs.mkdir(out, { recursive: true });
await fs.writeFile(
  out + "/walkthrough.json",
  JSON.stringify(
    {
      run,
      url: `${base}/?run=${run}&departure=NORTH-RAIL&cargo=CT-0121&page=Operations`,
    },
    null,
    2,
  ),
);
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({
  viewport: { width: 1280, height: 800 },
  reducedMotion: "reduce",
});
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
await page.goto(
  `${base}/?run=${run}&departure=NORTH-RAIL&cargo=CT-0121&page=Operations`,
);
await page
  .getByRole("region", { name: "Departure decision workspace" })
  .waitFor();
await page.getByRole("heading", { name: "North Rail", exact: true }).waitFor();
check(
  (await page
    .getByRole("button", { name: /Relocate container 122/ })
    .count()) === 1,
  "one prerequisite action",
);
await page.locator(".diagnosis-loading").waitFor({ state: "hidden" });
await page.screenshot({ path: out + "/01-situation.png" });
await page.locator(".case-map").screenshot({ path: out + "/01b-map.png" });
await page.getByRole("button", { name: /Relocate container 122/ }).click();
check(
  (await page.getByLabel("Case container").inputValue()) === "CT-0121",
  "prerequisite selection preserves case cargo",
);
await page
  .getByRole("button", { name: "Inspect required work", exact: true })
  .click();
await page
  .getByRole("region", { name: "Selected work details" })
  .scrollIntoViewIfNeeded();
await page.screenshot({ path: out + "/02-work.png" });
await page
  .getByRole("button", { name: "Compare destinations", exact: true })
  .click();
await page.locator(".placement-options").waitFor({ timeout: 60000 });
await page.locator(".placement").scrollIntoViewIfNeeded();
await page.screenshot({ path: out + "/03-placement.png" });
await page
  .getByRole("button", { name: "3 Compare & book", exact: true })
  .click();
await page
  .getByRole("button", { name: "Build recovery schedules", exact: true })
  .click();
await page.locator(".schedule-candidates").waitFor({ timeout: 60000 });
check(
  (await page.locator(".schedule-choice").count()) === 3,
  "all strategies retained",
);
await page.locator(".schedule-candidates").scrollIntoViewIfNeeded();
await page.screenshot({ path: out + "/04-comparison.png" });
await page.locator(".schedule-timeline").scrollIntoViewIfNeeded();
await page.screenshot({ path: out + "/05-bookings.png" });
const bundle = page
  .locator(".booking-lane button")
  .filter({ hasText: "122" })
  .first();
await bundle.click();
check(
  (await page.locator(".selected-bundle").count()) >= 2,
  "simultaneous resource bundle highlighted",
);
await page
  .getByRole("button", { name: "Review schedule for approval", exact: true })
  .click();
await page.getByRole("dialog").waitFor();
await page.screenshot({ path: out + "/06-approval.png" });
await page.getByRole("button", { name: "Cancel", exact: true }).last().click();
await page.setViewportSize({ width: 900, height: 800 });
await page.getByRole("button", { name: "1 Situation", exact: true }).click();
await page.screenshot({ path: out + "/07-narrow.png" });
await page.getByRole("button", { name: "Scenario lab", exact: true }).click();
await page
  .getByRole("heading", { name: "Scenario lab", exact: true })
  .waitFor();
await page.screenshot({ path: out + "/08-scenario.png" });
check(
  await page
    .getByRole("button", { name: "Inject failure", exact: true })
    .isDisabled(),
  "original run protected",
);
await page.getByRole("button", { name: "Evaluation", exact: true }).click();
await page
  .locator(".evaluation-panel")
  .waitFor()
  .catch(() => {});
// Complete the guided branch flow without disturbing the starting case.
await page.getByRole("button", { name: "Disruption", exact: true }).click();
await page
  .getByLabel("Scenario administrator code")
  .fill((await fs.readFile("../.local/admin-code", "utf8")).trim());
await page
  .getByRole("button", { name: "Unlock scenario controls", exact: true })
  .click();
await page
  .getByRole("button", { name: "Fork this shift", exact: true })
  .click();
await page.waitForFunction(
  (original) => new URL(location.href).searchParams.get("run") !== original,
  run,
);
await page
  .getByRole("heading", { name: "Scenario lab", exact: true })
  .waitFor();
const branch = new URL(page.url()).searchParams.get("run");
await page.getByRole("button", { name: "Inject failure", exact: true }).click();
for (let i = 0; i < 100; i++) {
  const state = await (await api.get("/api/state?run=" + branch)).json();
  if (state.equipment.find((e) => e.id === "YC-1").status === "failed") break;
  await new Promise((r) => setTimeout(r, 100));
}
await page.waitForFunction(() =>
  document.querySelector(".case-context")?.textContent.includes("revision 1"),
);
await page.screenshot({ path: out + "/09-disruption-branch.png" });
await page.getByRole("button", { name: "Open recovery", exact: true }).click();
await page
  .getByRole("button", { name: "Build recovery schedules", exact: true })
  .click();
await page.locator(".schedule-candidates").waitFor({ timeout: 60000 });
// Exercise explicit placement writeback on a different fresh branch.
const forkResponse = await api.post("/api/runs?run=" + run, {
  headers,
  data: {
    name: "Placement review · isolated",
    fresh: false,
    profile: "standard",
  },
});
check(forkResponse.ok(), await forkResponse.text());
const placementRun = (await forkResponse.json()).id;
await page.goto(
  `${base}/?run=${placementRun}&departure=NORTH-RAIL&cargo=CT-0121&page=Operations&stage=Required%20work`,
);
await page
  .getByRole("button", { name: "Compare destinations", exact: true })
  .click();
await page.locator(".placement-options").waitFor({ timeout: 60000 });
await page
  .locator(".placement-options button")
  .filter({ hasText: "D3" })
  .click();
await page
  .getByRole("button", { name: "Review destination change", exact: true })
  .click();
await page
  .getByRole("button", { name: "Apply destination", exact: true })
  .click();
await page
  .locator(".action-receipt")
  .filter({ hasText: "acknowledged" })
  .waitFor({ timeout: 20000 });
const placed = await (await api.get("/api/state?run=" + placementRun)).json();
check(
  placed.jobs.find((j) => j.id === "MV-013").target_id === "D3",
  "relocation target written",
);
check(
  placed.jobs.find((j) => j.id === "MV-002").source_id === "D3",
  "downstream pickup written",
);
check(
  placed.containers.find((c) => c.id === "CT-0122").location_id === "A1",
  "writeback does not move cargo",
);
check(!placed.schedule, "placement does not approve equipment bookings");
await page.locator(".action-receipt").scrollIntoViewIfNeeded();
await page.screenshot({ path: out + "/10-placement-acknowledged.png" });
await page.goto(
  `${base}/?run=${placementRun}&departure=NORTH-RAIL&cargo=CT-0121&page=Operations&revision=0`,
);
await page
  .getByRole("button", { name: "Return to current state", exact: true })
  .waitFor();
check(
  (await page
    .getByRole("button", { name: "Compare destinations", exact: true })
    .count()) === 0,
  "historical placement mutations unavailable",
);
await page.screenshot({ path: out + "/11-history.png" });
await fs.writeFile(
  out + "/additional-routes.json",
  JSON.stringify(
    {
      branch,
      placementRun,
      checks: [
        "admin unlock",
        "branch stays in Scenario lab",
        "inject failure",
        "recover on branch",
        "placement acknowledgement",
        "pickup rewrite",
        "no movement or booking",
        "historical mutation protection",
      ],
    },
    null,
    2,
  ),
);
check(errors.length === 0, JSON.stringify(errors));
await fs.writeFile(
  out + "/browser-checks.json",
  JSON.stringify(
    {
      run,
      errors,
      checks: [
        "case retained",
        "placement SQL comparison",
        "three schedules",
        "bundle selection",
        "approval dialog",
        "900px viewport",
        "scenario branch protection",
      ],
    },
    null,
    2,
  ),
);
await browser.close();
await api.dispose();
console.log(JSON.stringify({ run, errors }));
