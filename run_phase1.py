# -*- coding: utf-8 -*-
"""阶段一完整流程（分部位版，优化版）：
  1. 加载重采样宽表
  2. 分部位工况划分（截割部 / 牵引部 / 油泵 / 破碎机 / 设备级）
  3. 分工况统计 + 新分析（覆盖率 / 段持续时间 / Kruskal-Wallis）
  4. 生成图表（分部位时间线 + 箱线图 + 相关性）
  5. 分部位转换检测 + 分部位聚类验证
  6. 输出汇总报告

  优化要点：
  - 避免重复列过滤缓存
  - plot_gap_overview 复用已算好的空洞结果
  - 图表批量生成后关图防内存堆积
  - parquet 保存移到末尾
  - 细化进度打印
"""

from __future__ import annotations

import gc
import time
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from src import config
from src.condition import (
    add_cmj_part_conditions,
    add_zzj_condition,
    cond_stats,
)
from src.config import CMJ_PART_COND_COLS
from src.visualize import generate_all_charts
from src.preprocess import (
    detect_data_gaps,
    plot_gap_overview,
    compute_point_coverage,
)
from src.param_map import generate_param_hierarchy
from src.transition import (
    detect_all_part_transitions,
    detect_device_transitions,
    compute_transition_stats,
    plot_transition_parameters,
    extract_transition_features,
    plot_aggregate_transition_profile,
    plot_multi_param_transition,
)
from src.cluster_validate import (
    generate_per_part_cluster_reports,
)
from src.significance import run_per_part_significance_test
from src.segment_stats import (
    compute_all_part_segment_stats,
    compute_all_part_anomalous_segments,
    compute_all_part_value_anomalies,
)
from src.generate_report_docx import build_week2_report

# ── 常量 ──
PART_COND_COLS_RUN = ["截割部_工况", "牵引部_工况", "油泵_工况", "破碎机_工况"]
PART_NAME = {
    "截割部_工况": "截割部",
    "牵引部_工况": "牵引部",
    "油泵_工况": "油泵",
    "破碎机_工况": "破碎机",
}
# 设备级切换典型图用的三组参数
DEV_TRANSITION_PARAMS = [
    "采煤机_截割部位_右滚筒_电机_电流",
    "采煤机_牵引部位_采煤机速度",
    "采煤机_截割部位_右摇臂_角度",
]
# 聚合剖面筛选关键词
PROFILE_KEYWORDS = ["右滚筒_电机_电流", "右电机_电流", "采煤机速度", "右滚筒_电机_温度"]


def _filter_cols(df: pd.DataFrame, keywords: list[str]) -> list[str]:
    """缓存友好的列名过滤。"""
    return [c for c in df.columns
            if any(kw in c for kw in keywords)]


def _monitor_cols(df: pd.DataFrame) -> list[str]:
    """返回宽表中属于 CMJ_MONITOR_POINTS 的列。"""
    return [c for c in df.columns if c in config.CMJ_MONITOR_POINTS]


def _clean_figs(msg: str = "") -> None:
    """关闭所有图窗并回收内存。"""
    plt.close("all")
    gc.collect()


def load_wide(device: str) -> pd.DataFrame:
    path = config.OUTPUT_DIR / "processed" / f"{device}_wide_1min.parquet"
    print(f"  加载 {path}")
    df = pd.read_parquet(path)
    print(f"  行数: {len(df)}, 列数: {len(df.columns)}")
    return df


def cmj_part_analysis(df: pd.DataFrame, output_dir: Path) -> dict:
    """采煤机分部位工况分析流水线。"""
    print("\n===== 采煤机分部位工况划分 =====")
    df = add_cmj_part_conditions(df)

    monitor_cols = _monitor_cols(df)

    for col in PART_COND_COLS_RUN:
        if col not in df.columns:
            continue
        print(f"\n{col} 分布:")
        print(df[col].value_counts())

        stats = cond_stats(df, col, monitor_cols)
        stats.to_csv(output_dir / f"cmj_stats_by_{col}.csv", encoding="utf-8-sig")
        print(f"  → cmj_stats_by_{col}.csv")

    if "设备_工况" in df.columns:
        print("\n设备_工况 分布:")
        print(df["设备_工况"].value_counts())
        stats = cond_stats(df, "设备_工况", monitor_cols)
        stats.to_csv(output_dir / "cmj_stats_by_设备_工况.csv", encoding="utf-8-sig")

    return {"df": df}


