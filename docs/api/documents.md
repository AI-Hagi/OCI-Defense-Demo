# Document Intelligence API

Source: `services/doc-intelligence/app/routers/rag.py`. Use case 2
("Doktrin- & Lage-RAG") per `CLAUDE_DEV9.md`.

## `POST /api/documents/search`

Vector + keyword hybrid search over `doc_chunks` (HNSW index on
`embedding`).

Request:

```json
{ "query": "geo-redundancy NIS2", "k": 5 }
```

`k` defaults to 5, max 25.

Response `200 OK` — list of hits ordered by descending hybrid score:

```json
[
  {
    "doc_id": "D001",
    "chunk_idx": 0,
    "title": "NIS2 Annex",
    "snippet": "geo-redundancy baseline ...",
    "score": 0.87
  }
]
```

## `POST /api/documents/chat`

RAG chat — accepts a conversation history, retrieves top-k chunks,
calls the in-cluster LLM, and returns a grounded response with
citations.

Request:

```json
{
  "messages": [{ "role": "user", "content": "Was sagt NIS2 zu Redundanz?" }],
  "k": 5
}
```

Response `200 OK`:

```json
{
  "role": "assistant",
  "content": "NIS2 erfordert geo-redundante Systeme.",
  "citations": [
    {
      "doc_id": "D001",
      "chunk_idx": 0,
      "title": "NIS2 Annex",
      "snippet": "geo-redundancy"
    }
  ]
}
```

Errors: `422` on payload validation; `500` on LLM/embedding failure.
