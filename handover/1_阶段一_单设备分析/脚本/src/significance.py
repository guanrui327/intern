# -*- coding: utf-8 -*-
"""Kruskal-Wallis 显著性检验：判断"哪些工况显著影响哪些监测参数"。

为每个部位（截割部/牵引部/油泵/破碎机）计算：
  - Kruskal-Wallis H 统计量 & p 值
  - FDR (Benjamini-Hochberg) 校正
  - epsilon² 效应量
"""

from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
import numpy as np
import pandas as pd
from scipy.stats import kruskal

# 中文字体（与 visualize/anomaly_viz/segment_stats 保持一致，防止热力图中文变方框）
plt.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["Microsoft YaHei", "SimHei", "WenQuanYi Micro Hei", "Noto Sans CJK SC", "DejaVu Sans"],
    "axes.unicode_minus": False,
})


# ── Kruskal-Wallis + 效应量 ────────────────────────────────


def _epsilon_squared(h: float, n: int, k: int) -> float:
    """计算 epsilon² 效应量 = H / (n - 1)。

    Tomczak & Tomczak (2014) 标准版本:
      ε² = H / (N - 1)
    其中 N = 全部观测数，H = Kruskal-Wallis 统计量。

    解释阈值 (Cohen, 1988):
      small  ≥ 0.01, medium ≥ 0.06, large ≥ 0.14
    """
    if n <= 1:
        return 0.0
    return h / (n - 1) if n > 1 else 0.0


def _effect_size_label(eps: float) -> str:
    """给 epsilon² 分级：小 ≥0.01, 中 ≥0.06, 大 ≥0.14 (Cohen 准则变体)。"""
    if eps >= 0.14:
        return "大"
    elif eps >= 0.06:
        return "中"
    elif eps >= 0.01:
        return "小"
    return "无"


def kruskal_wallis_test(
    df: pd.DataFrame,
    cond_col: str,
    value_cols: list[str],
    min_samples: int = 10,
) -> pd.DataFrame:
    """对每个监测参数，按工况分组做 Kruskal-Wallis 检验。

    Parameters
    ----------
    df : 宽表（含工况列）
    cond_col : 工况列名（如 "截割部_工况"）
    value_cols : 待检验的监测参数列
    min_samples : 每组最少样本数，低于此值跳过

    Returns
    -------
    pd.DataFrame
        [参数列, H统计量, p值, FDR校正p值, epsilon², 效应量等级, 有效组数]
    """
    results = []
    cond_groups = [g.dropna() for _, g in df.groupby(cond_col)
                   if g[cond_col].notna().any()]
    # 排除"未知"组；dropna 可能把某工况组删空（该工况下 monitor 全 NaN），需跳过空组
    cond_groups = [g for g in cond_groups
                   if len(g) > 0 and g[cond_col].iloc[0] != "未知"]

    for col in value_cols:
        # 提取各工况下的该参数值
        groups = []
        valid_group_names = []
        for g in cond_groups:
            vals = g[col].dropna()
            if len(vals) >= min_samples:
                groups.append(vals.values)
                valid_group_names.append(g[cond_col].iloc[0])

        if len(groups) < 2:
            results.append({
                "参数列": col,
                "H统计量": np.nan,
                "p值": np.nan,
                "FDR校正p值": np.nan,
                "epsilon²": np.nan,
                "效应量等级": "—",
                "有效组数": len(groups),
            })
            continue

        h_stat, p_val = kruskal(*groups)
        n_total = sum(len(g) for g in groups)
        k = len(groups)
        eps = _epsilon_squared(h_stat, n_total, k)

        results.append({
            "参数列": col,
            "H统计量": round(h_stat, 4),
            "p值": p_val,
            "FDR校正p值": p_val,  # placeholder
            "epsilon²": round(eps, 4),
            "效应量等级": _effect_size_label(eps),
            "有效组数": k,
        })

    result_df = pd.DataFrame(results)

    # FDR (Benjamini-Hochberg) 校正
    if not result_df.empty and result_df["p值"].notna().any():
        p_vals = result_df["p值"].fillna(1.0).values
        n_tests = len(p_vals)
        sorted_idx = np.argsort(p_vals)
        sorted_p = p_vals[sorted_idx]
        rank = np.arange(1, n_tests + 1)
        q = sorted_p * n_tests / rank
        bh_corrected = np.minimum.accumulate(q[::-1])[::-1][np.argsort(sorted_idx)]
        result_df["FDR校正p值"] = np.round(bh_corrected, 6)

    return result_df


# ── 热力图可视化 ────────────────────────────────────────────


