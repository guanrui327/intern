# -*- coding: utf-8 -*-
"""工况划分：分部位独立工况 + 设备级推导。

=== KW+聚类优化后（v2）===

ARI 验证结果（KMeans vs 规则划分）：
  截割部  0.17 → 0.59（v3） — 待机高度拆分 + 割煤中 3 档高度拆分 + 聚类去高度特征
  牵引部  0.556 — 空/重载子类有统计意义，保留（4态）
  油泵    0.800 — 轻/重载划分优秀，保留（3态）
  破碎机  0.350 — 阈值准确（0 空载误报），带载样本极少，保留（3态）

部位列（优化后）
  截割部_工况 — 停机 / 待机 / 待机-高位 / 调架中 / 割煤低位 / 割煤中位 / 割煤高位
  牵引部_工况 — 停机 / 待机 / 空载牵引 / 重载牵引
  油泵_工况   — 停机 / 轻载 / 重载
  破碎机_工况 — 停机 / 空载运行 / 带载运行

设备级列
  设备_工况   — 割煤中 / 正常运行 / 空载牵引 / 待机 / 停机

优化依据
  - 截割部 ARI=0.17→0.59：原始规则仅用速度+滚筒转停，KMeans 以高度为主聚类维度。
    待机拆为待机/待机-高位（4.5m阈值），割煤中按最大高度拆为低位/中位/高位（3m/5m阈值），
    聚类特征中去掉滚筒高度，使聚类与运营规则对齐。
  - 牵引部 ARI=0.556 → 空载/重载牵引电流差异显著（73A vs 247A 中位数）
  - 油泵   ARI=0.800 → 油压轻/重载分离极好（p10=0.15  vs 中位 2.35 MPa）
  - 破碎机 ARI=0.350 → 50A 阈值无假阳性（0/16960），带载仅 0.66% 样本
"""

from __future__ import annotations

from typing import Literal

import numpy as np
import pandas as pd

from src import config as _config


# ---------------------------------------------------------------------------
# 通用工具
# ---------------------------------------------------------------------------

def _is_running(s: pd.Series) -> pd.Series:
    """运行状态 > 0 视为运行（兼容非 0/1 值的状态字段）。"""
    return s.fillna(0).astype(float) > 0


# ---------------------------------------------------------------------------
# 采煤机 — 分部位工况划分
# ---------------------------------------------------------------------------

# 字段别名 → 宽表列名
CMJ_COLUMN_ALIAS: dict[str, str] = {
    "右滚筒_运行状态":       "采煤机_截割部位_右滚筒_运行状态",
    "左滚筒_运行状态":       "采煤机_截割部位_左滚筒_运行状态",
    "右滚筒_电机_运行状态":  "采煤机_截割部位_右滚筒_电机_运行状态",
    "左滚筒_电机_运行状态":  "采煤机_截割部位_左滚筒_电机_运行状态",
    "右滚筒_电机_电流":      "采煤机_截割部位_右滚筒_电机_电流",
    "左滚筒_电机_电流":      "采煤机_截割部位_左滚筒_电机_电流",
    "右电机_运行状态":       "采煤机_牵引部位_右电机_运行状态",
    "左电机_运行状态":       "采煤机_牵引部位_左电机_运行状态",
    "右电机_电流":           "采煤机_牵引部位_右电机_电流",
    "左电机_电流":           "采煤机_牵引部位_左电机_电流",
    "采煤机速度":            "采煤机_牵引部位_采煤机速度",
    "方向":                  "采煤机_牵引部位_方向",
    "位置架号":              "采煤机_牵引部位_位置架号",
    "右滚筒_高度":           "采煤机_截割部位_右滚筒_高度",
    "左滚筒_高度":           "采煤机_截割部位_左滚筒_高度",
    "右摇臂_角度":           "采煤机_截割部位_右摇臂_角度",
    "左摇臂_角度":           "采煤机_截割部位_左摇臂_角度",
    "油泵_右电机_运行状态":  "采煤机_油泵_右电机_运行状态",
    "油泵_左电机_运行状态":  "采煤机_油泵_左电机_运行状态",
    "油泵_右油压":           "采煤机_油泵_右油箱_油压",
    "油泵_左油压":           "采煤机_油泵_左油箱_油压",
    "破碎机_电机_运行状态":  "采煤机_破碎机_电机_运行状态",
    "破碎机_电机_电流":      "采煤机_破碎机_电机_电流",
}


