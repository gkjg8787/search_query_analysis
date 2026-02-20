import asyncio
from pathlib import Path
from urllib.parse import urlparse
import re


import nodriver as uc
import structlog

from models import (
    SearchURLAnalysisRequest,
    ErrorDetail,
    WaitCSSSelector,
    AskGeminiErrorInfo,
    SearchURLAnalysisResponse,
    URLAnalysisModel,
)
from req_gemini import generate_searchbox_info, generate_search_query
from category import check_category
from url_analysis import URLPatternLogic

COOKIE_PATH = Path("/app/cookie/")
DEFAULT_WAIT_TIME = {
    "first_load": 10,
    "after_search": 10,
}

logger = structlog.get_logger(__name__)


async def _cookie_to_param(
    cookies: list[uc.cdp.network.Cookie],
) -> list[uc.cdp.network.CookieParam]:
    if not cookies:
        return []
    return [uc.cdp.network.CookieParam.from_json(c.to_json()) for c in cookies if c]


async def _add_cookies(
    add_cookies: list[uc.cdp.util.T_JSON_DICT],
    base_cookies: list[uc.cdp.network.CookieParam],
):
    if not add_cookies:
        return base_cookies
    results = [c for c in base_cookies]
    for c in add_cookies:
        results.append(uc.cdp.network.CookieParam.from_json(c))
    return results


async def _set_cookies(
    cookiejar: uc.core.browser.CookieJar, cookies: list[uc.cdp.network.CookieParam]
):
    connection = None
    for tab in cookiejar._browser.tabs:
        if tab.closed:
            continue
        connection = tab
        break
    else:
        connection = cookiejar._browser.connection
    await connection.send(uc.cdp.storage.set_cookies(cookies))


async def _wait_css_selector(page, selector: WaitCSSSelector):
    if selector.pre_wait_time and selector.pre_wait_time > 0:
        await asyncio.sleep(selector.pre_wait_time)
    if selector.on_error:
        max_retry = (
            selector.on_error.max_retries
            if selector.on_error.max_retries and selector.on_error.max_retries > 0
            else 1
        )
    else:
        max_retry = 1
    for retry_count in range(max_retry):
        try:
            await page.wait_for(
                selector=selector.selector,
                timeout=selector.timeout,
            )
            return
        except Exception as e:
            logger.warning(
                f"Waiting for selector '{selector.selector}' failed: {e}, retry_count={retry_count}"
            )
            if retry_count >= max_retry - 1:
                logger.error(
                    f"Max retries reached for selector '{selector.selector}', retry_count={retry_count}"
                )
                raise e
            if selector.on_error.action_type == "raise":
                logger.error(
                    f"Raising error for selector '{selector.selector}' as per on_error action"
                )
                raise e
            elif selector.on_error.action_type == "retry":
                wait_time = (
                    selector.on_error.wait_time
                    if selector.on_error.wait_time and selector.on_error.wait_time > 0
                    else 0
                )
                if wait_time > 0 and selector.on_error.check_exist_tag:
                    elem = await page.select(
                        selector.on_error.check_exist_tag, timeout=wait_time
                    )
                    if elem is None:
                        logger.error(
                            f"Check exist tag '{selector.on_error.check_exist_tag}' not found, raising error"
                        )
                        raise e
                    if elem:
                        logger.info(
                            f"Check exist tag '{selector.on_error.check_exist_tag}' found, stopping retries"
                        )
                        return
                    logger.warning(
                        f"Check exist tag '{selector.on_error.check_exist_tag}' not found, continuing retries"
                    )
                    continue
                logger.info(
                    f"Retrying to wait for selector '{selector.selector}', retry_count={retry_count + 1}"
                )
                continue
            else:
                logger.error(
                    f"Unknown on_error action_type '{selector.on_error.action_type}' for selector '{selector.selector}'"
                )
                raise e


async def get_domain_from_url(url: str) -> str:
    parsed_url = urlparse(url)
    return parsed_url.netloc


async def get_cookie_filepath(filename: str, url: str) -> Path:
    if filename:
        return COOKIE_PATH / filename
    domain = await get_domain_from_url(url)
    return COOKIE_PATH / f"{domain}_cookies.dat"


async def format_version_regex(version):
    # 「(数字.数字) の後の .0」を探して、前のグループ部分だけに置換する
    return re.sub(r"^(\d+\.\d+)\.0$", r"\1", version)


