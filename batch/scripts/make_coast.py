"""web/coast.json(簡易海岸線)を作り直す。表示範囲(diag.DOMAIN)を変えたときに使う。

MSMの地上ファイル(MSMyyyymmddhhS.nc)の、海面気圧と地上気圧の差から陸地を判定して輪郭を取る。
使い方: python batch/scripts/make_coast.py MSM2026102009S.nc web/coast.json
"""
import json
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from scipy.io import netcdf_file  # noqa: E402
from scipy.ndimage import gaussian_filter  # noqa: E402

sys.path.insert(0, __file__.rsplit("scripts", 1)[0])
from turbmap.diag import DOMAIN  # noqa: E402
from turbmap.msmfile import open_msm  # noqa: E402


def main(src, dst):
    f = open_msm(src)                      # NetCDFの新旧・GRIB2のどれでも、緯度は北→南
    lat, lon = f.lat, f.lon

    def rd(n):
        return f.read(n, 0)

    land = gaussian_filter((rd("psea") - rd("sp")) / 100, 1.0)
    cs = plt.contour(lon, lat, land, levels=[1.0])
    lines = []
    for p in cs.allsegs[0]:
        if len(p) < 10:
            continue
        m = ((p[:, 0] >= DOMAIN["lon_min"] - 0.1) & (p[:, 0] <= DOMAIN["lon_max"] + 0.1)
             & (p[:, 1] >= DOMAIN["lat_min"] - 0.1) & (p[:, 1] <= DOMAIN["lat_max"] + 0.1))
        if m.sum() < 4:
            continue
        lines.append([[round(float(x), 2), round(float(y), 2)] for x, y in p[::2]])
    with open(dst, "w", encoding="utf-8") as g:
        json.dump({"source": "MSM地上データの海面気圧と地上気圧の差から作った簡易海岸線", "lines": lines},
                  g, ensure_ascii=False, separators=(",", ":"))
    print(f"{dst}: {len(lines)}本")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
