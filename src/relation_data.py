# -*- coding: utf-8 -*-
"""阶段三：跨设备关联数据处理模块。

1. 加载 CMJ/ZZJ 带工况宽表，验证时间戳对齐
2. 构建系统宽表（CMJ 产量代理 + ZZJ 负载 + 双工况列）
3. 合成联合系统工况（设备_工况 × 工况）
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from src import config


def load_wide_tables() -> tuple[pd.DataFrame, pd.DataFrame]:
    """加载阶段一产出的带工况宽表。"""
    cmj = pd.read_parquet(config.PHASE1_DIR / "cmj_with_condition.parquet")
    zzj = pd.read_parquet(config.PHASE1_DIR / "zzj_with_condition.parquet")
    return cmj, zzj


def validate_alignment(cmj: pd.DataFrame, zzj: pd.DataFrame) -> dict:
    """验证两张宽表时间戳对齐情况，返回统计 dict。"""
    ci = set(cmj.index)
    zi = set(zzj.index)
    inter = len(ci & zi)
    union = len(ci | zi)
    ratio = inter / union if union else 0.0
    return {
        "cmj_points": len(ci),
        "zzj_points": len(zi),
        "intersection": inter,
        "cmj_only": len(ci - zi),
        "zzj_only": len(zi - ci),
        "align_ratio": ratio,
        "cmj_range": (str(cmj.index.min()), str(cmj.index.max())),
        "zzj_range": (str(zzj.index.min()), str(zzj.index.max())),
        "cmj_dup": int(cmj.index.duplicated().sum()),
        "zzj_dup": int(zzj.index.duplicated().sum()),
    }


def build_system_table(cmj: pd.DataFrame, zzj: pd.DataFrame) -> pd.DataFrame:
    """按 index inner join 成系统宽表。

    列 = CMJ 产量代理 + 设备_工况 + ZZJ 负载 + 工况。
    母电流等开关量列不进入（双峰方差趋零问题见 config 注释）。
    """
    cmj_cols = config.CMJ_PROD_FEATURES + ["设备_工况"]
    zzj_cols = config.ZZJ_LOAD_FEATURES + ["工况"]
    missing = [c for c in cmj_cols + zzj_cols if c not in cmj.columns and c not in zzj.columns]
    if missing:
        raise KeyError(f"系统宽表缺列: {missing}")
    sys_df = cmj[cmj_cols].join(zzj[zzj_cols], how="inner")
    return sys_df


def derive_joint_condition(device_cond: str, zzj_cond: str) -> str:
    """设备_工况 × 工况 → 联合系统工况（物理语义映射）。"""
    # 正常采煤：上游割煤 + 下游带载
    if device_cond == "割煤中" and zzj_cond == "带载运行":
        return "生产运行"
    # 采煤-转载错配：上游割煤但下游未带载（堵煤/卡链/断链风险）
    if device_cond == "割煤中" and zzj_cond in ("空载运行", "停机"):
        return "采煤-转载错配"
    # 转载余流：上游已停止割煤但下游仍在带载（残余煤流/滞后）
    if device_cond in ("正常运行", "空载牵引", "待机", "停机") and zzj_cond == "带载运行":
        return "转载余流"
    # 全线停机：上游待机/停机不产煤 + 下游停机（含采煤机带电待机休息）
    if device_cond in ("停机", "待机") and zzj_cond == "停机":
        return "全线停机"
    # 全线待机（设备带电待机循环）
    if device_cond == "待机" and zzj_cond == "空载运行":
        return "全线待机"
    # 空载循环：设备运转但不产煤
    if device_cond in ("正常运行", "空载牵引") and zzj_cond in ("空载运行", "停机"):
        return "空载循环"
    return "过渡态"


def add_joint_condition(sys_df: pd.DataFrame) -> pd.DataFrame:
    """为系统宽表追加 联合工况 列。"""
    sys_df = sys_df.copy()
    sys_df[config.JOINT_COND_COL] = [
        derive_joint_condition(d, z)
        for d, z in zip(sys_df["设备_工况"], sys_df["工况"])
    ]
    return sys_df


def condition_crosstab(sys_df: pd.DataFrame) -> pd.DataFrame:
    """设备_工况 × 工况 交叉表，验证物理耦合。"""
    return pd.crosstab(sys_df["设备_工况"], sys_df["工况"])


def joint_cond_stats(sys_df: pd.DataFrame) -> pd.DataFrame:
    """联合工况占比统计。"""
    vc = sys_df[config.JOINT_COND_COL].value_counts()
    out = pd.DataFrame({"count": vc})
    out["pct"] = (out["count"] / out["count"].sum() * 100).round(2)
    return out
