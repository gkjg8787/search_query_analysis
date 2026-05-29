from typing import Literal
import re

from bs4 import BeautifulSoup, Tag
from pydantic import BaseModel

from models import SelectData, OptionData, CustomSelectData
from common.read_config import MatchRule, get_extract_category_options


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


def _analyze_visibility(elem):
    """
    静的な情報から、その要素が「現在隠されているか」
    および「動的に表示されるものか」を判定する
    """
    findings = {"is_hidden": False, "is_dynamic": False, "reason": ""}

    curr = elem
    while curr and curr.name not in [None, "html", "body"]:
        style = curr.get("style", "").lower()
        classes = " ".join(curr.get("class", [])).lower()

        # 1. display:none の直接検知
        if "display:none" in style.replace(" ", ""):
            findings["is_hidden"] = True
            findings["is_dynamic"] = True  # style属性で制御されている＝動的な可能性大
            findings["reason"] = f"style in <{curr.name}>"
            return findings

        # 2. aria属性による開閉状態の検知
        if curr.get("aria-expanded") == "false" or curr.get("aria-hidden") == "true":
            findings["is_hidden"] = True
            findings["is_dynamic"] = True
            findings["reason"] = "aria-attributes"
            return findings

        # 3. クラス名による推測 (よくある動的UIのクラス)
        if any(word in classes for word in ["modal", "dropdown", "popup", "hidden"]):
            findings["is_dynamic"] = True

        curr = curr.parent

    return findings


def _is_visible(element):
    """
    要素単体が非表示設定になっているか判定する
    """
    if not isinstance(element, Tag):
        return True

    # 1. style属性のチェック
    style = element.get("style", "").lower()
    if "display:none" in style.replace(" ", "") or "visibility:hidden" in style.replace(
        " ", ""
    ):
        return False

    # 2. HTML5 hidden属性
    if element.has_attr("hidden"):
        return False

    # 3. ARIA属性 (非表示・折りたたみ)
    if element.get("aria-hidden") == "true":
        return False
    if element.get("aria-expanded") == "false":
        return False

    return True


def find_first_visible_ancestor(element):
    """
    要素から親へ遡り、自身も含めて「完全に表示されている」最初のタグを返す
    """
    curr = element

    while curr and curr.name != "[document]":
        # 現在の要素からルートまで遡り、途中に非表示要素がないか確認
        is_effectively_visible = True
        temp_curr = curr

        # 先祖をすべてチェックして、一つでも非表示があればその要素は「非表示」とみなす
        while temp_curr and temp_curr.name != "[document]":
            if not _is_visible(temp_curr):
                is_effectively_visible = False
                break
            temp_curr = temp_curr.parent

        # もしこの要素（とその先祖）がすべて表示なら、これを返す
        if is_effectively_visible:
            return curr

        # そうでなければ一つ上の親へ移動して再試行
        curr = curr.parent

    return None


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
            visible=not select.has_attr("hidden") and not _is_display_none(select),
        )
        results.append(select_info)

    return results


