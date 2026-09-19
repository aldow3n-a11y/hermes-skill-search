#!/usr/bin/env python3
"""One-copy install check for skill-search. Run after editing the plugin, the indexer, or the pools.

Asserts: installed plugin == repo plugin, superseded copies stay retired, the plugin's own
repair hint points at a file that exists, and the index is not behind the pool on disk.
"""
import hashlib, os, re, sqlite3, sys
from pathlib import Path

HOME = Path.home(); APPDATA = HOME / "AppData/Local/hermes"
REPO = HOME / "hermes-skill-search"
INST = APPDATA / "plugins/skill-search"
DB = Path(os.environ.get("SKILL_INDEX_DB", str(APPDATA / "skill_index.db")))
h = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
fails = []

for rel in ("__init__.py", "plugin.yaml"):
    if not (INST / rel).exists():
        fails.append(f"installed plugin missing {rel}")
    elif h(INST / rel) != h(REPO / "plugin" / rel):
        fails.append(f"{rel}: installed != repo (reinstall: copy hermes-skill-search/plugin/* -> plugins/skill-search/)")

for dead in (HOME / "graymatter/scripts/skill_indexer.py", HOME / "graymatter/scripts/skill_search.py",
             HOME / "AppData/Local/hermes/skills/system/skill-search/scripts/duplicate_indexer.py"):
    if dead.exists():
        fails.append(f"superseded duplicate is back: {dead}")

for m in re.finditer(r"python\s+(\S*\.py)", (INST / "__init__.py").read_text(encoding="utf-8")):
    p = Path(m.group(1).strip("\"'"))
    if not p.exists():
        fails.append(f"plugin hint points at a missing file: {p}")

sys.path.insert(0, str(REPO / "scripts"))
import skill_indexer as si
found = len(si.discover_skills())
rows = sqlite3.connect(str(DB)).execute("SELECT COUNT(*) FROM skills").fetchone()[0]
if si.SKILL_ROOTS and "AppData" not in str(si.SKILL_ROOTS[0]):
    fails.append(f"first skill root must be the active AppData pool (first-root-wins): {si.SKILL_ROOTS[0]}")

if not DB.exists():
    fails.append(f"index db missing: {DB}")
elif rows < found:
    fails.append(f"index stale: {rows} rows < {found} skills on disk (run {REPO}/scripts/skill_indexer.py)")

print(f"plugin={h(INST / '__init__.py')[:12]} db={DB.name} rows={rows} on-disk={found}")
print("roots:", [str(r) for r in si.SKILL_ROOTS])
if fails:
    print("\nFAIL:"); [print("  -", f) for f in fails]; sys.exit(1)
print("OK  one plugin, one indexer, no stale copies")
