import type { Root } from "mdast";
import { unified } from "unified";
import remarkParse from "remark-parse";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import { SKIP, visit } from "unist-util-visit";
import type { VFile } from "vfile";

const parser = unified().use(remarkParse).use(remarkGfm).use(remarkMath);

function convertPairs(text: string) {
  // Consume escaped backslashes as pairs; only a complete matching pair is replaced.
  const tokens = /\\([\\()[\]])/g;
  const pieces: string[] = [];
  let copied = 0;
  let open: { index: number; closer: string; delimiter: string } | undefined;
  for (const match of text.matchAll(tokens)) {
    const symbol = match[1];
    if (open && symbol === open.closer) {
      pieces.push(
        text.slice(copied, open.index),
        open.delimiter,
        text.slice(open.index + 2, match.index),
        open.delimiter,
      );
      copied = match.index + 2;
      open = undefined;
    } else if (symbol === "(" || symbol === "[") {
      open = {
        index: match.index,
        closer: symbol === "(" ? ")" : "]",
        delimiter: symbol === "(" ? "$" : "$$",
      };
    }
  }
  return pieces.length ? pieces.join("") + text.slice(copied) : text;
}

export function normalizeMath(source: string) {
  if (!source.includes("\\(") && !source.includes("\\[")) return source;
  // Let CommonMark identify literal spans (including arbitrary fence lengths,
  // indentation, container blocks and multi-backtick code) before touching delimiters.
  let cursor = 0;
  const parts: string[] = [];
  visit(parser.parse(source), (node) => {
    if (
      ![
        "code",
        "inlineCode",
        "html",
        "link",
        "image",
        "definition",
        "math",
        "inlineMath",
      ].includes(node.type)
    )
      return;
    const from = node.position?.start.offset,
      to = node.position?.end.offset;
    if (from == null || to == null) return;
    parts.push(
      convertPairs(source.slice(cursor, from)),
      source.slice(from, to),
    );
    cursor = to;
    return SKIP;
  });
  return parts.join("") + convertPairs(source.slice(cursor));
}

export function mathPresentation() {
  return (tree: Root, file: VFile) => {
    const source = String(file);
    visit(tree, (node, index, parent) => {
      if (node.type === "code" && node.lang === "math") {
        // rehype-katex also recognizes a math-labelled code fence by default.
        node.data = {
          ...node.data,
          hProperties: { className: [], dataLiteralLanguage: "math" },
        };
        return;
      }
      if (node.type !== "math" && node.type !== "inlineMath") return;
      const raw = source.slice(
        node.position?.start.offset,
        node.position?.end.offset,
      );
      const fence = /^\$+/.exec(raw)?.[0] ?? "$$";
      const closed =
        node.type === "inlineMath" ||
        (raw.includes("\n") &&
          /^\$+$/.test(
            raw
              .split("\n")
              .at(-1)!
              .replace(/^([\s>])*/, "")
              .trimEnd(),
          ) &&
          raw.trimEnd().endsWith(fence));
      if ((!closed || node.value.length > 16384) && parent && index != null) {
        parent.children[index] = { type: "text", value: raw };
      } else if (
        node.type === "inlineMath" &&
        raw.startsWith("$$") &&
        node.data
      ) {
        node.data.hProperties = { className: ["math-display"] };
      }
    });
  };
}
