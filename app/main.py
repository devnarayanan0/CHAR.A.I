from contextlib import asynccontextmanager
import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.admin.routes import router as admin_router
from app.config.settings import get_settings
from app.webhook.handler import handle_get, handle_post, send_whatsapp_message

logging.basicConfig(
    level=logging.ERROR,
    format="%(levelname)s: %(message)s",
)
logging.getLogger("httpx").setLevel(logging.ERROR)
logging.getLogger("httpcore").setLevel(logging.ERROR)
logging.getLogger("urllib3").setLevel(logging.ERROR)
logging.getLogger("uvicorn.access").setLevel(logging.ERROR)
logger = logging.getLogger(__name__)
settings = get_settings()
static_dir = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(_: FastAPI):
    if not settings.rag_service_url:
        logger.error("RAG_SERVICE_URL missing")

    if not settings.whatsapp_access_token:
        logger.error("WHATSAPP_ACCESS_TOKEN missing")

    if not settings.whatsapp_phone_number_id:
        logger.error("WHATSAPP_PHONE_NUMBER_ID missing")

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


@app.get("/test-send")
async def test_send():
    settings = get_settings()
    to_number = settings.whatsapp_test_number.strip()
    if not to_number:
        return {"status": "failed", "error": "Set WHATSAPP_TEST_NUMBER for test-send"}
    send_whatsapp_message(to_number, "TEST MESSAGE WORKING")
    return {"status": "sent"}
