#!/usr/bin/env bash
export $(grep -v '^#' ops/env.example | xargs) && \
uvicorn api.app:app --host 0.0.0.0 --port ${PORT:-8080} --reload
