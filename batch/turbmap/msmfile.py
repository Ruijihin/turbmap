"""MSMのNetCDFファイルを、形式の違いを吸収して読む。

京大生存圏研究所のアーカイブは、2026年10月22日03UTC初期値から形式が変わった。
                旧形式                         新形式(wgrib2 で変換)
  次元・変数名  lat / lon、鉛直流 w            latitude / longitude、鉛直流 VVEL
  緯度の並び    北→南                          南→北
  時刻          初期時刻からの時間(hours)      1970年からの秒(reference_time に初期時刻)
  値            16bit整数 + scale_factor       32bit浮動小数点。欠測は 9.999e20
                                               (湿度は300hPaより上、地上の雨は初期時刻が欠測)
どちらの形式でも、緯度は北→南、時刻は初期時刻からの時間、欠測は置き換えた値で返す。
"""
import numpy as np
from scipy.io import netcdf_file

ALIASES = {"lat": ("lat", "latitude"), "lon": ("lon", "longitude"), "w": ("w", "VVEL")}
FILL_ABOVE = 1e19
FILL_VALUE = {"rh": 75.0}     # 欠測を置き換える値(湿度は旧形式と同じ75%。それ以外は0)


def _text(x):
    return x.decode() if isinstance(x, bytes) else str(x)


class MsmFile:
    def __init__(self, path):
        self.f = netcdf_file(path, "r", mmap=False)
        v = self.f.variables
        # 32bit で格納された座標(22.399999…)を丸める。範囲の判定(22.4度以上など)で端の行が外れないように
        lat = np.round(np.array(v[self._name("lat")][:], dtype=float), 5)
        self.flip = lat[0] < lat[-1]                  # 南→北なら、読むときに北→南へ並べ替える
        self.lat = lat[::-1].copy() if self.flip else lat.copy()
        self.lon = np.round(np.array(v[self._name("lon")][:], dtype=float), 5)
        t = v["time"]
        units = _text(t.units)
        if units.startswith("seconds since 1970") and hasattr(t, "reference_time"):
            self.hours = [round((float(x) - float(t.reference_time)) / 3600.0, 3) for x in t[:]]
            self.time_units = "hours since " + _text(getattr(t, "reference_date", "")).replace(".", "-")
        else:
            self.hours = [float(x) for x in t[:]]
            self.time_units = units
        self.lev = [float(x) for x in v["p"][:]] if "p" in v else []

    def _name(self, name):
        for n in ALIASES.get(name, (name,)):
            if n in self.f.variables:
                return n
        raise KeyError(name)

    def read(self, name, *idx):
        """name の値を返す(idx は time, [p] の添字)。緯度は北→南。"""
        var = self.f.variables[self._name(name)]
        a = np.array(var[idx], dtype=float)
        if hasattr(var, "scale_factor"):
            a = a * var.scale_factor + var.add_offset
        bad = a > FILL_ABOVE
        if bad.any():
            a[bad] = FILL_VALUE.get(name, 0.0)
        return a[::-1] if self.flip else a

    def close(self):
        self.f.close()
