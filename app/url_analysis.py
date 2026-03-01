import urllib.parse
from typing import List, Dict, Optional
import re
import json


from models import URLAnalysisModel, ParameterDetail


def build_url(
    analysis: URLAnalysisModel,
    keyword: str,
    category: str | None = None,
    category_name: str = "category_name",
) -> str:
    params_config = analysis.parameters
    url = analysis.url_template

    # 1. Keyword の処理 (空でも None でも安全にエンコード)
    kw_config = params_config.get("keyword")
    processed_kw = urllib.parse.quote(
        keyword or "", encoding=kw_config.encoding if kw_config else "utf-8"
    )

    # 2. Category の処理
    ct_config = params_config.get("category")
    processed_ct = None

    if category and ct_config:
        if ct_config.is_json:
            if ct_config.json_key_path == "$.*":
                json_obj = {category: category_name}
                processed_ct = json.dumps(
                    json_obj, ensure_ascii=False, separators=(",", ":")
                )
            processed_ct = urllib.parse.quote(processed_ct)
        elif ct_config.position == "path" and ct_config.consumed_segments > 1:
            delimiter = ct_config.delimiter or "/"
            if delimiter in category:
                processed_ct = category
            else:
                seg_len = len(category) // ct_config.consumed_segments
                if seg_len > 0:
                    parts = [
                        category[i : i + seg_len]
                        for i in range(0, len(category), seg_len)
                    ]
                    processed_ct = delimiter.join(parts)
                else:
                    processed_ct = category
        else:
            processed_ct = category

    # 3. 置換の実行
    # ここでは `{category}` をそのままにし、値がある場合だけ埋める
    format_data = {"keyword": processed_kw}
    if processed_ct is not None:
        format_data["category"] = processed_ct
    else:
        format_data["category"] = "REMOVEME"  # 一旦マーカーを置く

    # 置換実行
    res_url = url.format(**format_data)

    # 4. 不要なパラメータのクリーンアップ (後処理)
    if processed_ct is None:
        if ct_config and ct_config.position == "query":
            # マツキヨ型: key=REMOVEME を消す
            key = ct_config.key
            # ?key=REMOVEME& / &key=REMOVEME / ?key=REMOVEME のパターンに対応
            res_url = re.sub(rf"{key}=REMOVEME&?", "", res_url)
            res_url = re.sub(rf"&{key}=REMOVEME", "", res_url)
        else:
            # 楽天/ビックカメラ型: /REMOVEME/ を / に
            res_url = res_url.replace("REMOVEME/", "").replace("REMOVEME", "")

    # 5. 最終仕上げ (重複スラッシュや記号の掃除)
    res_url = res_url.replace("?&", "?").replace("&&", "&").rstrip("&").rstrip("?")
    res_url = re.sub(r"(?<!:)/{2,}", "/", res_url)

    return res_url


# --- Generator Logic ---
def generate_template(
    base_url: str,
    segments: List[str],
    query_dict: Dict[str, List[str]],
    params: Dict[str, ParameterDetail],
) -> str:
    """解析結果からURLテンプレート文字列を構築する"""

    # 1. Path部分の構築
    path_placeholders = {
        p.index: (name, p.consumed_segments)
        for name, p in params.items()
        if p.position == "path"
    }

    template_segments = []
    skip_until = -1
    for i, seg in enumerate(segments):
        if i <= skip_until:
            continue

        if i in path_placeholders:
            name, count = path_placeholders[i]
            template_segments.append(f"{{{name}}}")
            skip_until = i + count - 1
        else:
            template_segments.append(seg)

    path_part = "/" + "/".join(template_segments) + "/"

    # 2. Query部分の構築
    query_placeholders = {
        p.key: name for name, p in params.items() if p.position == "query"
    }
    query_pairs = []

    for key, values in query_dict.items():
        if key in query_placeholders:
            query_pairs.append(f"{key}={{{query_placeholders[key]}}}")
        else:
            # 固定値のクエリも保持する
            query_pairs.append(f"{key}={values[0]}")

    query_part = "?" + "&".join(query_pairs) if query_pairs else ""

    return f"{base_url}{path_part}{query_part}"


