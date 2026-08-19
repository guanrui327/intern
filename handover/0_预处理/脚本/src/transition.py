# -*- coding: utf-8 -*-
"""工况转换时序特征：检测切换事件、提取窗口数据、统计特征。"""

from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# ── 转换检测 ──────────────────────────────────────────────


def detect_transitions(
    df: pd.DataFrame,
    cond_col: str = "L1",
    window: int = 5,
    exclude_unknown: bool = True,
) -> pd.DataFrame:
    """检测工况转换事件，提取窗口数据。

    Parameters
    ----------
    df :
        已含工况列的宽表（重采样到 1min 等间隔）。
    cond_col :
        工况列名，默认 "L1"。
    window :
        切换点前后各取多少分钟，默认 5min。
    exclude_unknown :
        是否排除包含 "未知" 工况的切换。

    Returns
    -------
    pd.DataFrame
        [切换时间, 切换前工况, 切换后工况, 持续帧数, …]
        另带 "*_窗口" 列记录前后 window 帧内各参数的均值。
    """
    cond = df[cond_col].ffill()
    # 定位切换点：前后值不同
    shift_prev = cond.shift(1)
    shift_next = cond.shift(-1)
    change_mask = (cond != shift_prev) & (shift_prev.notna())

    change_positions = np.where(change_mask.values)[0]
    if len(change_positions) == 0:
        return pd.DataFrame(columns=["切换时间", "切换前工况", "切换后工况",
                                      "持续帧数", "帧索引"])

    # ── 预计算工况游程编码：切换点按位置查表 O(1)，
    #    替代原实现逐切换点 cond.loc[idx:] 的 O(n²) 切片 ──
    cond_values = cond.values
    n = len(cond_values)
    run_starts = np.concatenate([[0], np.where(cond_values[:-1] != cond_values[1:])[0] + 1])
    run_ends = np.concatenate([run_starts[1:], [n]])

    records = []
    for pos in change_positions:
        prev_cond = shift_prev.iat[pos]
        next_cond = cond.iat[pos]
        if exclude_unknown and ("未知" in str(prev_cond) or "未知" in str(next_cond)):
            continue

        # 持续帧数：切后工况所在游程的剩余帧数
        # （修正原逻辑 cumsum==1 恒为 1 的问题）
        k = int(np.searchsorted(run_starts, pos, side="right") - 1)
        run_length = int(run_ends[k] - pos)

        records.append({
            "切换时间": df.index[pos],
            "切换前工况": prev_cond,
            "切换后工况": next_cond,
            "持续帧数": run_length,
            "帧索引": df.index[pos],
        })

    if not records:
        return pd.DataFrame(columns=["切换时间", "切换前工况", "切换后工况",
                                      "持续帧数", "帧索引"])

    result = pd.DataFrame(records).sort_values("切换时间").reset_index(drop=True)

    # 追加切换窗口内各参数均值（仅数值列，使用滚动窗口向量化计算）
    param_cols = df.select_dtypes(include="number").columns.tolist()
    if param_cols and not result.empty:
        # 预计算滚动窗口均值，避免逐行 .loc + .mean()
        rolling_before = df[param_cols].rolling(window=window, min_periods=1).mean().shift(1)
        rolling_after = df[param_cols].rolling(window=window, min_periods=1).mean()
        for col in param_cols:
            times = result["切换时间"]
            before_vals = rolling_before.loc[times, col].values
            after_vals = rolling_after.loc[times, col].values
            result[f"{col}_切换前均值"] = before_vals
            result[f"{col}_切换后均值"] = after_vals

    return result


# ── 典型切换可视化 ─────────────────────────────────────────


