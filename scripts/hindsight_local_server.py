"""Standalone Local Hindsight-compatible HTTP Server on port 8888.

Can be started via `python scripts/hindsight_local_server.py` when the external
`hindsight-api` binary is not installed, providing the exact HTTP endpoints at
http://localhost:8888 (`/v1/default/banks/{bank_id}/memories`, `/recall`, `/reflect`, `/config`).
"""
from __future__ import annotations

import os
from typing import Any, Optional

from fastapi import FastAPI
from pydantic import BaseModel
import uvicorn

os.environ["HINDSIGHT_FORCE_EMBEDDED"] = "1"
from hindsight_client import Hindsight  # noqa: E402

app = FastAPI(title="Local Hindsight API Server", version="0.1.0")
engine = Hindsight(base_url="http://localhost:8888")


class ConfigPayload(BaseModel):
    mission: str
    directives: list[str]
    disposition: str = "moderately_skeptical"


class RetainPayload(BaseModel):
    content: str
    metadata: Optional[dict[str, Any]] = None
    timestamp: Optional[str] = None


class RecallPayload(BaseModel):
    query: str
    token_budget: int = 600


class ReflectPayload(BaseModel):
    prompt: str
    context: Optional[dict[str, Any]] = None


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "hindsight-api-local"}


@app.post("/v1/default/banks/{bank_id}/config")
def configure_bank(bank_id: str, payload: ConfigPayload) -> dict[str, Any]:
    return engine.configure_bank(
        bank_id=bank_id,
        mission=payload.mission,
        directives=payload.directives,
        disposition=payload.disposition,
    )


@app.post("/v1/default/banks/{bank_id}/memories")
def retain_memory(bank_id: str, payload: RetainPayload) -> dict[str, Any]:
    return engine.retain(
        bank_id=bank_id,
        content=payload.content,
        metadata=payload.metadata,
        timestamp=payload.timestamp,
    )


@app.post("/v1/default/banks/{bank_id}/recall")
def recall_memory(bank_id: str, payload: RecallPayload) -> dict[str, Any]:
    return engine.recall(
        bank_id=bank_id,
        query=payload.query,
        token_budget=payload.token_budget,
    )


@app.post("/v1/default/banks/{bank_id}/reflect")
def reflect_memory(bank_id: str, payload: ReflectPayload) -> dict[str, Any]:
    return engine.reflect(
        bank_id=bank_id,
        prompt=payload.prompt,
        context=payload.context,
    )


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8888)