# --- Core Logic ---
class URLPatternLogic:
    def __init__(self, target_url: str, keyword: str, category_val: str):
        self.parsed = urllib.parse.urlparse(target_url)
        self.keyword = keyword
        self.category_val = category_val
        # パスをセグメントに分割 (空文字を除去)
        self.segments = [s for s in self.parsed.path.split("/") if s]
        self.query_dict = urllib.parse.parse_qs(self.parsed.query)
        self.encodings = ["utf-8", "shift-jis", "euc-jp", "cp932"]

    def _find_keyword(self) -> Optional[ParameterDetail]:
        """生のクエリ文字列から、各エンコーディングを試してキーワードを探す"""

        # 1. クエリ文字列を & で分割
        if self.parsed.query:
            pairs = self.parsed.query.split("&")

            for pair in pairs:
                if "=" not in pair:
                    continue
                key, val_encoded = pair.split("=", 1)

                # 2. 各エンコーディングでデコードを試みる
                for enc in self.encodings:
                    try:
                        # %エンコードをバイト列に戻してからデコード
                        # urllib.parse.unquote_to_bytes を使うのがコツ
                        val_bytes = urllib.parse.unquote_to_bytes(val_encoded)
                        decoded_val = val_bytes.decode(enc)

                        if self.keyword in decoded_val:
                            return ParameterDetail(
                                position="query",
                                key=key,
                                encoding=enc,
                                value_type="keyword",
                            )
                    except (UnicodeDecodeError, AttributeError):
                        continue
        # 2. パスから探す (楽天型)
        for i, seg in enumerate(self.segments):
            for enc in self.encodings:
                try:
                    decoded_seg = urllib.parse.unquote(seg, encoding=enc)
                    if self.keyword == decoded_seg:
                        return ParameterDetail(
                            position="path", index=i, encoding=enc, value_type="keyword"
                        )
                except:
                    continue
        return None

    def _find_category(self) -> Optional[ParameterDetail]:
        """パスまたはクエリからカテゴリIDを逆引き"""
        # 1. パス内の結合チェック (BicCamera型: 001/170 -> 001170)
        # 1. パス内のチェック (スラッシュ区切り対応)
        # 比較用に category_val の前後スラッシュを除去
        target_cat = self.category_val.strip("/")

        for start in range(len(self.segments)):
            for end in range(start + 1, len(self.segments) + 1):
                # セグメントをスラッシュで結合して比較
                combined_with_slash = "/".join(self.segments[start:end])
                # セグメントを単純結合して比較 (BicCamera型用)
                combined_plain = "".join(self.segments[start:end])

                if combined_with_slash == target_cat or combined_plain == target_cat:
                    return ParameterDetail(
                        position="path",
                        index=start,
                        consumed_segments=end - start,
                        delimiter="/",
                        value_type="category",
                    )

        # 2. クエリ内のチェック
        for key, values in self.query_dict.items():
            for value in values:
                # クエリ内でも念のため strip して比較
                if target_cat == value.strip("/"):
                    return ParameterDetail(
                        position="query", key=key, value_type="category"
                    )
                if value.startswith("{") or value.startswith("["):
                    # デコードした文字列が JSON っぽければパースしてみる
                    try:
                        data = json.loads(value)
                        # JSONの中身を再帰的にチェックするロジック...
                        return ParameterDetail(
                            position="query",
                            key=key,
                            is_json=True,
                            json_key_path="$.*",
                            value_type="category",
                        )
                    except Exception as e:  # pass
                        print(f"type: {type(e)} error: {str(e)}")

        return None

    def analyze(self) -> URLAnalysisModel:
        params = {}
        kw = self._find_keyword()
        if kw:
            params["keyword"] = kw
            # キーワード検出で判明したエンコーディングを使ってクエリパラメータを再パースする
            # これにより、キーワード以外のパラメータ(submitボタンの値など)の文字化けを防ぐ
            if kw.encoding and kw.encoding != "utf-8":
                try:
                    self.query_dict = urllib.parse.parse_qs(
                        self.parsed.query, encoding=kw.encoding
                    )
                except Exception:
                    pass

        ct = self._find_category()
        if ct:
            params["category"] = ct

        # path にあるパラメータの中で一番若いインデックスを探す
        path_indices = [
            p.index
            for p in params.values()
            if p.position == "path" and p.index is not None
        ]

        if path_indices:
            first_param_idx = min(path_indices)
            # パラメータが出現する直前までのセグメントを固定パスとする
            fixed_path = "/" + "/".join(self.segments[:first_param_idx]) + "/"
        else:
            # パスにパラメータがない場合は、パス全体が固定
            fixed_path = self.parsed.path
            if not fixed_path.endswith("/"):
                fixed_path += "/"

        base_url = f"{self.parsed.scheme}://{self.parsed.netloc}"
        template_segments = []
        skip_until = -1
        path_placeholders = {
            p.index: (name, p.consumed_segments)
            for name, p in params.items()
            if p.position == "path"
        }

        for i in range(len(self.segments)):
            if i <= skip_until:
                continue
            if i in path_placeholders:
                name, count = path_placeholders[i]
                template_segments.append(f"{{{name}}}")
                skip_until = i + count - 1
            else:
                template_segments.append(self.segments[i])

        # 最後にスラッシュを付ける（ECサイトの慣習に合わせる）
        template_path = "/" + "/".join(template_segments)
        if self.parsed.path.endswith("/") and not template_path.endswith("/"):
            template_path += "/"

        query_parts = []
        query_placeholders = {
            p.key: name for name, p in params.items() if p.position == "query"
        }
        for k, vs in self.query_dict.items():
            if k in query_placeholders:
                query_parts.append(f"{k}={{{query_placeholders[k]}}}")
            else:
                query_parts.append(f"{k}={vs[0]}")

        if query_parts:
            template_path += "?" + "&".join(query_parts)

        template_path = f"{base_url}" + template_path

        # 構造判定
        has_path = any(p.position == "path" for p in params.values())
        has_query = any(p.position == "query" for p in params.values())
        struct = (
            "directory"
            if has_path and not has_query
            else "mixed" if has_path else "query"
        )

        return URLAnalysisModel(
            base_url=base_url,
            fixed_path=fixed_path,
            structure_type=struct,
            url_template=template_path,
            parameters=params,
        )
