import { chromium } from "playwright";
import fs from "node:fs/promises";
const base = "http://127.0.0.1:8790",
  out = "../docs/diagnosis";
const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage({
    viewport: { width: 1440, height: 1000 },
  });
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  const check = (v, m) => {
    if (!v) throw Error(m);
  };
  const login = await page.request.post(base + "/api/session", {
    data: { code: (await fs.readFile("../.local/admin-code", "utf8")).trim() },
  });
  const { csrf } = await login.json();
  const packs = await (await page.request.get(base + "/api/datasets")).json();
  const pack = packs.find((p) => p.id === "imperfect-information");
  const imported = await page.request.post(base + "/api/datasets/import", {
    headers: { "X-CSRF-Token": csrf },
    data: {
      pack_id: pack.id,
      expected_digest: pack.digest,
      request_id: crypto.randomUUID(),
    },
  });
  check(imported.ok(), "Import failed");
  const { id: run } = await imported.json();
  await page.goto(
    `${base}/?run=${run}&departure=NORTH-RAIL&cargo=CT-0121&entity=CT-0121`,
  );
  await page.locator(".diagnosis-next").waitFor();
  check(
    (await page.locator(".diagnosis-panel").innerText()).includes(
      "Container 121 · Next move ready",
    ),
    "Starting diagnosis",
  );
  await fs.mkdir(out, { recursive: true });
  await page.screenshot({ path: out + "/01-start.png", fullPage: true });
  await page.getByRole("button", { name: "+5 min", exact: true }).click();
  await page
    .locator(".diagnosis-next")
    .getByText("Work instruction needs reconciliation", { exact: true })
    .waitFor();
  check(
    (await page.locator(".diagnosis-next").innerText()).includes(
      "Container 122 is observed at Yard A · stack 2",
    ),
    "Correction explanation",
  );
  await page.locator('.toast').waitFor({state:'hidden'});
  await page.screenshot({ path: out + "/02-correction.png", fullPage: true });
  await page
    .getByRole("button", { name: "2 · Required work", exact: true })
    .click();
  check(
    (await page.locator(".work-panel tbody tr").count()) === 2,
    "Work scope leaked unrelated jobs",
  );
  check(
    (await page.getByLabel("Decision cargo").inputValue()) === "CT-0121",
    "Cargo lost on work page",
  );
  await page.reload();
  await page.locator(".diagnosis-next").waitFor();
  check(
    (await page.locator("h1").innerText()).includes("Know what can move next"),
    "Workspace URL lost",
  );
  await page
    .getByRole("button", { name: "Equipment windows", exact: true })
    .click();
  await page.locator(".calendar-plot").first().waitFor();
  check(
    (await page.locator(".equipment-lanes").innerText()).includes(
      "Morning road service",
    ),
    "Competing work missing",
  );
  await page.screenshot({ path: out + "/03-equipment.png", fullPage: true });
  await page
    .getByRole("button", { name: "3 · Check evidence", exact: true })
    .click();
  await page.locator(".data-current").waitFor();
  check(
    (await page.getByLabel("Decision cargo").inputValue()) === "CT-0121",
    "Cargo lost on evidence",
  );
  await page
    .getByRole("button", { name: "1 · Situation", exact: true })
    .click();
  await page
    .getByRole("button", {
      name: "Inspect starting snapshot · read-only",
      exact: true,
    })
    .click();
  await page
    .getByText("Read-only snapshot · revision 0", { exact: true })
    .waitFor();
  await page.waitForFunction(
    () => document.querySelector(".diagnosis-revision")?.textContent === "r0",
  );
  check(
    (await page.locator(".diagnosis-panel").innerText()).includes(
      "Next move ready",
    ),
    "Historical diagnosis polluted",
  );
  check(
    await page
      .getByRole("button", { name: "4 · Review recovery", exact: true })
      .isDisabled(),
    "Historical recovery enabled",
  );
  await page.reload();
  await page.waitForFunction(
    () => document.querySelector(".diagnosis-revision")?.textContent === "r0",
  );
  check(
    (await page.locator(".clockbar").innerText()).includes(
      "Read-only snapshot",
    ),
    "Historical URL lost",
  );
  await page
    .locator(".clockbar")
    .getByRole("button", { name: "Return to current state", exact: true })
    .click();
  await page
    .locator(".diagnosis-next")
    .getByText("Work instruction needs reconciliation", { exact: true })
    .waitFor();
  await page.getByLabel("Decision departure").selectOption("AURORA");
  await page.waitForFunction(
    () =>
      document.querySelector('[aria-label="Decision cargo"]').value ===
      "CT-0139",
  );
  await page.locator(".diagnosis-panel").waitFor();
  check(
    !(await page.locator(".diagnosis-next").innerText()).includes(
      "needs reconciliation",
    ),
    "Expected transfer misdiagnosed",
  );
  await page.getByLabel("Decision departure").selectOption("NORTH-RAIL");
  for (const width of [1100, 760, 390]) {
    await page.setViewportSize({ width, height: 900 });
    check(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth + 2,
      ),
      `Overflow at ${width}`,
    );
  }
  await page.screenshot({ path: out + "/04-mobile.png", fullPage: true });
  check(errors.length === 0, errors.join("\n"));
  await fs.writeFile(
    out + "/browser-audit.json",
    JSON.stringify(
      {
        run,
        errors,
        checks: [
          "baseline diagnosis",
          "late correction explanation",
          "scoped work queue",
          "workspace and cargo URL reload",
          "equipment activity and competing work",
          "evidence context",
          "historical diagnosis and action guard",
          "historical URL reload",
          "alternate departure expected transfer",
          "1100/760/390 layout",
        ],
      },
      null,
      2,
    ),
  );
  console.log(JSON.stringify({ run, errors }));
} finally {
  await browser.close();
}
