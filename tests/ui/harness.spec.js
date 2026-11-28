const { test, expect } = require("@playwright/test");
const { spawn } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const net = require("node:net");
const { startCoverage, finishCoverage, writeCoverage } = require("./coverage");

const repoRoot = path.resolve(__dirname, "../..");
const fixturePath = path.join(__dirname, "serve_fixture.py");
const sessionToken = "test-session-token";
let configDir;
let baseUrl;
let ownerToken;
let serverProcess;

async function findFreePort() {
  const listener = net.createServer();
  await new Promise((resolve, reject) => {
    listener.once("error", reject);
    listener.listen(0, "127.0.0.1", resolve);
  });
  const port = listener.address().port;
  await new Promise((resolve, reject) => listener.close((error) => {
    if (error) reject(error);
    else resolve();
  }));
  return port;
}

async function waitForServer() {
  const deadline = Date.now() + 20_000;
  while (Date.now() < deadline) {
    if (serverProcess.exitCode !== null) {
      throw new Error("Harness CLI fixture exited before the UI became ready.");
    }
    try {
      const response = await fetch(baseUrl);
      if (response.status === 200) return;
    } catch (_error) {}
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error("Harness CLI fixture did not serve the UI within 20 seconds.");
}

async function signInOwner(page) {
  await page.goto(baseUrl + "#" + ownerToken);
  await startCoverage(page);
  await expect(page.locator("#auth-text")).toHaveText("Connected");
  await expect(page.locator("#auth-modal")).toBeHidden();
  expect(new URL(page.url()).hash).toBe("");
  expect(await page.locator("body").innerText()).not.toContain(ownerToken);
}

test.beforeAll(async () => {
  configDir = fs.mkdtempSync(path.join(os.tmpdir(), "harness-ui-smoke-"));
  const port = await findFreePort();
  baseUrl = "http://127.0.0.1:" + port + "/";
  const python = process.env.PYTHON || (process.platform === "win32" ? "python" : "python3");
  const env = { ...process.env };
  for (const name of Object.keys(env)) {
    if (name.startsWith("HARNESS_") || name.endsWith("_API_KEY") || name.endsWith("_TOKEN")) {
      delete env[name];
    }
  }
  Object.assign(env, {
    HARNESS_CONFIG_DIR: configDir,
    HOME: configDir,
    USERPROFILE: configDir,
    PYTHONUTF8: "1",
  });
  env.PYTHONPATH = [repoRoot, env.PYTHONPATH].filter(Boolean).join(path.delimiter);
  serverProcess = spawn(python, [fixturePath, String(port), configDir], {
    cwd: repoRoot,
    env,
    stdio: "ignore",
  });
  await new Promise((resolve, reject) => {
    serverProcess.once("spawn", resolve);
    serverProcess.once("error", reject);
  });
  await waitForServer();
  ownerToken = fs.readFileSync(path.join(configDir, "desktop_token"), "utf8").trim();
  expect(ownerToken.length).toBeGreaterThanOrEqual(32);
  expect(fs.readFileSync(path.join(configDir, "gui-open.url"), "utf8"))
    .toContain("#" + ownerToken);
});

test.afterEach(async () => {
  await finishCoverage();
});

test.afterAll(async () => {
  await finishCoverage();
  writeCoverage();
  if (serverProcess && serverProcess.exitCode === null) {
    serverProcess.kill();
    await new Promise((resolve) => serverProcess.once("exit", resolve));
  }
  if (configDir) {
    const target = path.resolve(configDir);
    const tempRoot = path.resolve(os.tmpdir());
    if (path.dirname(target) === tempRoot
        && path.basename(target).startsWith("harness-ui-smoke-")) {
      fs.rmSync(target, { recursive: true, force: true });
    }
  }
});

test("01 launch, load, and one-time browser pairing", async ({ page }) => {
  const requestUrls = [];
  page.on("request", (request) => requestUrls.push(request.url()));
  await page.goto(baseUrl);
  await startCoverage(page);
  await expect(page.locator("#auth-modal")).toBeVisible();
  await expect(page.getByText("One-time pairing code", { exact: true })).toBeVisible();
  await expect(page.locator("#auth-connect-help")).toContainText("gui-open.url");
  await expect(page.locator("#auth-connect-help")).toContainText("harness serve --open");

  const ownerPage = await page.context().newPage();
  await signInOwner(ownerPage);
  await ownerPage.locator("#btn-auth-toggle").click();
  await expect(ownerPage.locator("#auth-title")).toHaveText("Pair another browser");
  await ownerPage.locator("#btn-create-pair").click();
  const codeOutput = ownerPage.locator("#auth-pair-code");
  await expect(codeOutput).toHaveText(/[23456789ABCDEFGHJKLMNPQRSTUVWXYZ]{5}-[23456789ABCDEFGHJKLMNPQRSTUVWXYZ]{5}/);
  const code = await codeOutput.textContent();
  expect(code).not.toContain(ownerToken);

  await page.locator("#auth-pair-input").fill(code);
  await page.locator("#btn-connect-pair").click();
  await expect(page.locator("#auth-modal")).toBeHidden();
  await expect(page.locator("#auth-text")).toHaveText("Connected");
  expect(await page.locator("body").innerText()).not.toContain(ownerToken);
  expect(requestUrls.every((url) => !url.includes(ownerToken))).toBe(true);

  const duplicate = await page.evaluate(async (pairCode) => {
    const response = await fetch("/api/auth/pair/redeem", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code: pairCode.replace(/-/g, "") }),
    });
    return response.status;
  }, code);
  expect(duplicate).toBe(401);

  await page.reload();
  await expect(page.locator("#auth-text")).toHaveText("Connected");
  await expect(page.locator("#auth-modal")).toBeHidden();
  const runtime = await page.evaluate(() => ({
    origin: window.location.origin,
    electron: typeof window.require !== "undefined",
    webview: typeof window.pywebview !== "undefined",
  }));
  expect(runtime.origin).toBe(baseUrl.slice(0, -1));
  expect(runtime.electron).toBe(false);
  expect(runtime.webview).toBe(false);
});

