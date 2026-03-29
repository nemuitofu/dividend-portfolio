"""
ポートフォリオ計算・データ処理ロジック（Streamlit非依存）
"""

from __future__ import annotations

import io
from pathlib import Path

import pandas as pd
import yfinance as yf

# ------------------------------------------------------------------ #
# 定数
# ------------------------------------------------------------------ #

DIVIDEND_CACHE_FILE = Path(__file__).parent / "dividend_data.csv"
SECTOR_MASTER_FILE = Path(__file__).parent / "sector_master.csv"
FUNDAMENTAL_CACHE_FILE = Path(__file__).parent / "fundamental_data.csv"

# 銘柄コード範囲によるセクター推定テーブル
_SECTOR_RANGES: list[tuple[str, list[tuple[int, int]]]] = [
    ("水産・農林",     [(1300, 1399)]),
    ("鉱業",          [(1500, 1599)]),
    ("建設",          [(1800, 1999)]),
    ("食品",          [(2000, 2999)]),
    ("繊維",          [(3000, 3199)]),
    ("パルプ・紙",    [(3800, 3899)]),
    ("化学",          [(4000, 4399)]),
    ("医薬品",        [(4400, 4599)]),
    ("石油・石炭",    [(5000, 5099)]),
    ("ゴム",          [(5100, 5199)]),
    ("ガラス・土石",  [(5200, 5399)]),
    ("鉄鋼",          [(5400, 5599)]),
    ("非鉄金属",      [(5600, 5699)]),
    ("金属製品",      [(5700, 5999)]),
    ("機械",          [(6000, 6399)]),
    ("電気機器",      [(6400, 6999)]),
    ("輸送用機器",    [(7000, 7299)]),
    ("精密機器",      [(7700, 7799)]),
    ("その他製品",    [(7800, 7999)]),
    ("電気・ガス",    [(9500, 9699)]),
    ("陸運",          [(9000, 9099)]),
    ("海運",          [(9100, 9199)]),
    ("空運",          [(9200, 9299)]),
    ("倉庫・運輸",    [(9300, 9399)]),
    ("情報・通信",    [(4600, 4799), (9400, 9499), (9600, 9799)]),
    ("卸売",          [(8000, 8099)]),
    ("小売",          [(2800, 2999), (3000, 3099), (7800, 7899), (9800, 9999)]),
    ("銀行",          [(8300, 8399)]),
    ("証券",          [(8600, 8699)]),
    ("保険",          [(8700, 8799)]),
    ("その他金融",    [(8100, 8299), (8400, 8599), (8800, 8899)]),
    ("不動産",        [(8900, 8999)]),
    ("REIT・ETF",     [(1300, 1499), (2550, 2600)]),  # ETF帯域（おおよそ）
]

# 投資スタイル分類テーブル
_DEFENSIVE_SECTORS = frozenset({
    "医薬品", "食品", "電気・ガス", "情報・通信", "水産・農林",
})
_CYCLICAL_SECTORS = frozenset({
    "鉄鋼", "化学", "機械", "電気機器", "輸送用機器", "建設",
    "非鉄金属", "ゴム", "石油・石炭", "パルプ・紙", "繊維",
    "ガラス・土石", "金属製品", "鉱業",
})
_FINANCIAL_SECTORS = frozenset({"銀行", "証券", "保険", "その他金融"})

# ファンダメンタルズキャッシュの列定義
_FUND_COLS = [
    "ticker", "roe", "roa", "debt_to_equity", "current_ratio",
    "payout_ratio", "revenue_growth", "earnings_growth",
    "pb_ratio", "pe_ratio", "operating_margin",
]

# ------------------------------------------------------------------ #
# CSV読み込み
# ------------------------------------------------------------------ #

def _to_float(series: pd.Series) -> pd.Series:
    """カンマ区切り・全角数字・"---"などを含む列をfloatに変換"""
    return (
        series.astype(str)
        .str.replace(",", "", regex=False)
        .str.replace("，", "", regex=False)
        .str.strip()
        .replace({"---": None, "": None, "nan": None})
        .astype(float, errors="ignore")
    )


