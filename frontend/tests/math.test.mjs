import assert from "node:assert/strict";
import test from "node:test";
import { unified } from "unified";
import remarkParse from "remark-parse";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import remarkRehype from "remark-rehype";
import rehypeKatex from "rehype-katex";
import { visit } from "unist-util-visit";
import { normalizeMath, mathPresentation } from "../src/mathMarkdown.ts";

const parser = unified()
  .use(remarkParse)
  .use(remarkGfm)
  .use(remarkMath)
  .use(mathPresentation)
  .use(remarkRehype)
  .use(rehypeKatex, { trust: false, maxExpand: 500, maxSize: 12 });
function elements(input) {
  const source = normalizeMath(input);
  const tree = parser.runSync(parser.parse(source), source);
  const nodes = [];
  visit(tree, "element", (n) => {
    nodes.push(n);
  });
  return nodes;
}
const withClass = (nodes, name) =>
  nodes.filter((n) => n.properties.className?.includes(name));

test("inline, display and matrix notation retain direction-independent TeX", () => {
  const source = String.raw`فارسی $E=mc^2$ و \(\alpha_i^2\)

$$\int_0^\infty e^{-x^2}dx=\frac{\sqrt{\pi}}{2}$$

\[
\begin{bmatrix}a&b\\c&d\end{bmatrix}
\]

$$
\sum_{i=1}^n x_i
$$`;
  const nodes = elements(source);
  assert.equal(withClass(nodes, "katex").length, 5);
  assert.equal(withClass(nodes, "katex-display").length, 3);
  assert.equal(withClass(nodes, "katex-error").length, 0);
});
test("code, labelled math fences, links, indented code and escaped delimiters remain literal", () => {
  const source = [
    "`\\(x\\)`",
    "`` ` $a$ ` ``",
    "~~~math",
    "\\[y\\] $c$",
    "~~~",
    "",
    "    \\(indented\\)",
    "",
    String.raw`\\(escaped\\) and \\$escaped and [link](https://example.org/a)`,
  ].join("\n");
  assert.equal(normalizeMath(source), source);
  assert.equal(withClass(elements(source), "katex").length, 0);
});
test("unfinished streaming equations stay text and complete on the closing chunk", () => {
  for (const [start, end] of [
    ["$a^", "2$"],
    ["$$\na^2", "\n$$"],
    [String.raw`\(\frac{1}`, String.raw`{2}\)`],
  ]) {
    assert.equal(withClass(elements(start), "katex").length, 0);
    assert.equal(withClass(elements(start + end), "katex").length, 1);
  }
  const blocked = elements(
    String.raw`$\includegraphics{https://example.org/image}$`,
  );
  assert.equal(blocked.filter((n) => n.tagName === "img").length, 0);
});
