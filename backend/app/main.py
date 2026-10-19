"""APIL FastAPI application entry point.

IMPORTANT: app.config must be imported FIRST so that .env credentials are loaded
into os.environ before app.api.routers instantiates the TransactionCoordinator
(and its PayPalClient) at module level.
"""
import app.config  # noqa: F401 — side-effect: loads .env with override=True

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routers import router

app = FastAPI(
    title="Agent Payment Integrity Layer (APIL) API",
    description=(
        "Deterministic authorization, canonical proposal fingerprinting, "
        "and lifecycle state verification for AI purchasing agents with PayPal."
    ),
    version="1.0.0",
)

import os

# Enable CORS for Next.js web application
cors_origins_raw = os.getenv("CORS_ORIGINS", "*")
if cors_origins_raw == "*":
    allowed_origins = ["*"]
else:
    allowed_origins = [o.strip() for o in cors_origins_raw.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/")
async def root():
    return {
        "project": "Agent Payment Integrity Layer (APIL)",
        "hackathon": "PayPal AI Hackathon 2026",
        "docs_url": "/docs",
        "health_url": "/api/health",
    }
