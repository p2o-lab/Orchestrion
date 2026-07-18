"""FastAPI application for the Orchestrion POL backend."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from orchestrion.api import live, peas, projects
from orchestrion.db.engine import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()                       # create tables on first run
    yield
    await live.registry.shutdown()  # close every persistent PEA connection on exit


app = FastAPI(title="Orchestrion", version="0.1.0", lifespan=lifespan)

app.include_router(projects.router)
app.include_router(peas.router)
app.include_router(live.router)


# The route owns the /api prefix: the Vite dev proxy forwards /api/* without a
# rewrite, so a bare /health would be shadowed by the dev server and never reach
# this app from the browser.
@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