async def extract_search_button(html_content: str, search_input_selector: str = ""):
    soup = BeautifulSoup(html_content, "lxml")

    # ==========================================================
    # 【修正・最適化】入力欄セレクタがある場合の周辺要素ピンポイント探索
    # ==========================================================
    if search_input_selector:
        try:
            target_input = soup.select_one(search_input_selector)
        except Exception:
            target_input = None

        if target_input:
            proximity_candidates = []

            # 探索範囲: 入力欄の親、および「親の親（formや共通divなど）」の配下
            lookup_parents = []
            p = target_input.parent
            if p:
                lookup_parents.append(p)
                if p.parent:
                    lookup_parents.append(p.parent)
                    # 楽天のようにformの外にハミ出しているケースを考慮し、もう1階層上までカバー
                    if p.parent.parent:
                        lookup_parents.append(p.parent.parent)

            # 周辺の特定のタグだけを収集
            local_elements = []
            for parent_node in lookup_parents:
                for t in parent_node.find_all(
                    ["a", "button", "input", "div", "svg"], recursive=True
                ):
                    if t != target_input and t not in local_elements:
                        local_elements.append(t)

            for tag in local_elements:
                score = 0
                name = tag.name.lower()

                # クラス名や属性の取得
                def get_attr_str_local(t, attr_name):
                    val = t.attrs.get(attr_name, "")
                    return " ".join(val) if isinstance(val, list) else str(val)

                attr_all = (
                    get_attr_str_local(tag, "id")
                    + " "
                    + get_attr_str_local(tag, "class")
                    + " "
                    + get_attr_str_local(tag, "name")
                )
                attr_all_lower = attr_all.lower()

                # --------------------------------------------------
                # 強力な除外フィルタ（クリアボタン、サジェスト、履歴の排除）
                # --------------------------------------------------
                # 文字列、属性、IDなどからノイズ要素を徹底排除
                text_val = tag.get_text(" ", strip=True).lower()
                aria_val = get_attr_str_local(tag, "aria-label").lower()
                alt_val = get_attr_str_local(tag, "alt").lower()
                combined_text = text_val + " " + aria_val + " " + alt_val

                # テキスト消去ボタン、サジェスト、履歴、非表示要素は即除外(スコアをマイナスに)
                if re.search(
                    r"(clear|iss-attach|history|suggest|popup|dialog|hidden|close|×|消去|クリア)",
                    attr_all_lower + " " + combined_text,
                ):
                    continue

                # --------------------------------------------------
                # スコアリング（キーワード・属性による判定）
                # --------------------------------------------------
                # 1. 検索専用の強力なキーワード (最優先)
                if re.search(
                    r"(js_keywordsearchbtn|srcbtn|submit|search_btn|search_icon|search-button)",
                    attr_all_lower,
                ):
                    score += 70
                # 汎用的な検索キーワード
                elif re.search(r"(search|src|btn|button|find)", attr_all_lower):
                    score += 35

                # 2. タグの種類と属性
                if name == "input" and tag.attrs.get("type", "").lower() in [
                    "submit",
                    "image",
                ]:
                    score += 50
                elif name == "button":
                    score += 45
                elif name == "a":
                    score += 30

                # 3. テキストやaria-label、alt（「検索」の文字や虫眼鏡）
                if any(k in combined_text for k in ["search", "検索", "探す"]):
                    score += 40

                # 4. 構造的トポロジー（親要素の共有度合い）
                input_parent = target_input.parent
                tag_parent = tag.parent

                if input_parent == tag_parent:
                    score += 30  # 完全に同じ直近の親
                elif target_input.find_parent("form") and target_input.find_parent(
                    "form"
                ) == tag.find_parent("form"):
                    score += 25  # 同じform内

                # 子要素にボタンを持つdivは、div自身ではなく中身が正解なので減点
                if name == "div" and tag.find(["button", "input", "a"]):
                    score -= 30

                # 最低限、検索ボタンとしてのシグナル（キーワード等）があるものだけを対象にする
                if score > 40:
                    proximity_candidates.append((score, tag))

            if proximity_candidates:
                return finalize(proximity_candidates, soup)

    # ==========================================================
    # 【既存ロジック】入力欄がない、または見つからない場合のフォールバック（全件走査）
    # ==========================================================
    def get_attr_str(tag, attr_name):
        val = tag.attrs.get(attr_name, "")
        return " ".join(val).lower() if isinstance(val, list) else str(val).lower()

    elements = soup.find_all(["input", "button", "a", "div", "svg"])
    button_candidates = []

    for tag in elements:
        score = 0
        name = tag.name.lower()
        attr_all = (
            get_attr_str(tag, "id")
            + " "
            + get_attr_str(tag, "class")
            + " "
            + get_attr_str(tag, "name")
        )

        if re.search(
            r"(js_keywordsearchbtn|srcbtn|submit|search_btn|search_icon|search-button)",
            attr_all,
        ):
            score += 70

        if name == "input" and tag.attrs.get("type", "").lower() in [
            "submit",
            "image",
        ]:
            score += 40
        elif name == "button":
            score += 35

        text_val = tag.get_text(" ", strip=True).lower()
        aria_val = get_attr_str(tag, "aria-label")
        alt_val = get_attr_str(tag, "alt")
        if any(
            k in (text_val + aria_val + alt_val) for k in ["search", "検索", "探す"]
        ):
            score += 40

        curr = tag.parent
        depth = 0
        is_in_header = False
        is_in_excluded_area = False
        while curr and depth < 5:
            p_attr = (
                get_attr_str(curr, "id") + " " + get_attr_str(curr, "class")
            ).lower()
            if "header" in curr.name or "header" in p_attr:
                is_in_header = True
            if any(k in p_attr for k in ["sidebar", "side-nav", "modal", "filter"]):
                is_in_excluded_area = True
                break
            curr = curr.parent
            depth += 1

        if is_in_header:
            score += 30
        if is_in_excluded_area:
            score -= 50
        if name == "div" and tag.find(["button", "input"]):
            score -= 30
        if tag.find_parent("form"):
            score += 20

        if score > 30:
            button_candidates.append((score, tag))

    return finalize(button_candidates, soup)


