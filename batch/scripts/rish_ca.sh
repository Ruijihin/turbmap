#!/usr/bin/env bash
# 京大生存圏研究所のサーバーは、正しい中間証明書を送ってこない(2026年10月時点)。
# また、その発行元のルート証明書(SECOM TLS RSA Root CA 2024)はPythonのcertifiに入っていない。
# リポジトリに置いた2つの証明書をcertifiの束に足して、Pythonのrequestsに使わせる。
# 使い方: source batch/scripts/rish_ca.sh  → REQUESTS_CA_BUNDLE が設定される
set -euo pipefail
DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/../certs" && pwd)
WORK=${RUNNER_TEMP:-/tmp}/rish-ca
mkdir -p "$WORK"

# ルート証明書の指紋を確かめる(Windowsの信頼済みストアの値と照合済み)
EXPECTED="14:35:F2:25:C5:D2:52:D7:A2:19:48:CC:3C:E6:2A:EC:FA:88:00:1E:3D:D7:2D:1C:C3:55:51:00:EB:37:2F:93"
ACTUAL=$(openssl x509 -in "$DIR/secom-tls-rsa-root-ca-2024.pem" -noout -fingerprint -sha256 | cut -d= -f2)
if [ "$ACTUAL" != "$EXPECTED" ]; then
  echo "ルート証明書の指紋が一致しません: $ACTUAL" >&2; return 1 2>/dev/null || exit 1
fi

BASE=$(python -m certifi)
cat "$BASE" "$DIR/secom-tls-rsa-root-ca-2024.pem" "$DIR/nii-odca-g8-rsa.pem" > "$WORK/bundle.pem"
export REQUESTS_CA_BUNDLE="$WORK/bundle.pem"
if [ -n "${GITHUB_ENV:-}" ]; then echo "REQUESTS_CA_BUNDLE=$WORK/bundle.pem" >> "$GITHUB_ENV"; fi
echo "証明書の束を作りました: $REQUESTS_CA_BUNDLE"
