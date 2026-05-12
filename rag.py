import os
from typing import List, Dict, Any

import numpy as np
from openai import OpenAI

from db import get_all_threads_with_embeddings


OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

EMBEDDING_MODEL = "text-embedding-3-small"
CHAT_MODEL = "gpt-4.1-mini"


_client: OpenAI | None = None


def get_openai_client() -> OpenAI:
    global _client
    if _client is None:
        if not OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY environment variable is not set")
        _client = OpenAI(api_key=OPENAI_API_KEY)
    return _client


def generate_embedding(text: str) -> List[float]:
    client = get_openai_client()
    response = client.embeddings.create(model=EMBEDDING_MODEL, input=text)
    return response.data[0].embedding


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    if a.shape != b.shape:
        raise ValueError("Embedding vectors must have the same shape")
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


def retrieve_relevant_threads(query: str, top_k: int = 5) -> List[Dict[str, Any]]:
    """
    Embed the query, compute cosine similarity against stored thread embeddings,
    and return the top_k most relevant threads.
    """
    query_embedding = np.array(generate_embedding(query), dtype=float)
    threads = get_all_threads_with_embeddings()

    scored: List[Dict[str, Any]] = []
    for th in threads:
        if not th.get("embedding"):
            continue
        emb = np.array(th["embedding"], dtype=float)
        score = _cosine_similarity(query_embedding, emb)
        scored.append({**th, "score": score})

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_k]


def build_chat_prompt(question: str, context_threads: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """
    Build messages for OpenAI chat completion using thread-level Slack context.
    """
    context_blocks: List[str] = []
    for th in context_threads:
        channel_name = th.get("channel_name") or th.get("channel_id") or "unknown-channel"
        text = th.get("text") or ""
        url = th.get("url")
        header = f"Slack Thread (channel: {channel_name})"
        if url:
            header += f"\nSource: {url}"
        block = f"{header}\n\n{text}"
        context_blocks.append(block)

    context_text = "\n\n---\n\n".join(context_blocks) if context_blocks else "No relevant Slack discussions available."

    system_content = "You answer questions using internal Slack discussions."
    user_content = (
        f"{context_text}\n\n"
        "User question:\n"
        f"{question}"
    )

    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_content},
    ]


def answer_question(question: str) -> str:
    """
    1) Retrieve relevant Slack threads
    2) Call OpenAI chat completion
    3) Return the assistant's reply text
    """
    client = get_openai_client()

    context_threads = retrieve_relevant_threads(question, top_k=5)
    messages = build_chat_prompt(question, context_threads)

    response = client.chat.completions.create(
        model=CHAT_MODEL,
        messages=messages,
        temperature=0.2,
    )

    return response.choices[0].message.content or ""