def plot_transition_parameters(
    df: pd.DataFrame,
    transitions: pd.DataFrame,
    param_col: str,
    window: int = 10,
    max_examples: int = 3,
    title: str = "工况切换关键参数时序",
    output_path: str | Path | None = None,
) -> plt.Figure:
    """针对一个典型切换序列，绘制关键参数在窗口内的时序。

    将 *transitions* 中切换点周围 ±window 分钟的数据叠图，
    选定前 *max_examples* 个非重复切换类型。
    """
    if transitions.empty:
        fig, ax = plt.subplots(figsize=(8, 3))
        ax.text(0.5, 0.5, "无切换数据", ha="center", va="center")
        return fig

    # 选取代表性的切换（按类型取前 N 个）
    transitions = transitions.copy()
    type_key = transitions["切换前工况"].astype(str) + "→" + transitions["切换后工况"].astype(str)
    transitions["切换类型"] = type_key
    examples = transitions.groupby("切换类型").head(max_examples)
    # 最多画 12 张子图，防止卡死
    MAX_PANELS = 12
    if len(examples) > MAX_PANELS:
        examples = examples.head(MAX_PANELS)

    n_examples = len(examples)
    fig, axes = plt.subplots(n_examples, 1, figsize=(10, 3 * n_examples),
                              sharex=False, squeeze=False)
    axes = axes[:, 0]

    for ax_i, (_, row) in enumerate(examples.iterrows()):
        t0 = row["切换时间"]
        left = t0 - pd.Timedelta(minutes=window)
        right = t0 + pd.Timedelta(minutes=window)

        window_data = df.loc[left:right].copy()
        if window_data.empty:
            axes[ax_i].text(0.5, 0.5, "窗口无数据", ha="center", va="center")
            continue

        # 相对时间（分钟）
        rel_time = (window_data.index - pd.Timestamp(t0)).total_seconds() / 60.0

        if param_col in window_data.columns:
            axes[ax_i].plot(rel_time, window_data[param_col].values,
                    color="#1565C0", linewidth=1.5, marker=".", markersize=2)
        else:
            axes[ax_i].plot(rel_time, np.zeros(len(rel_time)),
                    color="#ccc", linestyle="--")

        axes[ax_i].axvline(0, color="red", linestyle="--", linewidth=1, alpha=0.7)
        axes[ax_i].set_title(f"{row['切换前工况']} → {row['切换后工况']}  @ {t0:%m-%d %H:%M}",
                     fontsize=9)
        axes[ax_i].set_ylabel(_short_label(param_col), fontsize=8)
        axes[ax_i].grid(True, alpha=0.3)

    axes[0].set_title(f"{title} — {_short_label(param_col)}", fontsize=11)
    fig.tight_layout()
    fig.supxlabel("相对时间 (min)", fontsize=9)

    if output_path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(output_path, bbox_inches="tight")

    plt.close(fig)
    return fig


# ── 切换统计 ────────────────────────────────────────────────


def compute_transition_stats(
    transitions: pd.DataFrame,
) -> pd.DataFrame:
    """对每类工况切换计算机统计特征：切换次数、平均持续时间、切换前后均值变化。

    Returns
    -------
    pd.DataFrame
        [切换类型, 切换次数, 平均持续帧数, 各参数前/后均值变化]
    """
    if transitions.empty:
        return pd.DataFrame(columns=["切换类型", "切换次数"])

    transitions = transitions.copy()
    type_key = transitions["切换前工况"].astype(str) + "→" + transitions["切换后工况"].astype(str)
    transitions["切换类型"] = type_key

    agg = transitions.groupby("切换类型").agg(
        切换次数=("持续帧数", "count"),
        平均持续帧数=("持续帧数", "mean"),
    )

    # 对每个参数的变化量
    param_change_cols = [c for c in transitions.columns
                         if c.endswith("_切换前均值") or c.endswith("_切换后均值")]
    if param_change_cols:
        change_agg = transitions.groupby("切换类型")[param_change_cols].mean()
        # 重命名并计算差值
        agg = agg.join(change_agg, how="left")

    return agg.reset_index().round(2)


# ── 切换时域特征提取 ──────────────────────────────────────


