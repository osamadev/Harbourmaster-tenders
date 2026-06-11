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
