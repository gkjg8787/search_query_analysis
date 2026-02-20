import url_analysis


def analysis_and_print(ptn):
    logic = url_analysis.URLPatternLogic(
        ptn["target"], keyword=ptn["keyword"], category_val=ptn["category_value"]
    )
    result = logic.analyze()

    print(result.model_dump_json(indent=2, exclude_none=True))
    return result


def test_url_analysis():
    # --- テスト実行 ---
    # URL3: ビックカメラの例
    bic_ptn = {
        "target": "https://www.biccamera.com/bc/category/001/170/?q=%83X%83%7D%83C%83%8B40",
        "keyword": "スマイル40",
        "category_value": "001170",
    }
    bic_correct = {
        "anlaysis": {
            "base_url": "https://www.biccamera.com",
            "fixed_path": "/bc/category/",
            "structure_type": "mixed",
            "url_template": "https://www.biccamera.com/bc/category/{category}/?q={keyword}",
            "parameters": {
                "keyword": {
                    "position": "query",
                    "key": "q",
                    "consumed_segments": 1,
                    "encoding": "shift-jis",
                    "value_type": "keyword",
                },
                "category": {
                    "position": "path",
                    "index": 2,
                    "consumed_segments": 2,
                    "delimiter": "/",
                    "encoding": "utf-8",
                    "value_type": "category",
                },
            },
        },
        "generate": [
            {
                "url": "https://www.biccamera.com/bc/category/001/100/?q=%83%8B%81%5B%83%5E%81%5B",
                "keyword": "ルーター",
                "category_value": "001100",
            },
            {
                "url": "https://www.biccamera.com/bc/category/?q=%97%E2%91%A0%8C%C9",
                "keyword": "冷蔵庫",
                "category_value": "",
            },
        ],
    }
    rakuten_ptn = {
        "target": "https://search.rakuten.co.jp/search/mall/%E3%83%9D%E3%82%B1%E3%83%A2%E3%83%B3/566382/",
        "keyword": "ポケモン",
        "category_value": "566382",
    }
    rakuten_correct = {
        "analysis": {
            "base_url": "https://search.rakuten.co.jp",
            "fixed_path": "/search/mall/",
            "structure_type": "directory",
            "url_template": "https://search.rakuten.co.jp/search/mall/{keyword}/{category}/",
            "parameters": {
                "keyword": {
                    "position": "path",
                    "index": 2,
                    "consumed_segments": 1,
                    "encoding": "utf-8",
                    "value_type": "keyword",
                },
                "category": {
                    "position": "path",
                    "index": 3,
                    "consumed_segments": 1,
                    "delimiter": "/",
                    "encoding": "utf-8",
                    "value_type": "category",
                },
            },
        },
        "generate": [
            {
                "url": "https://search.rakuten.co.jp/search/mall/%E3%81%8A%E7%B1%B3/100227/",
                "keyword": "お米",
                "category_value": "100227",
            },
            {
                "url": "https://search.rakuten.co.jp/search/mall/USB/",
                "keyword": "USB",
                "category_value": "",
            },
        ],
    }
    matsukiyo_ptn = {
        "target": "https://www.matsukiyococokara-online.com/store/catalogsearch/result?search_keyword=%E3%83%90%E3%83%95%E3%82%A1%E3%83%AA%E3%83%B3&categories=%7B%2200100000000000000%22%3A%22%E5%8C%BB%E8%96%AC%E5%93%81%E3%83%BB%E5%8C%BB%E8%96%AC%E9%83%A8%E5%A4%96%E5%93%81%22%7D&layout=1",
        "keyword": "バファリン",
        "category_value": "00100000000000000",
    }
    matsukiyo_correct = {
        "analysis": {
            "base_url": "https://www.matsukiyococokara-online.com",
            "fixed_path": "/store/catalogsearch/result/",
            "structure_type": "query",
            "url_template": "https://www.matsukiyococokara-online.com/store/catalogsearch/result?search_keyword={keyword}&categories={category}&layout=1",
            "parameters": {
                "keyword": {
                    "position": "query",
                    "key": "search_keyword",
                    "consumed_segments": 1,
                    "encoding": "utf-8",
                    "value_type": "keyword",
                },
                "category": {
                    "position": "query",
                    "key": "categories",
                    "consumed_segments": 1,
                    "encoding": "utf-8",
                    "value_type": "category",
                    "is_json": True,
                    "json_key_path": "$.*",
                },
            },
        },
        "generate": [
            {
                "url": "https://www.matsukiyococokara-online.com/store/catalogsearch/result?search_keyword=%E3%83%86%E3%82%A3%E3%83%83%E3%82%B7%E3%83%A5%E3%83%9A%E3%83%BC%E3%83%91%E3%83%BC&categories=%7B%2200600000000000000%22%3A%22%E6%97%A5%E7%94%A8%E5%93%81%E3%83%BB%E3%83%9A%E3%83%83%E3%83%88%22%7D&layout=1",
                "keyword": "ティッシュペーパー",
                "category_value": "00600000000000000",
                "category_name": "日用品・ペット",
            },
            {
                "url": "https://www.matsukiyococokara-online.com/store/catalogsearch/result?search_keyword=%E6%B4%97%E5%89%A4&layout=1",
                "keyword": "洗剤",
                "category_value": "",
            },
        ],
    }
    # 入力ヒント: 検索語="スマイル40", カテゴリID="001170"

    bic_analysis = analysis_and_print(bic_ptn)
    print("--------------------------")
    rakuten_analysis = analysis_and_print(rakuten_ptn)
    print("--------------------------")
    matsu_analysis = analysis_and_print(matsukiyo_ptn)

    def _build_url_and_assert(analysis, correct):
        for gen in correct["generate"]:
            result = url_analysis.build_url(
                analysis,
                gen["keyword"],
                gen["category_value"],
                gen.get("category_name", "category_name"),
            )
            print("Build:", result)
            assert result == gen["url"], "URL generation failed"

    print("--- Build URL -----------------------------------------")
    _build_url_and_assert(bic_analysis, bic_correct)
    _build_url_and_assert(rakuten_analysis, rakuten_correct)
    _build_url_and_assert(matsu_analysis, matsukiyo_correct)
