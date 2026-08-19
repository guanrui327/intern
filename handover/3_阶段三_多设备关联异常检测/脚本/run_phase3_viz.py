# -*- coding: utf-8 -*-
"""阶段三：可视化生成驱动。

读取 pipeline 输出（system_table.parquet / rule_events.csv /
propagation_chains.csv），生成周报用图到 report/阶段三/。
"""
from __future__ import annotations

import pandas as pd

from src import config
from src.relation_data import add_joint_condition
from src.relation_event import rule_condition_events, propagate_events, extract_merged_events
from src import relation_viz as rv

FIG_DIR = config.PHASE3_DIR.parents[1] / "report" / "阶段三"


def main() -> None:
    FIG_DIR.mkdir(parents=True, exist_ok=True)

    sys_df = pd.read_parquet(config.PHASE3_DATA / "system_table.parquet")
    if config.JOINT_COND_COL not in sys_df.columns:
        sys_df = add_joint_condition(sys_df)

    # 图1：联合工况堆叠
    rv.plot_joint_condition_stack(sys_df, FIG_DIR / "1_联合工况堆叠.png")

    # 图2：双设备叠加时间线（聚焦 04-15 长时错配案例 08:00~16:00）
    rule = pd.read_csv(config.PHASE3_DATA / "rule_events.csv",
                       parse_dates=["start", "end"])
    rv.plot_cmj_zzj_timeline(sys_df, rule, "2024-04-15 08:00",
                             "2024-04-15 16:00", FIG_DIR / "2_关联时间线_错配案例.png")

    # 图3：产量-负载散点（恒流带 vs 错配断流）
    rv.plot_coupling_scatter(sys_df, FIG_DIR / "3_产量负载散点.png")

    # 图4：事件传导滞后分布
    chains = None
    p = config.PHASE3_DATA / "propagation_chains.csv"
    if p.exists():
        chains = pd.read_csv(p, parse_dates=["上游start", "下游start"])
    rv.plot_propagation_chains(chains, FIG_DIR / "4_事件传导滞后.png")

    print(f"[Done] 阶段三图已生成到 {FIG_DIR}")


if __name__ == "__main__":
    main()
