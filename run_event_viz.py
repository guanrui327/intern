# -*- coding: utf-8 -*-
"""任务 4：具体异常事件可视化入口（独立脚本，不侵入阶段二 pipeline）。

从 output/phase2/anomalies/*_merged_events.csv（merge_anomaly_events 长表）
+ 阶段一原始宽表（output/phase1/*_with_condition.parquet）出发：

1. 按连续 any_anomaly 时间戳分组 → 结构化"异常事件"（起止 / 时长 / 工况 /
   方法集 / 严重度 / 归因摘要）→ *_events.csv
2. 按时长 × log1p(严重度) 取 Top-N 代表事件 → *_event_XXX.png
   （±30min 窗口原始参数 z-score 归一堆叠 + 红色高亮异常区间 + 工况条）
3. 汇总 anomaly_events_summary.md

覆盖当前 pipeline 的 5 组产物：
  CMJ 分部位 4 组（截割部 / 牵引部 / 油泵 / 破碎机）
  ZZJ 设备级 1 组

用法：python run_event_viz.py
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src import config
from src.anomaly_event_viz import (
    build_anomaly_events,
    plot_event_window,
    select_top_events,
)

# 部位关键词过滤（与 run_phase2._filter_part_monitor_cols 同逻辑）
_PART_KEYWORDS = {
    "截割部": ["滚筒", "电机_电流", "电机_温度", "角度"],
    "牵引部": ["牵引", "电机_电流", "电机_温度", "速度"],
    "油泵":   ["油泵", "电流", "温度", "油压"],
    "破碎机": ["破碎机", "电流", "温度"],
}

# 5 组产物 specs
SPECS = [
    {"prefix": "cmj_截割部", "cond_col": "截割部_工况", "part_key": "截割部",
     "device": "cmj"},
    {"prefix": "cmj_牵引部", "cond_col": "牵引部_工况", "part_key": "牵引部",
     "device": "cmj"},
    {"prefix": "cmj_油泵", "cond_col": "油泵_工况", "part_key": "油泵",
     "device": "cmj"},
    {"prefix": "cmj_破碎机", "cond_col": "破碎机_工况", "part_key": "破碎机",
     "device": "cmj"},
    {"prefix": "zzj", "cond_col": "工况", "part_key": None,
     "device": "zzj"},
]


def _load_raw(device: str) -> pd.DataFrame:
    """加载阶段一带工况宽表（DatetimeIndex）。"""
    path = config.PHASE1_DIR / f"{device}_with_condition.parquet"
    df = pd.read_parquet(path)
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)
    return df


def _select_monitor_cols(raw: pd.DataFrame, spec: dict) -> list[str]:
    """按部位选择监测参数列。

    - ZZJ：直接取 config.ZZJ_MONITOR_POINTS 中存在的列
    - CMJ 分部位：先取 config.CMJ_MONITOR_POINTS 存在列，再按关键词过滤
    """
    if spec["device"] == "zzj":
        return [c for c in raw.columns if c in config.ZZJ_MONITOR_POINTS]
    cmj_all = [c for c in raw.columns if c in config.CMJ_MONITOR_POINTS]
    kws = _PART_KEYWORDS.get(spec["part_key"], [])
    if not kws:
        return cmj_all
    return [c for c in cmj_all if any(kw in c for kw in kws)]


def main() -> None:
    out_dir = config.PHASE2_DIR / "anomaly_events"
    out_dir.mkdir(parents=True, exist_ok=True)

    # 缓存宽表
    raw_cache: dict[str, pd.DataFrame] = {}
    summary: list[str] = []
    summary.append("# 具体异常事件可视化汇总\n")
    summary.append("覆盖当前 phase2 pipeline 的 5 组产物。"
                   "事件 = 连续 any_anomaly 时间戳分组（相邻间隔 > 1min 断开）。\n")

    for spec in SPECS:
        prefix = spec["prefix"]
        merged_path = config.PHASE2_DIR / "anomalies" / f"{prefix}_merged_events.csv"
        if not merged_path.exists():
            print(f"[跳过] 缺少 {merged_path.name}")
            continue

        print(f"\n{'=' * 60}\n处理: {prefix}\n{'=' * 60}")
        merged = pd.read_csv(merged_path)
        if merged.empty:
            print("  merged_events 为空，跳过")
            continue

        # 1. 事件结构化
        events = build_anomaly_events(merged)
        events_csv = out_dir / f"{prefix}_events.csv"
        events.to_csv(events_csv, index=False, encoding="utf-8-sig")
        print(f"  事件数: {len(events)}  -> {events_csv.name}")

        # 2. Top-N 代表事件
        top = select_top_events(events)
        if top.empty:
            print("  无事件可绘图，跳过")
            continue

        # 3. 原始宽表 + 事件窗口图
        raw = raw_cache.get(spec["device"])
        if raw is None:
            raw = _load_raw(spec["device"])
            raw_cache[spec["device"]] = raw
        monitor_cols = _select_monitor_cols(raw, spec)
        cond_col = spec["cond_col"]
        print(f"  监测参数: {len(monitor_cols)} 个, 工况列: {cond_col}")

        drawn = 0
        for i, (_, ev) in enumerate(top.iterrows()):
            png = out_dir / f"{prefix}_event_{i:03d}.png"
            ok = plot_event_window(ev, raw, monitor_cols, png,
                                   cond_col=cond_col)
            if ok:
                drawn += 1
        print(f"  绘制事件窗口图: {drawn}/{len(top)}")

        summary.append(f"\n## {prefix}\n")
        summary.append(f"- 事件总数: **{len(events)}**，代表事件图: {drawn}"
                       f"（Top-{len(top)}）\n")
        summary.append(f"- 监测参数 {len(monitor_cols)} 个，工况列 `{cond_col}`\n")
        summary.append("| 事件ID | 开始 | 结束 | 时长min | 工况 | 方法集 | "
                       "严重度 | 归因摘要 |")
        summary.append("|---|---|---|---|---|---|---|---|")
        for _, ev in top.iterrows():
            start = pd.Timestamp(ev["开始时间"]).strftime("%m-%d %H:%M")
            end = pd.Timestamp(ev["结束时间"]).strftime("%m-%d %H:%M")
            summary.append(
                f"| {ev['事件ID']} | {start} | {end} | {ev['时长_分钟']} "
                f"| {ev['工况']} | {ev['方法集']} | {ev['严重度']} "
                f"| {ev['归因摘要'][:40]} |")

    md_path = out_dir / "anomaly_events_summary.md"
    md_path.write_text("\n".join(summary), encoding="utf-8")
    print(f"\n汇总 -> {md_path}")


if __name__ == "__main__":
    main()
