import { useMemo } from "react";
import Markdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";
import { mathPresentation, normalizeMath } from "./mathMarkdown";
import type { PluggableList } from "unified";
const plugins = [remarkGfm, remarkMath, mathPresentation];
const mathPlugins: PluggableList = [
  [
    rehypeKatex,
    {
      trust: false,
      strict: "error",
      maxSize: 12,
      maxExpand: 500,
      output: "htmlAndMathml",
    },
  ],
];
export default function MathMarkdownView({
  text,
  components,
}: {
  text: string;
  components: Components;
}) {
  const markdown = useMemo(() => normalizeMath(text), [text]);
  return (
    <Markdown
      skipHtml
      remarkPlugins={plugins}
      rehypePlugins={mathPlugins}
      components={components}
    >
      {markdown}
    </Markdown>
  );
}
