"use client";

import { relativeTime, type Conversation } from "@/app/lib/history";

/**
 * Local conversation history. Most-recent-first, hover to reveal delete.
 * Above 720px it collapses to zero width in place; below that it becomes an
 * overlay driven by `mobileOpen`, with a scrim rendered by the page.
 */
export default function Sidebar({
  conversations,
  error,
  currentId,
  collapsed,
  mobileOpen,
  onSelect,
  onDelete,
  onNew,
}: {
  conversations: Conversation[];
  /** Set when the history could not be loaded at all. */
  error?: string | null;
  currentId: string | null;
  collapsed: boolean;
  mobileOpen: boolean;
  onSelect: (c: Conversation) => void;
  onDelete: (id: string) => void;
  onNew: () => void;
}) {
  return (
    <aside
      className={`sidebar${collapsed ? " collapsed" : ""}${mobileOpen ? " mobile-open" : ""}`}
      aria-label="Conversation history"
      /* Collapsed means width 0 with overflow hidden, so the panel is invisible
         but its buttons stayed in the tab order — aria-hidden alone produced
         the classic trap where tabbing lands you on a control you cannot see
         and a screen reader refuses to name. `inert` removes the whole subtree
         from focus and from the a11y tree together; React 19 takes it as a
         boolean prop. Keep both: aria-hidden for assistive tech on the older
         path, inert for focus. */
      aria-hidden={collapsed && !mobileOpen}
      inert={collapsed && !mobileOpen}
    >
      <div className="sidebar-inner">
        <div className="sidebar-head">
          <span className="sidebar-title">conversations</span>
          <button
            type="button"
            className="new-chat"
            onClick={onNew}
            aria-label="Start a new conversation"
          >
            <svg
              width="15"
              height="15"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.2"
              strokeLinecap="round"
              aria-hidden="true"
            >
              <path d="M12 5v14M5 12h14" />
            </svg>
          </button>
        </div>

        {error ? (
          <p className="sidebar-empty">{error}</p>
        ) : conversations.length === 0 ? (
          <p className="sidebar-empty">
            no conversations yet — ask something to begin.
          </p>
        ) : (
          <ul className="history">
            {conversations.map((c) => (
              <li key={c.id}>
                <div
                  className={`history-item${c.id === currentId ? " current" : ""}`}
                >
                  <button
                    type="button"
                    className="history-open"
                    onClick={() => onSelect(c)}
                  >
                    <span className="history-title">{c.title}</span>
                    <span className="history-time">
                      {relativeTime(c.updatedAt)}
                    </span>
                  </button>
                  <button
                    type="button"
                    className="history-delete"
                    onClick={() => onDelete(c.id)}
                    aria-label={`Delete conversation: ${c.title}`}
                  >
                    <svg
                      width="14"
                      height="14"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2"
                      strokeLinecap="round"
                      aria-hidden="true"
                    >
                      <path d="M4 7h16M10 11v6M14 11v6" />
                      <path d="M6 7l1 13h10l1-13M9 7V4h6v3" />
                    </svg>
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </aside>
  );
}
