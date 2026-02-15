import os
import asyncio
from contextlib import asynccontextmanager
import uuid

from fastapi import FastAPI, Request
import structlog

from models import SearchURLAnalysisRequest, SearchURLAnalysisResponse, ErrorDetail
from downloader import get_search_query_result
from common.logger_config import configure_logger

configure_logger(filename="app.log", logging_level="INFO")
logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    lock_file = "/tmp/.X99-lock"
    if os.path.exists(lock_file):
        os.remove(lock_file)
        logger.info(f"Removed stale lock file: {lock_file}")
    # 仮想ディスプレイを起動
    xvfb_process = await asyncio.create_subprocess_exec(
        "Xvfb", ":99", "-ac", "-screen", "0", "1920x1080x24"
    )
    yield
    if xvfb_process and xvfb_process.returncode is None:
        try:
            xvfb_process.kill()
            await xvfb_process.wait()
        except Exception as e:
            logger.error(f"Error stopping Xvfb: {e}")
    else:
        logger.warning(
            f"Xvfb process was not started or already terminated. returncode: {xvfb_process.returncode}"
        )


app = FastAPI(lifespan=lifespan)


@app.post("/searchurl/analysis/", response_model=SearchURLAnalysisResponse)
async def generate_search_query(request: Request, suareq: SearchURLAnalysisRequest):
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(
        router_path=request.url.path,
        request_id=str(uuid.uuid4()),
    )
    log = structlog.get_logger(__name__)
    log.info("Received request for search URL analysis", suareq=suareq)
    success, result = await get_search_query_result(suareq)
    log.info(
        "Completed request for search URL analysis",
        success=success,
        result=result.model_dump(),
    )
    return result
