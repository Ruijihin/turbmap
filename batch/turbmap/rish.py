"""京大生存圏研究所アーカイブ(MSM最新1週間分)の一覧取得とダウンロード。"""
import re
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import requests

BASE = "https://database.rish.kyoto-u.ac.jp/arch/jmadata/data/gpv/latest/"
UA = {"User-Agent": "turbmap-batch (+https://github.com/)"}


def list_inits(days=2):
    """直近days日分のフォルダから、気圧面ファイルがある初期時刻(YYYYMMDDHH)を新しい順に返す。"""
    now = datetime.now(timezone.utc)
    inits = []
    for d in range(days):
        day = (now - timedelta(days=d)).strftime("%Y%m%d")
        r = requests.get(BASE + day + "/", headers=UA, timeout=60)
        if r.status_code == 404:
            continue
        r.raise_for_status()
        inits += re.findall(r'href="MSM(\d{10})P\.nc"', r.text)
    return sorted(set(inits), reverse=True)


def file_url(init, kind="P"):
    """kind: "P"=気圧面、"S"=地上"""
    return f"{BASE}{init[:8]}/MSM{init}{kind}.nc"


def is_stable(init, min_age_minutes=10):
    """掲載直後(書き込み途中の可能性)を避けるため、気圧面・地上の両方が掲載から一定時間たっているか確かめる。"""
    for kind in ("P", "S"):
        r = requests.head(file_url(init, kind), headers=UA, timeout=60)
        if r.status_code == 404:
            return False
        r.raise_for_status()
        lm = r.headers.get("Last-Modified")
        if lm and datetime.now(timezone.utc) - parsedate_to_datetime(lm) < timedelta(minutes=min_age_minutes):
            return False
    return True


def download(init, dest, kind="P", retries=3):
    url = file_url(init, kind)
    for k in range(retries):
        try:
            with requests.get(url, headers=UA, stream=True, timeout=300) as r:
                r.raise_for_status()
                expected = int(r.headers.get("Content-Length", 0))
                n = 0
                with open(dest, "wb") as f:
                    for chunk in r.iter_content(chunk_size=1 << 20):
                        f.write(chunk)
                        n += len(chunk)
            if expected and n != expected:
                raise IOError(f"サイズが合いません: {n} / {expected}")
            return dest
        except Exception as e:  # noqa: BLE001
            if k == retries - 1:
                raise
            print(f"ダウンロード再試行 ({k + 1}): {e}")
            time.sleep(20 * (k + 1))
