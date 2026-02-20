from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

LOG_OPTIONS = {"directory_path": f"{BASE_DIR}/log/"}
AI_MODEL_LIST = {
    "gemini": [
        # "gemini-3-pro-preview",
        "gemini-3-flash-preview",
        "gemini-2.5-pro",
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite",
        # "gemini-2.0-flash",
        # "gemini-2.0-flash-lite",
    ]
}
EXTRACT_CATEGORY = {
    "extract_type": "rule",  # "rule" or "ai"
    "correct_category": {  # Required for rule
        "match_threshold": 2,  # Number of matching settings
        "rules": [
            {
                "match_type": "exact",
                "match_threshold": 1,
                "match_list": ["すべての商品", "全商品", "全ての商品"],
            },
            {
                "match_type": "contains",
                "match_threshold": 1,
                "match_list": [
                    "パソコン",
                    "食品",
                    "家電",
                    "スマホ",
                    "カメラ",
                    "テレビ",
                    "電子書籍",
                    "医薬品",
                    "エアコン",
                    "ゲーム",
                    "おもちゃ",
                ],
            },
        ],
    },
    "incorrect_category": {
        "match_threshold": 1,
        "rules": [
            {
                "match_type": "exact",
                "match_threshold": 1,
                "match_list": ["安い順", "人気順", "新着順", "発売日"],
            },
        ],
    },
}
