"""「揺れる雲」の要素(対流・雲中の湿潤不安定)を計算する。

雲があるだけでは揺れない。揺れるのは次のような雲。
  - 対流:下層の空気に浮力(CAPE)があり、実際に強い雨や強い上昇流が起きている。
    雲底(自由対流高度)から雲頂(平衡高度)までと、雲頂のすぐ上(突き抜け)で揺れる。
    強い対流のまわり数十kmでも、対流が作る波で揺れることがある。
  - 雲中の湿潤不安定:飽和に近い層が、湿った空気として不安定(相当温位が上ほど低い)。
    層状の雲に隠れた対流や、不安定な中層雲を拾う。湿った空気として安定な雲は揺れにくい。
"""
import numpy as np
from scipy.io import netcdf_file
from scipy.ndimage import gaussian_filter, maximum_filter

from .msmfile import open_msm

G0 = 9.80665

THRESH_CV = {
    "cape": 500.0,      # J/kg   浮力の目安
    "rain": 10.0,       # mm/h   強い雨の目安(前後1時間の最大、周囲約25km)
    "wup": 1.0,         # m/s    強い上昇流の目安(850〜300hPaの、雲の中の最大)
    "rh_cloud": 90.0,   # %      上昇流を数える「雲の中」の相対湿度
    "nm2": 6e-5,        # s^-2   湿潤成層のマイナスの大きさ(相当温位が1kmで約2K下がる程度)
    "overshoot": 0.10,  # 雲頂の上、雲頂気圧の何割までを「突き抜け」とするか(約2,000ft)
}
PARCEL_LEVELS = [1000, 975, 950, 925, 900, 850, 800, 700]   # 持ち上げる空気を選ぶ高さ


def thetae(t, rh, p):
    """相当温位(K)。Bolton(1980)。t:K, rh:%, p:hPa"""
    rh = np.clip(rh, 1, 100)
    es = 6.112 * np.exp(17.67 * (t - 273.15) / (t - 29.65))
    e = rh / 100 * es
    r = 0.622 * e / (p - e)
    td = 243.5 * np.log(e / 6.112) / (17.67 - np.log(e / 6.112)) + 273.15
    tl = 1 / (1 / (td - 56) + np.log(t / td) / 800) + 56
    return t * (1000 / p) ** (0.2854 * (1 - 0.28 * r)) * np.exp((3.376 / tl - 0.00254) * r * 1000 * (1 + 0.81 * r))


def _moist_parcel_t(the, p, iters=24):
    """相当温位 the を保つ飽和した空気の、気圧 p での気温を二分法で求める。"""
    lo = np.full_like(the, 150.0)
    hi = np.full_like(the, 330.0)
    for _ in range(iters):
        mid = (lo + hi) / 2
        f = thetae(mid, 100.0, p) - the
        hi = np.where(f > 0, mid, hi)
        lo = np.where(f > 0, lo, mid)
    return (lo + hi) / 2


def parcel(levs, T, RH, Z, sp):
    """最も不安定な下層の空気を持ち上げ、CAPE・自由対流高度・平衡高度(雲頂)を求める。

    levs: 気圧面(hPa、下→上の順) / T,RH,Z: [層,緯度,経度] / sp: 地上気圧(hPa)
    戻り値: cape(J/kg), p_lfc(hPa), p_el(hPa)。対流が無い所は p_lfc=p_el=nan
    """
    nl = len(levs)
    src_the = np.full(sp.shape, -np.inf)
    src_k = np.zeros(sp.shape, int)
    for k, p in enumerate(levs):
        if p not in PARCEL_LEVELS:
            continue
        th = thetae(T[k], RH[k], p)
        ok = (p <= sp - 5) & (th > src_the)
        src_the = np.where(ok, th, src_the)
        src_k = np.where(ok, k, src_k)
    src_p = np.array(levs, float)[src_k]
    src_t = np.take_along_axis(T, src_k[None], 0)[0]

    B = np.full((nl,) + sp.shape, np.nan)       # 浮力(m/s^2)。持ち上げ始めより下は nan
    for k, p in enumerate(levs):
        above = p < src_p
        t_dry = src_t * (p / src_p) ** 0.2857
        t_moist = _moist_parcel_t(src_the, p)
        tp = np.maximum(t_dry, t_moist)           # 持ち上げ凝結高度より下は乾燥、上は湿潤断熱
        B[k] = np.where(above, G0 * (tp - T[k]) / T[k], np.nan)

    cape = np.zeros(sp.shape)
    for k in range(nl - 1):
        b0, b1 = np.nan_to_num(B[k]), np.nan_to_num(B[k + 1])
        cape += 0.5 * (np.maximum(b0, 0) + np.maximum(b1, 0)) * np.maximum(Z[k + 1] - Z[k], 0)

    p_lfc = np.full(sp.shape, np.nan)
    p_el = np.full(sp.shape, np.nan)
    for k in range(nl):                            # 下から順に
        bk = B[k]
        pos = np.nan_to_num(bk) > 0
        first = pos & np.isnan(p_lfc)
        p_lfc = np.where(first, levs[k], p_lfc)
        if k + 1 < nl:                             # 正→負に変わる所を平衡高度とする(線形補間)
            b1 = B[k + 1]
            cross = pos & ~(np.nan_to_num(b1) > 0)
            frac = np.where(cross, bk / np.maximum(bk - np.nan_to_num(b1), 1e-9), 0)
            pe = levs[k] + (levs[k + 1] - levs[k]) * np.clip(frac, 0, 1)
            p_el = np.where(cross, pe, p_el)       # いちばん上の交差が残る
        else:
            p_el = np.where(pos, levs[k], p_el)
    weak = cape < 25
    p_lfc = np.where(weak, np.nan, p_lfc)
    p_el = np.where(weak, np.nan, p_el)
    return cape, p_lfc, p_el


