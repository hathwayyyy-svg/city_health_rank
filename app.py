# app.py
# -*- coding: utf-8 -*-


import pandas as pd
import numpy as np
from pathlib import Path
import streamlit as st
import plotly.graph_objects as go
from datetime import datetime
from urllib.parse import quote
import streamlit.components.v1 as components  # 如需内嵌 FineBI，可用到

# ===================== 配置区 =====================

# 原始经营数据
INPUT_FILE = Path("./地市经营情况数据.xlsx")
INPUT_SHEET = "地市总体情况-总体情况"

# 表头列名（如果你的 Excel 列名不同，在这里改）
COL_CITY = "地市"
COL_INCOME_RATE = "收入完成率"
COL_TIME_PROGRESS = "时间进度"

COL_COVER_RATE = "覆盖客户率"
COL_COVER_TIME_PROGRESS = "覆盖率时间进度"

COL_TURN_X9 = "x9周转"
COL_RENO15_SO = "reno15 so"
COL_RENO15_ST = "reno15 st"

# 新的维度5：合约机占比
COL_CONTRACT_RATIO = "合约机占比"   # ⚠️ 确保与 Excel 列名一致

# 等级颜色
LEVEL_COLORS = {
    "A": "#2ecc71",  # 绿
    "B": "#3498db",  # 蓝
    "C": "#f1c40f",  # 黄
    "D": "#e74c3c",  # 红
    "NA": "#95a5a6"  # 灰
}

# FineBI 报表链接配置（你给的链接）
FINEBI_BASE_URL = "http://172.16.73.12:1024/webroot/decision/link/uwHs"
FINEBI_CITY_PARAM = "city"  # FineBI URL 参数名（需要在 FineBI 里配置对应参数）


# ============== 小工具函数 ==============

def rank_to_score(series: pd.Series, ascending: bool) -> pd.Series:
    """将一个数值序列按排序转换为 0~20 分"""
    scores = pd.Series(index=series.index, dtype=float)
    valid = series.notna()
    if valid.sum() == 0:
        return scores
    ranks = series[valid].rank(method="min", ascending=ascending)
    N = len(ranks)
    scores[valid] = (N - ranks).astype(float)
    return scores


# ============== 打分逻辑 ==============