async def _get_browser_with_ua(useragent):
    if not useragent:
        return await uc.start()
    ua_os_version = await format_version_regex(useragent.os_version)
    ua_template = (
        f"Mozilla/5.0 (Windows NT {ua_os_version}; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        f"Chrome/{useragent.major}.0.0.0 Safari/537.36"
    )
    return await uc.start(browser_args=[f"--user-agent={ua_template}"])


async def _get_page_with_ua(browser, useragent):
    if not useragent:
        return await browser.get("about:blank")
    page = await browser.get("about:blank")

    def set_ua_cdp_generator(major, platform, os_version, ua_os_version):
        yield {
            "method": "Network.setUserAgentOverride",
            "params": {
                "userAgent": (
                    f"Mozilla/5.0 (Windows NT {ua_os_version}; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    f"Chrome/{major}.0.0.0 Safari/537.36"
                ),
                "platform": platform,
                "userAgentMetadata": {
                    "brands": [
                        {"brand": "Chromium", "version": f"{major}"},
                        {"brand": "Google Chrome", "version": f"{major}"},
                        {"brand": "Not=A?Brand", "version": "24"},
                    ],
                    "platform": platform,
                    "platformVersion": os_version,
                    "architecture": "x86",
                    "model": "",
                    "mobile": False,
                },
            },
        }

    await page.send(
        set_ua_cdp_generator(
            major=useragent.major,
            platform=useragent.platform,
            os_version=useragent.os_version,
            ua_os_version=await format_version_regex(useragent.os_version),
        )
    )
    return page