def plot_kruskal_heatmap(
    results: pd.DataFrame,
    title: str = "Kruskal-Wallis 检验 — 工况×参数 中位数热力图",
    p_threshold: float = 0.05,
    condition_medians: pd.DataFrame | None = None,
    output_path: str | Path | None = None,
) -> plt.Figure:
    """Kruskal-Wallis 效应量 + 工况-参数中位数 2D 热力图。

    当提供 condition_medians 时，绘制二维热力图：
    - 行 = 监测参数，按 epsilon² 降序排列
    - 列 = 工况状态
    - 颜色 = 行归一化 z-score（高亮各参数在不同工况下的偏移）
    - 标注：显著参数格点标记 *

    不提供 condition_medians 时回退为旧版一维条形图。
    """
    if results.empty:
        fig, ax = plt.subplots(figsize=(6, 2))
        ax.text(0.5, 0.5, "无有效数据", ha="center", va="center")
        return fig

    if condition_medians is not None and not condition_medians.empty:
        return _plot_2d_median_heatmap(
            results, condition_medians, title, p_threshold, output_path,
        )

    # ── Fallback: 旧版一维条形图（无 medians 时） ──
    significant = results["FDR校正p值"].fillna(1) < p_threshold
    params = [_short_label(c) for c in results["参数列"]]
    eps_vals = results["epsilon²"].fillna(0)

    fig, ax = plt.subplots(figsize=(max(8, len(params) * 0.4), 4))
    colors = ["#E53935" if sig else "#BDBDBD" for sig in significant]
    bars = ax.barh(range(len(params)), eps_vals, color=colors, height=0.6)

    for i, (sig, eps) in enumerate(zip(significant, eps_vals)):
        if sig:
            ax.text(eps + 0.005, i, "*", va="center", fontsize=12, color="#E53935")

    ax.set_yticks(range(len(params)))
    ax.set_yticklabels(params, fontsize=8)
    ax.set_xlabel("epsilon² 效应量", fontsize=10)
    ax.set_title(title, fontsize=11)
    ax.axvline(0.01, color="gray", linestyle=":", linewidth=0.5, label="小阈值")
    ax.axvline(0.06, color="gray", linestyle="--", linewidth=0.5, label="中阈值")
    ax.axvline(0.14, color="gray", linestyle="-", linewidth=0.5, label="大阈值")
    ax.legend(fontsize=7)
    fig.tight_layout()

    if output_path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(output_path, bbox_inches="tight", dpi=130)
    return fig


def _plot_2d_median_heatmap(
    results: pd.DataFrame,
    condition_medians: pd.DataFrame,
    title: str,
    p_threshold: float = 0.05,
    output_path: str | Path | None = None,
) -> plt.Figure:
    """2D 中位数热力图（参数 × 工况）。"""
    # ── 行归一化（z-score per parameter） ──
    mean_vals = condition_medians.mean(axis=1)
    std_vals = condition_medians.std(axis=1)
    # 零方差参数保持 0
    zscore = condition_medians.sub(mean_vals, axis=0).div(std_vals.replace(0, 1), axis=0)

    # ── 按 epsilon² 降序排列参数 ──
    eps_map = results.set_index("参数列")["epsilon²"].fillna(0)
    # 只保留 condition_medians 中出现的行列
    common_params = [p for p in eps_map.index if p in zscore.index]
    zscore = zscore.loc[common_params]
    eps_map = eps_map.loc[common_params]
    # 降序排列
    sort_order = eps_map.sort_values(ascending=False).index
    zscore = zscore.loc[sort_order]

    # ── 显著参数集合 ──
    sig_set = set(
        results.loc[results["FDR校正p值"].fillna(1) < p_threshold, "参数列"]
    )

    n_params, n_conds = zscore.shape
    fig_w = max(6, n_conds * 1.5 + 2.0)   # +2 留给 epsilon² 注释柱 + colorbar
    fig_h = max(4, n_params * 0.38)
    fig, (ax_heat, ax_eps) = plt.subplots(
        1, 2, figsize=(fig_w, fig_h),
        gridspec_kw={"width_ratios": [n_conds * 1.5, 0.6], "wspace": 0.15},
    )

    # ── 主热力图 ──
    vmax = max(abs(zscore.values.min()), abs(zscore.values.max()), 0.5)
    cmap = plt.cm.RdBu_r
    cmap.set_bad("lightgray")

    im = ax_heat.imshow(zscore.values, aspect="auto", cmap=cmap,
                        vmin=-vmax, vmax=vmax, interpolation="nearest")

    # 标注数值 + 显著性星号
    for i in range(n_params):
        for j in range(n_conds):
            val = zscore.values[i, j]
            if np.isnan(val):
                continue
            is_sig = zscore.index[i] in sig_set
            text_color = "white" if abs(val) > 0.65 else "black"
            marker = " *" if is_sig else ""
            ax_heat.text(j, i, f"{val:.1f}{marker}", ha="center", va="center",
                         fontsize=6, color=text_color)

    ax_heat.set_xticks(range(n_conds))
    ax_heat.set_xticklabels(zscore.columns, rotation=30, ha="right", fontsize=8)
    ax_heat.set_yticks(range(n_params))
    ax_heat.set_yticklabels([_short_label(p) for p in zscore.index], fontsize=7)
    ax_heat.set_title(title, fontsize=10, pad=8)

    # ── 右侧 epsilon² 注释柱 ──
    eps_vals = eps_map[zscore.index].values  # 确保顺序一致
    eps_colors = []
    for p in zscore.index:
        sig = p in sig_set
        eps_colors.append("#E53935" if sig else "#BDBDBD")

    ax_eps.barh(range(n_params), eps_vals, color=eps_colors, height=0.6)
    ax_eps.set_xlim(0, max(eps_vals.max() * 1.4, 0.05))
    ax_eps.set_xlabel("ε²", fontsize=8)
    ax_eps.set_yticks([])
    ax_eps.tick_params(labelsize=7)
    ax_eps.axvline(0.01, color="gray", linestyle=":", linewidth=0.4)
    ax_eps.axvline(0.06, color="gray", linestyle="--", linewidth=0.4)
    ax_eps.axvline(0.14, color="gray", linestyle="-", linewidth=0.4)

    # ── 顶部图例 ──
    fig.colorbar(im, ax=ax_heat, label="z-score (按行归一化)", shrink=0.8)

    # 显著标记 + epsilon² 图例
    legend_elements = [
        Patch(facecolor="#E53935", alpha=0.6, label="显著 (FDR p<0.05)"),
        Patch(facecolor="#BDBDBD", alpha=0.6, label="不显著"),
    ]
    ax_eps.legend(handles=legend_elements, fontsize=6, loc="lower right")

    fig.tight_layout()

    if output_path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(output_path, bbox_inches="tight", dpi=130)
    plt.close(fig)
    return fig


