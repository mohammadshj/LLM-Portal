import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { Check, Copy, Layers3, X } from "lucide-react";

export const number = (value: number) => value.toLocaleString("fa-IR");
export const thinkingNames: Record<string, string> = {
  off: "خاموش",
  on: "روشن",
  low: "کم",
  high: "زیاد",
  max: "بیشینه",
};

export function Brand() {
  return (
    <div className="brand" dir="ltr">
      <span className="brand-mark">
        <Layers3 size={24} />
      </span>
      <strong>
        LLM <span>Portal</span>
      </strong>
    </div>
  );
}

export function Dialog({
  title,
  onClose,
  children,
  drawer = false,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  drawer?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const label = useId();
  useEffect(() => {
    const dialog = ref.current!;
    const opener = document.activeElement;
    dialog.showModal();
    return () => {
      dialog.close();
      if (opener instanceof HTMLElement && opener.isConnected) opener.focus();
    };
  }, []);
  return (
    <dialog
      ref={ref}
      aria-labelledby={label}
      className={drawer ? "drawer" : "modal"}
      onCancel={(e) => {
        e.preventDefault();
        onClose();
      }}
      onClick={(e) => {
        if (e.target === ref.current) {
          const r = ref.current.getBoundingClientRect();
          if (
            e.clientX < r.left ||
            e.clientX > r.right ||
            e.clientY < r.top ||
            e.clientY > r.bottom
          )
            onClose();
        }
      }}
    >
      <div className="modal-head">
        <h2 id={label}>{title}</h2>
        <button
          className="icon"
          aria-label="بستن"
          title="بستن"
          onClick={onClose}
        >
          <X />
        </button>
      </div>
      {children}
    </dialog>
  );
}

export function CopyButton({ text, label }: { text: string; label: string }) {
  const [feedback, setFeedback] = useState("");
  useEffect(() => {
    if (!feedback) return;
    const timer = setTimeout(() => setFeedback(""), 2200);
    return () => clearTimeout(timer);
  }, [feedback]);
  async function copy() {
    try {
      if (navigator.clipboard?.writeText)
        await navigator.clipboard.writeText(text);
      else {
        const input = document.createElement("textarea");
        input.value = text;
        input.className = "sr-only";
        (document.querySelector("dialog[open]") ?? document.body).append(input);
        const before = document.activeElement;
        input.select();
        const ok = document.execCommand("copy");
        input.remove();
        if (before instanceof HTMLElement) before.focus();
        if (!ok) throw new Error();
      }
      setFeedback("کپی شد");
    } catch {
      setFeedback("کپی ممکن نشد");
    }
  }
  return (
    <span className="copy-action">
      <button className="icon" title={label} aria-label={label} onClick={copy}>
        {feedback === "کپی شد" ? <Check /> : <Copy />}
      </button>
      {feedback && <small role="status">{feedback}</small>}
    </span>
  );
}

export function useMedia(query: string) {
  const [matches, setMatches] = useState(() => matchMedia(query).matches);
  useEffect(() => {
    const media = matchMedia(query);
    const change = () => setMatches(media.matches);
    change();
    media.addEventListener("change", change);
    return () => media.removeEventListener("change", change);
  }, [query]);
  return matches;
}
