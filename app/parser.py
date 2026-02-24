from typing import Optional
import re

from bs4 import BeautifulSoup
from pydantic import BaseModel

from models import SelectData, OptionData


def _is_display_none(elem):
    style = elem.get("style", "")
    if not style:
        return False

    # パターンの解説:
    # display      : "display" という文字
    # \s*:\s* : 前後に空白があってもなくても良い ":"
    # none         : "none" という文字
    # (?=;|$)      : 直後に ";" が来るか、文字列の終端であることを確認（先読み）
    pattern = r"display\s*:\s*none(?=\s*;|$)"

    return bool(re.search(pattern, style, re.IGNORECASE))


def extract_select_options(html_content: str) -> list[SelectData]:
    soup = BeautifulSoup(html_content, "lxml")
    results = []

    # 全ての select タグをループ
    for select in soup.find_all("select"):
        # オプション群の抽出
        options = [
            OptionData(value=opt.get("value"), text=opt.get_text(strip=True))
            for opt in select.find_all("option")
        ]

        # セレクトボックス情報の抽出
        select_info = SelectData(
            id=select.get("id"),
            name=select.get("name"),
            class_list=select.get("class", []),  # bs4のclassはデフォルトでリスト形式
            options=options,
            displayed=not select.has_attr("hidden") and not _is_display_none(select),
        )
        results.append(select_info)

    return results


def _generate_css_selector(tag) -> Optional[str]:
    if tag.get("id"):
        return f"#{tag['id']}"
    if tag.get("name"):
        return f"{tag.name}[name='{tag['name']}']"

    cls = tag.get("class")
    if cls:
        if isinstance(cls, list):
            valid_cls = [c for c in cls if c.strip()]
            if valid_cls:
                return f"{tag.name}.{'.'.join(valid_cls)}"
        elif cls.strip():
            return f"{tag.name}.{cls}"

    for attr in ["placeholder", "aria-label", "role", "type", "title", "value", "alt"]:
        if tag.get(attr):
            return f"{tag.name}[{attr}='{tag[attr]}']"

    if tag.name == "a" and tag.get("href"):
        href = tag.get("href").strip()
        if href and not href.startswith("javascript:") and href != "#":
            return f"{tag.name}[href='{href}']"

    return None


async def extract_search_elements(html_content: str) -> dict[str, list[str]]:
    soup = BeautifulSoup(html_content, "lxml")

    # --- Search Input Candidates ---
    inputs = soup.find_all("input")
    input_candidates = []

    for tag in inputs:
        score = 0
        attrs = tag.attrs
        t = attrs.get("type", "text").lower()

        if t not in ["text", "search"]:
            continue

        if t == "search":
            score += 10

        name = attrs.get("name", "").lower()
        if name in ["q", "s", "k", "key", "keyword", "query", "text"]:
            score += 10
        elif "search" in name:
            score += 5

        id_val = attrs.get("id", "").lower()
        if "search" in id_val:
            score += 5

        raw_class = attrs.get("class", [])
        if isinstance(raw_class, list):
            class_val = " ".join(raw_class).lower()
        else:
            class_val = str(raw_class).lower()

        if "search" in class_val:
            score += 3

        placeholder = attrs.get("placeholder", "").lower()
        if "search" in placeholder or "検索" in placeholder:
            score += 5

        aria_label = attrs.get("aria-label", "").lower()
        if "search" in aria_label or "検索" in aria_label:
            score += 5

        if score > 0:
            input_candidates.append((score, tag))

    input_candidates.sort(key=lambda x: x[0], reverse=True)
    search_input_set = set()
    for _, tag in input_candidates:
        sel = _generate_css_selector(tag)
        if sel:
            search_input_set.add(sel)
            if len(search_input_set) >= 3:
                break

    # --- Search Button Candidates ---
    buttons = soup.find_all(["button", "input"])
    button_candidates = []

    for tag in buttons:
        score = 0
        attrs = tag.attrs
        name = tag.name.lower()
        t = attrs.get("type", "").lower()

        if name == "input" and t not in ["submit", "button", "image"]:
            continue

        text = tag.get_text(" ", strip=True).lower()
        if "search" in text or "検索" in text:
            score += 10
        if "go" == text:
            score += 2

        if t == "submit":
            score += 3

        id_val = attrs.get("id", "").lower()
        if "search" in id_val or "submit" in id_val:
            score += 5

        raw_class = attrs.get("class", [])
        if isinstance(raw_class, list):
            class_val = " ".join(raw_class).lower()
        else:
            class_val = str(raw_class).lower()

        if "search" in class_val or "submit" in class_val or "btn" in class_val:
            score += 2

        aria_label = attrs.get("aria-label", "").lower()
        if "search" in aria_label or "検索" in aria_label:
            score += 10

        title = attrs.get("title", "").lower()
        if "search" in title or "検索" in title:
            score += 10

        if name == "button":
            inner_html = str(tag).lower()
            if (
                "fa-search" in inner_html
                or "icon-search" in inner_html
                or "search-icon" in inner_html
            ):
                score += 5

        if score > 0:
            button_candidates.append((score, tag))

    button_candidates.sort(key=lambda x: x[0], reverse=True)
    search_button_set = set()
    for _, tag in button_candidates:
        sel = _generate_css_selector(tag)
        if sel:
            search_button_set.add(sel)
            if len(search_button_set) >= 3:
                break

    return {
        "search_input_list": list(search_input_set),
        "search_button_list": list(search_button_set),
    }
