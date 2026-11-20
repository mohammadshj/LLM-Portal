// Run on a local test installation. See tests/browser/README.md.
const assert = require("node:assert/strict");
const { spawn, execFileSync } = require("node:child_process");
const { randomBytes } = require("node:crypto");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const readline = require("node:readline");
const { setTimeout: pause } = require("node:timers/promises");
const { chromium } = require("playwright");

const root = path.resolve(__dirname, "../..");
const base = process.env.PORTAL_TEST_URL || "http://127.0.0.1:8080";
const user = "stream_test_" + randomBytes(6).toString("hex");
const password = randomBytes(24).toString("hex");
const backend = ["compose", "exec", "-T", "backend"];
const timeout = 12000;
const stopLabel = "توقف پاسخ‌های این گفتگو";

function django(code, params = {}) {
  // Send transient test credentials through stdin, outside command line arguments.
  const input =
    "import json\nparams=json.loads(" +
    JSON.stringify(JSON.stringify({ user, ...params })) +
    ")\n" +
    code;
  return execFileSync(
    "docker",
    [
      ...backend,
      "python",
      "manage.py",
      "shell",
      "-c",
      "import sys; exec(sys.stdin.read())",
    ],
    { cwd: root, input, encoding: "utf8", timeout: 20000 },
  );
}

const prepare = `
from django.contrib.auth import get_user_model
from portal.models import ModelConnection, LanguageModel
get_user_model().objects.create_user(params["user"], password=params["password"])
conn = ModelConnection.objects.create(name=params["user"], base_url="http://127.0.0.1:%d/v1" % params["port"], api_key_env="")
for model in ("fast", "slow", "failure"):
    LanguageModel.objects.create(name=params["user"]+" "+model, provider="openai", connection=conn, model_id=model,
        thinking_contract="toggle_effort" if model=="fast" else "effort",
        thinking_levels=["off","low","high","max"] if model=="fast" else ["low","high","max"],
        thinking_default="max", reasoning_policy="store")
`;
const checkAccounting = `
from portal.models import Account, Message
rows = list(Message.objects.filter(conversation__user__username=params["user"], role="assistant").select_related("model","conversation"))
actual = {(m.conversation.title, m.model.model_id): m for m in rows}
assert len(rows) == len(actual) == 5
a, b, c = params["titles"]
for key in [(a, "fast"), (a, "slow"), (c, "fast")]:
    m = actual[key]
    assert (m.status, m.input_tokens, m.output_tokens, m.usage_source) == ("completed", 7, 13, "reported"), key
assert actual[a, "failure"].status == "failed"
assert actual[b, "fast"].status == "cancelled"
assert all(m.reserved_tokens == 0 for m in rows)
account = Account.objects.get(user__username=params["user"])
assert account.tokens_used == sum(m.total_tokens or 0 for m in rows)
for m in rows:
    if m.status == "completed":
        assert m.total_tokens == 20
        assert m.reasoning_tokens == (0 if m.thinking_level=="off" else 6)
    if m.status != "failed" and m.thinking_level != "off":
        assert m.reasoning_content == "TRACE[%s/%s]" % (m.conversation.title, m.model.model_id)
    assert "TRACE" not in m.content
`;
const cleanup = `
from django.contrib.auth import get_user_model
from portal.models import LanguageModel, ModelConnection
get_user_model().objects.filter(username=params["user"]).delete()
LanguageModel.objects.filter(connection__name=params["user"]).delete()
ModelConnection.objects.filter(name=params["user"]).delete()
`;

async function until(check, message) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    if (await check()) return;
    await pause(50);
  }
  throw new Error(message);
}