def finalize(candidates, soup, limit=5):
    candidates.sort(key=lambda x: x[0], reverse=True)
    unique_sels = []
    seen = set()
    for _, tag in candidates:
        try:
            sel = _generate_css_selector(tag, soup)
            if sel and sel not in seen:
                seen.add(sel)
                unique_sels.append(sel)
            if len(unique_sels) >= limit:
                break
        except:
            continue
    return unique_sels


async def extract_search_input_text(
    html_content: str,
):
    soup = BeautifulSoup(html_content, "lxml")

    def get_attr_str(tag, attr_name):
        val = tag.attrs.get(attr_name, "")
        return " ".join(val).lower() if isinstance(val, list) else str(val).lower()

    # --- Search Input Candidates ---
    all_inputs = soup.find_all(["input", "textarea"])
    input_candidates = []

    for tag in all_inputs:
        score = 0
        attrs = tag.attrs
        t = attrs.get("type", "text").lower()

        # 除外：hidden は絶対だが、それ以外はスコアで判断
        if t == "hidden":
            continue

        # A. 属性の強力一致 (ヨドバシ: getJsonData / 楽天: sitem / ヤフショ: inputField)
        attr_text = (
            get_attr_str(tag, "id")
            + " "
            + get_attr_str(tag, "name")
            + " "
            + get_attr_str(tag, "class")
        )

        # ヨドバシの 'word' や 'getjsondata'、一般的な 'q', 's' を最優先
        if re.search(r"\b(word|q|s|keyword|query|getjsondata|search)\b", attr_text):
            score += 60

        # B. テキスト入力としての適格性
        if t in ["text", "search"]:
            score += 20
        elif t in ["checkbox", "radio"]:  # ヨドバシのサイドメニュー対策
            score -= 50

        # C. プレースホルダー/Aria (GreenBeans等)
        placeholder_aria = (
            get_attr_str(tag, "placeholder") + " " + get_attr_str(tag, "aria-label")
        )
        if any(k in placeholder_aria for k in ["search", "検索", "キーワード"]):
            score += 40

        # D. フォームコンテキスト
        if tag.find_parent("form"):
            score += 15

        if score > 30:
            input_candidates.append((score, tag))

    return finalize(input_candidates, soup)


async def extract_search_elements(html_content: str) -> dict[str, list[str]]:

    input_candidates = await extract_search_input_text(html_content)

    if input_candidates:
        search_input_selector = input_candidates[0]
    else:
        search_input_selector = ""

    button_candidates = await extract_search_button(html_content, search_input_selector)
    return {
        "search_input_list": input_candidates,
        "search_button_list": button_candidates,
    }


class CategoryNameOption(BaseModel):
    name: str
    match_type: Literal["exact", "contains"] = "exact"


class CorrectCategories(BaseModel):
    category_list: list[CategoryNameOption]
    required_match_threshold: int

    def __init__(self, rule: MatchRule):
        super().__init__(
            category_list=[
                CategoryNameOption(name=name, match_type=rule.match_type)
                for name in rule.match_list
            ],
            required_match_threshold=rule.match_threshold,
        )

    def execute(self, select_data: SelectData):
        corrects = []
        for category in self.category_list:
            for option in select_data.options:
                if category.match_type == "exact":
                    if option.text.strip() == category.name.strip():
                        corrects.append(category)

                elif category.match_type == "contains":
                    if category.name.strip() in option.text.strip():
                        corrects.append(category)

                if len(corrects) >= self.required_match_threshold:
                    return True
        return False


async def _check_category_by_rules(select_data, rules: list[MatchRule]):
    for rule in rules:
        correct_category_checker = CorrectCategories(rule)
        if not correct_category_checker.execute(select_data):
            return False
    return True


