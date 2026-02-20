from bs4 import BeautifulSoup
from pydantic import BaseModel
from typing import List, Optional


class OptionData(BaseModel):
    value: Optional[str]
    text: str


class SelectData(BaseModel):
    id: Optional[str]
    name: Optional[str]
    class_list: List[str]
    options: List[OptionData]


def extract_select_options(html_content: str) -> List[SelectData]:
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
        )
        results.append(select_info)

    return results
