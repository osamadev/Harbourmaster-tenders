# Submission Summary

## Project

Harbourmaster is a governed procurement/tender review agent system that:

- segments and analyzes contract clauses with specialist agents,
- computes aggregate risk and verifier decisions,
- pauses for human oversight when risk is high,
- proposes counter-clauses and drafts reviewer-ready summaries.

## Partner track alignment: Arize + Elastic

This solution uses two complementary partner integrations:

Arize Phoenix provides governance observability and evaluation:

- OpenInference traces for model + workflow activity
- Governance dashboard powered by Phoenix telemetry
- Red-team suite synced as dataset/experiment metadata
- Governance Copilot that uses `@arizeai/phoenix-mcp` tools to inspect traces, datasets, prompts, and experiments

Elastic provides searchable procurement memory:

- Persistent Elasticsearch indexes for policies, sample tenders, red-team prompts, review summaries, and counter-clause artifacts
- Elastic MCP tools in Governance Copilot for policy and precedent search
- Optional retrieval context injected into specialist analysis while preserving clause-level evidence requirements

## Multi-step mission

The workflow is explicitly multi-step:

1. Guard evaluation on tender content
2. Clause segmentation
3. Elastic retrieval of similar policy/precedent snippets
4. Parallel specialist analyses
5. Deterministic aggregation
6. Verifier revision loop
7. Governance routing to auto-continue or HITL interrupt
8. Negotiation and final draft generation
9. Review artifact persistence back into Elastic

## Human control

Harbourmaster uses LangGraph interrupt/resume so a human reviewer can approve/reject and provide notes before final output.

## Deployment model

- **Local (default):** `make run` starts Compose profile `local` (`ui` + self-hosted `phoenix` + `elastic`)
- **Cloud / hybrid:** `make run-cloud` with `.env.cloud` — set `PHOENIX_MODE=cloud` and `PHOENIX_API_KEY`; optionally `ELASTIC_MODE=cloud` with `ELASTIC_API_KEY`
- **Configuration UI:** Streamlit `6_Configuration.py` saves non-env overrides to `configs/runtime_settings/runtime_config.json` (environment variables always win)
- **Validation:** `make config-check` prints resolved URLs, modes, and missing-key errors before demos
