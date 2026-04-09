# 高配当株ポートフォリオマネージャー

両学長（リベ大）の高配当株投資理論に基づいた、ポートフォリオ分析・可視化ツールです。  
マネックス証券・楽天証券のCSVをアップロードするだけで、保有銘柄を多角的に分析できます。

## 機能

- **サマリーダッシュボード** — 時価評価額・評価損益・年間配当金・ポートフォリオ利回りを一目で確認
- **銘柄一覧** — 保有全銘柄の配当利回り・損益を色分けで表示
- **セクター分散分析** — 両学長チェックリスト（利回り・銘柄数・セクター数・集中度）に基づく評価
- **両学長スコアリング** — IRバンクの過去10年財務データから配当継続性・財務健全性・業績成長を自動スコアリング
- **配当データ管理** — yfinanceによる一括取得 + 手動編集でキャッシュ管理

## 対応証券会社

| 証券会社 | ファイル名パターン |
|----------|------------------|
| マネックス証券 | `stockposition_*.csv` |
| 楽天証券 | `assetbalance_*.csv` |

## セットアップ

```bash
git clone https://github.com/nemuitofu/dividend-portfolio.git
cd dividend-portfolio
pip install -r requirements.txt
streamlit run app.py
```

ブラウザで `http://localhost:8501` が開きます。

## 使い方

1. 各証券会社の管理画面からCSVをダウンロード
2. サイドバーからCSVをアップロード
3. 「配当データ管理」タブで「yfinanceで一括取得」を実行
4. 各タブで分析結果を確認

詳細な操作手順は [MANUAL.md](MANUAL.md) を参照してください。

## ファイル構成

```
dividend-portfolio/
├── app.py                # Streamlit UIアプリ（エントリーポイント）
├── utils.py              # ビジネスロジック・計算処理
├── ir_scraper.py         # IRバンクから財務データをスクレイピング
├── ryogakucho_eval.py    # 両学長スタイルの銘柄スコアリング
├── requirements.txt      # Pythonパッケージ一覧
├── sector_master.csv     # セクター分類マスタ（カスタマイズ可）
└── MANUAL.md             # 操作マニュアル
```

## 技術スタック

- [Streamlit](https://streamlit.io/) — Webアプリフレームワーク
- [Pandas](https://pandas.pydata.org/) — データ処理
- [Plotly](https://plotly.com/) — インタラクティブグラフ
- [yfinance](https://github.com/ranaroussi/yfinance) — 配当利回りデータ取得
- [Beautiful Soup](https://www.crummy.com/software/BeautifulSoup/) — IRバンクスクレイピング

## 注意事項

- 本ツールは個人利用目的のみを想定しています
- IRバンクへのスクレイピングはリクエスト間隔2秒以上を守っています
- 投資判断はご自身の責任で行ってください
