import type { Detail } from "./types";

// Only the authenticated active branch returned by the conversation API is exported.
export function downloadChat(chat: Detail) {
  const content = [
    "# " + chat.title,
    ...chat.messages.map(
      (m) =>
        "## " +
        (m.role === "user" ? "شما" : m.model_name || "پاسخ مدل") +
        "\n\n" +
        m.content,
    ),
  ].join("\n\n");
  const url = URL.createObjectURL(
    new Blob([content], { type: "text/markdown;charset=utf-8" }),
  );
  const link = document.createElement("a");
  link.href = url;
  link.download =
    (chat.title.replace(/[^\p{L}\p{N} -]+/gu, "").trim() || "گفتگو") + ".md";
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