def compute_scores() -> pd.DataFrame:
    """读取原始数据并计算五维度等级和得分"""

    if not INPUT_FILE.exists():
        st.error(f"找不到输入文件：{INPUT_FILE.resolve()}")
        st.stop()

    df = pd.read_excel(INPUT_FILE, sheet_name=INPUT_SHEET)

    required_cols = [
        COL_CITY,
        COL_INCOME_RATE, COL_TIME_PROGRESS,
        COL_COVER_RATE, COL_COVER_TIME_PROGRESS,
        COL_TURN_X9, COL_RENO15_SO, COL_RENO15_ST,
        COL_CONTRACT_RATIO
    ]
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        st.error(f"缺少列：{missing}")
        st.stop()

    prov_avg_income = df[COL_INCOME_RATE].mean()
    prov_avg_cover = df[COL_COVER_RATE].mean()

    # ----- 维度1 收入完成 -----
    dim1_level = []
    for _, row in df.iterrows():
        rate = row[COL_INCOME_RATE]
        tprog = row[COL_TIME_PROGRESS]
        if pd.isna(rate) or pd.isna(tprog):
            dim1_level.append("NA")
        elif tprog > 0:
            dim1_level.append("A")
        elif tprog < 0 and rate >= prov_avg_income:
            dim1_level.append("B")
        else:
            dim1_level.append("C")
    df["收入完成_等级"] = dim1_level

    tmp = df[COL_TIME_PROGRESS].copy()
    tmp[tmp.isna()] = tmp.max()
    bottom3_idx_dim1 = tmp.sort_values(ascending=True).index[:3]
    df.loc[bottom3_idx_dim1, "收入完成_等级"] = "D"

    df["收入完成_得分"] = rank_to_score(df[COL_TIME_PROGRESS], ascending=False)

    # ----- 维度2 覆盖率 -----
    dim2_level = []
    for _, row in df.iterrows():
        cov_tprog = row[COL_COVER_TIME_PROGRESS]
        cover_rate = row[COL_COVER_RATE]
        if pd.isna(cov_tprog) or pd.isna(cover_rate):
            dim2_level.append("NA")
        elif cov_tprog > 0:
            dim2_level.append("A")
        elif cov_tprog < 0 and cover_rate >= prov_avg_cover:
            dim2_level.append("B")
        else:
            dim2_level.append("C")
    df["覆盖率_等级"] = dim2_level

    cover_tmp = df[COL_COVER_RATE].copy()
    cover_tmp[cover_tmp.isna()] = cover_tmp.max()
    bottom3_cover_idx = cover_tmp.sort_values(ascending=True).index[:3]
    df.loc[bottom3_cover_idx, "覆盖率_等级"] = "D"

    df["覆盖率_得分"] = rank_to_score(df[COL_COVER_RATE], ascending=False)

    # ----- 维度3 X9 周转（越低越好） -----
    avg_x9 = df[COL_TURN_X9].mean()
    x9_sorted_asc = df[COL_TURN_X9].sort_values(ascending=True)
    x9_sorted_desc = df[COL_TURN_X9].sort_values(ascending=False)
    best3_x9_idx = x9_sorted_asc.index[:3]
    worst3_x9_idx = x9_sorted_desc.index[:3]

    dim3_level = []
    for idx, row in df.iterrows():
        v = row[COL_TURN_X9]
        if pd.isna(v):
            dim3_level.append("NA")
        elif idx in best3_x9_idx:
            dim3_level.append("A")
        elif idx in worst3_x9_idx:
            dim3_level.append("D")
        elif v < avg_x9:
            dim3_level.append("B")
        else:
            dim3_level.append("C")
    df["X9周转_等级"] = dim3_level
    df["X9周转_得分"] = rank_to_score(df[COL_TURN_X9], ascending=True)

    # ----- 维度4 Reno15 差值（st - so，越大越好） -----
    df["Reno15_diff"] = df[COL_RENO15_ST] - df[COL_RENO15_SO]
    diff = df["Reno15_diff"]
    diff_sorted_desc = diff.sort_values(ascending=False)
    diff_sorted_asc = diff.sort_values(ascending=True)
    top3_diff_idx = diff_sorted_desc.index[:3]
    bottom3_diff_idx = diff_sorted_asc.index[:3]

    dim4_level = []
    for idx, row in df.iterrows():
        d = row["Reno15_diff"]
        if pd.isna(d):
            dim4_level.append("NA")
        elif d >= 0 and idx in top3_diff_idx:
            dim4_level.append("A")
        elif d >= 0:
            dim4_level.append("B")
        elif d < 0 and idx in bottom3_diff_idx:
            dim4_level.append("D")
        else:
            dim4_level.append("C")
    df["Reno15_等级"] = dim4_level
    df["Reno15_得分"] = rank_to_score(df["Reno15_diff"], ascending=False)

    # ----- 维度5 合约机占比（越高越好） -----
    contract_series = df[COL_CONTRACT_RATIO]
    avg_contract = contract_series.mean()

    contract_sorted_desc = contract_series.sort_values(ascending=False)
    contract_sorted_asc = contract_series.sort_values(ascending=True)
    top3_contract_idx = contract_sorted_desc.index[:3]
    bottom3_contract_idx = contract_sorted_asc.index[:3]

    dim5_level = []
    for idx, row in df.iterrows():
        v = row[COL_CONTRACT_RATIO]
        if pd.isna(v):
            dim5_level.append("NA")
        elif idx in top3_contract_idx:
            dim5_level.append("A")
        elif idx in bottom3_contract_idx:
            dim5_level.append("D")
        elif v >= avg_contract:
            dim5_level.append("B")
        else:
            dim5_level.append("C")
    df["合约机_等级"] = dim5_level
    df["合约机_得分"] = rank_to_score(df[COL_CONTRACT_RATIO], ascending=False)

    # ----- 输出结构 + 综合得分 -----
    out_cols = [
        COL_CITY,
        "收入完成_等级", "收入完成_得分",
        "覆盖率_等级", "覆盖率_得分",
        "X9周转_等级", "X9周转_得分",
        "Reno15_等级", "Reno15_得分",
        "合约机_等级", "合约机_得分",
    ]
    result = df[out_cols].copy()

    score_cols = [
        "收入完成_得分", "覆盖率_得分",
        "X9周转_得分", "Reno15_得分", "合约机_得分"
    ]
    result["综合得分"] = result[score_cols].sum(axis=1)

    def total_level(x):
        if pd.isna(x):
            return "NA"
        if x >= 85:
            return "A"
        elif x >= 70:
            return "B"
        elif x >= 50:
            return "C"
        else:
            return "D"

    result["综合等级"] = result["综合得分"].apply(total_level)
    return result