def classify_cutting_part(df: pd.DataFrame, col_map: dict[str, str]) -> pd.Series:
    """截割部_工况：停机 / 待机 / 待机-高位 / 调架中 / 割煤低位 / 割煤中位 / 割煤高位

    判定逻辑（按优先级）：
      停机：所有截割电机停（滚筒电机 & 滚筒运行状态均为 0）
      待机：电机通电但滚筒均不转 + 滚筒最大高度 < 4.5 m
      待机-高位：电机通电但滚筒均不转 + 滚筒最大高度 >= 4.5 m
      调架中：任一滚筒运行 + 速度 <= 0.5 m/min
      割煤低位：任一滚筒运行 + 速度 > 0.5 + 滚筒最大高度 < 3 m
      割煤中位：任一滚筒运行 + 速度 > 0.5 + 3 m <= 滚筒最大高度 < 5 m
      割煤高位：任一滚筒运行 + 速度 > 0.5 + 滚筒最大高度 >= 5 m

    KW 验证：滚筒电流（H≈32000）和采煤机速度（H≈33350）是截割工况最显著的区分参数。
    ARI 优化过程：
      1. 原始 4 态 ARI=0.33 — 规则仅用速度+滚筒运行判定，KMeans 以高度为主聚类维度
      2. 添加待机-高位拆分（4.5m 阈值）→ 5 态 ARI 反降至 0.16（仅待机态对齐不足）
      3. 割煤中按最大高度拆 3 档（3m/5m 阈值）+ 聚类特征中去掉高度 → 7 态 ARI=0.59
      核心：高度是配置参数非工况特征，聚类去掉高度后与运营规则对齐度大幅提升
    """
    right_drum = _is_running(df[col_map["右滚筒_运行状态"]]) if "右滚筒_运行状态" in col_map else pd.Series(False, index=df.index)
    left_drum  = _is_running(df[col_map["左滚筒_运行状态"]]) if "左滚筒_运行状态" in col_map else pd.Series(False, index=df.index)
    any_drum   = right_drum | left_drum

    right_motor = _is_running(df[col_map["右滚筒_电机_运行状态"]]) if "右滚筒_电机_运行状态" in col_map else pd.Series(False, index=df.index)
    left_motor  = _is_running(df[col_map["左滚筒_电机_运行状态"]]) if "左滚筒_电机_运行状态" in col_map else pd.Series(False, index=df.index)
    any_motor   = right_motor | left_motor

    speed_col = col_map.get("采煤机速度", "")
    speed = df.get(speed_col, pd.Series(0.0, index=df.index)).fillna(0).astype(float)

    # 滚筒高度（用于拆分待机 & 割煤中）
    left_height_col = col_map.get("左滚筒_高度", "")
    right_height_col = col_map.get("右滚筒_高度", "")
    left_height = df.get(left_height_col, pd.Series(0.0, index=df.index)).fillna(0).astype(float)
    right_height = df.get(right_height_col, pd.Series(0.0, index=df.index)).fillna(0).astype(float)
    max_height = np.maximum(left_height, right_height)

    cond = pd.Series("停机", index=df.index, dtype="object")
    motor_on_no_drum = ~any_drum & any_motor
    # 待机拆分维度与割煤统一：用左右滚筒最大高度（原先左滚筒高度不对称）
    cond.loc[motor_on_no_drum & (max_height < _config.CUT_HEIGHT_HIGH)] = "待机"
    cond.loc[motor_on_no_drum & (max_height >= _config.CUT_HEIGHT_HIGH)] = "待机-高位"
    cond.loc[any_drum & (speed <= 0.5)] = "调架中"
    cutting = any_drum & (speed > 0.5)
    cond.loc[cutting & (max_height >= _config.CUT_HEIGHT_MID)] = "割煤高位"
    cond.loc[cutting & (max_height >= _config.CUT_HEIGHT_LOW)
            & (max_height < _config.CUT_HEIGHT_MID)] = "割煤中位"
    cond.loc[cutting & (max_height < _config.CUT_HEIGHT_LOW)] = "割煤低位"
    return cond.rename("截割部_工况")


