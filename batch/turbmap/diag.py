"""MSM気圧面データ(と地上データ)から揺れやすさの要素を計算する。

出力は要素ごとの「強さの指数」(並=1.0)を0.01刻みの整数(0〜255)にした配列。
配列の形は [予報時刻, 層, 要素, 緯度, 経度]。
あわせて、高さに関係しない補助の量(CAPE・雲頂・雨・上昇流)を [予報時刻, 量, 緯度, 経度] で返す。
"""
import numpy as np
from scipy.io import netcdf_file
from scipy.ndimage import gaussian_filter, uniform_filter

from . import convect

G0 = 9.80665
RD = 287.05
OMEGA = 7.292e-5
EARTH_R = 6371e3

# 上下の気圧面の組(hPa)。層の値はこの2面の間の量。
LAYER_PAIRS = [(700, 600), (600, 500), (500, 400), (400, 300), (300, 250), (250, 200), (200, 150)]
ELEMS = ["mw", "ii", "df", "ri", "vws", "rhi", "cv", "mi"]
MISSING_ELEMS = ["rhi", "mi"]          # 湿度を使うので、300hPaより上は「データなし」
# 補助の量:名前と、画素値に掛けると元の単位になる係数
AUX = [("cape", 40.0), ("el_fl", 2.0), ("rain", 0.2), ("wup", 0.02)]   # J/kg, FL, mm/h, m/s

# 「並(moderate)相当」の目安。指数 = 値 / 目安。
THRESH = {
    "sigma_w": 0.25,   # m/s   鉛直流の細かい揺らぎ(山岳波・重力波)
    "eta_f": -0.25,    # 絶対渦度/f(慣性不安定)。0.25から-0.25までを0→1に対応させる
    "ti1": 8.0,        # 1e-7 s^-2  Ellrod TI1(変形場)
    "ri": 0.75,        # リチャードソン数
    "vws": 6.0,        # kt/1000ft
}

# 表示範囲。MSM気圧面の範囲(北緯22.4〜47.6度、東経120〜150度)のうち、
# 北海道より北・東を除いた部分。石垣島・台湾(南端を除く)・朝鮮半島が入る。
# MSM気圧面の湿度は300hPaまでしか実データが無い(250hPa以上は全マスが一定値75%)。
RH_MIN_P = 300
RH_MISSING = 255   # 数値データ中の「データなし」の印(通常の値は0〜254)

DOMAIN = {"lat_min": 22.4, "lat_max": 46.0, "lon_min": 120.0, "lon_max": 147.0}


def isa_flight_level(p_hpa):
    """気圧(hPa)を標準大気の気圧高度(フライトレベル、100ft単位)に変換する。"""
    h = 44330.8 * (1 - (p_hpa / 1013.25) ** 0.190263)
    return h / 0.3048 / 100


def _esw(t):
    return 6.112 * np.exp(17.67 * (t - 273.15) / (t - 29.65))


def _esi(t):
    return 6.112 * np.exp(22.46 * (t - 273.15) / (t - 0.53))


class MsmPressureFile:
    def __init__(self, path):
        self.f = netcdf_file(path, "r", mmap=False)
        v = self.f.variables
        self.lat = v["lat"][:].copy()
        self.lon = v["lon"][:].copy()
        self.lev = [float(x) for x in v["p"][:]]
        self.hours = [float(x) for x in v["time"][:]]
        self.time_units = v["time"].units.decode() if isinstance(v["time"].units, bytes) else v["time"].units

    def read(self, name, it, p):
        var = self.f.variables[name]
        a = np.array(var[it, self.lev.index(float(p))], dtype=float)
        if hasattr(var, "scale_factor"):
            a = a * var.scale_factor + var.add_offset
        return a

    def close(self):
        self.f.close()


