# -*- coding: utf-8 -*-
"""阶段二：具体异常事件可视化模块。

把 merge_anomaly_events 产出的长表（merged_events.csv）按连续
any_anomaly 时间戳分组，结构化出"异常事件"（起止时间 / 时长 /
工况 / 触发方法集 / 严重度 / 归因摘要），并为 Top-N 代表事件绘制
±窗口原始参数时序图（z-score 归一堆叠 + 异常区间高亮 + 工况条）。

输出目录：output/phase2/anomaly_events/

纯读函数，不侵入阶段二 pipeline。
"""

from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.patches import Patch

# ── 中文字体链（与 anomaly_viz.py 保持一致） ──
plt.rcParams.update({
    "font.sans-serif": ["Microsoft YaHei", "SimHei", "WenQuanYi Micro Hei",
                        "Noto Sans CJK SC", "DejaVu Sans"],
    "axes.unicode_minus": False,
})

# 相邻异常时间戳间隔 > gap_min 分钟视为新事件
EVENT_GAP_MIN = 1
# 事件窗口前后各外扩分钟数
EVENT_WINDOW_MIN = 30
# 每个部位选取的代表事件数
DEFAULT_TOP_N = 10
# 单图最多绘制的参数数（防止拥挤）
MAX_PARAMS_PER_PLOT = 12

METHOD_COLORS = {
    "Mahalanobis": "#C62828",
    "IsolationForest": "#1565C0",
    "残差": "#2E7D32",
    "单变量IQR+3σ": "#F9A825",
}


def _short_label(col: str) -> str:
    """缩短参数名：去掉设备前缀，便于图上展示。"""
    return (str(col)
            .replace("三机_采煤机_", "")
            .replace("三机_转载机_", ""))


def build_anomaly_events(
    merged_events: pd.DataFrame,
    gap_min: int = EVENT_GAP_MIN,
) -> pd.DataFrame:
    """按连续 any_anomaly=True 时间戳分组，产出结构化事件列表。

    Parameters
    ----------
    merged_events : merge_anomaly_events 输出的长表
        [时间戳, 工况, 方法, 分数, is_anomaly, interpretation, any_anomaly]
        同一时间戳可有多行（不同方法 / 单变量不同参数）。

    Returns
    -------
    pd.DataFrame
        每个事件一行：
        [事件ID, 开始时间, 结束时间, 时长_分钟, 工况, 方法集, 严重度,
         触发行数, 归因摘要]
        事件ID 为 0 起始的连续分组号。
    """
    if merged_events is None or merged_events.empty:
        return pd.DataFrame()

    df = merged_events.copy()
    df["时间戳"] = pd.to_datetime(df["时间戳"])
    ano = df[df["any_anomaly"]].copy()
    if ano.empty:
        return pd.DataFrame()

    # 异常时间戳去重排序，相邻间隔 > gap 断开
    ts = ano["时间戳"].drop_duplicates().sort_values()
    gap = pd.Timedelta(minutes=gap_min)
    breaks = ts.diff() > gap          # 首行为 NaN → False，第一组事件 ID = 0
    # 注意：ts 是 Series（index=原始行号）。不能直接 pd.Series(cumsum, index=ts)——
    # data 是 Series 时 pandas 会按 ts 的值 reindex（行号 vs 时间戳无交集 → 全 NaN）。
    # breaks 与 ts 同序，用 to_numpy() 按位置配对即可。
    ts_event = pd.Series(breaks.cumsum().to_numpy(), index=ts.to_numpy())
    # 按时间戳映射回所有行（同一时间戳多方法/多参数行共享事件 ID，
    # 直接对去重索引 groupby 会让重复时间戳行对齐到 NaN 被丢弃）
    event_ids = ano["时间戳"].map(ts_event)

    records = []
    for eid, group in ano.groupby(event_ids):
        g_start = group["时间戳"].min()
        g_end = group["时间戳"].max()
        methods = sorted(group["方法"].dropna().unique().tolist())
        sev = float(group["分数"].max())
        top = group.loc[group["分数"].idxmax()]
        records.append({
            "事件ID": int(eid),
            "开始时间": g_start,
            "结束时间": g_end,
            "时长_分钟": round((g_end - g_start).total_seconds() / 60.0 + 1, 1),
            "工况": str(top.get("工况", "")),
            "方法集": "; ".join(methods),
            "严重度": round(sev, 3),
            "触发行数": int(len(group)),
            "归因摘要": str(top.get("interpretation", ""))[:120],
        })
    return pd.DataFrame(records)


