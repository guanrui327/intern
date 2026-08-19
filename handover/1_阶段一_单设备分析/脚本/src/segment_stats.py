# -*- coding: utf-8 -*-
"""状态段持续时间统计（Run-Length Encoding）。

对每种状态的连续段做游程编码，统计：
  - 段数（切换次数）
  - 最短 / 最长持续时间
  - 平均 / 中位持续时间
  - 总持续时长
"""

from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# ── 设置 CJK 字体 ──
plt.rcParams.update({
    "font.sans-serif": ["Microsoft YaHei", "SimHei", "WenQuanYi Micro Hei", "Noto Sans CJK SC", "DejaVu Sans"],
    "axes.unicode_minus": False,
})


def compute_segment_stats(
    df: pd.DataFrame,
    cond_col: str,
) -> pd.DataFrame:
    """对工况列做游程编码，输出每种状态的段持续时间统计。

    Parameters
    ----------
    df : 重采样后的等间隔宽表（1min）
    cond_col : 工况列名

    Returns
    -------
    pd.DataFrame
        [状态, 段数, 最短(min), 最长(min), 平均(min), 中位(min), 总时长(min)]
    """
    cond = df[cond_col].fillna("未知")
    # 游程编码
    values = cond.values
    n = len(values)
    if n == 0:
        return pd.DataFrame(columns=["状态", "段数", "最短(min)", "最长(min)",
                                      "平均(min)", "中位(min)", "总时长(min)"])

    # 找出变化点
    change_points = np.where(values[:-1] != values[1:])[0] + 1
    starts = np.concatenate([[0], change_points])
    ends = np.concatenate([change_points, [n]])
    run_lengths = ends - starts  # 帧数（分钟）
    run_values = values[starts]

    stats_list = []
    for state in np.unique(run_values):
        mask = run_values == state
        durations = run_lengths[mask]
        if len(durations) == 0:
            continue
        stats_list.append({
            "状态": str(state),
            "段数": int(len(durations)),
            "最短(min)": int(durations.min()),
            "最长(min)": int(durations.max()),
            "平均(min)": round(float(durations.mean()), 1),
            "中位(min)": round(float(np.median(durations)), 1),
            "总时长(min)": int(durations.sum()),
        })

    return pd.DataFrame(stats_list)


