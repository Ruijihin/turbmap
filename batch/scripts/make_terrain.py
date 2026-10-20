"""web/terrain.png と web/terrain.json を作る(山岳波の評価に使う「地形の影響圏」)。

MSMの地上ファイル(MSMyyyymmddhhS.nc)の、海面気圧と地上気圧の差から地形の高さの目安を出し、
標高の高い場所とその周辺(約50km)を「地形の影響圏」として 0〜1 にする。
値は 0〜255 の画素値で、気圧面の格子(diag.py の DOMAIN と同じ範囲・間隔)に合わせてある。

使い方: python batch/scripts/make_terrain.py MSM2026102009S.nc web
"""
import json
import sys

import numpy as np
from PIL import Image
from scipy.io import netcdf_file
from scipy.ndimage import gaussian_filter

sys.path.insert(0, __file__.rsplit("scripts", 1)[0])
from turbmap.diag import DOMAIN  # noqa: E402

HEIGHT_THRESHOLD_M = 400      # これより高い所を「山」とみなす
SMOOTH_CELLS = 2.0            # 地形を平滑化する幅(約25km)
INFLUENCE_CELLS = 4.0         # 山の周辺に広げる幅(約50km)
FULL_AT = 0.3                 # 影響の強さがこの値以上で「完全に地形の影響圏」


def main(src, outdir):
    f = netcdf_file(src, "r", mmap=False)
    lat = f.variables["lat"][:].copy()[::2]       # 地上ファイルは気圧面の2倍の細かさ
    lon = f.variables["lon"][:].copy()[::2]

    def rd(name):
        v = f.variables[name]
        return (np.array(v[0], float) * v.scale_factor + v.add_offset)[::2, ::2]

    psea, sp, t = rd("psea"), rd("sp"), rd("temp")
    h = 29.3 * (t + 3.0) * np.log(psea / sp)      # 地形の高さ(m)の目安
    jj = np.where((lat >= DOMAIN["lat_min"]) & (lat <= DOMAIN["lat_max"]))[0]
    ii = np.where((lon >= DOMAIN["lon_min"]) & (lon <= DOMAIN["lon_max"]))[0]
    h = h[np.ix_(jj, ii)]
    hs = gaussian_filter(h, SMOOTH_CELLS)
    zone = gaussian_filter((hs > HEIGHT_THRESHOLD_M).astype(float), INFLUENCE_CELLS)
    zf = np.clip(zone / FULL_AT, 0, 1)

    Image.fromarray(np.round(zf * 255).astype(np.uint8), "L").save(f"{outdir}/terrain.png", optimize=True)
    info = {
        "nx": int(len(ii)), "ny": int(len(jj)),
        "lat0": round(float(lat[jj[0]]), 4), "lon0": round(float(lon[ii[0]]), 4),
        "note": "地形の影響圏(0〜1を0〜255で格納)。海面気圧と地上気圧の差から出した地形の高さの目安で、"
                f"{HEIGHT_THRESHOLD_M}m超の場所とその周辺約50kmを1にする",
        "max_height_m": round(float(hs.max())),
    }
    with open(f"{outdir}/terrain.json", "w", encoding="utf-8") as g:
        json.dump(info, g, ensure_ascii=False, separators=(",", ":"))
    print(f"{outdir}/terrain.png {info['nx']}x{info['ny']} 影響圏の割合 {100 * (zf > 0.5).mean():.1f}%")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
