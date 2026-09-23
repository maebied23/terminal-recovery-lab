import { chromium } from "playwright";
import fs from "node:fs/promises";
const base = "http://127.0.0.1:8790";
const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({
  viewport: { width: 1440, height: 1000 },
});
const page = await context.newPage();
const errors = [];
page.on("response", (r) => {
  if (r.status() >= 400) errors.push(`${r.status()} ${r.url()}`);
});
page.on("pageerror", (e) => errors.push(e.message));
page.on("console", (m) => {
  if (m.type() === "error") errors.push(m.text());
});
await page.goto(base, { waitUntil: "domcontentloaded" });
await page
  .getByRole("button", { name: "Terminal overview", exact: true })
  .click();
await page
  .getByRole("heading", { name: "One terminal. Connected decisions." })
  .waitFor();
await page.screenshot({
  path: "../docs/screenshots/01-operations.png",
  fullPage: true,
});
await page.getByRole("button", { name: "Inspect YC-1", exact: true }).click();
await page.getByText("FOLLOW THE WORK").waitFor();
await page.screenshot({
  path: "../docs/screenshots/02-inspector.png",
  fullPage: true,
});
await page.getByRole("button", { name: "Close inspector" }).click();
await page.getByRole("button", { name: "Scenario lab", exact: true }).click();
await page
  .getByLabel("Scenario administrator code")
  .fill((await fs.readFile("../.local/admin-code", "utf8")).trim());
await page.getByRole("button", { name: "Unlock scenario controls" }).click();
await page
  .getByRole("button", { name: "New standard shift · 144 containers" })
  .waitFor();
await page
  .getByRole("button", { name: "New standard shift · 144 containers" })
  .click();
await page
  .getByRole("heading", { name: "One terminal. Connected decisions." })
  .waitFor();
await page.waitForFunction(
  () =>
    document.querySelector('select[aria-label="Active shift"]').value !==
    "main",
);
const run = await page.getByLabel("Active shift").inputValue();
await page.getByRole("button", { name: "Scenario lab", exact: true }).click();
await page.getByRole("button", { name: "Inject failure", exact: true }).click();
await page.waitForFunction(async (run) => {
  const s = await (await fetch("/api/state?run=" + run)).json();
  return s.equipment.find((e) => e.id === "YC-1").status === "failed";
}, run);
await page.getByRole("button", { name: "Recovery", exact: true }).click();
await page
  .getByText("Additional tools · access relocations and policy experiments", {
    exact: true,
  })
  .click();
await page.getByRole("button", { name: "Compare plans", exact: true }).click();
await page
  .getByRole("heading", { name: "Recovery alternatives", exact: false })
  .waitFor({ timeout: 90000 });
await page.screenshot({
  path: "../docs/screenshots/03-recovery.png",
  fullPage: true,
});
await page
  .getByRole("button", { name: "Approve policy", exact: true })
  .first()
  .click();
await page.getByRole("button", { name: "Approve & submit" }).click();
await page
  .getByRole("heading", { name: /Approved policy/ })
  .waitFor({ timeout: 15000 });
await page.getByRole("button", { name: "+5 min", exact: true }).click();
await page.waitForFunction(
  async (run) =>
    (await (await fetch("/api/state?run=" + run)).json()).minute === 5,
  run,
);
await page
  .getByRole("button", { name: "Work & commitments", exact: true })
  .click();
await page.getByLabel("Search handling moves").fill("MV-001");
if ((await page.locator("tbody tr").count()) !== 1)
  throw Error("Work search did not narrow to a single job");
await page.getByRole("button", { name: "Evidence", exact: true }).click();
await page
  .getByRole("heading", { name: "Every decision has a history." })
  .waitFor();
await page.screenshot({
  path: "../docs/screenshots/04-evidence.png",
  fullPage: true,
});
await page.getByLabel("Historical revision").fill("0");
await page.getByRole("button", { name: "Inspect snapshot" }).click();
await page.getByText("Read-only snapshot · revision 0").waitFor();
await page
  .getByRole("button", { name: "Return to current state", exact: true })
  .click();
await page.getByRole("button", { name: "Ask the terminal" }).click();
await page.getByRole("button", { name: "How is risk calculated?" }).click();
await page.getByText("Risk labels are rule-based:", { exact: false }).waitFor();
await page.getByRole("button", { name: "Close assistant" }).click();
await page.setViewportSize({ width: 390, height: 844 });
await page.screenshot({
  path: "../docs/screenshots/05-mobile.png",
  fullPage: true,
});
const overflow = await page.evaluate(
  () => document.documentElement.scrollWidth > window.innerWidth,
);
console.log(
  JSON.stringify({
    run,
    errors,
    mobileOverflow: overflow,
    checks: [
      "map selection",
      "admin login",
      "isolated shift",
      "equipment failure",
      "simulation comparison",
      "human approval",
      "advance clock",
      "work search",
      "historical snapshot",
      "assistant tools",
      "responsive layout",
    ],
  }),
);
await browser.close();
if (errors.length || overflow) process.exitCode = 1;