def _read_csv_sjis(file) -> pd.DataFrame:
    """Shift-JIS / cp932 でCSVを読む。両方失敗したらUTF-8で試みる"""
    raw = file.read() if hasattr(file, "read") else Path(file).read_bytes()
    for enc in ("cp932", "shift_jis", "utf-8"):
        try:
            return pd.read_csv(io.BytesIO(raw), encoding=enc)
        except (UnicodeDecodeError, pd.errors.ParserError):
            continue
    raise ValueError("CSVのエンコードを判別できませんでした（cp932/shift_jis/utf-8）")


def load_position_csv(file) -> pd.DataFrame:
    """
    SBI証券 stockposition_*.csv を読み込んで正規化済みDataFrameを返す。

    返却列:
        ticker, name, market, account_type, current_price,
        avg_cost, shares, market_value, unrealized_pl, unrealized_pl_pct
    """
    df = _read_csv_sjis(file)
    # 列名の空白除去
    df.columns = df.columns.str.strip()

    col_map = {
        "銘柄コード":   "ticker",
        "銘柄名":       "name",
        "市場":         "market",
        "口座区分":     "account_type",
        "現在値":       "current_price",
        "平均取得単価": "avg_cost",
        "保有数":       "shares",
        "時価評価額":   "market_value",
        "評価損益":     "unrealized_pl",
    }
    df = df.rename(columns=col_map)

    # 必要列のみ残す
    keep = list(col_map.values())
    df = df[[c for c in keep if c in df.columns]].copy()

    # 数値変換
    for col in ["current_price", "avg_cost", "shares", "market_value", "unrealized_pl"]:
        if col in df.columns:
            df[col] = _to_float(df[col])

    # ticker を文字列に統一（ゼロ埋めなし）
    df["ticker"] = df["ticker"].astype(str).str.strip().str.zfill(4)

    # 評価損益率
    df["unrealized_pl_pct"] = (
        df["unrealized_pl"] / (df["market_value"] - df["unrealized_pl"]) * 100
    ).round(2)

    return df.dropna(subset=["ticker", "current_price"])


