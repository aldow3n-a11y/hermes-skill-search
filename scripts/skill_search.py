#!/usr/bin/env python3
"""skill_search.py — semantic skill lookup CLI (standalone).

Query the skill index built by skill_indexer.py. Returns top-N skills
ranked by cosine similarity. Useful for testing the index without Hermes.

Usage:
    python skill_search.py "plan a feature safely" [--top 3] [--json]

Configuration (env vars, all optional):
    OLLAMA_URL        default http://127.0.0.1:11434
    SKILL_EMBED_MODEL default all-minilm:l6-v2
    SKILL_INDEX_DB    default <hermes-home>/skill_index.db
"""

import argparse
import json
import math
import os
import sqlite3
import sys
import time
from pathlib import Path

import requests

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
EMBED_MODEL = os.environ.get("SKILL_EMBED_MODEL", "all-minilm:l6-v2")
_HERMES_HOME = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))
INDEX_DB = Path(os.environ.get(
    "SKILL_INDEX_DB",
    str(_HERMES_HOME / "skill_index.db"),
))


def embed_text(text: str) -> list[float]:
    r = requests.post(
        f"{OLLAMA_URL}/api/embeddings",
        json={"model": EMBED_MODEL, "prompt": text, "keep_alive": -1},
        timeout=60,
    )
    r.raise_for_status()
    return r.json()["embedding"]


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def search(query: str, top: int = 3) -> list[dict]:
    conn = sqlite3.connect(str(INDEX_DB))
    rows = conn.execute(
        "SELECT name, path, description, embedding FROM skills"
    ).fetchall()
    conn.close()

    if not rows:
        return []

    qv = embed_text(query)
    scored = []
    for name, path, desc, emb_json in rows:
        ev = json.loads(emb_json)
        scored.append((cosine(qv, ev), name, path, desc))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [
        {"name": n, "path": p, "description": d, "score": round(s, 4)}
        for s, n, p, d in scored[:top]
    ]


def main():
    ap = argparse.ArgumentParser(description="Semantic skill search")
    ap.add_argument("query", help="what you need a skill for")
    ap.add_argument("--top", type=int, default=3)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    t0 = time.time()
    results = search(args.query, args.top)
    dt = time.time() - t0

    if args.json:
        print(json.dumps({"query": args.query, "elapsed_ms": round(dt * 1000),
                          "results": results}, indent=2))
        return 0

    print(f"query: {args.query} ({dt*1000:.0f}ms)")
    for r in results:
        print(f"  {r['score']:.3f}  {r['name']}")
        print(f"        {r['description'][:100]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
