"""
高配当株ポートフォリオマネージャー
両学長の高配当株投資理論に基づくSBI証券CSV分析ツール
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go

from utils import (
    load_monex_csv,
    load_rakuten_csv,
    combine_positions,
    load_dividend_cache,
    save_dividend_cache,
    load_sector_master,
    load_fundamental_cache,
    save_fundamental_cache,
    fetch_all_fundamental_data,
    calc_portfolio_summary,
    calc_with_dividend,
    calc_sector_allocation,
    calc_annual_dividend_total,
    calc_stock_scores,
    check_ryogakucho_criteria,
    fetch_all_dividend_yields,
    classify_investment_style,
    get_sector,
    fmt_yen,
    fmt_pct,
)
from ir_scraper import fetch_all_ir_data, load_all_ir_caches, get_scrape_errors
from ryogakucho_eval import calc_all_ryogakucho_scores, calc_ryogakucho_scores, FORMULAS

st.set_page_config(
    page_title="高配当株ポートフォリオマネージャー",
    page_icon="📈",
    layout="wide",
)

# ------------------------------------------------------------------ #
# セッション初期化
# ------------------------------------------------------------------ #

if "df_monex" not in st.session_state:
    st.session_state.df_monex = None
if "df_rakuten" not in st.session_state:
    st.session_state.df_rakuten = None
if "div_cache" not in st.session_state:
    st.session_state.div_cache = load_dividend_cache()
if "sector_master" not in st.session_state:
    st.session_state.sector_master = load_sector_master()
if "fund_cache" not in st.session_state:
    st.session_state.fund_cache = load_fundamental_cache()
if "ir_data" not in st.session_state:
    st.session_state.ir_data = {}

# ------------------------------------------------------------------ #
# サイドバー
# ------------------------------------------------------------------ #

with st.sidebar:
    st.title("📂 データ読み込み")

    pos_file = st.file_uploader(
        "マネックス証券CSV (stockposition_*.csv)",
        type="csv",
        key="pos_uploader",
    )
    bal_file = st.file_uploader(
        "楽天証券CSV (assetbalance_*.csv)",
        type="csv",
        key="bal_uploader",
    )

    if pos_file:
        try:
            st.session_state.df_monex = load_monex_csv(pos_file)
            st.success(f"マネックス: {len(st.session_state.df_monex)}銘柄")
        except Exception as e:
            st.error(f"マネックスCSVエラー: {e}")

    if bal_file:
        try:
            st.session_state.df_rakuten = load_rakuten_csv(bal_file)
            st.success(f"楽天証券: {len(st.session_state.df_rakuten)}銘柄")
        except Exception as e:
            st.error(f"楽天証券CSVエラー: {e}")

    st.divider()
    # 資産マスキングモード（他の人に見せる際に金額を非表示にする）
    mask = st.checkbox(
        "👁 資産マスキングモード",
        value=False,
        help="ONにすると金額・損益を非表示にします。画面共有時などにご利用ください。",
    )
    if mask:
        st.info("マスキングON: 金額非表示中")

    st.divider()
    st.subheader("配当データ管理")

    if st.button("🔄 yfinanceで一括取得", use_container_width=True):
        _all_dfs = [d for d in [st.session_state.df_monex, st.session_state.df_rakuten] if d is not None]
        if _all_dfs:
            _combined = pd.concat(_all_dfs, ignore_index=True)
            tickers = _combined["ticker"].unique().tolist()
            names = dict(zip(_combined["ticker"], _combined["name"]))
            bar = st.progress(0, text="取得中...")

            def _progress(done, total):
                bar.progress(done / total, text=f"取得中... {done}/{total}")

            new_data = fetch_all_dividend_yields(tickers, progress_callback=_progress)
            st.session_state.div_cache.update(new_data)
            save_dividend_cache(st.session_state.div_cache, names)
            bar.empty()
            st.success(f"{len(new_data)}銘柄の配当データを取得しました")
        else:
            st.warning("先にCSVを読み込んでください")

    if st.button("🔄 セクターマスタ再読み込み", use_container_width=True):
        st.session_state.sector_master = load_sector_master()
        st.success("セクターマスタを更新しました")

# ------------------------------------------------------------------ #
# メインエリア
# ------------------------------------------------------------------ #

st.title("📈 高配当株ポートフォリオマネージャー")

df_combined = combine_positions(st.session_state.df_monex, st.session_state.df_rakuten)

if df_combined.empty:
    st.info("👈 サイドバーからCSVをアップロードしてください。")
    st.markdown("""
    ### 使い方
    | ファイル | 証券会社 | ダウンロード場所 |
    |---------|---------|----------------|
    | `stockposition_*.csv` | マネックス証券 | ポートフォリオ → 保有証券一覧 → CSV出力 |
    | `assetbalance_*.csv` | 楽天証券 | 保有証券 → 国内株式 → CSV出力 |

    どちらか一方だけでも利用できます。
    """)
    st.stop()

# データ加工
df: pd.DataFrame = df_combined
div_cache: dict[str, float] = st.session_state.div_cache
sector_master: dict[str, str] = st.session_state.sector_master
fund_cache: pd.DataFrame = st.session_state.fund_cache

df = calc_with_dividend(df, div_cache)
# セクター列を付与（全タブで共用）
df["sector"] = df["ticker"].apply(lambda t: get_sector(t, sector_master))

summary = calc_portfolio_summary(df)
sector_df = calc_sector_allocation(df, sector_master)
annual_div = calc_annual_dividend_total(df)
portfolio_yield = (annual_div / summary["total_market_value"] * 100) if summary["total_market_value"] > 0 else 0.0

# ------------------------------------------------------------------ #
# タブ
# ------------------------------------------------------------------ #

tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
    "📊 サマリー",
    "📋 銘柄一覧",
    "🥧 セクター分散",
    "💰 配当データ管理",
    "📉 分散分析",
    "🔍 銘柄評価",
    "🗂 生データ",
])

def _color_score(val):
    if pd.isna(val):
        return ""
    if val >= 70:
        return "background-color: #d5f5e3; color: #1e8449"
    if val >= 50:
        return "background-color: #fef9e7; color: #7d6608"
    return "background-color: #fadbd8; color: #922b21"


# ========== Tab1: サマリー ========== #
with tab1:
    _M = "¥ — — —" if mask else None  # マスク時の表示文字列

    col1, col2, col3, col4 = st.columns(4)
    col1.metric(
        "総時価評価額",
        _M or f"¥{summary['total_market_value']:,.0f}",
    )
    col2.metric(
        "総含み損益",
        _M or fmt_yen(summary["total_unrealized_pl"]),
        delta=None if mask else fmt_pct(summary["total_unrealized_pl_pct"]),
        delta_color="normal",
    )
    col3.metric(
        "年間配当金見込み",
        _M or f"¥{annual_div:,.0f}",
        delta=None if mask else f"月平均 ¥{annual_div/12:,.0f}",
        delta_color="off",
    )
    col4.metric(
        "ポートフォリオ利回り",
        fmt_pct(portfolio_yield),
        delta="目標 3〜5%" if not (3.0 <= portfolio_yield <= 5.0) else "目標達成",
        delta_color="off",
    )

    st.divider()

    # 口座別内訳
    st.subheader("口座別内訳")
    acct_rows = []
    for acct, vals in summary["by_account"].items():
        acct_rows.append({
            "口座": acct,
            "時価評価額": "¥ — — —" if mask else f"¥{vals['market_value']:,.0f}",
            "含み損益": "— — —" if mask else fmt_yen(vals["unrealized_pl"]),
            "含み損益率": "— — —" if mask else fmt_pct(vals["unrealized_pl_pct"]),
            "比率": f"{vals['ratio']:.1f}%",
        })
    if acct_rows:
        st.dataframe(
            pd.DataFrame(acct_rows),
            use_container_width=True,
            hide_index=True,
        )

    # 口座別円グラフ
    if len(summary["by_account"]) > 1:
        _hover_acct = (
            "<b>%{label}</b><br>%{percent}<extra></extra>" if mask
            else "<b>%{label}</b><br>¥%{value:,.0f}<br>%{percent}<extra></extra>"
        )
        fig_acct = go.Figure(go.Pie(
            labels=list(summary["by_account"].keys()),
            values=[v["market_value"] for v in summary["by_account"].values()],
            hole=0.4,
            hovertemplate=_hover_acct,
        ))
        fig_acct.update_layout(
            title="口座別 時価評価額",
            height=300,
            margin=dict(t=40, b=0, l=0, r=0),
        )
        st.plotly_chart(fig_acct, use_container_width=True)


# ========== Tab2: 銘柄一覧 ========== #
with tab2:
    display_df = df.copy()
    display_df["セクター"] = display_df["sector"]

    cols_order = {
        "ticker":              "コード",
        "name":                "銘柄名",
        "account_type":        "口座",
        "セクター":             "セクター",
        "current_price":       "現在値(円)",
        "avg_cost":            "平均取得(円)",
        "shares":              "保有数",
        "market_value":        "時価評価額(円)",
        "unrealized_pl":       "含み損益(円)",
        "unrealized_pl_pct":   "含み損益率(%)",
        "div_yield_pct":       "配当利回り(%)",
        "annual_div_total":    "年間配当金(円)",
    }
    disp = display_df.rename(columns=cols_order)[
        [v for v in cols_order.values() if v in display_df.rename(columns=cols_order).columns]
    ].copy()

    def _color_yield(val):
        """配当利回り色分け: 3%未満=赤, 3~5%=緑, 5%超=青"""
        if pd.isna(val):
            return ""
        if val < 3.0:
            return "color: #e74c3c"
        if val <= 5.0:
            return "color: #27ae60; font-weight: bold"
        return "color: #2980b9"

    def _color_pl(val):
        """含み損益 色分け"""
        if pd.isna(val):
            return ""
        return "color: #27ae60" if val >= 0 else "color: #e74c3c"

    if mask:
        # マスキング時は金額列を文字列置換してからスタイル適用
        _MASK_STR = "— — —"
        for col in ["現在値(円)", "平均取得(円)", "時価評価額(円)", "含み損益(円)", "含み損益率(%)", "年間配当金(円)"]:
            if col in disp.columns:
                disp[col] = _MASK_STR
        styled = disp.style.map(_color_yield, subset=["配当利回り(%)"])
    else:
        def _fmt_num(fmt: str, prefix: str = ""):
            """数値なら fmt で整形、そうでなければそのまま返す"""
            def _f(v):
                if pd.isna(v) or not isinstance(v, (int, float)):
                    return "—"
                return prefix + format(v, fmt)
            return _f

        styled = disp.style.map(_color_yield, subset=["配当利回り(%)"]).map(
            _color_pl, subset=["含み損益(円)", "含み損益率(%)"]
        ).format(
            {
                "現在値(円)":      _fmt_num(",.1f"),
                "平均取得(円)":    _fmt_num(",.2f"),
                "時価評価額(円)":  _fmt_num(",.0f"),
                "含み損益(円)":    lambda v: "—" if pd.isna(v) or not isinstance(v, (int, float)) else f"{v:+,.0f}",
                "含み損益率(%)":   lambda v: "—" if pd.isna(v) or not isinstance(v, (int, float)) else f"{v:+.2f}%",
                "配当利回り(%)":   lambda v: "—" if pd.isna(v) or not isinstance(v, (int, float)) else f"{v:.2f}%",
                "年間配当金(円)":  lambda v: "—" if pd.isna(v) or not isinstance(v, (int, float)) else f"¥{v:,.0f}",
            },
        )

    st.dataframe(styled, use_container_width=True, hide_index=True, height=600)

    st.caption(
        f"合計: {len(disp)}銘柄 ｜ "
        + ("時価合計: ¥ — — — ｜ 含み損益合計: — — — ｜ 年間配当合計: ¥ — — —" if mask else
           f"時価合計: ¥{df['market_value'].sum():,.0f} ｜ "
           f"含み損益合計: {fmt_yen(df['unrealized_pl'].sum())} ｜ "
           f"年間配当合計: ¥{annual_div:,.0f}")
    )


# ========== Tab3: セクター分散 ========== #
with tab3:
    col_chart, col_check = st.columns([3, 2])

    with col_chart:
        _hover_sector = (
            "<b>%{label}</b><br>%{percent}<extra></extra>" if mask
            else "<b>%{label}</b><br>¥%{value:,.0f}<br>%{percent}<extra></extra>"
        )
        fig_sector = go.Figure(go.Pie(
            labels=sector_df["sector"],
            values=sector_df["market_value"],
            text=sector_df["ratio_pct"].apply(lambda v: f"{v:.1f}%"),
            hovertemplate=_hover_sector,
            hole=0.3,
        ))
        fig_sector.update_layout(
            title="セクター別 時価評価額",
            height=450,
            margin=dict(t=50, b=0, l=0, r=0),
        )
        st.plotly_chart(fig_sector, use_container_width=True)

        _sector_disp = sector_df.rename(columns={
            "sector": "セクター",
            "market_value": "時価評価額(円)",
            "ratio_pct": "比率(%)",
        }).copy()
        if mask:
            _sector_disp["時価評価額(円)"] = "— — —"
            _sector_style = _sector_disp.style.format({"比率(%)": "{:.1f}%"}).bar(
                subset=["比率(%)"], color="#4a90d9"
            )
        else:
            _sector_style = _sector_disp.style.format({
                "時価評価額(円)": "{:,.0f}",
                "比率(%)": "{:.1f}%",
            }).bar(subset=["比率(%)"], color="#4a90d9")
        st.dataframe(_sector_style, use_container_width=True, hide_index=True)

    with col_check:
        st.subheader("両学長チェックリスト")
        checks = check_ryogakucho_criteria(df, summary, sector_df)
        for c in checks:
            icon = "✅" if c["ok"] else "⚠️"
            status = st.success if c["ok"] else st.warning
            status(f"{icon} **{c['label']}**\n\n{c['detail']}")

        st.divider()
        st.caption("参考: 両学長の高配当株投資ルール")
        st.markdown("""
        - 配当利回り **3〜5%** を目標にする
        - 銘柄数は **20〜30銘柄** に分散
        - 単一セクターへの集中を避ける（目安: 30%未満）
        - 連続増配 or 安定配当銘柄を選ぶ
        - 含み損は気にせず **配当金** に注目する
        """)


# ========== Tab4: 配当データ管理 ========== #
with tab4:
    st.subheader("配当利回りデータ")
    st.caption("yfinanceで取得できない場合は手動で編集できます。保存ボタンで反映されます。")

    cache_rows = []
    for _, row in df.iterrows():
        cache_rows.append({
            "ticker":     row["ticker"],
            "name":       row["name"],
            "div_yield":  div_cache.get(row["ticker"], None),
        })
    cache_df = pd.DataFrame(cache_rows).drop_duplicates(subset=["ticker"])

    edited = st.data_editor(
        cache_df,
        column_config={
            "ticker":    st.column_config.TextColumn("コード", disabled=True),
            "name":      st.column_config.TextColumn("銘柄名", disabled=True),
            "div_yield": st.column_config.NumberColumn(
                "配当利回り(%)",
                min_value=0.0,
                max_value=20.0,
                step=0.01,
                format="%.2f",
            ),
        },
        use_container_width=True,
        hide_index=True,
    )

    if st.button("💾 保存する", type="primary"):
        new_cache = {
            row["ticker"]: row["div_yield"]
            for _, row in edited.iterrows()
            if row["div_yield"] is not None and not pd.isna(row["div_yield"])
        }
        names = dict(zip(edited["ticker"], edited["name"]))
        st.session_state.div_cache = new_cache
        save_dividend_cache(new_cache, names)
        st.success("配当データを保存しました。画面を再描画します...")
        st.rerun()


# ========== Tab5: 分散分析 ========== #
with tab5:
    st.subheader("ポートフォリオ分散状況")

    _hover_mv   = "<b>%{label}</b><br>%{percent}<extra></extra>" if mask else "<b>%{label}</b><br>¥%{value:,.0f}<br>%{percent}<extra></extra>"
    _hover_div  = "<b>%{label}</b><br>%{percent}<extra></extra>" if mask else "<b>%{label}</b><br>¥%{value:,.0f}<br>%{percent}<extra></extra>"
    _PIE_H      = 380
    _PIE_MARGIN = dict(t=55, b=10, l=10, r=10)

    # ---- 共通データ ----
    # 投資スタイル列
    df["投資スタイル"] = df["sector"].apply(classify_investment_style)

    _STYLE_COLORS = {
        "ディフェンシブ": "#2ecc71",
        "景気敏感":       "#e74c3c",
        "金融":           "#3498db",
        "REIT・ETF":     "#9b59b6",
        "その他":         "#95a5a6",
    }

    TOP_N = 15

    # ---- 評価額ベースのデータ ----
    # 企業別（評価額）
    mv_stock_df = (
        df.groupby(["ticker", "name"])["market_value"]
        .sum().reset_index().sort_values("market_value", ascending=False)
    )
    if len(mv_stock_df) > TOP_N:
        _top = mv_stock_df.iloc[:TOP_N].copy()
        _others_row = pd.DataFrame([{
            "ticker": "—", "name": f"その他 ({len(mv_stock_df) - TOP_N}銘柄)",
            "market_value": mv_stock_df.iloc[TOP_N:]["market_value"].sum(),
        }])
        mv_stock_df = pd.concat([_top, _others_row], ignore_index=True)

    # セクター別（評価額）: sector_df 既存
    # 投資スタイル別（評価額）
    mv_style_df = (
        df.groupby("投資スタイル")["market_value"]
        .sum().reset_index().sort_values("market_value", ascending=False)
    )

    # ---- 配当金ベースのデータ ----
    _div_df = df[df["annual_div_total"].notna() & (df["annual_div_total"] > 0)].copy()

    # 企業別（配当金）
    div_stock_df = (
        _div_df.groupby(["ticker", "name"])["annual_div_total"]
        .sum().reset_index().sort_values("annual_div_total", ascending=False)
    )
    if len(div_stock_df) > TOP_N:
        _top_d = div_stock_df.iloc[:TOP_N].copy()
        _others_d = pd.DataFrame([{
            "ticker": "—", "name": f"その他 ({len(div_stock_df) - TOP_N}銘柄)",
            "annual_div_total": div_stock_df.iloc[TOP_N:]["annual_div_total"].sum(),
        }])
        div_stock_df = pd.concat([_top_d, _others_d], ignore_index=True)

    # セクター別（配当金）
    div_sector_df = (
        _div_df.groupby("sector")["annual_div_total"]
        .sum().reset_index().sort_values("annual_div_total", ascending=False)
        .rename(columns={"sector": "sector"})
    )

    # 投資スタイル別（配当金）
    div_style_df = (
        _div_df.groupby("投資スタイル")["annual_div_total"]
        .sum().reset_index().sort_values("annual_div_total", ascending=False)
    )

    # ---- グラフ生成 ----
    def _pie(labels, values, title, hover, colors=None, **kw):
        trace_kw = dict(labels=labels, values=values, hovertemplate=hover, hole=0.32)
        if colors is not None:
            trace_kw["marker_colors"] = colors
        fig = go.Figure(go.Pie(**trace_kw))
        fig.update_layout(
            title=dict(text=title, font=dict(size=13)),
            height=_PIE_H, margin=_PIE_MARGIN,
            legend=dict(font=dict(size=10)),
            **kw,
        )
        return fig

    # 上段: 評価額ベース
    fig_mv_stock = _pie(
        mv_stock_df["name"], mv_stock_df["market_value"],
        "企業別構成比（評価額）", _hover_mv,
    )
    fig_mv_sector = _pie(
        sector_df["sector"], sector_df["market_value"],
        "業界別構成比（評価額）", _hover_mv,
    )
    fig_mv_style = _pie(
        mv_style_df["投資スタイル"], mv_style_df["market_value"],
        "景気感応度別構成比（評価額）", _hover_mv,
        colors=[_STYLE_COLORS.get(s, "#95a5a6") for s in mv_style_df["投資スタイル"]],
    )

    # 下段: 配当金ベース
    if _div_df.empty:
        _no_div_msg = True
    else:
        _no_div_msg = False
        fig_div_stock = _pie(
            div_stock_df["name"], div_stock_df["annual_div_total"],
            "企業別構成比（配当金額）", _hover_div,
        )
        fig_div_sector = _pie(
            div_sector_df["sector"], div_sector_df["annual_div_total"],
            "業界別構成比（配当金額）", _hover_div,
        )
        fig_div_style = _pie(
            div_style_df["投資スタイル"], div_style_df["annual_div_total"],
            "景気感応度別構成比（配当金額）", _hover_div,
            colors=[_STYLE_COLORS.get(s, "#95a5a6") for s in div_style_df["投資スタイル"]],
        )

    # ---- 3×2 レイアウト ----
    st.caption("上段：評価額ベース　｜　下段：配当金額ベース")

    col_a, col_b, col_c = st.columns(3)
    with col_a:
        st.plotly_chart(fig_mv_stock,  use_container_width=True)
    with col_b:
        st.plotly_chart(fig_mv_sector, use_container_width=True)
    with col_c:
        st.plotly_chart(fig_mv_style,  use_container_width=True)

    if _no_div_msg:
        st.info("配当金データが未取得のため、下段（配当金ベース）は表示できません。サイドバーの「yfinanceで一括取得」を実行してください。")
    else:
        col_d, col_e, col_f = st.columns(3)
        with col_d:
            st.plotly_chart(fig_div_stock,  use_container_width=True)
        with col_e:
            st.plotly_chart(fig_div_sector, use_container_width=True)
        with col_f:
            st.plotly_chart(fig_div_style,  use_container_width=True)


# ========== Tab6: 銘柄評価 ========== #
with tab6:
    st.subheader("銘柄ファンダメンタルズ評価")

    col_fetch, col_info = st.columns([2, 3])
    with col_fetch:
        st.markdown("""
        **取得データ（yfinance）**
        - ROE / ROA
        - 有利子負債比率 (D/E)
        - 流動比率
        - 配当性向
        - 売上・利益成長率
        - PBR / PER / 営業利益率
        """)
        if st.button("📥 ファンダメンタルズ一括取得", type="primary", use_container_width=True):
            tickers = df["ticker"].unique().tolist()
            bar = st.progress(0, text="取得中...")

            def _fund_progress(done, total):
                bar.progress(done / total, text=f"取得中... {done}/{total}")

            new_fund = fetch_all_fundamental_data(tickers, progress_callback=_fund_progress)
            bar.empty()
            save_fundamental_cache(new_fund)
            st.session_state.fund_cache = new_fund
            st.success(f"{len(new_fund)}銘柄のデータを取得しました")
            st.rerun()

    with col_info:
        st.markdown("""
        **評価軸（各100点満点）**

        | 評価軸 | 主な指標 |
        |--------|---------|
        | 安全性 | D/E比率・流動比率・ROA |
        | 成長性 | 売上成長率・利益成長率 |
        | 収益性 | ROE・営業利益率 |
        | 株主還元 | 配当利回り・配当性向 |
        | 割安性 | PBR・PER |
        """)

    with st.expander("📐 評価スコア計算式・計算例（クリックで展開）"):
        st.markdown("""
        ### 評価スコア計算式

        > ⚠️ **データ元**: yfinanceの`info`から取得。**成長率は直近四半期の前年同期比**であり、長期トレンドは反映されません。
        > （例：商社は商品価格変動で直近四半期が減収でも、長期成長企業の場合があります）

        ---
        #### 1. 安全性スコア（満点100点）

        | 指標 | 閾値 | 点数 | データなし |
        |------|------|------|-----------|
        | D/E比率 | <50 / <100 / <200 / それ以上 | 40 / 28 / 16 / 5 | 20点 |
        | 流動比率 | >2.0 / >1.5 / >1.0 / それ以下 | 30 / 22 / 14 / 5 | 15点 |
        | ROA(%) | >8% / >5% / >2% / それ以下 | 30 / 22 / 12 / 0 | 15点 |

        **計算例（伊藤忠商事 8001）**:
        D/E=120 → 16点、流動比率=1.4 → 14点、ROA=7% → 22点 → **合計52点**

        ---
        #### 2. 成長性スコア（満点100点）

        | 指標 | 閾値 | 点数 | データなし |
        |------|------|------|-----------|
        | 売上成長率(%) | >10 / >5 / >0 / >-5 / それ以下 | 50 / 38 / 25 / 12 / 0 | 25点 |
        | 利益成長率(%) | >10 / >5 / >0 / >-5 / それ以下 | 50 / 38 / 25 / 12 / 0 | 25点 |

        > **注意**: yfinanceで取得できる成長率は「直近四半期の前年同期比」です。伊藤忠商事のように長期的には増収でも、直近四半期が前年比-3%なら「売上成長率スコア12点」になります。

        **計算例**: 売上成長率=+3% → 25点、利益成長率=-3% → 12点 → **合計37点**

        ---
        #### 3. 収益性スコア（満点100点）

        | 指標 | 閾値 | 点数 | データなし |
        |------|------|------|-----------|
        | ROE(%) | >15 / >10 / >5 / それ以下 | 50 / 37 / 22 / 5 | 25点 |
        | 営業利益率(%) | >20 / >10 / >5 / それ以下 | 50 / 35 / 20 / 5 | 25点 |

        **計算例**: ROE=20% → 50点、営業利益率=8% → 20点 → **合計70点**

        ---
        #### 4. 株主還元スコア（満点100点）

        | 指標 | 閾値 | 点数 | データなし |
        |------|------|------|-----------|
        | 配当利回り(%) | 3〜5% / 5〜7% / 2〜3% / 7〜10% / >10% / それ以外 | 60 / 45 / 38 / 30 / 15 / 10 | 30点 |
        | 配当性向(%) | 30〜60% / 20〜30% / 60〜80% / >80% / それ以外 | 40 / 28 / 25 / 10 / 15 | 20点 |

        **計算例**: 配当利回り=3.5% → 60点、配当性向=40% → 40点 → **合計100点**

        ---
        #### 5. 割安性スコア（満点100点）

        | 指標 | 閾値 | 点数 | データなし |
        |------|------|------|-----------|
        | PBR | <1.0 / <1.5 / <2.0 / <3.0 / それ以上 | 50 / 35 / 22 / 10 / 0 | 25点 |
        | PER | <10 / <15 / <20 / <25 / それ以上 | 50 / 35 / 22 / 10 / 0 | 25点 |

        **計算例**: PBR=1.2 → 35点、PER=12 → 35点 → **合計70点**

        ---
        #### 総合スコア
        ```
        総合スコア = (安全性 + 成長性 + 収益性 + 株主還元 + 割安性) ÷ 5
        ```
        """)


    if not fund_cache.empty:
        # 現在のポートフォリオ銘柄のみを対象にスコア計算
        current_tickers = set(df["ticker"].unique())
        filtered_fund = fund_cache[fund_cache["ticker"].isin(current_tickers)]
        scores_df = calc_stock_scores(filtered_fund, div_cache)

        # 銘柄名・年間配当を結合
        name_map = dict(zip(df["ticker"], df["name"]))
        div_by_ticker = df.groupby("ticker")["annual_div_total"].sum().fillna(0).to_dict()
        scores_df["name"] = scores_df["ticker"].map(name_map).fillna("")
        scores_df["annual_div"] = scores_df["ticker"].map(div_by_ticker).fillna(0)

        if not scores_df.empty:
            st.divider()

            # ---- ポートフォリオ全体レーダーチャート ---- #
            st.subheader("ポートフォリオ全体スコア")
            weight_mode = st.radio(
                "集計方法",
                ["均等加重（単純平均）", "配当金構成比ベース（配当加重）"],
                horizontal=True,
            )

            score_cols = ["safety", "growth", "profitability", "shareholder_return", "value"]
            label_jp = ["安全性", "成長性", "収益性", "株主還元", "割安性"]

            if (
                weight_mode == "配当金構成比ベース（配当加重）"
                and scores_df["annual_div"].sum() > 0
            ):
                weights = scores_df["annual_div"] / scores_df["annual_div"].sum()
                portfolio_scores = (
                    scores_df[score_cols].multiply(weights, axis=0)
                ).sum().tolist()
                weight_label = "配当加重平均"
            else:
                portfolio_scores = scores_df[score_cols].mean().tolist()
                weight_label = "単純平均"

            total_portfolio = round(sum(portfolio_scores) / 5, 1)

            fig_radar_port = go.Figure()
            fig_radar_port.add_trace(go.Scatterpolar(
                r=portfolio_scores + [portfolio_scores[0]],
                theta=label_jp + [label_jp[0]],
                fill="toself",
                name=f"ポートフォリオ ({weight_label})",
                line_color="#3498db",
                fillcolor="rgba(52, 152, 219, 0.25)",
            ))
            fig_radar_port.update_layout(
                polar=dict(radialaxis=dict(visible=True, range=[0, 100])),
                height=400,
                margin=dict(t=30, b=30, l=30, r=30),
                showlegend=True,
            )

            col_radar, col_kpi = st.columns([2, 1])
            with col_radar:
                st.plotly_chart(fig_radar_port, use_container_width=True)
            with col_kpi:
                st.metric("総合スコア", f"{total_portfolio:.1f} / 100")
                for col, label in zip(score_cols, label_jp):
                    st.metric(label, f"{scores_df[col].mean():.1f}")

            st.divider()

            # ---- 個別銘柄レーダーチャート ---- #
            st.subheader("個別銘柄スコア")
            ticker_options = [
                f"{r['ticker']}  {r['name']}"
                for _, r in scores_df.sort_values("total", ascending=False).iterrows()
            ]
            selected = st.selectbox("銘柄を選択（総合スコア降順）", ticker_options)
            selected_ticker = selected.split()[0]
            sel_row = scores_df[scores_df["ticker"] == selected_ticker].iloc[0]
            sel_scores = [sel_row[c] for c in score_cols]

            fig_radar_stock = go.Figure()
            fig_radar_stock.add_trace(go.Scatterpolar(
                r=portfolio_scores + [portfolio_scores[0]],
                theta=label_jp + [label_jp[0]],
                fill="toself",
                name="ポートフォリオ平均",
                line_color="#95a5a6",
                fillcolor="rgba(149, 165, 166, 0.15)",
            ))
            fig_radar_stock.add_trace(go.Scatterpolar(
                r=sel_scores + [sel_scores[0]],
                theta=label_jp + [label_jp[0]],
                fill="toself",
                name=sel_row["name"] or selected_ticker,
                line_color="#e74c3c",
                fillcolor="rgba(231, 76, 60, 0.2)",
            ))
            fig_radar_stock.update_layout(
                polar=dict(radialaxis=dict(visible=True, range=[0, 100])),
                height=400,
                margin=dict(t=30, b=30, l=30, r=30),
                showlegend=True,
            )

            col_r2, col_detail = st.columns([2, 1])
            with col_r2:
                st.plotly_chart(fig_radar_stock, use_container_width=True)
            with col_detail:
                st.metric("総合スコア", f"{sel_row['total']:.1f} / 100")
                for col, label in zip(score_cols, label_jp):
                    st.metric(label, f"{sel_row[col]:.1f}")

            st.divider()

            # ---- 全銘柄スコアテーブル ---- #
            st.subheader("全銘柄スコア一覧")

            display_scores = scores_df[["ticker", "name", "total"] + score_cols].copy()
            display_scores = display_scores.sort_values("total", ascending=False)
            display_scores.columns = [
                "コード", "銘柄名", "総合",
                "安全性", "成長性", "収益性", "株主還元", "割安性",
            ]

            score_display_cols = ["総合", "安全性", "成長性", "収益性", "株主還元", "割安性"]
            styled_scores = display_scores.style.map(
                _color_score, subset=score_display_cols
            ).format(
                {col: "{:.1f}" for col in score_display_cols},
                na_rep="—",
            )

            st.dataframe(styled_scores, use_container_width=True, hide_index=True, height=500)
        else:
            st.warning("現在の保有銘柄に対応するファンダメンタルズデータがありません。再取得してください。")
    else:
        st.info("「📥 ファンダメンタルズ一括取得」ボタンを押してデータを取得してください。")

    # ===== 両学長 IRデータ評価セクション ===== #
    st.divider()
    st.subheader("📊 両学長 IRデータ評価（過去10年実績ベース）")

    # セッションのIRデータを取得し、キャッシュ済み銘柄を自動ロード
    ir_data_store: dict = st.session_state.ir_data
    current_tickers = df["ticker"].unique().tolist()
    not_yet_loaded = [t for t in current_tickers if t not in ir_data_store]
    if not_yet_loaded:
        newly_loaded = load_all_ir_caches(not_yet_loaded)
        st.session_state.ir_data.update(newly_loaded)
        ir_data_store = st.session_state.ir_data

    covered_ir_count = sum(
        1 for t in current_tickers
        if ir_data_store.get(t, {}).get("results")
    )

    col_ir_btn, col_ir_desc = st.columns([1, 2])
    with col_ir_btn:
        force_refresh_ir = st.checkbox(
            "強制再取得（キャッシュ無視）",
            value=False,
            key="ir_force_refresh",
        )
        if st.button(
            "📥 IRバンクデータ一括取得",
            type="primary",
            use_container_width=True,
            key="ir_fetch_btn",
        ):
            n = len(current_tickers)
            bar_ir = st.progress(0, text="IRバンクから取得中...")

            def _ir_progress(done, total):
                if total == 0:
                    return
                remaining_sec = (total - done) * 2
                bar_ir.progress(
                    done / total,
                    text=f"取得中... {done}/{total}（残り約{remaining_sec}秒）",
                )

            new_ir = fetch_all_ir_data(
                current_tickers,
                force_refresh=force_refresh_ir,
                progress_callback=_ir_progress,
            )
            bar_ir.empty()
            # セッション状態を更新（st.rerun()なしでそのまま継続）
            st.session_state.ir_data.update(new_ir)
            ir_data_store = st.session_state.ir_data
            covered_ir_count = sum(
                1 for t in current_tickers
                if ir_data_store.get(t, {}).get("results")
            )
            if covered_ir_count > 0:
                st.success(
                    f"✅ {covered_ir_count}/{n}銘柄のIRデータを取得しました"
                )
            else:
                st.error(
                    f"⚠️ {n}銘柄すべてのIRデータ取得に失敗しました。"
                    "下の「取得エラー診断」を確認してください。"
                )

            # エラーがあれば即時表示
            errors = get_scrape_errors()
            failed = [t for t in current_tickers if t in errors]
            success = [t for t in current_tickers if ir_data_store.get(t, {}).get("results")]
            if failed:
                with st.expander(
                    f"⚠️ 取得エラー詳細（{len(failed)}件）",
                    expanded=(covered_ir_count == 0),
                ):
                    st.markdown(f"**成功: {len(success)}件 / 失敗: {len(failed)}件**")
                    for t in failed[:20]:  # 最大20件表示
                        name = dict(zip(df["ticker"], df["name"])).get(t, "")
                        st.markdown(f"- `{t}` {name}: {errors[t]}")
                    if len(failed) > 20:
                        st.caption(f"...他 {len(failed)-20}件省略")

        st.caption(f"取得済み: {covered_ir_count} / {len(current_tickers)} 銘柄")
        if covered_ir_count < len(current_tickers):
            st.info(f"⏱️ 未取得 {len(current_tickers) - covered_ir_count}銘柄 × 約2秒")

    with col_ir_desc:
        st.markdown("""
        **データソース**: IRバンク（irbank.net）

        取得項目（過去10年分以上）:
        - EPS（一株当たり利益）推移
        - DPS（一株当たり配当）推移・連続増配年数
        - 配当性向（%）推移
        - 自己資本比率（%）推移
        - 売上高・利益推移（CAGR計算用）

        > yfinanceの「直近四半期比較」とは異なり、**長期トレンドで信頼性を評価**します。
        """)

    # ---- 取得状況の診断エクスパンダー ---- #
    errors_now = get_scrape_errors()
    if errors_now or covered_ir_count < len(current_tickers):
        with st.expander("🔍 取得エラー診断（クリックで展開）", expanded=False):
            st.markdown(
                f"**取得済み: {covered_ir_count} / {len(current_tickers)} 銘柄**"
            )
            failed_tickers = [
                t for t in current_tickers
                if t in errors_now or not ir_data_store.get(t, {}).get("results")
            ]
            if failed_tickers and errors_now:
                st.markdown("**未取得の原因（直近取得時）:**")
                for t in failed_tickers[:20]:
                    name = dict(zip(df["ticker"], df["name"])).get(t, "")
                    msg = errors_now.get(t, "キャッシュなし・未取得")
                    st.markdown(f"- `{t}` {name}: {msg}")
                if len(failed_tickers) > 20:
                    st.caption(f"...他 {len(failed_tickers)-20}件")
            elif failed_tickers:
                st.markdown(
                    "IRバンクデータ取得ボタンを押してください。"
                    f"（{len(failed_tickers)}銘柄が未取得）"
                )

    # ---- 計算式エクスパンダー ---- #
    with st.expander("📐 両学長スコア計算式（クリックで展開）", expanded=False):
        st.markdown("""
        > **評価軸**: 配当継続性 / 配当性向適正 / 財務健全性 / 業績成長性 / 配当利回り適正
        > / 営業利益率 / 営業CF / 現金等 の8軸（各0〜100点）の単純平均を総合スコアとします。
        > ※ 両学長の「優良高配当株を見分ける重要な8項目」に完全準拠。
        """)
        for formula_text in FORMULAS.values():
            st.markdown(formula_text)
            st.markdown("---")

    # ---- スコア表示 ---- #
    if covered_ir_count > 0:
        rg_scores_df = calc_all_ryogakucho_scores(ir_data_store, div_cache)
        name_map = dict(zip(df["ticker"], df["name"]))
        rg_scores_df["name"] = rg_scores_df["ticker"].map(name_map).fillna("")

        # 現在の保有銘柄のみに絞る
        rg_scores_df = rg_scores_df[
            rg_scores_df["ticker"].isin(set(current_tickers))
        ].copy()

        if not rg_scores_df.empty:
            rg_score_cols = [
                "dividend_continuity", "payout_ratio_score",
                "financial_health", "business_growth", "dividend_yield_score",
                "operating_margin_score", "operating_cf_score", "cash_score",
            ]
            rg_label_jp = [
                "配当継続性", "配当性向適正", "財務健全性", "業績成長性", "配当利回り",
                "営業利益率", "営業CF", "現金等",
            ]

            st.divider()

            # ---- ポートフォリオ平均レーダー ---- #
            st.subheader("ポートフォリオ平均スコア（両学長基準）")
            rg_port_scores = rg_scores_df[rg_score_cols].mean().tolist()
            rg_total_port = round(sum(rg_port_scores) / 8, 1)

            fig_rg_port = go.Figure()
            fig_rg_port.add_trace(go.Scatterpolar(
                r=rg_port_scores + [rg_port_scores[0]],
                theta=rg_label_jp + [rg_label_jp[0]],
                fill="toself",
                name="ポートフォリオ平均",
                line_color="#27ae60",
                fillcolor="rgba(39, 174, 96, 0.2)",
            ))
            fig_rg_port.update_layout(
                polar=dict(radialaxis=dict(visible=True, range=[0, 100])),
                height=400,
                margin=dict(t=30, b=30, l=30, r=30),
                showlegend=True,
            )

            col_rg_r, col_rg_kpi = st.columns([2, 1])
            with col_rg_r:
                st.plotly_chart(fig_rg_port, use_container_width=True)
            with col_rg_kpi:
                st.metric("両学長 総合スコア", f"{rg_total_port:.1f} / 100")
                for col_name, label in zip(rg_score_cols, rg_label_jp):
                    st.metric(label, f"{rg_scores_df[col_name].mean():.1f}")

            st.divider()

            # ---- 個別銘柄詳細 ---- #
            st.subheader("個別銘柄 詳細分析")
            rg_ticker_opts = [
                f"{r['ticker']}  {r['name']}"
                for _, r in rg_scores_df.sort_values("total", ascending=False).iterrows()
            ]
            sel_rg = st.selectbox(
                "銘柄を選択（総合スコア降順）",
                rg_ticker_opts,
                key="rg_stock_select",
            )
            sel_ticker_rg = sel_rg.split()[0]
            sel_row_rg = rg_scores_df[rg_scores_df["ticker"] == sel_ticker_rg].iloc[0]
            sel_scores_rg = [sel_row_rg[c] for c in rg_score_cols]

            # 個別銘柄レーダーチャート
            fig_rg_stock = go.Figure()
            fig_rg_stock.add_trace(go.Scatterpolar(
                r=rg_port_scores + [rg_port_scores[0]],
                theta=rg_label_jp + [rg_label_jp[0]],
                fill="toself",
                name="ポートフォリオ平均",
                line_color="#95a5a6",
                fillcolor="rgba(149, 165, 166, 0.15)",
            ))
            fig_rg_stock.add_trace(go.Scatterpolar(
                r=sel_scores_rg + [sel_scores_rg[0]],
                theta=rg_label_jp + [rg_label_jp[0]],
                fill="toself",
                name=sel_row_rg["name"] or sel_ticker_rg,
                line_color="#e67e22",
                fillcolor="rgba(230, 126, 34, 0.2)",
            ))
            fig_rg_stock.update_layout(
                polar=dict(radialaxis=dict(visible=True, range=[0, 100])),
                height=400,
                margin=dict(t=30, b=30, l=30, r=30),
                showlegend=True,
            )

            col_rg2, col_rg_detail = st.columns([2, 1])
            with col_rg2:
                st.plotly_chart(fig_rg_stock, use_container_width=True)
            with col_rg_detail:
                st.metric("両学長 総合スコア", f"{sel_row_rg['total']:.1f} / 100")

                # スコア内訳（計算根拠の詳細）
                sel_ir = ir_data_store.get(sel_ticker_rg, {})
                sel_bd = calc_ryogakucho_scores(
                    sel_ticker_rg, sel_ir, div_cache.get(sel_ticker_rg)
                )["breakdown"]

                bd_cont = sel_bd["dividend_continuity"]
                bd_pay  = sel_bd["payout_ratio"]
                bd_fin  = sel_bd["financial_health"]
                bd_grow = sel_bd["business_growth"]
                bd_yld  = sel_bd["dividend_yield"]
                bd_opm  = sel_bd["operating_margin"]
                bd_ocf  = sel_bd["operating_cf"]
                bd_cash = sel_bd["cash"]

                st.markdown("**スコア内訳**")
                st.markdown(f"""