test("02 primary chat request uses the served UI and real CLI route", async ({ page }) => {
  await signInOwner(page);
  const request = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return url.pathname === "/api/chat"
      && response.request().method() === "POST";
  });
  await page.locator("#prompt-input").fill("primary request");
  await page.locator("#prompt-input").press("Enter");
  const response = await request;
  expect(response.status()).toBe(201);
  const run = await response.json();
  expect(run.kind).toBe("chat");
  expect(run.id).toMatch(/^[A-Za-z0-9_-]+$/);
});

test("03 driver studio surface loads from the served UI", async ({ page }) => {
  await signInOwner(page);
  await page.locator('[data-pane="studio"]').click();
  await page.locator('.subtool-btn[data-pane="driver"]').click();
  await expect(page.locator("#subtool-body h2")).toHaveText("Driver");
  await expect(page.locator("#driver-watch-card")).toBeVisible();
  await page.locator("#btn-watch-start").click();
  await expect(page.locator("#driver-watch-pill")).toContainText("running");
  await page.locator("#btn-watch-pause").click();
  await expect(page.locator("#driver-watch-pill")).toContainText("paused");
  await page.locator("#btn-watch-resume").click();
  await expect(page.locator("#driver-watch-pill")).toContainText("running");
  await page.locator("#btn-watch-stop").click();
  await expect(page.locator("#driver-watch-pill")).toContainText("stopped");
  await page.locator("#btn-watch-refresh").click();
  await expect(page.getByText("Task Request / Goal")).toBeVisible();
  await expect(page.locator("#subtool-body")).toContainText("Perception & Health");
});

test("04 settings and provider status expose posture without credentials", async ({ page }) => {
  await signInOwner(page);
  await expect(page.locator("#route-text")).toContainText("Primary: free");
  await page.locator('[data-pane="studio"]').click();
  await page.locator('.subtool-btn[data-pane="legacy"]').click();
  const settingsRow = page.locator(".pane-legacy-row")
    .filter({ hasText: "/api/settings" });
  await settingsRow.getByRole("button", { name: "Fetch" }).click();
  const output = settingsRow.locator("pre");
  await expect(output).toBeVisible();
  await expect(output).toContainText('"paid_key_present": false');
  await expect(output).toContainText('"jev_api_key": null');
  await expect(output).toContainText('"mcp_auth_token": null');
  await expect(output).not.toContainText(ownerToken);
  await expect(output).not.toContainText(sessionToken);

  // Clearing browser storage exercises the real 401 recovery path through
  // the served settings control and the server's auth middleware.
  await page.evaluate(() => window.HARNESS_SET_TOKEN(null));
  await settingsRow.getByRole("button", { name: "Fetch" }).click();
  await expect(page.locator("#auth-modal")).toBeVisible();
  await page.locator("#btn-cancel-token").click();
  await expect(page.locator("#auth-modal")).toBeHidden();
});

test("05 terminal result is rendered after the real chat dispatch completes", async ({ page }) => {
  await signInOwner(page);
  await page.locator("#prompt-input").fill("terminal result");
  await page.locator("#prompt-input").press("Enter");
  await expect(page.locator("#chat-feed")).toContainText(
    "E2E offline response: terminal result",
    { timeout: 10_000 },
  );
  await expect(page.locator("#chat-feed")).toContainText("Execution complete");
});

