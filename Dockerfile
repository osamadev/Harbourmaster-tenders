# syntax=docker/dockerfile:1.7

ARG PYTHON_VERSION=3.11

FROM python:${PYTHON_VERSION}-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl nodejs npm \
    && rm -rf /var/lib/apt/lists/*

# Pre-fetch the MCP server packages into the image so runtime `npx` never downloads them
# (the slowest part of the Copilot/dashboard MCP cold start). Keep these versions in sync
# with the MCP_*_PACKAGE defaults in harbourmaster/settings.py and .env.docker.
ARG MCP_PHOENIX_PACKAGE=@arizeai/phoenix-mcp@4.0.14
ARG MCP_ELASTIC_PACKAGE=@elastic/mcp-server-elasticsearch@0.3.1
RUN npm install -g "${MCP_PHOENIX_PACKAGE}" "${MCP_ELASTIC_PACKAGE}" || true

COPY requirements.txt pyproject.toml README.md ./
COPY harbourmaster ./harbourmaster
COPY app ./app
COPY .streamlit ./.streamlit
COPY configs ./configs
COPY data ./data
COPY scripts ./scripts

RUN python -m pip install --upgrade pip \
    && pip install -r requirements.txt \
    && pip install -e .

EXPOSE 8000 8501
