#!/usr/bin/env python3
"""skill_search.py — semantic skill lookup CLI for the Hermes skill index.

Searches skill_index.db (built by skill_indexer.py) by intent. Supports
keyword search, listing, exact name lookup, category filter, and index reload.

Usage:
    python skill_search.py "video"                  # search by keyword
    python skill_search.py --list                   # list all skills
    python skill_search.py --name "graymatter-sdk"  # exact name lookup
    python skill_search.py --category "devops"      # filter by category
    python skill_search.py --reload                 # rebuild index

Config (env vars, optional):
    OLLAMA_URL        default http://127.0.0.1:11434
    SKILL_EMBED_MODEL default all-minilm:l6-v2
    SKILL_INDEX_DB    default <hermes-home>/skill_index.db
"""

import argparse
import json
import math
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
EMBED_MODEL = os.environ.get("SKILL_EMBED_MODEL", "all-minilm:l6-v2")
_INDEX_DB = os.environ.get(
    "SKILL_INDEX_DB",
    str(Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes"))) / "skill_index.db"),
)
INDEX_DB = Path(_INDEX_DB)

# Path to the indexer (reload needs it)
_HERE = Path(__file__).resolve().parent
_INDEXER_CANDIDATES = [
    Path("C:/Users/MnM26/hermes-skill-search/scripts/skill_indexer.py"),
    _HERE / "skill_indexer.py",
    Path.home() / "hermes-skill-search" / "scripts" / "skill_indexer.py",
]


def embed_text(text: str) -> list[float]:
    import requests
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


def _connect() -> sqlite3.Connection:
    if not INDEX_DB.exists():
        sys.exit(f"skill index not found: {INDEX_DB}\n  run: python skill_search.py --reload")
    return sqlite3.connect(str(INDEX_DB))


def search_keyword(query: str, top: int) -> int:
    conn = _connect()
    rows = conn.execute(
        "SELECT name, path, description, embedding FROM skills"
    ).fetchall()
    conn.close()
    if not rows:
        sys.exit("skill index is empty\n  run: python skill_search.py --reload")

    qv = embed_text(query)
    scored = []
    for name, path, desc, emb_json in rows:
        ev = json.loads(emb_json)
        scored.append((cosine(qv, ev), name, path, desc))
    scored.sort(key=lambda x: x[0], reverse=True)

    print(f"query: {query}  |  {len(rows)} indexed")
    for s, n, p, d in scored[:top]:
        print(f"  {s:.3f}  {n}")
        print(f"        {d[:110]}")
    return 0


def list_all() -> int:
    conn = _connect()
    rows = conn.execute(
        "SELECT name, path FROM skills ORDER BY name"
    ).fetchall()
    conn.close()
    print(f"{len(rows)} skills\n")
    for name, path in rows:
        print(f"  {name}")
        print(f"      {path}")
    return 0


def by_name(name: str) -> int:
    conn = _connect()
    row = conn.execute(
        "SELECT name, path, description FROM skills WHERE name=?", (name,)
    ).fetchone()
    conn.close()
    if not row:
        print(f"no skill named '{name}'")
        return 1
    n, p, d = row
    print(f"{n}\n  path: {p}\n  desc: {d}")
    return 0


def by_category(category: str) -> int:
    conn = _connect()
    rows = conn.execute(
        "SELECT name, path, description FROM skills ORDER BY name"
    ).fetchall()
    conn.close()
    marker = category.lower()
    hits = []
    for n, p, d in rows:
        if marker in p.lower() or marker in n.lower() or marker in d.lower():
            hits.append((n, p, d))
    print(f"{len(hits)} skills matching '{category}'\n")
    for n, p, d in hits:
        print(f"  {n}")
        print(f"      {p}")
    return 0


def reload_index() -> int:
    for cand in _INDEXER_CANDIDATES:
        if cand.exists():
            print(f"rebuilding index via: {cand}")
            return subprocess.call([sys.executable, str(cand), "--force"])
    sys.exit(f"skill_indexer.py not found in {[str(c) for c in _INDEXER_CANDIDATES]}")
    return 1  # unreachable


def main() -> int:
    ap = argparse.ArgumentParser(description="Semantic skill search (Hermes)")
    ap.add_argument("query", nargs="?", help="what you need a skill for")
    ap.add_argument("--list", action="store_true", help="list all skills")
    ap.add_argument("--name", metavar="NAME", help="exact skill name lookup")
    ap.add_argument("--category", metavar="CAT", help="filter by category (substring)")
    ap.add_argument("--reload", action="store_true", help="rebuild the skill index")
    ap.add_argument("--top", type=int, default=3, help="results for keyword search (default 3)")
    args = ap.parse_args()

    if args.reload:
        return reload_index()
    if args.name:
        return by_name(args.name)
    if args.category:
        return by_category(args.category)
    if args.list:
        return list_all()
    if args.query:
        return search_keyword(args.query, args.top)

    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