def select_top_events(
    events: pd.DataFrame,
    top_n: int = DEFAULT_TOP_N,
) -> pd.DataFrame:
    """按时长 × log1p(严重度) 打分排序，取 Top-N 代表事件。

    时长优先（长时持续异常更值得看），严重度取对数压缩
    （Mahalanobis 分数可到几十，单变量 z-score 通常在个位数）。
    """
    if events is None or events.empty:
        return pd.DataFrame()
    ev = events.copy()
    sev = pd.to_numeric(ev["严重度"], errors="coerce").fillna(0.0).clip(lower=1e-9)
    dur = pd.to_numeric(ev["时长_分钟"], errors="coerce").fillna(1.0).clip(lower=1.0)
    ev["_score"] = dur * np.log1p(sev)
    ev = ev.sort_values("_score", ascending=False).drop(columns="_score")
    return ev.head(top_n).reset_index(drop=True)


def plot_event_window(
    event_row: pd.Series,
    raw_wide: pd.DataFrame,
    monitor_cols: list[str],
    output_path: str | Path,
    window_min: int = EVENT_WINDOW_MIN,
    cond_col: str = "工况",
) -> Path | None:
    """绘制单个异常事件的 ±窗口原始参数时序图。

    Parameters
    ----------
    event_row : build_anomaly_events 产出的单行（Series）
    raw_wide : 带工况宽表（DatetimeIndex，含 monitor 参数列与 cond_col）
    monitor_cols : 该部位监测参数列
    output_path : 输出 PNG 路径
    window_min : 事件前后各外扩分钟数
    cond_col : 工况列名

    图结构（2 子图，共享 x 轴）：
      上：监测参数 z-score 归一堆叠折线，红色半透明条高亮异常区间
      下：工况台阶条
    图注：事件 ID / 工况 / 起止时间 / 时长 / 严重度 / 方法集 / 归因摘要
    """
    output_path = Path(output_path)
    left = pd.Timestamp(event_row["开始时间"]) - pd.Timedelta(minutes=window_min)
    right = pd.Timestamp(event_row["结束时间"]) + pd.Timedelta(minutes=window_min)
    win = raw_wide.loc[left:right].copy()
    if win.empty:
        return None

    params = [c for c in monitor_cols
              if c in win.columns and pd.api.types.is_numeric_dtype(win[c])]
    params = [c for c in params if win[c].nunique() > 1]
    if not params:
        return None
    params = params[:MAX_PARAMS_PER_PLOT]

    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(16, 8), sharex=True,
        gridspec_kw={"height_ratios": [3, 1]},
    )

    # ── 上子图：z-score 归一堆叠 ──
    offset = 0.0
    yticks, ylabels = [], []
    for p in params:
        vals = win[p].values.astype(float)
        s = np.nanstd(vals)
        m = np.nanmean(vals)
        z = (vals - m) / s if s > 1e-12 else np.zeros(len(vals))
        ax1.plot(win.index, z + offset, linewidth=1.0)
        yticks.append(offset)
        ylabels.append(_short_label(p))
        offset += 2.2
    ax1.set_yticks(yticks)
    ax1.set_yticklabels(ylabels, fontsize=7)

    ev_start = pd.Timestamp(event_row["开始时间"])
    ev_end = pd.Timestamp(event_row["结束时间"])
    ax1.axvspan(ev_start, ev_end, color="#C62828", alpha=0.15)
    ax1.axvline(ev_start, color="#C62828", linestyle="--", linewidth=0.8, alpha=0.6)
    ax1.axvline(ev_end, color="#C62828", linestyle="--", linewidth=0.8, alpha=0.6)

    ax1.set_title(
        f"事件 {event_row['事件ID']}  工况={event_row['工况']}  "
        f"[{ev_start:%m-%d %H:%M} ~ {ev_end:%m-%d %H:%M}]  "
        f"时长={event_row['时长_分钟']}min  严重度={event_row['严重度']}\n"
        f"方法集: {event_row['方法集']}  归因: {event_row['归因摘要']}",
        fontsize=10,
    )
    ax1.grid(True, alpha=0.3)

    # ── 下子图：工况台阶条 ──
    cond = win.get(cond_col, pd.Series("未知", index=win.index)).fillna("未知")
    codes, uniq = pd.factorize(cond.values)
    n_uniq = len(uniq)
    palette = plt.cm.tab20(np.linspace(0, 1, max(n_uniq, 1)))
    step_idx = np.arange(len(win) + 1)
    step_idx[-1] = len(win) - 1
    for i in range(len(win)):
        ax2.axvspan(win.index[i], win.index[min(i + 1, len(win) - 1)],
                    color=palette[codes[i]], linewidth=0)
    ax2.set_yticks([])
    ax2.set_ylabel("工况", fontsize=9)
    ax2.set_ylim(0, 1)
    handles = [Patch(facecolor=palette[i], label=str(uniq[i]))
               for i in range(n_uniq)]
    ax2.legend(handles=handles, loc="upper right", fontsize=7, ncol=3)

    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d %H:%M"))
    ax2.xaxis.set_major_locator(mdates.AutoDateLocator())

    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, bbox_inches="tight", dpi=130)
    plt.close(fig)
    return output_path
