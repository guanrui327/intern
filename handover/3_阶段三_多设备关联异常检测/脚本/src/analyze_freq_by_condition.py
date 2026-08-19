# -*- coding: utf-8 -*-
"""频域特征的工况区分度分析。

验证假设：不同工况下频谱模式是否有统计显著的差异。

方法：
  1. 从 cmj_with_condition.parquet 读取原始 1min 等间隔数据
  2. 调用 extract_frequency_features() 计算滑动窗口 FFT 特征
  3. 透转为宽表 + 合并工况标签
  4. 分部位运行 Kruskal-Wallis 检验
  5. 可视化（KW热力图 / 区分度排名 / PCA散点 / 箱线图）

输出：output/phase2/freq_analysis/
  - {part}_kw_results.csv          KW 检验结果
  - {part}_kw_heatmap.png          epsilon² 效应量热力图
  - {part}_discriminative_power.png  H 统计量 top-20 柱状图
  - {part}_pca_scatter.png         PCA 频域空间散点
  - {part}_box_grid.png            区分度 top-4 箱线图矩阵
"""

from __future__ import annotations

import gc
import warnings
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Ellipse
import numpy as np
import pandas as pd

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    from sklearn.decomposition import PCA
    from sklearn.impute import SimpleImputer

from src import config
from src.feature_extract import extract_frequency_features
from src.significance import kruskal_wallis_test, _effect_size_label

