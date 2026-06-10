"""Seed Elasticsearch with Harbourmaster procurement knowledge."""

from __future__ import annotations

import sys

from harbourmaster import config
from harbourmaster.elastic_store import index_all


def main() -> None:
    print("=== Harbourmaster Elastic indexer ===")
    print(f"Elastic URL: {config.ELASTIC_URL}")
    try:
        counts = index_all()
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: could not index Elastic knowledge: {exc}")
        sys.exit(1)

    for name, count in counts.items():
        print(f"{name}: {count}")
    print("PASS: Elastic knowledge indexes updated.")


if __name__ == "__main__":
    main()
