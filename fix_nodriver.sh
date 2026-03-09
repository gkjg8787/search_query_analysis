#!/bin/bash
set -e

# 設定
TARGET_FILE="/app/venv/lib/python3.14/site-packages/nodriver/core/connection.py"
NETWORK_FILE="/app/venv/lib/python3.14/site-packages/nodriver/cdp/network.py"
FIX_REQUIRED_MAX="0.48.1"

# 1. 現在のインストール済みバージョンを取得
# (uv がインストールされている前提)
CURRENT_VER=$(uv pip show nodriver | grep "Version:" | awk '{print $2}')

if [ -z "$CURRENT_VER" ]; then
    echo "Error: nodriver is not installed."
    exit 1
fi

# バージョン比較関数: $1 が $2 以下 (<=) かどうかを判定
# 例: version_le "0.48.1" "0.48.1" -> true
version_le() {
    [ "$(printf '%s\n' "$1" "$2" | sort -V | head -n1)" = "$1" ]
}

echo "Detected nodriver version: $CURRENT_VER"

# 修正が必要なバージョンか判定
if version_le "$CURRENT_VER" "$FIX_REQUIRED_MAX"; then
    echo "Applying patches for Python 3.14 compatibility..."

    # A. 改行コードのクリーンアップ (^M 除去)
    # パッケージ全体に対して実施
    find /app/venv/lib/python3.14/site-packages/nodriver/ -name "*.py" -exec sed -i 's/\r//g' {} +

    # B. network.py の非UTF-8文字 (±記号等) を除去
    if [ -f "$NETWORK_FILE" ]; then
        echo " - Fixing non-UTF-8 characters in network.py"
        LC_ALL=C sed -i 's/\xb1/ /g' "$NETWORK_FILE"
    fi

    # C. connection.py の SyntaxWarning (finally: continue) 修正
    if [ -f "$TARGET_FILE" ]; then
        # 修正対象のパターン (finally: 直後の continue) があるか確認
        if grep -q "finally:" "$TARGET_FILE" && grep -q "continue" "$TARGET_FILE"; then
            echo " - Fixing SyntaxWarning in connection.py"
            
            # finally: と continue の行を削除 (413,414行目付近)
            # 行番号がズレていても「finally: の次の行が continue」なら消去するロジック
            sed -i '/finally:/ { N; s/finally:\n\s*continue//; }' "$TARGET_FILE"
            
            # remove() の後に continue を挿入 (重複防止のため grep で確認)
            if ! grep -q "self.enabled_domains.remove(domain_mod)\n\s+continue" "$TARGET_FILE"; then
                sed -i '/self.enabled_domains.remove(domain_mod)/a \                        continue' "$TARGET_FILE"
            fi
        fi
    fi
    
    echo "Successfully patched nodriver $CURRENT_VER."
else
    echo "Skipping patches. nodriver $CURRENT_VER is likely already fixed or compatible."
fi