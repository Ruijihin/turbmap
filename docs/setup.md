# 設定手順

所要時間の目安は1時間ほどです。必要なものは次のとおりです。

- GitHub のアカウント
- Cloudflare のアカウント(無料プラン)
- 手元のPCに Git と Node.js(Worker を登録するときに `npx wrangler` を使う)

途中で作る秘密情報(R2の鍵、GitHubのトークン)は、**リポジトリのファイルに書かないでください**。
公開リポジトリなので、書くと誰でも見られます。登録場所はこの手順のとおりです。

---

## 1. GitHub に公開リポジトリを作る

1. GitHub で新しいリポジトリを作ります(例:`turbmap`、Public)。
2. このフォルダを登録します。

```bash
cd turbmap
git init -b main
git add .
git commit -m "揺れやすさ地図の初版"
git remote add origin https://github.com/Ruijihin/turbmap.git
git push -u origin main
```

3. リポジトリの **Settings → Actions → General** で、Actions が使える状態になっているか確かめます。

## 2. Cloudflare R2 にバケットを作る

1. Cloudflare のダッシュボードで **R2 Object Storage** を開き、R2を有効にします。
   無料枠の範囲でも、支払い方法の登録を求められることがあります(無料枠内なら請求はありません)。
2. **Create bucket** で `turbmap-data` を作ります。公開設定(Public access)は**オフのまま**にします。
   データは Worker 経由でだけ配信します。
3. **Manage R2 API Tokens → Create API token** で鍵を作ります。
   - 権限:**Object Read & Write**
   - 対象:`turbmap-data` だけに限定
4. 表示される次の3つを控えます(Secret は一度しか表示されません)。
   - Account ID
   - Access Key ID
   - Secret Access Key

## 3. GitHub に R2 の鍵を登録する

リポジトリの **Settings → Secrets and variables → Actions** で登録します。

| 種類 | 名前 | 値 |
|---|---|---|
| Secret | `R2_ACCOUNT_ID` | Account ID |
| Secret | `R2_ACCESS_KEY_ID` | Access Key ID |
| Secret | `R2_SECRET_ACCESS_KEY` | Secret Access Key |
| Variable(任意) | `R2_BUCKET` | バケット名を変えた場合だけ |
| Variable(任意) | `RETENTION_DAYS` | 保存日数(既定60) |
| Variable(任意) | `FT_MAX` | 計算する最後の予報時間(既定21。MSMは最大33。33にすると1回分のデータが約1.6倍) |

## 4. 最初のバッチを手動で動かす

1. リポジトリの **Actions → build → Run workflow** を押します(init は `auto` のまま)。
2. 数分で終わります。ログに「保存: 約7MB, 予報時刻11個」「一覧を更新しました」と出れば成功です。
3. R2 のバケットに `index.json` と `runs/<初期時刻>/` ができていることを確かめます。

失敗したときは [operations.md](operations.md) の「困ったとき」を見てください。

## 5. Worker 用の GitHub トークンを作る

Worker が30分ごとにバッチを起動するためのトークンです。

1. GitHub の **Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token**。
2. 設定:
   - Repository access:**Only select repositories** → `turbmap` だけ
   - Permissions → Repository permissions → **Actions: Read and write**
   - 有効期限:最長1年。期限前に作り直す必要があるので、予定表に入れておきます。
3. 表示されたトークンを控えます。

## 6. Worker を登録する

1. `worker/wrangler.toml` の `GH_OWNER`(あなたのGitHubアカウント名)と `GH_REPO`(リポジトリ名)を書き換え、コミットします。
2. 手元のPCで次を実行します。

```bash
cd worker
npx wrangler login                 # ブラウザが開くので Cloudflare にログイン
npx wrangler secret put GH_TOKEN   # 5. のトークンを貼り付ける
npx wrangler deploy
```

3. 最後に表示される `https://turbmap.<あなたのサブドメイン>.workers.dev` を開くと地図が出ます。
4. 30分以内に、Actions の画面に Worker から起動された実行(`workflow_dispatch`)が現れることを確かめます。

## 7. 閲覧できる人を限定する(推奨)

このままでは、URLを知っている人は誰でも見られます。運航関係者だけに見せるなら、
Cloudflare Zero Trust の **Access** を使います(少人数なら無料)。

1. ダッシュボードの **Zero Trust → Access → Applications → Add an application → Self-hosted**。
2. アプリケーションのドメインに Worker のURL(または独自ドメイン)を指定します。
3. ポリシーで、許可するメールアドレスやドメイン(例:`@example.co.jp`)を指定します。

Worker の画面とデータ(`/data/*`)は同じURLなので、両方まとめて保護されます。
R2 のバケットは非公開なので、直接は読めません。

## 8. 揺れの報告を重ねる(任意)

[pirep.md](pirep.md) を参照してください。
