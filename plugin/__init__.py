"""skill_search — semantic skill discovery tool for Hermes Agent.

Registers a `skill_search` tool that queries a local skill index
(skill_index.db, built by scripts/skill_indexer.py) using a lightweight
local embedding model (default: all-minilm:l6-v2 via Ollama, ~45MB,
CPU-friendly). Lets the agent find the right skill by intent instead of
exact name — the full OMH catalog is discoverable without loading it
into context.

Also injects a compact persistent pointer (pre_llm_call hook) so every
session knows to reach for skill_search when a task might match a skill.

Index lifecycle:
  - Build/refresh: python scripts/skill_indexer.py [--force]
  - The tool returns a clear error if the index is missing or stale.

Configuration (all optional, env vars):
  OLLAMA_URL            default http://127.0.0.1:11434
  SKILL_EMBED_MODEL     default all-minilm:l6-v2
  SKILL_INDEX_DB        default <hermes-home>/skill_index.db
  SKILL_ROOTS           optional ';'-separated extra skill dirs to index
"""

from __future__ import annotations

import json
import math
import os
import sqlite3
import time
from pathlib import Path

import requests

_TOOLSET = "skill_search"

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
EMBED_MODEL = os.environ.get("SKILL_EMBED_MODEL", "all-minilm:l6-v2")
_HERMES_HOME = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))
INDEX_DB = Path(os.environ.get(
    "SKILL_INDEX_DB",
    str(_HERMES_HOME / "skill_index.db"),
))

# Compact persistent pointer injected into every LLM call. Kept short —
# the whole point is saving context, not adding to it.
SKILL_SEARCH_POINTER = (
    "[Skill discovery] When a task might match a skill but you don't know the "
    "exact name, call skill_search(query) — it finds the right skill by intent "
    "across the full catalog (native + OMH). Then load the match with "
    "skill_view(name)."
)

SKILL_SEARCH_SCHEMA = {
    "name": "skill_search",
    "description": (
        "Semantic skill discovery: find the right Hermes skill for a task by intent, "
        "not exact name. Use when you need a skill but aren't sure which one, or when "
        "a task might match a skill you haven't seen. Returns top-N skills with "
        "relevance scores, paths, and descriptions. Then load the chosen skill with "
        "skill_view(name)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "What you need a skill for, in natural language (e.g. 'plan a feature safely', 'review this PR for bugs').",
            },
            "top": {
                "type": "integer",
                "description": "Number of results to return (default 3, max 5).",
            },
        },
        "required": ["query"],
    },
}


def _embed(text: str) -> list[float]:
    r = requests.post(
        f"{OLLAMA_URL}/api/embeddings",
        json={"model": EMBED_MODEL, "prompt": text, "keep_alive": -1},
        timeout=60,
    )
    r.raise_for_status()
    return r.json()["embedding"]


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def skill_search_handler(args: dict, **kwargs) -> str:
    query = (args.get("query") or "").strip()
    if not query:
        return json.dumps({"error": "query is required"})
    top = min(int(args.get("top", 3)), 5)

    if not INDEX_DB.exists():
        return json.dumps({
            "error": "skill index not found",
            "hint": "run: python scripts/skill_indexer.py",
        })

    t0 = time.time()
    try:
        conn = sqlite3.connect(str(INDEX_DB))
        rows = conn.execute(
            "SELECT name, path, description, embedding FROM skills"
        ).fetchall()
        conn.close()
    except sqlite3.Error as e:
        return json.dumps({"error": f"index read failed: {e}"})

    if not rows:
        return json.dumps({
            "error": "skill index is empty",
            "hint": "run: python scripts/skill_indexer.py",
        })

    try:
        qv = _embed(query)
    except Exception as e:
        return json.dumps({
            "error": f"embedding failed: {e}",
            "hint": "is Ollama running? (ollama serve)",
        })

    scored = []
    for name, path, desc, emb_json in rows:
        try:
            ev = json.loads(emb_json)
        except (json.JSONDecodeError, TypeError):
            continue
        scored.append((_cosine(qv, ev), name, path, desc))
    scored.sort(key=lambda x: x[0], reverse=True)

    results = [
        {"name": n, "path": p, "description": d[:200], "score": round(s, 4)}
        for s, n, p, d in scored[:top]
    ]
    return json.dumps({
        "query": query,
        "elapsed_ms": round((time.time() - t0) * 1000),
        "results": results,
    }, indent=2)


def pre_llm_call(**kwargs) -> dict[str, object] | None:
    """Inject the compact skill-search pointer into every LLM call."""
    return {"context": SKILL_SEARCH_POINTER}


def register(ctx):
    """Register the skill_search tool and its pointer hook with Hermes."""
    ctx.register_tool(
        "skill_search",
        _TOOLSET,
        SKILL_SEARCH_SCHEMA,
        skill_search_handler,
        description=SKILL_SEARCH_SCHEMA["description"],
    )
    ctx.register_hook("pre_llm_call", pre_llm_call)
