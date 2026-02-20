from typing import Literal
from pydantic import BaseModel

import parser as cate_parser
from common.read_config import MatchRule, get_extract_category_options


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

    def execute(self, select_data: cate_parser.SelectData):
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
    select_data_list = cate_parser.extract_select_options(html)
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
