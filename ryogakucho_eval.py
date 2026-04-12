"""
両学長（リベ大）の高配当株投資理論に基づく銘柄評価スコア計算モジュール。

両学長の高配当株投資スタイル（参考）:
  - 配当利回り 3%以上（目標4%以上）
  - 配当性向 50%以下（持続可能な水準）
  - 連続増配・維持（理想10年以上）
  - 自己資本比率 40%以上（財務健全性）
  - 業績が安定・右肩上がり（売上・EPS）

各スコアの計算式は FORMULAS 定数に文字列として定義されており、
ダッシュボードで計算根拠をそのまま表示できる。
データソース: ir_scraper.py が取得するIRバンクの過去10年実績データ。
"""
from __future__ import annotations

import pandas as pd

# ------------------------------------------------------------------ #
# 計算式の文字列定義（ダッシュボード表示用）
# ※ここに書かれた式と下の関数実装が1対1対応している
# ------------------------------------------------------------------ #

FORMULAS: dict[str, str] = {
    "dividend_continuity": """
#### ① 配当継続性スコア（0〜100点）

> 両学長が最重視する指標。長期にわたり配当をカットしない実績を評価。

```
連続スコア = min(直近から連続して増配・維持した年数 × 10,  60点)

カットボーナス =
  過去データ中 カット0回 → 40点
  過去データ中 カット1回 → 20点
  過去データ中 カット2回 →  5点
  過去データ中 カット3回以上 → 0点

配当継続性スコア = min(連続スコア + カットボーナス, 100)
```

**定義**:
- 連続増配・維持: 前年比でDPS（一株当たり配当）が同額または増加
- 配当カット: 前年比でDPSが減少したケース（無配転落もカット扱い）
- データは新しい年度から古い年度の順で比較
""",

    "payout_ratio": """
#### ② 配当性向適正スコア（0〜100点）

> 「30〜50%が理想」という両学長の基準を数値化。
> 高すぎると配当が持続困難（赤字時に即カット）、低すぎると株主還元への積極性が低い。

```
直近5年（データ不足時は利用可能な全期間）の配当性向平均を使用

avg_payout（%）に応じたスコア:
  20% ≤ avg_payout ≤ 50% → 100点（両学長の理想域）
  10% ≤ avg_payout < 20% →  60点（配当余力があるが積極性低め）
  50% < avg_payout ≤ 75% →  65点（やや高いが許容範囲）
  75% < avg_payout ≤ 100% → 25点（危険域：少し業績悪化で減配リスク）
  avg_payout > 100%        →  5点（赤字配当：持続不能）
  データなし               → 50点（中立）
```
""",

    "financial_health": """
#### ③ 財務健全性スコア（0〜100点）

> 自己資本比率（両学長基準: 40%以上）とEPS黒字率で財務の安定性を評価。

```
【自己資本比率スコア】 最大60点
  直近3年平均（データ不足時は利用可能な全期間の平均）
  60%以上 → 60点
  40〜60% → 48点
  30〜40% → 30点
  30%未満  → 15点
  データなし → 30点

【EPS黒字率スコア】 最大40点
  = (EPS > 0 だった年数 ÷ 総取得年数) × 40点
  例: 10年中9年黒字 → 9/10 × 40 = 36点

財務健全性スコア = 自己資本比率スコア + EPS黒字率スコア
```
""",

    "business_growth": """
#### ④ 業績成長性スコア（0〜100点）

> 売上高とEPSの長期CAGR（複利年成長率）で企業の成長力を評価。
> yfinanceの「直近四半期比較」ではなく、取得できた全期間のトレンドで判断する。

```
CAGR（複利年成長率）= (最新値 ÷ 最古値)^(1 ÷ 年数) - 1
  ※ 最新値・最古値のいずれかが 0 以下の場合はCAGR計算不可 → 中立点

【売上高 CAGR スコア】 最大50点
  CAGR ≥ 5%  → 50点
  CAGR ≥ 3%  → 40点（50の80%）
  CAGR ≥ 0%  → 28点（50の56%）
  CAGR < 0%  → 10点（50の20%）
  データ不足  → 25点（中立）

【EPS CAGR スコア】 最大50点（同上の閾値・点数を適用）

業績成長性スコア = 売上高CAGRスコア + EPSCAGRスコア
```
""",

    "dividend_yield": """
#### ⑤ 配当利回り適正スコア（0〜100点）

> 両学長の推奨帯「3〜5%」に近いほど高得点。
> 利回りが高すぎる場合は経営悪化・減配リスクのサインとして減点。

```
現在の配当利回り（%）に応じたスコア:
  3.0% ≤ yield ≤ 5.0% → 100点（両学長の理想域）
  5.0% < yield ≤ 7.0% →  75点（高めだが許容範囲）
  2.0% ≤ yield < 3.0% →  65点（やや低め）
  7.0% < yield ≤ 10.0% → 50点（高すぎ注意）
  yield < 2.0%          →  20点（高配当株として不十分）
  yield > 10.0%         →  20点（減配リスク極めて高い）
  データなし             →  40点（中立）
```
""",

    "operating_margin": """
#### ⑥ 営業利益率スコア（0〜100点）

> 両学長基準：10%以上なら優秀。5%以下は検討の余地なし。

```
直近3年（データ不足時は利用可能な全期間）の営業利益率平均を使用
営業利益率 = 営業利益 ÷ 売上高 × 100

avg_margin（%）に応じたスコア:
  avg_margin ≥ 10% → 100点（両学長の優秀基準）
  avg_margin ≥  5% →  60点（許容範囲）
  avg_margin ≥  0% →  30点（低収益・要注意）
  avg_margin <  0% →   5点（営業赤字）
  データなし        →  50点（中立）
```

※ 銀行・商社など営業利益が定義されない業種はデータなし扱い（50点）
""",

    "operating_cf": """
#### ⑦ 営業キャッシュフロースコア（0〜100点）

> 両学長基準：毎期黒字であること、長期的に増加傾向であること。
> 過去10年で1年でも赤字があれば高配当株には推奨しない。

```
【黒字継続スコア】 最大60点
  = (営業CF > 0 だった年数 ÷ 総取得年数) × 60点
  例: 10年中10年黒字 → 60点、10年中8年黒字 → 48点

【CAGR スコア】 最大40点
  CAGR ≥ 5% → 40点
  CAGR ≥ 0% → 25点（50の56%）
  CAGR < 0% → 8点（50の20%に相当）
  データ不足 → 20点（中立）

営業CFスコア = 黒字継続スコア + CAGRスコア
```
""",

    "cash": """
#### ⑧ 現金等スコア（0〜100点）

> 両学長基準：長期的に見て増加傾向であること（キャッシュリッチな企業を選ぶ）。

```
現金等のCAGRで評価（取得できた全期間）

CAGR ≥ 5% → 100点
CAGR ≥ 0% →  65点
CAGR < 0% →  20点
データなし  →  50点（中立）
```
""",

    "total": """
#### 両学長 総合スコア（0〜100点）

```
総合スコア = (配当継続性 + 配当性向適正 + 財務健全性 + 業績成長性
             + 配当利回り適正 + 営業利益率 + 営業CF + 現金等) ÷ 8
```

> **データソース**: IRバンク（irbank.net）からスクレイピングした過去実績データ
> （最大10年分以上）。yfinanceベースの現時点スナップショットとは異なり、
> 長期トレンドで企業の配当信頼性を評価します。
""",
}


