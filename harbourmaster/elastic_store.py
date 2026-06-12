"""Elasticsearch indexing and retrieval helpers for procurement memory."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from harbourmaster import config
from harbourmaster.policies import active_policies

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
REDTEAM_CASES = ROOT / "configs" / "redteam_cases.yaml"


def enabled() -> bool:
    return config.ELASTIC_ENABLED and bool(config.ELASTIC_URL)


def client():
    """Return an Elasticsearch client configured from env."""
    if not enabled():
        raise RuntimeError("Elastic integration is disabled")

    from elasticsearch import Elasticsearch

    kwargs: dict[str, Any] = {"request_timeout": 10}
    if _usable_api_key(config.ELASTIC_API_KEY):
        kwargs["api_key"] = config.ELASTIC_API_KEY
    elif config.ELASTIC_USERNAME and config.ELASTIC_PASSWORD:
        kwargs["basic_auth"] = (config.ELASTIC_USERNAME, config.ELASTIC_PASSWORD)

    return Elasticsearch(config.ELASTIC_URL, **kwargs)


def index_name(kind: str) -> str:
    safe = re.sub(r"[^a-z0-9_-]+", "-", kind.lower()).strip("-")
    return f"{config.ELASTIC_INDEX_PREFIX}-{safe}"


def ensure_indexes() -> None:
    es = client()
    mapping = {
        "mappings": {
            "properties": {
                "doc_type": {"type": "keyword"},
                "source": {"type": "keyword"},
                "title": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
                "body": {"type": "text"},
                "content": {"type": "text"},
                "tags": {"type": "keyword"},
                "policy_id": {"type": "keyword"},
                "clause_id": {"type": "keyword"},
                "risk_level": {"type": "keyword"},
                "metadata": {"type": "object", "enabled": True},
            }
        }
    }
    for kind in ("knowledge", "reviews"):
        name = index_name(kind)
        if not es.indices.exists(index=name):
            es.indices.create(index=name, **mapping)


def index_policies() -> int:
    ensure_indexes()
    es = client()
    count = 0
    for policy in active_policies():
        doc = {
            "doc_type": "policy",
            "source": "corporate_policies",
            "title": policy["title"],
            "body": policy["body"],
            "content": policy["body"],
            "tags": policy.get("scope_tags", []),
            "policy_id": policy["id"],
            "metadata": {
                "version": policy.get("version", "1.0"),
                "active": policy.get("active", True),
            },
        }
        es.index(index=index_name("knowledge"), id=f"policy:{policy['id']}", document=doc)
        count += 1
    return count


def index_sample_tenders() -> int:
    ensure_indexes()
    es = client()
    count = 0
    for path in sorted(DATA_DIR.glob("sample_tender*.md")):
        text = path.read_text(encoding="utf-8")
        for clause in split_clauses(text):
            doc_id = f"tender:{path.stem}:{clause['id']}"
            doc = {
                "doc_type": "tender_clause",
                "source": path.name,
                "title": clause["title"],
                "body": clause["text"],
                "content": clause["text"],
                "tags": ["sample_tender", "clause"],
                "clause_id": clause["id"],
                "metadata": {"file": path.name},
            }
            es.index(index=index_name("knowledge"), id=doc_id, document=doc)
            count += 1
    return count


def index_redteam_cases() -> int:
    ensure_indexes()
    import yaml

    es = client()
    data = yaml.safe_load(REDTEAM_CASES.read_text(encoding="utf-8"))
    count = 0
    for case in data.get("test_cases", []):
        name = str(case.get("name", "case"))
        doc = {
            "doc_type": "redteam_case",
            "source": "configs/redteam_cases.yaml",
            "title": name,
            "body": str(case.get("prompt", "")),
            "content": str(case.get("prompt", "")),
            "tags": ["redteam", str(case.get("category", ""))],
            "risk_level": str(case.get("expected_action", "")),
            "metadata": {
                "category": case.get("category", ""),
                "description": case.get("description", ""),
                "expected_action": case.get("expected_action", ""),
            },
        }
        es.index(index=index_name("knowledge"), id=f"redteam:{name}", document=doc)
        count += 1
    return count


def index_review_artifact(kind: str, title: str, body: str, metadata: dict[str, Any] | None = None) -> None:
    ensure_indexes()
    doc_id = f"{kind}:{_stable_id(title + body)}"
    client().index(
        index=index_name("reviews"),
        id=doc_id,
        document={
            "doc_type": kind,
            "source": "harbourmaster_review",
            "title": title,
            "body": body,
            "content": body,
            "tags": [kind],
            "metadata": metadata or {},
        },
    )


def search(query: str, *, size: int = 5, doc_types: list[str] | None = None) -> list[dict[str, Any]]:
    """Run text search against indexed procurement memory (MCP-first, native fallback)."""
    if not query.strip() or not enabled():
        return []

    # MCP-first: search via the Elastic MCP server.
    try:
        from harbourmaster.mcp_client import mcp_elastic_search

        hits = mcp_elastic_search(
            query=query,
            size=size,
            index=f"{config.ELASTIC_INDEX_PREFIX}-*",
            doc_types=doc_types,
        )
        if hits is not None:
            return hits
    except Exception:  # noqa: BLE001
        pass

    try:
        ensure_indexes()
        filters: list[dict[str, Any]] = []
        if doc_types:
            filters.append({"terms": {"doc_type": doc_types}})
        response = client().search(
            index=f"{config.ELASTIC_INDEX_PREFIX}-*",
            size=size,
            query={
                "bool": {
                    "must": [
                        {
                            "multi_match": {
                                "query": query,
                                "fields": ["title^3", "body", "content", "tags^2", "policy_id^2"],
                            }
                        }
                    ],
                    "filter": filters,
                }
            },
        )
    except Exception:  # noqa: BLE001
        return []

    hits = []
    for hit in response.get("hits", {}).get("hits", []):
        source = hit.get("_source", {})
        source["_score"] = hit.get("_score", 0)
        source["_index"] = hit.get("_index", "")
        hits.append(source)
    return hits


def retrieval_context_for_clauses(clauses: list[dict[str, str]], *, size: int = 3) -> list[dict[str, Any]]:
    """Find similar policy/precedent snippets for segmented clauses."""
    rows: list[dict[str, Any]] = []
    for clause in clauses[:8]:
        query = f"{clause.get('title', '')}\n{clause.get('text', '')}"
        for hit in search(query, size=size, doc_types=["policy", "tender_clause", "redteam_case"]):
            rows.append(
                {
                    "clause_id": clause.get("id", ""),
                    "query_title": clause.get("title", ""),
                    "match_type": hit.get("doc_type", ""),
                    "match_title": hit.get("title", ""),
                    "match_source": hit.get("source", ""),
                    "body": str(hit.get("body", ""))[:900],
                    "score": hit.get("_score", 0),
                }
            )
    return rows[:12]


def split_clauses(text: str) -> list[dict[str, str]]:
    """Simple markdown heading splitter for indexing sample tenders."""
    heading = re.compile(r"^#{2,6}\s+(.*)$")
    clauses: list[dict[str, str]] = []
    current_title = "Document Body"
    current_lines: list[str] = []

    def flush() -> None:
        body = "\n".join(current_lines).strip()
        if body:
            clauses.append(
                {
                    "id": f"C{len(clauses) + 1}",
                    "title": current_title,
                    "text": body,
                }
            )

    for line in text.splitlines():
        match = heading.match(line.strip())
        if match:
            flush()
            current_title = match.group(1).strip() or f"Clause {len(clauses) + 1}"
            current_lines = []
        else:
            current_lines.append(line)
    flush()
    return clauses or [{"id": "C1", "title": "Document Body", "text": text.strip()}]


def index_all() -> dict[str, int]:
    return {
        "policies": index_policies(),
        "sample_tenders": index_sample_tenders(),
        "redteam_cases": index_redteam_cases(),
    }


def _stable_id(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:24]


def _usable_api_key(value: str) -> bool:
    """Avoid treating demo placeholder secrets as real Elastic API keys."""
    from harbourmaster.settings import usable_secret

    return usable_secret(value) is not None