def classify_traction_part(df: pd.DataFrame, col_map: dict[str, str],
                           current_threshold: float | None = None) -> pd.Series:
    """牵引部_工况：停机 / 待机 / 空载牵引 / 重载牵引

    判定逻辑：
      停机：两台牵引电机均不运行
      待机：牵引电机通电但速度为 0
      空载牵引：通电 + 速度 > 0 + 电机总电流 < threshold
      重载牵引：通电 + 速度 > 0 + 电机总电流 >= threshold

    新增空/重载子类：聚类 ARI=0.57 说明已有规则基本合理，
    但加入电流阈值区分负荷强度后，对设备级"空载牵引"判定更精确。
    """
    if current_threshold is None:
        current_threshold = _config.TRACTION_CURRENT_THRESHOLD
    right_motor = _is_running(df[col_map["右电机_运行状态"]]) if "右电机_运行状态" in col_map else pd.Series(False, index=df.index)
    left_motor  = _is_running(df[col_map["左电机_运行状态"]]) if "左电机_运行状态" in col_map else pd.Series(False, index=df.index)
    any_motor   = right_motor | left_motor

    speed_col = col_map.get("采煤机速度", "")
    speed = df.get(speed_col, pd.Series(0.0, index=df.index)).fillna(0).astype(float)

    # 电机总电流（负载指标）
    right_cur = df.get(col_map.get("右电机_电流", ""), pd.Series(0.0, index=df.index)).fillna(0).astype(float)
    left_cur = df.get(col_map.get("左电机_电流", ""), pd.Series(0.0, index=df.index)).fillna(0).astype(float)
    total_current = right_cur + left_cur

    cond = pd.Series("停机", index=df.index, dtype="object")
    cond.loc[any_motor & (speed <= 0)] = "待机"
    running = any_motor & (speed > 0)
    cond.loc[running & (total_current < current_threshold)] = "空载牵引"
    cond.loc[running & (total_current >= current_threshold)] = "重载牵引"
    return cond.rename("牵引部_工况")


def classify_oil_pump_part(df: pd.DataFrame, col_map: dict[str, str],
                           pressure_threshold: float | None = None) -> pd.Series:
    """油泵_工况：停机 / 轻载 / 重载

    判定逻辑：
      停机：泵电机均不运行
      轻载：运行 + 平均油压 < threshold (MPa)
      重载：运行 + 平均油压 >= threshold (MPa)

    新增轻/重载子类：聚类 ARI=0.44 → 加入油压维度区分负载状态。
    KW 检验显示油压是油泵部位最显著的特征参数。
    """
    if pressure_threshold is None:
        pressure_threshold = _config.PUMP_PRESSURE_THRESHOLD
    right = _is_running(df[col_map["油泵_右电机_运行状态"]]) if "油泵_右电机_运行状态" in col_map else pd.Series(False, index=df.index)
    left  = _is_running(df[col_map["油泵_左电机_运行状态"]]) if "油泵_左电机_运行状态" in col_map else pd.Series(False, index=df.index)
    running = right | left

    # 平均油压
    right_p = df.get(col_map.get("油泵_右油压", ""), pd.Series(0.0, index=df.index)).fillna(0).astype(float)
    left_p = df.get(col_map.get("油泵_左油压", ""), pd.Series(0.0, index=df.index)).fillna(0).astype(float)
    avg_pressure = (right_p + left_p) / 2

    cond = pd.Series("停机", index=df.index, dtype="object")
    cond.loc[running & (avg_pressure < pressure_threshold)] = "轻载"
    cond.loc[running & (avg_pressure >= pressure_threshold)] = "重载"
    return cond.rename("油泵_工况")


def classify_crusher_part(df: pd.DataFrame, col_map: dict[str, str],
                           current_threshold: float | None = None) -> pd.Series:
    """破碎机_工况：停机 / 空载运行 / 带载运行

    判定逻辑：
      停机：电机停
      空载：运行 + 电流 < threshold (A)
      带载：运行 + 电流 >= threshold (A)

    KW 验证：电机电流是破碎机最显著参数（H≈9379，远超其他参数 60~190）。
    50A 阈值经验证无误：0/16960 空载点误报，带载中位数 58A 高于阈值。
    ARI=0.350 偏低源于带载样本仅 0.66%（112/17072），划分器准确但少数类分数低。
    """
    if current_threshold is None:
        current_threshold = _config.CRUSHER_CURRENT_THRESHOLD
    run_col = col_map.get("破碎机_电机_运行状态")
    if run_col is None or run_col not in df.columns:
        return pd.Series("停机", index=df.index, dtype="object").rename("破碎机_工况")
    running = _is_running(df[run_col])

    cur_col = col_map.get("破碎机_电机_电流")
    current = df.get(cur_col, pd.Series(0.0, index=df.index)).fillna(0).astype(float)

    cond = pd.Series("停机", index=df.index, dtype="object")
    cond.loc[running & (current < current_threshold)] = "空载运行"
    cond.loc[running & (current >= current_threshold)] = "带载运行"
    return cond.rename("破碎机_工况")