- 配当継続性: **{sel_row_rg['dividend_continuity']:.0f}点**
  連続{bd_cont.get('consecutive_years', 0)}年維持・カット{bd_cont.get('cut_count', 0)}回

- 配当性向: **{sel_row_rg['payout_ratio_score']:.0f}点**
  過去5年平均 {bd_pay.get('avg_payout_pct', 'N/A')}%（{bd_pay.get('years_used', 0)}年分）

- 財務健全性: **{sel_row_rg['financial_health']:.0f}点**
  自己資本比率 {bd_fin.get('avg_equity_ratio', 'N/A')}%
  EPS黒字率 {bd_fin.get('eps_positive_rate_pct', 'N/A')}%

- 業績成長性: **{sel_row_rg['business_growth']:.0f}点**
  売上CAGR {bd_grow.get('revenue_cagr_pct', 'N/A')}%
  EPS CAGR {bd_grow.get('eps_cagr_pct', 'N/A')}%

- 配当利回り: **{sel_row_rg['dividend_yield_score']:.0f}点**
  現在 {bd_yld.get('div_yield_pct', 'N/A')}%

- 営業利益率: **{sel_row_rg['operating_margin_score']:.0f}点**
  直近3年平均 {bd_opm.get('avg_margin_pct', 'N/A')}%（{bd_opm.get('years_used', 0)}年分）

