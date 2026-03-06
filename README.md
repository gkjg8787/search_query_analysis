# search_query_analysis

# 概要
- 解析したい対象のサイト（検索ボックスが表示されている）のURLから検索を自動で行いURLの解析情報を出力するAPI


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


- statud code error が出た場合は useragent を なし(null)にして再試行してみると通るサイトもある
```json
{
  "url": "https://www.example.com",
  "search_word": "test",
  "useragent": null
}
```

- 結果の"url_template"の値が固定({}がない)または入力したurlと同じ値の場合、解析に失敗しているか検索テキストや検索ボタンを見つけられていない or 間違ったものを使用している可能性がある。ルールベースなので対応できないサイトでは解析できない。

### 可能
- URLから検索を実行して遷移したURLを解析、解析情報を出力する
- カテゴリフィルターがselect optionタグ型であるならカテゴリーも出力する。隠れselect option型（動的）の一部もカテゴリを出力できる。

### 不可
- カテゴリフィルターがselect option型でなく動的なタグの場合はカテゴリ出力できない。
- 検索テキストボックスや検索ボタンを押すのに動的な動作（ボタンを押してテキストボックスが出てくる場合や検索ボタンがなくEnterのみで検索する等）の場合は抽出できない。

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

### 不可
- カテゴリの変化がURL内の複数ヶ所に影響する場合は解析できない。例えば 1つのカテゴリで2つのクエリに変化がある(cat=1&cname=XXX がセット)場合など。
- 検索ワードとカテゴリ以外のパラメータは固定として扱われる。URL内にカテゴリが存在してcategory_valueが指定されない場合も同様にカテゴリも固定として扱われる。



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

- url_info は 1, 2のAPIで出力した解析情報を使用する

