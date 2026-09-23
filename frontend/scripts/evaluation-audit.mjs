import { chromium, request } from "playwright";
import fs from "node:fs/promises";
const base = "http://127.0.0.1:8790",
  run = "eval-daa648df",
  eid = "25954807-cd69-41f9-a9d9-2c7a8443fa24";
const check = (v, m) => {
  if (!v) throw Error(m);
};
const api = await request.newContext({ baseURL: base });
const before = await (await api.get("/api/state?run=" + run)).json();
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } }),
  errors = [];
page.on("pageerror", (e) => errors.push(e.message));
page.on("response", (r) => {
  if (r.status() >= 400) errors.push(r.status() + " " + r.url());
});
try {
  await page.goto(`${base}/?run=${run}&page=Scenario%20lab`);
  await page
    .getByRole("heading", { name: "Does the plan survive execution?" })
    .waitFor();
  await page.getByLabel("Evaluation report").selectOption(eid);
  await page.getByText("7 wins · 7 ties · 4 losses").waitFor();
  await page.locator(".evaluation-panel").first().scrollIntoViewIfNeeded();
  await page.screenshot({
    path: "../docs/evaluation/01-results.png",
    fullPage: true,
  });
  await page
    .getByText("Which departures gained or lost?", { exact: true })
    .click();
  await page.getByLabel("Evaluation case").selectOption("slow-handling");
  check(
    (await page.locator(".evaluation-panel").innerText()).includes(
      "interrupted",
    ),
    "interrupted evidence visible",
  );
  await page.getByLabel("Evaluation case").scrollIntoViewIfNeeded();
  await page.screenshot({ path: "../docs/evaluation/02-case.png" });
  await page.locator(".assistant-trigger").click();
  await page
    .getByRole("button", {
      name: "What do evaluation results show?",
      exact: true,
    })
    .click();
  await page.locator(".assistant-answer").waitFor({ timeout: 20000 });
  check(
    (await page.locator(".assistant-answer").innerText()).includes(
      "Synthetic fixed-schedule tests",
    ),
    "assistant caveat",
  );
  check(
    (await page.locator(".assistant-answer").innerText()).includes(eid),
    "selected report is assistant context",
  );
  check(
    (await page.locator(".assistant-answer").innerText()).includes("4 losses"),
    "assistant preserves regressions",
  );
  check(
    (await page.locator(".assistant-citations a").count()) > 0,
    "evidence citations",
  );
  await page.screenshot({ path: "../docs/assistant/01-evidence.png" });
  await page.getByRole("button", { name: "Close assistant" }).click();
  await page.getByRole("button", { name: "Evidence", exact: true }).click();
  await page
    .getByRole("heading", { name: "Assistant evidence trail" })
    .waitFor();
  await page
    .getByRole("heading", { name: "Assistant evidence trail" })
    .scrollIntoViewIfNeeded();
  await page.screenshot({ path: "../docs/assistant/02-trace.png" });
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto(`${base}/?run=${run}&page=Scenario%20lab`);
  await page.getByLabel("Evaluation report").selectOption(eid);
  await page.getByText("7 wins · 7 ties · 4 losses").waitFor();
  await page.locator(".evaluation-panel").first().scrollIntoViewIfNeeded();
  check(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
    "no laptop document overflow",
  );
  await page.screenshot({ path: "../docs/evaluation/03-laptop.png" });
  const after = await (await api.get("/api/state?run=" + run)).json();
  check(
    before.revision === after.revision && before.minute === after.minute,
    "no operational state mutation",
  );
  check(errors.length === 0, JSON.stringify(errors));
  await fs.writeFile(
    "../docs/evaluation/browser-audit.json",
    JSON.stringify(
      {
        run,
        evaluation: eid,
        checks: [
          "SQL report cards",
          "per-departure impact",
          "case interruption",
          "assistant citations",
          "persisted traces",
          "1280px layout",
          "operational revision unchanged",
        ],
        errors,
        revision: after.revision,
      },
      null,
      2,
    ),
  );
  console.log("Evaluation and assistant browser audit passed");
} finally {
  await browser.close();
  await api.dispose();
}
