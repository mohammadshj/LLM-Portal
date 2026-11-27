import test from "node:test";
import assert from "node:assert/strict";
import { applyCredit, money, priced } from "../src/credit.ts";
test("an earlier SSE settlement or delayed REST read cannot replace newer available credit", () => {
  const after = { credit_version: 5, credit_available_rial: 4982600 };
  assert.equal(
    applyCredit(after, { credit_version: 4, credit_available_rial: 5000000 }),
    after,
  );
  assert.equal(
    applyCredit(after, { credit_version: 6, credit_available_rial: 23000 })
      .credit_available_rial,
    23000,
  );
});
test("Persian toman preserves fractions of one toman and distinguishes missing prices", () => {
  assert.equal(money(1), "۰٫۱ تومان");
  assert.equal(money(4982600), "۴۹۸٬۲۶۰ تومان");
  assert.equal(
    priced({
      input_price_per_million_rial: null,
      output_price_per_million_rial: 0,
    }),
    false,
  );
  assert.equal(
    priced({
      input_price_per_million_rial: 0,
      output_price_per_million_rial: 0,
    }),
    true,
  );
});
