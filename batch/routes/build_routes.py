"""定義ルート(社内のルート表)を、FIXの並びに展開して routes.json を作る。

入力
  --sheet    ルート表のCSV(列:出発地,目的地,ルート番号,飛行経路)。URL でもよい
  --jp-kml   日本のAIPのKMLを置いたフォルダ(RNAV_ROUTES / ATS_ROUTES / REP_WPT / RADIO_NAVIGATION_AIDS の *.kml)
  --kr-html  韓国のeAIPから保存した KR-ENR-3.1/3.3/3.5/4.4 の HTML を置いたフォルダ(ENR-3.1.html などの名前)
  --tw       台湾のAIPから写した地点・航空路(batch/routes/taiwan_aip.txt)
  --extra    手で補う地点(batch/routes/extra_points.txt)
  --route-no 展開するルート番号(既定 1)
出力
  routes.json(R2 の routes/routes.json に置く。ルート表は社内情報なので Git には入れない)

展開のしかた
  - 航空路は、入るFIXと出るFIXのあいだの地点を、航空路のつながり(日本:KML の区間、韓国・台湾:AIP の表の順)で探して展開する
  - SID/STAR は省き、空港と最初・最後の地点を直線で結ぶ
  - 座標が見つからない地点(空港周辺の手順用FIX、範囲外の国など)は飛ばし、前後を直線で結ぶ(その区間に近似の印を付ける)
"""
import argparse
import collections
import csv
import glob
import html
import io
import json
import os
import re
import urllib.request

AW = re.compile(r"[A-Z]{1,2}\d{1,4}[A-Z]?$")


def dms(lat, lon):
    la = int(lat[:2]) + int(lat[2:4]) / 60 + float(lat[4:6]) / 3600
    lo = int(lon[:3]) + int(lon[3:5]) / 60 + float(lon[5:7]) / 3600
    return [round(lo, 5), round(la, 5)]


class NavDB:
    def __init__(self):
        self.pts = {}
        self.graph = collections.defaultdict(lambda: collections.defaultdict(set))

    def add_pt(self, n, c):
        self.pts.setdefault(n, c)

    def add_seq(self, awy, seq):
        for a, b in zip(seq, seq[1:]):
            self.graph[awy][a].add(b)
            self.graph[awy][b].add(a)

    def alias(self, awy, n, tol=0.06):
        """航空路の上に n が無いとき、座標が近い(約5km以内の)航空路上の地点を同じ地点とみなす。"""
        g = self.graph.get(awy)
        if not g or n in g or n not in self.pts:
            return n
        c = self.pts[n]
        best = min(((abs(self.pts[m][0] - c[0]) + abs(self.pts[m][1] - c[1]), m) for m in g if m in self.pts),
                   default=None)
        return best[1] if best and best[0] < tol else n

    def path(self, awy, a, b):
        g = self.graph.get(awy)
        if g:
            a, b = self.alias(awy, a), self.alias(awy, b)
        if not g or a not in g or b not in g:
            return None
        prev, q = {a: None}, [a]
        while q:
            x = q.pop(0)
            if x == b:
                break
            for y in g[x]:
                if y not in prev:
                    prev[y] = x
                    q.append(y)
        if b not in prev:
            return None
        out = [b]
        while prev[out[-1]] is not None:
            out.append(prev[out[-1]])
        return out[::-1]


