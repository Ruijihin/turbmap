"""気象庁のMSM GRIB2(元データ)を、MsmFile と同じ形で読む。

京大生存圏研究所のアーカイブでは、NetCDFへの変換が止まることがある(2026年10月22日03UTC初期値の後など)。
元のGRIB2は original/YYYY/MM/DD/ に毎回届くので、こちらを使う。NetCDFより小さい(約4割)。
  気圧面: Z__C_RJTD_YYYYMMDDhh0000_MSM_GPV_Rjp_L-pall_FH00-15_grib2.bin と FH18-33(3時間ごと)
  地上:   Z__C_RJTD_YYYYMMDDhh0000_MSM_GPV_Rjp_Lsurf_FH00-15_grib2.bin と FH16-33(1時間ごと)
気象庁のファイルは、1つのGRIBメッセージに多数の量が入った形(マルチフィールド)なので、
ecCodes のマルチフィールド読み込みを有効にして読む。
"""
import numpy as np
import eccodes as ec

# NetCDF(京大の変換)の変数名 → GRIB2の(分類, 番号)
PARAMS = {
    "z": (3, 5), "u": (2, 2), "v": (2, 3), "temp": (0, 0), "w": (2, 8), "VVEL": (2, 8), "rh": (1, 1),
    "psea": (3, 1), "sp": (3, 0), "ncld_low": (6, 3), "ncld_mid": (6, 4), "ncld_upper": (6, 5),
    "nclda": (6, 1), "r1h": (1, 8), "dswrf": (4, 7),
}
FILL_VALUE = {"rh": 75.0}     # 無い量の代わりの値(湿度は300hPaより上が無い。MsmFile と同じ75%)


def is_grib(path):
    with open(path, "rb") as f:
        return f.read(4) == b"GRIB"


class MsmGribFile:
    """paths: 同じ初期値・同じ種類(気圧面か地上)のGRIB2ファイルの並び。
    names を指定すると、その量だけを読み込む(メモリの節約)。max_hour より先の予報時間は読まない。"""

    def __init__(self, paths, names=None, max_hour=None):
        want = {PARAMS[n] for n in names} if names else None
        self.fields = {}
        levs, hours = set(), set()
        ec.codes_grib_multi_support_on()
        self.lat = self.lon = None
        for path in paths:
            with open(path, "rb") as f:
                while True:
                    h = ec.codes_grib_new_from_file(f)
                    if h is None:
                        break
                    try:
                        key = (ec.codes_get(h, "parameterCategory"), ec.codes_get(h, "parameterNumber"))
                        # 積算量(1時間降水量など)は期間の終わりの時刻に置く(京大のNetCDFと同じ)
                        hour = float(ec.codes_get(h, "endStep"))
                        if max_hour is not None and hour > max_hour:
                            continue
                        pl = ec.codes_get_long(h, "typeOfFirstFixedSurface") == 100   # 気圧面
                        lev = float(ec.codes_get(h, "level")) if pl else None
                        if pl:
                            levs.add(lev)
                        if ec.codes_get(h, "stepType") == "instant" or not pl:
                            hours.add(hour)
                        if self.lat is None:
                            self._grid(h)
                        if want is not None and key not in want:
                            continue
                        a = ec.codes_get_values(h).reshape(self.ny, self.nx).astype(np.float32)
                        if self.flip:
                            a = a[::-1]
                        self.fields[(key, hour, lev)] = a
                    finally:
                        ec.codes_release(h)
        self.lev = sorted(levs, reverse=True)          # 下→上(1000→100hPa)。NetCDFと同じ並び
        self.hours = sorted(hours)
        self.time_units = "hours since " + self.init_iso

    def _grid(self, h):
        self.nx, self.ny = ec.codes_get(h, "Ni"), ec.codes_get(h, "Nj")
        la1 = ec.codes_get(h, "latitudeOfFirstGridPointInDegrees")
        la2 = ec.codes_get(h, "latitudeOfLastGridPointInDegrees")
        lo1 = ec.codes_get(h, "longitudeOfFirstGridPointInDegrees")
        lo2 = ec.codes_get(h, "longitudeOfLastGridPointInDegrees")
        self.flip = la1 < la2                          # 南→北なら北→南へ並べ替える
        lat = np.round(np.linspace(la1, la2, self.ny), 5)
        self.lat = lat[::-1].copy() if self.flip else lat
        self.lon = np.round(np.linspace(lo1, lo2, self.nx), 5)
        d, t = str(ec.codes_get(h, "dataDate")), ec.codes_get(h, "dataTime")
        self.init_iso = f"{d[:4]}-{d[4:6]}-{d[6:]} {t // 100:02d}:{t % 100:02d}:00 UTC"

    def read(self, name, *idx):
        """name の値を返す(idx は time, [p] の添字)。緯度は北→南。無い量は置き換えた値。"""
        if name not in PARAMS:
            raise KeyError(name)
        key = PARAMS[name]
        hour = self.hours[idx[0]]
        lev = self.lev[idx[1]] if len(idx) > 1 else None
        a = self.fields.get((key, hour, lev))
        if a is None:
            if not any(k[0] == key for k in self.fields):
                raise KeyError(name)                   # ファイルに無い量(読み込み対象外も含む)
            return np.full((self.ny, self.nx), FILL_VALUE.get(name, 0.0))
        return a.astype(float)

    def close(self):
        self.fields = {}