def make_level_badge(level: str, text_prefix="综合等级"):
    color = LEVEL_COLORS.get(level, "#95a5a6")
    return f"""
    <span style="
        background-color:{color};
        color:white;
        padding:2px 8px;
        border-radius:12px;
        font-size:12px;
        margin-left:6px;">
        {text_prefix} {level}
    </span>
    """


def make_city_profile(row: pd.Series) -> str:
    """文字画像"""
    city = row[COL_CITY]
    total = row["综合得分"]
    level = row["综合等级"]

    parts = []
    parts.append(f"【综合评价】{city} 综合得分为 {total:.1f} 分，整体健康等级为 {level}。")

    dims = [
        ("收入完成", "收入完成_等级", "收入完成_得分"),
        ("覆盖率", "覆盖率_等级", "覆盖率_得分"),
        ("X9周转", "X9周转_等级", "X9周转_得分"),
        ("Reno15", "Reno15_等级", "Reno15_得分"),
        ("合约机", "合约机_等级", "合约机_得分"),
    ]

    detail_txt = []
    for name, lvl_col, sc_col in dims:
        lvl = row.get(lvl_col, "NA")
        sc = row.get(sc_col, None)
        if pd.isna(sc):
            detail_txt.append(f"{name}：数据缺失")
        else:
            detail_txt.append(f"{name}：{sc:.1f} 分（{lvl} 级）")
    parts.append("【五维度得分】" + "；".join(detail_txt) + "。")

    scores_for_rank = pd.Series(
        {name: row[sc_col] for name, _, sc_col in dims}
    )
    scores_sorted = scores_for_rank.sort_values(ascending=False)
    top3 = scores_sorted.head(3)
    bottom3 = scores_sorted.tail(3)

    adv_txt = "、".join([f"{k}（{v:.1f}分）" for k, v in top3.items()])
    weak_txt = "、".join([f"{k}（{v:.1f}分）" for k, v in bottom3.items()])

    parts.append(f"【优势维度】重点优势在：{adv_txt}。")
    parts.append(f"【薄弱维度】相对薄弱在：{weak_txt}。")

    return "\n\n".join(parts)


def make_radar_figure(df: pd.DataFrame, cities):
    """多地市雷达图"""
    dimensions = ["收入完成", "覆盖率", "X9周转", "Reno15", "合约机"]
    score_cols = [
        "收入完成_得分", "覆盖率_得分",
        "X9周转_得分", "Reno15_得分", "合约机_得分"
    ]

    fig = go.Figure()
    for city in cities:
        row = df[df[COL_CITY] == city]
        if row.empty:
            continue
        values = row[score_cols].iloc[0].tolist()
        fig.add_trace(go.Scatterpolar(
            r=values + [values[0]],
            theta=dimensions + [dimensions[0]],
            name=city,
            fill='toself',
            opacity=0.35
        ))

    fig.update_layout(
        polar=dict(
            radialaxis=dict(
                range=[0, 20],
                showticklabels=True,
                ticks=""
            )
        ),
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=-0.25),
        margin=dict(l=40, r=40, t=40, b=60),
        template="plotly_white",
    )
    return fig


def make_bar_figure(row: pd.Series):
    """单地市五维度柱状图"""
    dims = ["收入完成", "覆盖率", "X9周转", "Reno15", "合约机"]
    score_cols = [
        "收入完成_得分", "覆盖率_得分",
        "X9周转_得分", "Reno15_得分", "合约机_得分"
    ]
    scores = [row[c] for c in score_cols]

    fig = go.Figure(go.Bar(
        x=dims,
        y=scores,
        text=[f"{s:.1f}" for s in scores],
        textposition="outside"
    ))
    fig.update_yaxes(range=[0, 20])
    fig.update_layout(
        margin=dict(l=10, r=10, t=10, b=10),
        template="plotly_white",
        height=260
    )
    return fig


# ===================== 主页面 =====================