def derive_device_condition(df: pd.DataFrame) -> pd.Series:
    """从 4 个部位列合并推导设备级工况。

    优先级：割煤中 > 正常运行 > 空载牵引 > 待机 > 停机

    部位→设备映射：
      截割部：割煤中/调架中 → 割煤中/正常运行（直接映射）
      牵引部：空载牵引/重载牵引 → 由截割部状态决定是否为空载牵引
      待机/停机 → 直接映射

    空载牵引条件 = 牵引部有牵引动作 + 截割部处于非割煤状态（待机或停机）
    """
    cond = pd.Series("停机", index=df.index, dtype="object")

    trac = df.get("牵引部_工况", "停机")
    cut = df.get("截割部_工况", "停机")

    CUTTING_RUN = ["割煤低位", "割煤中位", "割煤高位"]  # "割煤中" 永不产生（classify_cutting_part 只产 低/中/高位）
    CUTTING_IDLE = ["待机", "待机-高位", "停机"]
    TRAC_RUNNING = ["空载牵引", "重载牵引", "牵引中"]
    TRAC_IDLE = ["停机", "待机"]

    mask_tow = trac.isin(TRAC_RUNNING) & cut.isin(CUTTING_IDLE)
    cond.loc[mask_tow] = "空载牵引"

    mask_standby = (
        (cut == "待机")
        | (trac.isin(TRAC_IDLE) & ~cut.isin(CUTTING_RUN))
    )
    cond.loc[mask_standby & ~mask_tow] = "待机"

    cond.loc[cut == "调架中"] = "正常运行"

    cond.loc[cut.isin(CUTTING_RUN)] = "割煤中"

    return cond.rename("设备_工况")


def _is_traction_idle(val):
    """牵引部是否处于非牵引状态。"""
    return val in ("停机", "待机")


def add_cmj_part_conditions(df: pd.DataFrame) -> pd.DataFrame:
    """为采煤机宽表添加 4 个部位工况列 + 设备级工况列。

    新增列：
      截割部_工况, 牵引部_工况, 油泵_工况, 破碎机_工况, 设备_工况
    """
    col_map = {k: v for k, v in CMJ_COLUMN_ALIAS.items() if v in df.columns}

    parts = {
        "截割部_工况": classify_cutting_part(df, col_map),
        "牵引部_工况": classify_traction_part(df, col_map),
        "油泵_工况":   classify_oil_pump_part(df, col_map),
        "破碎机_工况": classify_crusher_part(df, col_map),
    }
    result = pd.concat([df, pd.DataFrame(parts, index=df.index)], axis=1)
    result["设备_工况"] = derive_device_condition(result)
    return result


# ---------------------------------------------------------------------------
# 转载机工况划分
# ---------------------------------------------------------------------------

ZZJ_COLUMN_ALIAS: dict[str, str] = {
    "运行状态":       "三机_转载机_运行状态",
    "变频器_运行状态": "三机_转载机_变频器_运行状态",
    "电机_电流":      "三机_转载机_电机_电流",
    "电机_转速":      "三机_转载机_电机_转速",
}

ZZJ_COND: list[tuple[str, str]] = [
    ("停机", "运行状态 == 0"),
    ("空载运行", "运行且电流 < 50A"),
    ("带载运行", "运行且电流 >= 50A"),
]


def add_zzj_condition(df: pd.DataFrame, current_threshold: float | None = None) -> pd.DataFrame:
    """为转载机添加工况列：停机 / 空载运行 / 带载运行。"""
    if current_threshold is None:
        current_threshold = _config.ZZJ_CURRENT_THRESHOLD
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
    stats.columns = [f"{col}_{stat}" for col, stat in stats.columns]
    stats = stats.round(4)
    return stats
