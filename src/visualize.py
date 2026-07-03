# -*- coding: utf-8 -*-
"""阶段一可视化：工况时间条、箱线图、相关性热力图。"""

from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # 无头模式
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
import pandas as pd

# ── 全局绘图风格 ──────────────────────────────────────────────
plt.rcParams.update({
    "figure.dpi": 120,
    "font.family": "sans-serif",
    "font.sans-serif": ["Microsoft YaHei", "SimHei", "WenQuanYi Micro Hei", "Noto Sans CJK SC", "DejaVu Sans"],
    "axes.unicode_minus": False,
    "figure.figsize": (12, 5),
})

COND_COLORS = {
    "停机": "#888888",
    "运行": "#4CAF50",
    "割煤": "#2196F3",
    "调架": "#FF9800",
    "空载牵引": "#9C27B0",
    "向机头": "#00BCD4",
    "向机尾": "#FF5722",
    "静止/方向未知": "#BDBDBD",
    "未知": "#EEEEEE",
    "空载运行": "#81C784",
    "带载运行": "#E53935",
}


def _sanitize_path(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _short_label(col: str) -> str:
    """从完整列名中提取可读的短标签。

    去掉设备前缀后取最后 3 段（至少 2 段），确保左右/不同部位可区分。
    例: "采煤机_截割部位_右滚筒_电机_电流" → "右滚筒_电机_电流"
         "采煤机_牵引部位_采煤机速度"       → "采煤机速度"
         "三机_转载机_电机_电流"             → "转载机_电机_电流"
    """
    for prefix in ["采煤机_", "三机_"]:
        if col.startswith(prefix):
            col = col[len(prefix):]
            break
    parts = col.split("_")
    if len(parts) <= 2:
        return col
    return "_".join(parts[-3:])


def plot_condition_timeline(
    df: pd.DataFrame,
    cond_col: str = "L1",
    title: str = "工况时间条",
    sample_every: int = 1,
    output_path: str | Path | None = None,
) -> plt.Figure:
    """绘制工况时间条（甘特图样式）。"""
    data = df[[cond_col]].copy()
    if sample_every > 1:
        data = data.iloc[::sample_every]
    data["color"] = data[cond_col].map(COND_COLORS).fillna("#EEEEEE")

    fig, ax = plt.subplots(figsize=(14, 1.5))
    # 逐段着色
    unique_vals = data[cond_col].unique()
    for val in unique_vals:
        mask = data[cond_col] == val
        color = COND_COLORS.get(val, "#EEEEEE")
        ax.fill_between(
            data.index, 0, 1,
            where=mask.values,
            color=color, label=val, step="post",
        )

    ax.set_ylim(0, 1)
    ax.set_yticks([])
    ax.set_title(title, fontsize=12)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
    ax.xaxis.set_major_locator(mdates.DayLocator(interval=3))
    fig.autofmt_xdate()
    ax.legend(loc="upper right", ncol=min(len(unique_vals), 6), fontsize=8)

    if output_path:
        fig.savefig(_sanitize_path(Path(output_path)), bbox_inches="tight")
    return fig


def plot_cond_boxplot(
    df: pd.DataFrame,
    cond_col: str,
    value_cols: list[str],
    title: str = "分工况参数分布",
    output_path: str | Path | None = None,
    max_cols: int = 6,
) -> plt.Figure:
    """按工况绘制多个监测参数的箱线图。"""
    plot_cols = value_cols[:max_cols]
    n = len(plot_cols)
    if n == 0:
        return plt.figure()

    fig, axes = plt.subplots(1, n, figsize=(4 * n, 4), sharey=False)
    if n == 1:
        axes = [axes]

    conditions = df[cond_col].dropna().unique()
    cond_order = sorted([c for c in conditions if c != "未知"], key=lambda x: (x == "停机", x))

    for ax, col in zip(axes, plot_cols):
        data_to_plot = [df.loc[df[cond_col] == c, col].dropna().values for c in cond_order]
        bp = ax.boxplot(data_to_plot, tick_labels=cond_order, patch_artist=True, showfliers=False)

        for patch, cond in zip(bp["boxes"], cond_order):
            patch.set_facecolor(COND_COLORS.get(cond, "#EEEEEE"))
            patch.set_alpha(0.6)

        ax.set_title(_short_label(col), fontsize=9)
        ax.tick_params(axis="x", rotation=30, labelsize=7)

    fig.suptitle(title, fontsize=12)
    fig.tight_layout()

    if output_path:
        fig.savefig(_sanitize_path(Path(output_path)), bbox_inches="tight")
    return fig


def plot_corr_heatmap(
    df: pd.DataFrame,
    value_cols: list[str],
    title: str = "监测参数相关性热力图",
    output_path: str | Path | None = None,
) -> plt.Figure:
    """绘制监测参数间的 Spearman 相关性热力图。"""
    corr = df[value_cols].corr(method="spearman")

    short_labels = [_short_label(c) for c in corr.columns]

    fig, ax = plt.subplots(figsize=(max(6, len(value_cols) * 0.5),
                                     max(5, len(value_cols) * 0.45)))
    im = ax.imshow(corr.values, cmap="RdBu_r", vmin=-1, vmax=1, aspect="auto")

    ax.set_xticks(range(len(value_cols)))
    ax.set_yticks(range(len(value_cols)))
    ax.set_xticklabels(short_labels, rotation=45, ha="right", fontsize=7)
    ax.set_yticklabels(short_labels, fontsize=7)
    fig.colorbar(im, ax=ax, shrink=0.8)
    ax.set_title(title, fontsize=12)

    if output_path:
        fig.savefig(_sanitize_path(Path(output_path)), bbox_inches="tight")
    return fig


def plot_cond_proportion(
    df: pd.DataFrame,
    cond_col: str = "L2",
    title: str = "工况时长占比",
    output_path: str | Path | None = None,
) -> plt.Figure:
    """绘制工况时长饼图。"""
    counts = df[cond_col].value_counts()

    colors = [COND_COLORS.get(c, "#EEEEEE") for c in counts.index]
    fig, ax = plt.subplots(figsize=(6, 5))
    wedges, texts, autotexts = ax.pie(
        counts.values, labels=counts.index, autopct="%1.1f%%",
        colors=colors, startangle=90,
        textprops={"fontsize": 9},
    )
    ax.set_title(title, fontsize=12)

    if output_path:
        fig.savefig(_sanitize_path(Path(output_path)), bbox_inches="tight")
    return fig


def generate_all_charts(
    cmj_wide: pd.DataFrame,
    zzj_wide: pd.DataFrame,
    output_dir: str | Path,
) -> list[Path]:
    """生成阶段一全套图表。"""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    charts: list[Path] = []

    # ── 采煤机 ──
    # L1 timeline
    l1_path = output_dir / "cmj_condition_L1_timeline.png"
    plot_condition_timeline(cmj_wide, "L1", "采煤机 L1 — 停机/运行", output_path=l1_path)
    charts.append(l1_path)

    # L2 timeline
    l2_path = output_dir / "cmj_condition_L2_timeline.png"
    plot_condition_timeline(cmj_wide, "L2", "采煤机 L2 — 工艺工况", sample_every=3, output_path=l2_path)
    charts.append(l2_path)

    # L2 proportion
    p2_path = output_dir / "cmj_condition_L2_pie.png"
    plot_cond_proportion(cmj_wide, "L2", "采煤机 L2 工况占比", output_path=p2_path)
    charts.append(p2_path)

    # Boxplot — 截割电流 vs L2
    cut_current_cols = [c for c in cmj_wide.columns if "滚筒" in c and "电流" in c]
    if cut_current_cols:
        bx_path = output_dir / "cmj_cut_current_by_L2.png"
        plot_cond_boxplot(cmj_wide, "L2", cut_current_cols,
                          "采煤机截割电流 — 分工况(L2)分布", output_path=bx_path)
        charts.append(bx_path)

    # Boxplot — 牵引电流 vs L2
    trac_current_cols = [c for c in cmj_wide.columns if "牵引" in c and "电流" in c]
    if trac_current_cols:
        bx2_path = output_dir / "cmj_trac_current_by_L2.png"
        plot_cond_boxplot(cmj_wide, "L2", trac_current_cols,
                          "采煤机牵引电流 — 分工况(L2)分布", output_path=bx2_path)
        charts.append(bx2_path)

    # Correlation heatmap — 关键监测参数
    key_monitor = [c for c in cmj_wide.columns
                   if any(kw in c for kw in ["电机_电流", "电机_温度", "采煤机速度", "俯仰角"])]
    if key_monitor:
        corr_path = output_dir / "cmj_corr_heatmap.png"
        plot_corr_heatmap(cmj_wide, key_monitor, "采煤机关键参数 Spearman 相关性", output_path=corr_path)
        charts.append(corr_path)

    # ── 转载机 ──
    zzj_cond_path = output_dir / "zzj_condition_timeline.png"
    plot_condition_timeline(zzj_wide, "工况", "转载机工况时间条", sample_every=5, output_path=zzj_cond_path)
    charts.append(zzj_cond_path)

    zzj_pie_path = output_dir / "zzj_condition_pie.png"
    plot_cond_proportion(zzj_wide, "工况", "转载机工况占比", output_path=zzj_pie_path)
    charts.append(zzj_pie_path)

    zzj_current_cols = [c for c in zzj_wide.columns if "电流" in c]
    if zzj_current_cols:
        bx3_path = output_dir / "zzj_current_by_cond.png"
        plot_cond_boxplot(zzj_wide, "工况", zzj_current_cols,
                          "转载机电流 — 分工况分布", output_path=bx3_path)
        charts.append(bx3_path)

    zzj_monitor = [c for c in zzj_wide.columns
                   if any(kw in c for kw in ["电流", "温度", "转速", "转矩"])]
    if len(zzj_monitor) >= 2:
        corr2_path = output_dir / "zzj_corr_heatmap.png"
        plot_corr_heatmap(zzj_wide, zzj_monitor, "转载机参数 Spearman 相关性", output_path=corr2_path)
        charts.append(corr2_path)

    return charts
