"""RAG (Retrieval-Augmented Generation) module for Fractal Wiki knowledge.

Uses ChromaDB with sentence-transformers for local embedding + vector search.
Activated via TONE_ASSISTANT_RAG=on environment variable.
"""

import os
from pathlib import Path
from typing import Any

# Lazy-loaded globals
_collection = None
_embed_model = None

# Paths
BASE_DIR = Path(__file__).parent.parent
RAG_DB_DIR = BASE_DIR / "data" / "rag_db"

# Config
EMBEDDING_MODEL = os.environ.get(
    "TONE_ASSISTANT_EMBED_MODEL",
    "all-MiniLM-L6-v2"
)
COLLECTION_NAME = "fractal_wiki"


def _get_embed_model():
    """Lazy-load the sentence-transformer embedding model."""
    global _embed_model
    if _embed_model is None:
        from sentence_transformers import SentenceTransformer
        _embed_model = SentenceTransformer(EMBEDDING_MODEL)
    return _embed_model


def _get_collection():
    """Lazy-load the ChromaDB collection."""
    global _collection
    if _collection is None:
        import chromadb

        client = chromadb.PersistentClient(path=str(RAG_DB_DIR))
        _collection = client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )
    return _collection


def is_available() -> bool:
    """Check if RAG index exists and has data."""
    try:
        coll = _get_collection()
        return coll.count() > 0
    except Exception:
        return False


def query_knowledge(
    query: str,
    block_type: str = "",
    top_k: int = 5,
) -> list[dict[str, Any]]:
    """Query the RAG knowledge base.

    Args:
        query: Natural language query (e.g., "Plexi crunch tone tips")
        block_type: Optional filter by block type (e.g., "amp", "delay")
        top_k: Number of results to return

    Returns:
        List of dicts with keys: content, source, section, score
    """
    try:
        model = _get_embed_model()
        collection = _get_collection()

        # Embed the query
        query_embedding = model.encode(query).tolist()

        # Build optional filter
        where_filter = None
        if block_type:
            where_filter = {"block_type": block_type}

        # Query ChromaDB
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            where=where_filter,
            include=["documents", "metadatas", "distances"],
        )

        # Format results
        output = []
        if results["documents"] and results["documents"][0]:
            for i, doc in enumerate(results["documents"][0]):
                meta = results["metadatas"][0][i] if results["metadatas"] else {}
                distance = results["distances"][0][i] if results["distances"] else 0.0
                output.append({
                    "content": doc,
                    "source": meta.get("source", ""),
                    "section": meta.get("section", ""),
                    "block_type": meta.get("block_type", ""),
                    "score": round(1.0 - distance, 4),  # cosine: 1 = identical
                })

        return output

    except Exception as e:
        return [{"error": str(e), "content": "", "source": "", "section": "", "score": 0.0}]