def zzj_analysis(df: pd.DataFrame, output_dir: Path) -> dict:
    """转载机分析流水线。"""
    print("\n===== 转载机工况划分 =====")
    df = add_zzj_condition(df)

    print("\n工况分布:")
    print(df["工况"].value_counts())

    monitor_cols = [c for c in df.columns if c in config.ZZJ_MONITOR_POINTS]
    print(f"\n分工况统计 — {len(monitor_cols)} 个监测参数")
    stats = cond_stats(df, "工况", monitor_cols)
    stats_path = output_dir / "zzj_stats_by_cond.csv"
    stats.to_csv(stats_path, encoding="utf-8-sig")
    print(f"  → {stats_path}")

    return {"df": df}


def generate_report(
    cmj_result: dict,
    zzj_result: dict,
    chart_paths: list[Path],
    output_dir: Path,
) -> Path:
    """生成阶段一汇总报告 MD（分部位版）。"""
    cmj_df = cmj_result["df"]
    zzj_df = zzj_result["df"]

    lines = [
        "# 阶段一：单设备分析报告（分部位工况）",
        "",
        f"> 生成时间：{pd.Timestamp.now():%Y-%m-%d %H:%M}",
        f"> 数据：大海则煤矿 2024-04-01 ~ 2024-06-01（on-change 存储）",
        "",
        "---",
        "## 1. 采煤机分部位工况划分结果",
        "",
        "### 1.1 设备级工况",
        "",
    ]

    if "设备_工况" in cmj_df.columns:
        dev_counts = cmj_df["设备_工况"].value_counts()
        for cond, cnt in dev_counts.items():
            pct = cnt / len(cmj_df) * 100
            lines.append(f"- **{cond}**: {cnt} min ({pct:.1f}%)")
        lines.append("")

    for col in PART_COND_COLS_RUN:
        if col not in cmj_df.columns:
            continue
        part_name = PART_NAME.get(col, col)
        lines.append(f"### 1.2 {part_name} 工况")
        lines.append("")
        counts = cmj_df[col].value_counts()
        for cond, cnt in counts.items():
            pct = cnt / len(cmj_df) * 100
            lines.append(f"- **{cond}**: {cnt} min ({pct:.1f}%)")
        lines.append("")

    lines.extend([
        "---",
        "## 2. 转载机工况划分结果",
        "",
    ])
    cond_counts_zzj = zzj_df["工况"].value_counts()
    for cond, cnt in cond_counts_zzj.items():
        pct = cnt / len(zzj_df) * 100
        lines.append(f"- **{cond}**: {cnt} min ({pct:.1f}%)")

    lines.extend([
        "",
        "---",
        "## 3. 各工况监测参数统计",
        "",
        "详见 CSV 文件：",
    ])
    for col in PART_COND_COLS_RUN + ["设备_工况"]:
        lines.append(f"- `cmj_stats_by_{col}.csv` — 采煤机 {col} 分工况统计")
    lines.append("- `zzj_stats_by_cond.csv` — 转载机分工况统计")
    lines.append("")

    lines.extend([
        "---",
        "## 4. 图表输出",
        "",
    ])
    for p in chart_paths:
        rel = p.relative_to(output_dir.parent)
        lines.append(f"- [{p.name}]({rel})")

    lines.extend([
        "",
        "---",
        "## 5. 数据空洞分析",
        "",
        "基于 on-change 存储特性，对重采样后连续相同值游程 ≥120min 的参数进行检测。",
        "详见 `gap_detection.png`（热力图）和 `gap_report.csv`。",
        "",
        "---",
        "## 6. 参数层级图谱",
        "",
        "按 `设备_部位_组件_传感器_指标` 命名规则解析测点层级关系。",
        "",
        "---",
        "## 7. 工况转换分析",
        "",
        "分部位检测工况切换事件（截割部/牵引部/油泵/破碎机各自独立），",
        "详见各 `transition_*_stats.csv` 和转换时序图。",
        "",
        "---",
        "## 8. 聚类验证规则工况",
        "",
        "以关键监测参数为特征，KMeans 聚类后与规则标签对比，",
        "ARI 反映规则划分的合理性。",
        "",
        "---",
        "## 9. 显著性检验 (Kruskal-Wallis)",
        "",
        "对 4 个部位做分部位 Kruskal-Wallis 检验 + FDR 校正 + epsilon² 效应量。",
        "",
        "---",
        "## 10. 关键发现",
        "",
        "### 采煤机",
        "",
        "- **设备级工况占比**反映设备利用率",
        "- **截割部**: 割煤中电流显著高于调架中",
        "- **牵引部**: 牵引中电流变化与负载相关",
        "- 滞后互相关揭示电流与温度、速度的延时耦合关系",
        "",
        "### 转载机",
        "",
        "- **带载运行** 占比反映转载机实际输送负荷率",
        "- 电流-转矩-转速 三者联动关系有助于判断传动链健康状态",
        "",
        "---",
        "## 11. 下一步（阶段二）",
        "",
        "1. 分工况建立 3σ / IQR 基线",
        "2. 提取时域特征：RMS、斜率、启停次数",
        "3. 滑动窗口 + 马氏距离多维异常检测",
        "",
    ])

    report_path = output_dir / "phase1_report.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n报告已生成: {report_path}")
    return report_path