def extract_transition_features(
    df: pd.DataFrame,
    transitions: pd.DataFrame,
    param_cols: list[str] | None = None,
    window: int = 10,
) -> pd.DataFrame:
    """对每个切换事件提取窗口内的时域特征。

    对每个事件*param_cols*中的每个参数计算：

    - Δ_mean         : 切换后均值 - 切换前均值
    - Δ_std_ratio    : |Δ_mean| / 前窗口 std（效应量）
    - max_slope      : 窗口内最大一阶差分（绝对值）
    - rise_time      : 从 t=0 到首次跨越 (pre_mean + Δ_mean/2) 的时间（分钟）
    - settling_time  : 从 t=0 到进入 post_mean±5% 并停留不再出的时间
    - overshoot      : (peak - post_mean) / (post_mean - pre_mean)，无超调时为 0
    - energy_ratio   : 后窗 RMS / 前窗 RMS

    Parameters
    ----------
    df : 原宽表（1min 等间隔，时间索引）
    transitions : detect_transitions() 输出的切换事件表
    param_cols : 要分析的特征参数列表，默认选全数值列的子集
    window : 窗口半径（分钟），默认 10

    Returns
    -------
    pd.DataFrame
        行 = 切换事件，列 = 特征（展平为 param__feature 格式）
    """
    if transitions.empty:
        return pd.DataFrame()

    if param_cols is None:
        param_cols = [c for c in df.select_dtypes(include="number").columns
                      if "工况" not in c and "状态" not in c
                      and any(kw in c for kw in ["电流", "速度", "温度", "角度", "高度", "电压", "转矩"])]
    # 过滤缺失列（等价于原循环内 `if col not in win.columns: continue`，
    # 因为 df.loc 不丢列，win.columns 恒等于 df.columns）
    param_cols = [c for c in param_cols if c in df.columns]

    records = []
    for _, row in transitions.iterrows():
        t0 = row["切换时间"]
        left = t0 - pd.Timedelta(minutes=window)
        right = t0 + pd.Timedelta(minutes=window)

        win = df.loc[left:right]
        if win.empty or len(win) < 3:
            continue

        rel_time = (win.index - t0).total_seconds() / 60.0
        pre_mask = rel_time < 0
        post_mask = rel_time >= 0

        feat = {
            "切换时间": t0,
            "切换前工况": row.get("切换前工况", ""),
            "切换后工况": row.get("切换后工况", ""),
        }

        # 一次预取整窗 numpy 2D 数组，避免逐参数 win[col] pandas 列访问
        win_np = win[param_cols].values.astype(float)
        for k, col in enumerate(param_cols):
            vals = win_np[:, k]
            pre_vals = vals[pre_mask]
            post_vals = vals[post_mask]

            if len(pre_vals) < 2 or len(post_vals) < 2:
                continue

            pre_mean = np.nanmean(pre_vals)
            post_mean = np.nanmean(post_vals)
            pre_std = np.nanstd(pre_vals)
            delta = post_mean - pre_mean

            feat[f"{col}__Δ_mean"] = round(delta, 4)
            feat[f"{col}__Δ_std_ratio"] = round(abs(delta) / pre_std, 4) if pre_std > 1e-8 else 0.0
            feat[f"{col}__pre_mean"] = round(pre_mean, 4)
            feat[f"{col}__post_mean"] = round(post_mean, 4)
            feat[f"{col}__pre_std"] = round(pre_std, 4)

            # 最大斜率（一阶差分 max）
            diffs = np.abs(np.diff(vals))
            feat[f"{col}__max_slope"] = round(float(np.nanmax(diffs)), 4) if len(diffs) > 0 else 0.0

            # 上升时间：从 t=0 到首次跨越 pre 和 post 中点
            midpoint = (pre_mean + post_mean) / 2
            crossing = np.where((vals[len(pre_vals):] >= midpoint)
                                if delta >= 0
                                else (vals[len(pre_vals):] <= midpoint))[0]
            rise_t = int(crossing[0]) if len(crossing) > 0 else window
            feat[f"{col}__rise_time"] = rise_t

            # 稳定时间：进入 post_mean ± 5% 范围不再出去
            # 向量化：settled = 最后一个越界点索引 + 1（该点之后全部 in band），
            # 全部 in band → 0；末尾仍越界（无稳定点）→ window。与旧 O(W²) 循环等价。
            band_low = post_mean - 0.05 * abs(post_mean) if abs(post_mean) > 1e-8 else post_mean
            band_high = post_mean + 0.05 * abs(post_mean) if abs(post_mean) > 1e-8 else post_mean + 0.05
            post_band = (vals[len(pre_vals):] >= band_low) & (vals[len(pre_vals):] <= band_high)
            bad = np.flatnonzero(~post_band)
            if len(bad) == 0:
                settled = 0
            elif bad[-1] < len(post_band) - 1:
                settled = int(bad[-1] + 1)
            else:
                settled = window
            feat[f"{col}__settling_time"] = settled

            # 超调量
            if abs(delta) > 1e-8:
                if delta > 0:
                    peak = np.nanmax(post_vals)
                    overshoot = max(0.0, (peak - post_mean) / delta)
                else:
                    trough = np.nanmin(post_vals)
                    overshoot = max(0.0, (post_mean - trough) / abs(delta))
            else:
                overshoot = 0.0
            feat[f"{col}__overshoot"] = round(overshoot, 4)

            # 能量比（RMS）
            pre_rms = np.sqrt(np.nanmean(pre_vals ** 2))
            post_rms = np.sqrt(np.nanmean(post_vals ** 2))
            feat[f"{col}__energy_ratio"] = round(post_rms / pre_rms, 4) if pre_rms > 1e-8 else 1.0

        records.append(feat)

    if not records:
        return pd.DataFrame()
    return pd.DataFrame(records).sort_values("切换时间").reset_index(drop=True)


