# -*- coding: utf-8 -*-
"""CSV 读取、清洗与 on-change 重采样。"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .config import CHUNK_SIZE, DEFAULT_RESAMPLE_FREQ


def iter_chunks(
    csv_path: Path | str,
    points: Iterable[str] | None = None,
    chunksize: int = CHUNK_SIZE,
) -> Iterable[pd.DataFrame]:
    """分块读取 CSV，仅保留 point_name / value / time。"""
    point_set = set(points) if points is not None else None
    for chunk in pd.read_csv(
        csv_path,
        usecols=["point_name", "value", "time"],
        chunksize=chunksize,
    ):
        chunk["time"] = pd.to_datetime(chunk["time"])
        if point_set is not None:
            chunk = chunk[chunk["point_name"].isin(point_set)]
            if chunk.empty:
                continue
        yield chunk


def summarize_csv(csv_path: Path | str, chunksize: int = CHUNK_SIZE) -> dict:
    """扫描整表，输出基础统计信息。"""
    path = Path(csv_path)
    point_counts: dict[str, int] = {}
    value_stats: dict[str, dict[str, float]] = {}
    t_min = t_max = None
    rows = 0

    for chunk in iter_chunks(path, chunksize=chunksize):
        rows += len(chunk)
        cmin, cmax = chunk["time"].min(), chunk["time"].max()
        t_min = cmin if t_min is None else min(t_min, cmin)
        t_max = cmax if t_max is None else max(t_max, cmax)

        for point, cnt in chunk["point_name"].value_counts().items():
            point_counts[point] = point_counts.get(point, 0) + int(cnt)

        grouped = chunk.groupby("point_name")["value"]
        for point, series in grouped:
            stats = value_stats.setdefault(
                point,
                {"min": np.inf, "max": -np.inf, "sum": 0.0, "count": 0},
            )
            stats["min"] = min(stats["min"], float(series.min()))
            stats["max"] = max(stats["max"], float(series.max()))
            stats["sum"] += float(series.sum())
            stats["count"] += int(series.count())

    point_summary = []
    for point, count in sorted(point_counts.items(), key=lambda x: x[0]):
        stats = value_stats[point]
        mean = stats["sum"] / stats["count"] if stats["count"] else np.nan
        point_summary.append(
            {
                "point_name": point,
                "count": count,
                "value_min": stats["min"],
                "value_max": stats["max"],
                "value_mean": mean,
            }
        )

    return {
        "file": str(path),
        "file_size_mb": round(path.stat().st_size / 1024 / 1024, 2),
        "rows": rows,
        "point_count": len(point_counts),
        "time_start": None if t_min is None else str(t_min),
        "time_end": None if t_max is None else str(t_max),
        "points": point_summary,
    }


def load_selected_long(
    csv_path: Path | str,
    points: Iterable[str],
    chunksize: int = CHUNK_SIZE,
) -> pd.DataFrame:
    """读取指定测点的长表数据。"""
    parts = [chunk for chunk in iter_chunks(csv_path, points=points, chunksize=chunksize)]
    if not parts:
        return pd.DataFrame(columns=["point_name", "value", "time"])
    df = pd.concat(parts, ignore_index=True)
    return df.sort_values(["point_name", "time"]).reset_index(drop=True)


def build_wide_from_csv(
    csv_path: Path | str,
    points: Iterable[str],
    freq: str = DEFAULT_RESAMPLE_FREQ,
    chunksize: int = CHUNK_SIZE,
) -> pd.DataFrame:
    """单次扫描 CSV，逐测点重采样，避免重复读盘。"""
    point_list = list(dict.fromkeys(points))
    point_set = set(point_list)
    buffers: dict[str, list[pd.DataFrame]] = {p: [] for p in point_list}

    for chunk in iter_chunks(csv_path, points=point_set, chunksize=chunksize):
        for point, sub in chunk.groupby("point_name"):
            buffers[point].append(sub[["time", "value"]])

    series_list: list[pd.Series] = []
    for point in point_list:
        parts = buffers.get(point) or []
        if not parts:
            continue
        sub = pd.concat(parts, ignore_index=True)
        series = (
            sub.drop_duplicates(subset=["time"], keep="last")
            .set_index("time")["value"]
            .sort_index()
            .rename(point)
        )
        series_list.append(series)

    if not series_list:
        return pd.DataFrame()

    wide = pd.concat(series_list, axis=1).sort_index().ffill()
    return wide.resample(freq).last().ffill()


def long_to_wide_onchange(
    df_long: pd.DataFrame,
    freq: str = DEFAULT_RESAMPLE_FREQ,
) -> pd.DataFrame:
    """
    将 on-change 长表转为等间隔宽表。
    每个测点按变化记录展开，再前向填充并重采样。
    """
    if df_long.empty:
        return pd.DataFrame()

    wide_parts = []
    for point, sub in df_long.groupby("point_name"):
        series = (
            sub.drop_duplicates(subset=["time"], keep="last")
            .set_index("time")["value"]
            .sort_index()
        )
        wide_parts.append(series.rename(point))

    wide = pd.concat(wide_parts, axis=1).sort_index()
    # 先按原始时间轴前向填充，再重采样取末值
    wide = wide.ffill()
    resampled = wide.resample(freq).last().ffill()
    return resampled


def save_wide_parquet(df_wide: pd.DataFrame, output_path: Path | str) -> Path:
    """保存宽表，便于后续快速加载。"""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df_wide.to_parquet(output_path)
    return output_path


# ---------------------------------------------------------------------------
# 数据空洞检测
# ---------------------------------------------------------------------------

def detect_and_filter_outliers(
    df: pd.DataFrame,
    method: str = "iqr",
    iqr_multiplier: float = 1.5,
    sigma_threshold: float = 3.0,
    inplace: bool = False,
    report: bool = True,
) -> pd.DataFrame:
    """宽表野值检测与清洗：IQR / 3σ / 两者组合。

    将超出边界的值替换为 NaN（后续前向填充自动覆盖），
    返回清洗统计报告。

    Parameters
    ----------
    df : 等间隔宽表（1min DatetimeIndex），仅计算数值列
    method : 'iqr' | 'sigma' | 'both'
        'iqr'  — 1.5×IQR 超出 Q1/Q3
        'sigma' — 均值 ± 3σ
        'both'  — 两者取交集（更保守，只清掉两边都标记的）
    iqr_multiplier : IQR 倍数，默认 1.5
    sigma_threshold : σ 倍数，默认 3.0
    inplace : 是否原地修改 df
    report : 是否打印统计报告

    Returns
    -------
    pd.DataFrame
        清洗统计报告 [列名, 总数, 有效数, 野值数, 野值占比%, 方法]
        若 inplace=True，同时修改原 DataFrame 的值
    """
    numeric_cols = [c for c in df.columns
                    if pd.api.types.is_numeric_dtype(df[c])]
    report_rows = []

    for col in numeric_cols:
        vals = df[col].values
        n_total = len(vals)
        valid = vals[~np.isnan(vals)]
        if len(valid) < 20:  # 样本太少不洗
            continue

        q1, q3 = np.percentile(valid, [25, 75])
        iqr = q3 - q1
        mean_v = float(np.mean(valid))
        std_v = float(np.std(valid))

        if method == "iqr":
            lower = q1 - iqr_multiplier * iqr
            upper = q3 + iqr_multiplier * iqr
        elif method == "sigma":
            lower = mean_v - sigma_threshold * std_v
            upper = mean_v + sigma_threshold * std_v
        else:  # both
            lower_i = q1 - iqr_multiplier * iqr
            upper_i = q3 + iqr_multiplier * iqr
            lower_s = mean_v - sigma_threshold * std_v
            upper_s = mean_v + sigma_threshold * std_v
            lower = max(lower_i, lower_s)
            upper = min(upper_i, upper_s)

        outlier_mask = (vals < lower) | (vals > upper)
        # 排除原本就是 NaN 的点
        outlier_mask = outlier_mask & ~np.isnan(vals)
        n_outliers = int(outlier_mask.sum())
        pct = n_outliers / n_total * 100 if n_total > 0 else 0.0

        if inplace and n_outliers > 0:
            df.loc[outlier_mask, col] = np.nan

        report_rows.append({
            "列名": col,
            "总数": n_total,
            "有效数": int(n_total - np.isnan(vals).sum()),
            "野值数": n_outliers,
            "野值占比%": round(pct, 3),
            "方法": method,
            "下限": round(lower, 4),
            "上限": round(upper, 4),
        })

    result = pd.DataFrame(report_rows)

    if report and not result.empty:
        total_outliers = result["野值数"].sum()
        print(f"  野值清洗 [{method}]: 共 {total_outliers} 个值被标记为 NaN "
              f"（{len(result)} 列中有野值），占比 {total_outliers/ (result['总数'].sum() or 1) * 100:.3f}%")
        # 打印列名含 "电流" 或 "温度" 的 top 野值列
        key_cols = result[result["列名"].str.contains("电流|温度|速度|油压")]
        if not key_cols.empty:
            for _, row in key_cols.head(10).iterrows():
                if row["野值数"] > 0:
                    print(f"    {row['列名']}: {row['野值数']} 个野值 ({row['野值占比%']:.2f}%)  "
                          f"边界 [{row['下限']:.1f}, {row['上限']:.1f}]")

    return result


def detect_data_gaps(
    df: pd.DataFrame,
    value_cols: list[str],
    gap_threshold: int = 120,
) -> pd.DataFrame:
    """检测宽表中连续相同值超过阈值的游程（潜在数据空洞）。

    on-change 数据长时间无更新可能意味着传感器损坏或断电。
    本函数通过在重采样后的 1min 宽表中扫描连续相同值的游程，
    标记长度 ≥ *gap_threshold* 分钟的区间。

    Parameters
    ----------
    df :
        已重采样到等间隔（如 1min）的宽表。
    value_cols :
        要扫描的监测参数列名列表。
    gap_threshold :
        空洞判定阈值（分钟），默认 120（2 小时）。

    Returns
    -------
    pd.DataFrame
        空洞汇总表，列: [列名, 起始时间, 结束时间, 持续时长(分钟)]
    """
    records: list[dict] = []

    for col in value_cols:
        if col not in df.columns:
            continue
        series = df[col]
        values = series.values
        n = len(values)

        # 通过 diff != 0 定位变化点
        diffs = np.diff(values, prepend=values[0] + 1)  # 首元素不视为变化
        change_idx = np.where(diffs != 0)[0]

        # 计算游程长度（插入末尾哨兵）
        run_ends = np.concatenate([change_idx, [n]])
        run_starts = np.concatenate([[0], change_idx])
        run_lengths = run_ends - run_starts

        # 筛选超过阈值的游程
        for start, length in zip(run_starts, run_lengths):
            if length >= gap_threshold:
                end = min(start + length - 1, n - 1)
                records.append({
                    "列名": col,
                    "起始时间": series.index[start],
                    "结束时间": series.index[end],
                    "持续时长(分钟)": int(length),
                })

    if not records:
        return pd.DataFrame(columns=["列名", "起始时间", "结束时间", "持续时长(分钟)"])

    return pd.DataFrame(records).sort_values(["列名", "起始时间"]).reset_index(drop=True)


def plot_gap_overview(
    df: pd.DataFrame,
    value_cols: list[str],
    gap_threshold: int = 120,
    *,
    gaps: pd.DataFrame | None = None,
    title: str = "数据空洞概览（连续不变 >N min）",
    output_path: str | Path | None = None,
) -> plt.Figure:
    """绘制数据空洞热力图。

    Y 轴为监测参数，X 轴为时间，每个参数一行，
    空洞区间用红色/橙色方块标注（按时长着色），
    绿色区域表示正常更新。

    可传入预计算的 gaps DataFrame 避免重复空洞检测。
    """
    from matplotlib.patches import Rectangle
    from matplotlib.colors import LinearSegmentedColormap

    # 先检测空洞（允许传入预计算结果避免重复）
    if gaps is None:
        gaps = detect_data_gaps(df, value_cols, gap_threshold)
    n_params = len(value_cols)

    fig, ax = plt.subplots(figsize=(16, max(4, n_params * 0.4)))
    t_min, t_max = df.index.min(), df.index.max()
    total_days = (t_max - t_min).total_seconds() / 86400

    # 为每个参数绘制基线（绿色/正常）
    for i, col in enumerate(value_cols):
        ax.add_patch(Rectangle(
            (t_min, i - 0.4), t_max - t_min, 0.8,
            facecolor="#e8f5e9", edgecolor="none",
        ))

    # 空洞用红色标注（按时长着色深浅）
    if not gaps.empty:
        max_gap = gaps["持续时长(分钟)"].max()
        for _, row in gaps.iterrows():
            if row["列名"] not in value_cols:
                continue
            i = value_cols.index(row["列名"])
            duration = row["持续时长(分钟)"]
            intensity = min(duration / max_gap, 1.0) if max_gap > 0 else 0.5
            red = (1.0, 1.0 - intensity * 0.7, 1.0 - intensity * 0.7)
            ax.add_patch(Rectangle(
                (row["起始时间"], i - 0.4),
                row["结束时间"] - row["起始时间"], 0.8,
                facecolor=red, edgecolor="#b71c1c", linewidth=0.3,
                alpha=0.8,
            ))

    ax.set_yticks(range(n_params))
    ax.set_yticklabels([_short_label(c) for c in value_cols], fontsize=7)
    ax.set_xlim(t_min, t_max)
    ax.set_ylim(-0.5, n_params - 0.5)
    ax.set_title(f"{title}（阈值={gap_threshold}min，共{total_days:.0f}天）", fontsize=11)
    ax.xaxis.set_major_formatter(plt.matplotlib.dates.DateFormatter("%m-%d"))
    fig.autofmt_xdate()

    # 图例
    from matplotlib.patches import Patch
    legend_elements = [
        Patch(facecolor="#e8f5e9", label="数据正常"),
        Patch(facecolor="#ff6b6b", label=f"空洞(>{gap_threshold}min)"),
    ]
    ax.legend(handles=legend_elements, loc="upper right", fontsize=8)

    fig.tight_layout()
    if output_path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(output_path, bbox_inches="tight", dpi=120)
    return fig


# ---------------------------------------------------------------------------
# 点位覆盖统计
# ---------------------------------------------------------------------------

def compute_point_coverage(
    df: pd.DataFrame,
    output_path: str | Path | None = None,
) -> pd.DataFrame:
    """计算宽表中每个监测点的数据覆盖率。

    对每个数值列统计：
      - 总记录数（等于 df 行数）
      - 有效（非空）记录数
      - 有效比例
      - 有效数据最早 / 最晚时间

    Parameters
    ----------
    df : 等间隔宽表
    output_path : 可选的 CSV 输出路径

    Returns
    -------
    pd.DataFrame
        [列名, 总记录数, 有效记录数, 有效比例, 最早时间, 最晚时间, 时间跨度(天)]
    """
    total = len(df)
    records = []
    for col in df.columns:
        non_null = df[col].notna()
        valid = non_null.sum()
        first_valid = df.index[non_null].min() if valid > 0 else None
        last_valid = df.index[non_null].max() if valid > 0 else None
        span_days = (last_valid - first_valid).total_seconds() / 86400 if first_valid and last_valid else 0.0
        records.append({
            "列名": col,
            "总记录数": total,
            "有效记录数": int(valid),
            "有效比例": round(valid / total, 4) if total > 0 else 0.0,
            "最早时间": str(first_valid) if first_valid else "",
            "最晚时间": str(last_valid) if last_valid else "",
            "时间跨度(天)": round(span_days, 2),
        })

    result = pd.DataFrame(records)
    if output_path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        result.to_csv(output_path, index=False, encoding="utf-8-sig")
        print(f"  点位覆盖表: {output_path}")
    return result


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
