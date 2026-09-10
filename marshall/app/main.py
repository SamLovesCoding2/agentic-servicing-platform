"""
Marshall — FastAPI backend for the Salient Replica.

M1: Minimal entrypoint. Full API surface comes in M2-M5.
"""

from __future__ import annotations

from fastapi import FastAPI

app = FastAPI(title="Marshall", version="0.1.0", description="Salient Replica backend")


@app.get("/health")
async def health():
    return {"status": "healthy", "service": "marshall", "version": "0.1.0"}


@app.get("/ready")
async def ready():
    return {"status": "ready", "service": "marshall"}
