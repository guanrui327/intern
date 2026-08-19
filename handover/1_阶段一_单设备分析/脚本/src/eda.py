# -*- coding: utf-8 -*-
"""探索性数据分析与报告生成。"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from . import config
from .preprocess import build_wide_from_csv, summarize_csv


def _format_points_table(points: list[dict], exclude: set[str] | None = None) -> str:
    """生成 Markdown 测点统计表。"""
    exclude = exclude or set()
    lines = [
        "| 测点 | 记录数 | 最小值 | 最大值 | 均值 | 是否保留 |",
        "| --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for item in points:
        keep = "否" if item["point_name"] in exclude else "是"
        lines.append(
            f"| {item['point_name']} | {item['count']} | "
            f"{item['value_min']:.4g} | {item['value_max']:.4g} | "
            f"{item['value_mean']:.4g} | {keep} |"
        )
    return "\n".join(lines)


def build_overview_report(output_dir: Path | str | None = None) -> Path:
    """扫描两台设备 CSV，生成 EDA 概览报告。"""
    output_dir = Path(output_dir or config.OUTPUT_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)

    cmj_summary = summarize_csv(config.CMJ_CSV)
    zzj_summary = summarize_csv(config.ZZJ_CSV)

    report_lines = [
        "# 采煤机 + 转载机 数据 EDA 概览",
        "",
        "## 1. 数据文件概况",
        "",
        "| 设备 | 文件大小(MB) | 行数 | 测点数 | 起始时间 | 结束时间 |",
        "| --- | ---: | ---: | ---: | --- | --- |",
        f"| 采煤机 | {cmj_summary['file_size_mb']} | {cmj_summary['rows']} | "
        f"{cmj_summary['point_count']} | {cmj_summary['time_start']} | {cmj_summary['time_end']} |",
        f"| 转载机 | {zzj_summary['file_size_mb']} | {zzj_summary['rows']} | "
        f"{zzj_summary['point_count']} | {zzj_summary['time_start']} | {zzj_summary['time_end']} |",
        "",
        "> 说明：数据为 on-change 存储，同一测点仅在数值变化时落库。",
        "",
        "## 2. 采煤机测点统计",
        "",
        _format_points_table(cmj_summary["points"], config.CMJ_EXCLUDE_POINTS),
        "",
        "## 3. 转载机测点统计",
        "",
        _format_points_table(zzj_summary["points"]),
        "",
        "## 4. 阶段一建议使用的测点",
        "",
        "### 采煤机工况状态量",
        "",
    ]
    report_lines.extend(f"- {p}" for p in config.CMJ_STATE_POINTS)
    report_lines.extend(["", "### 采煤机监测参数", ""])
    report_lines.extend(f"- {p}" for p in config.CMJ_MONITOR_POINTS)
    report_lines.extend(["", "### 转载机工况状态量", ""])
    report_lines.extend(f"- {p}" for p in config.ZZJ_STATE_POINTS)
    report_lines.extend(["", "### 转载机监测参数", ""])
    report_lines.extend(f"- {p}" for p in config.ZZJ_MONITOR_POINTS)
    report_lines.extend(
        [
            "",
            "## 5. 下一步",
            "",
            "1. 运行 `python run_resample.py` 生成 1 分钟宽表（parquet）。",
            "2. 基于状态量划分工况（停机 / 运行 / 割煤 / 调架等）。",
            "3. 分工况统计监测参数分布并出图。",
            "",
        ]
    )

    report_path = output_dir / "eda_overview.md"
    report_path.write_text("\n".join(report_lines), encoding="utf-8")

    summary_json = output_dir / "eda_summary.json"
    summary_json.write_text(
        json.dumps({"cmj": cmj_summary, "zzj": zzj_summary}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return report_path


def resample_device(
    device: str,
    csv_path: Path,
    state_points: list[str],
    monitor_points: list[str],
    output_dir: Path,
    freq: str = config.DEFAULT_RESAMPLE_FREQ,
) -> Path:
    """读取关键测点并重采样，保存 parquet。"""
    points = list(dict.fromkeys(state_points + monitor_points))
    df_wide = build_wide_from_csv(csv_path, points, freq=freq)
    output_path = output_dir / f"{device}_wide_{freq}.parquet"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df_wide.to_parquet(output_path)
    return output_path