# ── 并行骨架：包装器，让 4 部位独立工作函数可并行 ──

def _do_part_transitions(
    cmj_df: pd.DataFrame,
    col: str,
    output_dir: Path,
) -> list[Path]:
    """单个部位的转换检测+出图，返回 chart_paths 子集。"""
    from src.transition import detect_transitions, compute_transition_stats, plot_transition_parameters
    charts: list[Path] = []
    trans_df = detect_transitions(cmj_df, cond_col=col, window=5, exclude_unknown=True)
    if trans_df.empty:
        return charts
    csv_path = output_dir / f"transition_{col}_stats.csv"
    compute_transition_stats(trans_df).to_csv(csv_path, index=False, encoding="utf-8-sig")

    current_cols = _filter_cols(cmj_df, ["电流"])
    if current_cols:
        t_path = output_dir / f"transition_{col}_{current_cols[0].split('_')[-1]}.png"
        plot_transition_parameters(cmj_df, trans_df, current_cols[0],
                                   window=10, max_examples=2, output_path=t_path)
        charts.append(t_path)
    return charts


def _do_part_charts(
    cmj_df: pd.DataFrame,
    col: str,
    output_dir: Path,
) -> list[Path]:
    """单个部位的箱线图（可并行）。"""
    from src.visualize import plot_cond_boxplot
    charts: list[Path] = []
    col_map = {
        "截割部_工况": ("截割部", "滚筒", "cut"),
        "牵引部_工况": ("牵引部", "牵引", "traction"),
        "油泵_工况":   ("油泵", "油泵", "pump"),
        "破碎机_工况": ("破碎机", "破碎机", "crusher"),
    }
    if col not in col_map:
        return charts
    pname, kw, suffix = col_map[col]
    target_cols = _filter_cols(cmj_df, [kw, "电流"])
    if target_cols:
        bx = output_dir / f"cmj_{pname}_{suffix}_current_boxplot.png"
        plot_cond_boxplot(cmj_df, col, target_cols,
                          f"{pname} — 分工况{pname}电流分布", output_path=bx)
        charts.append(bx)
    return charts