# ── 聚合切换剖面可视化 ──────────────────────────────────


def plot_aggregate_transition_profile(
    df: pd.DataFrame,
    transitions: pd.DataFrame,
    param_col: str,
    window: int = 15,
    min_samples: int = 3,
    title: str = "切换聚合剖面",
    output_path: str | Path | None = None,
) -> plt.Figure:
    """对同一切换类型的所有事件，叠图展示参数轨迹均值±标准差包络。

    每类切换子图占一行：| 均值线 | ±1σ 阴影 | 个体轨迹（薄且透明） |
    """
    if transitions.empty:
        fig, ax = plt.subplots(figsize=(8, 3))
        ax.text(0.5, 0.5, "无切换数据", ha="center", va="center")
        return fig

    transitions = transitions.copy()
    type_key = transitions["切换前工况"].astype(str) + "→" + transitions["切换后工况"].astype(str)
    transitions["切换类型"] = type_key

    types = transitions["切换类型"].unique()
    # 过滤掉样本太少或不感兴趣的
    type_counts = transitions["切换类型"].value_counts()
    valid_types = type_counts[type_counts >= min_samples].index.tolist()

    if not valid_types:
        fig, ax = plt.subplots(figsize=(8, 3))
        ax.text(0.5, 0.5, f"无类型满足最少样本数 ({min_samples})", ha="center", va="center")
        return fig

    n_types = len(valid_types)
    fig, axes = plt.subplots(n_types, 1, figsize=(12, 3 * n_types),
                               sharex=True, squeeze=False)
    axes = axes[:, 0]

    rel_time = np.arange(-window, window + 1)

    for ax_i, tp in enumerate(valid_types):
        subset = transitions[transitions["切换类型"] == tp]
        trajectories = []

        for _, row in subset.iterrows():
            t0 = row["切换时间"]
            left = t0 - pd.Timedelta(minutes=window)
            right = t0 + pd.Timedelta(minutes=window)
            win = df.loc[left:right]

            if param_col in win.columns:
                traj = win[param_col].values[:len(rel_time)]
                if len(traj) == len(rel_time):
                    trajectories.append(traj.astype(float))

        if len(trajectories) < min_samples:
            axes[ax_i].text(0.5, 0.5, f"对齐后样本不足 ({len(trajectories)})",
                          ha="center", va="center", transform=axes[ax_i].transAxes)
            continue

        traj_arr = np.array(trajectories)
        mean_traj = np.nanmean(traj_arr, axis=0)
        std_traj = np.nanstd(traj_arr, axis=0)

        # 个体轨迹（浅色透明）
        for t in traj_arr:
            axes[ax_i].plot(rel_time, t, color="gray", alpha=0.08, linewidth=0.5)

        # 均值 ± 1σ 包络
        axes[ax_i].fill_between(rel_time, mean_traj - std_traj, mean_traj + std_traj,
                                alpha=0.25, color="#FF8C00")
        axes[ax_i].plot(rel_time, mean_traj, color="#D84315", linewidth=2, label=f"均值 (n={len(trajectories)})")

        axes[ax_i].axvline(0, color="red", linestyle="--", linewidth=1, alpha=0.7)
        axes[ax_i].set_title(f"{tp}  — {_short_label(param_col)}", fontsize=10)
        axes[ax_i].set_ylabel(_short_label(param_col), fontsize=8)
        axes[ax_i].grid(True, alpha=0.3)
        axes[ax_i].legend(fontsize=7, loc="best")

    axes[0].set_title(f"{title} — {_short_label(param_col)}", fontsize=12)
    fig.tight_layout()
    fig.supxlabel("相对时间 (min)", fontsize=9)

    if output_path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(output_path, bbox_inches="tight")

    plt.close(fig)
    return fig


