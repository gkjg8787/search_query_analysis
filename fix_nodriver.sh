#!/bin/bash
set -e

# 設定
TARGET_FILE="/app/venv/lib/python3.14/site-packages/nodriver/core/connection.py"
NETWORK_FILE="/app/venv/lib/python3.14/site-packages/nodriver/cdp/network.py"
FIX_REQUIRED_MAX="0.48.1"

# 1. 現在のインストール済みバージョンを取得
CURRENT_VER=$(uv pip show nodriver | grep "Version:" | awk '{print $2}')

if [ -z "$CURRENT_VER" ]; then
    echo "Error: nodriver is not installed."
    exit 1
fi

version_le() {
    [ "$(printf '%s\n' "$1" "$2" | sort -V | head -n1)" = "$1" ]
}

echo "Detected nodriver version: $CURRENT_VER"

if [ -f "$NETWORK_FILE" ]; then
    echo " - Fixing non-UTF-8 characters in network.py"
    LC_ALL=C sed -i 's/\xb1/ /g' "$NETWORK_FILE"
fi

if version_le "$CURRENT_VER" "$FIX_REQUIRED_MAX"; then
    echo "Applying patches for Python 3.14 and Chrome 146+ compatibility..."

    # A. 改行コードのクリーンアップ (^M 除去)
    find /app/venv/lib/python3.14/site-packages/nodriver/ -name "*.py" -exec sed -i 's/\r//g' {} +

    # B. network.py の非UTF-8文字 (±記号等) を除去
    if [ -f "$NETWORK_FILE" ]; then

        # --- 追加: Chrome 146+ KeyError 対策 ---
        echo " - Fixing KeyError: 'privateNetworkRequestPolicy' and 'sameParty' in network.py"
        
        # privateNetworkRequestPolicy の修正 (存在チェックを追加)
        sed -i "s/private_network_request_policy=PrivateNetworkRequestPolicy.from_json(json\['privateNetworkRequestPolicy'\]),/private_network_request_policy=PrivateNetworkRequestPolicy.from_json(json['privateNetworkRequestPolicy']) if 'privateNetworkRequestPolicy' in json else None,/g" "$NETWORK_FILE"
        
        # sameParty の修正 (.get() を使用してデフォルト False)
        sed -i "s/same_party=bool(json\['sameParty'\]),/same_party=bool(json.get('sameParty', False)),/g" "$NETWORK_FILE"
        # --------------------------------------
    fi

    # C. connection.py の SyntaxWarning (finally: continue) 修正
    if [ -f "$TARGET_FILE" ]; then
        if grep -q "finally:" "$TARGET_FILE" && grep -q "continue" "$TARGET_FILE"; then
            echo " - Fixing SyntaxWarning in connection.py"
            sed -i '/finally:/ { N; s/finally:\n\s*continue//; }' "$TARGET_FILE"
            if ! grep -q "self.enabled_domains.remove(domain_mod)\n\s+continue" "$TARGET_FILE"; then
                sed -i '/self.enabled_domains.remove(domain_mod)/a \                        continue' "$TARGET_FILE"
            fi
        fi
    fi
    
    echo "Successfully patched nodriver $CURRENT_VER."
else
    echo "Skipping patches. nodriver $CURRENT_VER is likely already fixed or compatible."
fi