test("[negative-control] deliberately broken settings journey fails its UI assertion", async ({ page }) => {
  await page.route("**/api/settings", (route) => route.fulfill({
    status: 503,
    contentType: "application/json",
    body: JSON.stringify({ error: "negative control: settings route unavailable" }),
  }));
  await signInOwner(page);
  // The journey's normal assertion must fail when the settings route is broken.
  await expect(page.locator("#route-text")).toContainText("Primary: free");
});

test("06 driver NL intake plans, cancels, and runs through the served card", async ({ page }) => {
  await signInOwner(page);
  const plan = {
    status: "plan",
    plan_id: "plan-journey-1",
    plan: [
      { action: "open_app", params: { name: "notepad" }, class: "mutating" },
      { action: "delete_file", params: { path: "notes.txt" }, class: "irreversible" },
    ],
  };
  const run = {
    status: "done",
    plan_id: "plan-journey-1",
    steps: [
      { action: "open_app", ok: true },
      { action: "delete_file", ok: true },
    ],
  };
  await page.route("**/api/driver/nl", (route) => {
    const body = JSON.parse(route.request().postData() || "{}");
    let payload = plan;
    if (body.confirm) payload = run;
    else if (body.cancel_plan) payload = { status: "cancelled" };
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(payload),
    });
  });

  const section = page.locator("#driver-nl");
  await expect(section).toBeVisible();
  await expect(page.locator("#driver-nl-card")).toBeHidden();
  await expect(page.locator("#driver-nl-steps li")).toHaveCount(0);

  // Empty input is refused in place; no request leaves the page.
  await page.locator("#btn-driver-nl-plan").click();
  await expect(page.locator("#driver-nl-status")).toHaveText("Type an instruction first.");

  await page.locator("#driver-nl-input").fill("open notepad and delete notes.txt");
  await page.locator("#btn-driver-nl-plan").click();
  await expect(page.locator("#driver-nl-card")).toBeVisible();
  await expect(page.locator("#driver-nl-steps li")).toHaveCount(2);
  await expect(page.locator("#driver-nl-steps li").first()).toContainText("open_app");
  await expect(page.locator("#driver-nl-steps li").first().locator(".driver-nl-class"))
    .toHaveText("mutating");
  await expect(page.locator("#driver-nl-steps li").nth(1).locator(".driver-nl-class.irreversible"))
    .toHaveText("irreversible");
  // The step-state slot shares the driver-nl-params class (the plan renderer
  // uses it for both the params text and the live status cell), so the params
  // assertion is scoped to the first match in the row.
  await expect(page.locator("#driver-nl-steps li").first().locator(".driver-nl-params").first())
    .toContainText("notepad");
  await expect(page.locator("#driver-nl-status"))
    .toHaveText("Plan ready — review each step, then Run Plan.");

  // Cancel is a real request and reports its own status.
  await page.locator("#btn-driver-nl-cancel").click();
  await expect(page.locator("#driver-nl-status"))
    .toHaveText("Cancellation requested — running steps stop between steps.");

  await page.locator("#btn-driver-nl-run").click();
  await expect(page.locator("#driver-nl-status")).toHaveText("Done.");
  await expect(page.locator("#driver-nl-steps li").first().locator("[data-step-state]"))
    .toContainText("✓");
});

async function openStudio(page) {
  await page.locator('.pane-tab', { hasText: "Studio Inspector" }).click();
  return page.locator("#subtool-body");
}

async function pickSubtool(page, label) {
  await page.locator(".subtool-btn", { hasText: label }).click();
}

const POPULATED_SNAPSHOT = {
  sessions: [{
    metrics: {
      run_depth_distribution: {
        T0: { runs: 10, share: 0.5 }, T1: { runs: 4, share: 0.2 },
        T2: { runs: 4, share: 0.2 }, T3: { runs: 2, share: 0.1 },
      },
      cost_per_gated_task: { T0: { median_cost: 0.001, samples: 5 },
                             T1: { median_cost: 0.002, samples: 3 } },
      escalation_escape_rate: { T2: { escape_rate: 0.25, samples: 4 } },
      frontier_warrant_rate: { frontier_runs: 2, warranted: 1,
                               warrant_rate: 0.5, unwarranted_flagged: 1 },
      hourglass_savings: { actual_cost: 1.5, modeled_frontier_cost: 4.25,
                           basis: "modeled from the pricing snapshot" },
    },
  }],
};