def main():
    st.set_page_config(
        page_title="地市五维度健康画像看板",
        layout="wide"
    )

    # 一点 CSS 美化：去掉菜单/footer，调整背景
    st.markdown("""
        <style>
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        .block-container {
            padding-top: 1.2rem;
            padding-bottom: 1.2rem;
            padding-left: 2rem;
            padding-right: 2rem;
        }
        </style>
    """, unsafe_allow_html=True)

    st.markdown("## 📊 地市五维度健康画像看板")
    st.caption("基于收入完成、覆盖率、X9周转、Reno15、合约机占比五个维度的地市经营健康度评估。")
    st.markdown("---")

    df_scores = compute_scores()

    # ---------- 从 URL 读取 city 参数（支持 FineBI → Streamlit 跳转，使用新 API） ----------
    query_params = st.query_params
    city_from_url = query_params.get("city", [None])[0]

    city_options = df_scores[COL_CITY].tolist()
    if city_from_url in city_options:
        default_city_index = city_options.index(city_from_url)
    else:
        default_city_index = 0 if city_options else 0

    # ---------- 顶部总览卡片 ----------
    level_counts = df_scores["综合等级"].value_counts()
    avg_score = df_scores["综合得分"].mean()

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("平均综合得分", f"{avg_score:.1f}")
    c2.metric("A级地市数", int(level_counts.get("A", 0)))
    c3.metric("B级地市数", int(level_counts.get("B", 0)))
    c4.metric("C级地市数", int(level_counts.get("C", 0)))
    c5.metric("D级地市数", int(level_counts.get("D", 0)))

    st.markdown("")

    # ---------- 侧边栏选择 ----------
    with st.sidebar:
        st.header("筛选条件")

        main_city = st.selectbox(
            "主查看地市",
            options=city_options,
            index=default_city_index
        )
        multi_cities = st.multiselect(
            "对比地市（可多选）",
            options=city_options,
            default=[main_city]
        )
        if not multi_cities:
            multi_cities = [main_city]

    # ---------- Tabs ----------
    tab1, tab2 = st.tabs(["📍 单地市画像", "📈 多地市对比"])

    # ====== Tab1：单地市画像 ======
    with tab1:
        col_left, col_right = st.columns([2, 1])

        row = df_scores[df_scores[COL_CITY] == main_city].iloc[0]

        with col_left:
            st.subheader(f"{main_city} - 五维度表现")
            radar_fig = make_radar_figure(df_scores, [main_city])
            st.plotly_chart(radar_fig, use_container_width=True, key="radar_single")

            st.subheader("维度得分柱状图")
            bar_fig = make_bar_figure(row)
            st.plotly_chart(bar_fig, use_container_width=True, key="bar_single")

        with col_right:
            st.subheader("健康度概览")

            badge_html = make_level_badge(row["综合等级"])
            st.markdown(
                f"<h4 style='margin-bottom:0;'>综合得分：{row['综合得分']:.1f}{badge_html}</h4>",
                unsafe_allow_html=True
            )
            st.markdown("&nbsp;", unsafe_allow_html=True)

            # Streamlit → FineBI：当前地市跳转到 FineBI 明细
            city_encoded = quote(main_city)  # URL 编码避免中文问题
            finebi_url = f"{FINEBI_BASE_URL}?{FINEBI_CITY_PARAM}={city_encoded}"

            st.link_button("在 FineBI 中查看该地市明细 ➜", finebi_url)

            # 如需内嵌 FineBI，可解开下面注释（前提是 FineBI 允许 iframe）
            # st.markdown("###### 内嵌 FineBI 明细（当前地市）")
            # components.iframe(finebi_url, height=600, scrolling=True)

            st.markdown("---")

            profile_text = make_city_profile(row)
            st.write(profile_text.replace("\n", "  \n"))

    # ====== Tab2：多地市对比 ======
    with tab2:
        st.subheader("多地市五维度雷达对比")
        radar_fig_multi = make_radar_figure(df_scores, multi_cities)
        st.plotly_chart(radar_fig_multi, use_container_width=True, key="radar_multi")

    # ---------- 底部表格 ----------
    st.markdown("---")
    st.subheader("全省地市综合得分排名")

    rank_df = df_scores[[
        COL_CITY, "综合得分",
        "收入完成_得分", "覆盖率_得分",
        "X9周转_得分", "Reno15_得分", "合约机_得分",
        "综合等级"
    ]].sort_values("综合得分", ascending=False)

    st.dataframe(rank_df, use_container_width=True)


if __name__ == "__main__":
    main()