async def check_category(html: str):
    select_data_list = extract_select_options(html)
    extract_category_options = get_extract_category_options()
    if extract_category_options.extract_type == "rule":
        correct_category_rule = extract_category_options.correct_category
        incorrect_category_rule = extract_category_options.incorrect_category
        for select_data in select_data_list:
            if correct_category_rule is not None:
                if await _check_category_by_rules(
                    select_data, correct_category_rule.rules
                ):
                    if incorrect_category_rule is None:
                        return True, select_data
                    else:
                        if not await _check_category_by_rules(
                            select_data, incorrect_category_rule.rules
                        ):
                            return True, select_data
                continue
            if incorrect_category_rule is not None:
                if await _check_category_by_rules(
                    select_data, incorrect_category_rule.rules
                ):
                    continue
                return True, select_data

    # AIによるカテゴリ抽出の実装はここに追加
    return False, select_data_list


def _generate_css_selector(elem, soup):
    """
    要素からID、あるいはタグ名とクラスを組み合わせて
    一意に特定可能なCSSセレクタを生成する
    """
    elem_id = elem.get("id")

    if elem_id:
        # 【ここがポイント】一番上(soup)から、そのIDを検索してみる
        matches = soup.select(f"#{elem_id}")

        if len(matches) == 1:
            # 世界に一つだけなら、このIDだけでOK
            return f"#{elem_id}"

    path = []
    curr = elem

    while curr and curr.name != "[document]":
        tag_name = curr.name

        selector = tag_name

        elem_id = curr.get("id")
        if elem_id:
            # IDに数字から始まるものや特殊文字が含まれる場合に備え [id="..."] 形式が安全
            selector += f"#{elem_id}"
            # break

        # 2. クラス名を取得
        classes = curr.get("class", [])

        if classes:
            # タグ名.クラス1.クラス2 の形式
            selector += f".{'.'.join(classes)}"

        # 3. 同階層に同じタグがある場合の順序 (nth-of-type)
        # 兄弟要素の中で、自分と同じタグ名を持つ要素を探す
        siblings = curr.parent.find_all(tag_name, recursive=False)
        if len(siblings) > 1:
            # indexは0から始まるので、CSS用に +1 する
            index = siblings.index(curr) + 1
            selector += f":nth-of-type({index})"

        path.append(selector)
        curr = curr.parent

    path.reverse()
    return " > ".join(path)


async def find_custom_select_candidates(
    html: str, original_select: SelectData
) -> list[CustomSelectData]:
    soup = BeautifulSoup(html, "lxml")

    # ターゲットテキストの準備
    target_texts = [
        opt.text.strip() for opt in original_select.options if opt.text.strip()
    ]
    if not target_texts:
        return []

    target_set = set(target_texts)
    # threshold = len(target_set) * 0.7
    threshold = len(target_set) - 2
    if threshold < 1:
        threshold = 1

    candidates_found = []

    # 1. ページ内の全コンテナを取得
    all_containers = soup.find_all(["div", "ul", "dl"])

    for cand in all_containers:
        # 自分の直下に、同じ条件を満たす別のコンテナがあるかチェック
        # これがある場合、自分は「外側の枠（親）」に過ぎないと判断してスキップする
        child_containers = cand.find_all(["div", "ul", "dl"], recursive=True)
        has_better_child = False
        for child in child_containers:
            child_text = child.get_text("|", strip=True)
            child_match_count = sum(1 for t in target_set if t in child_text)
            if child_match_count >= threshold:
                has_better_child = True
                break

        if has_better_child:
            continue

        # 2. 自分自身のスコア判定
        cand_text = cand.get_text("|", strip=True)
        match_count = sum(1 for t in target_set if t in cand_text)

        if match_count >= threshold:
            # ここまで来れば、それは「条件を満たす最小単位のコンテナ」
            current_target_set = target_set.copy()
            detected_options = []

            # 選択肢要素を抽出
            for item in cand.find_all(True, recursive=True):
                txt = item.get_text(strip=True)
                if txt in current_target_set:
                    val = item.get("data-value") or item.get("href") or txt
                    detected_options.append(OptionData(value=val, text=txt))
                    current_target_set.remove(txt)

            visible_analyze = _analyze_visibility(cand)

            candidates_found.append(
                CustomSelectData(
                    id=cand.get("id"),
                    selector=_generate_css_selector(cand, soup),
                    class_list=cand.get("class", []),
                    trigger_text=f"Match count: {match_count}",
                    options=detected_options,
                    linked_select_id=original_select.id,
                    container_tag=cand.name,
                    item_tag=detected_options[0].text if detected_options else "mixed",
                    is_hidden=visible_analyze["is_hidden"],
                    is_dynamic=visible_analyze["is_dynamic"],
                )
            )

    return candidates_found
