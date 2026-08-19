# -*- coding: utf-8 -*-
"""阶段三：事件传导关联模块（辅助）。

输入两种事件源，跨设备时间对齐找传导链：
1. 阶段二 merged_events CSV（单设备异常检测产出，时间戳×工况×方法三维网格）
2. 联合工况规则事件（采煤-转载错配 / 转载余流，从系统宽表按标签提取）

传导假设：上游 CMJ 事件先行 → 下游 ZZJ 事件在 ±window 内跟随。
"""

from __future__ import annotations

import pandas as pd

from src import config


def _segments(mask: pd.Series, idx: pd.DatetimeIndex, gap_min: int,
              tname: str) -> pd.DataFrame:
    """布尔序列 → 事件区间 [start, end]。间隔 > gap_min 分钟则断开。"""
    if not mask.any():
        return pd.DataFrame(columns=[tname, "start", "end", "duration_min",
                                     "n_points"])
    sub = idx[mask]
    delta = sub.to_series().diff().dt.total_seconds() / 60.0
    new_seg = (delta.fillna(999.0) > gap_min).cumsum()
    g = sub.to_series().groupby(new_seg)
    out = g.agg(start="first", end="last", n_points="size").reset_index(drop=True)
    out["duration_min"] = (
        (out["end"] - out["start"]).dt.total_seconds() / 60.0 + 1).round(1)
    out.insert(0, tname, "事件")
    return out


def extract_merged_events(csv_path: str, gap_min: int = 5) -> pd.DataFrame:
    """阶段二 merged_events CSV → 去重后的事件区间。

    原表为 [时间戳, 工况, 方法, 分数, is_anomaly, ...] 三维网格
    （时间戳×工况×方法），同一时刻可能被多种方法标记 → 按时间戳取 any_anomaly。
    """
    df = pd.read_csv(csv_path)
    df["时间戳"] = pd.to_datetime(df["时间戳"])
    # 时间戳级去重：同刻任一本方法判异常即为异常
    any_col = "any_anomaly" if "any_anomaly" in df.columns else "is_anomaly"
    per_ts = (df.sort_values("时间戳").groupby("时间戳")[any_col]
              .any().astype(bool))
    return _segments(per_ts, per_ts.index, gap_min, "事件类型")


def rule_condition_events(sys_df: pd.DataFrame, conds: list[str],
                          gap_min: int = 5) -> pd.DataFrame:
    """联合工况规则事件：按标签提取连续时段。

    错配（割煤中+下游未带载）与余流（上游停机+下游带载）本身即关联异常
    信号，无需回归——标签已编码物理规则。
    """
    mask = sys_df[config.JOINT_COND_COL].isin(conds)
    tname = "规则类型"
    out = _segments(mask, sys_df.index, gap_min, tname)
    if not out.empty:
        out["规则类型"] = "|".join(conds)
    return out


def _type_col(df: pd.DataFrame) -> str:
    """事件表的类型列（第一列，名为 事件类型/规则类型）。"""
    return df.columns[0]


def propagate_events(up_events: pd.DataFrame, down_events: pd.DataFrame,
                     window_min: int = config.PROPAGATION_WINDOW_MIN,
                     lag_max: int = 0) -> pd.DataFrame:
    """上游事件 → 下游跟随 传导链匹配。

    对每条上游事件，找 start 后 [lag_max, lag_max+window_min] 分钟窗口内
    开始的下游事件。返回对齐后的传导链表。
    """
    if up_events.empty or down_events.empty:
        return pd.DataFrame(columns=["上游start", "下游start", "滞后_min",
                                     "上游类型", "下游类型"])
    up_t, dn_t = _type_col(up_events), _type_col(down_events)
    up = up_events.sort_values("start").reset_index(drop=True)
    dn = down_events.sort_values("start").reset_index(drop=True)
    rows = []
    for _, u in up.iterrows():
        lo = u["start"] + pd.Timedelta(minutes=lag_max)
        hi = lo + pd.Timedelta(minutes=window_min)
        hit = dn[(dn["start"] >= lo) & (dn["start"] <= hi)]
        if not hit.empty:
            rows.append({
                "上游start": u["start"],
                "下游start": hit["start"].iloc[0],
                "滞后_min": round((hit["start"].iloc[0] - u["start"])
                                  .total_seconds() / 60.0, 1),
                "上游类型": u[up_t],
                "下游类型": hit[dn_t].iloc[0],
            })
    return pd.DataFrame(rows)


def propagation_stats(chains: pd.DataFrame, n_up: int) -> dict:
    """传导统计：传导率、滞后分布、方向验证（上游应先行）。"""
    if chains.empty:
        return {"n_up": n_up, "n_chain": 0, "rate": 0.0,
                "lag_median": float("nan"), "lag_mean": float("nan")}
    return {
        "n_up": n_up,
        "n_chain": len(chains),
        "rate": round(len(chains) / n_up * 100, 2) if n_up else 0.0,
        "lag_median": float(chains["滞后_min"].median()),
        "lag_mean": float(chains["滞后_min"].mean()),
    }
