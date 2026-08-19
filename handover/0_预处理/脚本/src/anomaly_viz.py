# -*- coding: utf-8 -*-
"""阶段二：异常检测可视化模块。

提供多变量异常检测结果的可视化：
1. Mahalanobis 时间线 + 归因堆叠柱状图
2. Isolation Forest vs Mahalanobis 对比散点图
3. 滑动窗口特征仪表板
4. 异常日历热力图
5. 归因总结柱状图
"""

from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
import pandas as pd

# ── 设置 CJK 字体 ──
plt.rcParams.update({
    "font.sans-serif": ["Microsoft YaHei", "SimHei", "WenQuanYi Micro Hei", "Noto Sans CJK SC", "DejaVu Sans"],
    "axes.unicode_minus": False,
})

from matplotlib.colors import LinearSegmentedColormap
from matplotlib.patches import Patch


def plot_mahalanobis_timeline(
    df_raw: pd.DataFrame,
    mahal_scores: pd.DataFrame,
    monitor_cols: list[str] | None = None,
    cond_col: str = "工况",
    output_path: str | Path | None = None,
) -> plt.Figure:
    """绘制 Mahalanobis 异常检测时间线。

    上子图：选定的监测参数折线（归一化堆叠）
    下子图：Mahalanobis 距离散点 + χ² 阈值虚线
    """
    if mahal_scores.empty:
        fig, ax = plt.subplots(figsize=(12, 3))
        ax.text(0.5, 0.5, "无 Mahalanobis 数据", ha="center", va="center")
        return fig

    if monitor_cols is None:
        monitor_cols = [c for c in df_raw.columns if c not in [cond_col, "时间戳"]]

    # 仅取 mahal_scores 覆盖的时间范围
    t_min = mahal_scores["时间戳"].min()
    t_max = mahal_scores["时间戳"].max()
    df_viz = df_raw.loc[t_min:t_max].copy()

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(16, 7), sharex=True,
                                    gridspec_kw={"height_ratios": [1.2, 1]})

    # ── 上子图：参数时间序列（归一化堆叠）──
    plot_params = [c for c in monitor_cols if c in df_viz.columns]
    # 选取有数值变动的参数
    plot_params = [
        c for c in plot_params
        if pd.api.types.is_numeric_dtype(df_viz[c]) and df_viz[c].nunique() > 1
    ]
    # 最多显示 12 个参数，避免图太拥挤
    plot_params = plot_params[:12]

    # 归一化并偏移堆叠
    offset = 0
    yticks = []
    yticklabels = []
    for param in plot_params:
        vals = df_viz[param].values
        valid = vals[~np.isnan(vals)]
        if len(valid) < 2:
            continue
        std = np.nanstd(vals)
        if std > 0:
            normalized = (vals - np.nanmean(vals)) / std
        else:
            normalized = np.zeros_like(vals, dtype=float)
        y_vals = normalized + offset * 5

        ax1.plot(df_viz.index, y_vals, linewidth=0.4, alpha=0.7)
        yticks.append(offset * 5)
        yticklabels.append(_short_name(param))
        offset += 1

    ax1.set_yticks(yticks)
    ax1.set_yticklabels(yticklabels, fontsize=7)
    ax1.set_ylabel("参数 (z-score 堆叠)", fontsize=9)
    ax1.set_title("Mahalanobis 异常检测 — 监测参数时间序列", fontsize=11)
    ax1.grid(True, alpha=0.2)

    # ── 下子图：Mahalanobis 距离 ──
    times = pd.to_datetime(mahal_scores["时间戳"])
    distances = mahal_scores["mahal_dist"].values
    thresholds = mahal_scores["threshold"].values
    is_anom = mahal_scores["is_anomaly"].values

    # 正常 vs 异常点用不同颜色
    ax2.scatter(times[~is_anom], distances[~is_anom],
                c="#42A5F5", s=8, alpha=0.4, edgecolors="none", label="正常")
    anom_mask = is_anom
    if anom_mask.any():
        ax2.scatter(times[anom_mask], distances[anom_mask],
                    c="#E53935", s=20, alpha=0.7, edgecolors="none", label="异常")

    # 阈值线（取第一个不 NaN 的阈值）
    valid_thresh = thresholds[~np.isnan(thresholds)]
    if len(valid_thresh) > 0:
        global_threshold = np.median(valid_thresh)
        ax2.axhline(global_threshold, color="#E53935", linestyle="--",
                    linewidth=1, alpha=0.7, label=f"χ²阈值 ≈ {global_threshold:.1f}")

    ax2.set_ylabel("Mahalanobis 距离", fontsize=10)
    ax2.set_xlabel("时间", fontsize=10)
    ax2.legend(fontsize=8, loc="upper right")
    ax2.grid(True, alpha=0.3)

    # 统计标注
    n_anom = int(anom_mask.sum())
    n_total = len(distances)
    ax2.text(0.02, 0.95,
             f"异常: {n_anom}/{n_total} ({n_anom / n_total * 100:.1f}%)",
             transform=ax2.transAxes, fontsize=9, verticalalignment="top",
             bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.8))

    ax2.set_xlim(t_min, t_max)
    fig.tight_layout()

    if output_path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(output_path, bbox_inches="tight", dpi=130)
    plt.close(fig)
    return fig


