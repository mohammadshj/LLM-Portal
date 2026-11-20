import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import type { Conversation, Page } from "./types";

export function useHistory() {
  const [query, setQuery] = useState("");
  const [items, setItems] = useState<Conversation[]>([]);
  const [next, setNext] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [paging, setPaging] = useState(false);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  const read = useRef<AbortController | null>(null);
  const pageLock = useRef(false);
  function refresh() {
    read.current?.abort();
    setRevision((v) => v + 1);
  }
  useEffect(() => {
    const controller = new AbortController();
    read.current = controller;
    pageLock.current = false;
    setPaging(false);
    setLoading(true);
    setNext(null);
    setError("");
    const timer = setTimeout(
      async () => {
        try {
          const page = await api<Page>(
            "conversations/?q=" + encodeURIComponent(query.trim()),
            "GET",
            undefined,
            controller.signal,
          );
          if (!controller.signal.aborted) {
            setItems(page.results);
            setNext(page.next);
          }
        } catch (e) {
          if (!controller.signal.aborted) {
            setItems([]);
            setError((e as Error).message);
          }
        } finally {
          if (!controller.signal.aborted) setLoading(false);
        }
      },
      query ? 180 : 0,
    );
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [query, revision]);
  async function more() {
    const controller = read.current;
    if (!next || pageLock.current || !controller || controller.signal.aborted)
      return;
    pageLock.current = true;
    setPaging(true);
    try {
      const path = "conversations/" + new URL(next, location.href).search;
      const page = await api<Page>(path, "GET", undefined, controller.signal);
      if (!controller.signal.aborted) {
        setItems((old) => [
          ...old,
          ...page.results.filter((c) => !old.some((i) => i.id === c.id)),
        ]);
        setNext(page.next);
        setError("");
      }
    } catch (e) {
      if (!controller.signal.aborted) setError((e as Error).message);
    } finally {
      if (!controller.signal.aborted) {
        pageLock.current = false;
        setPaging(false);
      }
    }
  }
  return {
    query,
    setQuery,
    items,
    next,
    paging,
    loading,
    error,
    refresh,
    more,
  };
}