# ------------------------------------------------------------------ #
# ヘルパー関数
# ------------------------------------------------------------------ #

def _get_field_series(results: list[dict], field: str) -> list[float | None]:
    """resultsリスト（新→古の年度順）から指定フィールドの値リストを返す"""
    return [row.get(field) for row in results]


def _valid_values(values: list[float | None]) -> list[float]:
    """Noneを除いた有効な数値リストを返す（順序維持）"""
    return [v for v in values if v is not None]


def _calc_cagr(start_val: float, end_val: float, years: int) -> float | None:
    """
    CAGR（複利年成長率）を計算。
    start_val: 古い年度の値（基点）
    end_val: 新しい年度の値（終点）
    years: 経過年数
    計算式: (end_val / start_val)^(1/years) - 1
    """
    if years <= 0 or start_val <= 0 or end_val <= 0:
        return None
    return (end_val / start_val) ** (1 / years) - 1


# ------------------------------------------------------------------ #
# 個別スコア計算関数
# ------------------------------------------------------------------ #

def score_dividend_continuity(results: list[dict]) -> tuple[float, dict]:
    """
    配当継続性スコアを計算（0〜100点）。
    計算式: FORMULAS["dividend_continuity"] 参照

    Returns:
        (score, breakdown_dict)
        breakdown_dict のキー: consecutive_years, cut_count, consecutive_score, cut_bonus
    """
    dps_list = _get_field_series(results, "dps")
    # Noneおよび0以下を除外
    valid_dps = [(i, d) for i, d in enumerate(dps_list) if d is not None and d > 0]

    if len(valid_dps) < 2:
        return (50.0, {"consecutive_years": 0, "cut_count": 0,
                       "consecutive_score": 0, "cut_bonus": 0,
                       "note": "データ不足（有効年度2年未満）"})

    # 連続増配・維持年数: 新年度 >= 旧年度 が続く間をカウント
    # valid_dps[0] = 最新、valid_dps[1] = 1年前、...
    consecutive = 1
    for i in range(len(valid_dps) - 1):
        curr = valid_dps[i][1]      # 新しい年のDPS
        prev = valid_dps[i + 1][1]  # 古い年のDPS
        if curr >= prev:             # 維持 or 増配
            consecutive += 1
        else:
            break

    # 過去全期間のカット回数（新→古の比較）
    cut_count = 0
    for i in range(len(valid_dps) - 1):
        curr = valid_dps[i][1]
        prev = valid_dps[i + 1][1]
        if curr < prev:
            cut_count += 1

    consecutive_score = min(consecutive * 10, 60)

    if cut_count == 0:
        cut_bonus = 40
    elif cut_count == 1:
        cut_bonus = 20
    elif cut_count == 2:
        cut_bonus = 5
    else:
        cut_bonus = 0

    score = min(float(consecutive_score + cut_bonus), 100.0)

    breakdown = {
        "consecutive_years": consecutive,
        "cut_count": cut_count,
        "consecutive_score": consecutive_score,
        "cut_bonus": cut_bonus,
    }
    return (score, breakdown)


