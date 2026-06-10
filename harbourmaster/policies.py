"""Persistence helpers for corporate procurement policy definitions."""

from __future__ import annotations

import json
import re
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

POLICIES_DIR = Path(__file__).resolve().parents[1] / "configs" / "corporate_policies"
ALLOWED_SCOPE_TAGS = {"legal", "financial", "delivery", "ip_data", "compliance"}


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "policy"


def _validate_policy(data: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError("policy must be a JSON object")

    title = str(data.get("title") or "").strip()
    if not title:
        raise ValueError("policy title is required")

    policy_id = str(data.get("id") or _slugify(title)).strip()
    version = str(data.get("version") or "1.0").strip()
    body = str(data.get("body") or "").strip()
    if not body:
        raise ValueError("policy body is required")

    raw_tags = data.get("scope_tags") or []
    if not isinstance(raw_tags, list):
        raise ValueError("scope_tags must be a list")

    scope_tags = sorted({str(tag).strip() for tag in raw_tags if str(tag).strip()})
    invalid = [tag for tag in scope_tags if tag not in ALLOWED_SCOPE_TAGS]
    if invalid:
        raise ValueError(f"invalid scope tags: {', '.join(invalid)}")

    active = bool(data.get("active", True))
    return {
        "id": policy_id,
        "title": title,
        "version": version,
        "scope_tags": scope_tags,
        "active": active,
        "body": body,
    }


def _policy_path(slug: str) -> Path:
    safe_slug = _slugify(slug)
    return POLICIES_DIR / f"{safe_slug}.json"


def list_policies() -> list[dict[str, Any]]:
    """Return all stored policies sorted by title."""
    if not POLICIES_DIR.exists():
        return []

    rows: list[dict[str, Any]] = []
    for path in sorted(POLICIES_DIR.glob("*.json")):
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            row = _validate_policy(raw)
            row["_file"] = path.name
            rows.append(row)
        except Exception:
            continue

    rows.sort(key=lambda x: x["title"].lower())
    return rows


def load_policy(slug: str) -> dict[str, Any]:
    """Load one policy by slug (filename without extension)."""
    path = _policy_path(slug)
    if not path.exists():
        raise FileNotFoundError(f"policy not found: {slug}")
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    policy = _validate_policy(raw)
    policy["_file"] = path.name
    return policy


def save_policy(data: dict[str, Any], slug: str | None = None) -> dict[str, Any]:
    """Persist one policy using atomic file write semantics."""
    policy = _validate_policy(data)
    POLICIES_DIR.mkdir(parents=True, exist_ok=True)

    target_slug = slug or policy["id"] or policy["title"]
    target = _policy_path(target_slug)
    policy["id"] = _slugify(target.stem)

    with NamedTemporaryFile("w", delete=False, dir=POLICIES_DIR, encoding="utf-8") as tmp:
        json.dump(policy, tmp, indent=2, ensure_ascii=True)
        tmp.write("\n")
        tmp_path = Path(tmp.name)

    tmp_path.replace(target)
    policy["_file"] = target.name
    return policy


def delete_policy(slug: str) -> bool:
    """Delete one policy file by slug."""
    path = _policy_path(slug)
    if not path.exists():
        return False
    path.unlink()
    return True


def active_policies() -> list[dict[str, Any]]:
    """Return all policies currently marked active."""
    return [p for p in list_policies() if p.get("active")]
