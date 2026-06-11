# Harbourmaster

Harbourmaster is a governed, multi-agent tender review control plane built with Gemini and LangGraph. It uses **Arize Phoenix** for observability/evaluation and **Elastic** for searchable procurement memory over policies, tenders, clauses, red-team prompts, and review artifacts.

## What changed in this refactor

- Replaced external proxy firewall with inline guard (`guard.py`) and Phoenix telemetry.
- Added inline `guard.py` evaluator (`ALLOW | HUMAN_REVIEW | DENY`) before workflow execution.
- Routed all model calls directly to Gemini's OpenAI-compatible endpoint.
- Added Phoenix OpenInference tracing bootstrap (`telemetry.py`).
- Replaced file-based audit model with Phoenix trace/span-backed dashboard ingestion.
- Added Governance Copilot page backed by `@arizeai/phoenix-mcp`.
- Added Elastic MCP and persistent local Elasticsearch for policy/precedent search.
- Updated Docker Compose to `ui + phoenix + elastic` (self-hosted by default, cloud via env).

## Architecture

```text
Tender input -> Guard evaluator -> LangGraph specialists -> Human review (if needed) -> Draft summary
                      |                           |                         |
                      +---- inspection reports ---+                         +-> Elastic review memory

Every model call + workflow activity -> OpenInference -> Arize Phoenix
Policies/samples/red-team cases/review outputs -> Elasticsearch
Governance Copilot uses Phoenix MCP for traces/evals and Elastic MCP for search.
```

## Prerequisites

- Python 3.10+
- Node 18+ (for `npx @arizeai/phoenix-mcp` and `npx @elastic/mcp-server-elasticsearch`)
- Gemini API key
- Docker + Docker Compose (for self-hosted Phoenix and Elasticsearch)

## Environment and modes

Settings merge in this order: **defaults → `configs/runtime_settings/runtime_config.json` (optional UI overrides) → environment variables (highest precedence)**. Local Phoenix + Elastic are the default modes; set keys in `.env` / `.env.docker`.

Per-service deployment modes:

| Variable | Values | Purpose |
|----------|--------|---------|
| `PHOENIX_MODE` | `local` / `cloud` | Self-hosted Phoenix vs Phoenix Cloud |
| `ELASTIC_MODE` | `local` / `cloud` | Compose Elasticsearch vs Elastic Cloud |
| `MCP_ENABLED` | `true` / `false` | Master switch for Governance Copilot MCP subprocesses |
| `MCP_PHOENIX_ENABLED` | `true` / `false` | Phoenix MCP server (`@arizeai/phoenix-mcp`) |
| `MCP_ELASTIC_ENABLED` | `true` / `false` | Elastic MCP server (native Elastic search tools still work when false) |

Copy `.env.example` to `.env` for local development, or `.env.docker` for Compose (`cp .env.docker.example .env.docker`).

Key URLs and secrets:

- `GEMINI_API_KEY` — Copilot and workflow LLM calls
- `PHOENIX_BASE_URL` — server-side REST, OTLP, MCP (`http://phoenix:6006` in Docker local mode)
- `PHOENIX_CONSOLE_URL` — browser links (`http://localhost:6006` from host)
- `PHOENIX_API_KEY` — required when `PHOENIX_MODE=cloud`
- `ELASTIC_URL` — native client + MCP (`http://elastic:9200` in Docker local mode)
- `ELASTIC_API_KEY` — required when `ELASTIC_MODE=cloud`

Validate resolved settings:

```bash
make config-check
```

## Run

```bash
make install
make run            # ui + phoenix + elastic (COMPOSE_PROFILES=local in .env.docker)
make smoke          # Gemini + guard + workflow smoke checks
make smoke-copilot  # copilot health + native tool path
make config-check   # resolved settings + validation
make demo           # CLI tender review workflow
make ui             # local Streamlit UI
make redteam        # adversarial suite + Phoenix experiment sync
make index-elastic  # seed policies, sample tenders, and red-team prompts into Elastic
```

Cloud / hybrid (UI-only Compose stack):

```bash
cp .env.cloud.example .env.cloud
# fill PHOENIX_API_KEY and optional ELASTIC_API_KEY
make run-cloud
```

## Deploy to a VPS (self-hosted stack)

Phoenix and Elastic start automatically when `.env.docker` sets `COMPOSE_PROFILES=local` (the default in `.env.docker.example`). Starting **only** `ui` without that profile leaves nothing listening on `phoenix:6006` / `elastic:9200`.

```bash
cp .env.docker.example .env.docker
# edit GEMINI_API_KEY and set PHOENIX_CONSOLE_URL to your public VPS host, e.g.:
# PHOENIX_CONSOLE_URL=http://203.0.113.10:6006

docker compose --env-file .env.docker up --build -d
```

Keep **server-side** URLs on the Docker network (do not change these for VPS):

- `PHOENIX_BASE_URL=http://phoenix:6006`
- `ELASTIC_URL=http://elastic:9200`

Set **browser** URL separately:

- `PHOENIX_CONSOLE_URL=http://<your-vps-host>:6006`

Open firewall ports `8501` (UI), `6006` (Phoenix console), and optionally `9200`. If you used the Configuration page locally, delete or fix `configs/runtime_settings/runtime_config.json` on the VPS when it still points at `localhost`.

For a UI-only VPS with managed Phoenix/Elastic, use `make run-cloud` and `.env.cloud` instead.

## Streamlit pages

- `Home.py`: reviewer workflow and HITL controls
- `2_Governance_Dashboard.py`: Phoenix telemetry dashboard
- `3_Red_Team_Scorecard.py`: adversarial scorecard
- `4_Corporate_Policies.py`: policy management
- `5_Governance_Copilot.py`: MCP-driven governance copilot
- `6_Configuration.py`: modes, credentials, MCP toggles, validation, and runtime overrides

## Demo flow

```bash
make run
make index-elastic
make demo SAMPLE=data/sample_tender_human_review.md
make redteam
```

Then open **Governance Copilot** and ask:

- “Find similar high-risk indemnity clauses from prior tenders.”
- “Which policy passages support escalating this clause?”
- “Show precedent counter-clauses for IP ownership risk.”
- “Show the latest red-team experiment and key failures.”

## Challenge fit

- Real-world multi-step business workflow (tender governance)
- Human-in-the-loop checkpoint via LangGraph interrupt
- Meaningful partner MCP usage through Phoenix Copilot/telemetry workflows
- Elastic MCP adds enterprise semantic search over procurement knowledge
- Dataset/experiment loop for red-team regression checks