async def get_search_query_result(req: SearchURLAnalysisRequest):
    logger.debug(f"input_params : {req.model_dump()}")
    browser = None
    page = None
    try:
        browser = await _get_browser_with_ua(req.useragent)
        page = await _get_page_with_ua(browser, req.useragent)
        top_page_url = urlparse(req.url)._replace(query="", fragment="").geturl()
        page = await page.get(top_page_url)

        if req.cookie:
            if req.cookie.load:
                try:
                    cookie_fpath = await get_cookie_filepath(
                        filename=req.cookie.filename, url=req.url
                    )
                    await browser.cookies.load(cookie_fpath)
                except Exception as e:
                    logger.exception(f"Error loading cookies from file: {e}")

            if req.cookie.cookie_dict_list:
                br_cookies = await _cookie_to_param(await browser.cookies.get_all())
                included_cookies = await _add_cookies(
                    add_cookies=req.cookie.cookie_dict_list, base_cookies=br_cookies
                )
                await _set_cookies(browser.cookies, included_cookies)

            if req.cookie.load or req.cookie.cookie_dict_list:
                await page.reload()

        if req.page_wait_time and req.page_wait_time > 0:
            await asyncio.sleep(req.page_wait_time)
        else:
            await asyncio.sleep(DEFAULT_WAIT_TIME["first_load"])

        html_content = await page.get_content()

        if not html_content:
            return False, SearchURLAnalysisResponse(
                error=ErrorDetail(
                    error_type="NoContentError",
                    error_msg="Failed to retrieve HTML content from the page",
                )
            )

        if req.cookie and req.cookie.save:
            try:
                cookie_fpath = await get_cookie_filepath(
                    filename=req.cookie.filename, url=req.url
                )
                await browser.cookies.save(cookie_fpath)
            except Exception as e:
                logger.exception(f"Error saving cookies to file: {e}")

        generate_searchbox_info_result = await generate_searchbox_info(html_content)
        category_ok, category_data = await check_category(html_content)
        logger.info(
            f"Information extraction from HTML completed",
            category_return=category_ok,
            category_data=category_data,
            generate_searchbox_info_result=generate_searchbox_info_result.model_dump(),
        )
        if isinstance(generate_searchbox_info_result, AskGeminiErrorInfo):
            return False, SearchURLAnalysisResponse(
                error=ErrorDetail(
                    error_type=generate_searchbox_info_result.error_type,
                    error_msg=generate_searchbox_info_result.error,
                )
            )
        if (
            not generate_searchbox_info_result.search_input_box
            or not generate_searchbox_info_result.search_buttons
        ):
            return (
                False,
                SearchURLAnalysisResponse(
                    error=ErrorDetail(
                        error_type="SearchBoxInfoError",
                        error_msg="Failed to extract search box information from the page",
                    )
                ),
            )

        # start search and get url
        try:
            searchbox = await page.select(
                generate_searchbox_info_result.search_input_box
            )

        except Exception as e:
            logger.exception(f"Failed to find or interact with search box: {e}")
            return False, SearchURLAnalysisResponse(
                error=ErrorDetail(
                    error_type=f"SearchBoxInteractionError: {type(e).__name__}",
                    error_msg=f"Failed to find or interact with search box: {e}",
                )
            )

        search_keyword = req.search_word or "ポケモン"
        await searchbox.send_keys(search_keyword)
        active_element_info = await page.evaluate(
            "document.activeElement.tagName + ' #' + document.activeElement.id + ' .' + document.activeElement.className"
        )
        logger.debug(
            f"searchword: {search_keyword}, Active element info: {active_element_info}"
        )

        # category のセレクトボックスがあれば選択してみる
        selected_category = {"value": None, "text": None}
        if category_ok and category_data:
            logger.info(
                f"Category data found, trying to interact with category selection",
                category_data=category_data.model_dump(),
            )
            selected_index = 0  # TODO: 現状はマッチした最初のカテゴリーを選択する実装だが、将来的には複数マッチした場合の選択方法も検討する必要がある
            selected_category["value"] = category_data.options[selected_index].value
            selected_category["text"] = category_data.options[selected_index].text
            if category_data.id or category_data.name:
                if category_data.id:
                    selector = f"select#{category_data.id}"
                elif category_data.name:
                    selector = f"select[name='{category_data.name}']"
                selector += f" option[value='{selected_category['value']}']"
                try:
                    select_elem = await page.select(selector)
                    await select_elem.select_option()
                    logger.info(
                        f"Interacted with category select element successfully",
                        selector=selector,
                        selected_category=selected_category,
                    )
                except Exception as e:
                    logger.warning(
                        f"Failed to interact with category select element: {e}",
                        selector=selector,
                    )
            elif category_data.class_list:
                for class_name in category_data.class_list:
                    selector = f"select.{class_name}"
                    selector += f" option[value='{selected_category['value']}']"
                    try:
                        select_elem = await page.select(selector)
                        await select_elem.select_option()
                        logger.info(
                            f"Interacted with category select element successfully",
                            selector=selector,
                            selected_category=selected_category,
                        )
                        break
                    except Exception as e:
                        logger.warning(
                            f"Failed to interact with category select element: {e}",
                            selector=selector,
                        )
                        continue
            else:
                logger.warning(
                    f"Unsupported category tag type for interaction",
                    selected_category=selected_category,
                )
                # ここではセレクトボックス以外のパターンは未対応とする

        for btn_selector in generate_searchbox_info_result.search_buttons:
            try:
                search_btn = await page.select(btn_selector)
                await search_btn.mouse_click()
                break
            except Exception as e:
                logger.warning(
                    f"Failed to click search button",
                    btn_selector=btn_selector,
                    error=str(e),
                )
                if btn_selector == generate_searchbox_info_result.search_buttons[-1]:
                    logger.exception(
                        f"Failed to find or interact with any of the search buttons: {generate_searchbox_info_result.search_buttons}"
                    )
                    return False, SearchURLAnalysisResponse(
                        error=ErrorDetail(
                            error_type=f"SearchButtonInteractionError: {type(e).__name__}",
                            error_msg=f"Failed to find or interact with search button: {e}",
                        )
                    )
                continue

        await asyncio.sleep(DEFAULT_WAIT_TIME["after_search"])

        search_content = await page.get_content()

        after_search_url = page.url
        url_analysis = URLPatternLogic(
            target_url=after_search_url, keyword=search_keyword, category_val=""
        ).analyze()

        logger.debug(f"url_analysis : {url_analysis.model_dump()}")

        result = SearchURLAnalysisResponse(
            url_info=url_analysis,
        )

        return True, result

    except Exception as e:
        logger.exception("other error")
        return False, SearchURLAnalysisResponse(
            error=ErrorDetail(
                error_type=type(e).__name__,
                error_msg=str(e),
            )
        )
    finally:
        if browser:
            try:
                browser.stop()
            except Exception:
                logger.exception("browser stop error")
