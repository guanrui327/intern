# -*- coding: utf-8 -*-
"""CSV 读取、清洗与 on-change 重采样。"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

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