test("07 studio inspector: Proof renders its populated content exactly once", async ({ page }) => {
  await page.route("**/api/snapshot", (route) =>
    route.fulfill({ status: 200, contentType: "application/json",
                    body: JSON.stringify(POPULATED_SNAPSHOT) }));
  await signInOwner(page);
  await openStudio(page);
  await pickSubtool(page, "Proof");
  const body = page.locator("#subtool-body");
  await expect(body).toContainText("Run depth (the hourglass)");
  // Superseded renders must not stack a second copy of the pane (#586).
  expect(await body.locator("h2").count()).toBe(1);
  await expect(body).toContainText("Cost per gated task");
  await expect(body).toContainText("$1.50 actual vs");
  await expect(body).toContainText("$4.25 modeled");
  await expect(body).toContainText("No escalations in the recent ledger tail.");
});

test("08 studio inspector: an unpaired pane offers Connect instead of going blank",
     async ({ page }) => {
  await page.route("**/api/snapshot", (route) =>
    route.fulfill({ status: 401, contentType: "application/json",
                    body: JSON.stringify({ error: "This browser is not connected to Harness" }) }));
  await signInOwner(page);
  await openStudio(page);
  await pickSubtool(page, "Proof");
  const body = page.locator("#subtool-body");
  await expect(body).toContainText("This browser is not connected to Harness");
  await expect(body.locator("button", { hasText: "Connect browser" })).toBeVisible();
  // The pane must not have parked: the heading it draws first is followed by
  // a message and an action, not left alone.
  expect(await body.locator("h2").count()).toBe(1);
  await expect(body.locator("h2")).toContainText("Proof Bench");
});

test("09 studio inspector: a failed snapshot says so, and an empty ledger says so",
     async ({ page }) => {
  await page.route("**/api/snapshot", (route) =>
    route.fulfill({ status: 500, contentType: "application/json",
                    body: JSON.stringify({ error: "snapshot exploded" }) }));
  await signInOwner(page);
  await openStudio(page);
  await pickSubtool(page, "Proof");
  await expect(page.locator("#subtool-body")).toContainText("Snapshot unavailable");

  await page.unroute("**/api/snapshot");
  await page.route("**/api/snapshot", (route) =>
    route.fulfill({ status: 200, contentType: "application/json",
                    body: JSON.stringify({ sessions: [] }) }));
  await pickSubtool(page, "Intake");
  await pickSubtool(page, "Proof");
  await expect(page.locator("#subtool-body"))
    .toContainText("No runs in the local ledger yet");
});

test("10 studio inspector: modeled baseline absent is not printed as a comparison",
     async ({ page }) => {
  const snapshot = { sessions: [{ metrics: {
    run_depth_distribution: { T0: { runs: 3, share: 1 } },
    cost_per_gated_task: { T0: { median_cost: 0.001, samples: 2 } },
    escalation_escape_rate: {},
    frontier_warrant_rate: {},
    hourglass_savings: { actual_cost: 0.75, basis: "unavailable: no priced model" },
  } }] };
  await page.route("**/api/snapshot", (route) =>
    route.fulfill({ status: 200, contentType: "application/json",
                    body: JSON.stringify(snapshot) }));
  await signInOwner(page);
  await openStudio(page);
  await pickSubtool(page, "Proof");
  const body = page.locator("#subtool-body");
  await expect(body).toContainText("No modeled frontier baseline");
  await expect(body).not.toContainText("actual vs —");
});

test("11 studio inspector: Proof makes one read and paints each section as it lands",
     async ({ page }) => {
  const asked = [];
  page.on("request", r => asked.push(new URL(r.url()).pathname));
  const snapshot = {
    sessions: [{ metrics: {
      run_depth_distribution: { T0: { runs: 2, share: 1 } },
      cost_per_gated_task: { T0: { median_cost: 0.001, samples: 2 } },
      escalation_escape_rate: {},
      frontier_warrant_rate: {},
      hourglass_savings: { actual_cost: 1, modeled_frontier_cost: 2 },
    } }],
    recent_escalations: [{ seq: 7, from_model: "m-a", to_model: "m-b",
                           directed_by: "jev", jev_confidence: 0.9,
                           task_id: "task-7", event: "escalate" }],
  };
  await page.route("**/api/snapshot", (route) =>
    route.fulfill({ status: 200, contentType: "application/json",
                    body: JSON.stringify(snapshot) }));
  await signInOwner(page);
  // Studio opens on Proof; clicking the tab is one render, so one read.
  const body = await openStudio(page);
  await expect(body).toContainText("Run depth (the hourglass)");
  // The escalations section comes from the same payload: no second ledger
  // read, which is what used to gate the first paint (#599).
  await expect(body).toContainText("task-7");
  expect(asked.filter(p => p === "/api/ledger/tail").length).toBe(0);
  expect(asked.filter(p => p === "/api/snapshot").length).toBe(1);
  expect(await body.locator("h3").count()).toBe(6);
  await expect(body.locator("[data-pane-loading]")).toHaveCount(0);
});
