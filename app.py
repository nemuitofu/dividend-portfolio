"""
高配当株ポートフォリオマネージャー
両学長の高配当株投資理論に基づくSBI証券CSV分析ツール
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go

from utils import (
    load_position_csv,
    load_balance_csv,
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

st.set_page_config(
    page_title="高配当株ポートフォリオマネージャー",
    page_icon="📈",
    layout="wide",
)

# ------------------------------------------------------------------ #
# セッション初期化
# ------------------------------------------------------------------ #

if "df" not in st.session_state:
    st.session_state.df = None
if "balance" not in st.session_state:
    st.session_state.balance = {}
if "div_cache" not in st.session_state:
    st.session_state.div_cache = load_dividend_cache()
if "sector_master" not in st.session_state:
    st.session_state.sector_master = load_sector_master()
if "fund_cache" not in st.session_state:
    st.session_state.fund_cache = load_fundamental_cache()

# ------------------------------------------------------------------ #
# サイドバー
# ------------------------------------------------------------------ #

with st.sidebar:
    st.title("📂 データ読み込み")

    pos_file = st.file_uploader(
        "保有株CSV (stockposition_*.csv)",
        type="csv",
        key="pos_uploader",
    )
    bal_file = st.file_uploader(
        "資産残高CSV (assetbalance_*.csv)　任意",
        type="csv",
        key="bal_uploader",
    )

    if pos_file:
        try:
            st.session_state.df = load_position_csv(pos_file)
            st.success(f"{len(st.session_state.df)}銘柄 読み込み完了")
        except Exception as e:
            st.error(f"CSV読み込みエラー: {e}")

    if bal_file:
        try:
            st.session_state.balance = load_balance_csv(bal_file)
        except Exception as e:
            st.error(f"残高CSV読み込みエラー: {e}")

    st.divider()
    st.subheader("配当データ管理")

    if st.button("🔄 yfinanceで一括取得", use_container_width=True):
        if st.session_state.df is not None:
            tickers = st.session_state.df["ticker"].unique().tolist()
            names = dict(zip(st.session_state.df["ticker"], st.session_state.df["name"]))
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

if st.session_state.df is None:
    st.info("👈 サイドバーからSBI証券の保有株CSVをアップロードしてください。")
    st.markdown("""
    ### 使い方
    1. SBI証券 → 口座管理 → 保有証券 → CSVダウンロード（`stockposition_*.csv`）
    2. サイドバーからアップロード
    3. 必要に応じて「yfinanceで一括取得」で配当データを取得
    """)
    st.stop()

# データ加工
df: pd.DataFrame = st.session_state.df.copy()
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

# ========== Tab1: サマリー ========== #
with tab1:
    col1, col2, col3, col4 = st.columns(4)
    col1.metric(
        "総時価評価額",
        f"¥{summary['total_market_value']:,.0f}",
    )
    col2.metric(
        "総含み損益",
        fmt_yen(summary["total_unrealized_pl"]),
        delta=fmt_pct(summary["total_unrealized_pl_pct"]),
        delta_color="normal",
    )
    col3.metric(
        "年間配当金見込み",
        f"¥{annual_div:,.0f}",
        delta=f"月平均 ¥{annual_div/12:,.0f}",
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
            "時価評価額": f"¥{vals['market_value']:,.0f}",
            "含み損益": fmt_yen(vals["unrealized_pl"]),
            "含み損益率": fmt_pct(vals["unrealized_pl_pct"]),
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
        fig_acct = go.Figure(go.Pie(
            labels=list(summary["by_account"].keys()),
            values=[v["market_value"] for v in summary["by_account"].values()],
            hole=0.4,
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
    ]

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

    styled = disp.style.map(_color_yield, subset=["配当利回り(%)"]).map(
        _color_pl, subset=["含み損益(円)", "含み損益率(%)"]
    ).format(
        {
            "現在値(円)":      "{:,.1f}",
            "平均取得(円)":    "{:,.2f}",
            "時価評価額(円)":  "{:,.0f}",
            "含み損益(円)":    "{:+,.0f}",
            "含み損益率(%)":   "{:+.2f}%",
            "配当利回り(%)":   lambda v: f"{v:.2f}%" if not pd.isna(v) else "—",
            "年間配当金(円)":  lambda v: f"¥{v:,.0f}" if not pd.isna(v) else "—",
        },
        na_rep="—",
    )

    st.dataframe(styled, use_container_width=True, hide_index=True, height=600)

    st.caption(
        f"合計: {len(disp)}銘柄 ｜ "
        f"時価合計: ¥{df['market_value'].sum():,.0f} ｜ "
        f"含み損益合計: {fmt_yen(df['unrealized_pl'].sum())} ｜ "
        f"年間配当合計: ¥{annual_div:,.0f}"
    )


# ========== Tab3: セクター分散 ========== #
with tab3:
    col_chart, col_check = st.columns([3, 2])

    with col_chart:
        fig_sector = go.Figure(go.Pie(
            labels=sector_df["sector"],
            values=sector_df["market_value"],
            text=sector_df["ratio_pct"].apply(lambda v: f"{v:.1f}%"),
            hovertemplate="<b>%{label}</b><br>¥%{value:,.0f}<br>%{percent}<extra></extra>",
            hole=0.3,
        ))
        fig_sector.update_layout(
            title="セクター別 時価評価額",
            height=450,
            margin=dict(t=50, b=0, l=0, r=0),
        )
        st.plotly_chart(fig_sector, use_container_width=True)

        st.dataframe(
            sector_df.rename(columns={
                "sector": "セクター",
                "market_value": "時価評価額(円)",
                "ratio_pct": "比率(%)",
            }).style.format({
                "時価評価額(円)": "{:,.0f}",
                "比率(%)": "{:.1f}%",
            }).bar(subset=["比率(%)"], color="#4a90d9"),
            use_container_width=True,
            hide_index=True,
        )

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

    # --- 企業別（銘柄別）構成比 ---
    stock_pie_df = (
        df.groupby(["ticker", "name"])["market_value"]
        .sum()
        .reset_index()
        .sort_values("market_value", ascending=False)
    )
    # 上位15銘柄 + それ以外をまとめる
    TOP_N = 15
    if len(stock_pie_df) > TOP_N:
        top = stock_pie_df.iloc[:TOP_N].copy()
        others_mv = stock_pie_df.iloc[TOP_N:]["market_value"].sum()
        others_count = len(stock_pie_df) - TOP_N
        others_row = pd.DataFrame([{
            "ticker": "—",
            "name": f"その他 ({others_count}銘柄)",
            "market_value": others_mv,
        }])
        stock_pie_df = pd.concat([top, others_row], ignore_index=True)

    fig_stock = go.Figure(go.Pie(
        labels=stock_pie_df["name"],
        values=stock_pie_df["market_value"],
        hovertemplate="<b>%{label}</b><br>¥%{value:,.0f}<br>%{percent}<extra></extra>",
        hole=0.35,
    ))
    fig_stock.update_layout(
        title="企業別（銘柄別）構成比",
        height=420,
        margin=dict(t=50, b=0, l=0, r=0),
        legend=dict(font=dict(size=11)),
    )

    # --- セクター別構成比 ---
    fig_sector2 = go.Figure(go.Pie(
        labels=sector_df["sector"],
        values=sector_df["market_value"],
        hovertemplate="<b>%{label}</b><br>¥%{value:,.0f}<br>%{percent}<extra></extra>",
        hole=0.35,
    ))
    fig_sector2.update_layout(
        title="業種別（セクター別）構成比",
        height=420,
        margin=dict(t=50, b=0, l=0, r=0),
    )

    # --- 投資スタイル別構成比 ---
    df["投資スタイル"] = df["sector"].apply(classify_investment_style)
    style_df = (
        df.groupby("投資スタイル")["market_value"]
        .sum()
        .reset_index()
        .sort_values("market_value", ascending=False)
    )
    _STYLE_COLORS = {
        "ディフェンシブ": "#2ecc71",
        "景気敏感":       "#e74c3c",
        "金融":           "#3498db",
        "REIT・ETF":     "#9b59b6",
        "その他":         "#95a5a6",
    }
    fig_style = go.Figure(go.Pie(
        labels=style_df["投資スタイル"],
        values=style_df["market_value"],
        marker_colors=[_STYLE_COLORS.get(s, "#95a5a6") for s in style_df["投資スタイル"]],
        hovertemplate="<b>%{label}</b><br>¥%{value:,.0f}<br>%{percent}<extra></extra>",
        hole=0.35,
    ))
    fig_style.update_layout(
        title="投資スタイル別構成比（景気敏感 / ディフェンシブ）",
        height=420,
        margin=dict(t=50, b=0, l=0, r=0),
    )

    # --- 通貨・国別構成比 ---
    def _classify_country(ticker: str, sector: str) -> str:
        code = int(ticker) if ticker.isdigit() else 0
        if sector == "REIT・ETF":
            # 国内REIT・ETF帯（1300-1499）
            if 1300 <= code <= 1499:
                return "国内REIT・ETF (JPY)"
            # 外国株式ETF帯（2500-2800）
            if 2500 <= code <= 2800:
                return "外国株式ETF (USD他)"
        return "国内株式 (JPY)"

    df["通貨・国"] = df.apply(lambda r: _classify_country(r["ticker"], r["sector"]), axis=1)
    country_df = (
        df.groupby("通貨・国")["market_value"]
        .sum()
        .reset_index()
        .sort_values("market_value", ascending=False)
    )
    fig_country = go.Figure(go.Pie(
        labels=country_df["通貨・国"],
        values=country_df["market_value"],
        hovertemplate="<b>%{label}</b><br>¥%{value:,.0f}<br>%{percent}<extra></extra>",
        hole=0.35,
    ))
    fig_country.update_layout(
        title="通貨・国別構成比",
        height=420,
        margin=dict(t=50, b=0, l=0, r=0),
    )

    # 2×2 レイアウト
    col_a, col_b = st.columns(2)
    with col_a:
        st.plotly_chart(fig_stock, use_container_width=True)
    with col_b:
        st.plotly_chart(fig_sector2, use_container_width=True)

    col_c, col_d = st.columns(2)
    with col_c:
        st.plotly_chart(fig_style, use_container_width=True)
    with col_d:
        st.plotly_chart(fig_country, use_container_width=True)

    st.caption(
        "※ 通貨・国別分類は銘柄コード帯による自動推定です。"
        "海外ETFの判定は主要コード帯のみ対応しており、誤差が含まれる場合があります。"
    )


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

            def _color_score(val):
                if pd.isna(val):
                    return ""
                if val >= 70:
                    return "background-color: #d5f5e3; color: #1e8449"
                if val >= 50:
                    return "background-color: #fef9e7; color: #7d6608"
                return "background-color: #fadbd8; color: #922b21"

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


# ========== Tab7: 生データ ========== #
with tab7:
    st.subheader("アップロードCSV（デバッグ用）")
    st.dataframe(df, use_container_width=True, hide_index=True)
    st.caption(f"行数: {len(df)}  ｜  列数: {len(df.columns)}")
