"""FastAPI application for the Orchestrion POL backend."""

from fastapi import FastAPI

app = FastAPI(title="Orchestrion", version="0.1.0")


# The route owns the /api prefix: the Vite dev proxy forwards /api/* without a
# rewrite, so a bare /health would be shadowed by the dev server and never reach
# this app from the browser.
@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
