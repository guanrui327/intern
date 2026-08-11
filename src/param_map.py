# -*- coding: utf-8 -*-
"""参数层级图谱与分部位参数展示。

将采煤机 / 转载机测点按照命名规则
  「设备_部位_组件_传感器_指标」
解析为层次结构，支持可视化和导出。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# 命名解析
# ---------------------------------------------------------------------------

CMJ_PREFIX = "采煤机_"
ZZJ_PREFIX = "三机_"
KNOWN_PARTS = {
    "截割部位", "牵引部位", "油泵", "破碎机", "采煤机倾角",
    "转载机", "功能", "虚拟点", "干预状态",
}


def parse_point_name(name: str) -> dict[str, str]:
    """将完整测点名解析为层级分量。

    格式：［设备_］部位［_组件［_传感器［_指标］］］

    Returns
    -------
    字典，键: device, part, component, sensor, metric
    缺少的层级置空字符串。
    """
    result: dict[str, str] = {
        "device": "", "part": "", "component": "",
        "sensor": "", "metric": "",
    }

    if name.startswith(CMJ_PREFIX):
        result["device"] = "采煤机"
        rest = name[len(CMJ_PREFIX):]
    elif name.startswith(ZZJ_PREFIX):
        result["device"] = "三机"
        rest = name[len(ZZJ_PREFIX):]
    else:
        result["device"] = name
        return result

    segments = rest.split("_")

    # 前 1-2 段是部位
    if not segments:
        return result

    # 尝试匹配已知部位名（可能为单字部位如"油泵"）
    part_detected = segments[0] in KNOWN_PARTS
    if part_detected:
        result["part"] = segments[0]
        seg_idx = 1
    elif len(segments) >= 2 and f"{segments[0]}_{segments[1]}" in KNOWN_PARTS:
        result["part"] = f"{segments[0]}_{segments[1]}"
        seg_idx = 2
    else:
        result["part"] = segments[0]
        seg_idx = 1

    remaining = segments[seg_idx:]

    if not remaining:
        return result

    # 尝试组件 → 传感器 → 指标
    # 规则：传感器/指标以 电机_XXX、油箱_XXX、IGBT、冷却水 等关键词结尾
    sensor_keywords = {"电机", "油箱", "变频器", "冷却水", "减速器"}
    metric_keywords = {"电流", "温度", "电压", "转速", "转矩", "角度", "高度",
                       "油压", "油位", "流量", "压力", "速度", "方向", "位置架号",
                       "位置米数", "状态", "俯仰角", "运行状态", "链条速度",
                       "记忆割煤状态"}

    # 确定指标段（最后一段或最后两段）
    # 常见模式: 右滚筒_电机_电流 → comp=右滚筒, sensor=电机, metric=电流
    #          右电机_运行状态   → comp=右电机, metric=运行状态
    #          采煤机速度        → metric=采煤机速度 (component为空)
    def _is_metric(s: str) -> bool:
        return any(kw in s for kw in metric_keywords)

    def _is_sensor(s: str) -> bool:
        return s in sensor_keywords

    # 从后往前匹配
    if len(remaining) >= 3:
        # 可能: 组件_传感器_指标
        if _is_metric(remaining[-1]) and _is_sensor(remaining[-2]):
            result["component"] = "_".join(remaining[:-2])
            result["sensor"] = remaining[-2]
            result["metric"] = remaining[-1]
        else:
            result["component"] = "_".join(remaining[:-1])
            result["metric"] = remaining[-1]
    elif len(remaining) == 2:
        if _is_metric(remaining[-1]):
            result["component"] = remaining[0]
            result["metric"] = remaining[1]
        else:
            result["component"] = "_".join(remaining)
    else:  # 1 segment
        result["metric"] = remaining[0]

    return result


# ---------------------------------------------------------------------------
# 构建层级树
# ---------------------------------------------------------------------------

def build_param_hierarchy(point_names: list[str]) -> pd.DataFrame:
    """解析测点名列表，输出层级关系表。

    Returns
    -------
    DataFrame，列: [设备, 部位, 组件, 传感器, 指标, 原始列名]
    """
    rows = []
    for name in point_names:
        parsed = parse_point_name(name)
        parsed["原始列名"] = name
        rows.append(parsed)
    return pd.DataFrame(rows)


def hierarchy_tree_dict(rows: pd.DataFrame) -> dict[str, Any]:
    """将层级表转为嵌套字典，便于绘图。"""
    tree: dict[str, Any] = {}
    for _, row in rows.iterrows():
        device = row.get("device", "") or "未知"
        part = row.get("part", "") or "其他"
        comp = row.get("component", "") or "(直接)"
        metric = row.get("metric", "") or row.get("原始列名", "")

        tree.setdefault(device, {})
        tree[device].setdefault(part, {})
        tree[device][part].setdefault(comp, [])
        if metric and metric not in tree[device][part][comp]:
            tree[device][part][comp].append(metric)
    return tree


# ---------------------------------------------------------------------------
# 可视化
# ---------------------------------------------------------------------------

# 部位配色
PART_COLORS = {
    "截割部位": "#2196F3",
    "牵引部位": "#FF9800",
    "油泵": "#4CAF50",
    "破碎机": "#9C27B0",
    "采煤机倾角": "#00BCD4",
    "转载机": "#607D8B",
    "功能": "#795548",
    "虚拟点": "#9E9E9E",
    "干预状态": "#E91E63",
}


def plot_param_hierarchy(
    tree: dict[str, Any],
    title: str = "设备参数层级图谱",
    output_path: str | Path | None = None,
    highlight_params: set[str] | None = None,
) -> plt.Figure:
    """绘制参数层级树状图（水平树形布局 — 体现层级嵌套关系）。"""
    from collections import defaultdict

    if not tree:
        fig, ax = plt.subplots(figsize=(6, 2))
        ax.text(0.5, 0.5, "无参数层级数据", ha="center", va="center")
        return fig

    # ── 1. 展平为 leaf paths ──────────────────────────────────
    paths: list[list[str]] = []               # [device, part, comp, metric]
    for device, parts_dict in tree.items():
        for part, comp_dict in parts_dict.items():
            comps = comp_dict if comp_dict else {"(直接参数)": []}
            for comp, metrics in comps.items():
                m_list = metrics if metrics else [""]
                for metric in m_list:
                    paths.append([device, part, comp, metric])

    if not paths:
        fig, ax = plt.subplots(figsize=(6, 2))
        ax.text(0.5, 0.5, "无参数层级数据", ha="center", va="center")
        return fig

    # ── 2. 去重节点 ────────────────────────────────────────────
    # 收集所有唯一节点（level 0-3）
    all_nodes: list[dict] = []
    seen_ids: set[str] = set()

    def _ensure(path: list[str], lvl: int) -> str:
        node_id = f"L{lvl}_{path[lvl]}"
        if node_id not in seen_ids:
            seen_ids.add(node_id)
            all_nodes.append({
                "id": node_id,
                "label": path[lvl],
                "level": lvl,
                "parent": _ensure(path, lvl - 1) if lvl > 0 else None,
                "children": [],
            })
        return node_id

    # 注册根节点（设备级）
    _ensure(paths[0], 0)
    for p in paths:
        for lvl in range(1, 4):
            _ensure(p, lvl)

    # 建立子节点列表
    node_map = {n["id"]: n for n in all_nodes}
    for p in paths:
        for lvl in range(1, 4):
            pid = _ensure(p, lvl - 1)
            cid = _ensure(p, lvl)
            if cid not in node_map[pid]["children"]:
                node_map[pid]["children"].append(cid)

    # ── 3. 递归计算 y 位置 ────────────────────────────────────
    def _assign_y(node_id: str) -> float:
        """返回节点占据的总高度。叶子 = 1，非叶子 = sum(children)。"""
        node = node_map[node_id]
        children = node["children"]
        if not children:
            node["y"] = _y_counter[0]
            _y_counter[0] += 1
            node["height"] = 1.0
            return 1.0
        total_h = sum(_assign_y(c) for c in children)
        first_y = node_map[children[0]]["y"]
        last_y = node_map[children[-1]]["y"]
        node["y"] = (first_y + last_y) / 2
        node["height"] = total_h
        return total_h

    _y_counter = [0.0]
    for root_id in [n["id"] for n in all_nodes if n["level"] == 0]:
        _assign_y(root_id)

    # 把 y 转为绘图坐标（翻转 y 轴方向）
    for n in all_nodes:
        n["y"] = -n["y"]

    # 层级 x 坐标
    LEVEL_X = {0: 0.5, 1: 3.0, 2: 6.5, 3: 10.5}

    # ── 4. 标记高亮路径（分类参数红显） ──────────────────────
    highlighted_ids: set[str] = set()
    if highlight_params:
        for n in all_nodes:
            if n["level"] == 3 and n["label"] in highlight_params:
                highlighted_ids.add(n["id"])
                # 回溯祖先链
                pid = n["parent"]
                while pid:
                    highlighted_ids.add(pid)
                    pid = node_map[pid]["parent"]

    def _is_highlighted(node_id: str) -> bool:
        return node_id in highlighted_ids

    # ── 5. 绘图 ────────────────────────────────────────────────
    total_metrics = sum(1 for n in all_nodes if n["level"] == 3)
    fig_h = max(4, total_metrics * 0.28 + 1)
    fig_w = 14

    fig, ax = plt.subplots(figsize=(fig_w, fig_h))
    ax.set_xlim(-1, 13)
    y_pad = 0.5
    all_ys = [n["y"] for n in all_nodes]
    if all_ys:
        ax.set_ylim(min(all_ys) - y_pad, max(all_ys) + y_pad)
    ax.axis("off")
    ax.set_title(title, fontsize=13, fontweight="bold", pad=15)

    # ── 节点样式 ────────────────────────────────────────────────
    LEVEL_STYLES = {
        0: {"size": 0.35, "fontsize": 11, "weight": "bold", "face": "#37474F", "edge": "none", "text": "white"},
        1: {"size": 0.30, "fontsize": 9, "weight": "bold", "edge": "none", "text": "white"},
        2: {"size": 0.22, "fontsize": 7.5, "weight": "normal", "face": "#ECEFF1", "edge": "#90A4AE", "text": "#37474F"},
        3: {"size": 0.18, "fontsize": 6.5, "weight": "normal", "face": "none", "edge": "none", "text": "#546E7A"},
    }

    for n in all_nodes:
        x = LEVEL_X.get(n["level"], 8)
        y = n["y"]
        style = LEVEL_STYLES.get(n["level"], LEVEL_STYLES[3])

        # 部位专用配色
        facecolor = style.get("face", "#ECEFF1")
        textcolor = style["text"]
        if n["level"] == 1:
            part_label = n["label"]
            facecolor = PART_COLORS.get(part_label, "#9E9E9E")
            textcolor = "white"
            # 用半透明渐变色
            facecolor_light = _lighten_color(facecolor, 0.7)
        elif n["level"] == 2:
            # 子部件使用其父部位的颜色（淡色）
            parent_id = n["parent"]
            if parent_id and parent_id in node_map:
                parent_label = node_map[parent_id]["label"]
                facecolor = PART_COLORS.get(parent_label, "#ECEFF1")
                facecolor = _lighten_color(facecolor, 0.3)

        # 画椭圆 / 圆角框
        is_hl = _is_highlighted(n["id"])
        if n["level"] <= 2 and n["label"]:
            bw = len(n["label"]) * 0.085 + 0.2
            bh = style["size"]
            hl_edge = "#E53935" if is_hl else style["edge"]
            hl_lw = 1.5 if is_hl else 0.6
            rect = mpatches.FancyBboxPatch(
                (x - bw / 2, y - bh / 2), bw, bh,
                boxstyle="round,pad=0.04",
                facecolor=facecolor, edgecolor=hl_edge,
                linewidth=hl_lw, alpha=0.9,
            )
            ax.add_patch(rect)
            ax.text(x, y, n["label"], ha="center", va="center",
                    fontsize=style["fontsize"], fontweight=style["weight"],
                    color=textcolor)

        # 指标级：只画文字，不画框
        if n["level"] == 3 and n["label"]:
            leaf_color = "#E53935" if is_hl else "#546E7A"
            ax.text(x + 0.1, y, n["label"], ha="left", va="center",
                    fontsize=6.5, color=leaf_color)

        # ── 画连接线（parent → child） ──
        if n["parent"] and n["parent"] in node_map:
            px = LEVEL_X.get(node_map[n["parent"]]["level"], 0)
            py = node_map[n["parent"]]["y"]
            cx = x
            cy = y
            # 高亮路径：parent 和 child 都在 highlighted_ids 中时为红线
            hl_line = (
                _is_highlighted(n["id"])
                and _is_highlighted(n["parent"])
            )
            line_color = "#E53935" if hl_line else "#90A4AE"
            line_alpha = 0.8 if hl_line else 0.5
            # 用贝塞尔曲线或折线
            mid_x = (px + cx) / 2
            ax.plot([px, mid_x, mid_x, cx],
                    [py, py, cy, cy],
                    color=line_color, linewidth=0.6, alpha=line_alpha,
                    solid_joinstyle="round")

    # ── 层级标签 ──
    LEVEL_LABELS = {0: "设备", 1: "部位", 2: "组件", 3: "指标"}
    for lvl, label in LEVEL_LABELS.items():
        x = LEVEL_X[lvl]
        if lvl == 3:
            x += 0.1  # 对齐文本
        ax.text(x, max(all_ys) + y_pad * 0.8, label,
                ha="center", va="bottom", fontsize=9, fontweight="bold",
                color="#78909C")

    # 底部标注
    ax.text(0, min(all_ys) - y_pad * 0.6,
            f"共 {sum(1 for n in all_nodes if n['level']==3)} 个监测指标",
            fontsize=8, color="#9E9E9E")

    fig.tight_layout()
    if output_path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(output_path, bbox_inches="tight", dpi=130)
    plt.close(fig)
    return fig


def _lighten_color(hex_color: str, factor: float = 0.5) -> str:
    """使 hex 颜色变亮（混入白色）。factor=1 → 白, factor=0 → 原色。"""
    import matplotlib.colors as mcolors
    try:
        rgb = mcolors.hex2color(hex_color)
        lightened = tuple(c + (1 - c) * factor for c in rgb)
        return mcolors.rgb2hex(lightened)
    except Exception:
        return hex_color


def plot_param_hierarchy_table(
    rows: pd.DataFrame,
    title: str = "设备参数层级表",
    output_path: str | Path | None = None,
) -> plt.Figure:
    """将层级关系表渲染为表格图。"""
    display_cols = ["设备", "部位", "组件", "传感器", "指标"]
    available = [c for c in display_cols if c in rows.columns]

    display = rows[available + ["原始列名"]].copy()
    for c in available:
        display[c] = display[c].fillna("").replace("", "-")
    display["原始列名"] = display["原始列名"].str.slice(-40)

    fig, ax = plt.subplots(figsize=(max(10, len(available) * 2.5), len(display) * 0.28 + 2))
    ax.axis("off")

    # 表格
    col_labels = available + ["原始列名(截短)"]
    cell_text = display.values.tolist()
    table = ax.table(
        cellText=cell_text,
        colLabels=col_labels,
        cellLoc="left",
        loc="center",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(7)
    table.scale(1, 1.2)

    # 表头着色
    for j in range(len(col_labels)):
        table[0, j].set_facecolor("#37474F")
        table[0, j].set_text_props(color="white", fontweight="bold")

    ax.set_title(title, fontsize=11, fontweight="bold", pad=15)
    fig.tight_layout()

    if output_path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(output_path, bbox_inches="tight", dpi=130)
    return fig


def generate_param_hierarchy(
    all_point_names: list[str],
    output_dir: Path,
    *,
    highlight_params: set[str] | None = None,
) -> dict:
    """完整分析：解析 → 保存CSV → 绘图 → 返回路径。

    Parameters
    ----------
    highlight_params : set[str] | None
        若传入，这些指标名称在层级图中以红色高亮。
    """
    rows = build_param_hierarchy(all_point_names)
    # 只保留监测点和状态点（过滤掉虚拟点等）
    param_csv = output_dir / "param_hierarchy.csv"
    rows.to_csv(param_csv, index=False, encoding="utf-8-sig")

    # 绘图
    tree = hierarchy_tree_dict(rows)
    tree_png = output_dir / "param_hierarchy.png"
    plot_param_hierarchy(tree, output_path=tree_png,
                         highlight_params=highlight_params)

    table_png = output_dir / "param_hierarchy_table.png"
    plot_param_hierarchy_table(rows, output_path=table_png)

    return {
        "hierarchy_df": rows,
        "hierarchy_csv": param_csv,
        "hierarchy_tree_png": tree_png,
        "hierarchy_table_png": table_png,
    }
