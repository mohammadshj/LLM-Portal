import assert from "node:assert/strict";
import test from "node:test";
import { composeMessages } from "../src/composeMessages.ts";

const question = (id, request_id, content) => ({
  role: "user",
  id,
  request_id,
  content,
});
const reply = (id, parent_id, model_id, status, content) => ({
  role: "assistant",
  id,
  parent_id,
  model_id,
  status,
  content,
});

const savedQuestion = question(10, "request", "سؤال");
const temporaryQuestion = question(-1, "request", "سؤال");
const fast = reply(-2, undefined, 1, "running", "پاسخ جزئی");
const slow = reply(-3, undefined, 2, "running", "هنوز در حال پاسخ");
const live = {
  id: "request",
  messages: [temporaryQuestion, fast, slow],
  stopping: false,
};
const final = {
  ...reply(11, 10, 1, "completed", "پاسخ کامل"),
  reasoning_content: "استدلال ثبت‌شده",
};
const running = {
  ...reply(12, 10, 2, "running", ""),
  elapsed_ms: 300,
  elapsedSampleAt: 700,
};

test("a settled model takes its server row while its sibling keeps streaming", () => {
  const stored = [savedQuestion, final, running];
  assert.deepEqual(composeMessages({ stored, live, streaming: true }), [
    temporaryQuestion,
    final,
    slow,
  ]);
});

test("reloading after disconnect replaces partial replies without duplicating the turn", () => {
  const history = [
    question(2, "earlier", "پیشین"),
    reply(3, 2, 1, "completed", "پاسخ قبلی"),
  ];
  const stored = [...history, savedQuestion, final, running];
  const polled = composeMessages({ stored, live, streaming: false });
  assert.deepEqual(polled, [
    ...history,
    temporaryQuestion,
    final,
    { ...slow, elapsed_ms: 300, elapsedSampleAt: 700 },
  ]);
  assert.equal(
    composeMessages({
      stored,
      live,
      streaming: false,
      readError: "قطع ارتباط",
    }).at(-1).elapsed_ms,
    null,
  );

  const finished = [
    ...history,
    savedQuestion,
    final,
    { ...running, status: "completed", content: "پاسخ دوم" },
  ];
  // useChats drops the live turn when the detail API reports no active request.
  assert.deepEqual(
    composeMessages({ stored: finished, streaming: false }),
    finished,
  );
});

test("editing an earlier turn switches only the suffix after server acknowledgement", () => {
  const prefix = [
    question(1, "first", "ابتدا"),
    reply(2, 1, 1, "completed", "اول"),
  ];
  const original = question(3, "old", "نسخه پیشین");
  const stored = [
    ...prefix,
    original,
    reply(4, 3, 1, "completed", "قدیم"),
    question(5, "later", "ادامه"),
  ];
  const edit = { ...live, editOf: original.id };
  assert.deepEqual(
    composeMessages({ stored, live: edit, streaming: true }),
    stored,
  );
  assert.deepEqual(
    composeMessages({
      stored,
      live: { ...edit, confirmed: true },
      streaming: true,
    }),
    [...prefix, ...edit.messages],
  );
});
