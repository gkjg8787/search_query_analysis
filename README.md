# search_query_analysis

# 概要
- 解析したい対象のサイト（検索ボックスが表示されている）のURLから検索を自動で行いURLのクエリを抽出するAPI

# API Usage

## 1. Search URL Probe (検索構造の自動解析)
ブラウザ(nodriver)を起動して対象サイトにアクセスし、検索ボックスを自動検知して検索を実行します。その結果からURLパターンを解析します。

**Endpoint:** `POST /searchurl/probe/`

**Request JSON Example:**
```json
{
  "url": "https://www.example.com",
  "search_word": "test"
}
```

## 2. Search URL Analysis (URLパターンの静的解析)
既に検索結果のURLが分かっている場合に、そのURLと検索キーワードからパラメータ構造を解析します。

**Endpoint:** `POST /searchurl/analysis/`

**Request JSON Example:**
```json
{
  "url": "https://www.example.com/search?q=test&cat=1",
  "search_word": "test",
  "category_value": "1"
}
```

## 3. Generate Search URL (検索URLの生成)
`url_info` (解析結果) と新しいキーワード・カテゴリ情報を入力として、検索用URLを生成します。

**Endpoint:** `POST /searchurl/generate/`

**Request JSON Example:**
```json
{
  "url_info": {
    "base_url": "https://www.example.com",
    "fixed_path": "/search/",
    "structure_type": "query",
    "url_template": "https://www.example.com/search/?q={keyword}",
    "parameters": {
      "keyword": {
        "position": "query",
        "key": "q",
        "value_type": "keyword"
      }
    }
  },
  "search_keyword": "iphone",
  "category_value": "",
  "category_name": ""
}
```