def score_payout_ratio(results: list[dict]) -> tuple[float, dict]:
    """
    配当性向適正スコアを計算（0〜100点）。直近5年平均配当性向を使用。
    計算式: FORMULAS["payout_ratio"] 参照

    Returns:
        (score, breakdown_dict)
        breakdown_dict のキー: avg_payout_pct, years_used
    """
    payout_list = _get_field_series(results, "payout_ratio")
    recent_5 = _valid_values(payout_list[:5])  # 直近5年分

    if not recent_5:
        return (50.0, {"avg_payout_pct": None, "years_used": 0})

    avg_payout = sum(recent_5) / len(recent_5)

    if 20.0 <= avg_payout <= 50.0:
        score = 100.0
    elif 10.0 <= avg_payout < 20.0:
        score = 60.0
    elif 50.0 < avg_payout <= 75.0:
        score = 65.0
    elif 75.0 < avg_payout <= 100.0:
        score = 25.0
    elif avg_payout > 100.0:
        score = 5.0
    else:   # avg_payout < 10%
        score = 40.0

    breakdown = {
        "avg_payout_pct": round(avg_payout, 1),
        "years_used": len(recent_5),
    }
    return (score, breakdown)


def score_financial_health(results: list[dict]) -> tuple[float, dict]:
    """
    財務健全性スコアを計算（0〜100点）。
    自己資本比率（直近3年平均）とEPS黒字率で評価。
    計算式: FORMULAS["financial_health"] 参照

    Returns:
        (score, breakdown_dict)
        breakdown_dict のキー: avg_equity_ratio, equity_score, eps_positive_rate_pct, eps_score
    """
    eq_list = _get_field_series(results, "equity_ratio")
    recent_3_eq = _valid_values(eq_list[:3])

    # 自己資本比率スコア（max 60点）
    if recent_3_eq:
        avg_equity = sum(recent_3_eq) / len(recent_3_eq)
        if avg_equity >= 60.0:
            eq_score = 60.0
        elif avg_equity >= 40.0:
            eq_score = 48.0
        elif avg_equity >= 30.0:
            eq_score = 30.0
        else:
            eq_score = 15.0
    else:
        avg_equity = None
        eq_score = 30.0  # データなし → 中立

    # EPS黒字率スコア（max 40点）
    # = (EPS > 0 だった年数 / 総年数) × 40
    eps_all = _valid_values(_get_field_series(results, "eps"))
    if eps_all:
        positive_count = sum(1 for e in eps_all if e > 0)
        eps_positive_rate = positive_count / len(eps_all)
        eps_score = eps_positive_rate * 40.0
    else:
        eps_positive_rate = None
        eps_score = 20.0  # データなし → 中立

    score = min(eq_score + eps_score, 100.0)

    breakdown = {
        "avg_equity_ratio": round(avg_equity, 1) if avg_equity is not None else None,
        "equity_score": round(eq_score, 1),
        "eps_positive_rate_pct": round(eps_positive_rate * 100, 1) if eps_positive_rate is not None else None,
        "eps_score": round(eps_score, 1),
    }
    return (score, breakdown)