def column_weight(pa, pb, p_lfc, p_el):
    """層 [pb, pa](hPa)のうち、雲の柱(自由対流高度〜平衡高度)と突き抜けの部分にかかる割合。"""
    thick = pa - pb
    lo_p = np.nan_to_num(p_lfc, nan=-1)          # 雲底側(大きい気圧)
    hi_p = np.nan_to_num(p_el, nan=1e9)          # 雲頂側(小さい気圧)
    inside = np.clip(np.minimum(pa, lo_p) - np.maximum(pb, hi_p), 0, None) / thick
    os_top = hi_p * (1 - THRESH_CV["overshoot"])
    over = np.clip(np.minimum(pa, hi_p) - np.maximum(pb, os_top), 0, None) / thick
    w = np.clip(inside + 0.6 * over, 0, 1)
    return np.where(np.isnan(p_el), 0, w)


class MsmSurfaceFile:
    """地上ファイル(毎時)。地上気圧と1時間降水量を、気圧面の格子に合わせて返す。"""

    NAMES = ["sp", "r1h", "u", "v", "ncld_low", "ncld_mid", "ncld_upper"]

    def __init__(self, path, max_hour=None):
        # 形式の違い(NetCDFの新旧・GRIB2)を吸収して、緯度は北→南で読む
        self.m = open_msm(path, self.NAMES, max_hour)
        self.hours = self.m.hours

    def _rd(self, name, it):
        return self.m.read(name, it)

    def sp_hpa(self, hour):
        it = self.hours.index(hour)
        return self._rd("sp", it)[::2, ::2] / 100

    def rain_max(self, hour):
        """前後1時間(hour と hour+1 の1時間降水量)の最大を、周囲約25kmの最大で広げる。"""
        its = [self.hours.index(h) for h in (hour, hour + 1) if h in self.hours]
        r = np.max([np.maximum(self._rd("r1h", i), 0) for i in its], axis=0)
        r = maximum_filter(r, size=5)              # 地上ファイルは約5km格子
        return r[::2, ::2]

    def cloud(self, name, hour):
        """モデルの雲量(%)。古い形式に無いときは0。"""
        try:
            return self._rd(name, self.hours.index(hour))[::2, ::2]
        except KeyError:
            return np.zeros_like(self._rd("sp", self.hours.index(hour))[::2, ::2])

    def wind10_max(self, hour):
        """地上10mの風速(kt)。前後1時間の最大を、周囲約15kmの最大で広げる。"""
        its = [self.hours.index(h) for h in (hour, hour + 1) if h in self.hours]
        w = np.max([np.hypot(self._rd("u", i), self._rd("v", i)) for i in its], axis=0) * 1.94384
        w = maximum_filter(w, size=3)
        return w[::2, ::2]

    def close(self):
        self.m.close()


def convective_layers(levs, T, RH, Z, W, sp, rain, pairs, rho_of):
    """対流の指数を層ごとに返す。あわせて補助の2次元量も返す。

    W: 鉛直流(Pa/s)[層,..] / rain: mm/h / pairs: 層の気圧面の組 / rho_of(k): 空気の密度
    """
    cape, p_lfc, p_el = parcel(levs, T, RH, Z, sp)
    cape = gaussian_filter(cape, 1.0)
    # 実際に対流が起きている兆候:強い雨か、強い上昇流
    # 上昇流は、飽和した層(雲の中)のものだけ数える。山岳波などで乾いた空気が持ち上がる分は対流ではない
    wup = np.zeros(sp.shape)
    for k, p in enumerate(levs):
        if 300 <= p <= 850:
            w_ms = -W[k] / (rho_of(k) * G0)
            incloud = (p <= sp - 5) & (RH[k] >= THRESH_CV["rh_cloud"])
            wup = np.maximum(wup, np.where(incloud, w_ms, 0))
    act = np.maximum(rain / THRESH_CV["rain"], wup / THRESH_CV["wup"])
    col = np.sqrt(np.clip(cape / THRESH_CV["cape"], 0, None) * np.clip(act, 0, None))
    out = []
    for pa, pb in pairs:
        local = col * column_weight(pa, pb, p_lfc, p_el)
        near = 0.5 * maximum_filter(local, size=5)  # 周囲約50km
        out.append(np.maximum(local, near))
    el_fl = np.where(np.isnan(p_el), 0, 44330.8 * (1 - (np.nan_to_num(p_el, nan=1013.25) / 1013.25) ** 0.190263) / 30.48)
    aux = {"cape": cape, "el_fl": el_fl, "rain": rain, "wup": wup}
    return out, aux


def moist_instability(ta, tb, rha, rhb, za, zb, pa, pb, rhi):
    """層の湿潤不安定の指数。飽和に近い(氷相対湿度85%以上)層で、相当温位が上ほど低いほど大きい。"""
    tha, thb = thetae(ta, rha, pa), thetae(tb, rhb, pb)
    nm2 = G0 / ((tha + thb) / 2) * (thb - tha) / (zb - za)
    sat = np.clip((rhi - 85) / 10, 0, 1)
    return sat * np.clip(-nm2, 0, None) / THRESH_CV["nm2"]
