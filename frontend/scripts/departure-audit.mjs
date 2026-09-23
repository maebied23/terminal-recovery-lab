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
  const check = (ok, msg) => {
    if (!ok) throw Error(msg);
  };
  const out = "../docs/departure-workspace";
  await fs.mkdir(out, { recursive: true });
  const login = await page.request.post(base + "/api/session", {
    data: { code: (await fs.readFile("../.local/admin-code", "utf8")).trim() },
  });
  const { csrf } = await login.json();
  const created = await page.request.post(base + "/api/runs", {
    headers: { "X-CSRF-Token": csrf },
    data: {
      name: "Departure workspace · guided test",
      fresh: true,
      profile: "standard",
    },
  });
  check(created.ok(), "Create isolated test shift failed");
  const { id: run } = await created.json();
  await page.goto(`${base}/?run=${run}&departure=NORTH-RAIL`);
  await page
    .getByRole("heading", { name: "Protect the next departure." })
    .waitFor();
  check(
    (await page.locator(".cargo-choice").count()) === 6,
    "Manifest must include all six North Rail containers",
  );
  await page.getByRole("button", { name: /Container 121 CT-0121/ }).click();
  check(
    (await page.locator(".stack-section").innerText()).includes(
      "Container 122",
    ),
    "Physical cover missing",
  );
  const tasks = await page.locator(".departure-task").allTextContents();
  check(
    tasks.length === 2 &&
      tasks[0].includes("Relocate Container 122") &&
      tasks[1].includes("Retrieve Container 121"),
    "Wrong dependency order",
  );
  check(
    !(await page.locator(".inspector").count()),
    "Inspector steals case workspace space",
  );
  await page.screenshot({ path: out + "/01-departure.png", fullPage: true });
  await page
    .getByRole("button", { name: "Equipment activity", exact: true })
    .click();
  check(
    (await page.locator(".equipment-activity").innerText()).includes(
      "No recorded activity",
    ),
    "Initial timeline invents activity",
  );
  check(
    (await page.locator(".activity-track > span").count()) === 0,
    "Initial timeline has invented bars",
  );
  await page.getByRole("button", { name: "+5 min", exact: true }).click();
  await page.waitForFunction(
    () => document.querySelector(".shift-title strong").textContent === "08:05",
  );
  check(
    (await page.locator(".activity-track > span").count()) > 0,
    "No persisted activity after stepping",
  );
  await page.screenshot({ path: out + "/02-equipment.png", fullPage: true });
  await page
    .getByRole("button", { name: "Inspect starting snapshot · read-only" })
    .click();
  await page.getByText("Read-only snapshot · revision 0").waitFor();
  check(
    await page
      .getByRole("button", { name: "Open existing recovery tools" })
      .isDisabled(),
    "Historical action enabled",
  );
  check(
    (await page.locator(".activity-track > span").count()) === 0,
    "History displays current equipment use",
  );
  await page
    .getByRole("button", { name: "Stack & access", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Inspect cargo evidence", exact: true })
    .click();
  await page
    .getByRole("heading", { name: "Every decision has a history." })
    .waitFor();
  check(
    (await page.locator(".clockbar").innerText()).includes("revision 0"),
    "Evidence loses snapshot",
  );
  await page.getByRole("button", { name: "Operations", exact: true }).click();
  await page
    .getByRole("button", { name: "Return to current state", exact: true })
    .click();
  await page.getByLabel("Decision departure", { exact: true }).selectOption("AURORA");
  check(
    (await page.locator(".cargo-choice").count()) === 3,
    "Aurora outbound manifest must exclude inbound cargo",
  );
  check(
    (await page.getByLabel("Decision departure", { exact: true }).inputValue()) === "AURORA",
    "Service selection failed",
  );
  check(page.url().includes("departure=AURORA"), "Departure missing from URL");
  await page
    .getByLabel("Decision departure", { exact: true })
    .selectOption("NORTH-RAIL");
  await page.getByRole("button", { name: "Terminal map", exact: true }).click();
  check(
    (await page.getByLabel("Interactive terminal map").count()) === 1,
    "Map missing",
  );
  await page
    .getByRole("button", { name: "Terminal overview", exact: true })
    .click();
  await page
    .getByRole("heading", { name: "One terminal. Connected decisions." })
    .waitFor();
  await page
    .getByRole("button", { name: "Departure workspace", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Stack & access", exact: true })
    .click();
  for (const width of [1100, 760, 390]) {
    await page.setViewportSize({ width, height: 900 });
    check(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth + 2,
      ),
      `Horizontal overflow at ${width}`,
    );
  }
  await page.getByRole("button", { name: "Open existing recovery tools", exact: true }).click();
  await page.getByRole("heading", { name: "Make the next move count." }).waitFor();
  check((await page.locator(".inspector").innerText()).includes("MV-013"), "Recovery lost next-work context");
  await page.getByRole("button", { name: "Operations", exact: true }).click();
  await page.setViewportSize({ width: 1100, height: 900 });
  await page.screenshot({ path: out + "/03-laptop.png", fullPage: true });
  check(!errors.length, "Browser errors: " + errors.join("; "));
  await fs.writeFile(
    out + "/audit.json",
    JSON.stringify(
      {
        run,
        url: `${base}/?run=${run}&departure=NORTH-RAIL`,
        errors,
        checks: [
          "six-container manifest",
          "cross-container dependency order",
          "physical cover",
          "no sidebar dump",
          "empty initial activity",
          "persisted activity after step",
          "historical action disabled",
          "historical activity isolation",
          "evidence revision retained",
          "alternate departure",
          "URL context",
          "map",
          "original overview",
          "recovery next-work context",
          "1100/760/390 width",
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
