#!/usr/bin/env python3
"""skill_indexer.py — build a semantic skill index for Hermes Agent.

Walks Hermes skill directories (native + OMH managed + any extra roots),
parses SKILL.md frontmatter, embeds each skill's name+description with a
lightweight local embedding model (default: all-minilm:l6-v2 via Ollama,
~45MB, CPU-friendly), and stores {name, path, description, embedding} in
a SQLite table for cosine search.

Usage:
    python skill_indexer.py              # incremental (only new/changed)
    python skill_indexer.py --force      # rebuild everything
    python skill_indexer.py --stats      # show index stats

Configuration (env vars, all optional):
    OLLAMA_URL            default http://127.0.0.1:11434
    SKILL_EMBED_MODEL     default all-minilm:l6-v2
    SKILL_INDEX_DB        default <hermes-home>/skill_index.db
    HERMES_SKILLS_DIR    default <hermes-home>/skills
    OMH_SKILLS_DIR        default ~/.omh/skills
    OMH_FULL_SKILLS_DIR   optional: full OMH catalog checkout (e.g. a clone
                          of rlaope/oh-my-hermes) to index all 106 skills
    EXTRA_SKILL_ROOTS     optional ';'-separated additional skill dirs
"""

import argparse
import json
import os
import re
import sqlite3
import sys
import time
from pathlib import Path

import requests

# ─── Config ────────────────────────────────────────────────────────────────

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
EMBED_MODEL = os.environ.get("SKILL_EMBED_MODEL", "all-minilm:l6-v2")
_HERMES_HOME = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))
INDEX_DB = Path(os.environ.get(
    "SKILL_INDEX_DB",
    str(_HERMES_HOME / "skill_index.db"),
))

# Skill roots: native Hermes skills + OMH managed skills + optional extras
SKILL_ROOTS = [
    Path(os.environ.get("HERMES_SKILLS_DIR", str(_HERMES_HOME / "skills"))),
    Path(os.environ.get("OMH_SKILLS_DIR", str(Path.home() / ".omh" / "skills"))),
]
_full = os.environ.get("OMH_FULL_SKILLS_DIR")
if _full:
    SKILL_ROOTS.append(Path(_full))
for extra in os.environ.get("EXTRA_SKILL_ROOTS", "").split(";"):
    if extra.strip():
        SKILL_ROOTS.append(Path(extra.strip()))

# ─── Frontmatter parsing ────────────────────────────────────────────────────

def parse_frontmatter(content: str) -> dict:
    """Extract YAML-ish frontmatter (name, description) from SKILL.md."""
    m = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
    if not m:
        return {}
    fm = {}
    for line in m.group(1).splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            k, _, v = line.partition(":")
            fm[k.strip()] = v.strip().strip('"').strip("'")
    return fm


def discover_skills() -> list[dict]:
    """Walk skill roots, return [{name, path, description}]."""
    skills = []
    seen = set()
    for root in SKILL_ROOTS:
        if not root.exists():
            continue
        for sk in sorted(root.rglob("SKILL.md")):
            try:
                content = sk.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            fm = parse_frontmatter(content)
            name = fm.get("name") or sk.parent.name
            if name in seen:
                continue
            seen.add(name)
            desc = fm.get("description", "")
            # Fallback: first non-frontmatter heading or first paragraph
            if not desc:
                body = re.sub(r"^---\s*\n.*?\n---\s*\n", "", content, flags=re.DOTALL)
                m = re.search(r"^#\s+(.+)$", body, re.MULTILINE)
                desc = m.group(1) if m else body[:200]
            skills.append({
                "name": name,
                "path": str(sk),
                "description": desc,
            })
    return skills


# ─── Embedding ─────────────────────────────────────────────────────────────

def embed_text(text: str) -> list[float]:
    """Embed via Ollama. Keeps model warm with keep_alive=-1."""
    r = requests.post(
        f"{OLLAMA_URL}/api/embeddings",
        json={"model": EMBED_MODEL, "prompt": text, "keep_alive": -1},
        timeout=60,
    )
    r.raise_for_status()
    return r.json()["embedding"]


# ─── Index DB ─────────────────────────────────────────────────────────────

def get_db() -> sqlite3.Connection:
    INDEX_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(INDEX_DB))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS skills (
            name        TEXT PRIMARY KEY,
            path        TEXT NOT NULL,
            description TEXT NOT NULL,
            embedding   BLOB NOT NULL,
            dims        INTEGER NOT NULL,
            indexed_at  TEXT NOT NULL
        )
    """)
    conn.commit()
    return conn


def main():
    ap = argparse.ArgumentParser(description="Build semantic skill index")
    ap.add_argument("--force", action="store_true", help="rebuild all")
    ap.add_argument("--stats", action="store_true", help="show stats only")
    args = ap.parse_args()

    conn = get_db()

    if args.stats:
        n = conn.execute("SELECT COUNT(*) FROM skills").fetchone()[0]
        print(f"indexed skills: {n}")
        print(f"model: {EMBED_MODEL}")
        print(f"db: {INDEX_DB}")
        return 0

    skills = discover_skills()
    print(f"discovered {len(skills)} skills")

    if args.force:
        conn.execute("DELETE FROM skills")
        conn.commit()
        print("index cleared (--force)")

    existing = {r[0] for r in conn.execute("SELECT name FROM skills")}
    todo = [s for s in skills if args.force or s["name"] not in existing]
    print(f"to index: {len(todo)} (skipping {len(skills) - len(todo)} cached)")

    t0 = time.time()
    for i, s in enumerate(todo, 1):
        text = f"{s['name']}: {s['description']}"
        try:
            emb = embed_text(text)
        except Exception as e:
            print(f"  ✗ {s['name']}: {e}")
            continue
        conn.execute(
            "INSERT OR REPLACE INTO skills (name, path, description, embedding, dims, indexed_at) VALUES (?,?,?,?,?,?)",
            (s["name"], s["path"], s["description"],
             json.dumps(emb), len(emb),
             time.strftime("%Y-%m-%dT%H:%M:%SZ")),
        )
        conn.commit()
        if i % 10 == 0 or i == len(todo):
            print(f"  {i}/{len(todo)} ({time.time()-t0:.0f}s)")

    n = conn.execute("SELECT COUNT(*) FROM skills").fetchone()[0]
    print(f"\ndone: {n} skills indexed in {time.time()-t0:.0f}s")
    print(f"db size: {INDEX_DB.stat().st_size/1024:.0f} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