def plot_anomaly_feature_breakdown(
    mahal_scores: pd.DataFrame,
    feature_cols: list[str],
    top_n: int = 10,
    output_path: str | Path | None = None,
) -> plt.Figure:
    """绘制 Top-N 异常点的特征贡献堆叠柱状图。

    每个异常点一行，显示各特征对其 Mahalanobis 距离的贡献占比。
    """
    if mahal_scores.empty:
        fig, ax = plt.subplots(figsize=(8, 3))
        ax.text(0.5, 0.5, "无异常数据", ha="center", va="center")
        return fig

    anom = mahal_scores[mahal_scores["is_anomaly"]].copy()
    if anom.empty:
        fig, ax = plt.subplots(figsize=(8, 2))
        ax.text(0.5, 0.5, "无异常样本", ha="center", va="center")
        return fig

    # 取 Top-N 异常点（按距离排序）
    anom = anom.sort_values("mahal_dist", ascending=False).head(top_n)

    # 从 top_contributors 和 top_pcts 解析
    # 构建特征贡献矩阵
    all_features = set()
    contrib_data = []
    for _, row in anom.iterrows():
        contribs = row.get("top_contributors", "")
        pcts = row.get("top_pcts", "")
        if not contribs or not pcts:
            continue
        names = [n.strip() for n in contribs.split(";")]
        vals = [float(p.replace("%", "").strip()) for p in pcts.split(";")]
        feats = dict(zip(names, vals))
        all_features.update(feats.keys())
        contrib_data.append(feats)

    if not contrib_data:
        return plt.figure()

    feature_list = sorted(all_features)
    n_rows = len(contrib_data)

    # 构建矩阵
    matrix = np.zeros((n_rows, len(feature_list)))
    for i, feats in enumerate(contrib_data):
        for j, feat in enumerate(feature_list):
            matrix[i, j] = feats.get(feat, 0)

    # 堆叠柱状图
    fig, ax = plt.subplots(figsize=(12, max(5, n_rows * 0.35)))
    colors = plt.cm.tab20(np.linspace(0, 1, len(feature_list)))
    bottom = np.zeros(n_rows)
    bars = []
    for j in range(len(feature_list)):
        b = ax.barh(range(n_rows), matrix[:, j], left=bottom,
                    color=colors[j], edgecolor="white", linewidth=0.3)
        bottom += matrix[:, j]
        bars.append(b)

    # y 轴标签 = 时间戳
    time_labels = [str(t)[:16] for t in anom["时间戳"].values[:n_rows]]
    ax.set_yticks(range(n_rows))
    ax.set_yticklabels(time_labels, fontsize=7)
    ax.set_xlabel("贡献百分比 (%)", fontsize=9)
    ax.set_title(f"Top-{min(top_n, n_rows)} 异常点特征贡献分解", fontsize=11)
    ax.set_xlim(0, 105)
    ax.grid(True, alpha=0.2, axis="x")

    # 图例
    ax.legend([b[0] for b in bars], [_short_name(f) for f in feature_list],
              fontsize=6, loc="lower right", ncol=3)
    fig.tight_layout()

    if output_path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(output_path, bbox_inches="tight", dpi=130)
    plt.close(fig)
    return fig


