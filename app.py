"""
高配当株ポートフォリオマネージャー
両学長の高配当株投資理論に基づくSBI証券CSV分析ツール
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px

from utils import (
    load_position_csv,
    load_balance_csv,
    load_dividend_cache,
    save_dividend_cache,
    load_sector_master,
    calc_portfolio_summary,
    calc_with_dividend,
    calc_sector_allocation,
    calc_annual_dividend_total,
    check_ryogakucho_criteria,
    fetch_all_dividend_yields,
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

df = calc_with_dividend(df, div_cache)
summary = calc_portfolio_summary(df)
sector_df = calc_sector_allocation(df, sector_master)
annual_div = calc_annual_dividend_total(df)
portfolio_yield = (annual_div / summary["total_market_value"] * 100) if summary["total_market_value"] > 0 else 0.0

# ------------------------------------------------------------------ #
# タブ
# ------------------------------------------------------------------ #

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📊 サマリー",
    "📋 銘柄一覧",
    "🥧 セクター分散",
    "💰 配当データ管理",
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
    # 表示用DataFrame整形
    display_df = df.copy()
    from utils import get_sector
    display_df["セクター"] = display_df["ticker"].apply(
        lambda t: get_sector(t, sector_master)
    )

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

    # スタイリング
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

    # 統計行
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
        # セクター円グラフ
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

        # セクターテーブル
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

    # 現在のキャッシュをdfと結合して表示
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


# ========== Tab5: 生データ ========== #
with tab5:
    st.subheader("アップロードCSV（デバッグ用）")
    st.dataframe(df, use_container_width=True, hide_index=True)
    st.caption(f"行数: {len(df)}  ｜  列数: {len(df.columns)}")
