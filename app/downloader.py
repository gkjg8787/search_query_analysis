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
    SearchBoxInfo,
)
from req_gemini import generate_searchbox_info
from category import check_category
from url_analysis import URLPatternLogic
from parser import extract_search_elements
from common.read_config import get_base_dir

COOKIE_PATH = Path("/app/cookie/")
DEFAULT_WAIT_TIME = {
    "first_load": 10,
    "after_search": 10,
}

logger = structlog.get_logger(__name__)
chrome_version_fpath = get_base_dir() / "temp" / "chrome_version.txt"


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


async def get_browser_version():
    if chrome_version_fpath.exists():
        try:
            version = chrome_version_fpath.read_text().strip()
            logger.info(f"Read Chrome version from file: {version}")
            return version
        except Exception as e:
            logger.exception(f"Error reading Chrome version from file: {e}")

    try:
        browser = await uc.start()
        page = await browser.get("about:blank")
        # JavaScriptを実行してUser Agentを取得
        user_agent = await page.evaluate("navigator.userAgent")

        # 正規表現でChromeのバージョン部分を抽出
        match = re.search(r"Chrome/(\d+\.\d+\.\d+\.\d+)", user_agent)
        try:
            v = int(match.group(1))
            chrome_version_fpath.write_text(str(v))
            logger.info(f"Detected Chrome version: {v}")
            return v
        except ValueError:
            logger.exception(
                f"Failed to parse Chrome version from user agent: {match.group(1)}"
            )
            return None
    except Exception as e:
        logger.exception(f"Error detecting Chrome version: {e}")
        return None
    finally:
        browser.stop()
        await asyncio.sleep(1)


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
    browser_args = [
        "--window-size=1920,1080",
        "--start-maximized",
    ]
    if not useragent:
        return await uc.start(browser_args=browser_args)
    chrome_major_version = await get_browser_version()
    if not chrome_major_version:
        chrome_major_version = useragent.major
    ua_os_version = await format_version_regex(useragent.os_version)
    ua_template = (
        f"Mozilla/5.0 (Windows NT {ua_os_version}; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        f"Chrome/{chrome_major_version}.0.0.0 Safari/537.36"
    )
    browser_args.append(f"--user-agent={ua_template}")
    return await uc.start(browser_args=browser_args)


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

    chrome_major_version = await get_browser_version()
    if not chrome_major_version:
        chrome_major_version = useragent.major

    await page.send(
        set_ua_cdp_generator(
            major=chrome_major_version,
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

        # AI
        # ret = await generate_searchbox_info(html_content)
        # searchboxinfo = SearchBoxInfo(
        #     search_input_list=[ret.search_input_box],
        #     search_button_list=ret.search_buttons,
        # )
        # if isinstance(searchboxinfo, AskGeminiErrorInfo):
        #    return False, SearchURLAnalysisResponse(
        #        error=ErrorDetail(
        #            error_type=searchboxinfo.error_type,
        #            error_msg=searchboxinfo.error,
        #          )
        #   )
        ret = await extract_search_elements(html_content)
        searchboxinfo = SearchBoxInfo(
            search_input_list=ret["search_input_list"],
            search_button_list=ret["search_button_list"],
        )
        category_ok, category_data = await check_category(html_content)
        logger.info(
            f"Information extraction from HTML completed",
            category_return=category_ok,
            category_data=category_data,
            generate_searchbox_info_result=searchboxinfo.model_dump(),
        )

        if not searchboxinfo.search_input_list or not searchboxinfo.search_button_list:
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

        for selector in searchboxinfo.search_input_list:
            try:
                searchbox = await page.select(selector)
                break
            except Exception as e:
                logger.warning(
                    f"Failed to find search box with selector '{selector}': {e}"
                )

            if selector == searchboxinfo.search_input_list[-1]:
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
        # selectタグのみ対応
        selected_category = {"value": None, "text": None}
        if category_ok and category_data and category_data.options:
            logger.info(
                f"Category data found, trying to interact with category selection",
                category_data=category_data.model_dump(),
            )
            selected_index = 1

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
                try:
                    select_elem = await page.select(
                        f"select option[value='{selected_category['value']}']"
                    )
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

        for btn_selector in searchboxinfo.search_button_list:
            try:
                search_btn = await page.select(btn_selector)
                await search_btn.mouse_click()
                logger.info(
                    f"Clicked search button successfully", btn_selector=btn_selector
                )
                break
            except Exception as e:
                logger.warning(
                    f"Failed to click search button",
                    btn_selector=btn_selector,
                    error=str(e),
                )
                if btn_selector == searchboxinfo.search_button_list[-1]:
                    logger.exception(
                        f"Failed to find or interact with any of the search buttons: {searchboxinfo.search_buttons}"
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
        if selected_category["value"]:
            category_val = selected_category["value"]
        else:
            category_val = ""
        url_analysis = URLPatternLogic(
            target_url=after_search_url,
            keyword=search_keyword,
            category_val=category_val,
        ).analyze()

        logger.debug(f"url_analysis : {url_analysis.model_dump()}")

        result = SearchURLAnalysisResponse(
            url_info=url_analysis,
        )
        if category_ok and category_data:
            result.categories = category_data

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
