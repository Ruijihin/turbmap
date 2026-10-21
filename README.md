# 揺れやすさ地図(turbmap)

気象庁のメソモデル(MSM)の予報から、飛行機が揺れやすい場所を計算して地図に表示します。
VWS(鉛直シアー)だけでなく、山岳波・慣性不安定・変形場・低リチャードソン数を別々に計算し、
それらの組み合わせを考慮した「総合の揺れやすさ」を出します。晴天乱気流(CAT)に加えて、
「揺れる雲」(浮力と実際の対流がそろった対流、湿った空気として不安定な雲)も評価します。

- 範囲:北緯22.4〜46度、東経120〜147度(石垣島・台湾・朝鮮半島を含み、北海道より北・東は含まない)
- 高度:FL120〜FL410(1000ft刻み。モデルの層のあいだは補間)
- 表示:2D地図、3D(回転・拡大できるボリューム表示)、地図上の点を結んだ線に沿った鉛直断面
- 更新:MSMの発表ごと(1日8回)。過去60日分を保存
- 費用:GitHub(公開リポジトリ)と Cloudflare の無料枠の中で動く

> **注意** これは乱れやすい環境の目安で、乱気流そのものの予報ではありません。
> 気象庁の航空気象情報の代わりにはなりません。判定の目安や係数は仮の値です。
> 入力データの利用条件は「[データの利用条件](#データの利用条件)」を必ず確認してください。

## しくみ

```
Cloudflare Worker(30分ごと)
  │ GitHub API で workflow_dispatch(init=auto)
  ▼
GitHub Actions(.github/workflows/build.yml)
  1. 京大生存圏研究所のアーカイブに新しい初期値があるか確認(無ければ終了)
  2. MSM気圧面ファイル(約187MB)と地上ファイル(約198MB)をダウンロード
  3. Python で要素を計算し、予報時刻ごとの数値データ(PNGに格納)と meta.json を作る
  4. Cloudflare R2 に保存し、一覧 index.json を更新、古い分を削除
  ▼
Cloudflare R2(非公開バケット)
  ▲ Worker が /data/* として読み出して配信
Cloudflare Worker(web/ の画面も配信)
  ▼
ブラウザ:数値データを読み、高度の補間・総合の計算・色付けをその場で行う
```

PNGは画像ではなく、数値(指数×100、0〜255)の入れ物として使っています。
総合の計算や色はブラウザ側で行うので、係数を変えても再計算は要りません。

## フォルダ構成

| パス | 内容 |
|---|---|
| `batch/turbmap/` | バッチ処理(取得 `rish.py`、計算 `diag.py`、保存 `store.py`、実行 `main.py`) |
| `batch/scripts/rish_ca.sh` | 京大サーバーの証明書の不備を補う |
| `batch/certs/` | 補うための中間証明書とルート証明書(公開情報) |
| `batch/scripts/make_coast.py` | 表示範囲を変えたときに海岸線を作り直す |
| `batch/scripts/make_terrain.py` | 地形の影響圏(`web/terrain.png`)を作る。表示範囲を変えたときに作り直す |
| `.github/workflows/build.yml` | GitHub Actions の定義 |
| `worker/` | Cloudflare Worker(画面とデータの配信、定期起動) |
| `web/` | 地図の画面(`index.html`、3D表示 `view3d.js`、`config.js`、`coast.json`、地形の影響圏 `terrain.png`) |
| `web/vendor/` | 3D表示に使う three.js(MIT、ライセンスは `three.LICENSE`) |
| `gas/Code.gs` | 揺れの報告を集める Google Apps Script(任意) |
| `docs/` | ドキュメント |

## ドキュメント

- [docs/setup.md](docs/setup.md):最初の設定手順(GitHub・Cloudflare)
- [docs/operations.md](docs/operations.md):運用・監視・困ったとき
- [docs/method.md](docs/method.md):計算方法とデータ形式
- [docs/pirep.md](docs/pirep.md):揺れの報告を地図に重ねる(任意)

## 手元で試す

```bash
cd batch
pip install -r requirements.txt
# 京大サーバーへの接続に必要(Linux / Git Bash)
source scripts/rish_ca.sh
# 最新の初期値を1件計算して ../out/data に出力
python -m turbmap.main --init auto --max-runs 1 --out ../out/data
cd .. && python -m http.server 8000
# ブラウザで http://localhost:8000/web/?data=/out/data/ を開く
```

試験用のデータは `web/` の中に置かないでください。`web/` の中身はすべて Worker から配信されます。

## データの利用条件

- 入力は気象庁のMSMで、京都大学生存圏研究所のアーカイブ(教育・研究機関向けの公開)から取得しています。
  アーカイブの利用条件に従ってください。
- 実際の運航に使う場合は、一般財団法人 気象業務支援センターからの正式な配信を受けることを検討してください。
  取得部分(`batch/turbmap/rish.py`)を差し替えれば、計算と配信の仕組みはそのまま使えます。
- 1回のダウンロードは約385MB(気圧面+地上)で、1日8回取得します。アーカイブに負担をかけないよう、
  起動間隔を短くしすぎないでください(既定は30分ごとの確認で、新しい初期値があるときだけダウンロード)。
