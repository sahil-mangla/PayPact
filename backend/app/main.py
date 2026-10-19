from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from app.api.routers import router

load_dotenv()

app = FastAPI(
    title="Agent Payment Integrity Layer (APIL) API",
    description=(
        "Deterministic authorization, canonical proposal fingerprinting, "
        "and lifecycle state verification for AI purchasing agents with PayPal."
    ),
    version="1.0.0",
)

# Enable CORS for Next.js web application
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000", "*"],
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
