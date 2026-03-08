from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

LOG_OPTIONS = {"directory_path": f"{BASE_DIR}/log/"}

EXTRACT_CATEGORY = {
    "extract_type": "rule",  # "rule"
    "correct_category": {  # Required for rule
        "match_threshold": 2,  # Number of matching settings
        "rules": [
            {
                "match_type": "exact",
                "match_threshold": 1,
                "match_list": [
                    "すべての商品",
                    "全商品",
                    "全ての商品",
                    "全てのカテゴリ",
                    "すべてのカテゴリ",
                    "全カテゴリ",
                    "すべてのジャンル",
                    "全てのジャンル",
                    "全ジャンル",
                ],
            },
            {
                "match_type": "contains",
                "match_threshold": 1,
                "match_list": [
                    "パソコン",
                    "周辺機器",
                    "食品",
                    "ドリンク",
                    "酒",
                    "菓子",
                    "家電",
                    "スマホ",
                    "スマートフォン",
                    "タブレット",
                    "カメラ",
                    "テレビ",
                    "オーディオ",
                    "楽器",
                    "書籍",
                    "医薬品",
                    "エアコン",
                    "ゲーム",
                    "おもちゃ",
                    "ホビー",
                    "日用品",
                    "家具",
                    "インテリア",
                    "寝具",
                    "ファッション",
                    "アクセサリー",
                    "雑貨",
                    "スポーツ",
                    "アウトドア",
                    "車",
                    "化粧品",
                    "美容",
                    "ペット",
                ],
            },
        ],
    },
    "incorrect_category": {
        "match_threshold": 1,
        "rules": [
            {
                "match_type": "contains",
                "match_threshold": 1,
                "match_list": [
                    "安い順",
                    "人気順",
                    "おすすめ順",
                    "オススメ順",
                    "新着順",
                    "発売日",
                    "北海道",
                    "東京",
                ],
            },
        ],
    },
}
