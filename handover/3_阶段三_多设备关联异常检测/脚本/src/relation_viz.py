# -*- coding: utf-8 -*-
"""阶段三：跨设备关联可视化模块。

图：
1. 联合工况堆叠面积图（全局 4 周）
2. 双设备叠加时间线（CMJ 速度/电流 + ZZJ 电流，错配事件区间标注）
3. 产量-负载散点图（生产运行 vs 错配，展示恒流带 / 错配断流）
4. 事件传导时序图（CMJ 先行 → ZZJ 跟随 链）
"""

from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
import pandas as pd

from matplotlib.patches import Patch

plt.rcParams.update({
    "font.sans-serif": ["Microsoft YaHei", "SimHei", "WenQuanYi Micro Hei",
                        "Noto Sans CJK SC", "DejaVu Sans"],
    "axes.unicode_minus": False,
})

# 联合工况配色（与物理语义对齐）
COND_COLORS = {
    "生产运行": "#2E86AB",   # 蓝：正常采煤
    "全线停机": "#6C757D",   # 灰：停产
    "转载余流": "#F6AE2D",   # 黄：滞后余流
    "采煤-转载错配": "#E85D75",  # 红：堵煤/断链风险
    "空载循环": "#8C7A6B",   # 棕：空转
    "全线待机": "#B5B8C0",   # 浅灰：待机
    "过渡态": "#333333",     # 黑：异常映射（应为零）
}


def _save(fig, out_path: str | Path) -> None:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=140, bbox_inches="tight")
    plt.close(fig)
    print(f"[Viz] 已保存: {out_path}")


def plot_joint_condition_stack(sys_df: pd.DataFrame,
                               out_path: str | Path) -> plt.Figure:
    """联合工况堆叠面积图：一周采样（整月过密，取 04-01~04-07）。"""
    cond_col = "联合工况"
    w = sys_df.loc["2024-04-01":"2024-04-07"]
    w = w.sort_index()
    order = ["生产运行", "转载余流", "采煤-转载错配", "空载循环",
             "全线待机", "全线停机", "过渡态"]
    t = w.index
    fig, ax = plt.subplots(figsize=(16, 4.5))
    bottom = np.zeros(len(w))
    for c in order:
        if c not in w[cond_col].value_counts():
            continue
        y = (w[cond_col] == c).astype(float).values
        ax.fill_between(t, bottom, bottom + y, label=c, color=COND_COLORS.get(c),
                        step="post")
        bottom += y
    ax.set_ylabel("状态（0/1 堆叠）")
    ax.set_title("联合系统工况堆叠（2024-04-01 ~ 04-07 采样）")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
    ax.legend(ncol=7, loc="upper center", fontsize=8, frameon=False)
    ax.set_ylim(0, 1.02)
    ax.grid(axis="y", alpha=0.3)
    _save(fig, out_path)
    return fig


def plot_cmj_zzj_timeline(sys_df: pd.DataFrame, rule_events: pd.DataFrame,
                          start: str, end: str,
                          out_path: str | Path) -> plt.Figure:
    """双设备叠加时间线：CMJ 速度/电流 + ZZJ 电流，错配区间红色标注。"""
    w = sys_df.loc[start:end]
    cmj_speed = "采煤机_牵引部位_采煤机速度"
    cmj_cur = "采煤机_截割部位_右滚筒_电机_电流"
    zzj_cur = "三机_转载机_电机_电流"
    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(16, 6.5), sharex=True,
        gridspec_kw={"height_ratios": [1, 1]})

    # 错配事件区间（红底标注）
    if rule_events is not None and not rule_events.empty:
        mis = rule_events[rule_events["规则类型"].str.contains("错配")]
        for _, ev in mis.iterrows():
            s, e = ev["start"], ev["end"]
            if e < pd.Timestamp(start) or s > pd.Timestamp(end):
                continue
            s = max(s, pd.Timestamp(start))
            e = min(e, pd.Timestamp(end))
            for ax in (ax1, ax2):
                ax.axvspan(s, e, color="#E85D75", alpha=0.25)

    ax1.plot(w.index, w[cmj_speed], color="#2E86AB", lw=0.8, label="CMJ 牵引速度")
    ax1.plot(w.index, w[cmj_cur].clip(upper=400), color="#8E44AD", lw=0.6,
             alpha=0.7, label="CMJ 右滚筒电流(clip 400A)")
    ax1.set_ylabel("CMJ（速度 m/min / 电流 A）")
    ax1.legend(loc="upper left", fontsize=8)
    ax1.grid(alpha=0.3)

    ax2.plot(w.index, w[zzj_cur], color="#2ECC71", lw=0.8, label="ZZJ 转载机电流")
    ax2.set_ylabel("ZZJ 电流（A）")
    ax2.set_xlabel("时间")
    ax2.legend(loc="upper left", fontsize=8)
    ax2.grid(alpha=0.3)
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d %H:%M"))
    fig.autofmt_xdate()
    fig.suptitle(f"CMJ→ZZJ 关联时间线（{start} ~ {end}）红区=采煤-转载错配",
                 fontsize=12)
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    _save(fig, out_path)
    return fig


