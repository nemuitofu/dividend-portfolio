"""
IRバンク（https://irbank.net/）から財務・配当履歴データをスクレイピングして取得する。

利用URL:
  業績: https://irbank.net/{4桁コード}/results
  ページ内のテーブル構成（確認済み）:
    テーブル0: 業績（PL）  - 経常収益/売上高, 当期利益, EPS, ROE, ROA
    テーブル1: BS         - 自己資本比率
    テーブル2: CF         - 営業CF
    テーブル3: 配当       - 一株配当, 配当性向

スクレイピングポリシー:
  - リクエスト間隔: 2秒以上（_REQUEST_DELAY）
  - User-Agentを適切に設定
  - キャッシュを活用（同日はネットワークアクセス不要）
  - 個人利用目的に限る
"""
from __future__ import annotations

import io
import json
import time
from datetime import date
from pathlib import Path

import pandas as pd
import requests

IR_CACHE_DIR = Path(__file__).parent / "ir_cache"

# 直近スクレイピングのエラーログ（診断用）
_scrape_errors: dict[str, str] = {}


def get_scrape_errors() -> dict[str, str]:
    """直近の fetch_all_ir_data で発生したエラーを返す"""
    return dict(_scrape_errors)


def clear_scrape_errors() -> None:
    _scrape_errors.clear()

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
_REQUEST_DELAY = 2.0  # 秒（サーバー負荷軽減のため厳守）

# 列名キーワードマッピング（日本語キーワード → 内部フィールド名）
# 重要: 部分一致のため、より長い（具体的な）キーワードを持つものを先に並べる
# 例: 「配当性向」を「配当」より先に、「経常収益」を「経常」より先に
_COL_KEYWORDS: list[tuple[list[str], str]] = [
    (["年度", "決算期", "会計年度"],                                        "fiscal_year"),
    # 「収益」は短いため具体的なキーワードを先に置き、最後に追加（商社等の「収益」列に対応）
    (["売上高", "売上収益", "経営収益", "営業収益", "経常収益", "収益"],    "revenue"),
    (["営業利益"],                                                           "operating_profit"),
    (["経常利益", "経常"],                                                   "ordinary_profit"),  # 銀行業績表では「経常」列
    (["純利益", "当期純利益", "当期利益", "親会社株主に帰属"],               "net_income"),
    (["EPS", "1株益", "一株益", "1株当たり純利益"],                         "eps"),
    (["配当性向"],                                                           "payout_ratio"),  # 「配当」より先
    (["一株配当", "配当", "1株配", "DPS", "1株当たり配当"],                  "dps"),
    # 「自己資本比率」「株主資本比率」の両方に対応（業種・ページにより異なる）
    (["自己資本比率", "株主資本比率"],                                       "equity_ratio"),
    (["ROE"],                                                                "roe"),
    (["ROA"],                                                                "roa"),
    (["営業CF", "営業キャッシュ"],                                           "operating_cf"),
    (["現金等", "現金及び現金等価物", "現預金", "現金・預金"],               "cash"),
]

_RESULT_FIELDS = [
    "revenue", "operating_profit", "ordinary_profit",
    "net_income", "eps", "dps", "payout_ratio",
    "equity_ratio", "roe", "roa", "operating_cf", "cash",
]


# ------------------------------------------------------------------ #
# ユーティリティ
# ------------------------------------------------------------------ #

def _parse_number(text: str | None) -> float | None:
    """
    数値文字列をfloatに変換。失敗時はNone。
    対応フォーマット:
      - カンマ区切り: "1,234.5"
      - %付き: "41.7%"
      - 兆・億サフィックス（単位として扱い数値部分のみ抽出）: "6.39兆", "-5246億"
      - 赤字・—・-: None
    """
    if text is None:
        return None
    s = (
        str(text).strip()
        .replace(",", "").replace("，", "")
        .replace("%", "").replace("％", "")
        .replace("円", "").replace("倍", "")
        .replace("兆", "").replace("億", "")  # 単位サフィックスを除去（数値は一貫した単位とみなす）
    )
    if s in ("", "—", "－", "-", "N/A", "nan", "None", "---", "赤字"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _fetch_html(url: str) -> str | None:
    """URLからHTMLを取得。ネットワークエラー時はNone"""
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=20)
        resp.raise_for_status()
        resp.encoding = "utf-8"
        return resp.text
    except Exception:
        return None


