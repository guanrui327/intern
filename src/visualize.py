# -*- coding: utf-8 -*-
"""阶段一可视化：工况时间条、箱线图、相关性热力图（分部位版）。"""

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
    "割煤中": "#2196F3",
    "调架中": "#FF9800",
    "牵引中": "#00BCD4",
    "空载牵引": "#9C27B0",
    "待机": "#78909C",
    "空载运行": "#81C784",
    "带载运行": "#E53935",
    "未知": "#EEEEEE",
    # v3 新增 — 截割部 7 态拆分
    "待机-高位": "#B0BEC5",
    "割煤低位": "#42A5F5",
    "割煤中位": "#1E88E5",
    "割煤高位": "#1565C0",
}


def _sanitize_path(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _short_label(col: str) -> str:
    """从完整列名中提取可读的短标签。"""
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
    cond_col: str = "设备_工况",
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
    cond_col: str = "设备_工况",
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


def plot_lagged_correlation(
    df: pd.DataFrame,
    col_a: str,
    col_b: str,
    cond_col: str | None = None,
    max_lag: int = 30,
    title: str = "参数滞后互相关",
    output_path: str | Path | None = None,
) -> plt.Figure:
    """计算两个参数在 [-max_lag, +max_lag] 范围内的 Spearman 滞后互相关。

    可选的 *cond_col* 可指定工况列，按工况分组分别计算。
    """
    from scipy.stats import spearmanr

    if cond_col and cond_col in df.columns:
        conditions = df[cond_col].dropna().unique()
        cond_order = sorted(conditions, key=lambda x: (x == "停机", str(x)))
    else:
        cond_order = ["全部"]

    lags = list(range(-max_lag, max_lag + 1))

    fig, ax = plt.subplots(figsize=(10, 5))

    for cond in cond_order:
        if cond == "全部":
            subset = df[[col_a, col_b]].dropna()
        else:
            mask = df[cond_col] == cond
            subset = df.loc[mask, [col_a, col_b]].dropna()

        if len(subset) < max_lag * 4:
            continue

        # Spearman = Pearson on ranks：rank 一次，按 lag 位移对齐后求相关，
        # 替代逐 lag 调用 spearmanr（每次内部重复 rank）
        ranked = subset[[col_a, col_b]].rank()
        r_a = ranked[col_a]
        r_b = ranked[col_b]
        corrs = []
        for lag in lags:
            x = r_a.shift(-lag) if lag != 0 else r_a
            pair = pd.concat([x, r_b], axis=1).dropna()
            if len(pair) < 10:
                corrs.append(np.nan)
                continue
            corrs.append(pair[col_a].corr(pair[col_b]))

        color = COND_COLORS.get(cond, "#333") if cond != "全部" else "#1a237e"
        ax.plot(lags, corrs, marker="o", markersize=3, linewidth=1.2,
                label=cond, color=color, alpha=0.85)

    ax.axhline(0, color="gray", linewidth=0.5)
    ax.axvline(0, color="red", linestyle="--", linewidth=0.8, label="lag=0")
    ax.set_xlabel("滞后时间 (min)", fontsize=10)
    ax.set_ylabel("Spearman 相关系数", fontsize=10)
    ax.set_title(f"{title}\n{_short_label(col_a)} vs {_short_label(col_b)}", fontsize=11)
    ax.legend(fontsize=7, ncol=min(len(cond_order), 4))
    ax.grid(True, alpha=0.3)
    fig.tight_layout()

    if output_path:
        fig.savefig(_sanitize_path(Path(output_path)), bbox_inches="tight")
    return fig


def plot_cond_multi_feature_comparison(
    df: pd.DataFrame,
    cond_col: str,
    feature_cols: list[str],
    normalize: bool = True,
    title: str = "跨工况参数 Profile 对比",
    output_path: str | Path | None = None,
) -> plt.Figure:
    """按工况分组，展示多个参数的均值±标准差对比图（归一化）。"""
    conditions = df[cond_col].dropna().unique()
    cond_order = sorted(conditions, key=lambda x: (x == "停机", str(x)))

    stats_rows = []
    for cond in cond_order:
        sub = df[df[cond_col] == cond]
        row = {"工况": cond}
        for col in feature_cols:
            vals = sub[col].dropna()
            if len(vals) < 5:
                row[f"{col}_mean"] = np.nan
                row[f"{col}_std"] = np.nan
            else:
                row[f"{col}_mean"] = float(vals.mean())
                row[f"{col}_std"] = float(vals.std())
        stats_rows.append(row)

    stats = pd.DataFrame(stats_rows).set_index("工况")

    mean_cols = [c for c in stats.columns if c.endswith("_mean")]
    std_cols  = [c for c in stats.columns if c.endswith("_std")]

    if normalize and mean_cols:
        for mc in mean_cols:
            mu = stats[mc].mean()
            sigma = stats[mc].std()
            if sigma > 0:
                stats[mc] = (stats[mc] - mu) / sigma

    n_conds = len(cond_order)
    n_params = len(feature_cols)
    x = np.arange(n_params)
    bar_width = 0.8 / n_conds

    fig, ax = plt.subplots(figsize=(max(8, n_params * 1.5), 5))

    for i, cond in enumerate(cond_order):
        if cond not in stats.index:
            continue
        means = [stats.loc[cond, f"{c}_mean"] for c in feature_cols]
        stds  = [stats.loc[cond, f"{c}_std"] for c in feature_cols]
        offset = (i - n_conds / 2 + 0.5) * bar_width
        color = COND_COLORS.get(cond, "#888")
        bars = ax.bar(x + offset, means, bar_width * 0.9,
                       yerr=stds, capsize=2, label=cond,
                       color=color, alpha=0.75, error_kw={"linewidth": 0.8})

    ax.set_xticks(x)
    ax.set_xticklabels([_short_label(c) for c in feature_cols], rotation=25, fontsize=8)
    ax.set_ylabel("标准化值" if normalize else "均值", fontsize=10)
    ax.set_title(title, fontsize=11)
    ax.legend(fontsize=7, ncol=min(n_conds, 6))
    ax.axhline(0, color="gray", linewidth=0.4) if normalize else None
    ax.grid(True, alpha=0.2, axis="y")
    fig.tight_layout()

    if output_path:
        fig.savefig(_sanitize_path(Path(output_path)), bbox_inches="tight")
    return fig


def generate_all_charts(
    cmj_wide: pd.DataFrame,
    zzj_wide: pd.DataFrame,
    output_dir: str | Path,
) -> list[Path]:
    """生成阶段一全套图表（分部位版）。"""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    charts: list[Path] = []

    # ════════════════════════════════════════════════════════════
    # 采煤机 — 设备级
    # ════════════════════════════════════════════════════════════
    # 设备级工况时间线
    p_dev_tl = output_dir / "cmj_device_condition_timeline.png"
    plot_condition_timeline(cmj_wide, "设备_工况",
                            "采煤机设备级工况时间线", output_path=p_dev_tl)
    charts.append(p_dev_tl)

    # 设备级工况占比
    p_dev_pie = output_dir / "cmj_device_condition_pie.png"
    plot_cond_proportion(cmj_wide, "设备_工况",
                         "采煤机设备级工况占比", output_path=p_dev_pie)
    charts.append(p_dev_pie)

    # ════════════════════════════════════════════════════════════
    # 采煤机 — 4 个部位时间线
    # ════════════════════════════════════════════════════════════
    part_cols = ["截割部_工况", "牵引部_工况", "油泵_工况", "破碎机_工况"]
    part_names = {"截割部_工况": "截割部", "牵引部_工况": "牵引部",
                  "油泵_工况": "油泵", "破碎机_工况": "破碎机"}
    for col in part_cols:
        if col not in cmj_wide.columns:
            continue
        safe_name = part_names.get(col, col)
        fn = output_dir / f"cmj_{safe_name}_timeline.png"
        plot_condition_timeline(cmj_wide, col,
                                f"采煤机 {safe_name} 工况时间线",
                                sample_every=3, output_path=fn)
        charts.append(fn)

    # ════════════════════════════════════════════════════════════
    # 采煤机 — 分部位箱线图（各部位自己的电流）
    # ════════════════════════════════════════════════════════════
    # 截割部 → 截割电流
    cut_current_cols = [c for c in cmj_wide.columns if "滚筒" in c and "电流" in c]
    if cut_current_cols and "截割部_工况" in cmj_wide.columns:
        bx1 = output_dir / "cmj_截割部_cut_current_boxplot.png"
        plot_cond_boxplot(cmj_wide, "截割部_工况", cut_current_cols,
                          "截割部 — 分工况截割电流分布", output_path=bx1)
        charts.append(bx1)

    # 牵引部 → 牵引电流
    trac_current_cols = [c for c in cmj_wide.columns if "牵引" in c and "电流" in c]
    if trac_current_cols and "牵引部_工况" in cmj_wide.columns:
        bx2 = output_dir / "cmj_牵引部_traction_current_boxplot.png"
        plot_cond_boxplot(cmj_wide, "牵引部_工况", trac_current_cols,
                          "牵引部 — 分工况牵引电流分布", output_path=bx2)
        charts.append(bx2)

    # 油泵 → 油泵电流
    pump_current_cols = [c for c in cmj_wide.columns if "油泵" in c and "电流" in c]
    if pump_current_cols and "油泵_工况" in cmj_wide.columns:
        bx3 = output_dir / "cmj_油泵_pump_current_boxplot.png"
        plot_cond_boxplot(cmj_wide, "油泵_工况", pump_current_cols,
                          "油泵 — 分工况油泵电流分布", output_path=bx3)
        charts.append(bx3)

    # 破碎机 → 破碎机电流
    crusher_current_cols = [c for c in cmj_wide.columns if "破碎机" in c and "电流" in c]
    if crusher_current_cols and "破碎机_工况" in cmj_wide.columns:
        bx4 = output_dir / "cmj_破碎机_crusher_current_boxplot.png"
        plot_cond_boxplot(cmj_wide, "破碎机_工况", crusher_current_cols,
                          "破碎机 — 分工况破碎机电流分布", output_path=bx4)
        charts.append(bx4)

    # ════════════════════════════════════════════════════════════
    # 相关性热力图
    # ════════════════════════════════════════════════════════════
    key_monitor = [c for c in cmj_wide.columns
                   if any(kw in c for kw in ["电机_电流", "电机_温度", "采煤机速度", "俯仰角"])]
    if key_monitor:
        corr_path = output_dir / "cmj_corr_heatmap.png"
        plot_corr_heatmap(cmj_wide, key_monitor, "采煤机关键参数 Spearman 相关性", output_path=corr_path)
        charts.append(corr_path)

    # ════════════════════════════════════════════════════════════
    # 滞后互相关（按设备_工况分组）
    # ════════════════════════════════════════════════════════════
    lag_pairs = []
    cut_current = [c for c in cmj_wide.columns if "滚筒" in c and "电流" in c]
    cut_temp = [c for c in cmj_wide.columns if "滚筒" in c and "温度" in c]
    if cut_current and cut_temp:
        lag_pairs.append((cut_current[0], cut_temp[0], "截割电流 vs 截割温度"))
    trac_current = [c for c in cmj_wide.columns if "牵引" in c and "电流" in c]
    speed_col = [c for c in cmj_wide.columns if "采煤机速度" in c]
    if trac_current and speed_col:
        lag_pairs.append((trac_current[0], speed_col[0], "牵引电流 vs 牵引速度"))
    pitch_col = [c for c in cmj_wide.columns if "俯仰角" in c]
    pos_col = [c for c in cmj_wide.columns if "位置架号" in c]
    if pitch_col and pos_col:
        lag_pairs.append((pitch_col[0], pos_col[0], "俯仰角 vs 位置架号"))

    for col_a, col_b, pair_title in lag_pairs:
        suffix = col_a.split("_")[-1] + "_vs_" + col_b.split("_")[-1]
        lag_path = output_dir / f"cmj_lagged_corr_{suffix}.png"
        plot_lagged_correlation(cmj_wide, col_a, col_b,
                                 cond_col="设备_工况", max_lag=30,
                                 title=f"采煤机 {pair_title}",
                                 output_path=lag_path)
        charts.append(lag_path)

    # ── 按部位滞后互相关 ──
    part_lag_config = []
    if cut_current and cut_temp:
        part_lag_config.append(
            ("截割部_工况", cut_current[0], cut_temp[0], "截割电流 vs 截割温度"))
    if trac_current and speed_col:
        part_lag_config.append(
            ("牵引部_工况", trac_current[0], speed_col[0], "牵引电流 vs 牵引速度"))
    pump_current = [c for c in cmj_wide.columns if "油泵" in c and "电流" in c]
    pump_pressure = [c for c in cmj_wide.columns if "油泵" in c and "油压" in c]
    if pump_current and pump_pressure:
        part_lag_config.append(
            ("油泵_工况", pump_current[0], pump_pressure[0], "油泵电流 vs 油压"))
    crusher_current_cols = [c for c in cmj_wide.columns if "破碎机" in c and "电流" in c]
    crusher_temp_cols = [c for c in cmj_wide.columns if "破碎机" in c and "温度" in c]
    if crusher_current_cols and crusher_temp_cols:
        part_lag_config.append(
            ("破碎机_工况", crusher_current_cols[0], crusher_temp_cols[0],
             "破碎机电流 vs 破碎机温度"))

    for cond_col, col_a, col_b, pair_title in part_lag_config:
        if cond_col not in cmj_wide.columns:
            continue
        fname = f"cmj_lagged_corr_{cond_col.split('_')[0]}.png"
        lag_path = output_dir / fname
        plot_lagged_correlation(cmj_wide, col_a, col_b,
                                 cond_col=cond_col, max_lag=30,
                                 title=f"采煤机 — {pair_title}",
                                 output_path=lag_path)
        charts.append(lag_path)

    # ════════════════════════════════════════════════════════════
    # 跨工况参数 Profile（按设备_工况）
    # ════════════════════════════════════════════════════════════
    profile_cols = [c for c in cmj_wide.columns
                    if any(kw in c for kw in ["滚筒_电机_电流", "滚筒_电机_温度",
                                               "采煤机速度", "摇臂_角度",
                                               "俯仰角", "位置架号"])]
    if profile_cols and "设备_工况" in cmj_wide.columns:
        prof_path = output_dir / "cmj_all_params_by_device_profile.png"
        plot_cond_multi_feature_comparison(cmj_wide, "设备_工况", profile_cols,
                                            "采煤机跨工况参数 Profile 对比",
                                            output_path=prof_path)
        charts.append(prof_path)

    # ════════════════════════════════════════════════════════════
    # 转载机
    # ════════════════════════════════════════════════════════════
    zzj_cond_path = output_dir / "zzj_condition_timeline.png"
    plot_condition_timeline(zzj_wide, "工况", "转载机工况时间线", sample_every=5,
                             output_path=zzj_cond_path)
    charts.append(zzj_cond_path)

    zzj_pie_path = output_dir / "zzj_condition_pie.png"
    plot_cond_proportion(zzj_wide, "工况", "转载机工况占比", output_path=zzj_pie_path)
    charts.append(zzj_pie_path)

    zzj_current_cols = [c for c in zzj_wide.columns if "电流" in c]
    if zzj_current_cols:
        bx5 = output_dir / "zzj_current_by_cond.png"
        plot_cond_boxplot(zzj_wide, "工况", zzj_current_cols,
                          "转载机电流 — 分工况分布", output_path=bx5)
        charts.append(bx5)

    zzj_monitor = [c for c in zzj_wide.columns
                   if any(kw in c for kw in ["电流", "温度", "转速", "转矩"])]
    if len(zzj_monitor) >= 2:
        corr2_path = output_dir / "zzj_corr_heatmap.png"
        plot_corr_heatmap(zzj_wide, zzj_monitor, "转载机参数 Spearman 相关性", output_path=corr2_path)
        charts.append(corr2_path)

    # ── 转载机滞后互相关 ──
    zzj_current = [c for c in zzj_wide.columns if "电流" in c]
    zzj_speed = [c for c in zzj_wide.columns if "转速" in c]
    if zzj_current and zzj_speed and "工况" in zzj_wide.columns:
        zzj_lag_path = output_dir / "zzj_lagged_corr_电流_vs_转速.png"
        plot_lagged_correlation(zzj_wide, zzj_current[0], zzj_speed[0],
                                 cond_col="工况", max_lag=30,
                                 title="转载机 — 电流 vs 转速",
                                 output_path=zzj_lag_path)
        charts.append(zzj_lag_path)

    return charts
