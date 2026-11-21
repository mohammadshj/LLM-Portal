import { useState } from "react";
import { ChevronLeft, ChevronRight, Pencil, UserRound } from "lucide-react";
import { MarkdownRenderer } from "./MarkdownRenderer";
import { CopyButton, number } from "./ui";
import type { Message } from "./types";
import type { Revision } from "./useChats";

export type VersionActions = {
  versions: Record<number, number[]>;
  locked: boolean;
  canUseSelection: boolean;
  selectedNames: string;
  save: (revision: Revision) => void;
  select: (anchor: number, target: number) => void;
};

export function UserTurn({
  question,
  replies,
  actions,
  status,
}: {
  question: Message;
  replies: Message[];
  actions: VersionActions;
  status?: string;
}) {
  const [draft, setDraft] = useState<string | null>(null);
  const [changeModels, setChangeModels] = useState(false);
  const versions = actions.versions[question.id] ?? [question.id];
  const index = versions.indexOf(question.id);
  function arrow(label: string, target: number | undefined, older: boolean) {
    return (
      <button
        type="button"
        className="icon"
        title={label}
        aria-label={label}
        disabled={actions.locked || target == null || draft !== null}
        onClick={() => target != null && actions.select(question.id, target)}
      >
        {older ? <ChevronLeft /> : <ChevronRight />}
      </button>
    );
  }
  return (
    <article className="message user" data-status={question.status}>
      <div className="line">
        <strong>
          <UserRound /> شما
        </strong>
        <div className="revision-tools">
          {versions.length > 1 && (
            <span
              className="revision-nav"
              dir="ltr"
              role="group"
              aria-label="نسخه‌های این پیام"
            >
              {arrow("نسخهٔ قدیمی‌تر", versions[index + 1], true)}
              <span>
                {number(index + 1)} / {number(versions.length)}
              </span>
              {arrow("نسخهٔ جدیدتر", versions[index - 1], false)}
            </span>
          )}
          {question.id > 0 && (
            <button
              type="button"
              className="icon"
              title="ویرایش پیام"
              aria-label="ویرایش پیام"
              disabled={actions.locked || draft !== null}
              onClick={() => {
                setDraft(question.content);
                setChangeModels(!replies.length);
              }}
            >
              <Pencil />
            </button>
          )}
          <CopyButton text={question.content} label="کپی پیام" />
        </div>
      </div>
      {draft === null ? (
        <MarkdownRenderer text={question.content} user />
      ) : (
        <form
          className="revision-editor"
          onSubmit={(e) => {
            e.preventDefault();
            if (
              draft.trim() &&
              !actions.locked &&
              (!changeModels || actions.canUseSelection)
            )
              actions.save({ question, replies, content: draft, changeModels });
          }}
        >
          <textarea
            dir="auto"
            autoFocus
            aria-label="متن ویرایش‌شدهٔ پیام"
            maxLength={12000}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            disabled={actions.locked}
          />
          <label>
            <input
              type="checkbox"
              checked={changeModels}
              disabled={actions.locked || !replies.length}
              onChange={(e) => setChangeModels(e.target.checked)}
            />{" "}
            استفاده از مدل‌ها و تنظیمات کادر ارسال
          </label>
          <small>
            {(changeModels
              ? actions.selectedNames
              : replies.map((r) => r.model_name).join("، ")) ||
              "یک مدل در کادر ارسال انتخاب کنید."}
          </small>
          <div>
            <button
              className="primary"
              disabled={
                actions.locked ||
                !draft.trim() ||
                (changeModels && !actions.canUseSelection)
              }
            >
              ذخیره و ارسال
            </button>
            <button
              type="button"
              disabled={actions.locked}
              onClick={() => setDraft(null)}
            >
              انصراف
            </button>
          </div>
        </form>
      )}
      {status && <small>{status}</small>}
    </article>
  );
}