def load_japan(db, folder, extra=()):
    def placemarks(path):
        s = open(path, encoding="utf-8").read()
        for p in re.findall(r"<Placemark.*?</Placemark>", s, re.S):
            a = dict(re.findall(r"<td>([^<]*)</td>\s*<td>([^<]*)</td>", p))
            cs = [[tuple(map(float, x.split(",")[:2])) for x in c.split()]
                  for c in re.findall(r"<coordinates>([^<]*)</coordinates>", p)]
            yield a, cs
    one = lambda pat: glob.glob(os.path.join(folder, pat))[0]
    allp = [(n, c) for n, c in extra]          # 手で補った地点(KMLの区間の端の照合にも使う)
    for a, cs in placemarks(one("REP_WPT*.kml")):
        allp.append((a["NAME_CODE"], cs[0][0]))
    for a, cs in placemarks(one("RADIO_NAVIGATION_AIDS*.kml")):
        allp.append((a["ID"], cs[0][0]))
    for n, c in allp:
        db.add_pt(n, [round(c[0], 5), round(c[1], 5)])

    def near(c, tol=0.05):   # 区間の端の座標に一番近い地点(KMLの区間にはFIX名が無い)
        best = None
        for n, q in allp:
            d = abs(q[0] - c[0]) + abs(q[1] - c[1])
            if d < tol and (best is None or d < best[0]):
                best = (d, n)
        return best[1] if best else None
    for pat in ("RNAV_ROUTES*.kml", "ATS_ROUTES*.kml"):
        for a, cs in placemarks(one(pat)):
            line = [c for seg in cs for c in seg]
            if len(line) < 2:
                continue
            na, nb = near(line[0]), near(line[-1])
            if na and nb:
                db.add_seq(a["DESIGNATOR"], [na, nb])


def load_korea(db, folder):
    def name_of(cell):
        t = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", cell))).strip()
        m = re.search(r"\(([A-Z]{2,3})\)", t)          # 航法援助施設 "ANYANG VORTAC (SEL)"
        if m:
            return m.group(1)
        m = re.match(r"([A-Z]{5})\b", re.sub(r"\(.*?\)", "", t).strip())
        return m.group(1) if m else None
    cre = re.compile(r"(\d{6}(?:\.\d+)?N)\s*(\d{7}(?:\.\d+)?E)")
    for name in ("ENR-3.1.html", "ENR-3.3.html", "ENR-3.5.html"):
        p = os.path.join(folder, name)
        if not os.path.exists(p):
            continue
        s = open(p, encoding="utf-8", errors="ignore").read()
        parts = re.split(r"<tr[^>]*>\s*<td[^>]*>\s*<p[^>]*>\s*([A-Z]{1,2}\d{1,4}[A-Z]?)\*?\s*</p>", s)
        for i in range(1, len(parts), 2):
            seq = []
            for row in re.findall(r"<tr[^>]*>(.*?)</tr>", parts[i + 1], re.S):
                cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
                for j in range(len(cells) - 1):
                    m = cre.search(html.unescape(re.sub(r"<[^>]+>", " ", cells[j + 1])))
                    if m:
                        n = name_of(cells[j])
                        if n:
                            db.add_pt(n, dms(m.group(1), m.group(2)))
                            if not seq or seq[-1] != n:
                                seq.append(n)
                        break
            if len(seq) >= 2:
                db.add_seq(parts[i], seq)
    p = os.path.join(folder, "ENR-4.4.html")
    if os.path.exists(p):
        t = html.unescape(re.sub(r"<[^>]+>", "\n", open(p, encoding="utf-8", errors="ignore").read()))
        for m in re.finditer(r"\b([A-Z]{5})(?:\(FIR BDRY\))?\s*\n\s*(\d{6}N)\s*(\d{7}E)", t):
            db.add_pt(m.group(1), dms(m.group(2), m.group(3)))


def load_taiwan(db, path):
    sec = None
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("["):
            sec = line
            continue
        p = line.split()
        if sec == "[PTS]":
            db.add_pt(p[0], dms(p[1], p[2]))
        elif sec == "[AWYS]":
            db.add_seq(p[0], p[1:])


