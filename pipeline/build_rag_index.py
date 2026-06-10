#!/usr/bin/env python3
"""Build RAG index from entire Fractal Audio Wiki (all pages, depth=0).

Fetches all wiki pages via MediaWiki API + pandoc, chunks them,
embeds with sentence-transformers, and stores in ChromaDB.

Usage:
    python3 pipeline/build_rag_index.py [--fetch]  # --fetch to re-download all
    python3 pipeline/build_rag_index.py --stats    # show index stats
    python3 pipeline/build_rag_index.py --test "query"  # test a query
"""

import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

# Project paths
BASE_DIR = Path(__file__).parent.parent
RAG_DB_DIR = BASE_DIR / "data" / "rag_db"
CACHE_DIR = BASE_DIR / "pipeline" / "wiki_cache"

WIKI_BASE = "https://wiki.fractalaudio.com/wiki"
WIKI_API = f"{WIKI_BASE}/api.php"

# Pages to skip (not useful for tone knowledge)
SKIP_PAGES = {
    "Zery uninteresting wiki sandbox",
    "Axe-Fx Wiki Home",
}

# Block type inference from page title
BLOCK_TYPE_MAP = {
    "amp": ["amp", "amplifier"],
    "drive": ["drive", "distortion", "overdrive", "fuzz"],
    "delay": ["delay"],
    "reverb": ["reverb"],
    "chorus": ["chorus"],
    "compressor": ["compressor", "gate"],
    "flanger": ["flanger"],
    "phaser": ["phaser"],
    "wah": ["wah"],
    "pitch": ["pitch", "vocoder"],
    "cab": ["cab", "ir ", "impulse"],
    "tremolo": ["tremolo", "panner"],
    "rotary": ["rotary"],
    "filter": ["filter"],
}

# Chunking config
CHUNK_SIZE = 800
CHUNK_OVERLAP = 100


def infer_block_type(title: str) -> str:
    """Infer block_type from page title."""
    t = title.lower()
    for btype, keywords in BLOCK_TYPE_MAP.items():
        for kw in keywords:
            if kw in t:
                return btype
    return "general"


def get_all_page_titles() -> list[str]:
    """Get all page titles from the wiki via MediaWiki API."""
    titles = []
    apcontinue = ""

    while True:
        url = f"{WIKI_API}?action=query&list=allpages&aplimit=500&format=json"
        if apcontinue:
            url += f"&apcontinue={apcontinue}"

        req = urllib.request.Request(url, headers={
            "User-Agent": "FractalWikiRAG/1.0 (tone-assistant; educational)"
        })
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())

        pages = data.get("query", {}).get("allpages", [])
        for p in pages:
            title = p["title"]
            if title not in SKIP_PAGES:
                titles.append(title)

        # Check for continuation
        if "continue" in data:
            apcontinue = data["continue"].get("apcontinue", "")
        else:
            break

    return titles


