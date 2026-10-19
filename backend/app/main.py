"""APIL FastAPI application entry point.

IMPORTANT: app.config must be imported FIRST so that .env credentials are loaded
into os.environ before app.api.routers instantiates the TransactionCoordinator
(and its PayPalClient) at module level.
"""

import app.config  # noqa: F401 — side-effect: loads .env with override=True

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routers import router

app = FastAPI(
    title="PayPact — Agent Payment Integrity Layer (APIL) API",
    description=(
        "Deterministic authorization, canonical proposal fingerprinting, "
        "and lifecycle state verification for AI purchasing agents with PayPal."
    ),
    version="1.0.0",
)

# Enable CORS for Next.js web application
cors_origins_raw = os.getenv("CORS_ORIGINS", "").strip()
if cors_origins_raw and cors_origins_raw != "*":
    allowed_origins = [o.strip() for o in cors_origins_raw.split(",") if o.strip()]
    allow_credentials = True
elif cors_origins_raw == "*":
    allowed_origins = ["*"]
    allow_credentials = (
        False  # Wildcard cannot have allow_credentials=True per W3C CORS spec
    )
else:
    allowed_origins = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ]
    allow_credentials = True

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/")
async def root():
    return {
        "project": "PayPact — Agent Payment Integrity Layer (APIL)",
        "hackathon": "PayPal AI Hackathon 2026",
        "docs_url": "/docs",
        "health_url": "/api/health",
    }