def expand(db, route, apts):
    toks = route.split()
    dep, arr, body = toks[0], toks[-1], toks[1:-1]
    out, warn = [], []

    def add(n, approx_before):
        c = db.pts.get(n)
        m = re.fullmatch(r"(\d{2})(\d{2})N(\d{3})(\d{2})E", n)
        if m:
            a = [int(x) for x in m.groups()]
            c = [a[2] + a[3] / 60, a[0] + a[1] / 60]
        if c is None:
            warn.append(n)
            return False
        if out and out[-1][0] == n:
            return True
        out.append([n, c[0], c[1], 1 if approx_before else 0])
        return True

    if dep in apts:
        out.append([dep, apts[dep]["lon"], apts[dep]["lat"], 0])
    gap = False
    for i, x in enumerate(body):
        if x == "DCT":
            continue
        first, last = i == 0, i == len(body) - 1
        if (first or last) and x not in db.pts and not AW.match(x):
            continue                                  # SID / STAR / STARの遷移
        if AW.match(x) and x not in db.pts and not first and not last:
            p = db.path(x, body[i - 1], body[i + 1])
            if p:
                for n in p[1:-1]:
                    add(n, gap)
                    gap = False
            else:
                warn.append(f"{x}({body[i - 1]}-{body[i + 1]})")
                gap = True
            continue
        if add(x, gap):
            gap = False
        else:
            gap = True
    if arr in apts:
        out.append([arr, apts[arr]["lon"], apts[arr]["lat"], 1 if gap else 0])
    return out, warn


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sheet", required=True)
    ap.add_argument("--jp-kml", required=True)
    ap.add_argument("--kr-html", required=True)
    ap.add_argument("--tw", default=os.path.join(os.path.dirname(__file__), "taiwan_aip.txt"))
    ap.add_argument("--airports", default=os.path.join(os.path.dirname(__file__), "airports.txt"))
    ap.add_argument("--extra", default=os.path.join(os.path.dirname(__file__), "extra_points.txt"))
    ap.add_argument("--route-no", default="1")
    ap.add_argument("--out", default="routes.json")
    a = ap.parse_args()

    apts = {}
    for line in open(a.airports, encoding="utf-8"):
        if line.strip() and not line.startswith("#"):
            icao, iata, name, la, lo = line.split()
            apts[icao] = {"iata": iata, "name": name, "lat": float(la), "lon": float(lo)}
    extra = []
    if os.path.exists(a.extra):
        for line in open(a.extra, encoding="utf-8"):
            if line.strip() and not line.startswith("#"):
                n, la, lo = line.split()[:3]
                extra.append((n, (float(lo), float(la))))
    db = NavDB()
    load_japan(db, a.jp_kml, extra)
    load_korea(db, a.kr_html)
    load_taiwan(db, a.tw)

    if a.sheet.startswith("http"):
        text = urllib.request.urlopen(a.sheet).read().decode("utf-8")
    else:
        text = open(a.sheet, encoding="utf-8").read()
    rows = [r for r in csv.DictReader(io.StringIO(text)) if r["ルート番号"].strip() == a.route_no]
    routes, nwarn, full = [], collections.Counter(), 0
    for r in rows:
        pts, warn = expand(db, r["飛行経路"], apts)
        full += not warn
        for w in warn:
            nwarn[w] += 1
        routes.append({"dep": r["出発地"], "arr": r["目的地"], "no": a.route_no, "str": r["飛行経路"],
                       "pts": pts, "warn": warn})
    used = sorted({r["dep"] for r in routes} | {r["arr"] for r in routes})
    out = {"version": 1, "route_no": a.route_no, "airports": {k: apts[k] for k in used if k in apts},
           "routes": routes,
           "sources": "日本AIP(KML)、韓国eAIP、台湾eAIP。座標が見つからない地点は前後を直線で結ぶ"}
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print(f"{a.out}: {len(routes)}ルート(完全に展開 {full})、空港 {len(out['airports'])}")
    print("見つからなかった地点・航空路:", ", ".join(f"{k}×{v}" for k, v in nwarn.most_common()))


if __name__ == "__main__":
    main()
