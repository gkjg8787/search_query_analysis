import asyncio
import pathlib
import json

from bs4 import BeautifulSoup
from pydantic import ValidationError
from google import genai
from google.genai import types, errors
import structlog

from models import (
    GeminiSearchBoxResponse,
    NoModelsAvailableError,
    AskGeminiErrorInfo,
    GeminiSearchURLAnalysisResponse,
)
from common.read_config import get_ai_model_list


logger = structlog.get_logger(__name__)


CURRENT_PATH = pathlib.Path(__file__).resolve().parent

DEFAULT_PROMPT_DIR = CURRENT_PATH / "prompts"

MODEL_ESCALATION_LIST = get_ai_model_list().get("gemini", [])


async def get_prompt(filename: str, dir_path: str = DEFAULT_PROMPT_DIR) -> str:
    prompt_path = pathlib.Path(dir_path) / filename
    if not prompt_path.exists():
        return ""
    text = prompt_path.read_text(encoding="utf-8")
    return text


async def _element_to_minimal_dict(element, text_limit: int | None = 10):
    # 抽出対象とするタグのホワイトリスト
    target_tags = {
        "form",
        "div",
        "input",
        "button",
        "select",
        "option",
        "label",
        "a",
        "span",
        "p",
        "section",
    }

    # 基本のタグ名
    res = {"t": element.name}

    # --- 属性の抽出 ---
    attrs = element.attrs
    if "id" in attrs:
        res["i"] = attrs["id"]
    if "class" in attrs:
        res["c"] = (
            ".".join(attrs["class"])
            if isinstance(attrs["class"], list)
            else attrs["class"]
        )

    # 検索機能特定に極めて重要な属性
    if "name" in attrs:
        res["n"] = attrs["name"]
    if "type" in attrs:
        res["tp"] = attrs["type"]
    if "placeholder" in attrs:
        res["ph"] = attrs["placeholder"]
    if "aria-label" in attrs:
        res["al"] = attrs["aria-label"]
    if "role" in attrs:
        res["r"] = attrs["role"]
    if "value" in attrs:
        # option要素やradio/checkboxの場合は値も重要
        res["v"] = attrs["value"][:text_limit] if attrs["value"] else ""

    # リンク・画像（最小限）
    if "href" in attrs:
        res["h"] = attrs["href"]

    # --- 子要素とテキストの処理 ---
    children = []
    for child in element.children:
        if child.name:
            # ターゲットタグ、または子孫にターゲットタグを持つ要素のみ保持
            # (無駄なdivの階層を減らすためのフィルタリング)
            if child.name in target_tags or child.find(list(target_tags)):
                children.append(await _element_to_minimal_dict(child, text_limit))
        elif child.strip():
            text = child.strip()
            if text:
                short_text = (
                    (text[:text_limit] + "..")
                    if text_limit and len(text) > text_limit
                    else text
                )
                children.append(short_text)

    if children:
        res["ch"] = children
    return res


async def html_to_minimal_dict_for_searchbox(
    html: str, text_limit: int | None = 10
) -> dict:
    soup = BeautifulSoup(html, "lxml")

    # 解析に不要なタグを削除
    # ※ header/nav/footerはサイトによって検索窓が含まれるため、
    # 一旦残して要素内のフィルタリングに任せる方が安全です。
    for s in soup(["script", "style", "head", "meta", "link", "noscript", "svg"]):
        s.decompose()

    body = soup.find("body")
    if not body:
        return await _element_to_minimal_dict(soup, text_limit)
    return await _element_to_minimal_dict(body, text_limit)


async def _request_gemini(
    client,
    response_model,
    contents,
):
    for gmodel in MODEL_ESCALATION_LIST:
        # 503などの一時的なエラーのために最大2回リトライ
        for attempt in range(2):
            try:
                response = await client.aio.models.generate_content(
                    model=gmodel,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_json_schema=response_model.model_json_schema(),
                    ),
                )
                return response_model.model_validate_json(response.text)

            except errors.APIError as e:
                # 503 (過負荷) なら、少し待ってリトライ（モデルは変えない）
                if e.code == 503 or "overloaded" in e.message.lower():
                    wait_time = (attempt + 1) * 2  # 2秒, 4秒...と待機
                    logger.warning(
                        f"503 Overloaded: Retrying {gmodel} in {wait_time}s..."
                    )
                    await asyncio.sleep(wait_time)
                    continue

                if e.code == 429:
                    logger.warning(f"Escalte from {gmodel} to the next model")
                    break  # 次のモデルへエスカレーション

                return AskGeminiErrorInfo(error_type=type(e).__name__, error=e.message)
            except ValidationError as e:
                # AIの回答がスキーマに合わなかった場合（ループ、欠落など）
                finish_reasons = []
                for candidate in response.candidates:
                    finish_reason = candidate.finish_reason or "unknown"
                    finish_reasons.append(finish_reason)

                logger.error(
                    f"Schema validation error for model {gmodel}",
                    error_type=type(e).__name__,
                    error=str(e),
                    gemini_response=response.text,
                    finish_reasons=", ".join(finish_reasons),
                    candidates_token_count=response.usage_metadata.candidates_token_count,
                )
                return AskGeminiErrorInfo(
                    error_type="SchemaValidationError", error=str(e)
                )
            except Exception as e:
                return AskGeminiErrorInfo(error_type=type(e).__name__, error=str(e))

    return AskGeminiErrorInfo(
        error_type=NoModelsAvailableError.__name__,
        error="No models available or Escalation limit exceeded.",
    )


async def generate_searchbox_info(
    html: str,
) -> GeminiSearchBoxResponse | AskGeminiErrorInfo:
    minimal_dict = await html_to_minimal_dict_for_searchbox(html)
    prompt_template = await get_prompt("searchbox_extraction_prompt.txt")
    client = genai.Client()
    contents = [
        types.Part.from_text(text=json.dumps(minimal_dict)),
        prompt_template,
    ]
    try:
        response = await _request_gemini(client, GeminiSearchBoxResponse, contents)
        return response
    except Exception as e:
        return AskGeminiErrorInfo(error_type=type(e).__name__, error=str(e))


async def generate_search_query(
    before_search_url: str,
    after_search_url: str,
    searchword: str,
    search_options: dict | None = None,
) -> GeminiSearchURLAnalysisResponse | AskGeminiErrorInfo:
    prompt_template = await get_prompt("search_query_prompt.txt")
    client = genai.Client()
    contents = [
        types.Part.from_text(
            text=f"Before Search URL: {before_search_url}\nAfter Search URL: {after_search_url}\nSearch Word: {searchword}\nSearch Options: {json.dumps(search_options) if search_options else '{}'}"
        ),
        prompt_template,
    ]

    try:
        response = await _request_gemini(
            client, GeminiSearchURLAnalysisResponse, contents
        )
        if isinstance(response, AskGeminiErrorInfo):
            return response
        return response
    except Exception as e:
        return AskGeminiErrorInfo(error_type=type(e).__name__, error=str(e))