def _map_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    DataFrameの列名を日本語キーワードベースで内部フィールド名にマッピングする。
    同一ターゲット名への2重マッピングはスキップ（先勝ち）。
    """
    col_rename: dict[str, str] = {}
    used_targets: set[str] = set()

    for col in df.columns:
        col_str = str(col)
        for keywords, target in _COL_KEYWORDS:
            if target in used_targets:
                continue
            if any(kw in col_str for kw in keywords):
                col_rename[col] = target
                used_targets.add(target)
                break

    return df.rename(columns=col_rename)


def _is_fiscal_year_table(df: pd.DataFrame) -> bool:
    """DataFrameが年度列を持つかチェック"""
    for col in df.columns:
        col_str = str(col)
        if any(kw in col_str for kw in ["年度", "決算期", "会計年度"]):
            return True
    return False


# ------------------------------------------------------------------ #
# スクレイピング
# ------------------------------------------------------------------ #

def scrape_irbank_results(ticker: str) -> list[dict]:
    """
    IRバンク業績ページ（/results）から財務データをスクレイピングして返す。
    URL: https://irbank.net/{ticker}/results

    IRバンクのページには複数のテーブルがあり（業績・BS・CF・配当）、
    すべてを「年度」列でマージして統合データを返す。

    Returns:
        list[dict]: 年度別データ（新しい年度順・降順）。
            キー: fiscal_year, revenue, net_income, eps, dps, payout_ratio,
                  equity_ratio, roe, roa, operating_cf 等
        取得失敗・データなし時は空リスト。
    """
    url = f"https://irbank.net/{ticker}/results"
    html = _fetch_html(url)
    if not html:
        _scrape_errors[ticker] = "HTMLの取得に失敗（ネットワークエラー・タイムアウト・HTTP 4xx/5xx）"
        return []

    try:
        all_tables = pd.read_html(io.StringIO(html))
    except Exception as e:
        _scrape_errors[ticker] = f"HTMLパースエラー: {type(e).__name__}: {e}"
        return []

    if not all_tables:
        _scrape_errors[ticker] = "ページにテーブルが見つかりません（URLが存在しないか構造が異なる）"
        return []

    # 年度列を持つテーブルをすべて取得してマージ
    fiscal_tables: list[pd.DataFrame] = []
    for tbl in all_tables:
        if _is_fiscal_year_table(tbl):
            mapped = _map_columns(tbl)
            fiscal_tables.append(mapped)

    if not fiscal_tables:
        return []

    # 最初のテーブルを基に、残りを fiscal_year でマージ
    merged = fiscal_tables[0]
    for other in fiscal_tables[1:]:
        if "fiscal_year" not in merged.columns or "fiscal_year" not in other.columns:
            continue
        # 重複列を除いてマージ
        other_new_cols = [c for c in other.columns if c not in merged.columns or c == "fiscal_year"]
        merged = pd.merge(
            merged,
            other[other_new_cols],
            on="fiscal_year",
            how="outer",
        )

    if "fiscal_year" not in merged.columns:
        _scrape_errors[ticker] = (
            f"年度列（決算期/年度）が見つかりません。列名: {list(merged.columns)[:10]}"
        )
        return []

    # 数値変換しながら行データを構築
    result_rows: list[dict] = []
    for _, row in merged.iterrows():
        fy = str(row.get("fiscal_year", "")).strip()
        if not fy or fy in ("nan", "None", ""):
            continue

        d: dict = {"fiscal_year": fy}
        for field in _RESULT_FIELDS:
            raw = row.get(field)
            d[field] = _parse_number(str(raw)) if raw is not None else None

        # 有効なデータが1つ以上ある行のみ保持
        if any(d.get(f) is not None for f in _RESULT_FIELDS):
            result_rows.append(d)

    if not result_rows:
        _scrape_errors[ticker] = "データ行が0件（テーブルは見つかったが有効なデータなし）"
        return []

    # IRバンクは古い年度順のため、降順（新しい年度が先）に反転
    result_rows.reverse()
    # 成功した場合はエラーログから除去
    _scrape_errors.pop(ticker, None)

    return result_rows


# ------------------------------------------------------------------ #
# キャッシュ管理
# ------------------------------------------------------------------ #

def load_ir_cache(ticker: str) -> dict | None:
    """ファイルキャッシュからIRデータを読む。存在しない場合はNone"""
    IR_CACHE_DIR.mkdir(exist_ok=True)
    cache_file = IR_CACHE_DIR / f"{ticker}.json"
    if not cache_file.exists():
        return None
    try:
        with open(cache_file, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def save_ir_cache(ticker: str, data: dict) -> None:
    """IRデータをJSONキャッシュファイルに保存"""
    IR_CACHE_DIR.mkdir(exist_ok=True)
    cache_file = IR_CACHE_DIR / f"{ticker}.json"
    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_ir_data(ticker: str, force_refresh: bool = False) -> dict:
    """
    キャッシュ優先でIRデータを返す。
    キャッシュがない場合またはforce_refresh=Trueの場合にスクレイピング実行。

    Returns:
        dict: {
            "ticker": str,
            "fetched_at": str (YYYY-MM-DD),
            "results": list[dict]  # 年度別データ（新→古順）
        }
    """
    if not force_refresh:
        cached = load_ir_cache(ticker)
        if cached and cached.get("results"):
            return cached

    results = scrape_irbank_results(ticker)
    data = {
        "ticker": ticker,
        "fetched_at": str(date.today()),
        "results": results,
    }
    if results:
        save_ir_cache(ticker, data)
    return data


def fetch_all_ir_data(
    tickers: list[str],
    force_refresh: bool = False,
    progress_callback=None,
) -> dict[str, dict]:
    """
    複数銘柄のIRデータを一括取得（キャッシュ優先）。
    スクレイピングが必要な銘柄間には _REQUEST_DELAY 秒の遅延を挿入。

    Args:
        tickers: 4桁銘柄コードのリスト
        force_refresh: Trueの場合キャッシュを無視してスクレイピング
        progress_callback: (done: int, total: int) -> None

    Returns:
        dict: {ticker: ir_data_dict}
    """
    clear_scrape_errors()
    results: dict[str, dict] = {}
    need_scrape: list[str] = []

    # まずキャッシュチェック
    for t in tickers:
        if not force_refresh:
            cached = load_ir_cache(t)
            if cached and cached.get("results"):
                results[t] = cached
                continue
        need_scrape.append(t)

    total = len(tickers)
    done = len(results)

    if progress_callback:
        progress_callback(done, total)

    # キャッシュなし銘柄をスクレイピング
    for i, t in enumerate(need_scrape):
        results[t] = get_ir_data(t, force_refresh=True)
        done += 1
        if progress_callback:
            progress_callback(done, total)
        if i < len(need_scrape) - 1:
            time.sleep(_REQUEST_DELAY)

    return results


def load_all_ir_caches(tickers: list[str]) -> dict[str, dict]:
    """キャッシュ済みのIRデータのみを返す（ネットワークアクセスなし）"""
    result: dict[str, dict] = {}
    for t in tickers:
        cached = load_ir_cache(t)
        if cached:
            result[t] = cached
    return result