# ── 全局绘图风格 ──────────────────────────────────────────────
plt.rcParams.update({
    "figure.dpi": 120,
    "font.family": "sans-serif",
    "font.sans-serif": ["Microsoft YaHei", "SimHei",
                         "WenQuanYi Micro Hei", "Noto Sans CJK SC",
                         "DejaVu Sans"],
    "axes.unicode_minus": False,
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
    "待机-高位": "#B0BEC5",
    "割煤低位": "#42A5F5",
    "割煤中位": "#1E88E5",
    "割煤高位": "#1565C0",
    # 补充
    "重载牵引": "#FF5722",
    "轻载": "#A5D6A7",
    "重载": "#E53935",
}

FREQ_FEATURES = ["主频", "频谱质心", "频谱熵", "低频占比", "中频占比", "高频占比"]

# ── 辅助函数 ──────────────────────────────────────────────────


def _short_label(col: str) -> str:
    """从完整列名提取可读短标签。

    处理形如 采煤机_截割部位_右滚筒_电机_电流_主频 的列名
    → 优先去前缀，保留最后 3 段 + 频域指标
    """
    s = col
    for prefix in ["采煤机_", "三机_"]:
        if s.startswith(prefix):
            s = s[len(prefix):]
            break
    return s


def _split_freq_col(col: str) -> tuple[str, str]:
    """拆分频域宽表列名为 (参数基名, 频域指标)。

    列名格式: {参数基名}_{频域指标}
    如: 采煤机_截割部位_右滚筒_电机_电流_主频 → (采煤机_截割部位_右滚筒_电机_电流, 主频)
    """
    for feat in FREQ_FEATURES:
        if col.endswith(f"_{feat}"):
            return col[:-(len(feat) + 1)], feat
    return col, ""


# ── 频域特征提取与透传 ──────────────────────────────────────


def _extract_and_pivot(
    df: pd.DataFrame,
    monitor_cols: list[str],
    cond_cols: list[str],
    window: int = 30,
    step: int = 5,
) -> pd.DataFrame:
    """提取频域特征 → 透传为宽表 → 合并工况。

    Returns
    -------
    pd.DataFrame
        [时间戳, 截割部_工况, 牵引部_工况, ...
         {param}_主频, {param}_频谱质心, ..., {param}_高频占比]
    """
    freq_long = extract_frequency_features(
        df, monitor_cols=monitor_cols, window=window, step=step,
    )
    if freq_long.empty:
        print("  [ERROR] 频域特征提取结果为空")
        return pd.DataFrame()

    # 逐个频域指标透传
    pivots = []
    for feat in FREQ_FEATURES:
        wide = freq_long.pivot_table(
            index="时间戳", columns="参数", values=feat, aggfunc="first",
        )
        wide.columns = [f"{c}_{feat}" for c in wide.columns]
        pivots.append(wide)

    # 合并所有频域指标
    freq_wide = pivots[0].join(pivots[1:], how="outer").reset_index()
    freq_wide = freq_wide.sort_values("时间戳").reset_index(drop=True)

    # 合并工况：从原始 df 按时间戳取工况
    for cond_col in cond_cols:
        if cond_col not in df.columns:
            continue
        ts = freq_wide["时间戳"].values
        # 确保 ts 在 df.index 范围内
        valid_mask = pd.Index(ts).isin(df.index)
        cond_vals = df.loc[ts[valid_mask], cond_col].values
        freq_wide[cond_col] = pd.NA  # object dtype，兼容 str
        freq_wide.loc[valid_mask, cond_col] = cond_vals

    print(f"  频域特征宽表: {freq_wide.shape}")
    return freq_wide


def _filter_freq_cols(
    freq_wide: pd.DataFrame,
    part_key: str,
) -> list[str]:
    """筛选部位相关的频域特征列 + 工况列。"""
    kw_filter = config.CMJ_PART_MONITOR_MAP.get(part_key, [])
    all_feat_cols = [
        c for c in freq_wide.columns
        if any(c.endswith(f"_{feat}") for feat in FREQ_FEATURES)
    ]
    if not kw_filter:
        return all_feat_cols
    return [c for c in all_feat_cols if any(kw in c for kw in kw_filter)]


# ── 可视化 ──────────────────────────────────────────────────


def plot_kw_heatmap(
    kw_df: pd.DataFrame,
    part_key: str,
    cond_col: str,
    output_dir: Path,
) -> None:
    """KW 效应量热力图：x=频域指标, y=参数基名, 色值=epsilon²。"""
    if kw_df.empty:
        return

    # 解析出 参数基名 × 频域指标
    rows = []
    for _, r in kw_df.iterrows():
        param_base, feat = _split_freq_col(r["参数列"])
        rows.append({
            "参数": param_base,
            "频域指标": feat,
            "epsilon²": r.get("epsilon²", 0),
            "FDR校正p值": r.get("FDR校正p值", 1),
            "效应量等级": r.get("效应量等级", "无"),
        })

    data = pd.DataFrame(rows)
    if data.empty:
        return

    # 透视：行=参数, 列=频域指标
    pivot = data.pivot_table(
        index="参数", columns="频域指标", values="epsilon²", aggfunc="first",
    )
    # 填充缺失频域指标列
    for feat in FREQ_FEATURES:
        if feat not in pivot.columns:
            pivot[feat] = np.nan
    pivot = pivot[FREQ_FEATURES]  # 固定列序

    # 按 epsilon² 均值降序排列参数
    pivot = pivot.loc[pivot.mean(axis=1).sort_values(ascending=False).index]

    sig_pivot = data.pivot_table(
        index="参数", columns="频域指标", values="FDR校正p值", aggfunc="first",
    )[FREQ_FEATURES]
    sig_pivot = sig_pivot.loc[pivot.index]

    n_params, n_feats = pivot.shape
    if n_params == 0:
        return

    fig_w = max(6, n_feats * 1.5 + 2)
    fig_h = max(4, n_params * 0.45 + 1)
    fig, ax = plt.subplots(figsize=(fig_w, fig_h))
    im = ax.imshow(pivot.values, aspect="auto", cmap="YlOrRd",
                    vmin=0, vmax=max(0.2, pivot.values.max()), interpolation="nearest")

    # 标注数值 + 显著性星号
    for i in range(n_params):
        for j in range(n_feats):
            val = pivot.values[i, j]
            if np.isnan(val):
                continue
            sig = sig_pivot.values[i, j] < 0.05 if not np.isnan(sig_pivot.values[i, j]) else False
            grade = _effect_size_label(val)
            color = "white" if val > 0.10 else "black"
            label = f"{val:.2f}"
            if sig:
                label += "*"
            ax.text(j, i, label, ha="center", va="center", fontsize=7, color=color)

    ax.set_xticks(range(n_feats))
    ax.set_xticklabels(pivot.columns, fontsize=9)
    ax.set_yticks(range(n_params))
    ax.set_yticklabels([_short_label(c) for c in pivot.index], fontsize=7)
    ax.set_title(f"{part_key} — KW 效应量 epsilon²（*p<0.05）", fontsize=11)
    fig.colorbar(im, ax=ax, shrink=0.8)

    path = output_dir / f"{part_key}_kw_heatmap.png"
    fig.savefig(path, bbox_inches="tight", dpi=130)
    plt.close(fig)
    print(f"  KW 热力图: {path}")


def plot_discriminative_power(
    kw_df: pd.DataFrame,
    part_key: str,
    output_dir: Path,
    top_n: int = 20,
) -> None:
    """区分度排名柱状图：按 H 统计量排序 top-N 参数×频域特征组合。"""
    if kw_df.empty:
        return

    # 筛除 NaN
    plot_df = kw_df.dropna(subset=["H统计量", "epsilon²"]).head(top_n).copy()

    if plot_df.empty:
        return

    # 取短标签
    short = [_short_label(c) for c in plot_df["参数列"]]
    eps = plot_df["epsilon²"].values
    h_stat = plot_df["H统计量"].values
    sig = plot_df["FDR校正p值"].fillna(1) < 0.05

    fig_h = max(4, len(short) * 0.35)
    fig, ax = plt.subplots(figsize=(10, fig_h))

    colors = ["#E53935" if s else "#BDBDBD" for s in sig]
    bars = ax.barh(range(len(short)), h_stat, color=colors, height=0.6)

    # epsilon² 数值标注
    for i, (h, e) in enumerate(zip(h_stat, eps)):
        ax.text(h + max(h_stat) * 0.01, i,
                f"ε²={e:.4f}",
                va="center", fontsize=6, color="#333")

    ax.set_yticks(range(len(short)))
    ax.set_yticklabels(short, fontsize=7)
    ax.set_xlabel("Kruskal-Wallis H 统计量", fontsize=9)
    ax.set_title(f"{part_key} — 频域特征工况区分度排名（top-{top_n}）", fontsize=11)
    ax.axvline(0, color="gray", linewidth=0.5)
    ax.legend(
        [plt.Rectangle((0, 0), 1, 1, color="#E53935"),
         plt.Rectangle((0, 0), 1, 1, color="#BDBDBD")],
        ["显著 (FDR p<0.05)", "不显著"],
        fontsize=7, loc="lower right",
    )
    fig.tight_layout()

    path = output_dir / f"{part_key}_discriminative_power.png"
    fig.savefig(path, bbox_inches="tight", dpi=130)
    plt.close(fig)
    print(f"  区分度排名: {path}")


def plot_pca_scatter(
    freq_wide: pd.DataFrame,
    part_key: str,
    cond_col: str,
    output_dir: Path,
) -> None:
    """频域特征 PCA 散点，着色按工况。"""
    feat_cols = _filter_freq_cols(freq_wide, part_key)
    if not feat_cols or len(feat_cols) < 2:
        return

    # 准备数据
    data = freq_wide.dropna(subset=feat_cols, how="all").copy()
    if data.empty:
        return

    X = data[feat_cols].values
    conds = data[cond_col].values

    # 筛掉 NaN 行
    valid_mask = ~np.isnan(X).any(axis=1)
    X_valid = X[valid_mask]
    conds_valid = conds[valid_mask]

    if len(X_valid) < 10:
        return

    # 标准化
    imputer = SimpleImputer(strategy="mean")
    X_clean = imputer.fit_transform(X_valid)
    X_scaled = (X_clean - X_clean.mean(axis=0)) / np.maximum(X_clean.std(axis=0), 1e-10)

    # PCA
    n_components = min(10, len(feat_cols), len(X_scaled) - 1)
    pca = PCA(n_components=n_components).fit(X_scaled)
    scores = pca.transform(X_scaled)
    var_ratio = pca.explained_variance_ratio_

    # 绘图
    fig, ax = plt.subplots(figsize=(8, 6))
    unique_conds = sorted(set(conds_valid), key=lambda x: str(x))

    for cond in unique_conds:
        mask = conds_valid == cond
        if mask.sum() < 2:
            continue
        c = COND_COLORS.get(str(cond), "#EEEEEE")
        ax.scatter(scores[mask, 0], scores[mask, 1],
                   c=c, label=cond, alpha=0.5, s=8, edgecolors="none")

        # 置信椭圆
        if mask.sum() >= 5:
            _plot_confidence_ellipse(
                scores[mask, 0], scores[mask, 1], ax,
                edgecolor=c, facecolor=c, alpha=0.08,
            )

    ax.set_xlabel(f"PC1 ({var_ratio[0]*100:.1f}%)", fontsize=9)
    ax.set_ylabel(f"PC2 ({var_ratio[1]*100:.1f}%)", fontsize=9)
    ax.set_title(f"{part_key} — 频域特征 PCA（{len(feat_cols)} 维→2D）", fontsize=11)
    ax.legend(fontsize=7, loc="best", markerscale=2)

    path = output_dir / f"{part_key}_pca_scatter.png"
    fig.savefig(path, bbox_inches="tight", dpi=130)
    plt.close(fig)
    print(f"  PCA 散点: {path}")


def _plot_confidence_ellipse(
    x: np.ndarray, y: np.ndarray, ax: plt.Axes,
    edgecolor: str = "#333", facecolor: str = "#333", alpha: float = 0.1,
    n_std: float = 2.0,
) -> None:
    """绘制 95% 置信椭圆（近似）。"""
    cov = np.cov(x, y)
    if np.any(np.isnan(cov)):
        return
    try:
        eigenvalues, eigenvectors = np.linalg.eigh(cov)
    except np.linalg.LinAlgError:
        return

    angle = np.degrees(np.arctan2(eigenvectors[1, 0], eigenvectors[0, 0]))
    width, height = 2 * n_std * np.sqrt(eigenvalues)
    if width <= 0 or height <= 0:
        return

    ellipse = Ellipse(
        xy=(np.mean(x), np.mean(y)),
        width=width, height=height,
        angle=angle,
        edgecolor=edgecolor,
        facecolor=facecolor,
        alpha=alpha,
        linewidth=1,
    )
    ax.add_patch(ellipse)


def plot_box_grid(
    freq_wide: pd.DataFrame,
    kw_df: pd.DataFrame,
    part_key: str,
    cond_col: str,
    output_dir: Path,
    top_n: int = 4,
) -> None:
    """箱线图矩阵：选取 H 统计量最高的 top-N 频域特征。"""
    if kw_df.empty or freq_wide.empty:
        return

    top_cols = kw_df.dropna(subset=["H统计量"]).head(top_n)["参数列"].tolist()
    if not top_cols:
        return

    # 确保列存在于 freq_wide 中
    top_cols = [c for c in top_cols if c in freq_wide.columns]
    if not top_cols:
        return

    n_cols = min(len(top_cols), top_n)
    rows = (n_cols + 1) // 2
    fig, axes = plt.subplots(rows, 2, figsize=(12, 4 * rows))
    axes = axes.flatten() if rows > 1 else [axes] if n_cols == 1 else axes

    # 获取所有工况
    cond_vals = freq_wide[cond_col].dropna().unique()
    cond_order = sorted(
        [c for c in cond_vals if str(c) != "nan" and c != "未知"],
        key=lambda x: str(x),
    )

    for idx, col in enumerate(top_cols):
        ax = axes[idx]
        groups = []
        tick_labels = []
        positions = []
        pos_colors = []
        for i, cond in enumerate(cond_order):
            vals = freq_wide.loc[freq_wide[cond_col] == cond, col].dropna().values
            if len(vals) < 5:
                continue
            groups.append(vals)
            tick_labels.append(str(cond))
            positions.append(i + 1)
            pos_colors.append(COND_COLORS.get(str(cond), "#EEEEEE"))

        if not groups:
            ax.text(0.5, 0.5, "无数据", ha="center", va="center", fontsize=10)
            ax.set_title(_short_label(col), fontsize=8)
            continue

        bp = ax.boxplot(groups, positions=positions, patch_artist=True,
                         widths=0.5, showfliers=False, manage_ticks=False)
        for patch, color in zip(bp["boxes"], pos_colors):
            patch.set_facecolor(color)
            patch.set_alpha(0.7)

        ax.set_xticks(positions)
        ax.set_xticklabels(tick_labels, rotation=15, fontsize=7)
        ax.set_title(_short_label(col), fontsize=8)
        ax.tick_params(axis="y", labelsize=7)

    # 隐藏多余的子图
    for idx in range(n_cols, len(axes)):
        axes[idx].set_visible(False)

    fig.suptitle(f"{part_key} — 区分度 top-{n_cols} 频域特征工况分布", fontsize=11)
    fig.tight_layout(rect=[0, 0, 1, 0.97])

    path = output_dir / f"{part_key}_box_grid.png"
    fig.savefig(path, bbox_inches="tight", dpi=130)
    plt.close(fig)
    print(f"  箱线图: {path}")


# ── 主体分析流程 ──────────────────────────────────────────────


def _run_part_analysis(
    freq_wide: pd.DataFrame,
    part_key: str,
    cond_col: str,
    output_dir: Path,
) -> pd.DataFrame | None:
    """对单个部位运行频域特征工况区分度分析。"""
    print(f"\n{'=' * 50}")
    print(f"部位: {part_key}  |  工况列: {cond_col}")
    print(f"{'=' * 50}")

    # 筛选该部位频域特征列
    feat_cols = _filter_freq_cols(freq_wide, part_key)
    if not feat_cols:
        print("  [SKIP] 无匹配频域特征列")
        return None
    print(f"  频域特征数: {len(feat_cols)}")

    # 工况列可能含 NaN（非本部位工作时间段）
    part_data = freq_wide.dropna(subset=[cond_col]).copy()
    if part_data.empty:
        print("  [SKIP] 工况数据为空")
        return None

    # 排除"未知"
    part_data = part_data[part_data[cond_col] != "未知"]
    if part_data.empty:
        print("  [SKIP] 均为未知工况")
        return None

    # 打印工况分布
    cond_counts = part_data[cond_col].value_counts()
    for cond, cnt in cond_counts.items():
        print(f"    {cond}: {cnt} 窗口")

    # 1. Kruskal-Wallis 检验
    print("  KW 检验...")
    kw_result = kruskal_wallis_test(part_data, cond_col, feat_cols)
    if not kw_result.empty:
        kw_path = output_dir / f"{part_key}_kw_results.csv"
        kw_result.to_csv(kw_path, index=False, encoding="utf-8-sig")
        print(f"    CSV: {kw_path}")

        # 统计
        n_sig = (kw_result["FDR校正p值"].fillna(1) < 0.05).sum()
        n_large = (kw_result["epsilon²"].fillna(0) >= 0.14).sum()
        n_medium = ((kw_result["epsilon²"].fillna(0) >= 0.06)
                    & (kw_result["epsilon²"].fillna(0) < 0.14)).sum()
        print(f"    显著 (FDR p<0.05): {n_sig}/{len(kw_result)}")
        print(f"    大效应量: {n_large}, 中效应量: {n_medium}")

        # 按 H 统计量排序
        kw_result = kw_result.sort_values("H统计量", ascending=False)
        print(f"    区分度 top-5:")
        for _, r in kw_result.head(5).iterrows():
            print(f"      {_short_label(r['参数列'])}: "
                  f"H={r['H统计量']:.1f}, "
                  f"eps^2={r['epsilon\xb2']:.3f} ({r['效应量等级']})")
    else:
        print("  [WARN] KW 检验返回空")

    # 2. 可视化
    print("  可视化...")
    plot_kw_heatmap(kw_result, part_key, cond_col, output_dir)
    plot_discriminative_power(kw_result, part_key, output_dir)
    plot_pca_scatter(part_data, part_key, cond_col, output_dir)
    plot_box_grid(part_data, kw_result, part_key, cond_col, output_dir)

    return kw_result


def main() -> None:
    print("=" * 50)
    print("频域特征的工况区分度分析")
    print("=" * 50)

    output_dir = config.PHASE2_DIR / "freq_analysis"
    output_dir.mkdir(parents=True, exist_ok=True)

    # ── 1. 加载数据 ──
    print("\n--- 加载数据 ---")
    cmj_path = config.PHASE1_DIR / "cmj_with_condition.parquet"
    print(f"  CMJ: {cmj_path}")
    cmj = pd.read_parquet(cmj_path)
    print(f"    形状: {cmj.shape}")

    monitor_cols = [c for c in cmj.columns if c in config.CMJ_MONITOR_POINTS]
    print(f"  监测参数: {len(monitor_cols)} 个")

    # ── 2. 频域特征提取 + 宽表化 ──
    print("\n--- 频域特征提取 ---")
    window = 30  # 30帧 (30分钟)
    step = 5     # 5帧步长
    cond_cols = config.CMJ_PART_COND_COLS
    freq_wide = _extract_and_pivot(
        cmj, monitor_cols, cond_cols, window=window, step=step,
    )
    if freq_wide.empty:
        print("[ERROR] 频域特征为空，退出")
        return

    # 释放原始数据
    del cmj
    gc.collect()

    # ── 3. 分部位分析 ──
    part_cond_map = {
        "截割部": "截割部_工况",
        "牵引部": "牵引部_工况",
        "油泵": "油泵_工况",
        "破碎机": "破碎机_工况",
    }

    all_results: dict[str, pd.DataFrame] = {}
    for part_key, cond_col in part_cond_map.items():
        result = _run_part_analysis(
            freq_wide, part_key, cond_col, output_dir,
        )
        if result is not None:
            all_results[part_key] = result

    # ── 4. 跨部位汇总 ──
    print(f"\n{'=' * 50}")
    print("跨部位汇总")
    print(f"{'=' * 50}")

    summary_rows = []
    for part_key, kw_df in all_results.items():
        if kw_df.empty:
            continue
        n_sig = (kw_df["FDR校正p值"].fillna(1) < 0.05).sum()
        n_large = (kw_df["epsilon²"].fillna(0) >= 0.14).sum()
        n_medium = ((kw_df["epsilon²"].fillna(0) >= 0.06)
                    & (kw_df["epsilon²"].fillna(0) < 0.14)).sum()
        n_total = len(kw_df)

        # 按频域指标汇总
        for feat in FREQ_FEATURES:
            mask = kw_df["参数列"].str.endswith(f"_{feat}")
            if not mask.any():
                continue
            feat_mean_eps = kw_df.loc[mask, "epsilon²"].fillna(0).mean()
            feat_n_sig = (kw_df.loc[mask, "FDR校正p值"].fillna(1) < 0.05).sum()
            summary_rows.append({
                "部位": part_key,
                "频域指标": feat,
                "特征数": mask.sum(),
                "显著数": feat_n_sig,
                "平均epsilon²": round(feat_mean_eps, 4),
            })

        print(f"  {part_key}: {n_total} 特征, 显著 {n_sig}, "
              f"大效应量 {n_large}, 中效应量 {n_medium}")

    summary = pd.DataFrame(summary_rows)
    if not summary.empty:
        sum_path = output_dir / "freq_analysis_summary.csv"
        summary.to_csv(sum_path, index=False, encoding="utf-8-sig")
        print(f"  汇总表: {sum_path}")

        # 打印频域指标排名
        print("\n  频域指标平均区分度（跨部位）:")
        feat_ranking = summary.groupby("频域指标").agg(
            mean_eps=("平均epsilon²", "mean"),
            total_sig=("显著数", "sum"),
        ).sort_values("mean_eps", ascending=False)
        for feat, row in feat_ranking.iterrows():
            print(f"    {feat}: eps^2={row['mean_eps']:.4f}, 显著数={row['total_sig']}")

    print(f"\n完成。输出目录: {output_dir}")
    print("=" * 50)


if __name__ == "__main__":
    main()