- 営業CF: **{sel_row_rg['operating_cf_score']:.0f}点**
  黒字率 {bd_ocf.get('positive_rate_pct', 'N/A')}%（{bd_ocf.get('years_used', 0)}年分）
  CAGR {bd_ocf.get('cagr_pct', 'N/A')}%

- 現金等: **{sel_row_rg['cash_score']:.0f}点**
  CAGR {bd_cash.get('cagr_pct', 'N/A')}%（{bd_cash.get('years_used', 0)}年分）
""")

            # ---- 歴史的推移チャート ---- #
            st.subheader(f"{sel_row_rg['name'] or sel_ticker_rg} の長期トレンド")
            sel_results = ir_data_store.get(sel_ticker_rg, {}).get("results", [])

            if sel_results:
                trend_df = pd.DataFrame(sel_results)
                trend_df = trend_df.iloc[::-1].reset_index(drop=True)  # 古→新の順に反転

                col_t1, col_t2 = st.columns(2)

                with col_t1:
                    # DPS（一株当たり配当）トレンド
                    if "dps" in trend_df.columns and trend_df["dps"].notna().any():
                        fig_dps = go.Figure()
                        fig_dps.add_trace(go.Bar(
                            x=trend_df["fiscal_year"],
                            y=trend_df["dps"],
                            name="DPS（円）",
                            marker_color="#27ae60",
                        ))
                        fig_dps.update_layout(
                            title="一株当たり配当（DPS）推移",
                            yaxis_title="円",
                            height=300,
                            margin=dict(t=40, b=60, l=50, r=20),
                        )
                        st.plotly_chart(fig_dps, use_container_width=True)

                    # 配当性向トレンド
                    if "payout_ratio" in trend_df.columns and trend_df["payout_ratio"].notna().any():
                        fig_pr = go.Figure()
                        fig_pr.add_trace(go.Scatter(
                            x=trend_df["fiscal_year"],
                            y=trend_df["payout_ratio"],
                            mode="lines+markers",
                            name="配当性向（%）",
                            line=dict(color="#e67e22", width=2),
                        ))
                        fig_pr.add_hline(
                            y=50, line_dash="dash", line_color="red",
                            annotation_text="50%（両学長上限目安）",
                            annotation_position="bottom right",
                        )
                        fig_pr.update_layout(
                            title="配当性向（%）推移",
                            yaxis_title="%",
                            height=300,
                            margin=dict(t=40, b=60, l=50, r=20),
                        )
                        st.plotly_chart(fig_pr, use_container_width=True)

                with col_t2:
                    # EPS（一株当たり利益）トレンド
                    if "eps" in trend_df.columns and trend_df["eps"].notna().any():
                        eps_colors = [
                            "#e74c3c" if (v is not None and v < 0) else "#3498db"
                            for v in trend_df["eps"]
                        ]
                        fig_eps = go.Figure()
                        fig_eps.add_trace(go.Bar(
                            x=trend_df["fiscal_year"],
                            y=trend_df["eps"],
                            name="EPS（円）",
                            marker_color=eps_colors,
                        ))
                        fig_eps.add_hline(y=0, line_color="black", line_width=1)
                        fig_eps.update_layout(
                            title="一株当たり利益（EPS）推移",
                            yaxis_title="円",
                            height=300,
                            margin=dict(t=40, b=60, l=50, r=20),
                        )
                        st.plotly_chart(fig_eps, use_container_width=True)

                    # 自己資本比率トレンド
                    if "equity_ratio" in trend_df.columns and trend_df["equity_ratio"].notna().any():
                        fig_eq = go.Figure()
                        fig_eq.add_trace(go.Scatter(
                            x=trend_df["fiscal_year"],
                            y=trend_df["equity_ratio"],
                            mode="lines+markers",
                            name="自己資本比率（%）",
                            line=dict(color="#8e44ad", width=2),
                        ))
                        fig_eq.add_hline(
                            y=40, line_dash="dash", line_color="orange",
                            annotation_text="40%（両学長最低目安）",
                            annotation_position="bottom right",
                        )
                        fig_eq.update_layout(
                            title="自己資本比率（%）推移",
                            yaxis_title="%",
                            height=300,
                            margin=dict(t=40, b=60, l=50, r=20),
                        )
                        st.plotly_chart(fig_eq, use_container_width=True)
            else:
                st.info("この銘柄のIRデータがありません。「IRバンクデータ一括取得」を実行してください。")

            st.divider()

            # ---- 全銘柄スコアテーブル ---- #
            st.subheader("全銘柄 両学長スコア一覧（IRデータベース）")

            disp_rg = rg_scores_df[["ticker", "name", "total"] + rg_score_cols].copy()
            disp_rg = disp_rg.sort_values("total", ascending=False)
            disp_rg.columns = [
                "コード", "銘柄名", "総合",
                "配当継続性", "配当性向", "財務健全性", "業績成長性", "配当利回り",
                "営業利益率", "営業CF", "現金等",
            ]

            rg_disp_score_cols = [
                "総合", "配当継続性", "配当性向", "財務健全性", "業績成長性", "配当利回り",
                "営業利益率", "営業CF", "現金等",
            ]
            styled_rg = disp_rg.style.map(
                _color_score, subset=rg_disp_score_cols
            ).format(
                {col: "{:.1f}" for col in rg_disp_score_cols},
                na_rep="—",
            )
            st.dataframe(styled_rg, use_container_width=True, hide_index=True, height=500)

    else:
        st.info(
            "「📥 IRバンクデータ一括取得」ボタンを押してデータを取得してください。"
            f"  ⏱️ {len(current_tickers)}銘柄 × 約2秒 = 約{len(current_tickers) * 2}秒"
        )


# ========== Tab7: 生データ ========== #
with tab7:
    st.subheader("アップロードCSV（デバッグ用）")
    if mask:
        st.warning("⚠️ 資産マスキングモードON中です。このタブには実際の金額データが含まれます。")
    st.dataframe(df, use_container_width=True, hide_index=True)
    st.caption(f"行数: {len(df)}  ｜  列数: {len(df.columns)}")
