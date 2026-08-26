// Conversation history for the sidebar.
//
// Backed by the Python service (backend/app/store.py), not localStorage: the
// transcripts are also the corpus the divergence analytics read, and a corpus
// trapped in one browser profile is no corpus at all.
//
// Still purely a presentation concern from the UI's side — it stores and reads
// back transcripts the app has already produced, and never touches how a turn
// is taken or what an agent is asked.

import type { ChatMessage } from "@/app/lib/agents";

/** A sidebar row. Carries no transcript — the list never renders one. */
export interface Conversation {
  id: string;
  title: string;
  /** Epoch ms of the last write to this conversation. */
  updatedAt: number;
  messageCount?: number;
}

export interface ConversationDetail extends Conversation {
  transcript: ChatMessage[];
}

export function makeId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `c-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

/** Carries the status so callers can distinguish "gone" from "service down". */
export class HttpError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "HttpError";
  }
}

async function json<T>(res: Response): Promise<T> {
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    throw new HttpError(data?.error ?? "Request failed", res.status);
  }
  return data as T;
}

export async function listConversations(): Promise<Conversation[]> {
  return json<Conversation[]>(
    await fetch("/api/conversations", { cache: "no-store" }),
  );
}

export async function fetchConversation(id: string): Promise<ConversationDetail> {
  return json<ConversationDetail>(
    await fetch(`/api/conversations/${encodeURIComponent(id)}`, {
      cache: "no-store",
    }),
  );
}

/** Upsert. Called every time the transcript grows, so it must stay idempotent. */
export async function saveConversation(
  id: string,
  title: string,
  transcript: ChatMessage[],
): Promise<Conversation> {
  return json<Conversation>(
    await fetch(`/api/conversations/${encodeURIComponent(id)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title, transcript }),
    }),
  );
}

export async function removeConversation(id: string): Promise<void> {
  await fetch(`/api/conversations/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
}

/** First thing the user asked, trimmed to something that fits a sidebar row. */
export function titleFor(transcript: ChatMessage[]): string {
  const first = transcript.find((m) => m.role === "user") ?? transcript[0];
  const text = (first?.content ?? "untitled").replace(/\s+/g, " ").trim();
  return text.length > 64 ? `${text.slice(0, 63)}…` : text;
}

/** "just now" · "12m" · "5h" · "3d" · "14 Feb" */
export function relativeTime(ts: number, now: number = Date.now()): string {
  const diff = Math.max(0, now - ts);
  const min = Math.floor(diff / 60000);
  if (min < 1) return "just now";
  if (min < 60) return `${min}m`;
  const hrs = Math.floor(min / 60);
  if (hrs < 24) return `${hrs}h`;
  const days = Math.floor(hrs / 24);
  if (days < 7) return `${days}d`;
  return new Date(ts).toLocaleDateString(undefined, {
    day: "numeric",
    month: "short",
  });
}