def score_business_growth(results: list[dict]) -> tuple[float, dict]:
    """
    業績成長性スコアを計算（0〜100点）。
    売上高とEPSのCAGR（複利年成長率）で評価。
    計算式: FORMULAS["business_growth"] 参照

    Returns:
        (score, breakdown_dict)
        breakdown_dict のキー: revenue_cagr_pct, eps_cagr_pct, revenue_years, eps_years
    """
    revenue_vals = _valid_values(_get_field_series(results, "revenue"))
    eps_vals = _valid_values(_get_field_series(results, "eps"))

    def _cagr_score(values: list[float], max_pts: float) -> tuple[float, float | None, int]:
        """CAGR計算とスコア変換。(score, cagr_pct, years) を返す"""
        if len(values) < 2:
            return (max_pts * 0.5, None, 0)  # データ不足 → 中立点

        years = len(values) - 1
        newest = values[0]   # resultsは新→古順なので values[0] が最新
        oldest = values[-1]
        cagr = _calc_cagr(oldest, newest, years)

        if cagr is None:
            return (max_pts * 0.5, None, years)

        if cagr >= 0.05:
            pts = max_pts * 1.00   # 50点（CAGR 5%以上）
        elif cagr >= 0.03:
            pts = max_pts * 0.80   # 40点（CAGR 3〜5%）
        elif cagr >= 0.00:
            pts = max_pts * 0.56   # 28点（CAGR 0〜3%）
        else:
            pts = max_pts * 0.20   # 10点（CAGR マイナス）

        return (pts, round(cagr * 100, 2), years)

    rev_score, rev_cagr, rev_years = _cagr_score(revenue_vals, 50.0)
    eps_score, eps_cagr, eps_years = _cagr_score(eps_vals, 50.0)

    score = min(rev_score + eps_score, 100.0)

    breakdown = {
        "revenue_cagr_pct": rev_cagr,
        "eps_cagr_pct": eps_cagr,
        "revenue_years": rev_years,
        "eps_years": eps_years,
    }
    return (score, breakdown)


