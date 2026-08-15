# hermes-skill-search

[![Landing page](https://img.shields.io/badge/landing%20page-live-2ea44f)](https://aldow3n-a11y.github.io/hermes-skill-search/)

Semantic skill discovery for [Hermes Agent](https://hermes-agent.nousresearch.com/): find the right skill by **intent**, not exact name, using a tiny local embedding model. The full skill catalog (native + OMH) becomes discoverable without loading it into context.

> 🎨 **Animated landing page:** https://aldow3n-a11y.github.io/hermes-skill-search/

## Why

Hermes builds an eager `<available_skills>` index into every system prompt — every skill name + description, paid as tokens on every API call. With a large catalog (200+ skills) that's ~8-12k tokens of dead weight per session.

This plugin flips discovery on demand:

```
agent needs a skill, doesn't know the name
        ↓
skill_search("plan a feature safely")     ← 1 tool call, ~130ms
        ↓
top-3 matches: omh-plan (0.44), spike (0.39), ...
        ↓
skill_view("omh-plan")                    ← load only what's needed
```

The index is built once with a **45MB** embedding model (`all-minilm:l6-v2`) that runs on any old CPU. No GPU, no big model, no new services — just Ollama (already running for most Hermes setups) and a 2.5MB SQLite file.

## What it does

- **`skill_search` tool** — semantic search over the skill index, returns top-N with scores, paths, descriptions
- **`pre_llm_call` hook** — injects a compact 240-char pointer so every session knows to reach for `skill_search`
- **`skill_indexer.py`** — one-shot: walks skill dirs, parses SKILL.md frontmatter, embeds, stores in SQLite
- **`skill_search.py`** — standalone CLI for testing the index without Hermes

## Install

### Prerequisites

- Hermes Agent
- [Ollama](https://ollama.com/) running locally
- Python 3.10+

### 1. Pull the embedding model

```bash
ollama pull all-minilm:l6-v2   # 45MB, CPU-friendly
```

### 2. Install the plugin

```bash
# clone
git clone https://github.com/<you>/hermes-skill-search.git
cd hermes-skill-search

# copy plugin into Hermes plugins dir
mkdir -p ~/.hermes/plugins/skill-search
cp plugin/__init__.py plugin/plugin.yaml ~/.hermes/plugins/skill-search/

# enable it
hermes plugins enable skill-search
```

### 3. Build the index

```bash
# index native skills + OMH managed skills
python scripts/skill_indexer.py

# optionally include the full OMH catalog (106 skills) from a clone:
#   OMH_FULL_SKILLS_DIR=~/oh-my-hermes/skills python scripts/skill_indexer.py --force
```

### 4. Restart Hermes

```bash
hermes gateway restart
```

Verify: `hermes plugins list` shows `skill-search` enabled, and the `[Skill discovery]` pointer appears in sessions.

## Usage

Ask Hermes something like *"find a skill for reviewing a PR"* — it will call `skill_search`, pick the best match, and load it with `skill_view`.

Or test the index directly:

```bash
python scripts/skill_search.py "plan a feature safely"
# query: plan a feature safely (130ms)
#   0.438  omh-plan
#   0.390  spike
#   0.367  competitive-landscape-check
```

## Configuration

All optional, via env vars:

| Var | Default | Purpose |
|---|---|---|
| `OLLAMA_URL` | `http://127.0.0.1:11434` | Ollama endpoint |
| `SKILL_EMBED_MODEL` | `all-minilm:l6-v2` | Embedding model (any Ollama embed model works) |
| `SKILL_INDEX_DB` | `<hermes-home>/skill_index.db` | Index location |
| `HERMES_SKILLS_DIR` | `<hermes-home>/skills` | Native skills root |
| `OMH_SKILLS_DIR` | `~/.omh/skills` | OMH managed skills root |
| `OMH_FULL_SKILLS_DIR` | unset | Full OMH catalog checkout (optional) |
| `EXTRA_SKILL_ROOTS` | unset | `;`-separated extra skill dirs |

## Model choice

Benchmarked on skill-retrieval tasks (5 easy + 4 hard queries):

| Model | Size | Dims | Easy | Hard | Verdict |
|---|---|---|---|---|---|
| **all-minilm:l6-v2** | 45MB | 384 | 5/5 | 3/4 | ✅ chosen |
| granite-embedding:30m | 62MB | 384 | 5/5 | 3/4 | tie, larger |
| snowflake-arctic-embed:22m | 45MB | 384 | 5/5 | 2/4 | weak discrimination |
| nomic-embed-text | 274MB | 768 | — | — | overkill for 200 short texts |
| bge-m3 | 1.2GB | 1024 | — | — | sledgehammer |

`all-minilm:l6-v2` wins on size + discrimination. Any Ollama embed model can be swapped via `SKILL_EMBED_MODEL`.

## License

MIT
