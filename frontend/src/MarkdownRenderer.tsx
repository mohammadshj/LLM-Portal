import { memo, useMemo, type ReactNode } from "react";
import Markdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import Prism from "prismjs";
import "prismjs/components/prism-python";
import "prismjs/components/prism-sql";
import "prismjs/components/prism-typescript";
import "prismjs/components/prism-json";
import "prismjs/components/prism-bash";
import { CopyButton } from "./ui";

function tokenNodes(tokens: Prism.TokenStream): ReactNode {
  if (typeof tokens === "string") return tokens;
  if (Array.isArray(tokens))
    return tokens.map((token, index) =>
      typeof token === "string" ? (
        token
      ) : (
        <span className={"token " + token.type} key={index}>
          {tokenNodes(token.content)}
        </span>
      ),
    );
  return (
    <span className={"token " + tokens.type}>{tokenNodes(tokens.content)}</span>
  );
}
function CodeBlock({ text, language }: { text: string; language: string }) {
  const highlighted = useMemo(() => {
    const grammar = Object.hasOwn(Prism.languages, language)
      ? Prism.languages[language]
      : null;
    return grammar && typeof grammar === "object" && text.length <= 24000
      ? tokenNodes(Prism.tokenize(text, grammar))
      : text;
  }, [text, language]);
  return (
    <div className="code-block">
      <div className="code-bar">
        <bdi>{language || "کد"}</bdi>
        <CopyButton text={text} label="کپی کد" />
      </div>
      <pre dir="ltr">
        <code>{highlighted}</code>
      </pre>
    </div>
  );
}
const components: Components = {
  pre({ node }) {
    const code = node?.children.find(
      (child) => child.type === "element" && child.tagName === "code",
    );
    if (!code || code.type !== "element") return null;
    const classes = code.properties.className;
    const lang = Array.isArray(classes)
      ? classes
          .map(String)
          .find((c) => c.startsWith("language-"))
          ?.slice(9)
      : "";
    const text = code.children
      .map((child) => (child.type === "text" ? child.value : ""))
      .join("")
      .replace(/\n$/, "");
    return <CodeBlock text={text} language={lang || ""} />;
  },
  table({ children }) {
    return (
      <div className="table-scroll">
        <table>{children}</table>
      </div>
    );
  },
  a({ href, children }) {
    return href && /^(https?:\/\/|mailto:)/i.test(href) ? (
      <a href={href} target="_blank" rel="noopener noreferrer nofollow">
        {children}
      </a>
    ) : (
      <span>{children}</span>
    );
  },
  img({ alt }) {
    return alt ? <span>{alt}</span> : null;
  },
  p({ children }) {
    return <p dir="auto">{children}</p>;
  },
};
const plugins = [remarkGfm];
export const MarkdownRenderer = memo(function MarkdownRenderer({
  text,
}: {
  text: string;
}) {
  return (
    <div className="markdown final-answer" dir="auto">
      <Markdown skipHtml remarkPlugins={plugins} components={components}>
        {text}
      </Markdown>
    </div>
  );
});
