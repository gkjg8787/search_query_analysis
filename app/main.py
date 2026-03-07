import os
import asyncio
from contextlib import asynccontextmanager
import uuid

from fastapi import FastAPI, Request
import structlog

from models import (
    SearchURLProbeRequest,
    SearchURLProbeResponse,
    ErrorDetail,
    GenerateSearchURLResponse,
    GenerateSearchURLRequest,
    SearchURLAnalysisRequest,
    SearchURLAnalysisResponse,
    DownloadResponse,
    DownloadRequest,
)
from downloader import get_search_query_result, dl_with_nodriver
from common.logger_config import configure_logger
from url_analysis import build_url, URLPatternLogic

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


@app.post(
    "/searchurl/analysis",
    response_model=SearchURLAnalysisResponse,
    response_model_exclude_none=True,
)
async def analyze_search_url(request: Request, req: SearchURLAnalysisRequest):
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(
        outer_path=request.url.path,
        request_id=str(uuid.uuid4()),
    )
    log = structlog.get_logger(__name__)
    log.info("Received request for search URL analysis", req=req)
    url_analysis = URLPatternLogic(
        target_url=req.url,
        keyword=req.search_word,
        category_val=req.category_value,
    ).analyze()
    log.info("Completed request for search URL analysis", url_analysis=url_analysis)
    return SearchURLAnalysisResponse(url_info=url_analysis)


@app.post(
    "/searchurl/probe",
    response_model=SearchURLProbeResponse,
    response_model_exclude_none=True,
)
async def generate_search_query(request: Request, suareq: SearchURLProbeRequest):
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(
        router_path=request.url.path,
        request_id=str(uuid.uuid4()),
    )
    log = structlog.get_logger(__name__)
    log.info("Received request for search URL probe", suareq=suareq)
    success, result = await get_search_query_result(suareq)
    log.info(
        "Completed request for search URL probe",
        success=success,
        result=result.model_dump(),
    )
    return result


@app.post("/searchurl/generate", response_model=GenerateSearchURLResponse)
async def generate_search_url(request: Request, req: GenerateSearchURLRequest):
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(
        router_path=request.url.path,
        request_id=str(uuid.uuid4()),
    )
    log = structlog.get_logger(__name__)
    log.info("Received request for search URL generation", req=req)

    url = build_url(
        req.url_info, req.search_keyword, req.category_value, req.category_name
    )
    log.info("Completed request for search URL generation", url=url)
    return GenerateSearchURLResponse(url=url)


@app.post("/download", response_model=DownloadResponse)
async def download_html(request: DownloadRequest):
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(
        router_path=request.url.path,
        request_id=str(uuid.uuid4()),
    )
    log = structlog.get_logger(__name__)
    log.info("Received request for download", req=request)

    success, result, cookies = await dl_with_nodriver(request)

    if success:
        log.info("Completed request for download")
        return DownloadResponse(result=result, cookies=cookies)
    else:
        error_details = ErrorDetail(
            error_msg=str(result), error_type=type(result).__name__
        )
        return DownloadResponse(error=error_details)
