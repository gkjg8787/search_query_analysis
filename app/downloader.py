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
    GeminiSearchBoxResponse,
    SearchURLInfo,
)
from req_gemini import generate_searchbox_info, generate_search_query


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


async def dl_with_nodriver(req: SearchURLAnalysisRequest):
    logger.debug(f"input_params : {req.model_dump()}")
    browser = None
    page = None
    try:
        browser = await _get_browser_with_ua(req.useragent)
        page = await _get_page_with_ua(browser, req.useragent)
        page = await page.get(req.url)

        if req.cookie:
            if req.cookie.load:
                try:
                    cookie_fpath = await get_cookie_filepath(
                        filename=req.cookie.filename, url=req.url
                    )
                    await browser.cookies.load(cookie_fpath)
                except Exception as e:
                    logger.error(f"Error loading cookies from file: {e}")

            if req.cookie.cookie_dict_list:
                br_cookies = await _cookie_to_param(await browser.cookies.get_all())
                included_cookies = await _add_cookies(
                    add_cookies=req.cookie.cookie_dict_list, base_cookies=br_cookies
                )
                await _set_cookies(browser.cookies, included_cookies)

            if req.cookie.load or req.cookie.cookie_dict_list:
                await page.reload()

        if req.wait_css_selector:
            try:
                await _wait_css_selector(page, req.wait_css_selector)
            except Exception as e:
                logger.error(f"Error waiting for CSS selector: {e}")
                return False, e, []
        elif req.page_wait_time:
            await asyncio.sleep(req.page_wait_time)

        html_content = await page.get_content()
        cookies = []
        if req.cookie and req.cookie.save:
            try:
                cookie_fpath = await get_cookie_filepath(
                    filename=req.cookie.filename, url=req.url
                )
                await browser.cookies.save(cookie_fpath)
            except Exception as e:
                logger.error(f"Error saving cookies to file: {e}")

        if req.cookie and req.cookie.return_cookies:
            uc_cookies = await browser.cookies.get_all()
            cookies = [c.to_json() for c in uc_cookies]

        return True, html_content, cookies

    except Exception as e:
        logger.exception("other error")
        return False, e, []
    finally:
        if page:
            try:
                await page.close()
            except Exception:
                logger.exception("page close error")
        if browser:
            try:
                browser.stop()
            except Exception:
                logger.exception("browser stop error")


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
        logger.info(
            f"generate_searchbox_info_result : {generate_searchbox_info_result.model_dump()}"
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
            or not generate_searchbox_info_result.search_button
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
        try:
            search_btn = await page.select(generate_searchbox_info_result.search_button)
            await search_btn.mouse_click()
        except Exception as e:
            logger.exception(f"Failed to click search button: {e}")
            return False, SearchURLAnalysisResponse(
                error=ErrorDetail(
                    error_type=f"SearchButtonInteractionError: {type(e).__name__}",
                    error_msg=f"Failed to find or interact with search button: {e}",
                )
            )

        await asyncio.sleep(DEFAULT_WAIT_TIME["after_search"])

        search_content = await page.get_content()

        input_search_options = (
            generate_searchbox_info_result.search_options.model_dump()
            if generate_searchbox_info_result.search_options
            else None
        )
        if req.analysis_scope == "all":
            after_generate_searchbox_info_result = await generate_searchbox_info(
                search_content
            )
            logger.debug(
                f"after_generate_searchbox_info_result : {after_generate_searchbox_info_result.model_dump()}"
            )
            if (
                isinstance(
                    after_generate_searchbox_info_result, GeminiSearchBoxResponse
                )
                and after_generate_searchbox_info_result.search_options
            ):
                if input_search_options:
                    # 入力前の検索オプションと、検索後の検索オプションをマージして、検索クエリ生成に渡す
                    if (
                        input_search_options["category"]
                        and after_generate_searchbox_info_result.search_options.category
                        and input_search_options["category"]["tag_type"]
                        == after_generate_searchbox_info_result.search_options.category.tag_type
                        and input_search_options["category"]["query_name"]
                        == after_generate_searchbox_info_result.search_options.category.query_name
                    ):
                        # カテゴリーが両方にある場合は、検索後のカテゴリー情報を優先する
                        input_search_options["category"] = (
                            after_generate_searchbox_info_result.search_options.category.model_dump()
                        )
                        logger.info(
                            "Search options category matched between before and after search, using after search options",
                            category=input_search_options["category"],
                        )
                    else:
                        logger.warning(
                            "Search options category mismatch between before and after search, using before search options",
                            before_category=input_search_options.get("category"),
                            after_category=after_generate_searchbox_info_result.search_options.category.model_dump(),
                        )
                else:
                    input_search_options = (
                        after_generate_searchbox_info_result.search_options.model_dump()
                    )
                    logger.info(
                        "Search options category matched between before and after search, using after search options",
                        category=input_search_options["category"],
                    )

        after_search_url = page.url
        search_query_res = await generate_search_query(
            before_search_url=top_page_url,
            after_search_url=after_search_url,
            searchword=search_keyword,
            search_options=input_search_options,
        )
        if isinstance(search_query_res, AskGeminiErrorInfo):
            return False, SearchURLAnalysisResponse(
                error=ErrorDetail(
                    error_type=search_query_res.error_type,
                    error_msg=search_query_res.error,
                )
            )

        logger.debug(f"search_query_res : {search_query_res.model_dump()}")
        if not search_query_res.search_url_type == "query":
            return (
                False,
                SearchURLAnalysisResponse(
                    error=ErrorDetail(
                        error_type="SearchQueryAnalysisError",
                        error_msg=f"The search URL type is not 'query', cannot extract search query information , search_url_type: {search_query_res.search_url_type}",
                    )
                ),
            )
        result = SearchURLAnalysisResponse(
            url_info=SearchURLInfo(
                site_top_url=search_query_res.site_top_url,
                search_dir=search_query_res.search_dir,
                search_url_type=search_query_res.search_url_type,
                search_query=search_query_res.query_param,
                search_fixed_query=search_query_res.search_fixed_query,
                query_options=search_query_res.query_options,
                encoding=search_query_res.encoding,
            ),
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