def plot_coupling_scatter(sys_df: pd.DataFrame,
                          out_path: str | Path) -> plt.Figure:
    """产量-负载散点：生产运行（恒流带） vs 错配（断流）。

    左图：恒流控制下 ZZJ 电流在 80~86A 窄带，与上游速度幅度无关；
    右图：错配时上游高速割煤但下游电流≈0（关联异常铁证）。
    """
    cond_col = "联合工况"
    cmj_speed = "采煤机_牵引部位_采煤机速度"
    zzj_cur = "三机_转载机_电机_电流"

    prod = sys_df[sys_df[cond_col] == "生产运行"]
    mis = sys_df[sys_df[cond_col] == "采煤-转载错配"]

    fig, axes = plt.subplots(1, 2, figsize=(15, 5.5))
    # 左：生产运行，用二维直方图展示密度（点太多会糊）
    ax = axes[0]
    h = ax.hist2d(prod[cmj_speed], prod[zzj_cur], bins=(60, 40),
                  cmap="Blues", density=True, vmax=0.5)
    cb = fig.colorbar(h[3], ax=ax, shrink=0.8)
    cb.set_label("点密度")
    ax.set_xlabel("CMJ 牵引速度（m/min）")
    ax.set_ylabel("ZZJ 转载机电流（A）")
    ax.set_title("生产运行：恒流带（电流≈80-86A 与速度无关）")
    # 右：错配
    ax = axes[1]
    ax.scatter(mis[cmj_speed], mis[zzj_cur], s=8, c="#E85D75", alpha=0.5)
    ax.set_xlabel("CMJ 牵引速度（m/min）")
    ax.set_ylabel("ZZJ 转载机电流（A）")
    ax.set_title("采煤-转载错配：上游高速割煤但下游电流≈0")
    ax.grid(alpha=0.3)
    fig.suptitle("物理耦合二元层：割煤 <-> 带载（幅度层被恒流控制抹平）", fontsize=12)
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    _save(fig, out_path)
    return fig


def plot_propagation_chains(chains: pd.DataFrame,
                            out_path: str | Path) -> plt.Figure:
    """事件传导时序图：每条链 上游start → 下游start 的滞后分布。"""
    if chains is None or chains.empty:
        fig, ax = plt.subplots(figsize=(12, 4))
        ax.text(0.5, 0.5, "无传导链", ha="center", va="center")
        _save(fig, out_path)
        return fig
    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(14, 7),
        gridspec_kw={"height_ratios": [1.4, 1]})
    # 上：滞后直方图
    lag = chains["滞后_min"]
    ax1.hist(lag, bins=min(30, lag.nunique()), color="#2E86AB", alpha=0.8)
    ax1.axvline(lag.median(), color="#E85D75", ls="--", lw=1.2,
                label=f"中位 {lag.median():.0f} min")
    ax1.set_xlabel("滞后（上游 start → 下游 start，min）")
    ax1.set_ylabel("链数")
    ax1.set_title(f"CMJ→ZZJ 传导滞后分布（{len(chains)} 条链）")
    ax1.legend()
    ax1.grid(alpha=0.3)
    # 下：链的时间分布
    ax2.scatter(chains["上游start"], np.ones(len(chains)), s=10,
                c=chains["滞后_min"], cmap="viridis", alpha=0.7)
    ax2.set_yticks([])
    ax2.set_ylabel("链")
    ax2.set_xlabel("上游事件 start")
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
    fig.autofmt_xdate()
    fig.tight_layout()
    _save(fig, out_path)
    return fig
