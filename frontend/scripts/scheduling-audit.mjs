import { chromium, request as playwrightRequest } from "playwright";
import fs from "node:fs/promises";
const base = "http://127.0.0.1:8790",
  out = process.env.AUDIT_OUT || "../docs/scheduling";
const api = await playwrightRequest.newContext({ baseURL: base });
const login = await api.post("/api/session", {
  data: { code: (await fs.readFile("../.local/admin-code", "utf8")).trim() },
});
const { csrf } = await login.json(),
  headers = { "X-CSRF-Token": csrf };
const check = (v, m) => {
  if (!v) throw Error(m);
};
const packs = await (await api.get("/api/datasets")).json();
async function importPack(id) {
  const p = packs.find((p) => p.id === id);
  const res = await api.post("/api/datasets/import", {
    headers,
    data: {
      pack_id: id,
      expected_digest: p.digest,
      request_id: crypto.randomUUID(),
    },
  });
  check(res.ok(), "import " + (await res.text()));
  return (await res.json()).id;
}
async function state(run) {
  return await (await api.get("/api/state?run=" + run)).json();
}
async function cmd(run, action, extra = {}) {
  const s = await state(run);
  const res = await api.post("/api/commands?run=" + run, {
    headers,
    data: {
      action,
      expected_revision: s.revision,
      command_id: crypto.randomUUID(),
      ...extra,
    },
  });
  check(res.ok(), await res.text());
  const id = (await res.json()).id;
  for (let i = 0; i < 100; i++) {
    const rows = await (await api.get("/api/commands?run=" + run)).json();
    const c = rows.find((x) => x.id === id);
    if (c?.status === "acknowledged") return;
    check(!["failed", "rejected"].includes(c?.status), JSON.stringify(c));
    await new Promise((r) => setTimeout(r, 100));
  }
  throw Error("command timed out");
}
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
try {
  const run = await importPack("baseline-shift");
  const url = `${base}/?run=${run}&departure=NORTH-RAIL&cargo=CT-0121&page=Recovery`;
  await page.goto(url);
  await page
    .getByRole("button", { name: "Build recovery schedules", exact: true })
    .click();
  await page.locator(".schedule-candidates").waitFor({ timeout: 60000 });
  check(
    (await page.locator(".schedule-choice").count()) === 3,
    "three alternatives",
  );
  check(
    (await page.locator(".schedule-detail").innerText()).includes(
      "Morning road service",
    ),
    "competing departures visible",
  );
  await fs.mkdir(out, { recursive: true });
  await page.screenshot({ path: out + "/01-compare.png" });
  await page.locator(".schedule-timeline").scrollIntoViewIfNeeded();
  await page.screenshot({ path: out + "/02-bookings.png" });
  await page
    .getByRole("button", { name: "Review schedule for approval" })
    .click();
  await page.getByRole("dialog").waitFor();
  await page.screenshot({ path: out + "/03-approval.png" });
  await page
    .getByRole("button", { name: "Approve resource bookings", exact: true })
    .click();
  for (let i = 0; i < 150; i++) {
    if ((await state(run)).schedule) break;
    await new Promise((r) => setTimeout(r, 100));
  }
  const approved = await state(run);
  check(
    approved.minute === 0 && approved.schedule.status === "approved",
    "approval must not move cargo",
  );
  await cmd(run, "advance", { minutes: 1 });
  const underway = await state(run);
  check(
    underway.jobs.some((j) => j.status === "running"),
    "bookings dispatched",
  );
  await page.getByRole("button", { name: "Operations", exact: true }).click();
  await page
    .getByRole("heading", { name: "North Rail", exact: true })
    .waitFor();
  check(
    (await page.getByLabel("Case container").inputValue()) === "CT-0121",
    "case cargo preserved",
  );
  await page.getByRole("button", { name: "4 Execution", exact: true }).click();
  await page.getByRole("heading", { name: "Execution", exact: true }).waitFor();
  await page.getByRole("button", { name: "Evidence", exact: true }).click();
  await page
    .getByRole("heading", { name: /Shared approved schedule/ })
    .waitFor();
  const working = underway.jobs.find((j) => j.status === "running");
  await cmd(run, "fail", { entity_id: working.resources[0] });
  await page.getByRole("button", { name: "Recovery", exact: true }).click();
  await page
    .locator(".approved-schedule")
    .getByText("interrupted", { exact: true })
    .waitFor();
  check(
    (await state(run)).jobs.find((j) => j.id === working.id).status ===
      "running",
    "failed load must remain frozen",
  );
  await page.locator(".approved-schedule").scrollIntoViewIfNeeded();
  await page.screenshot({ path: out + "/04-interruption.png" });
  check(
    await page
      .getByRole("button", { name: "Review schedule for approval" })
      .isDisabled(),
    "stale approval disabled",
  );
  const fresh = await importPack("baseline-shift");
  const res = await api.post("/api/schedules?run=" + fresh, {
    headers,
    data: {
      expected_revision: 0,
      focus_commitment: "NORTH-RAIL",
      horizon: 180,
    },
  });
  check(res.ok(), "fresh comparison submission");
  for (let i = 0; i < 200; i++) {
    const comparisons = await (
      await api.get("/api/schedules?run=" + fresh)
    ).json();
    if (comparisons[0]?.status === "completed") break;
    check(comparisons[0]?.status !== "failed", "walkthrough planner failed");
    await new Promise((r) => setTimeout(r, 100));
  }
  const freshUrl = `${base}/?run=${fresh}&departure=NORTH-RAIL&cargo=CT-0121&page=Recovery`;
  await page.setViewportSize({ width: 1024, height: 800 });
  await page.goto(freshUrl);
  await page.locator(".schedule-candidates").waitFor({ timeout: 60000 });
  check(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
    "page overflow at laptop width",
  );
  await page.screenshot({ path: out + "/05-laptop.png" });
  check(errors.length === 0, JSON.stringify(errors));
  const record = {
    run: fresh,
    interrupted_run: run,
    url: freshUrl,
    interrupted_url: url,
    checks: [
      "comparison",
      "competing departures",
      "bookings",
      "approval does not move",
      "scheduled dispatch",
      "cross-page context",
      "failure freezes running load",
      "stale approval disabled",
      "1024px layout",
      "no browser errors",
    ],
  };
  await fs.writeFile(
    out + "/walkthrough.json",
    JSON.stringify(record, null, 2),
  );
  console.log(JSON.stringify(record, null, 2));
} finally {
  await browser.close();
  await api.dispose();
}
