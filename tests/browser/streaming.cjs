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
        thinking_contract={"fast":"toggle_effort","slow":"effort","failure":"budget_tokens"}[model],
        thinking_levels=["off","low","high","max"] if model=="fast" else (["brief","deep"] if model=="failure" else ["low","high","max"]),
        thinking_budgets={"brief":64,"deep":256} if model=="failure" else {},
        thinking_default="brief" if model=="failure" else "max", reasoning_policy="store")
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
assert all(m.response_duration_ms is not None for m in rows)
assert all(m.reserved_tokens == 0 for m in rows)
account = Account.objects.get(user__username=params["user"])
assert account.tokens_used == sum(m.total_tokens or 0 for m in rows)
for m in rows:
    if m.status == "completed":
        assert m.total_tokens == 20
        assert m.reasoning_tokens == (0 if m.reasoning_settings.get("toggle") is False else 6)
    if m.status != "failed" and m.reasoning_settings.get("toggle") is not False:
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

async function until(check, message, waitMs = timeout, intervalMs = 50) {
  const deadline = Date.now() + waitMs;
  while (Date.now() < deadline) {
    if (await check()) return;
    await pause(intervalMs);
  }
  throw new Error(message);
}

async function run() {
  await until(
    async () => {
      try {
        const response = await fetch(base + "/api/health/", {
          signal: AbortSignal.timeout(2000),
        });
        return response.ok;
      } catch {
        return false;
      }
    },
    "Nginx and Django did not become ready",
    60000,
    500,
  );
  const provider = spawn(
    "docker",
    [
      ...backend,
      "python",
      "-u",
      "-c",
      readFileSync(path.join(__dirname, "gated_provider.py"), "utf8"),
      user,
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
    const page = await browser.newPage({
      viewport: { width: 1440, height: 900 },
      permissions: ["clipboard-read", "clipboard-write"],
    });
    page.setDefaultTimeout(timeout);
    const errors = [];
    page.on("console", (m) => {
      if (
        m.type() === "error" &&
        !(
          m.text().includes("403 (Forbidden)") &&
          new URL(m.location().url || base).pathname === "/api/auth/me/"
        )
      )
        errors.push(m.text());
    });
    page.on("pageerror", (e) => errors.push(e.message));
    await page.goto(base);
    await page.getByLabel("نام کاربری", { exact: true }).fill(user);
    await page.getByLabel("رمز عبور", { exact: true }).fill(password);
    await page.getByRole("button", { name: /ورود به پورتال/ }).click();

    const thread = page.locator(".thread");
    const cards = thread.locator(".message.assistant");
    const stop = page.getByRole("button", { name: stopLabel });
    const capture = async (name) => {
      if (process.env.PORTAL_SCREENSHOTS)
        await page.screenshot({
          path: path.join(process.env.PORTAL_SCREENSHOTS, name + ".png"),
        });
    };
    await page.locator(".hero").waitFor();
    await page.evaluate(() => document.fonts.ready);
    await capture("workspace");
    await page.getByRole("button", { name: /بازنویسی متن/ }).click();
    assert.ok(
      (await page.locator("#prompt").inputValue()).includes("بازنویسی"),
    );
    await page.getByRole("button", { name: "جمع کردن نوار گفتگوها" }).click();
    await page.getByRole("button", { name: "باز کردن نوار گفتگوها" }).click();
    async function start(title, models, level) {
      await page.getByRole("button", { name: /گفتگوی تازه/ }).click();
      await page
        .getByRole("button", { name: "انتخاب مدل", exact: true })
        .click();
      await page
        .getByRole("checkbox", { name: user + " fast", exact: true })
        .waitFor();
      for (const checkbox of await page
        .getByRole("checkbox", { checked: true })
        .all()) {
        await checkbox.uncheck();
      }
      const filter = page.getByRole("textbox", { name: "جست‌وجوی مدل" });
      await filter.fill(user);
      assert.equal(await page.getByRole("checkbox").count(), 3);
      await filter.fill("");
      for (const model of models) {
        await page
          .getByRole("checkbox", { name: user + " " + model, exact: true })
          .check();
      }
      if (models.length === 3)
        assert.ok(
          await page
            .getByRole("checkbox", { checked: false })
            .evaluateAll((els) => els.every((el) => el.disabled)),
        );
      await page.getByText("تنظیمات استدلال", { exact: true }).click();
      for (const model of models) {
        if (model === "failure") {
          await page
            .getByRole("combobox", {
              name: "بودجهٔ استدلال " + user + " failure",
            })
            .selectOption("256");
          continue;
        }
        if (model === "fast") {
          const toggle = page.getByRole("switch", {
            name: "فعال‌سازی استدلال " + user + " fast",
          });
          await toggle.setChecked(level !== "off");
          if (level === "off") continue;
        }
        const select = page.getByRole("combobox", {
          name: "شدت استدلال " + user + " " + model,
        });
        if (model !== "fast")
          assert.equal(await select.locator('option[value="off"]').count(), 0);
        await select.selectOption(model === "fast" ? level : "high");
      }
      await page.getByRole("button", { name: "انجام شد" }).click();
      await page.getByLabel("پیام شما", { exact: true }).fill(title);
      if (level === "off") {
        const prompt = page.locator("#prompt");
        await prompt.press("Shift+Enter");
        assert.ok((await prompt.inputValue()).includes("\n"));
        await prompt.fill(title);
        await prompt.dispatchEvent("keydown", {
          key: "Enter",
          isComposing: true,
        });
        assert.equal(await stop.count(), 0);
        await prompt.press("Enter");
      } else
        await page
          .getByRole("button", { name: /ارسال پیام|مقایسهٔ پاسخ‌ها/ })
          .click();
      const task = title + "/fast";
      if (level !== "off") {
        const card = cards.filter({
          has: page.getByText(user + " fast", { exact: true }),
        });
        await card.locator(".reasoning summary").waitFor();
        if (!(await card.locator(".reasoning").evaluate((el) => el.open)))
          await card.locator(".reasoning summary").click();
        await card
          .locator(".reasoning")
          .getByText("TRACE[" + task + "]", { exact: true })
          .waitFor();
        assert.equal(
          await card.locator(".final-answer").count(),
          1,
          "Duplicate response card",
        );
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
        .getByRole("button", { name: title, exact: true })
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
    assert.ok(
      records.some((r) => r.task === A + "/failure" && r.budget === 256),
    );
    assert.ok(
      records.some((r) => r.task === A + "/slow" && r.level === "high"),
    );
    await thread.getByText(`FIRST[${A}/slow]`, { exact: true }).waitFor();
    const fastClock = cards
      .filter({ hasText: `FIRST[${A}/fast]` })
      .locator("time");
    const slowClock = cards
      .filter({ hasText: `FIRST[${A}/slow]` })
      .locator("time");
    const initial = await slowClock.getAttribute("datetime");
    await until(
      async () => (await slowClock.getAttribute("datetime")) !== initial,
      "The timer did not advance while waiting for more tokens",
    );
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
    await cards
      .filter({ hasText: `LAST[${A}/fast]` })
      .and(page.locator('[data-status="completed"]'))
      .waitFor();
    const fastFinal = await fastClock.getAttribute("datetime");
    const stillRunning = await slowClock.getAttribute("datetime");
    await until(
      async () => (await slowClock.getAttribute("datetime")) !== stillRunning,
      "The slower model clock stopped when its sibling completed",
    );
    assert.equal(await fastClock.getAttribute("datetime"), fastFinal);
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
    assert.equal(await fastClock.getAttribute("datetime"), fastFinal);
    const slowFinal = await slowClock.getAttribute("datetime");
    const asSeconds = (duration) => Number(duration.slice(2, -1));
    assert.ok(asSeconds(slowFinal) > asSeconds(fastFinal));
    const first = cards.filter({ hasText: `LAST[${A}/fast]` });
    await first.locator(".reasoning summary").click();
    await first
      .locator(".reasoning")
      .getByText(`TRACE[${A}/fast]`, { exact: true })
      .waitFor();
    assert.ok(
      !(await first.locator(".final-answer").textContent()).includes("TRACE"),
    );
    for (const colorScheme of ["dark", "light"]) {
      await page.emulateMedia({ colorScheme });
      for (const width of [320, 390, 640, 768, 1024, 1440]) {
        await page.setViewportSize({ width, height: 844 });
        await page.locator(`html[data-theme="${colorScheme}"]`).waitFor();
        assert.ok(await first.locator(".reasoning p").isVisible());
        assert.ok(
          await page.evaluate(
            () => document.documentElement.scrollWidth <= innerWidth,
          ),
          "overflow " + width,
        );
        if (width === 320) {
          await page.getByRole("button", { name: "باز کردن گفتگوها" }).click();
          await page.getByRole("dialog").waitFor();
          await page.keyboard.press("Escape");
          assert.equal(
            await page.evaluate(() =>
              document.activeElement.getAttribute("aria-label"),
            ),
            "باز کردن گفتگوها",
          );
          const tabs = page.getByRole("group", {
            name: "انتخاب پاسخ برای مطالعه",
          });
          await tabs.getByRole("button", { name: user + " slow" }).click();
          assert.equal(
            await cards.filter({ hasText: `LAST[${A}/fast]` }).isVisible(),
            false,
          );
          await tabs.getByRole("button", { name: user + " fast" }).click();
          await capture("mobile-" + colorScheme);
        }
      }
    }
    await page.setViewportSize({ width: 1280, height: 800 });
    await open(B);
    await cards.filter({ hasText: `FIRST[${B}/fast]` }).waitFor();
    assert.equal(await cards.filter({ hasText: "LAST[" }).count(), 0);
    await cards.getByRole("button", { name: "آماده‌سازی ارسال مجدد" }).click();
    assert.equal(await page.locator("#prompt").inputValue(), B);
    await open(C);
    await cards.filter({ hasText: `LAST[${C}/fast]` }).waitFor();
    assert.equal(await thread.locator("details.reasoning").count(), 0);
    assert.ok(!records.some((r) => r.event === "timeout"));
    assert.deepEqual(errors, []);
    django(checkAccounting, { titles: [A, B, C] });
    // Fork an earlier three-model turn. Look at a different branch after a refresh.
    await open(A);
    const questions = thread.locator("article.user");
    const continuation = "ادامهٔ نسخهٔ اصلی";
    await page.locator("#prompt").fill(continuation);
    await page.locator("#prompt").press("Enter");
    for (const suffix of ["fast/answer", "fast", "slow", "failure"])
      release(continuation + "/" + suffix);
    await questions.filter({ hasText: continuation }).waitFor();
    await stop.waitFor({ state: "hidden" });
    const editQuestion = questions
      .first()
      .getByRole("button", { name: "ویرایش پیام" });
    await editQuestion.click();
    const editor = page.getByRole("textbox", { name: "متن ویرایش‌شدهٔ پیام" });
    assert.equal(await editor.inputValue(), A);
    await editor.fill("متن انصراف");
    await questions.first().getByRole("button", { name: "انصراف" }).click();
    await editQuestion.click();
    assert.equal(await editor.inputValue(), A);
    const revised = String.raw`ویرایش ریاضی با \(E=mc^2\)`;
    await editor.fill(revised);
    await page.getByRole("button", { name: "ذخیره و ارسال" }).click();
    await until(
      () =>
        ["fast", "slow", "failure"].every((m) =>
          observed("started", revised + "/" + m),
        ),
      "Edited message did not inherit all models",
    );
    assert.ok(
      records.some((r) => r.task === revised + "/fast" && r.level === "low"),
    );
    release(revised + "/fast/answer");
    const editedCard = cards.filter({ hasText: user + " fast" });
    await editedCard
      .locator(".final-answer")
      .getByText(/frac/)
      .first()
      .waitFor();
    assert.equal(await questions.count(), 1);
    await questions.first().locator(".katex").waitFor();
    for (const m of ["fast", "slow", "failure"]) release(revised + "/" + m);
    await stop.waitFor({ state: "hidden" });
    await editedCard.locator(".katex-display").first().waitFor();
    assert.equal(
      await editedCard
        .locator(".katex-display annotation")
        .first()
        .textContent(),
      String.raw`\frac{a}{b}`,
    );
    assert.equal(
      await editedCard.locator(".final-answer code").textContent(),
      String.raw`\(literal\)`,
    );
    await page.setViewportSize({ width: 320, height: 844 });
    for (const colorScheme of ["dark", "light"]) {
      await page.emulateMedia({ colorScheme });
      await page.locator(`html[data-theme="${colorScheme}"]`).waitFor();
      assert.equal(
        await questions
          .first()
          .locator(".markdown p")
          .first()
          .evaluate((el) => getComputedStyle(el).direction),
        "rtl",
      );
      const longMath = editedCard.locator(".katex-display").last();
      assert.ok(
        await longMath.evaluate(
          (el) =>
            getComputedStyle(el).direction === "ltr" &&
            el.scrollWidth > el.clientWidth &&
            getComputedStyle(el).overflowX === "auto",
        ),
      );
      assert.ok(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      );
    }
    await page.setViewportSize({ width: 1280, height: 800 });
    await questions.first().getByText("۱ / ۲", { exact: true }).waitFor();
    assert.ok(
      await questions
        .first()
        .getByRole("button", { name: "نسخهٔ جدیدتر" })
        .isDisabled(),
    );
    const callsBeforeBrowse = records.filter(
      (r) => r.event === "started",
    ).length;
    await questions
      .first()
      .getByRole("button", { name: "نسخهٔ قدیمی‌تر" })
      .click();
    await questions.filter({ hasText: continuation }).waitFor();
    await questions.first().getByText("۲ / ۲", { exact: true }).waitFor();
    await page.reload();
    await open(A);
    await questions.filter({ hasText: continuation }).waitFor();
    await questions
      .first()
      .getByRole("button", { name: "نسخهٔ جدیدتر" })
      .click();
    await questions.first().locator(".katex").waitFor();
    assert.equal(await questions.count(), 1);
    assert.equal(await cards.count(), 3);
    assert.equal(
      records.filter((r) => r.event === "started").length,
      callsBeforeBrowse,
    );
    const D = "مقایسه Markdown";
    await start(D, ["fast", "slow"], "off");
    release(D + "/fast");
    release(D + "/slow");
    await stop.waitFor({ state: "hidden" });
    const rich = cards.filter({ hasText: user + " fast" });
    await rich.locator("table").waitFor();
    assert.equal(await cards.count(), 2);
    assert.equal(await rich.locator("pre").getAttribute("dir"), "ltr");
    assert.ok((await rich.locator("pre .token.keyword").count()) > 0);
    assert.equal(await rich.locator("a").count(), 1);
    assert.equal(await rich.locator("img,script,iframe,mark").count(), 0);
    await rich.getByRole("button", { name: "کپی کد" }).click();
    assert.equal(
      await page.evaluate(() => navigator.clipboard.readText()),
      "def hello(): return 1",
    );
    await capture("comparison");
    await rich.getByRole("button", { name: "گسترش پاسخ" }).click();
    await page.getByRole("dialog").locator("table").waitFor();
    await page.keyboard.press("Escape");
    const usage = rich.locator(".usage");
    await usage.locator("summary").click();
    assert.ok((await usage.innerText()).includes("۲۰ (گزارش سرویس)"));
    await page
      .getByRole("button", { name: "مدیریت گفتگو " + D, exact: true })
      .click();
    await page.getByLabel("عنوان گفتگو").fill("بازبینی متن");
    await page.getByRole("button", { name: "ذخیرهٔ عنوان" }).click();
    await page
      .getByRole("heading", { name: "بازبینی متن", exact: true })
      .waitFor();
    const search = page.getByRole("searchbox", { name: "جست‌وجوی گفتگوها" });
    await search.fill("بازبینی");
    await until(
      async () => (await page.locator(".history-link").count()) === 1,
      "Search results",
    );
    await page
      .getByRole("button", { name: "مدیریت گفتگو بازبینی متن" })
      .click();
    await page.getByRole("button", { name: "حذف گفتگو", exact: true }).click();
    await page.getByRole("button", { name: "تأیید حذف" }).click();
    await page.getByText("گفتگویی با این عنوان پیدا نشد.").waitFor();
    const E = "مطالعهٔ پاسخ طولانی";
    await start(E, ["fast"], "off");
    release(E + "/fast/body");
    await thread.getByText("بند پایانی", { exact: true }).waitFor();
    await thread.locator("pre").getByText("live", { exact: true }).waitFor();
    await thread.evaluate((el) => {
      el.scrollTop = 0;
    });
    await page.getByRole("button", { name: "آخرین پیام" }).waitFor();
    release(E + "/fast");
    await stop.waitFor({ state: "hidden" });
    assert.ok(
      await thread.evaluate((el) => el.scrollTop < 30),
      "Streaming interrupted reading position",
    );
    await page.getByRole("button", { name: "آخرین پیام" }).click();
    await until(
      async () =>
        await thread.evaluate(
          (el) => el.scrollHeight - el.clientHeight - el.scrollTop < 75,
        ),
      "Jump to last message",
    );
    const touch = await browser.newContext({
      isMobile: true,
      hasTouch: true,
      viewport: { width: 390, height: 844 },
      storageState: await page.context().storageState(),
    });
    try {
      const phone = await touch.newPage();
      phone.on("pageerror", (e) => errors.push(e.message));
      await phone.goto(base);
      const draft = phone.getByLabel("پیام شما", { exact: true });
      await draft.fill("خط اول");
      await draft.press("Enter");
      assert.equal(await draft.inputValue(), "خط اول\n");
      await phone
        .getByRole("button", { name: "انتخاب مدل", exact: true })
        .tap();
      await phone
        .getByRole("dialog")
        .getByRole("textbox", { name: "جست‌وجوی مدل" })
        .fill(user);
      assert.equal(await phone.getByRole("checkbox").count(), 3);
      await phone.getByRole("button", { name: "انجام شد" }).tap();
      await phone.getByRole("button", { name: "باز کردن گفتگوها" }).tap();
      await phone.getByRole("button", { name: A, exact: true }).tap();
      await phone
        .getByRole("group", { name: "انتخاب پاسخ برای مطالعه" })
        .getByRole("button", { name: user + " failure" })
        .tap();
      assert.ok(
        await phone.locator(".assistant[data-status=failed]").isVisible(),
      );
      assert.ok(
        await phone.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      );
    } finally {
      await touch.close();
    }
    // Exercise discovery against the same controlled HTTP server. Only this fixture's
    // exact loopback origin is authorized in the short-lived management process.
    django(`
from django.test import override_settings
from portal.discovery import sync_models
from portal.models import ModelConnection
conn = ModelConnection.objects.get(name=params["user"])
with override_settings(DISCOVERY_LOCAL_ORIGINS={conn.base_url.removesuffix("/v1")}):
    assert sync_models(conn.pk)["added"] == 5
assert conn.models.filter(auto_thinking=True, enabled=True).count() == 0
conn.models.filter(auto_thinking=True).update(enabled=True)
`);
    await page.reload();
    await page.getByRole("button", { name: "انتخاب مدل", exact: true }).click();
    for (const checkbox of await page
      .getByRole("checkbox", { checked: true })
      .all())
      await checkbox.uncheck();
    const unknown = page.getByRole("checkbox", {
      name: user + " unknown",
      exact: true,
    });
    await unknown.check();
    assert.equal(await page.getByRole("combobox").count(), 0);
    await unknown.uncheck();
    const fixed = page.getByRole("checkbox", {
      name: user + " fixed",
      exact: true,
    });
    const toggle = page.getByRole("checkbox", {
      name: user + " toggle",
      exact: true,
    });
    await fixed.check();
    await toggle.check();
    await page.getByText("تنظیمات استدلال", { exact: true }).click();
    await page.getByText("استدلال برای این مدل اجباری است.").waitFor();
    const range = page.getByRole("checkbox", {
      name: user + " range",
      exact: true,
    });
    await range.check();
    const slider = page.getByRole("slider", {
      name: "بودجهٔ استدلال " + user + " range",
    });
    await slider.focus();
    await slider.press("End");
    assert.equal(
      await page
        .getByRole("spinbutton", {
          name: "تعداد توکن استدلال " + user + " range",
        })
        .inputValue(),
      "256",
    );
    await range.uncheck();
    const switcher = page.getByRole("switch", {
      name: "فعال‌سازی استدلال " + user + " toggle",
    });
    await switcher.check();
    await page.getByText("تنظیمات استدلال", { exact: true }).click();
    await fixed.uncheck();
    await toggle.uncheck();
    await page
      .getByRole("checkbox", { name: user + " catalog", exact: true })
      .check();
    await page.getByText("تنظیمات استدلال", { exact: true }).click();
    const effort = page.getByRole("combobox", {
      name: "شدت استدلال " + user + " catalog",
    });
    assert.deepEqual(
      await effort
        .locator("option")
        .evaluateAll((nodes) => nodes.map((el) => el.value)),
      ["", "minimal", "medium", "xhigh"],
    );
    await effort.selectOption("xhigh");
    await page.getByRole("button", { name: "انجام شد" }).click();
    const title = "مدل کشف‌شده";
    await page.locator("#prompt").fill(title);
    await page.locator("#prompt").press("Enter");
    await until(
      () =>
        records.some(
          (r) => r.task === title + "/catalog" && r.level === "xhigh",
        ),
      "Discovered effort missing from provider payload",
    );
    release(title + "/catalog");
    await cards.filter({ hasText: "LAST[" + title + "/catalog]" }).waitFor();
    await stop.waitFor({ state: "hidden" });
    assert.deepEqual(errors, []);
    console.log(
      "PASS: separate reasoning deltas, independent effort settings, reload, mobile and themes; streamed three independent chats through Nginx. Stop closed only B upstream. Three comparison models ran concurrently; synchronized catalog efforts reached the provider through the live selector. Edited and restored a three-model branch without extra provider calls; verified streamed math, literal code and RTL mobile layout in both themes.",
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