def main() -> None:
    output_dir = config.OUTPUT_DIR / "phase1"
    output_dir.mkdir(parents=True, exist_ok=True)

    # ── 阶段计时探针（仅打印，不影响产物） ──
    # 语义：_mark("阶段N") 在阶段N 开头调用，把上一阶段(N-1) 的真实耗时
    #       补进 _stages[-1]，再登记"阶段N"占位（其时长由下一次 _mark 补齐）。
    #       避免旧实现"mark 在开头、记录上一段时长"导致的 off-by-one 归属错位。
    _t_last = time.perf_counter()
    _stages: list[tuple[str, float]] = []
    def _mark(name: str) -> None:
        nonlocal _t_last
        now = time.perf_counter()
        if _stages:
            prev_name, _ = _stages[-1]
            _stages[-1] = (prev_name, now - _t_last)
        _stages.append((name, 0.0))
        _t_last = now

    print("=" * 50)
    print("阶段一：单设备分析（分部位工况）")
    print("=" * 50)

    # ── 1. 加载数据 ──
    print("\n--- 加载数据 ---")
    cmj_wide = load_wide("cmj")
    zzj_wide = load_wide("zzj")
    _mark("加载数据")

    # 缓存的列过滤（只算一次）
    cmj_monitor = _monitor_cols(cmj_wide)

    # 注：野值清洗块已按 V 决策移除（零膨胀 IQR 误杀破碎机电流 6201 个真实读数），
    #     保持基线原始数据，保证任务1 ARI/KW 对比不被数据改动污染。

    # ── 1c. 数据空洞检测（一次性算好，复用给热力图） ──
    print("\n--- 数据空洞检测 ---")
    _mark("数据空洞检测")
    gaps = detect_data_gaps(cmj_wide, cmj_monitor, gap_threshold=120) if cmj_monitor else pd.DataFrame()
    if not gaps.empty:
        gaps.to_csv(output_dir / "gap_report.csv", index=False, encoding="utf-8-sig")
        print(f"  空洞数: {len(gaps)}")
        plot_gap_overview(cmj_wide, cmj_monitor, gap_threshold=120,
                          gaps=gaps,
                          output_path=output_dir / "gap_detection.png")
    _clean_figs("gap")

    # ── 1b. 参数层级图谱 ──
    print("\n--- 参数层级图谱 ---")
    _mark("参数层级图谱")
    hierarchy = generate_param_hierarchy(
        list(cmj_wide.columns), output_dir,
        highlight_params=set(config.CMJ_MONITOR_POINTS),
    )
    print(f"  CSV: {hierarchy['hierarchy_csv']}")

    # ── 2. 工况划分 ──
    _mark("工况划分")
    cmj_result = cmj_part_analysis(cmj_wide, output_dir)
    cmj_df = cmj_result["df"]

    zzj_result = zzj_analysis(zzj_wide, output_dir)
    zzj_df = zzj_result["df"]

    chart_paths: list[Path] = []

    # ── 3. 全套图表 ──
    print("\n--- 生成图表 ---")
    _mark("生成图表")
    chart_paths = generate_all_charts(cmj_df, zzj_df, output_dir)
    _clean_figs("charts")

    # ── 4a. 分部位转换检测（4 个部位串行，但每个独立） ──
    print("\n--- 分部位工况转换检测 ---")
    _mark("分部位转换检测")
    for col in PART_COND_COLS_RUN:
        if col not in cmj_df.columns:
            continue
        part_name = PART_NAME.get(col, col)
        part_charts = _do_part_transitions(cmj_df, col, output_dir)
        chart_paths.extend(part_charts)
        print(f"  {part_name}: {len(part_charts)} 张图")
    _clean_figs("part-trans")

    # ── 4b. 设备级转换检测 ──
    dev_transitions = detect_device_transitions(cmj_df, window=10)
    if not dev_transitions.empty:
        print(f"  设备级: 切换事件数={len(dev_transitions)}")
        dev_stats = compute_transition_stats(dev_transitions)
        dev_stats.to_csv(output_dir / "transition_设备_工况_stats.csv",
                         index=False, encoding="utf-8-sig")

        for param_col in DEV_TRANSITION_PARAMS:
            if param_col not in cmj_df.columns:
                continue
            suffix = param_col.split("_")[-1]
            t_path = output_dir / f"transition_device_{suffix}.png"
            plot_transition_parameters(cmj_df, dev_transitions, param_col,
                                       window=10, max_examples=2, output_path=t_path)
            chart_paths.append(t_path)
        _clean_figs("dev-trans")

    # ── 4c. 切换时域特征提取 ──
    print("\n--- 切换时域特征提取 ---")
    _mark("切换时域特征")
    key_params = [c for c in cmj_monitor
                  if any(kw in c for kw in ["电流", "速度", "温度", "角度"])]

    if not dev_transitions.empty and key_params:
        feat_df = extract_transition_features(cmj_df, dev_transitions,
                                              param_cols=key_params, window=10)
        if not feat_df.empty:
            feat_csv = output_dir / "transition_device_features.csv"
            feat_df.to_csv(feat_csv, index=False, encoding="utf-8-sig")
            print(f"  设备级特征: {feat_csv} ({len(feat_df)} 事件)")

        profile_params = [c for c in key_params
                          if any(kw in c for kw in PROFILE_KEYWORDS)]
        for pcol in profile_params[:3]:
            if pcol not in cmj_df.columns:
                continue
            p_suffix = pcol.split("_")[-1] if "电流" in pcol else (
                "速度" if "速度" in pcol else "温度")
            p_path = output_dir / f"transition_profile_device_{p_suffix}.png"
            plot_aggregate_transition_profile(
                cmj_df, dev_transitions, pcol,
                window=15, min_samples=3,
                title="设备工况切换聚合剖面", output_path=p_path,
            )
            chart_paths.append(p_path)

        # 多参数切换指纹
        type_key = (dev_transitions["切换前工况"].astype(str)
                    + "→" + dev_transitions["切换后工况"].astype(str))
        top_types = type_key.value_counts().head(3).index.tolist()
        if top_types:
            mp_groups = [
                ("电流速度", _filter_cols(cmj_df, ["电流", "速度"])[:6]),
                ("电流温度", _filter_cols(cmj_df, ["电流", "温度"])[:6]),
                ("全关键参数", key_params[:8]),
            ]
            for suffix, mp_cols in mp_groups:
                if len(mp_cols) < 2:
                    continue
                for ev_i, ttype in enumerate(top_types):
                    candidates = type_key[type_key == ttype].index.tolist()
                    if not candidates:
                        continue
                    global_idx = dev_transitions.index.get_loc(candidates[0])
                    mp_path = output_dir / f"transition_multi_param_{suffix}_{ev_i}.png"
                    plot_multi_param_transition(
                        cmj_df, dev_transitions, mp_cols,
                        event_idx=global_idx, window=15,
                        title=f"切换指纹: {ttype} — {len(mp_cols)}参数",
                        output_path=mp_path,
                    )
                    chart_paths.append(mp_path)
        _clean_figs("dev-feat")

    # ── 5. 分部位聚类验证（generate_per_part_cluster_reports 内部已循环 4 部位） ──
    print("\n--- 分部位聚类验证 ---")
    _mark("分部位聚类验证")
    part_cluster_results = generate_per_part_cluster_reports(cmj_df, output_dir=output_dir)
    for part_name, result in part_cluster_results.items():
        if "error" not in result["result"]:
            print(f"  {part_name}: ARI={result['result']['ari']:.4f}")
            if result.get("plot_path"):
                chart_paths.append(result["plot_path"])
    _clean_figs("cluster")

    # ── 6. Kruskal-Wallis（内部已循环 4 部位） ──
    print("\n--- 分部位 Kruskal-Wallis 显著性检验 ---")
    _mark("KW 检验")
    run_per_part_significance_test(cmj_df, output_dir, monitor_cols=cmj_monitor)
    _clean_figs("kw")

    # ── 7. 分段持续时间统计 ──
    print("\n--- 分段持续时间统计 ---")
    _mark("分段统计")
    compute_all_part_segment_stats(cmj_df, output_dir, part_cols=PART_COND_COLS_RUN)
    _clean_figs("segment")

    # ── 8. 异常段检测 ──
    print("\n--- 异常段检测 ---")
    _mark("异常段检测")
    compute_all_part_anomalous_segments(
        cmj_df, output_dir, part_cols=PART_COND_COLS_RUN,
        duration_threshold=120, percentile_threshold=99.0,
    )

    # ── 9. 数值异常检测（新增） ──
    print("\n--- 数值异常检测 ---")
    _mark("数值异常检测")
    compute_all_part_value_anomalies(
        cmj_df, output_dir, part_cols=PART_COND_COLS_RUN,
    )
    _clean_figs("value-ano")

    # ── 10. 点数据覆盖率（新增） ──
    print("\n--- 点数据覆盖率 ---")
    _mark("覆盖率")
    coverage_df = compute_point_coverage(cmj_df[cmj_monitor])
    if coverage_df is not None:
        coverage_df.to_csv(output_dir / "point_coverage.csv",
                           index=False, encoding="utf-8-sig")
        print(f"  保存到 point_coverage.csv ({len(coverage_df)} 个测点)")

    # ── 10b. 转载机进阶分析（6 模块） ──
    print("\n" + "=" * 40)
    print("转载机深度分析（6 模块）")
    print("=" * 40)
    zzj_monitor = [c for c in zzj_df.columns if c in config.ZZJ_MONITOR_POINTS]

    # 10b-1. 转换检测
    print("\n--- 转载机工况转换检测 ---")
    _mark("ZZJ 转换")
    zzj_trans = detect_all_part_transitions(zzj_df, part_cols=["工况"])
    for col, trans_df in zzj_trans.items():
        if trans_df.empty:
            continue
        csv_path = output_dir / f"transition_{col}_stats.csv"
        compute_transition_stats(trans_df).to_csv(csv_path, index=False, encoding="utf-8-sig")
        print(f"  {col}: {len(trans_df)} 个转换事件")
        zzj_current_cols = [c for c in zzj_df.columns if "电流" in c]
        if zzj_current_cols:
            t_path = output_dir / f"transition_{col}_current.png"
            plot_transition_parameters(zzj_df, trans_df, zzj_current_cols[0],
                                       window=10, max_examples=2, output_path=t_path)
            chart_paths.append(t_path)
    _clean_figs("zzj-trans")

    # 10b-2. 聚类验证（先将正则模式匹配为实际列名）
    print("\n--- 转载机聚类验证 ---")
    _mark("ZZJ 聚类")
    import re as _re
    zzj_cluster_features = {}
    for part, patterns in config.ZZJ_PART_CLUSTER_FEATURES.items():
        matched = []
        for pat in patterns:
            pattern = _re.compile(pat.replace(".*", ".*"))
            matched.extend([c for c in zzj_df.columns if pattern.search(c)])
        zzj_cluster_features[part] = list(set(matched))
    zzj_cluster_results = generate_per_part_cluster_reports(
        zzj_df, output_dir=output_dir,
        part_feature_map=zzj_cluster_features,
    )
    for part_name, result in zzj_cluster_results.items():
        if "error" not in result["result"]:
            print(f"  {part_name}: ARI={result['result']['ari']:.4f}")
            if result.get("plot_path"):
                chart_paths.append(result["plot_path"])
    _clean_figs("zzj-cluster")

    # 10b-3. Kruskal-Wallis
    print("\n--- 转载机 Kruskal-Wallis 检验 ---")
    _mark("ZZJ KW")
    run_per_part_significance_test(
        zzj_df, output_dir, monitor_cols=zzj_monitor,
        part_cond_map={"转载机": "工况"},
    )
    _clean_figs("zzj-kw")

    # 10b-4. 分段持续时间统计
    print("\n--- 转载机分段持续时间统计 ---")
    _mark("ZZJ 分段")
    compute_all_part_segment_stats(zzj_df, output_dir, part_cols=["工况"])
    _clean_figs("zzj-segment")

    # 10b-5. 异常段检测
    print("\n--- 转载机异常段检测 ---")
    _mark("ZZJ 异常段")
    compute_all_part_anomalous_segments(
        zzj_df, output_dir, part_cols=["工况"],
        duration_threshold=120, percentile_threshold=99.0,
    )

    # 10b-6. 数值异常检测
    print("\n--- 转载机数值异常检测 ---")
    _mark("ZZJ 数值异常")
    compute_all_part_value_anomalies(
        zzj_df, output_dir, part_cols=["工况"],
    )
    _clean_figs("zzj-value-ano")

    # ── 11. 保存带工况宽表（移到末尾，减少中间 I/O） ──
    print("\n--- 保存工况宽表 ---")
    _mark("保存 parquet")
    out_cmj = output_dir / "cmj_with_condition.parquet"
    cmj_df.to_parquet(out_cmj)
    print(f"  {out_cmj}")
    out_zzj = output_dir / "zzj_with_condition.parquet"
    zzj_df.to_parquet(out_zzj)
    print(f"  {out_zzj}")

    # ── 12. 报告 ──
    print("\n--- 生成报告 ---")
    _mark("生成报告")
    generate_report(cmj_result, zzj_result, chart_paths, output_dir)

    # ── 13. 第二周 DOCX ──
    print("\n--- 第二周深度分析报告 ---")
    _mark("第二周 DOCX")
    try:
        build_week2_report()
    except Exception as e:
        print(f"  [WARN] 失败: {e}")
        import traceback
        traceback.print_exc()

    print(f"\n[*] 阶段一分析完成。结果目录: {output_dir}")

    # ── 阶段耗时汇总 ──
    _mark("总计")
    # 手动关闭最后一个阶段（"总计"之前的阶段）的时长
    _now = time.perf_counter()
    if _stages:
        _prev_name, _ = _stages[-1]
        _stages[-1] = (_prev_name, _now - _t_last)
    print("\n=== 阶段耗时汇总 (s) ===")
    for name, sec in _stages:
        print(f"  {name:<16}{sec:8.1f}")


if __name__ == "__main__":
    main()
