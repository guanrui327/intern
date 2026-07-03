# -*- coding: utf-8 -*-
"""工况划分：基于状态量规则的层次化分类。

层次
  L1 — 停机 / 运行           （电机运行状态）
  L2 — 割煤 / 调架 / 空载牵引 （速度 + 滚筒 + 摇臂）
  L3 — 方向                  （位置架号变化 + 方向字段）

转载机简化为三层：停机 / 空载运行 / 带载运行。
"""

from __future__ import annotations

from typing import Literal

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# 采煤机工况划分
# ---------------------------------------------------------------------------

CMJ_COND_L1: list[tuple[str, str]] = [
    ("停机", "所有截割 / 牵引电机均停止"),
    ("运行", "至少一台截割或牵引电机运行"),
]

CMJ_COND_L2: list[tuple[str, str]] = [
    ("割煤", "截割滚筒运行 + 速度 > 0.5"),
    ("调架", "截割滚筒运行 + 速度 <= 0.5"),
    ("空载牵引", "牵引运行但截割停止"),
]

CMJ_COND_L3: list[tuple[str, str]] = [
    ("向机头", "方向 == -1"),
    ("向机尾", "方向 == 1"),
    ("静止/方向未知", "方向 == 0 或 NaN"),
]


def _is_running(s: pd.Series) -> pd.Series:
    """运行状态 > 0 视为运行（兼容非 0/1 值的状态字段）。"""
    return s.fillna(0).astype(float) > 0


def classify_cmj_l1(df: pd.DataFrame, col_map: dict[str, str]) -> pd.Series:
    """L1: 停机 / 运行"""
    run_cond = pd.Series(False, index=df.index)
    for key in ["右滚筒_运行状态", "左滚筒_运行状态",
                 "右电机_运行状态", "左电机_运行状态"]:
        col = col_map.get(key)
        if col and col in df.columns:
            run_cond |= _is_running(df[col])
    return run_cond.map({True: "运行", False: "停机"}).rename("L1")


def classify_cmj_l23(
    df: pd.DataFrame, col_map: dict[str, str], l1: pd.Series,
) -> pd.DataFrame:
    """L2 工艺 + L3 方向，仅在 L1="运行" 时有意义。"""
    l2 = pd.Series("未知", index=df.index, name="L2", dtype="object")
    l3 = pd.Series("未知", index=df.index, name="L3", dtype="object")

    mask_run = l1 == "运行"

    # 截割是否运行
    right_cut_run = _is_running(df[col_map["右滚筒_运行状态"]]) if "右滚筒_运行状态" in col_map else pd.Series(False, index=df.index)
    left_cut_run = _is_running(df[col_map["左滚筒_运行状态"]]) if "左滚筒_运行状态" in col_map else pd.Series(False, index=df.index)
    cutting = right_cut_run | left_cut_run

    # 速度
    speed = df.get(col_map.get("采煤机速度", ""), pd.Series(0.0, index=df.index)).fillna(0).astype(float)

    # L2
    mask_cut = mask_run & cutting
    mask_cut_high = mask_cut & (speed > 0.5)
    mask_cut_low  = mask_cut & (speed <= 0.5)
    mask_tow = mask_run & ~cutting & (speed > 0)

    l2.loc[mask_cut_high] = "割煤"
    l2.loc[mask_cut_low]  = "调架"
    l2.loc[mask_tow]      = "空载牵引"

    # L3 — 仅在 L1=运行 且 L2=割煤 时划分方向
    dir_col = col_map.get("方向", "")
    if dir_col in df.columns:
        direction = df[dir_col].fillna(0).astype(float)
        l3.loc[mask_cut_high & (direction < -0.5)] = "向机头"
        l3.loc[mask_cut_high & (direction > 0.5)]  = "向机尾"
        l3.loc[mask_cut_high & (direction.abs() <= 0.5)] = "静止/方向未知"
    else:
        l3.loc[mask_cut_high] = "方向未知（缺少方向字段）"

    return pd.DataFrame({"L1": l1, "L2": l2, "L3": l3})


