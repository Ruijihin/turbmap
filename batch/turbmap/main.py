"""揺れやすさ地図のバッチ処理。

例:
  python -m turbmap.main --init auto --r2                 # 新しい初期値を探して処理し、R2へ
  python -m turbmap.main --init 2026102009 --out ./out    # 指定した初期値をローカルへ
  python -m turbmap.main --init 2026102009 --file MSM2026102009P.nc --out ./out
"""
import argparse
import io
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

import numpy as np
from PIL import Image

from . import diag, rish
from .store import LocalStore, R2Store

INDEX_KEY = "index.json"
PNG_WIDTH = 4096


def pack_png(arr):
    """uint8配列を、劣化なしのグレースケールPNGに詰める(ブラウザで数値として読み戻す)。"""
    flat = arr.ravel()
    h = -(-flat.size // PNG_WIDTH)
    buf = np.zeros(h * PNG_WIDTH, np.uint8)
    buf[: flat.size] = flat
    bio = io.BytesIO()
    Image.fromarray(buf.reshape(h, PNG_WIDTH), "L").save(bio, format="PNG", optimize=True)
    data = bio.getvalue()
    check = np.array(Image.open(io.BytesIO(data))).ravel()[: flat.size]
    if not np.array_equal(check, flat):
        raise RuntimeError("PNGへの詰め込みで値が変わりました")
    return data


def init_dt(init):
    return datetime.strptime(init, "%Y%m%d%H").replace(tzinfo=timezone.utc)


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%MZ")


def process(init, store, nc_path=None):
    tmp = None
    if nc_path is None:
        tmp = tempfile.NamedTemporaryFile(suffix=".nc", delete=False)
        tmp.close()
        print(f"[{init}] ダウンロード: {rish.file_url(init)}")
        rish.download(init, tmp.name)
        nc_path = tmp.name
    try:
        print(f"[{init}] 計算")
        arr, info = diag.compute_run(nc_path)
    finally:
        if tmp:
            os.unlink(tmp.name)
    t0 = init_dt(init)
    valid = [iso(t0 + timedelta(hours=h)) for h in info["ft"]]
    meta = dict(info, init=init, init_iso=iso(t0), valid=valid,
                generated=iso(datetime.now(timezone.utc)),
                source="気象庁MSM(京都大学生存圏研究所 経由)")
    prefix = f"runs/{init}/"
    files, total = [], 0
    # 予報時刻ごとに1ファイル(ページは選んだ時刻の分だけ読み込む)
    for k, ft in enumerate(info["ft"]):
        png = pack_png(arr[k])
        name = f"ft{ft:02d}.png"
        store.put(prefix + name, png, "image/png", "public, max-age=31536000, immutable")
        files.append(name)
        total += len(png)
    meta["files"] = files
    store.put(prefix + "meta.json", json.dumps(meta, ensure_ascii=False, separators=(",", ":")).encode(),
              "application/json", "public, max-age=31536000, immutable")
    print(f"[{init}] 保存: {total / 1e6:.2f}MB, 予報時刻{len(valid)}個")
    return {"init": init, "init_iso": meta["init_iso"], "ft": info["ft"], "valid": valid}


def update_index(store, new_entries, retention_days):
    idx = store.get_json(INDEX_KEY) or {"version": 1, "runs": []}
    runs = {r["init"]: r for r in idx["runs"]}
    for e in new_entries:
        runs[e["init"]] = e
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    keep, drop = [], []
    for r in sorted(runs.values(), key=lambda r: r["init"], reverse=True):
        (keep if init_dt(r["init"]) >= cutoff else drop).append(r)
    for r in drop:
        print(f"[{r['init']}] 保存期間を過ぎたので削除")
        store.delete_prefix(f"runs/{r['init']}/")
    idx = {"version": 1, "updated": iso(datetime.now(timezone.utc)), "retention_days": retention_days, "runs": keep}
    store.put(INDEX_KEY, json.dumps(idx, ensure_ascii=False, separators=(",", ":")).encode(),
              "application/json", "no-cache")
    return idx


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--init", default="auto", help="auto または YYYYMMDDHH(UTC)")
    ap.add_argument("--file", help="手元のMSM気圧面ファイルを使う(--init と一緒に指定)")
    ap.add_argument("--out", help="ローカルフォルダに出力する")
    ap.add_argument("--r2", action="store_true", help="Cloudflare R2 に出力する")
    ap.add_argument("--retention-days", type=int, default=int(os.environ.get("RETENTION_DAYS", 60)))
    ap.add_argument("--max-runs", type=int, default=2, help="auto のとき、1回で処理する最大件数")
    ap.add_argument("--force", action="store_true", help="処理済みでもやり直す")
    a = ap.parse_args(argv)

    if bool(a.out) == bool(a.r2):
        ap.error("--out か --r2 のどちらか一方を指定してください")
    store = R2Store() if a.r2 else LocalStore(a.out)

    if a.init == "auto":
        done = {r["init"] for r in (store.get_json(INDEX_KEY) or {}).get("runs", [])}
        todo = [i for i in rish.list_inits() if a.force or i not in done][: a.max_runs]
        todo = [i for i in todo if rish.is_stable(i)]
        if not todo:
            print("新しい初期値はありません")
            return 0
    else:
        todo = [a.init]

    entries = []
    for init in sorted(todo):
        entries.append(process(init, store, a.file if a.init != "auto" else None))
    idx = update_index(store, entries, a.retention_days)
    print(f"一覧を更新しました(保存中 {len(idx['runs'])} 件)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