def compute_run(path, spath=None, ft_min=3):
    """1つの初期値ファイルについて、FT>=ft_minの全予報時刻を計算する。

    MSMのFT=0は鉛直流がゼロなので使わない。spath(地上ファイル)が無いときは、
    雨を使わずに上昇流だけで対流の兆候を見る。
    戻り値: (uint8配列[T,L,E,ny,nx], uint8配列[T,補助,ny,nx], 情報dict)
    """
    m = MsmPressureFile(path)
    sfc = convect.MsmSurfaceFile(spath) if spath else None
    lat, lon = m.lat, m.lon
    dy = np.deg2rad(lat[0] - lat[1]) * EARTH_R           # 緯度は北から南の順
    dx = np.deg2rad(lon[1] - lon[0]) * EARTH_R * np.cos(np.deg2rad(lat))[:, None]
    fcor = 2 * OMEGA * np.sin(np.deg2rad(lat))[:, None]

    def ddx(a):
        return np.gradient(a, axis=-1) / dx

    def ddy(a):
        return -np.gradient(a, axis=-2) / dy

    jj = np.where((lat >= DOMAIN["lat_min"]) & (lat <= DOMAIN["lat_max"]))[0]
    ii = np.where((lon >= DOMAIN["lon_min"]) & (lon <= DOMAIN["lon_max"]))[0]
    t_idx = [k for k, h in enumerate(m.hours) if h >= ft_min]

    out = np.zeros((len(t_idx), len(LAYER_PAIRS), len(ELEMS), len(jj), len(ii)), dtype=np.uint8)
    aux_out = np.zeros((len(t_idx), len(AUX), len(jj), len(ii)), dtype=np.uint8)
    sm = lambda x: gaussian_filter(x, 1.5)
    levs = m.lev                                           # 下→上(1000→100hPa)

    for a_t, it in enumerate(t_idx):
        hour = m.hours[it]
        # ---- 揺れる雲:対流(CAPE×対流の兆候、雲の柱の高さで重み付け)
        T = np.stack([m.read("temp", it, p) for p in levs])
        RH = np.stack([m.read("rh", it, p) for p in levs])
        Z = np.stack([m.read("z", it, p) for p in levs])
        W = np.stack([m.read("w", it, p) for p in levs])
        sp = sfc.sp_hpa(hour)[: len(lat), : len(lon)] if sfc else np.full(T.shape[1:], 1013.0)
        rain = sfc.rain_max(hour)[: len(lat), : len(lon)] if sfc else np.zeros(T.shape[1:])
        cv_layers, aux = convect.convective_layers(
            levs, T, RH, Z, W, sp, rain, LAYER_PAIRS, lambda k: levs[k] * 100 / (RD * T[k]))
        for a_x, (name, scale) in enumerate(AUX):
            aux_out[a_t, a_x] = np.clip(np.round(aux[name][np.ix_(jj, ii)] / scale), 0, 255).astype(np.uint8)

        for a_l, (pa, pb) in enumerate(LAYER_PAIRS):
            ta, tb = sm(m.read("temp", it, pa)), sm(m.read("temp", it, pb))
            ua, ub = sm(m.read("u", it, pa)), sm(m.read("u", it, pb))
            va, vb = sm(m.read("v", it, pa)), sm(m.read("v", it, pb))
            za, zb = sm(m.read("z", it, pa)), sm(m.read("z", it, pb))
            wa, wb = m.read("w", it, pa), m.read("w", it, pb)
            rha, rhb = m.read("rh", it, pa), m.read("rh", it, pb)

            tha, thb = ta * (1000 / pa) ** 0.2857, tb * (1000 / pb) ** 0.2857
            dz = zb - za
            n2 = G0 / ((tha + thb) / 2) * (thb - tha) / dz
            s2 = ((ub - ua) / dz) ** 2 + ((vb - va) / dz) ** 2
            vws = np.sqrt(s2)

            um, vm = (ua + ub) / 2, (va + vb) / 2
            ux, uy, vx, vy = ddx(um), ddy(um), ddx(vm), ddy(vm)
            deform = np.sqrt((ux - vy) ** 2 + (vx + uy) ** 2)
            zeta = vx - uy
            ti1 = vws * deform * 1e7
            ri = n2 / np.maximum(s2, 1e-10)
            eta_f = (fcor + zeta) / fcor

            tm = (ta + tb) / 2
            rho = ((pa + pb) / 2) * 100 / (RD * tm)
            w_ms = -((wa + wb) / 2) / (rho * G0)
            w_pert = w_ms - gaussian_filter(w_ms, 6)          # 約60kmより大きい動きを除く
            sigma_w = np.sqrt(uniform_filter(w_pert ** 2, 5))
            rhi = ((rha + rhb) / 2) * _esw(tm) / _esi(tm)

            score = {
                "mw": sigma_w / THRESH["sigma_w"],
                "ii": np.clip((0.25 - eta_f) / 0.5, 0, None),
                "df": ti1 / THRESH["ti1"],
                "ri": THRESH["ri"] / np.maximum(ri, 0.05),
                "vws": vws * 0.3048 * 1.94384 * 1000 / THRESH["vws"],
                "rhi": rhi / 100,
                "cv": cv_layers[a_l],
                "mi": convect.moist_instability(ta, tb, rha, rhb, za, zb, pa, pb, rhi),
            }
            for a_e, e in enumerate(ELEMS):
                x = score[e][np.ix_(jj, ii)]
                out[a_t, a_l, a_e] = np.clip(np.round(x * 100), 0, 254).astype(np.uint8)
            if min(pa, pb) < RH_MIN_P:
                # MSMの湿度は300hPaより上では欠測(全マスが一定値)なので、氷相対湿度は「データなし」にする
                for e in MISSING_ELEMS:
                    out[a_t, a_l, ELEMS.index(e)] = RH_MISSING

    mids = [float(np.exp((np.log(a) + np.log(b)) / 2)) for a, b in LAYER_PAIRS]
    info = {
        "ft": [int(m.hours[k]) for k in t_idx],
        "time_units": m.time_units,
        "layers": [[a, b] for a, b in LAYER_PAIRS],
        "mid_p": [round(p, 1) for p in mids],
        "mid_fl": [round(isa_flight_level(p), 1) for p in mids],
        "lat0": round(float(lat[jj[0]]), 4),
        "lon0": round(float(lon[ii[0]]), 4),
        "dlat": round(float(lat[1] - lat[0]), 4),
        "dlon": round(float(lon[1] - lon[0]), 4),
        "ny": int(len(jj)),
        "nx": int(len(ii)),
        "elems": ELEMS,
        "scale": 0.01,
        "missing": RH_MISSING,
        "rhi_valid_max_fl": round(isa_flight_level(RH_MIN_P), 1),   # これより上は氷相対湿度なし
        "rhi_valid_layers": sum(1 for a, b in LAYER_PAIRS if min(a, b) >= RH_MIN_P),
        "missing_elems": MISSING_ELEMS,
        "aux": [a for a, _ in AUX],
        "aux_scale": [s for _, s in AUX],
        "thresholds": dict(THRESH, **convect.THRESH_CV),
        "surface": bool(sfc),
    }
    m.close()
    if sfc:
        sfc.close()
    return out, aux_out, info