def compute_all_part_segment_stats(
    df: pd.DataFrame,
    output_dir: str | Path,
    part_cols: list[str] | None = None,
) -> dict[str, pd.DataFrame]:
    """为所有部位 + 设备级计算段持续时间统计。

    Returns
    -------
    dict[str, pd.DataFrame] — { 列名: 统计表 }
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if part_cols is None:
        part_cols = ["设备_工况", "截割部_工况", "牵引部_工况",
                      "油泵_工况", "破碎机_工况"]

    results = {}
    for col in part_cols:
        if col not in df.columns:
            continue
        stats = compute_segment_stats(df, col)
        if not stats.empty:
            safe_name = col.replace("_", "_")
            csv_path = output_dir / f"segment_stats_{safe_name}.csv"
            stats.to_csv(csv_path, index=False, encoding="utf-8-sig")
            results[col] = stats
            print(f"  {col}: {stats['状态'].tolist()}")
            print(f"    CSV: {csv_path}")

    # 可选：画箱线图
    _plot_all_segment_boxplots(df, part_cols, output_dir)

    return results


def _plot_all_segment_boxplots(
    df: pd.DataFrame,
    part_cols: list[str],
    output_dir: Path,
) -> None:
    """为每个部位画段持续时间箱线图。"""
    for col in part_cols:
        if col not in df.columns:
            continue
        _plot_single_segment_boxplot(df, col, output_dir)


def _plot_single_segment_boxplot(
    df: pd.DataFrame,
    cond_col: str,
    output_dir: Path,
) -> None:
    """针对一个工况列，画各状态的段持续时间箱线图。"""
    cond = df[cond_col].fillna("未知")
    values = cond.values
    change_points = np.where(values[:-1] != values[1:])[0] + 1
    starts = np.concatenate([[0], change_points])
    ends = np.concatenate([change_points, [len(values)]])
    run_lengths = ends - starts
    run_values = values[starts]

    # 按状态分组
    from collections import defaultdict
    state_durations = defaultdict(list)
    for state, dur in zip(run_values, run_lengths):
        state_durations[str(state)].append(dur)

    # 过滤掉样本过少的状态
    state_durations = {k: v for k, v in state_durations.items() if len(v) >= 3}

    if not state_durations:
        return

    try:
        from src.visualize import COND_COLORS
    except ImportError:
        COND_COLORS = {}

    states = list(state_durations.keys())
    data = [state_durations[s] for s in states]
    colors = [COND_COLORS.get(s, "#78909C") for s in states]

    fig, ax = plt.subplots(figsize=(max(6, len(states) * 1.2), 4))
    bp = ax.boxplot(data, tick_labels=states, patch_artist=True, showfliers=False)
    for patch, color in zip(bp["boxes"], colors):
        patch.set_facecolor(color)
        patch.set_alpha(0.6)

    ax.set_xlabel("工况", fontsize=9)
    ax.set_ylabel("持续时间 (min)", fontsize=9)
    ax.set_title(f"{cond_col} — 各工况段持续时间分布", fontsize=10)
    ax.tick_params(axis="x", rotation=25, labelsize=8)
    ax.grid(True, alpha=0.3, axis="y")
    fig.tight_layout()

    safe_name = cond_col.replace("_", "_")
    out_path = output_dir / f"segment_duration_{safe_name}.png"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, bbox_inches="tight", dpi=120)
    plt.close(fig)
    print(f"    箱线图: {out_path}")


# ═══════════════════════════════════════════════════════════
# 异常段检测：重采样导致的虚假持续段
# ═══════════════════════════════════════════════════════════


def detect_anomalous_segments(
    df: pd.DataFrame,
    cond_col: str,
    duration_threshold: int = 120,
    percentile_threshold: float = 99.0,
    min_anomalous_duration: int = 60,
) -> pd.DataFrame:
    """检测工况列中的异常持续段。

    On-change 存储 + 前向填充重采样会导致一种数据陷阱：
    当传感器停止更新（损坏/断电/通讯中断），最后上报的值被前向填充，
    形成一条平坦的"伪持续段"，掩盖了实际的数据缺失。

    本函数通过段持续时间检测这类异常：
    - 对每个工况状态，计算其持续时间分布
    - 超过 duration_threshold 分钟 或 p{percentile_threshold} 阈值的段被标记
    - 返回 _anomalous 标志列，供下游截断或排除

    Parameters
    ----------
    df : 重采样等间隔宽表（1min）
    cond_col : 工况列名
    duration_threshold : 绝对阈值（分钟），超过视为异常，默认 120
    percentile_threshold : 百分位阈值，默认 99%
    min_anomalous_duration : 至少持续此分钟才判定异常（避免短段误报），默认 60

    Returns
    -------
    pd.DataFrame
        列：[段起始时间, 段结束时间, 持续时间, 工况, 是否异常, 异常原因, 段索引, 分段号]
        每行 = 一个游程段。异常段标记在 _anomalous 列。
    """
    cond = df[cond_col].fillna("未知")
    values = cond.values
    n = len(values)
    if n == 0:
        return pd.DataFrame(columns=["段起始时间", "段结束时间", "持续时间(min)",
                                      "工况", "是否异常", "异常原因"])

    # 游程编码
    change_points = np.where(values[:-1] != values[1:])[0] + 1
    starts = np.concatenate([[0], change_points])
    ends = np.concatenate([change_points, [n]])
    run_lengths = ends - starts
    run_values = values[starts]
    run_index = np.arange(len(run_lengths))

    # 时间索引
    time_idx = df.index

    # 按状态计算各自的百分位阈值
    state_durations: dict[str, np.ndarray] = {}
    for state in np.unique(run_values):
        mask = run_values == state
        state_durations[str(state)] = run_lengths[mask]

    state_thresholds: dict[str, float] = {}
    for state, durations in state_durations.items():
        if len(durations) >= 5:
            p_thresh = float(np.percentile(durations, percentile_threshold))
            state_thresholds[state] = max(p_thresh, duration_threshold)
        else:
            state_thresholds[state] = float(duration_threshold)

    records = []
    for i in range(len(run_lengths)):
        dur = int(run_lengths[i])
        state = str(run_values[i])
        threshold = state_thresholds.get(state, duration_threshold)

        is_anomalous = False
        cause = "正常"
        if dur > threshold and dur >= min_anomalous_duration:
            is_anomalous = True
            # 判断是哪种原因
            if dur >= 360:  # 6小时以上：大概率断电/断线
                cause = "传感器断电/断线（段持续 >= 6h）"
            elif dur >= 240:
                cause = "通讯中断/传感器休眠（段持续 >= 4h）"
            else:
                cause = f"异常持续段（>{threshold:.0f}min 阈值）"

        seg_start = time_idx[starts[i]]
        seg_end = time_idx[ends[i] - 1]

        records.append({
            "段起始时间": seg_start,
            "段结束时间": seg_end,
            "持续时间(min)": dur,
            "工况": state,
            "是否异常": is_anomalous,
            "异常原因": cause,
            "段索引": int(run_index[i]),
        })

    result = pd.DataFrame(records)

    # 添加分段号（连续非异常段合并为一个分段号）
    result["分段号"] = (result["是否异常"] != result["是否异常"].shift(1)).cumsum()

    return result


def plot_anomalous_segments_timeline(
    df: pd.DataFrame,
    anomaly_result: pd.DataFrame,
    cond_col: str,
    output_path: str | Path | None = None,
) -> plt.Figure:
    """可视化异常段在时间轴上的分布。

    上子图：工况时间线，异常段用红色高亮
    下子图：段持续时间散点图，红线标记阈值
    """
    if anomaly_result.empty:
        fig, ax = plt.subplots(figsize=(8, 2))
        ax.text(0.5, 0.5, "无有效段数据", ha="center", va="center")
        return fig

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 6), sharex=True)

    # ── 上：工况时间线，异常段红色高亮 ──
    states = df[cond_col].fillna("未知").unique()
    state_to_int = {s: i for i, s in enumerate(states)}
    y_vals = df[cond_col].fillna("未知").map(state_to_int).values
    t_vals = df.index

    ax1.plot(t_vals, y_vals, color="#78909C", linewidth=0.5, alpha=0.6,
             drawstyle="steps-post")

    # 高亮异常段
    anomalous = anomaly_result[anomaly_result["是否异常"]]
    for _, seg in anomalous.iterrows():
        seg_start = pd.Timestamp(seg["段起始时间"])
        seg_end = pd.Timestamp(seg["段结束时间"])
        seg_state = state_to_int.get(seg["工况"], 0)
        ax1.axvspan(seg_start, seg_end, alpha=0.3, color="#E53935", zorder=0)

    ax1.set_yticks(range(len(states)))
    ax1.set_yticklabels(states, fontsize=8)
    ax1.set_ylabel("工况", fontsize=10)
    ax1.set_title(f"{cond_col} — 异常段检测（红色高亮）", fontsize=11)
    ax1.grid(True, alpha=0.2, axis="x")

    # ── 下：段持续时间散点 ──
    colors = anomaly_result["是否异常"].map({True: "#E53935", False: "#4CAF50"})
    sizes = anomaly_result["持续时间(min)"].clip(1, 200).values / 200 * 80 + 20
    ax2.scatter(
        anomaly_result["段起始时间"],
        anomaly_result["持续时间(min)"],
        c=colors, s=sizes, alpha=0.6, edgecolors="none",
    )

    # 标记阈值线
    duration_threshold = max(60, anomaly_result["持续时间(min)"].quantile(0.90))
    ax2.axhline(duration_threshold, color="#E53935", linestyle="--",
                linewidth=1, label=f"异常阈值 ≈ {duration_threshold:.0f}min")
    ax2.set_ylabel("段持续时间 (min)", fontsize=10)
    ax2.set_xlabel("时间", fontsize=10)
    ax2.legend(fontsize=8)
    ax2.grid(True, alpha=0.3)
    ax2.set_yscale("log")

    # 标注异常段占比
    total_segments = len(anomaly_result)
    anomalous_count = anomalous["持续时间(min)"].count()
    anomalous_duration = anomalous["持续时间(min)"].sum()
    total_duration = df.index[-1] - df.index[0]
    total_minutes = total_duration.total_seconds() / 60
    ax2.text(0.02, 0.95,
             f"异常段: {anomalous_count}/{total_segments} 段, "
             f"共 {anomalous_duration}min = {anomalous_duration / total_minutes * 100:.1f}% "
             f"({total_minutes / 60:.0f}h 总时长)",
             transform=ax2.transAxes, fontsize=9, verticalalignment="top",
             bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.8))

    fig.tight_layout()
    if output_path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(output_path, bbox_inches="tight", dpi=120)
    plt.close(fig)
    return fig


# ═══════════════════════════════════════════════════════════
# 数值异常检测：基于 IQR / 3σ 的工况内异常值检测
# ═══════════════════════════════════════════════════════════


def detect_value_anomalies(
    df: pd.DataFrame,
    cond_col: str,
    monitor_cols: list[str] | None = None,
    iqr_factor: float = 1.5,
    zscore_threshold: float = 3.0,
    min_consecutive: int = 3,
) -> pd.DataFrame:
    """检测各工况状态下的数值异常点（IQR + 3σ 双阈值，向量化实现）。

    对每个工况状态，分别计算各监测参数的统计边界：
    - IQR 法：超出 [Q1 - 1.5*IQR, Q3 + 1.5*IQR] 视为异常
    - 3σ 法：超出 [mean - 3*std, mean + 3*std] 视为异常
    - 任一方法触发即标记为异常

    Parameters
    ----------
    df : 重采样等间隔宽表
    cond_col : 工况列名
    monitor_cols : 待检测的监测参数列（默认从 config 读取）
    iqr_factor : IQR 倍数，默认 1.5
    zscore_threshold : z-score 阈值，默认 3.0
    min_consecutive : 最少连续异常分钟数才保留（避免单点噪声），默认 3

    Returns
    -------
    pd.DataFrame
        [时间, 参数, 工况, 实际值, Q1, Q3, 均值, 标准差,
         下限(IQR), 上限(IQR), 下限(3σ), 上限(3σ), 异常标志(IQR),
         异常标志(3σ), 异常标志(任意), z-score]
    """
    if monitor_cols is None:
        try:
            from src import config
            monitor_cols = [c for c in df.columns if c in config.CMJ_MONITOR_POINTS]
        except ImportError:
            monitor_cols = [c for c in df.columns if c not in [
                cond_col, "设备_工况", "截割部_工况", "牵引部_工况",
                "油泵_工况", "破碎机_工况", "时间",
            ]]

    numeric_cols = [c for c in monitor_cols if c in df.columns
                    and pd.api.types.is_numeric_dtype(df[c])]
    if not numeric_cols:
        return pd.DataFrame()

    cond = df[cond_col].fillna("未知")
    cond_values = cond.values
    time_idx = df.index

    # ── 预计算每个工况状态的统计边界（向量化） ──
    states_list = [s for s in cond.unique() if str(s) != "未知"]
    thresholds: dict[str, dict[str, dict]] = {}  # {state: {col: bounds}}
    for state in states_list:
        state = str(state)
        mask = (cond_values == state)
        thresholds[state] = {}
        for col in numeric_cols:
            vals = df[col].values[mask]
            valid = vals[~np.isnan(vals)]
            if len(valid) < 10:
                continue
            q1, q3 = np.percentile(valid, [25, 75])
            iqr = q3 - q1
            mean_v = float(np.mean(valid))
            std_v = float(np.std(valid))
            thresholds[state][col] = {
                "q1": q1, "q3": q3, "mean": mean_v, "std": std_v,
                "lower_iqr": q1 - iqr_factor * iqr,
                "upper_iqr": q3 + iqr_factor * iqr,
                "lower_3s": mean_v - zscore_threshold * std_v,
                "upper_3s": mean_v + zscore_threshold * std_v,
            }

    if not thresholds:
        return pd.DataFrame()

    # ── 向量化：逐 (col, state) 构建 DataFrame 块，pd.concat 合并 ──
    pieces: list[pd.DataFrame] = []
    for col in numeric_cols:
        col_vals = df[col].values
        for state, params in thresholds.items():
            if col not in params:
                continue
            p = params[col]
            mask = (cond_values == state)
            mask_nonan = mask & ~np.isnan(col_vals)
            if not mask_nonan.any():
                continue

            vals_sub = col_vals[mask_nonan]
            times_sub = time_idx[mask_nonan]

            std_v = p["std"]
            z_scores = np.where(std_v > 0, (vals_sub - p["mean"]) / std_v, 0.0)
            flag_iqr = (vals_sub < p["lower_iqr"]) | (vals_sub > p["upper_iqr"])
            flag_3s = (vals_sub < p["lower_3s"]) | (vals_sub > p["upper_3s"])
            flag_any = flag_iqr | flag_3s

            # 整块构建，不走 Python 逐行 append
            piece = pd.DataFrame({
                "时间": times_sub,
                "参数": col,
                "工况": state,
                "实际值": vals_sub,
                "均值": p["mean"],
                "标准差": p["std"],
                "Q1": p["q1"],
                "Q3": p["q3"],
                "下限(IQR)": p["lower_iqr"],
                "上限(IQR)": p["upper_iqr"],
                "下限(3σ)": p["lower_3s"],
                "上限(3σ)": p["upper_3s"],
                "z-score": z_scores,
                "异常(IQR)": flag_iqr,
                "异常(3σ)": flag_3s,
                "异常(任意)": flag_any,
            })
            pieces.append(piece)

    if not pieces:
        return pd.DataFrame()

    result = pd.concat(pieces, ignore_index=True)

    # ── 合并连续异常段（降噪，向量化） ──
    result = result.sort_values(["参数", "工况", "时间"])
    result["_gap"] = result.groupby(["参数", "工况", "异常(任意)"], sort=False)["时间"].diff().dt.total_seconds() / 60
    result["_new_block"] = (result["_gap"].fillna(999) > 3) | (~result["异常(任意)"])
    result["_block_id"] = result.groupby(["参数", "工况"], sort=False)["_new_block"].cumsum()

    block_sizes = result.groupby(["参数", "工况", "_block_id"], sort=False)["异常(任意)"].sum().reset_index()
    block_sizes = block_sizes[block_sizes["异常(任意)"] >= min_consecutive]
    keep_blocks = set(zip(block_sizes["参数"], block_sizes["工况"], block_sizes["_block_id"]))

    # 向量化 MultiIndex isin，替代 iterrows 逐行判重（结果可达数十万行）
    block_index = pd.MultiIndex.from_frame(result[["参数", "工况", "_block_id"]])
    keep_index = pd.MultiIndex.from_tuples(list(keep_blocks))
    result["异常(短段过滤)"] = result["异常(任意)"].values & block_index.isin(keep_index)

    result = result.drop(columns=["_gap", "_new_block", "_block_id"])

    # ── 严重程度（向量化） ──
    z_abs = result["z-score"].abs()
    result["严重程度"] = "正常"
    result.loc[result["异常(短段过滤)"] & (z_abs >= 5), "严重程度"] = "严重"
    result.loc[result["异常(短段过滤)"] & (z_abs >= 4) & (z_abs < 5), "严重程度"] = "较重"
    result.loc[result["异常(短段过滤)"] & (z_abs >= 3) & (z_abs < 4), "严重程度"] = "一般"
    result.loc[result["异常(短段过滤)"] & (z_abs >= 0) & (z_abs < 3), "严重程度"] = "轻微"

    return result


def plot_value_anomalies_timeline(
    df: pd.DataFrame,
    anomaly_result: pd.DataFrame,
    cond_col: str,
    n_top_params: int = 8,
    output_path: str | Path | None = None,
) -> plt.Figure:
    """可视化异常数据在时间轴上的分布。

    上子图：异常参数数量密度（每个时间点多少个参数被标记为异常）
    下子图：Top-N 参数的时间序列 + 异常点高亮
    """
    if anomaly_result.empty:
        fig, ax = plt.subplots(figsize=(10, 3))
        ax.text(0.5, 0.5, "无异常数据", ha="center", va="center")
        return fig

    # ── 按参数统计异常最多的 Top-N ──
    param_anomaly_counts = (
        anomaly_result[anomaly_result["异常(短段过滤)"]]
        .groupby("参数")["异常(短段过滤)"]
        .sum()
        .sort_values(ascending=False)
    )
    top_params = param_anomaly_counts.head(n_top_params).index.tolist()

    # ── 每个时间点的异常参数数量 ──
    time_anomaly_count = (
        anomaly_result[anomaly_result["异常(短段过滤)"]]
        .groupby("时间")["参数"]
        .nunique()
    )

    fig, axes = plt.subplots(
        2, 1, figsize=(14, 3 + len(top_params) * 0.9),
        gridspec_kw={"height_ratios": [1, len(top_params)]},
        sharex=True,
    )
    ax_top, ax_series = axes

    # ── 上：异常密度 ──
    ax_top.fill_between(
        time_anomaly_count.index,
        time_anomaly_count.values,
        alpha=0.4, color="#E53935", step="mid",
    )
    ax_top.plot(
        time_anomaly_count.index,
        time_anomaly_count.values,
        color="#C62828", linewidth=0.8, drawstyle="steps-mid",
    )
    ax_top.set_ylabel("异常参数数", fontsize=9)
    ax_top.set_title(
        f"{cond_col} — 数值异常检测 "
        f"（{len(param_anomaly_counts)} 参数, "
        f"{int(time_anomaly_count.sum())} 异常点）",
        fontsize=11,
    )
    ax_top.grid(True, alpha=0.2)
    ax_top.set_xlim(df.index[0], df.index[-1])

    # ── 下：Top-N 参数时间序列 ──
    for i, param in enumerate(top_params):
        ax = axes[1] if len(top_params) == 1 else axes[1]
        ax_i = i  # will use offset

    # 使用 Twin 轴不适合堆叠，改成在一个子图上用偏移堆叠
    ax_series.set_prop_cycle(None)  # reset color cycle

    # 归一化每个参数再堆叠
    param_data = {}
    for param in top_params:
        if param in df.columns:
            vals = df[param].values
            if np.nanstd(vals) > 0:
                normalized = (vals - np.nanmean(vals)) / np.nanstd(vals)
            else:
                normalized = np.zeros_like(vals)
            param_data[param] = normalized

    # 绘制堆叠时间序列
    n_display = len(param_data)
    if n_display == 0:
        ax_series.text(0.5, 0.5, "无有效参数数据", ha="center", va="center")
    else:
        offset = 0
        yticks = []
        yticklabels = []
        for idx, (param, normalized) in enumerate(param_data.items()):
            y_vals = normalized + offset * 6
            ax_series.plot(df.index, y_vals, linewidth=0.5, alpha=0.7,
                           label=_shorten_name(param))

            # 高亮异常点
            param_anom = anomaly_result[
                (anomaly_result["参数"] == param) &
                (anomaly_result["异常(短段过滤)"])
            ]
            if not param_anom.empty:
                anom_times = param_anom["时间"].values
                anom_vals = np.full(len(anom_times), offset * 6)
                # 获取实际 z-score 值做颜色映射
                z_scores = param_anom["z-score"].abs().values
                severity_colors = []
                for z in z_scores:
                    if z >= 5:
                        severity_colors.append("#B71C1C")
                    elif z >= 4:
                        severity_colors.append("#E53935")
                    elif z >= 3:
                        severity_colors.append("#FF8A80")
                    else:
                        severity_colors.append("#FFCDD2")
                ax_series.scatter(
                    anom_times, anom_vals,
                    c=severity_colors, s=3, alpha=0.6, edgecolors="none",
                )

            yticks.append(offset * 6)
            yticklabels.append(_shorten_name(param))
            offset += 1

        ax_series.set_yticks(yticks)
        ax_series.set_yticklabels(yticklabels, fontsize=7)
        ax_series.set_ylabel("参数 (z-score 堆叠)", fontsize=9)

    ax_series.set_xlabel("时间", fontsize=9)
    ax_series.grid(True, alpha=0.2)

    # 全局图例
    from matplotlib.patches import Patch
    legend_elements = [
        Patch(facecolor="#B71C1C", label="严重 (|z|≥5)"),
        Patch(facecolor="#E53935", label="较重 (4≤|z|<5)"),
        Patch(facecolor="#FF8A80", label="一般 (3≤|z|<4)"),
    ]
    ax_top.legend(handles=legend_elements, fontsize=7, loc="upper right",
                  ncol=3, framealpha=0.8)

    fig.tight_layout()
    if output_path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(output_path, bbox_inches="tight", dpi=130)
    plt.close(fig)
    return fig


def _shorten_name(col: str, max_len: int = 20) -> str:
    """截短列名用于图例显示。"""
    for prefix in ["采煤机_", "三机_"]:
        if col.startswith(prefix):
            col = col[len(prefix):]
            break
    if len(col) > max_len:
        parts = col.split("_")
        # 取最后三段
        if len(parts) > 3:
            col = "_".join(parts[-3:])
        else:
            col = col[:max_len]
    return col


def compute_all_part_value_anomalies(
    df: pd.DataFrame,
    output_dir: str | Path,
    part_cols: list[str] | None = None,
    monitor_cols: list[str] | None = None,
    iqr_factor: float = 1.5,
    zscore_threshold: float = 3.0,
    min_consecutive: int = 3,
) -> dict[str, pd.DataFrame]:
    """为所有部位运行数值异常检测，输出 CSV + 可视化。

    Parameters
    ----------
    monitor_cols : 监测参数列（默认自动检测 CMJ_MONITOR_POINTS）。

    Returns
    -------
    dict[str, pd.DataFrame] — { 列名: 数值异常检测结果 }
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if part_cols is None:
        part_cols = ["设备_工况", "截割部_工况", "牵引部_工况",
                      "油泵_工况", "破碎机_工况"]

    all_results = {}
    for col in part_cols:
        if col not in df.columns:
            continue
        print(f"\n  数值异常检测: {col}")
        anomaly = detect_value_anomalies(
            df, col, monitor_cols=monitor_cols,
            iqr_factor=iqr_factor,
            zscore_threshold=zscore_threshold,
            min_consecutive=min_consecutive,
        )
        if anomaly.empty:
            print(f"    无数据")
            continue

        safe_name = col.replace("_", "_")

        # CSV（全量明细）
        csv_path = output_dir / f"value_anomalies_{safe_name}.csv"
        anomaly.to_csv(csv_path, index=False, encoding="utf-8-sig")
        all_results[col] = anomaly
        print(f"    CSV: {csv_path}")

        # 汇总
        n_anom = anomaly["异常(短段过滤)"].sum()
        total = len(anomaly)
        n_severe = (anomaly["严重程度"] == "严重").sum()
        n_moderate = (anomaly["严重程度"] == "较重").sum()
        n_mild = (anomaly["严重程度"] == "一般").sum()
        print(f"    异常点: {n_anom}/{total} = {n_anom / total * 100:.1f}%"
              f"（严重 {n_severe}, 较重 {n_moderate}, 一般 {n_mild}）")

        # 可视化
        png_path = output_dir / f"value_anomalies_{safe_name}.png"
        plot_value_anomalies_timeline(
            df, anomaly, col, n_top_params=8, output_path=png_path,
        )
        print(f"    异常图: {png_path}")

    return all_results


