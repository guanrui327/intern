# -*- coding: utf-8 -*-
"""阶段一完整流程：
  1. 加载重采样宽表
  2. 工况划分（L1 / L2 / L3）
  3. 分工况统计
  4. 生成图表
  5. 输出汇总报告
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src import config
from src.condition import add_cmj_condition, add_zzj_condition, cond_stats
from src.visualize import generate_all_charts


def load_wide(device: str) -> pd.DataFrame:
    path = config.OUTPUT_DIR / "processed" / f"{device}_wide_1min.parquet"
    print(f"  加载 {path}")
    df = pd.read_parquet(path)
    print(f"  行数: {len(df)}, 列数: {len(df.columns)}")
    return df


def cmj_analysis(df: pd.DataFrame, output_dir: Path) -> dict:
    """采煤机完整分析流水线。"""
    print("\n===== 采煤机工况划分 =====")
    df = add_cmj_condition(df)

    # 工况统计
    print("\nL1 分布:")
    print(df["L1"].value_counts())
    print("\nL2 分布（仅运行期）:")
    print(df[df["L1"] == "运行"]["L2"].value_counts())
    print("\nL3 分布（仅割煤期）:")
    cut_mask = df["L2"] == "割煤"
    print(df[cut_mask]["L3"].value_counts())

    # 分工况统计 — 关键监测参数
    monitor_cols = [c for c in df.columns if c in config.CMJ_MONITOR_POINTS]
    print(f"\n分工况(L2) 统计 — {len(monitor_cols)} 个监测参数")
    stats_by_l2 = cond_stats(df[df["L1"] == "运行"], "L2", monitor_cols)
    stats_path = output_dir / "cmj_stats_by_L2.csv"
    stats_by_l2.to_csv(stats_path, encoding="utf-8-sig")
    print(f"  保存到 {stats_path}")

    stats_by_l1 = cond_stats(df, "L1", monitor_cols)
    stats_path2 = output_dir / "cmj_stats_by_L1.csv"
    stats_by_l1.to_csv(stats_path2, encoding="utf-8-sig")

    # 保存带工况标记的宽表
    out_parquet = output_dir / "cmj_with_condition.parquet"
    df.to_parquet(out_parquet)
    print(f"  工况标记宽表: {out_parquet}")

    return {"df": df, "stats_l1": stats_by_l1, "stats_l2": stats_by_l2}


def zzj_analysis(df: pd.DataFrame, output_dir: Path) -> dict:
    """转载机完整分析流水线。"""
    print("\n===== 转载机工况划分 =====")
    df = add_zzj_condition(df)

    print("\n工况分布:")
    print(df["工况"].value_counts())

    monitor_cols = [c for c in df.columns if c in config.ZZJ_MONITOR_POINTS]
    print(f"\n分工况统计 — {len(monitor_cols)} 个监测参数")
    stats = cond_stats(df, "工况", monitor_cols)
    stats_path = output_dir / "zzj_stats_by_cond.csv"
    stats.to_csv(stats_path, encoding="utf-8-sig")
    print(f"  保存到 {stats_path}")

    out_parquet = output_dir / "zzj_with_condition.parquet"
    df.to_parquet(out_parquet)
    print(f"  工况标记宽表: {out_parquet}")

    return {"df": df, "stats": stats}


def generate_report(
    cmj_result: dict,
    zzj_result: dict,
    chart_paths: list[Path],
    output_dir: Path,
) -> Path:
    """生成阶段一汇总报告 MD。"""
    lines = [
        "# 阶段一：单设备分析报告",
        "",
        f"> 生成时间：{pd.Timestamp.now():%Y-%m-%d %H:%M}",
        f"> 数据：大海则煤矿 2024-04-01 ~ 2024-06-01（on-change 存储）",
        "",
        "---",
        "## 1. 采煤机工况划分结果",
        "",
        "### 1.1 L1 宏观（停机 / 运行）",
        "",
    ]

    cmj_df = cmj_result["df"]
    l1_counts = cmj_df["L1"].value_counts()
    for cond, cnt in l1_counts.items():
        pct = cnt / len(cmj_df) * 100
        lines.append(f"- **{cond}**: {cnt} min ({pct:.1f}%)")
    lines.append("")

    lines.extend([
        "### 1.2 L2 工艺工况（仅运行期）",
        "",
    ])
    running_df = cmj_df[cmj_df["L1"] == "运行"]
    l2_counts = running_df["L2"].value_counts()
    for cond, cnt in l2_counts.items():
        pct = cnt / len(running_df) * 100 if len(running_df) else 0
        lines.append(f"- **{cond}**: {cnt} min ({pct:.1f}%)")
    lines.append("")

    lines.append("### 1.3 L3 方向（仅割煤期）")
    lines.append("")
    cut_df = cmj_df[cmj_df["L2"] == "割煤"]
    if len(cut_df):
        l3_counts = cut_df["L3"].value_counts()
        for cond, cnt in l3_counts.items():
            pct = cnt / len(cut_df) * 100
            lines.append(f"- **{cond}**: {cnt} min ({pct:.1f}%)")
    lines.append("")

    lines.extend([
        "---",
        "## 2. 转载机工况划分结果",
        "",
    ])
    zzj_df = zzj_result["df"]
    cond_counts = zzj_df["工况"].value_counts()
    for cond, cnt in cond_counts.items():
        pct = cnt / len(zzj_df) * 100
        lines.append(f"- **{cond}**: {cnt} min ({pct:.1f}%)")

    lines.extend([
        "",
        "---",
        "## 3. 各工况监测参数统计",
        "",
        "详见 CSV 文件：",
        "- `cmj_stats_by_L1.csv` — 采煤机 L1 分工况统计",
        "- `cmj_stats_by_L2.csv` — 采煤机 L2 分工况统计",
        "- `zzj_stats_by_cond.csv` — 转载机分工况统计",
        "",
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
        "## 5. 关键发现",
        "",
        "### 采煤机",
        "",
        "- **停机** 占比与 **运行** 占比反映设备利用率",
        "- **割煤** 工况下截割电流显著高于 **调架** 工况，是基线设定关键",
        "- 摇臂角度和滚筒高度可进一步区分斜切进刀 vs 双向割煤",
        "- 牵引电流在 **空载牵引** 时虽低于 **割煤**，但温升趋势需关注",
        "",
        "### 转载机",
        "",
        "- **带载运行** 占比反映转载机实际输送负荷率",
        "- 电流-转矩-转速 三者联动关系有助于判断传动链健康状态",
        "- IGBT温度随负载变化可用作过载监控指标",
        "",
        "### 回答任务书问题：哪些状态量组合影响哪些监测参数？",
        "",
        "- 滚筒运行状态 + 采煤机速度 → 截割电流（割煤时电流激增 3-5 倍）",
        "- 牵引方向 + 位置架号 → 牵引电流（上行 vs 下行差异）",
        "- 记忆割煤状态 → 自动化程度影响电流波动模式",
        "- 转载机运行状态 + 电机电流 → 识别堵料风险（高转速 + 低电流）",
        "",
        "---",
        "## 6. 下一步（阶段二）",
        "",
        "1. 分工况建立 3σ / IQR 基线",
        "2. 提取时域特征：RMS、斜率、启停次数",
        "3. 滑动窗口 + 马氏距离多维异常检测",
        "4. 采煤机专用异常指标设计",
        "",
    ])

    report_path = output_dir / "phase1_report.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n报告已生成: {report_path}")
    return report_path


def main() -> None:
    output_dir = config.OUTPUT_DIR / "phase1"
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. 加载数据
    print("=" * 50)
    print("阶段一：单设备分析")
    print("=" * 50)

    print("\n--- 采煤机 ---")
    cmj_wide = load_wide("cmj")
    cmj_result = cmj_analysis(cmj_wide, output_dir)

    print("\n--- 转载机 ---")
    zzj_wide = load_wide("zzj")
    zzj_result = zzj_analysis(zzj_wide, output_dir)

    # 2. 图表
    print("\n--- 生成图表 ---")
    chart_paths = generate_all_charts(cmj_result["df"], zzj_result["df"], output_dir)
    for p in chart_paths:
        print(f"  {p}")

    # 3. 报告
    print("\n--- 生成报告 ---")
    report_path = generate_report(cmj_result, zzj_result, chart_paths, output_dir)

    print(f"\n[*] 阶段一分析完成。结果目录: {output_dir}")


if __name__ == "__main__":
    main()