def fetch_page(title: str) -> str:
    """Fetch a wiki page as markdown via pandoc. Uses cache."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # Sanitize filename
    safe_name = re.sub(r'[/\\:*?"<>|]', '_', title)
    cache_file = CACHE_DIR / f"{safe_name}.md"

    if cache_file.exists() and "--fetch" not in sys.argv:
        return cache_file.read_text()

    url = f"{WIKI_BASE}/index.php?title={urllib.request.quote(title)}"

    result = subprocess.run(
        ["pandoc", "-f", "html", "-t", "markdown", "--wrap=none", url],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        # Retry once after brief pause
        time.sleep(1)
        result = subprocess.run(
            ["pandoc", "-f", "html", "-t", "markdown", "--wrap=none", url],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            return ""

    text = result.stdout
    if text.strip():
        cache_file.write_text(text)

    # Rate limit: be polite to the wiki
    time.sleep(0.5)
    return text


def clean_wiki_text(text: str) -> str:
    """Remove wiki navigation cruft from markdown text."""
    lines = text.split("\n")
    start = 0
    for i, line in enumerate(lines):
        if line.startswith("# ") or line.startswith("## "):
            start = i
            break

    text = "\n".join(lines[start:])

    # Remove wiki-specific cruft
    text = re.sub(r'\[edit\]', '', text)
    text = re.sub(r'\{[^}]*\.mw-headline[^}]*\}', '', text)
    text = re.sub(r'\{#[^}]*\}', '', text)
    text = re.sub(r'!\[.*?\]\(.*?\)', '', text)
    text = re.sub(r'\[\]\([^)]*\)', '', text)
    text = re.sub(r'\n{3,}', '\n\n', text)

    return text.strip()


def chunk_by_sections(text: str, page_title: str, block_type: str) -> list[dict]:
    """Split text into chunks by markdown headings, with size limits."""
    chunks = []
    sections = re.split(r'^(#{1,3} .+)$', text, flags=re.MULTILINE)

    current_section = page_title
    current_content = ""

    for part in sections:
        if re.match(r'^#{1,3} ', part):
            if current_content.strip():
                for chunk in split_long_content(current_content, current_section, page_title, block_type):
                    chunks.append(chunk)
            current_section = re.sub(r'^#+\s*', '', part).strip()
            current_section = re.sub(r'\[([^\]]+)\]\{[^}]*\}', r'\1', current_section)
            current_content = ""
        else:
            current_content += part

    if current_content.strip():
        for chunk in split_long_content(current_content, current_section, page_title, block_type):
            chunks.append(chunk)

    return chunks


def split_long_content(content: str, section: str, source: str, block_type: str) -> list[dict]:
    """Split content exceeding CHUNK_SIZE into overlapping chunks."""
    content = content.strip()
    if not content or len(content) < 50:
        return []

    if len(content) <= CHUNK_SIZE:
        return [{
            "content": content,
            "section": section,
            "source": source,
            "block_type": block_type,
        }]

    chunks = []
    start = 0
    while start < len(content):
        end = start + CHUNK_SIZE

        if end < len(content):
            para_break = content.rfind("\n\n", start + CHUNK_SIZE // 2, end + 100)
            if para_break > start:
                end = para_break
            else:
                sent_break = content.rfind(". ", start + CHUNK_SIZE // 2, end + 50)
                if sent_break > start:
                    end = sent_break + 1

        chunk_text = content[start:end].strip()
        if chunk_text and len(chunk_text) > 50:
            chunks.append({
                "content": chunk_text,
                "section": section,
                "source": source,
                "block_type": block_type,
            })

        start = end - CHUNK_OVERLAP
        if start >= len(content):
            break

    return chunks


def build_index(chunks: list[dict]):
    """Embed chunks and store in ChromaDB."""
    from sentence_transformers import SentenceTransformer
    import chromadb

    embed_model_name = os.environ.get("TONE_ASSISTANT_EMBED_MODEL", "all-MiniLM-L6-v2")
    print(f"\nLoading embedding model: {embed_model_name}")
    model = SentenceTransformer(embed_model_name)

    print(f"Embedding {len(chunks)} chunks...")
    texts = [c["content"] for c in chunks]
    embeddings = model.encode(texts, show_progress_bar=True, batch_size=64)

    # Create/reset ChromaDB
    RAG_DB_DIR.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(RAG_DB_DIR))

    try:
        client.delete_collection("fractal_wiki")
    except Exception:
        pass

    collection = client.create_collection(
        name="fractal_wiki",
        metadata={"hnsw:space": "cosine"},
    )

    # Generate stable IDs
    ids = []
    for i, chunk in enumerate(chunks):
        h = hashlib.md5(chunk["content"].encode()).hexdigest()[:12]
        ids.append(f"{chunk['source']}_{i}_{h}")

    # Batch insert
    batch_size = 500
    for start in range(0, len(chunks), batch_size):
        end = min(start + batch_size, len(chunks))
        collection.add(
            ids=ids[start:end],
            embeddings=[e.tolist() for e in embeddings[start:end]],
            documents=texts[start:end],
            metadatas=[{
                "source": c["source"],
                "section": c["section"],
                "block_type": c["block_type"],
            } for c in chunks[start:end]],
        )

    print(f"\n✅ Index built: {collection.count()} chunks in {RAG_DB_DIR}")


def show_stats():
    """Show index statistics."""
    import chromadb

    if not RAG_DB_DIR.exists():
        print("No RAG index found. Run: python3 pipeline/build_rag_index.py --fetch")
        return

    client = chromadb.PersistentClient(path=str(RAG_DB_DIR))
    try:
        collection = client.get_collection("fractal_wiki")
    except Exception:
        print("Collection 'fractal_wiki' not found.")
        return

    count = collection.count()
    print(f"Collection: fractal_wiki")
    print(f"Total chunks: {count}")

    if count > 0:
        sample = collection.get(limit=count, include=["metadatas"])
        block_types = {}
        sources = {}
        for m in sample["metadatas"]:
            bt = m.get("block_type", "unknown")
            block_types[bt] = block_types.get(bt, 0) + 1
            src = m.get("source", "unknown")
            sources[src] = sources.get(src, 0) + 1

        print(f"\nBy block_type:")
        for bt, n in sorted(block_types.items(), key=lambda x: -x[1]):
            print(f"  {bt}: {n}")

        print(f"\nBy source (top 20):")
        for src, n in sorted(sources.items(), key=lambda x: -x[1])[:20]:
            print(f"  {src}: {n}")


def test_query(query: str):
    """Test a RAG query."""
    sys.path.insert(0, str(BASE_DIR))
    from tools.rag import query_knowledge

    print(f"Query: \"{query}\"\n")
    results = query_knowledge(query, top_k=5)
    for i, r in enumerate(results):
        print(f"--- Result {i+1} (score: {r['score']}) ---")
        print(f"Source: {r['source']} / Section: {r['section'][:60]}")
        print(r['content'][:300])
        print()


def main():
    if "--stats" in sys.argv:
        show_stats()
        return

    if "--test" in sys.argv:
        idx = sys.argv.index("--test")
        query = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else "Plexi"
        test_query(query)
        return

    print("=== Building RAG Index from Fractal Audio Wiki (full site) ===\n")

    # Get all page titles
    print("Fetching page list from MediaWiki API...")
    titles = get_all_page_titles()
    print(f"Found {len(titles)} pages\n")

    # Fetch and chunk all pages
    all_chunks = []
    for i, title in enumerate(titles):
        block_type = infer_block_type(title)
        print(f"[{i+1}/{len(titles)}] {title} (→ {block_type})")

        text = fetch_page(title)
        if not text:
            print(f"  SKIP (fetch failed)")
            continue

        text = clean_wiki_text(text)
        if len(text) < 100:
            print(f"  SKIP (too short: {len(text)} chars)")
            continue

        chunks = chunk_by_sections(text, title, block_type)
        print(f"  → {len(chunks)} chunks")
        all_chunks.extend(chunks)

    print(f"\n{'='*50}")
    print(f"Total chunks: {len(all_chunks)}")

    if all_chunks:
        build_index(all_chunks)
    else:
        print("No chunks to index!")


if __name__ == "__main__":
    main()
