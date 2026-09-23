import { chromium } from "playwright";
import fs from "node:fs/promises";
const base = "http://127.0.0.1:8790";
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
  const out = "../docs/data-foundation";
  await fs.mkdir(out, { recursive: true });
  await page.goto(base);
  await page.getByRole("button", { name: "Scenario lab", exact: true }).click();
  await page
    .getByLabel("Input pack", { exact: true })
    .selectOption("imperfect-information");
  check(
    await page
      .getByRole("button", { name: "Import as a new paused shift" })
      .isDisabled(),
    "Operator can import",
  );
  await page
    .getByLabel("Scenario administrator code")
    .fill((await fs.readFile("../.local/admin-code", "utf8")).trim());
  await page.getByRole("button", { name: "Unlock scenario controls" }).click();
  const response = page.waitForResponse(
    (r) =>
      r.url().endsWith("/api/datasets/import") &&
      r.request().method() === "POST",
  );
  await page
    .getByRole("button", { name: "Import as a new paused shift" })
    .click();
  const result = await response;
  check(result.ok(), "Import failed");
  const { id: run } = await result.json();
  await page.waitForFunction(
    (id) => document.querySelector('[aria-label="Active shift"]').value === id,
    run,
  );
  await page
    .locator(".data-current")
    .getByText("Delayed and conflicting observations", { exact: true })
    .waitFor();
  check(
    (await page.locator(".clockbar").innerText()).includes("08:00"),
    "Import advanced clock",
  );
  await page.screenshot({ path: out + "/01-imported.png", fullPage: true });
  await page.getByRole("button", { name: "+5 min", exact: true }).click();
  await page.waitForFunction(
    () => document.querySelector(".shift-title strong").textContent === "08:05",
  );
  await page.waitForFunction(
    () => document.querySelectorAll(".data-receipts article").length === 6,
  );
  const statuses = await page.locator(".receipt-status").allTextContents();
  check(
    statuses.filter((x) => x === "applied").length === 2,
    "Wrong applied count",
  );
  check(
    statuses.includes("duplicate") &&
      statuses.includes("stale") &&
      statuses.filter((x) => x === "quarantined").length === 2,
    "Receipt outcomes missing",
  );
  check(
    (await page.locator(".data-impact").innerText()).includes("North Rail"),
    "SQL impact missing",
  );
  await page.screenshot({ path: out + "/02-reconciled.png", fullPage: true });
  await page.getByRole("button", { name: "Operations", exact: true }).click();
  await page.getByRole("button", { name: /Container 122 CT-0122/ }).click();
  check(
    (await page.locator(".departure-input-origin").innerText()).includes(
      "inventory",
    ),
    "Position provenance missing",
  );
  const top = await page.locator(".stack-tier").first().innerText();
  check(
    top.includes("Container 122"),
    "Accepted position did not reach operational UI",
  );
  await page
    .getByRole("button", { name: "Inspect starting snapshot · read-only" })
    .click();
  await page.getByText("Read-only snapshot · revision 0").waitFor();
  await page.getByRole("button", { name: /Container 121 CT-0121/ }).click();
  check(
    (await page.locator(".stack-tier").first().innerText()).includes(
      "Container 122",
    ),
    "Historical stack changed",
  );
  await page.getByRole("button", { name: "Inspect input provenance" }).click();
  await page
    .locator(".data-inputs")
    .getByText(/No test observations had been delivered/)
    .waitFor();
  check(
    (await page.locator(".data-receipts article").count()) === 0,
    "Future receipts leaked into past",
  );
  await page
    .locator(".clockbar")
    .getByRole("button", { name: "Return to current state", exact: true })
    .click();
  await page.getByRole("button", { name: "Scenario lab", exact: true }).click();
  await page.getByRole("button", { name: "+5 min", exact: true }).click();
  await page.waitForFunction(
    () => document.querySelectorAll(".data-receipts article").length === 8,
  );
  check(
    (await page.locator(".receipt-status").allTextContents()).filter(
      (x) => x === "quarantined",
    ).length === 3,
    "Collision not quarantined",
  );
  await page.getByLabel("Trace input entity").selectOption("YC-1");
  await page
    .getByRole("button", { name: "Close inspector", exact: true })
    .click();
  for (const width of [1100, 760, 390]) {
    await page.setViewportSize({ width, height: 900 });
    check(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth + 2,
      ),
      `Overflow at ${width}`,
    );
  }
  await page.setViewportSize({ width: 1100, height: 900 });
  await page.screenshot({ path: out + "/03-laptop.png", fullPage: true });
  check(!errors.length, "Browser errors: " + errors.join("; "));
  await fs.writeFile(
    out + "/browser-audit.json",
    JSON.stringify(
      {
        run,
        errors,
        checks: [
          "operator import denied",
          "admin UI import",
          "new paused shift",
          "six receipts at 08:05",
          "correct application/dedup/stale/quarantine",
          "SQL downstream commitments",
          "position correction visible in departure",
          "historical stack intact",
          "no future receipt leakage",
          "collision refused",
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