def _short_label(col: str) -> str:
    """截短列名用于显示。"""
    for prefix in ["采煤机_", "三机_"]:
        if col.startswith(prefix):
            col = col[len(prefix):]
            break
    parts = col.split("_")
    if len(parts) <= 2:
        return col
    return "_".join(parts[-3:])


# ── 批量运行 ────────────────────────────────────────────────


PART_COND_MAP = {
    "截割部": "截割部_工况",
    "牵引部": "牵引部_工况",
    "油泵": "油泵_工况",
    "破碎机": "破碎机_工况",
}


def run_per_part_significance_test(
    df: pd.DataFrame,
    output_dir: str | Path,
    monitor_cols: list[str] | None = None,
    part_cond_map: dict[str, str] | None = None,
) -> dict[str, pd.DataFrame]:
    """为每个部位运行 Kruskal-Wallis 检验，保存 CSV + 热力图。

    Returns
    -------
    dict[str, pd.DataFrame] — { 部位: 检验结果表 }
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if part_cond_map is None:
        part_cond_map = PART_COND_MAP
    if monitor_cols is None:
        from src import config
        monitor_cols = [c for c in df.columns if c in config.CMJ_MONITOR_POINTS]

    all_results = {}
    for part_name, cond_col in part_cond_map.items():
        if cond_col not in df.columns:
            print(f"  跳过 {part_name}: 缺少 {cond_col}")
            continue
        print(f"\n  Kruskal-Wallis: {part_name} ({cond_col})")
        result_df = kruskal_wallis_test(df, cond_col, monitor_cols)
        all_results[part_name] = result_df

        # CSV
        csv_path = output_dir / f"kruskal_{part_name}.csv"
        result_df.to_csv(csv_path, index=False, encoding="utf-8-sig")
        print(f"    CSV: {csv_path}")

        # ── 计算各工况下的参数中位数（用于 2D 热力图） ──
        med_df = df.groupby(cond_col)[monitor_cols].median().T
        # 排除全 NaN 的行/列
        med_df = med_df.dropna(how="all", axis=0).dropna(how="all", axis=1)
        # 排除"未知"工况
        if "未知" in med_df.columns:
            med_df = med_df.drop(columns=["未知"])
        # 保留至少含 2 个有效值的参数
        med_df = med_df.dropna(thresh=2, axis=0)

        # 热力图
        sig_count = (result_df["FDR校正p值"].fillna(1) < 0.05).sum()
        title = f"Kruskal-Wallis — {part_name}（{sig_count}/{len(result_df)} 显著）"
        png_path = output_dir / f"kruskal_{part_name}_heatmap.png"
        plot_kruskal_heatmap(
            result_df, title=title, condition_medians=med_df,
            output_path=png_path,
        )
        print(f"    热力图: {png_path}")

    return all_results
