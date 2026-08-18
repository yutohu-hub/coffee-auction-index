# COFFEE AUCTION INDEX ☕🔨

世界のスペシャルティコーヒー・**オークションの落札結果**を横断してまとめる索引サイト。
Cup of Excellence（COE）を自動巡回し、Best of Panama などを収録。GitHub Actions で毎日更新され、GitHub Pages で無料公開できます。

すべての価格は **USD/lb（ポンド単価）** に正規化してあるので、国・年・品種をまたいで横断比較できます。

## できること

- **価格ランキング** … 全期間の落札単価を横断ソート・フィルタ（オークション/国/年/品種/精製/農園・落札者検索）
- **オークション別** … オークション×国×年ごとに、ロット一覧を折りたたみ表示
- **📅 カレンダー**（メイン表示） … 月グリッドの実カレンダーで、オークション日（金）と**生豆サンプル注文期限の目安**（青緑）を配置。本日・TBD・終了も表示（`data/schedule.json`）
  - サンプル期限は各オークションが登録者に個別通知し公表されないため、オークション日から `settings.sample_lead_days`（既定21日）前を**目安**として表示。`schedule.json` に `sample_deadline` を書けば公表値を優先
- **期間の切替** … 「今シーズン(当年) / 過去 / すべて」でロットを分けて表示
- **通貨の切替** … USD ↔ JPY。当日の為替レート（USD→JPY）で自動換算
- **記録（レコード）** … 最高落札単価・最高スコア・最高総額
- **新着** … 前回巡回からの差分（新しく公表されたロット・全期間最高単価の更新）

## 仕組み

```
GitHub Actions（毎日1回）
   ↓
crawl.py が各オークション源を巡回
   ・COE      … 公式結果ページ（allianceforcoffeeexcellence.org / cupofexcellence.org）の
                「国-年」ページを発見し、HTMLテーブル（競技表＋オークション表）を解析・マージ
   ・mCultivo … Dubai Coffee Auction など CultivoCommerce(Framer)製の結果ページを解析
                （同一構造で複数オークションを一括取得。多国籍は農園名から原産国を推定）
   ・seed     … data/seed.json のキュレーション（BOP/Gesha Village/CGLE等、報道・公式発表ベース）
   ↓
model.py が USD/lb に正規化（US式 143.10 / 欧州式 143,10 の混在も自動判定）
   ↓
store.py が SQLite の前回スナップショットと比較して差分イベントを検出
   ↓
build_site.py が docs/ に単一HTMLのサイトを生成 → GitHub Pages で公開
```

外部依存は `httpx` と `pyyaml` のみ。HTMLの解析は標準ライブラリ（`html.parser`）だけで行っています。

## セットアップ（コード編集不要）

1. **GitHubに新しいリポジトリを作る**（例: `coffee-auction-index`、Public）。
2. **このフォルダの中身を全部アップロード**（`.github` フォルダも忘れずに）。コマンドが使えるなら:
   ```bash
   git init && git add . && git commit -m "init"
   git remote add origin https://github.com/あなたのID/coffee-auction-index.git
   git push -u origin main
   ```
3. **Actionsを有効化** … 「Actions」タブ →「Auction Index 巡回」→「Run workflow」で初回を手動実行。
4. **Pagesを有効化** … 「Settings」→「Pages」→ Source: `Deploy from a branch`、Branch: `main` / フォルダ: `/docs` → Save。
   数分後 `https://あなたのID.github.io/coffee-auction-index/` で見られます。

以降は**毎日自動巡回**され、サイトが勝手に更新されます（差分は `data/state.db` に蓄積）。

## ローカルでの動作テスト

```bash
pip install -r requirements.txt
python main.py --seed-only   # ネット不要。キュレーションデータだけで一巡
python main.py               # 実際に巡回（COE公式ページ、初回は1〜2分）
python3 -m http.server 8813 --directory docs   # http://localhost:8813 で確認
```

## 対象の追加・調整

### COE の対象年・取得量（`config/sources.yaml`）

```yaml
sources:
  coe:
    enabled: true
    min_year: 2015    # この年以降の結果を対象（過去年も収集）
    max_pages: 240    # 1回の巡回で取る「国×年」ページ上限（初回で全期間を網羅）
    concurrency: 5    # 同時アクセス数（控えめに）
```

公表済みの過去年は `data/state.db` に入ると次回以降スキップされ、巡回は軽くなります（当年ぶんは追い落札の反映のため毎回再取得）。

### mCultivo オークションを足す（`config/sources.yaml`）

Dubai Coffee Auction など CultivoCommerce 製の結果ページは、**完了済みオークションの結果URL**を列挙するだけで実スクレイピングできます（列はヘッダ名から自動マッピング、bid単価は USD/lb に正規化）。

```yaml
sources:
  mcultivo:
    enabled: true
    auctions:
      - name: "Dubai Coffee Auction"
        url: "https://dubaicoffeeauction.mcultivo.com/2025-auction-results-february"
        year: 2025
        country: ""        # 空=多国籍（農園・ロット名から原産国を推定）
```

`https://<auction>.mcultivo.com/` を開き、結果（Auction Results）ページのURLを控えて足すだけ。開催中でbidが未確定のオークションは結果確定後に追加してください。

### キュレーション・データ（`data/seed.json`）

COEのように機械的に取りにくいオークション（Best of Panama など）は、報道・公式発表ベースの検証済みデータをここに1件1ブロックで足します。

```json
{
  "source": "seed", "auction": "Best of Panama", "country": "Panama", "year": 2025,
  "category": "Geisha Washed", "farm": "Hacienda La Esmeralda",
  "variety": "Geisha", "process": "Washed", "price_lb": 13705, "buyer": "Dubai (UAE)",
  "url": "https://bestofpanama.org/"
}
```

### カレンダーの予定（`data/schedule.json`）

今後・過去のオークション日程を1件1ブロックで管理します（カレンダータブに反映）。`date` を空にすると「日程未定(TBD)」扱い。

```json
{"date": "2026-09-23", "auction": "Best of Panama", "type": "BOP",
 "country": "Panama", "year": 2026, "url": "https://bestofpanama.auction/", "note": "国際電子オークション"}
```

### 為替レート（USD→JPY）

巡回時に [frankfurter.dev](https://frankfurter.dev)（ECBデータ・キー不要）から取得し、`docs/data.json` に保存。取得失敗時はフォールバック値を使用します（`src/fx.py`）。

### 新しいオークション源のスクレイパーを足す

`src/sources/` に `fetch(client, cfg, skip_keys) -> (list[Lot], failed)` を持つモジュールを追加し、`crawl.py` から呼び出すだけ。出力を `model.Lot` に正規化すれば、サイト・記録・差分検知にそのまま乗ります。

## データについての注意

- 価格・スコアは各オークションの**公表結果のスナップショット**です。正確な取引条件は各オークション・出品者にご確認ください。
- COEは公式結果ページを機械的に解析しています。ページ構成の変更で一部が取得できないことがあります（取得失敗はサイト下部に件数表示）。
- 各サイトの利用規約を尊重し、巡回頻度は日次・同時接続は控えめにしてあります。