# ═══════════════════════════════════════════════════════════
# 旧版：持续段异常检测（保留向后兼容）
# ═══════════════════════════════════════════════════════════


def compute_all_part_anomalous_segments(
    df: pd.DataFrame,
    output_dir: str | Path,
    part_cols: list[str] | None = None,
    duration_threshold: int = 120,
    percentile_threshold: float = 99.0,
) -> dict[str, pd.DataFrame]:
    """为所有部位检测异常持续段，输出 CSV + 可视化。

    Returns
    -------
    dict[str, pd.DataFrame] — { 列名: 异常段检测结果 }
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if part_cols is None:
        part_cols = ["设备_工况", "截割部_工况", "牵引部_工况",
                      "油泵_工况", "破碎机_工况"]

    results = {}
    for col in part_cols:
        if col not in df.columns:
            continue
        print(f"\n  持续段异常检测: {col}")
        anomaly = detect_anomalous_segments(
            df, col,
            duration_threshold=duration_threshold,
            percentile_threshold=percentile_threshold,
        )
        if not anomaly.empty:
            safe_name = col.replace("_", "_")
            csv_path = output_dir / f"anomalous_segments_{safe_name}.csv"
            anomaly.to_csv(csv_path, index=False, encoding="utf-8-sig")
            results[col] = anomaly
            print(f"    CSV: {csv_path}")

            # 可视化
            png_path = output_dir / f"anomalous_segments_{safe_name}.png"
            plot_anomalous_segments_timeline(df, anomaly, col, output_path=png_path)
            print(f"    异常段图: {png_path}")

            # 汇总
            n_total = len(anomaly)
            n_anom = anomaly["是否异常"].sum()
            dur_anom = anomaly.loc[anomaly["是否异常"], "持续时间(min)"].sum()
            total_min = len(df)
            print(f"    异常: {n_anom}/{n_total} 段 = {n_anom / n_total * 100:.1f}%, "
                  f"合计 {dur_anom}/{total_min} min = {dur_anom / total_min * 100:.1f}%")
        else:
            print(f"    无数据")

    return results
