"""京大生存圏研究所アーカイブの、気象庁MSM元データ(GRIB2)の一覧取得とダウンロード。

以前は同じアーカイブの NetCDF(latest/YYYYMMDD/MSMyyyymmddhhP.nc)を使っていたが、
2026年10月22日03UTC初期値を最後に変換が止まったため、元のGRIB2(original/YYYY/MM/DD/)を使う。
1つの初期値は、予報時間で分かれた複数のファイルからなる。
"""
import re
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import requests

BASE = "https://database.rish.kyoto-u.ac.jp/arch/jmadata/data/gpv/original/"
UA = {"User-Agent": "turbmap-batch (+https://github.com/)"}
# 種類ごとのファイル(予報時間の範囲, ファイル名の部分)。気圧面は3時間ごと、地上は1時間ごと
PARTS = {
    "P": [(15, "L-pall_FH00-15"), (33, "L-pall_FH18-33")],
    "S": [(15, "Lsurf_FH00-15"), (33, "Lsurf_FH16-33")],
}


def _day_url(day):
    return f"{BASE}{day[:4]}/{day[4:6]}/{day[6:8]}/"


def parts(kind, max_hour):
    """max_hour までの予報時間に必要なファイル名の部分"""
    out = []
    for last, name in PARTS[kind]:
        out.append(name)
        if last >= max_hour:
            break
    return out


def file_urls(init, kind="P", max_hour=33):
    """kind: "P"=気圧面、"S"=地上。max_hour までに必要なファイルのURLの並び"""
    return [f"{_day_url(init)}Z__C_RJTD_{init}0000_MSM_GPV_Rjp_{p}_grib2.bin" for p in parts(kind, max_hour)]


def list_inits(ft_max=33, days=2):
    """直近days日分のフォルダから、必要なファイルがそろっている初期時刻(YYYYMMDDHH)を新しい順に返す。"""
    now = datetime.now(timezone.utc)
    need = parts("P", ft_max) + parts("S", ft_max + 1)
    inits = []
    for d in range(days):
        day = (now - timedelta(days=d)).strftime("%Y%m%d")
        r = requests.get(_day_url(day), headers=UA, timeout=60)
        if r.status_code == 404:
            continue
        r.raise_for_status()
        have = {}
        for init, p in re.findall(r'href="Z__C_RJTD_(\d{10})0000_MSM_GPV_Rjp_([^"]+)_grib2\.bin"', r.text):
            have.setdefault(init, set()).add(p)
        inits += [i for i, ps in have.items() if all(p in ps for p in need)]
    return sorted(set(inits), reverse=True)


def is_stable(init, ft_max=33, min_age_minutes=10):
    """掲載直後(書き込み途中の可能性)を避けるため、必要なファイルがすべて掲載から一定時間たっているか確かめる。"""
    for url in file_urls(init, "P", ft_max) + file_urls(init, "S", ft_max + 1):
        r = requests.head(url, headers=UA, timeout=60)
        if r.status_code == 404:
            return False
        r.raise_for_status()
        lm = r.headers.get("Last-Modified")
        if lm and datetime.now(timezone.utc) - parsedate_to_datetime(lm) < timedelta(minutes=min_age_minutes):
            return False
    return True


def download(url, dest, retries=3):
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
