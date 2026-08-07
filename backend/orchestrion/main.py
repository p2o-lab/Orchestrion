"""FastAPI application for the Orchestrion POL backend."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from orchestrion.api import control, live, peas, projects, recipes
from orchestrion.db.engine import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()                        # create tables on first run
    yield
    # Runs first: a live run drives services over the very connections the registry is
    # about to close, so cancelling it afterwards would have it writing into a dead
    # session. Neither commands the PEAs — an aborted run leaves equipment running
    # (step model §10), which is the same known limitation `abort` carries.
    await recipes.runs.shutdown()
    await live.registry.shutdown()   # close every persistent PEA connection on exit


app = FastAPI(title="Orchestrion", version="0.1.0", lifespan=lifespan)

app.include_router(projects.router)
app.include_router(peas.router)
app.include_router(live.router)
app.include_router(control.router)
app.include_router(recipes.router)


# The route owns the /api prefix: the Vite dev proxy forwards /api/* without a
# rewrite, so a bare /health would be shadowed by the dev server and never reach
# this app from the browser.
@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
