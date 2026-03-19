from pydantic import BaseModel, Field
from typing import Optional, Any


class ErrorDetail(BaseModel):
    error_msg: str = ""
    error_type: str = ""


class Cookie(BaseModel):
    cookie_dict_list: Optional[list[dict[str, Any]]] = None
    return_cookies: Optional[bool] = False
    save: Optional[bool] = False
    load: Optional[bool] = False
    filename: Optional[str] = None


class OnError(BaseModel):
    action_type: str = "raise"  # "raise" or "retry"
    max_retries: int = 0
    wait_time: float = 0.0  # seconds
    check_exist_tag: str = ""  # CSS selector


class WaitCSSSelector(BaseModel):
    selector: str
    timeout: Optional[int] = 10  # seconds
    on_error: Optional[OnError] = OnError()
    pre_wait_time: Optional[float] = 0.0  # seconds


class Wait(BaseModel):
    time: int = 0  # seconds


class Scroll(BaseModel):
    to_bottom: bool = False
    amount: Optional[int] = None  # pixels
    pause_time: Optional[float] = 0.5  # seconds


class UserAgent(BaseModel):
    major: int = 141  # chrome major version
    platform: str = "Windows"  # e.g., "Windows", "macOS", "Linux"
    os_version: str = "10.0.0"


class DownloadRequest(BaseModel):
    url: str
    cookie: Optional[Cookie] = None
    wait_css_selector: Optional[WaitCSSSelector] = None
    page_wait_time: Optional[float] = None
    actions: list[Wait | Scroll] = Field(default_factory=list)
    useragent: UserAgent | None = UserAgent()


class DownloadResponse(BaseModel):
    result: str = ""
    cookies: list[dict[str, Any]] = []
    error: ErrorDetail = ErrorDetail()


class SearchBoxInfo(BaseModel):
    search_input_list: list[str] = Field(
        default_factory=list,
        description="List of CSS selectors for search input boxes",
        max_length=5,
    )
    search_button_list: list[str] = Field(
        default_factory=list,
        description="List of CSS selectors for search buttons",
        max_length=5,
    )


class OptionData(BaseModel):
    value: Optional[str] = Field(
        description="Value attribute of the option", max_length=200
    )
    text: str = Field(description="Text content of the option", max_length=200)


class SelectData(BaseModel):
    id: Optional[str]
    name: Optional[str]
    class_list: list[str]
    options: list[OptionData]
    visible: bool = True


class CustomSelectData(BaseModel):
    # 外側のコンテナ（よく div や span になる）
    container_tag: str = Field(description="div, ul, span などの親タグ名")
    id: Optional[str]
    class_list: list[str]

    selector: Optional[str] = Field(
        None, description="この要素を一意に特定するための CSS セレクタ"
    )
    # ユーザーがクリックする「表示中の値」の部分
    trigger_text: Optional[str] = Field(
        None, description="クリックしてリストを開くための要素のセレクタやテキスト"
    )

    # 展開される選択肢のリスト
    # 既存の OptionData を再利用しつつ、タグ情報を追加
    options: list[OptionData]

    # 実体（隠れている本物のselect）との紐付け
    linked_select_id: Optional[str] = Field(
        None, description="display:none になっている本物の select の ID"
    )

    # 動的要素特有の状態
    is_expanded: bool = Field(False, description="ドロップダウンが開いているかどうか")

    # 選択肢が a タグや li タグなどの場合、その種類を保持
    item_tag_type: str = Field("li", description="li, a, div など選択肢のタグ種類")
    is_hidden: bool = Field(True, description="現在表示されているかどうか")
    is_dynamic: bool = Field(False, description="動的要素かどうか")


class ParameterDetail(BaseModel):
    position: str  # "path" or "query"
    key: str | None = None
    index: int | None = None
    consumed_segments: int = 1
    delimiter: str | None = None
    encoding: str = "utf-8"
    value_type: str  # "keyword" or "category"
    is_json: bool | None = None
    json_key_path: str | None = None


class URLAnalysisModel(BaseModel):
    base_url: str
    fixed_path: str
    structure_type: str
    url_template: str
    parameters: dict[str, ParameterDetail]


class SearchURLProbeRequest(BaseModel):
    url: str
    search_word: str | None = None
    cookie: Optional[Cookie] = None
    page_wait_time: Optional[float] = None
    useragent: UserAgent | None = UserAgent()


class SearchURLProbeResponse(BaseModel):
    url_info: URLAnalysisModel | None = None
    categories: SelectData | None = None
    error: ErrorDetail | None = None


class GenerateSearchURLRequest(BaseModel):
    url_info: URLAnalysisModel
    search_keyword: str
    category_value: Optional[str] = None
    category_name: Optional[str] = None


class GenerateSearchURLTemplateRequest(BaseModel):
    url_info: URLAnalysisModel
    search_keyword: str | None = None
    category_value: Optional[str] = None
    category_name: Optional[str] = None


class GenerateSearchURLResponse(BaseModel):
    url: str = Field(
        default="",
        description="Generated search URL based on the input parameters",
        max_length=500,
    )
    error: ErrorDetail | None = None


class SearchURLAnalysisRequest(BaseModel):
    url: str
    search_word: str
    category_value: str = Field(default="")


class SearchURLAnalysisResponse(BaseModel):
    url_info: URLAnalysisModel | None = None
    error: ErrorDetail | None = None


class NoStatusCode(Exception):
    pass


class StatusCodeError(Exception):
    pass
