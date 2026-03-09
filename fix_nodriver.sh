#!/bin/bash
set -e

TARGET_FILE="/app/venv/lib/python3.14/site-packages/nodriver/core/connection.py"
NETWORK_FILE="/app/venv/lib/python3.14/site-packages/nodriver/cdp/network.py"

# 1. 改行コードのクリーンアップ (^M 除去)
echo "Cleaning up line endings..."
find /app/venv/lib/python3.14/site-packages/nodriver/ -name "*.py" -exec sed -i 's/\r//g' {} +

# 2. network.py の非UTF-8文字 (±記号等) を除去
if [ -f "$NETWORK_FILE" ]; then
    echo "Fixing non-UTF-8 characters in network.py..."
    LC_ALL=C sed -i 's/\xb1/ /g' "$NETWORK_FILE"
fi

# 3. connection.py の finally: continue 修正
if [ -f "$TARGET_FILE" ]; then
    # finally: の直後に continue が続くパターンがあるかチェック
    # grep -Pz は複数行にまたがる検索を可能にします
    if grep -Pzql "finally:\n\s+continue" "$TARGET_FILE"; then
        echo "Applying fix for Python 3.14 SyntaxWarning in connection.py..."

        # 413,414行目付近の finally: と continue を削除
        # 行番号がズレていても安全なように、行内容とセットで削除
        sed -i '/finally:/ { N; s/finally:\n\s*continue//; }' "$TARGET_FILE"

        # remove() の後に continue を挿入 (まだ存在しない場合のみ)
        if ! grep -q "self.enabled_domains.remove(domain_mod)\n\s+continue" "$TARGET_FILE"; then
            sed -i '/self.enabled_domains.remove(domain_mod)/a \                        continue' "$TARGET_FILE"
        fi
    else
        echo "No SyntaxWarning pattern found in connection.py. Skipping."
    fi
fi

echo "nodriver fixes completed successfully."
