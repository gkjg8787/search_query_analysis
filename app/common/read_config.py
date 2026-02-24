from typing import Literal

from pydantic import BaseModel, Field

import settings


class LogOptions(BaseModel):
    directory_path: str


class MatchRule(BaseModel):
    match_type: Literal["exact", "contains"] = "exact"
    match_threshold: int = 1
    match_list: list[str] = Field(default_factory=list)


class CorrectCategory(BaseModel):
    match_threshold: int = 1
    rules: list[MatchRule] = Field(default_factory=list)


class ExtractCategoryOptions(BaseModel):
    extract_type: Literal["rule", "ai"] = Field(
        default="rule",
        description="Method to extract categories: 'rule' or 'ai'",
    )
    correct_category: CorrectCategory | None = Field(
        default=None,
        description="Settings for correct category extraction (required if extract_type is 'rule')",
    )
    incorrect_category: CorrectCategory | None = Field(
        default_factory=None,
        description="Settings for incorrect category extraction",
    )


def to_lower_keys(obj):
    if isinstance(obj, dict):
        # 新しい辞書を構築し、各キーを小文字に変換
        # 値が辞書の場合は再帰的にto_lower_keysを適用
        return {
            k.lower() if isinstance(k, str) else k: to_lower_keys(v)
            for k, v in obj.items()
        }
    elif isinstance(obj, list):
        # リストの場合は、各要素に対してto_lower_keysを適用
        return [to_lower_keys(elem) for elem in obj]
    else:
        # 辞書でもリストでもない場合はそのまま返す
        return obj


def get_base_dir():
    return settings.BASE_DIR


def get_log_options():
    lower_key_dict = to_lower_keys(settings.LOG_OPTIONS)
    return LogOptions(**lower_key_dict)


def get_ai_model_list():
    return settings.AI_MODEL_LIST


def get_extract_category_options():
    lower_key_dict = to_lower_keys(settings.EXTRACT_CATEGORY)
    return ExtractCategoryOptions(**lower_key_dict)
