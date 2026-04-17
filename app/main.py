from contextlib import asynccontextmanager
import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.admin.local_ingestion import ingest_local_documents
from app.admin.routes import router as admin_router
from app.config.settings import get_settings
from app.webhook.handler import handle_get, handle_post

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
settings = get_settings()
static_dir = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(_: FastAPI):
    logger.info("Starting local document ingestion")
    result = ingest_local_documents()
    logger.info("Local document ingestion complete: %s", result)
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.include_router(admin_router)
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/")
async def dashboard():
    return FileResponse(static_dir / "index.html")


@app.get("/webhook")
async def verify(req: Request):
    return await handle_get(req)


@app.post("/webhook")
async def webhook(req: Request):
    return await handle_post(req)
