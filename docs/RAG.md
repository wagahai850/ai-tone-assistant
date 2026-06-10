# RAG: Retrieval-Augmented Generation for Wiki Knowledge

## Overview

Optional RAG layer that augments the `fm9_lookup_model_info` and `fm9_lookup_block_info` tools with semantically relevant content from the Fractal Audio Wiki. Embedding-based vector search finds related knowledge chunks even when no keyword match exists.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│ Fractal Audio Wiki (113 pages, full site)                │
└──────────────────┬──────────────────────────────────────┘
                   │ MediaWiki API → pandoc → markdown
                   │ chunk (800 chars, 100 overlap)
                   │ embed (all-MiniLM-L6-v2, local)
                   ▼
┌─────────────────────────────────────────────────────────┐
│ ChromaDB (local, persistent)                             │
│ 12,406 chunks │ cosine similarity │ data/rag_db/         │
└──────────────────┬──────────────────────────────────────┘
                   │
                   │ query_knowledge(query, block_type, top_k)
                   ▼
┌─────────────────────────────────────────────────────────┐
│ MCP Tool Response                                        │
│ {                                                        │
│   "models": [...],          ← keyword match (always)     │
│   "rag_context": [...],     ← semantic search (if ON)    │
│   "rag_enabled": true       ← A/B identification flag    │
│ }                                                        │
└─────────────────────────────────────────────────────────┘
```

## Usage

### Enable RAG

```json
{
  "mcpServers": {
    "fm9-tone-assistant": {
      "command": "python3",
      "args": ["path/to/server.py", "--device", "fm9"],
      "env": { "TONE_ASSISTANT_RAG": "on" }
    }
  }
}
```

### Disable RAG (default)

Omit the `env` block or set `"TONE_ASSISTANT_RAG": "off"`.

### Build the Index

First-time setup (requires `pandoc` installed):

```bash
pip install chromadb sentence-transformers
python3 pipeline/build_rag_index.py --fetch
```

Rebuild after firmware updates or to refresh wiki content:

```bash
python3 pipeline/build_rag_index.py --fetch  # re-download all pages
```

### Verify

```bash
python3 pipeline/build_rag_index.py --stats
python3 pipeline/build_rag_index.py --test "Plexi crunch tone"
```

## How It Works

1. **Existing keyword match always runs** — backward compatible, no regression
2. **RAG adds `rag_context`** — top-k semantically similar chunks appended to response
3. **LLM decides** whether to use rag_context in its reasoning

The RAG layer is purely additive. It never replaces the structured model data.

## Data Pipeline

```
wiki.fractalaudio.com
  → MediaWiki allpages API (113 pages discovered)
  → pandoc HTML→Markdown per page
  → Clean (remove nav cruft, wiki markup artifacts)
  → Split by headings, then by size (800 char chunks, 100 overlap)
  → Embed (sentence-transformers, all-MiniLM-L6-v2, local)
  → Store in ChromaDB (persistent, data/rag_db/)
```

### Index Stats (2026-06-10)

| Category | Chunks |
|----------|--------|
| general | 6,892 |
| amp | 3,043 |
| cab | 1,052 |
| drive | 568 |
| delay | 175 |
| compressor | 142 |
| reverb | 111 |
| pitch | 97 |
| phaser | 58 |
| flanger | 57 |
| tremolo | 55 |
| chorus | 46 |
| wah | 45 |
| filter | 43 |
| rotary | 22 |
| **Total** | **12,406** |

## A/B Evaluation

### Design

RAG is toggled via environment variable to enable controlled comparison:

- **Same tool interface** — LLM-side prompt is identical
- **Same keyword results** — structured model data unchanged
- **Only difference** — presence/absence of `rag_context` in response

### Test Protocol

1. Fresh session (no prior context about RAG)
2. Same prompt: "Build me an SRV tone" (or equivalent)
3. Observe: does the AI call `fm9_lookup_model_info`? What model does it select?
4. Compare across RAG ON/OFF sessions

### Preliminary Results (2026-06-10, N=3)

| Trial | RAG | Called lookup? | Selected signature model? | Notes |
|-------|-----|---------------|--------------------------|-------|
| 1 | OFF | — | ❌ Generic choice | |
| 2 | OFF | — | ❌ Generic choice | |
| 3 | ON | ✅ (guided) | ✅ Signature amp | Vibrato Verb (SRV's actual amp) |

**Observations:**
- RAG OFF: LLM relies on training data, tends to pick "safe" well-known models
- RAG ON: lookup returns wiki-sourced specific model info → better selection
- However: LLM does not always call lookup unless guided (steering needed)
- The lookup tool itself (keyword match) could also surface this info — RAG's unique value is when query ≠ exact keyword

### Known Issues

1. **LLM doesn't always call lookup** — needs steering to enforce
2. **rag_context as separate field may be ignored** — consider inlining into prose
3. **Duplicate source pages** (Amp models / Amp models list) inflate results
4. **Some pages share content** (FRFR, Fletcher-Munson, Spillover = 392 chunks each — likely wiki templating artifact)

## Future Improvements

- [ ] Steering rule: "Always call lookup before model selection"
- [ ] Deduplicate identical/near-identical chunks
- [ ] Inline top rag_context into a `expert_notes` prose field
- [ ] Cliff Chase quotes extraction as high-priority chunks
- [ ] Larger embedding model option (e5-large) for better semantic matching
- [ ] Incremental index update (add new pages without full rebuild)
- [ ] Stadium (Line 6) wiki data as second knowledge source

## Files

```
tools/rag.py                    ← RAG engine (ChromaDB + sentence-transformers)
pipeline/build_rag_index.py     ← Full wiki ingest pipeline
data/rag_db/                    ← ChromaDB persistent storage (gitignored)
pipeline/wiki_cache/            ← Cached markdown pages (gitignored)
```