def plot_if_comparison(
    if_scores: pd.DataFrame,
    mahal_scores: pd.DataFrame | None = None,
    output_path: str | Path | None = None,
) -> plt.Figure:
    """绘制 Isolation Forest vs Mahalanobis 对比散点图。

    当两种方法都有时，合并同一时间戳的分数做二维散点。
    只有 IF 则画 IF 分数时间线。
    """
    has_if = if_scores is not None and not if_scores.empty
    has_mahal = mahal_scores is not None and not mahal_scores.empty

    if not has_if:
        fig, ax = plt.subplots(figsize=(8, 3))
        ax.text(0.5, 0.5, "无 Isolation Forest 数据", ha="center", va="center")
        return fig

    if has_if and has_mahal:
        # 合并两个 DataFrame
        if_times = pd.to_datetime(if_scores["时间戳"])
        mahal_times = pd.to_datetime(mahal_scores["时间戳"])

        # 对齐：按时间戳合并
        if_df = if_scores[["时间戳", "if_score", "is_anomaly"]].copy()
        if_df.columns = ["时间戳", "if_score", "if_anomaly"]
        mahal_df = mahal_scores[["时间戳", "mahal_dist", "is_anomaly"]].copy()
        mahal_df.columns = ["时间戳", "mahal_dist", "mahal_anomaly"]

        merged = pd.merge(if_df, mahal_df, on="时间戳", how="inner")
        if len(merged) > 0:
            fig, ax = plt.subplots(figsize=(8, 6))

            # 四种情况着色
            both_normal = (~merged["if_anomaly"]) & (~merged["mahal_anomaly"])
            only_if = merged["if_anomaly"] & (~merged["mahal_anomaly"])
            only_mahal = (~merged["if_anomaly"]) & merged["mahal_anomaly"]
            both_anom = merged["if_anomaly"] & merged["mahal_anomaly"]

            for mask, color, label, s in [
                (both_normal, "#B0BEC5", "双方正常", 10),
                (only_if, "#FFA726", "仅 IF 异常", 20),
                (only_mahal, "#42A5F5", "仅 Mahalanobis 异常", 20),
                (both_anom, "#E53935", "双方异常", 30),
            ]:
                if mask.any():
                    ax.scatter(
                        merged.loc[mask, "if_score"],
                        merged.loc[mask, "mahal_dist"],
                        c=color, s=s, alpha=0.6, edgecolors="none", label=label,
                    )

            ax.set_xlabel("Isolation Forest Score（越大越正常）", fontsize=9)
            ax.set_ylabel("Mahalanobis Distance", fontsize=9)
            ax.set_title("Isolation Forest vs Mahalanobis 异常判定对比", fontsize=11)
            ax.legend(fontsize=8)
            ax.grid(True, alpha=0.3)
            ax.axhline(0, color="gray", linewidth=0.5, linestyle="--")

            n_both = int(both_anom.sum())
            n_if = int(only_if.sum())
            n_mahal = int(only_mahal.sum())
            ax.text(0.98, 0.02,
                    f"双方异常: {n_both}\n仅IF: {n_if}\n仅Mahal: {n_mahal}",
                    transform=ax.transAxes, fontsize=8, verticalalignment="bottom",
                    horizontalalignment="right",
                    bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.8))
        else:
            fig, ax = plt.subplots(figsize=(8, 3))
            ax.text(0.5, 0.5, "两种方法时间戳无交集", ha="center", va="center")
    else:
        # 只有 IF：画时间线
        fig, ax = plt.subplots(figsize=(14, 4))
        times = pd.to_datetime(if_scores["时间戳"])
        scores = if_scores["if_score"].values
        is_anom = if_scores["is_anomaly"].values

        ax.scatter(times[~is_anom], scores[~is_anom],
                   c="#42A5F5", s=5, alpha=0.3, label="正常")
        if is_anom.any():
            ax.scatter(times[is_anom], scores[is_anom],
                       c="#E53935", s=15, alpha=0.7, label="异常")
        ax.axhline(0, color="gray", linewidth=0.5, linestyle="--")
        ax.set_ylabel("IF Score", fontsize=10)
        ax.set_xlabel("时间", fontsize=10)
        ax.set_title("Isolation Forest 异常分数时间线", fontsize=11)
        ax.legend(fontsize=8)
        ax.grid(True, alpha=0.3)

    fig.tight_layout()
    if output_path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(output_path, bbox_inches="tight", dpi=130)
    plt.close(fig)
    return fig


