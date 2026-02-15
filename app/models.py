from typing import Literal

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


class SearchURLAnalysisRequest(BaseModel):
    url: str
    search_word: str | None = None
    analysis_scope: (
        Literal[
            "before_search",
            "all",
        ]
        | None
    ) = Field(
        default=None,
        description="Scope of analysis: 'all' or 'before_search' or None, defalt is None, None and before_search are one anaylsis",
    )
    cookie: Optional[Cookie] = None
    wait_css_selector: Optional[WaitCSSSelector] = None
    page_wait_time: Optional[float] = None
    useragent: UserAgent | None = UserAgent()


class QueryOptionValue(BaseModel):
    value: str = Field(description="Value of the query parameter")
    text: Optional[str] = Field(
        default=None, description="Description of the query value"
    )


class QueryOption(BaseModel):
    key: str = Field(description="Query parameter key")
    values: list[QueryOptionValue] = Field(
        default_factory=list,
        description="List of possible values for the query parameter",
    )
    description: Optional[str] = Field(
        default=None, description="Description of the query option"
    )


class GeminiSearchBoxResponse(BaseModel):
    search_input_box: str = Field(
        default="", description="CSS selector for the search input box"
    )
    search_button: str = Field(
        default="", description="CSS selector for the search button"
    )
    search_options: dict = Field(
        default_factory=dict, description="Additional search options"
    )
    error_msg: str = Field(default="", description="Error message, if any")


class SearchURLInfo(BaseModel):
    site_top_url: str = ""
    search_dir: str = ""
    search_url_type: Literal["", "query", "directory"] = ""
    search_fixed_query: str = ""
    search_query: str | None = None
    encoding: str = ""
    query_options: list[QueryOption] = Field(default_factory=list)


class SearchURLAnalysisResponse(BaseModel):
    url_info: SearchURLInfo | None = None
    error: ErrorDetail | None = None


class NoModelsAvailableError(Exception):
    pass


class AskGeminiErrorInfo(BaseModel):
    error_type: str
    error: str


class GeminiSearchURLAnalysisResponse(BaseModel):
    site_top_url: str = Field(default="", description="Top URL of the site")
    search_dir: str = Field(default="", description="Search directory path")
    search_fixed_query: str = Field(default="", description="Search fixed query")
    search_url_type: Literal["query", "directory", "other"] = Field(
        default="other", description="Type of search URL"
    )
    query_param: str = Field(default="", description="Query parameter for search")
    encoding: str = Field(default="", description="Encoding used in the URL")
    query_options: list[QueryOption] = Field(
        default_factory=list, description="Query options extracted from the URL"
    )
