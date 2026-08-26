"""Backfill `generations.text` for rows written before that column existed.

The text is recovered from `messages` by joining on
(conversation_id, transcript_len == turn_index). That join is NOT reliable on
its own — `messages` is client-managed and re-saving a conversation can shift
indices, measured at ~76% agreement — so a row is only filled when the joined
message matches on BOTH the agent id and the exact word count. Anything else is
left NULL rather than guessed at, because a corpus with silently wrong
attributions is worse than a smaller one.

    python backend/scripts/backfill_generation_text.py [--apply]
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import store  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="write; otherwise dry run")
    args = ap.parse_args()

    store.init_db()
    with store.connect() as conn:
        candidates = conn.execute(
            """
            SELECT g.id, g.agent_id, g.word_count, m.role, m.content
              FROM generations g
              JOIN messages m ON m.conversation_id = g.conversation_id
                             AND m.turn_index = g.transcript_len
             WHERE g.text IS NULL
            """
        ).fetchall()

        verified = [
            r for r in candidates
            if r["agent_id"] == r["role"]
            and r["word_count"] == len(r["content"].split())
        ]
        total_null = conn.execute(
            "SELECT COUNT(*) FROM generations WHERE text IS NULL"
        ).fetchone()[0]

        print(f"rows missing text : {total_null}")
        print(f"joinable          : {len(candidates)}")
        print(f"verified match    : {len(verified)}  <- only these are filled")
        print(f"left NULL         : {total_null - len(verified)}")

        if not args.apply:
            print("\ndry run — pass --apply to write")
            return

        conn.executemany(
            "UPDATE generations SET text = ? WHERE id = ?",
            [(r["content"], r["id"]) for r in verified],
        )
        print(f"\nfilled {len(verified)} rows")


if __name__ == "__main__":
    main()