# ── 多参数切换同屏可视化 ───────────────────────────────


def plot_multi_param_transition(
    df: pd.DataFrame,
    transitions: pd.DataFrame,
    param_cols: list[str],
    event_idx: int = 0,
    window: int = 15,
    title: str = "工况切换多参数时序",
    output_path: str | Path | None = None,
) -> plt.Figure:
    """切换「多参数指纹」热力图。

    选定一个切换事件，绘制热力图：
      - 行 = 参数（按 Δ_mean 效应量排序）
      - 列 = 相对时间 [-window, +window]
      - 颜色 = 参数自身 z-score（行归一化，突出变化方向）
      - 右侧柱 = 切换前后 Δ_mean（绝对值方向反映物理量升降）

    相比旧版（纵向折线堆叠），该图紧凑、模式可读，一眼看出哪些参数对切换有响应。
    """
    if transitions.empty or event_idx >= len(transitions):
        fig, ax = plt.subplots(figsize=(10, 4))
        ax.text(0.5, 0.5, "无效切换索引", ha="center", va="center")
        return fig

    row = transitions.iloc[event_idx]
    t0 = row["切换时间"]
    left = t0 - pd.Timedelta(minutes=window)
    right = t0 + pd.Timedelta(minutes=window)

    win = df.loc[left:right].copy()
    if win.empty or len(win) < 3:
        fig, ax = plt.subplots(figsize=(10, 4))
        ax.text(0.5, 0.5, "窗口无数据", ha="center", va="center")
        return fig

    rel_time = (win.index - t0).total_seconds() / 60.0
    present_params = [c for c in param_cols if c in df.columns]
    if not present_params:
        fig, ax = plt.subplots(figsize=(10, 4))
        ax.text(0.5, 0.5, "无有效参数列", ha="center", va="center")
        return fig

    # ── 构建值矩阵 (n_params × n_time) ──
    vals_mat = np.array([win[c].values.astype(float) for c in present_params])
    # 按行 z-score
    row_mean = np.nanmean(vals_mat, axis=1, keepdims=True)
    row_std = np.nanstd(vals_mat, axis=1, keepdims=True)
    z_mat = np.where((row_std > 1e-8),
                     (vals_mat - row_mean) / row_std,
                     np.zeros_like(vals_mat))

    # 按 |Δ_mean| 排序：切换前后均值差最大的参数排上面
    half = len(rel_time[rel_time < 0])
    pre_mean = np.nanmean(vals_mat[:, :half], axis=1) if half > 0 else np.zeros(vals_mat.shape[0])
    post_mean = np.nanmean(vals_mat[:, half:], axis=1) if half < vals_mat.shape[1] else np.zeros(vals_mat.shape[0])
    deltas = np.nan_to_num(post_mean - pre_mean, nan=0.0)
    sort_idx = np.argsort(-np.abs(deltas))  # 从大到小
    z_mat = z_mat[sort_idx]
    sorted_params = [present_params[i] for i in sort_idx]
    sorted_deltas = deltas[sort_idx]

    n_params, n_time = z_mat.shape
    # 右栏给 Δ_bar
    fig, (ax_heat, ax_delta) = plt.subplots(
        1, 2, figsize=(12, max(3, n_params * 0.35 + 1.5)),
        gridspec_kw={"width_ratios": [n_time * 0.55, 0.5], "wspace": 0.15},
    )

    # ── 热力图 ──
    vmax = max(abs(np.nanmin(z_mat)), abs(np.nanmax(z_mat)), 0.5)
    cmap = plt.cm.RdBu_r
    cmap.set_bad("lightgray")
    im = ax_heat.imshow(z_mat, aspect="auto", cmap=cmap,
                        vmin=-vmax, vmax=vmax, interpolation="nearest")

    # 切换时刻竖线（红色虚线列标记）
    zero_col = np.searchsorted(rel_time, 0, side="left") if rel_time[0] < 0 else 0
    ax_heat.axvline(zero_col - 0.5, color="red", linestyle="--", linewidth=1.2, alpha=0.6)

    ax_heat.set_xticks(range(n_time))
    # 每隔 ~15 个标一个时间标签
    step_t = max(1, n_time // 10)
    tick_labels = [f"{int(rel_time[i])}" if i % step_t == 0 else ""
                   for i in range(n_time)]
    ax_heat.set_xticklabels(tick_labels, fontsize=7, rotation=0)
    ax_heat.set_yticks(range(n_params))
    ax_heat.set_yticklabels([_short_label_parts(p) for p in sorted_params], fontsize=7)
    ax_heat.set_xlabel("相对时间 (min)", fontsize=9)
    ax_heat.set_title(f"{title} — {row.get('切换前工况','?')} → {row.get('切换后工况','?')}",
                      fontsize=11, pad=8)

    # 数值标注
    if n_params <= 20 and n_time <= 40:
        for i in range(n_params):
            for j in range(n_time):
                v = z_mat[i, j]
                if np.isnan(v):
                    continue
                c = "white" if abs(v) > 0.6 else "#333"
                ax_heat.text(j, i, f"{v:.1f}", ha="center", va="center",
                             fontsize=5, color=c)

    fig.colorbar(im, ax=ax_heat, label="z-score", shrink=0.8)

    # ── Δ_mean 柱状图 ──
    delta_colors = ["#D32F2F" if d > 0 else "#1976D2" for d in sorted_deltas]
    ax_delta.barh(range(n_params), sorted_deltas, color=delta_colors, height=0.6)
    ax_delta.axvline(0, color="gray", linewidth=0.5)
    ax_delta.set_xlabel("Δ_mean\n(后-前)", fontsize=8)
    ax_delta.set_yticks([])
    ax_delta.tick_params(labelsize=7)
    # 自动调整 x 范围
    max_abs_delta = max(abs(sorted_deltas).max(), 1e-5) * 1.3
    ax_delta.set_xlim(-max_abs_delta, max_abs_delta)

    fig.tight_layout()
    if output_path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(output_path, bbox_inches="tight")
    plt.close(fig)
    return fig


def _short_label_parts(col: str) -> str:
    """截短列名用于显示（保留部位+传感器的版本）。"""
    for prefix in ["采煤机_", "三机_"]:
        if col.startswith(prefix):
            col = col[len(prefix):]
            break
    return col[:30]


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


# ── 分部位转换检测便利函数 ─────────────────────────────────


def detect_all_part_transitions(
    df: pd.DataFrame,
    part_cols: list[str] | None = None,
    window: int = 5,
    exclude_unknown: bool = True,
) -> dict[str, pd.DataFrame]:
    """同时对多个部位列检测工况转换。

    Parameters
    ----------
    part_cols : 部位工况列列表，默认 ["截割部_工况", "牵引部_工况", "油泵_工况", "破碎机_工况"]

    Returns
    -------
    dict[str, pd.DataFrame]  — { 列名: 转换事件表 }
    """
    if part_cols is None:
        part_cols = ["截割部_工况", "牵引部_工况", "油泵_工况", "破碎机_工况"]
    results = {}
    for col in part_cols:
        if col not in df.columns:
            continue
        results[col] = detect_transitions(df, cond_col=col, window=window,
                                          exclude_unknown=exclude_unknown)
    return results


def detect_device_transitions(
    df: pd.DataFrame,
    window: int = 10,
) -> pd.DataFrame:
    """检测设备级工况 (设备_工况) 的转换事件。"""
    return detect_transitions(df, cond_col="设备_工况", window=window,
                              exclude_unknown=True)