def score_operating_margin(results: list[dict]) -> tuple[float, dict]:
    """
    営業利益率スコアを計算（0〜100点）。直近3年平均営業利益率を使用。
    計算式: FORMULAS["operating_margin"] 参照

    Returns:
        (score, breakdown_dict)
        breakdown_dict のキー: avg_margin_pct, years_used
    """
    margins: list[float] = []
    for row in results[:3]:  # 直近3年
        op = row.get("operating_profit")
        rev = row.get("revenue")
        if op is not None and rev is not None and rev != 0:
            margins.append(op / rev * 100)

    if not margins:
        return (50.0, {"avg_margin_pct": None, "years_used": 0})

    avg_margin = sum(margins) / len(margins)

    if avg_margin >= 10.0:
        score = 100.0
    elif avg_margin >= 5.0:
        score = 60.0
    elif avg_margin >= 0.0:
        score = 30.0
    else:
        score = 5.0

    return (score, {"avg_margin_pct": round(avg_margin, 1), "years_used": len(margins)})


def score_operating_cf(results: list[dict]) -> tuple[float, dict]:
    """
    営業キャッシュフロースコアを計算（0〜100点）。
    黒字継続率 + CAGRで評価。
    計算式: FORMULAS["operating_cf"] 参照

    Returns:
        (score, breakdown_dict)
        breakdown_dict のキー: positive_rate_pct, years_used, cagr_pct
    """
    cf_vals = _valid_values(_get_field_series(results, "operating_cf"))

    if not cf_vals:
        return (50.0, {"positive_rate_pct": None, "years_used": 0, "cagr_pct": None})

    # 黒字継続スコア（max 60点）
    positive_count = sum(1 for v in cf_vals if v > 0)
    positive_rate = positive_count / len(cf_vals)
    positive_score = positive_rate * 60.0

    # CAGRスコア（max 40点）
    if len(cf_vals) >= 2:
        # results は新→古順なので cf_vals[0] が最新、cf_vals[-1] が最古
        cagr = _calc_cagr(cf_vals[-1], cf_vals[0], len(cf_vals) - 1)
        if cagr is None:
            cagr_score = 20.0
            cagr_pct = None
        elif cagr >= 0.05:
            cagr_score = 40.0
            cagr_pct = round(cagr * 100, 2)
        elif cagr >= 0.0:
            cagr_score = 25.0
            cagr_pct = round(cagr * 100, 2)
        else:
            cagr_score = 8.0
            cagr_pct = round(cagr * 100, 2)
    else:
        cagr_score = 20.0
        cagr_pct = None

    score = min(positive_score + cagr_score, 100.0)

    breakdown = {
        "positive_rate_pct": round(positive_rate * 100, 1),
        "years_used": len(cf_vals),
        "cagr_pct": cagr_pct,
    }
    return (score, breakdown)


def score_cash(results: list[dict]) -> tuple[float, dict]:
    """
    現金等スコアを計算（0〜100点）。長期CAGRで評価。
    計算式: FORMULAS["cash"] 参照

    Returns:
        (score, breakdown_dict)
        breakdown_dict のキー: cagr_pct, years_used
    """
    cash_vals = _valid_values(_get_field_series(results, "cash"))

    if len(cash_vals) < 2:
        return (50.0, {"cagr_pct": None, "years_used": len(cash_vals)})

    # results は新→古順なので cash_vals[0] が最新、cash_vals[-1] が最古
    cagr = _calc_cagr(cash_vals[-1], cash_vals[0], len(cash_vals) - 1)

    if cagr is None:
        return (50.0, {"cagr_pct": None, "years_used": len(cash_vals)})

    if cagr >= 0.05:
        score = 100.0
    elif cagr >= 0.0:
        score = 65.0
    else:
        score = 20.0

    return (score, {"cagr_pct": round(cagr * 100, 2), "years_used": len(cash_vals)})