# 字段别名 → 宽表列名
CMJ_COLUMN_ALIAS: dict[str, str] = {
    "右滚筒_运行状态":       "采煤机_截割部位_右滚筒_运行状态",
    "左滚筒_运行状态":       "采煤机_截割部位_左滚筒_运行状态",
    "右滚筒_电机_运行状态":  "采煤机_截割部位_右滚筒_电机_运行状态",
    "左滚筒_电机_运行状态":  "采煤机_截割部位_左滚筒_电机_运行状态",
    "右电机_运行状态":       "采煤机_牵引部位_右电机_运行状态",
    "左电机_运行状态":       "采煤机_牵引部位_左电机_运行状态",
    "采煤机速度":            "采煤机_牵引部位_采煤机速度",
    "方向":                  "采煤机_牵引部位_方向",
    "位置架号":              "采煤机_牵引部位_位置架号",
    "右滚筒_高度":           "采煤机_截割部位_右滚筒_高度",
    "左滚筒_高度":           "采煤机_截割部位_左滚筒_高度",
    "右摇臂_角度":           "采煤机_截割部位_右摇臂_角度",
    "左摇臂_角度":           "采煤机_截割部位_左摇臂_角度",
}


def add_cmj_condition(df: pd.DataFrame) -> pd.DataFrame:
    """为采煤机宽表添加 L1 / L2 / L3 工况列。"""
    col_map = {k: v for k, v in CMJ_COLUMN_ALIAS.items() if v in df.columns}
    l1 = classify_cmj_l1(df, col_map)
    cond = classify_cmj_l23(df, col_map, l1)
    return pd.concat([df, cond], axis=1)


# ---------------------------------------------------------------------------
# 转载机工况划分
# ---------------------------------------------------------------------------

ZZJ_COLUMN_ALIAS: dict[str, str] = {
    "运行状态":     "三机_转载机_运行状态",
    "变频器_运行状态": "三机_转载机_变频器_运行状态",
    "电机_电流":    "三机_转载机_电机_电流",
    "电机_转速":    "三机_转载机_电机_转速",
}

ZZJ_COND: list[tuple[str, str]] = [
    ("停机", "运行状态 == 0"),
    ("空载运行", "运行且电流 < 50A"),
    ("带载运行", "运行且电流 >= 50A"),
]


def add_zzj_condition(df: pd.DataFrame, current_threshold: float = 50.0) -> pd.DataFrame:
    """为转载机添加工况列：停机 / 空载运行 / 带载运行。

    Parameters
    ----------
    df :
        宽表
    current_threshold :
        空载 / 带载 电流分界（A）
    """
    run_col = "三机_转载机_运行状态"
    cur_col = "三机_转载机_电机_电流"

    cond = pd.Series("未知", index=df.index, name="工况", dtype="object")

    if run_col not in df.columns or cur_col not in df.columns:
        cond[:] = "缺少字段"
        return pd.concat([df, cond.to_frame()], axis=1)

    running = _is_running(df[run_col])
    current = df[cur_col].fillna(0).astype(float)

    cond.loc[~running] = "停机"
    cond.loc[running & (current < current_threshold)] = "空载运行"
    cond.loc[running & (current >= current_threshold)] = "带载运行"

    return pd.concat([df, cond.to_frame()], axis=1)


# ---------------------------------------------------------------------------
# 分工况统计
# ---------------------------------------------------------------------------

def cond_stats(
    df: pd.DataFrame,
    cond_col: str,
    value_cols: list[str],
) -> pd.DataFrame:
    """按工况分组，计算各监测参数的基本统计量。"""
    groups = df.groupby(cond_col)
    stats = groups[value_cols].agg(["count", "mean", "std", "min", "median", "max"])
    # 展平多级列名
    stats.columns = [f"{col}_{stat}" for col, stat in stats.columns]
    stats = stats.round(4)
    return stats