def load_balance_csv(file) -> dict:
    """
    SBI証券 assetbalance(JP)_*.csv を読み込んでサマリーdictを返す。
    """
    raw = file.read() if hasattr(file, "read") else Path(file).read_bytes()

    summary: dict[str, object] = {}
    for enc in ("cp932", "shift_jis", "utf-8"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        return summary

    for line in text.splitlines():
        parts = [p.strip().strip('"') for p in line.split(",")]
        if "現在の評価額合計" in parts[0]:
            val = parts[-1].replace(",", "").replace("¥", "").strip()
            summary["total_market_value"] = float(val) if val.lstrip("-").isdigit() else None
        elif "評価損益" in parts[0] and len(parts) >= 3:
            val = parts[-1].replace(",", "").strip()
            summary.setdefault("total_unrealized_pl", float(val) if val.lstrip("-").replace(".", "").isdigit() else None)

    return summary


# ------------------------------------------------------------------ #
# セクター分類
# ------------------------------------------------------------------ #

def estimate_sector(ticker_code: str) -> str:
    """銘柄コード（4桁文字列）からセクターを推定する"""
    try:
        code = int(ticker_code)
    except ValueError:
        return "その他"

    # ETF帯域は先に判定（1300-1499, 2550-2600）
    if (1300 <= code <= 1499) or (2550 <= code <= 2600):
        return "REIT・ETF"

    for sector, ranges in _SECTOR_RANGES:
        if sector == "REIT・ETF":
            continue
        for lo, hi in ranges:
            if lo <= code <= hi:
                return sector
    return "その他"


def load_sector_master() -> dict[str, str]:
    """sector_master.csv が存在すれば {ticker: sector} dictを返す"""
    if not SECTOR_MASTER_FILE.exists():
        return {}
    df = pd.read_csv(SECTOR_MASTER_FILE, dtype=str)
    df.columns = df.columns.str.strip()
    if "ticker" in df.columns and "sector" in df.columns:
        return dict(zip(df["ticker"].str.zfill(4), df["sector"]))
    return {}


def get_sector(ticker_code: str, master: dict[str, str]) -> str:
    return master.get(ticker_code, estimate_sector(ticker_code))


# ------------------------------------------------------------------ #
# 投資スタイル分類
# ------------------------------------------------------------------ #

def classify_investment_style(sector: str) -> str:
    """セクターから投資スタイルを返す（ディフェンシブ/景気敏感/金融/REIT・ETF/その他）"""
    if sector in _DEFENSIVE_SECTORS:
        return "ディフェンシブ"
    if sector in _CYCLICAL_SECTORS:
        return "景気敏感"
    if sector in _FINANCIAL_SECTORS:
        return "金融"
    if sector == "REIT・ETF":
        return "REIT・ETF"
    return "その他"


# ------------------------------------------------------------------ #
# 配当データ
# ------------------------------------------------------------------ #

def load_dividend_cache() -> dict[str, float]:
    """dividend_data.csv から {ticker: div_yield} を返す"""
    if not DIVIDEND_CACHE_FILE.exists():
        return {}
    df = pd.read_csv(DIVIDEND_CACHE_FILE, dtype={"ticker": str})
    df["ticker"] = df["ticker"].str.zfill(4)
    return dict(zip(df["ticker"], df["div_yield"].astype(float)))


def save_dividend_cache(data: dict[str, float], names: dict[str, str] | None = None) -> None:
    """配当データを dividend_data.csv に保存"""
    rows = [
        {"ticker": k, "name": (names or {}).get(k, ""), "div_yield": v}
        for k, v in data.items()
    ]
    pd.DataFrame(rows).to_csv(DIVIDEND_CACHE_FILE, index=False)


def fetch_dividend_yield(ticker_code: str) -> float | None:
    """
    yfinance で年間配当利回りを取得。
    ticker_code: 4桁コード → "{code}.T" 形式で検索
    失敗時は None を返す。
    """
    symbol = f"{ticker_code.lstrip('0') or ticker_code}.T"
    try:
        t = yf.Ticker(symbol)
        info = t.info
        if info.get("dividendYield"):
            yield_val = float(info["dividendYield"])
            # yfinanceは通常decimal形式（0.0424=4.24%）だが、
            # 銘柄によっては%形式（4.24）で返す場合がある
            # → *100 した結果が50%超なら既に%形式と判断して補正
            result = yield_val * 100
            if result > 50.0:
                return round(yield_val, 2) if yield_val <= 50.0 else None
            return round(result, 2)
        # dividendsの直近1年合計 / 現在株価 で計算
        hist = t.dividends
        if hist.empty:
            return None
        one_year_ago = hist.index[-1] - pd.DateOffset(years=1)
        annual = hist[hist.index >= one_year_ago].sum()
        price = info.get("currentPrice") or info.get("regularMarketPrice")
        if price and annual > 0:
            yield_pct = annual / price * 100
            # 50%超は異常値として除外
            return round(yield_pct, 2) if yield_pct <= 50.0 else None
    except Exception:
        pass
    return None


def fetch_all_dividend_yields(
    tickers: list[str],
    progress_callback=None,
) -> dict[str, float]:
    """複数銘柄の配当利回りを一括取得。取得できなかった銘柄はスキップ。"""
    results: dict[str, float] = {}
    for i, t in enumerate(tickers):
        val = fetch_dividend_yield(t)
        if val is not None:
            results[t] = val
        if progress_callback:
            progress_callback(i + 1, len(tickers))
    return results


# ------------------------------------------------------------------ #
# ファンダメンタルズデータ
# ------------------------------------------------------------------ #

def fetch_fundamental_data(ticker_code: str) -> dict:
    """yfinanceで1銘柄のファンダメンタルズ指標を取得する"""
    symbol = f"{ticker_code.lstrip('0') or ticker_code}.T"
    result: dict = {"ticker": ticker_code}
    try:
        info = yf.Ticker(symbol).info
        result.update({
            "roe":              info.get("returnOnEquity"),
            "roa":              info.get("returnOnAssets"),
            "debt_to_equity":   info.get("debtToEquity"),
            "current_ratio":    info.get("currentRatio"),
            "payout_ratio":     info.get("payoutRatio"),
            "revenue_growth":   info.get("revenueGrowth"),
            "earnings_growth":  info.get("earningsGrowth"),
            "pb_ratio":         info.get("priceToBook"),
            "pe_ratio":         info.get("forwardPE") or info.get("trailingPE"),
            "operating_margin": info.get("operatingMargins"),
        })
    except Exception:
        pass
    return result


def load_fundamental_cache() -> pd.DataFrame:
    """fundamental_data.csv からファンダメンタルズキャッシュを読む"""
    if not FUNDAMENTAL_CACHE_FILE.exists():
        return pd.DataFrame(columns=_FUND_COLS)
    df = pd.read_csv(FUNDAMENTAL_CACHE_FILE, dtype={"ticker": str})
    df["ticker"] = df["ticker"].str.zfill(4)
    return df


def save_fundamental_cache(df: pd.DataFrame) -> None:
    """ファンダメンタルズデータを fundamental_data.csv に保存"""
    df.to_csv(FUNDAMENTAL_CACHE_FILE, index=False)


def fetch_all_fundamental_data(
    tickers: list[str],
    progress_callback=None,
) -> pd.DataFrame:
    """複数銘柄のファンダメンタルズを一括取得"""
    rows = []
    for i, t in enumerate(tickers):
        rows.append(fetch_fundamental_data(t))
        if progress_callback:
            progress_callback(i + 1, len(tickers))
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ #
# スコアリング
# ------------------------------------------------------------------ #

def _score_safety(row: pd.Series) -> float:
    """安全性スコア（0-100）: D/E比率・流動比率・ROAで評価"""
    score = 0.0

    de = row.get("debt_to_equity")
    if pd.notna(de):
        if de < 50:    score += 40
        elif de < 100: score += 28
        elif de < 200: score += 16
        else:           score += 5
    else:
        score += 20  # データなしは中間値

    cr = row.get("current_ratio")
    if pd.notna(cr):
        if cr > 2.0:   score += 30
        elif cr > 1.5: score += 22
        elif cr > 1.0: score += 14
        else:           score += 5
    else:
        score += 15

    roa = row.get("roa")
    if pd.notna(roa):
        roa_pct = roa * 100
        if roa_pct > 8:   score += 30
        elif roa_pct > 5: score += 22
        elif roa_pct > 2: score += 12
        else:              score += 0
    else:
        score += 15

    return min(score, 100.0)


def _score_growth(row: pd.Series) -> float:
    """成長性スコア（0-100）: 売上・利益成長率で評価"""
    score = 0.0

    rg = row.get("revenue_growth")
    if pd.notna(rg):
        pct = rg * 100
        if pct > 10:   score += 50
        elif pct > 5:  score += 35
        elif pct > 0:  score += 20
        else:           score += 0
    else:
        score += 25

    eg = row.get("earnings_growth")
    if pd.notna(eg):
        pct = eg * 100
        if pct > 10:   score += 50
        elif pct > 5:  score += 35
        elif pct > 0:  score += 20
        else:           score += 0
    else:
        score += 25

    return min(score, 100.0)


def _score_profitability(row: pd.Series) -> float:
    """収益性スコア（0-100）: ROE・営業利益率で評価"""
    score = 0.0

    roe = row.get("roe")
    if pd.notna(roe):
        pct = roe * 100
        if pct > 15:   score += 50
        elif pct > 10: score += 37
        elif pct > 5:  score += 22
        else:           score += 5
    else:
        score += 25

    om = row.get("operating_margin")
    if pd.notna(om):
        pct = om * 100
        if pct > 20:   score += 50
        elif pct > 10: score += 35
        elif pct > 5:  score += 20
        else:           score += 5
    else:
        score += 25

    return min(score, 100.0)


def _score_shareholder_return(row: pd.Series, div_yield: float | None) -> float:
    """株主還元スコア（0-100）: 配当利回り・配当性向で評価"""
    score = 0.0

    if div_yield is not None and pd.notna(div_yield):
        if 3.0 <= div_yield <= 5.0:   score += 60
        elif 5.0 < div_yield <= 7.0:  score += 45
        elif 2.0 <= div_yield < 3.0:  score += 38
        elif 7.0 < div_yield <= 10.0: score += 30
        elif div_yield > 10.0:         score += 15
        else:                          score += 10
    else:
        score += 30

    pr = row.get("payout_ratio")
    if pd.notna(pr):
        pct = pr * 100
        if 30 <= pct <= 60:   score += 40
        elif 20 <= pct < 30:  score += 28
        elif 60 < pct <= 80:  score += 25
        elif pct > 80:         score += 10
        else:                  score += 15
    else:
        score += 20

    return min(score, 100.0)


def _score_value(row: pd.Series) -> float:
    """割安性スコア（0-100）: PBR・PERで評価"""
    score = 0.0

    pbr = row.get("pb_ratio")
    if pd.notna(pbr):
        if pbr < 1.0:   score += 50
        elif pbr < 1.5: score += 35
        elif pbr < 2.0: score += 22
        elif pbr < 3.0: score += 10
        else:            score += 0
    else:
        score += 25

    per = row.get("pe_ratio")
    if pd.notna(per) and per > 0:
        if per < 10:    score += 50
        elif per < 15:  score += 35
        elif per < 20:  score += 22
        elif per < 25:  score += 10
        else:            score += 0
    else:
        score += 25

    return min(score, 100.0)


def calc_stock_scores(
    fund_df: pd.DataFrame,
    div_cache: dict[str, float],
) -> pd.DataFrame:
    """
    各銘柄の5軸スコアを計算して返す。
    返却列: ticker, safety, growth, profitability, shareholder_return, value, total
    """
    if fund_df.empty:
        return pd.DataFrame(columns=[
            "ticker", "safety", "growth", "profitability",
            "shareholder_return", "value", "total",
        ])
    rows = []
    for _, row in fund_df.iterrows():
        t = str(row["ticker"])
        dy = div_cache.get(t)
        safety  = _score_safety(row)
        growth  = _score_growth(row)
        profit  = _score_profitability(row)
        sr      = _score_shareholder_return(row, dy)
        value   = _score_value(row)
        total   = round((safety + growth + profit + sr + value) / 5, 1)
        rows.append({
            "ticker":             t,
            "safety":             round(safety, 1),
            "growth":             round(growth, 1),
            "profitability":      round(profit, 1),
            "shareholder_return": round(sr, 1),
            "value":              round(value, 1),
            "total":              total,
        })
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ #
# ポートフォリオ計算
# ------------------------------------------------------------------ #

def calc_portfolio_summary(df: pd.DataFrame) -> dict:
    """ポートフォリオ全体サマリーを計算"""
    total_mv = df["market_value"].sum()
    total_pl = df["unrealized_pl"].sum()
    cost = total_mv - total_pl
    summary = {
        "total_market_value": total_mv,
        "total_unrealized_pl": total_pl,
        "total_unrealized_pl_pct": (total_pl / cost * 100) if cost != 0 else 0.0,
        "stock_count": len(df),
        "by_account": {},
    }

    for acct in df["account_type"].unique():
        sub = df[df["account_type"] == acct]
        sub_mv = sub["market_value"].sum()
        sub_pl = sub["unrealized_pl"].sum()
        sub_cost = sub_mv - sub_pl
        summary["by_account"][acct] = {
            "market_value": sub_mv,
            "unrealized_pl": sub_pl,
            "unrealized_pl_pct": (sub_pl / sub_cost * 100) if sub_cost != 0 else 0.0,
            "ratio": (sub_mv / total_mv * 100) if total_mv != 0 else 0.0,
        }

    return summary


def calc_with_dividend(
    df: pd.DataFrame, div_cache: dict[str, float]
) -> pd.DataFrame:
    """
    dfに配当関連列を追加して返す。
        div_yield_pct: 配当利回り（%）
        annual_div_per_share: 1株あたり年間配当（円）
        annual_div_total: 保有分年間配当合計（円）
    """
    df = df.copy()
    df["div_yield_pct"] = df["ticker"].map(div_cache)
    df["annual_div_per_share"] = (
        df["current_price"] * df["div_yield_pct"] / 100
    ).round(1)
    df["annual_div_total"] = (df["annual_div_per_share"] * df["shares"]).round(0)
    return df


def calc_sector_allocation(
    df: pd.DataFrame, sector_master: dict[str, str]
) -> pd.DataFrame:
    """セクター別時価評価額・比率のDataFrameを返す"""
    df = df.copy()
    df["sector"] = df["ticker"].apply(lambda t: get_sector(t, sector_master))
    sector_df = (
        df.groupby("sector")["market_value"]
        .sum()
        .reset_index()
        .sort_values("market_value", ascending=False)
    )
    total = sector_df["market_value"].sum()
    sector_df["ratio_pct"] = (sector_df["market_value"] / total * 100).round(1)
    return sector_df


def calc_annual_dividend_total(df: pd.DataFrame) -> float:
    """年間配当金合計（円）を返す。配当データがない銘柄は0として計算"""
    if "annual_div_total" not in df.columns:
        return 0.0
    return df["annual_div_total"].fillna(0).sum()


def check_ryogakucho_criteria(
    df: pd.DataFrame,
    summary: dict,
    sector_df: pd.DataFrame,
) -> list[dict]:
    """
    両学長の高配当株投資チェックリスト。
    各項目を {label, ok, detail} のdictリストで返す。
    """
    total_mv = summary["total_market_value"]
    annual_div = calc_annual_dividend_total(df)
    portfolio_yield = (annual_div / total_mv * 100) if total_mv > 0 else 0.0

    covered = df["div_yield_pct"].notna().sum() if "div_yield_pct" in df.columns else 0
    total = len(df)

    checks = [
        {
            "label": "ポートフォリオ利回り 3〜5%",
            "ok": 3.0 <= portfolio_yield <= 5.0,
            "detail": f"現在: {portfolio_yield:.2f}%",
        },
        {
            "label": "銘柄数 20以上（分散投資）",
            "ok": total >= 20,
            "detail": f"現在: {total}銘柄",
        },
        {
            "label": "セクター数 10以上",
            "ok": len(sector_df) >= 10,
            "detail": f"現在: {len(sector_df)}セクター",
        },
        {
            "label": "単一セクター比率 30%未満",
            "ok": sector_df["ratio_pct"].max() < 30.0 if not sector_df.empty else True,
            "detail": f"最大: {sector_df['ratio_pct'].max():.1f}% ({sector_df.iloc[0]['sector']})"
                       if not sector_df.empty else "データなし",
        },
        {
            "label": "配当データ取得率 80%以上",
            "ok": (covered / total >= 0.8) if total > 0 else False,
            "detail": f"{covered}/{total}銘柄",
        },
    ]
    return checks


# ------------------------------------------------------------------ #
# フォーマット
# ------------------------------------------------------------------ #

def fmt_yen(value: float | None) -> str:
    if value is None:
        return "—"
    sign = "+" if value > 0 else ""
    return f"{sign}¥{value:,.0f}"


def fmt_pct(value: float | None) -> str:
    if value is None:
        return "—"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.2f}%"