def score_dividend_yield(div_yield: float | None) -> tuple[float, dict]:
    """
    配当利回り適正スコアを計算（0〜100点）。
    計算式: FORMULAS["dividend_yield"] 参照

    Returns:
        (score, breakdown_dict)
        breakdown_dict のキー: div_yield_pct
    """
    if div_yield is None or not (0 < div_yield < 100):
        return (40.0, {"div_yield_pct": div_yield})

    if 3.0 <= div_yield <= 5.0:
        score = 100.0
    elif 5.0 < div_yield <= 7.0:
        score = 75.0
    elif 2.0 <= div_yield < 3.0:
        score = 65.0
    elif 7.0 < div_yield <= 10.0:
        score = 50.0
    else:   # < 2% or > 10%
        score = 20.0

    return (score, {"div_yield_pct": round(div_yield, 2)})


# ------------------------------------------------------------------ #
# メイン評価関数
# ------------------------------------------------------------------ #

def calc_ryogakucho_scores(
    ticker: str,
    ir_data: dict,
    div_yield: float | None,
) -> dict:
    """
    1銘柄の両学長スコアを計算して返す。

    Args:
        ticker: 4桁銘柄コード
        ir_data: ir_scraper.get_ir_data() の返却値
        div_yield: 現在の配当利回り（%）

    Returns:
        dict: {
            "ticker": str,
            "dividend_continuity": float (0-100),
            "payout_ratio_score": float (0-100),
            "financial_health": float (0-100),
            "business_growth": float (0-100),
            "dividend_yield_score": float (0-100),
            "total": float (0-100),
            "breakdown": dict,  # 各軸の詳細計算情報
        }
    """
    results = ir_data.get("results", [])

    s1, b1 = score_dividend_continuity(results)
    s2, b2 = score_payout_ratio(results)
    s3, b3 = score_financial_health(results)
    s4, b4 = score_business_growth(results)
    s5, b5 = score_dividend_yield(div_yield)
    s6, b6 = score_operating_margin(results)
    s7, b7 = score_operating_cf(results)
    s8, b8 = score_cash(results)

    total = round((s1 + s2 + s3 + s4 + s5 + s6 + s7 + s8) / 8, 1)

    return {
        "ticker": ticker,
        "dividend_continuity": round(s1, 1),
        "payout_ratio_score": round(s2, 1),
        "financial_health": round(s3, 1),
        "business_growth": round(s4, 1),
        "dividend_yield_score": round(s5, 1),
        "operating_margin_score": round(s6, 1),
        "operating_cf_score": round(s7, 1),
        "cash_score": round(s8, 1),
        "total": total,
        "breakdown": {
            "dividend_continuity": b1,
            "payout_ratio": b2,
            "financial_health": b3,
            "business_growth": b4,
            "dividend_yield": b5,
            "operating_margin": b6,
            "operating_cf": b7,
            "cash": b8,
        },
    }


def calc_all_ryogakucho_scores(
    ir_data_dict: dict[str, dict],
    div_cache: dict[str, float],
) -> pd.DataFrame:
    """
    複数銘柄の両学長スコアをまとめてDataFrameで返す。

    Returns:
        columns: ticker, dividend_continuity, payout_ratio_score,
                 financial_health, business_growth, dividend_yield_score, total
        IRデータが空の銘柄は除外。
    """
    rows = []
    for ticker, ir_data in ir_data_dict.items():
        if not ir_data.get("results"):
            continue
        dy = div_cache.get(ticker)
        row = calc_ryogakucho_scores(ticker, ir_data, dy)
        # breakdown を除いたフラットな行を追加
        rows.append({k: v for k, v in row.items() if k != "breakdown"})

    if not rows:
        return pd.DataFrame(columns=[
            "ticker", "dividend_continuity", "payout_ratio_score",
            "financial_health", "business_growth", "dividend_yield_score",
            "operating_margin_score", "operating_cf_score", "cash_score", "total",
        ])
    return pd.DataFrame(rows)