async function run() {
  const provider = spawn(
    "docker",
    [
      ...backend,
      "python",
      "-u",
      "-c",
      readFileSync(path.join(__dirname, "gated_provider.py"), "utf8"),
    ],
    {
      cwd: root,
      stdio: ["pipe", "pipe", "inherit"],
    },
  );
  const records = [];
  readline
    .createInterface({ input: provider.stdout })
    .on("line", (line) => records.push(JSON.parse(line)));
  const release = (task) => provider.stdin.write(task + "\n");
  const observed = (event, task) =>
    records.some((record) => record.event === event && record.task === task);
  let browser;
  let seeded = false;
  try {
    await until(
      () => records.some((record) => record.event === "ready"),
      "Mock did not start",
    );
    seeded = true;
    django(prepare, { password, port: records[0].port });
    browser = await chromium.launch({
      executablePath: process.env.CHROMIUM_BIN || undefined,
    });
    const page = await browser.newPage();
    page.setDefaultTimeout(timeout);
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await page.goto(base);
    await page.getByLabel("نام کاربری", { exact: true }).fill(user);
    await page.getByLabel("رمز عبور", { exact: true }).fill(password);
    await page.getByRole("button", { name: /ورود به پورتال/ }).click();

    const thread = page.locator(".thread");
    const cards = thread.locator(".message.assistant");
    const stop = page.getByRole("button", { name: stopLabel });
    async function start(title, models, level) {
      await page.getByRole("button", { name: /گفتگوی تازه/ }).click();
      await page
        .getByRole("checkbox", { name: user + " fast", exact: true })
        .waitFor();
      for (const checkbox of await page
        .getByRole("checkbox", { checked: true })
        .all()) {
        await checkbox.uncheck();
      }
      for (const model of models) {
        await page
          .getByRole("checkbox", { name: user + " " + model, exact: true })
          .check();
      }
      for (const model of models) {
        const select = page.getByRole("combobox", {
          name: "شدت استدلال " + user + " " + model,
        });
        if (model !== "fast")
          assert.equal(await select.locator('option[value="off"]').count(), 0);
        await select.selectOption(model === "fast" ? level : "high");
      }
      await page.getByLabel("پیام شما", { exact: true }).fill(title);
      await page
        .getByRole("button", { name: /ارسال پیام|مقایسهٔ پاسخ‌ها/ })
        .click();
      const task = title + "/fast";
      if (level !== "off") {
        const card = cards.filter({
          has: page.getByText(user + " fast", { exact: true }),
        });
        await card.locator("summary").waitFor();
        if (!(await card.locator("details").evaluate((el) => el.open)))
          await card.locator("summary").click();
        await card
          .locator(".reasoning")
          .getByText("TRACE[" + task + "]", { exact: true })
          .waitFor();
        assert.equal(await card.locator(".final-answer").textContent(), "");
        release(task + "/answer");
      }
      await until(
        () =>
          records.some(
            (r) =>
              r.event === "started" && r.task === task && r.level === level,
          ),
        "Wrong upstream thinking selection",
      );
      await thread.getByText(`FIRST[${title}/fast]`, { exact: true }).waitFor();
      assert.equal(await thread.getByText(/LAST\[/).count(), 0);
    }
    async function open(title) {
      await page
        .getByRole("navigation")
        .getByRole("button", { name: new RegExp(title) })
        .click();
      await page.getByRole("heading", { name: title, exact: true }).waitFor();
    }

    const A = "گفتگو الف",
      B = "گفتگو ب",
      C = "گفتگو ج";
    await start(A, ["fast", "slow", "failure"], "low");
    await until(
      () =>
        ["fast", "slow", "failure"].every((model) =>
          observed("started", `${A}/${model}`),
        ),
      "Three providers never ran concurrently",
    );
    await thread.getByText(`FIRST[${A}/slow]`, { exact: true }).waitFor();
    await start(B, ["fast"], "high");
    await start(C, ["fast"], "off");
    assert.equal(records.filter((r) => r.event === "finished").length, 0);
    await open(B);
    await thread.getByText(`FIRST[${B}/fast]`, { exact: true }).waitFor();
    assert.equal(await cards.filter({ hasText: A }).count(), 0);
    assert.equal(await cards.filter({ hasText: C }).count(), 0);
    await stop.click();
    await until(
      () => observed("disconnected", `${B}/fast`),
      "Stop did not close B's upstream HTTP connection",
    );
    await open(A);
    release(`${A}/fast`);
    await cards.filter({ hasText: `LAST[${A}/fast]` }).waitFor();
    assert.equal(await cards.filter({ hasText: `LAST[${A}/slow]` }).count(), 0);
    release(`${A}/failure`);
    await open(C);
    release(`${C}/fast`);
    await cards.filter({ hasText: `LAST[${C}/fast]` }).waitFor();
    assert.equal(await cards.filter({ hasText: A }).count(), 0);
    assert.equal(await cards.filter({ hasText: B }).count(), 0);
    release(`${A}/slow`);
    await open(A);
    await cards.filter({ hasText: `LAST[${A}/slow]` }).waitFor();
    await stop.waitFor({ state: "hidden" });
    // Reload confirms terminal states are durable and not merely DOM state.
    await page.reload();
    await open(A);
    await cards.filter({ hasText: `LAST[${A}/fast]` }).waitFor();
    await cards.filter({ hasText: `LAST[${A}/slow]` }).waitFor();
    const first = cards.filter({ hasText: `LAST[${A}/fast]` });
    await first.locator("summary").click();
    await first
      .locator(".reasoning")
      .getByText(`TRACE[${A}/fast]`, { exact: true })
      .waitFor();
    assert.ok(
      !(await first.locator(".final-answer").textContent()).includes("TRACE"),
    );
    for (const colorScheme of ["dark", "light"]) {
      await page.emulateMedia({ colorScheme });
      await page.setViewportSize({ width: 390, height: 844 });
      await page.locator(`html[data-theme="${colorScheme}"]`).waitFor();
      assert.ok(await first.locator(".reasoning p").isVisible());
      assert.ok(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      );
    }
    await page.setViewportSize({ width: 1280, height: 800 });
    await open(B);
    await cards.filter({ hasText: `FIRST[${B}/fast]` }).waitFor();
    assert.equal(await cards.filter({ hasText: "LAST[" }).count(), 0);
    await open(C);
    await cards.filter({ hasText: `LAST[${C}/fast]` }).waitFor();
    assert.equal(await thread.locator("details.reasoning").count(), 0);
    assert.ok(!records.some((r) => r.event === "timeout"));
    assert.deepEqual(errors, []);
    django(checkAccounting, { titles: [A, B, C] });
    console.log(
      "PASS: separate reasoning deltas, independent effort settings, reload, mobile and themes; streamed three independent chats through Nginx. Stop closed only B upstream. Three comparison models ran concurrently, and two successful replies survived their sibling's HTTP 500 and page reload.",
    );
  } finally {
    try {
      await browser?.close();
    } finally {
      provider.stdin.end();
      if (seeded) django(cleanup);
    }
  }
}

run().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
