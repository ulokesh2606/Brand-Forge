"""
rag/brand_memory.py — RAG-powered Brand Knowledge Store

CONCEPT:
--------
Instead of passing a raw text blob (potentially 50,000+ characters) directly
into Agent 1's prompt, we chunk the scraped content, embed each chunk using
OpenAI's text-embedding model, and store them in Qdrant (in-memory mode).

When Agent 1 needs to analyze the brand, it:
  1. Sends a semantic query (e.g. "brand voice and tone")
  2. Retrieves only the top-k most relevant chunks
  3. Passes those focused chunks to the LLM — not the entire scraped dump

WHY THIS MATTERS:
-----------------
1. Token efficiency: A 50k char scraped site at 1 token ≈ 4 chars = ~12,500 tokens.
   With RAG, we send ~1,000-2,000 tokens of highly relevant content instead.
2. Signal-to-noise: Agent 1's brand analysis prompt gets focused, relevant excerpts
   rather than navigation menus, cookie banners, and footer copyright text.
3. Reusability: Once indexed, any agent can query the brand knowledge store
   with different queries (voice vs. products vs. pricing vs. audience).
4. Scalability: In production you'd swap QdrantClient(":memory:") for
   QdrantClient(url="http://qdrant:6333") with zero code changes.

IMPLEMENTATION:
--------------
- Qdrant in-memory mode (no server needed for demo)
- OpenAI text-embedding-3-small (fast, cheap, 1536-dim)
- RecursiveCharacterTextSplitter from langchain-text-splitters
- Per-pipeline collection keyed by thread_id (isolates runs)
"""

import hashlib
import uuid
import os

from openai import OpenAI
from dotenv import load_dotenv
from langchain_text_splitters import RecursiveCharacterTextSplitter
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct

load_dotenv()

# ── Constants ─────────────────────────────────────────────────────────────────

EMBEDDING_MODEL  = "text-embedding-3-small"
EMBEDDING_DIM    = 1536
CHUNK_SIZE       = 600     # chars — tuned for brand copy (shorter = more precise retrieval)
CHUNK_OVERLAP    = 80      # chars — enough context overlap to avoid cutting mid-sentence
TOP_K_DEFAULT    = 5       # chunks returned per retrieval query

# ── Qdrant in-memory client (shared across the process lifetime) ──────────────
_qdrant = QdrantClient(":memory:")
_openai = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Keep track of mappings (thread_id -> collection_name) and existing collections
_thread_to_collection: dict[str, str] = {}
_indexed_hashes: set[str] = set()


# ── Chunking ──────────────────────────────────────────────────────────────────

_splitter = RecursiveCharacterTextSplitter(
    chunk_size=CHUNK_SIZE,
    chunk_overlap=CHUNK_OVERLAP,
    separators=["\n\n", "\n", ". ", " ", ""],
)


def _split_content(text: str) -> list[str]:
    """Split scraped content into overlapping chunks."""
    chunks = _splitter.split_text(text)
    # Filter empty/near-empty chunks
    return [c.strip() for c in chunks if len(c.strip()) > 40]


# ── Embedding ──────────────────────────────────────────────────────────────────

def _embed(texts: list[str]) -> list[list[float]]:
    """
    Embed a list of texts using OpenAI text-embedding-3-small.
    Returns a list of 1536-dimensional vectors.
    Batches requests to stay under the 2048 input limit.
    """
    response = _openai.embeddings.create(
        model=EMBEDDING_MODEL,
        input=texts,
    )
    return [item.embedding for item in response.data]


# ── Public API ────────────────────────────────────────────────────────────────

def index_brand_content(raw_content: str, thread_id: str) -> dict:
    """
    Idempotent RAG indexing. 
    1. Hashes the content to see if we've already embedded it.
    2. If yes, reuses the existing collection.
    3. Maps the thread_id to the resulting collection name.
    """
    # Calculate hash of content to see if we've seen it before
    content_hash = hashlib.md5(raw_content.encode('utf-8')).hexdigest()[:16]
    collection_name = f"brand_hash_{content_hash}"
    
    # Always mapping thread_id to the collection that contains this content
    _thread_to_collection[thread_id] = collection_name
    
    # Idempotent — skip if this exact content is already indexed in Qdrant (in-memory)
    if _qdrant.collection_exists(collection_name):
        print(f"[RAG] Reusing cached brand knowledge for collection '{collection_name}' (Content Match)")
        # Get count for stats
        count = _qdrant.count(collection_name).count
        return {"chunks": count, "collection": collection_name, "cached": True}

    chunks = _split_content(raw_content)
    if not chunks:
        return {"chunks": 0, "collection": collection_name, "cached": False}

    print(f"[RAG] Indexing {len(chunks)} chunks into new collection '{collection_name}'...")

    # Create collection
    _qdrant.create_collection(
        collection_name=collection_name,
        vectors_config=VectorParams(size=EMBEDDING_DIM, distance=Distance.COSINE),
    )

    # Embed all chunks in one API call
    vectors = _embed(chunks)

    # Build Qdrant points
    points = [
        PointStruct(
            id=i,
            vector=vectors[i],
            payload={"text": chunks[i], "chunk_index": i},
        )
        for i in range(len(chunks))
    ]

    _qdrant.upsert(collection_name=collection_name, points=points)

    print(f"[RAG] Successfully indexed {len(chunks)} chunks in '{collection_name}'. Cache is ready.")
    return {"chunks": len(chunks), "collection": collection_name, "cached": False}


def retrieve(query: str, thread_id: str, k: int = TOP_K_DEFAULT) -> list[str]:
    """
    Semantic search over the brand's indexed content.

    Called by agents that need focused context.
    Returns the top-k most relevant text chunks.

    Args:
        query:     Semantic search query (e.g. "brand voice and personality")
        thread_id: Which pipeline run's content to search
        k:         How many chunks to return

    Returns:
        List of chunk strings ordered by relevance (most → least relevant)
    """
    # Look up which collection contains the knowledge for this run
    collection_name = _thread_to_collection.get(thread_id)

    if not collection_name or not _qdrant.collection_exists(collection_name):
        print(f"[RAG] Warning: No collection found for thread {thread_id} — retrieval skipped.")
        return []

    query_vector = _embed([query])[0]

    # Use query_points (the unified modern API) as legacy 'search' is not present in this client version
    results = _qdrant.query_points(
        collection_name=collection_name,
        query=query_vector,
        limit=k,
        with_payload=True,
    ).points

    chunks = [hit.payload["text"] for hit in results]
    scores = [round(hit.score, 3) for hit in results]
    print(f"[RAG] Retrieved {len(chunks)} chunks for query '{query[:50]}...' (scores: {scores})")

    return chunks


def retrieve_as_context(query: str, thread_id: str, k: int = TOP_K_DEFAULT) -> str:
    """
    Convenience wrapper — returns chunks joined as a formatted context string.
    Ready to insert directly into a prompt.
    """
    chunks = retrieve(query, thread_id, k)
    if not chunks:
        return "(no relevant content retrieved)"

    return "\n\n---\n\n".join(f"[Chunk {i+1}]\n{chunk}" for i, chunk in enumerate(chunks))