def plot_interpretation_summary(
    merged_events: pd.DataFrame,
    top_n: int = 20,
    output_path: str | Path | None = None,
) -> plt.Figure:
    """绘制归因总结柱状图：Top-N 最常被引用的特征/归因。

    按 interpretation 字段中的特征提及频率排序。
    """
    if merged_events.empty:
        fig, ax = plt.subplots(figsize=(8, 3))
        ax.text(0.5, 0.5, "无事件数据", ha="center", va="center")
        return fig

    # 提取异常事件的归因文本中的特征提及
    anom_events = merged_events[merged_events.get("any_anomaly", False)].copy()
    if anom_events.empty:
        fig, ax = plt.subplots(figsize=(8, 2))
        ax.text(0.5, 0.5, "无异常事件", ha="center", va="center")
        return fig

    # 按方法分组统计异常数
    method_counts = anom_events["方法"].value_counts()

    # 按工况分组统计异常数
    cond_counts = anom_events["工况"].value_counts()

    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    # ── 左：方法分布 ──
    colors = {"Mahalanobis": "#42A5F5", "IsolationForest": "#FFA726",
              "残差": "#66BB6A", "单变量IQR+3σ": "#EF5350"}
    bar_colors = [colors.get(m, "#78909C") for m in method_counts.index]
    axes[0].barh(method_counts.index, method_counts.values, color=bar_colors, alpha=0.7)
    axes[0].set_xlabel("异常事件数", fontsize=10)
    axes[0].set_title("各方法异常事件数", fontsize=11)
    for i, v in enumerate(method_counts.values):
        axes[0].text(v + 0.5, i, str(v), va="center", fontsize=9)
    axes[0].grid(True, alpha=0.2, axis="x")

    # ── 右：工况分布（取 Top-N） ──
    cond_display = cond_counts.head(top_n)
    axes[1].barh(cond_display.index, cond_display.values, color="#78909C", alpha=0.7)
    axes[1].set_xlabel("异常事件数", fontsize=10)
    axes[1].set_title(f"各工况异常事件数（Top-{min(top_n, len(cond_display))}）", fontsize=11)
    for i, v in enumerate(cond_display.values):
        axes[1].text(v + 0.5, i, str(v), va="center", fontsize=8)
    axes[1].grid(True, alpha=0.2, axis="x")

    fig.suptitle("异常事件归因总结", fontsize=12, y=1.02)
    fig.tight_layout()

    if output_path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(output_path, bbox_inches="tight", dpi=130)
    plt.close(fig)
    return fig


def plot_window_feature_dashboard(
    window_df: pd.DataFrame,
    monitor_cols: list[str] | None = None,
    max_params: int = 8,
    output_path: str | Path | None = None,
) -> plt.Figure:
    """绘制滑动窗口特征仪表板。

    对 Top-N 参数（按 RMS 方差排序），画 RMS 和 斜率 的时间序列。
    """
    if window_df.empty:
        fig, ax = plt.subplots(figsize=(8, 3))
        ax.text(0.5, 0.5, "无窗口特征数据", ha="center", va="center")
        return fig

    # 找出可用的参数（从列名推断）
    rms_cols = [c for c in window_df.columns if c.endswith("_RMS")]
    if not rms_cols:
        rms_cols = [c for c in window_df.columns
                     if c not in ["时间戳", "工况"] and "_" in c]

    if not rms_cols:
        fig, ax = plt.subplots(figsize=(8, 3))
        ax.text(0.5, 0.5, "无 RMS 特征列", ha="center", va="center")
        return fig

    # 按 RMS 方差排序取 Top-N
    rms_var = {c: window_df[c].var() for c in rms_cols if c in window_df.columns}
    top_rms = sorted(rms_var, key=rms_var.get, reverse=True)[:max_params]

    n_cols = min(3, len(top_rms))
    n_rows = (len(top_rms) + n_cols - 1) // n_cols
    fig, axes = plt.subplots(n_rows, n_cols, figsize=(5 * n_cols, 3 * n_rows))
    axes = axes.flatten() if n_rows * n_cols > 1 else [axes]

    times = pd.to_datetime(window_df["时间戳"])
    for i, col in enumerate(top_rms):
        ax = axes[i]
        vals = window_df[col].values
        ax.plot(times, vals, linewidth=0.6, alpha=0.8)
        ax.set_title(_short_name(col), fontsize=8)
        ax.tick_params(axis="x", labelsize=6)
        ax.tick_params(axis="y", labelsize=7)
        ax.grid(True, alpha=0.2)

    # 隐藏剩余子图
    for j in range(len(top_rms), len(axes)):
        axes[j].set_visible(False)

    fig.suptitle("滑动窗口特征 — RMS 时间序列", fontsize=11, y=1.02)
    fig.tight_layout()

    if output_path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(output_path, bbox_inches="tight", dpi=130)
    plt.close(fig)
    return fig


def _short_name(name: str, max_len: int = 24) -> str:
    """截短参数名用于图表显示。"""
    for prefix in ["采煤机_", "三机_"]:
        if name.startswith(prefix):
            name = name[len(prefix):]
            break
    # 去后缀
    name = name.replace("_RMS", "").replace("_斜率", "")
    if len(name) > max_len:
        parts = name.split("_")
        if len(parts) > 3:
            name = "_".join(parts[-3:])
        else:
            name = name[:max_len]
    return name
