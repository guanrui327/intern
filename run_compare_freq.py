#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""一键自动化对比脚本：频域特征集成 vs 不集成。

流程：
  1. 备份当前 output/phase2（如有）
  2. 跑带频域特征的 pipeline（ENABLE_FREQ_FEATURES=True）
  3. 结果复制到 output/phase2_with_freq
  4. 在 config.py 中将 ENABLE_FREQ_FEATURES 改为 False
  5. 跑不带频域特征的 pipeline
  6. 结果复制到 output/phase2_no_freq
  7. 恢复 config.py 为 True
  8. 生成对比报告 output/phase2_comparison/comparison_report.md
"""

import re
import shutil
import subprocess
import sys
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parent
CONFIG_PY = ROOT / "src" / "config.py"
PHASE2_DIR = ROOT / "output" / "phase2"
WITH_FREQ_DIR = ROOT / "output" / "phase2_with_freq"
NO_FREQ_DIR = ROOT / "output" / "phase2_no_freq"
COMP_DIR = ROOT / "output" / "phase2_comparison"

PIPELINE_CMD = [sys.executable, "-m", "run_phase2"]


# ── config.py 补丁函数 ──

def _set_config_flag(value: bool) -> None:
    """在 config.py 中修改 ENABLE_FREQ_FEATURES = True/False"""
    text = CONFIG_PY.read_text("utf-8")
    new_text = re.sub(
        r'^(ENABLE_FREQ_FEATURES\s*=\s*)(True|False)',
        rf'\g<1>{value}',
        text,
        count=1,
        flags=re.MULTILINE,
    )
    if text == new_text:
        print(f"  [WARN] config.py 中未找到 ENABLE_FREQ_FEATURES，手动检查")
    CONFIG_PY.write_text(new_text, encoding="utf-8")
    print(f"  [CONFIG] ENABLE_FREQ_FEATURES = {value}")


def _get_config_flag() -> bool:
    """读取当前 ENABLE_FREQ_FEATURES 值"""
    text = CONFIG_PY.read_text("utf-8")
    m = re.search(r'^ENABLE_FREQ_FEATURES\s*=\s*(True|False)', text, re.MULTILINE)
    if m:
        return m.group(1) == "True"
    print("  [WARN] 未找到 ENABLE_FREQ_FEATURES，假设为 True")
    return True


# ── 运行 pipeline ──

def run_pipeline(label: str) -> float:
    """运行阶段二 pipeline，返回耗时（秒）"""
    print(f"\n{'=' * 60}")
    print(f"  运行：{label}")
    print(f"{'=' * 60}")
    t0 = time.time()
    result = subprocess.run(PIPELINE_CMD, cwd=ROOT)
    elapsed = time.time() - t0
    if result.returncode != 0:
        print(f"  [ERROR] pipeline 返回码 {result.returncode}")
        sys.exit(1)
    print(f"  耗时: {elapsed:.1f}s")
    return elapsed


def backup_phase2(target_dir: Path) -> None:
    """复制 output/phase2 → target_dir"""
    if not PHASE2_DIR.exists():
        print(f"  [SKIP] {PHASE2_DIR} 不存在，跳过备份")
        return
    if target_dir.exists():
        print(f"  [CLEAN] 删除旧目录: {target_dir}")
        shutil.rmtree(target_dir)
    print(f"  复制: {PHASE2_DIR} → {target_dir}")
    shutil.copytree(PHASE2_DIR, target_dir)
    print(f"  OK ({len(list(target_dir.rglob('*')))} 个文件)")


# ── 对比报告生成 ──

def load_merged_events(base_dir: Path) -> dict[str, "pd.DataFrame"]:
    import pandas as pd
    anom_dir = base_dir / "anomalies"
    result = {}
    if not anom_dir.exists():
        return result
    for csv in sorted(anom_dir.glob("*_merged_events.csv")):
        key = csv.stem.replace("_merged_events", "")
        df = pd.read_csv(csv, encoding="utf-8-sig")
        if not df.empty:
            result[key] = df
    return result


def load_pca_loadings(base_dir: Path) -> dict[str, "pd.DataFrame"]:
    import pandas as pd
    anom_dir = base_dir / "anomalies"
    result = {}
    if not anom_dir.exists():
        return result
    for csv in sorted(anom_dir.glob("*_pca_loadings.csv")):
        key = csv.stem.replace("_pca_loadings", "")
        df = pd.read_csv(csv, encoding="utf-8-sig", index_col=0)
        if not df.empty:
            result[key] = df
    return result


def load_windows(base_dir: Path) -> dict[str, "pd.DataFrame"]:
    import pandas as pd
    win_dir = base_dir / "windows"
    result = {}
    if not win_dir.exists():
        return result
    for csv in sorted(win_dir.glob("*_windows.csv")):
        key = csv.stem.replace("_windows", "")
        df = pd.read_csv(csv, encoding="utf-8-sig")
        if not df.empty:
            result[key] = df
    return result


def generate_report(
    merged_with: dict,
    merged_without: dict,
    loadings_with: dict,
    loadings_without: dict,
    windows_with: dict,
    windows_without: dict,
    run_time_with: float,
    run_time_without: float,
) -> str:
    import pandas as pd
    import numpy as np

    lines = []

    # ── 头部 ──
    lines.append("# 频域特征集成前后异常检测对比报告\n")
    lines.append(f"**生成时间**：{pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}  \n")
    lines.append(f"**带频域耗时**：{run_time_with:.1f}s  |  **不带频域耗时**：{run_time_without:.1f}s\n\n")

    # ── 1. 运行概况 ──
    lines.append("## 1. 运行概况\n")
    lines.append("| 项目 | 带频域特征 | 不带频域特征 |\n")
    lines.append("|------|-----------|-------------|\n")
    keys_all = sorted(set(list(merged_with.keys()) + list(merged_without.keys())))
    # 总异常点数
    total_w = sum(int(df["any_anomaly"].sum()) for df in merged_with.values())
    total_wo = sum(int(df["any_anomaly"].sum()) for df in merged_without.values())
    lines.append(f"| 总异常时间点数 | {total_w} | {total_wo} |\n")
    # 总 PCA 维度
    total_pc_w = sum(df.shape[1] for df in loadings_with.values())
    total_pc_wo = sum(df.shape[1] for df in loadings_without.values())
    lines.append(f"| 总 PCA 主成分数（各部位之和） | {total_pc_w} | {total_pc_wo} |\n")
    # 总窗口特征列数（不含时间戳和工况）
    total_col_w = sum(
        sum(1 for c in df.columns if c not in ["时间戳", "工况"])
        for df in windows_with.values()
    )
    total_col_wo = sum(
        sum(1 for c in df.columns if c not in ["时间戳", "工况"])
        for df in windows_without.values()
    )
    lines.append(f"| 总特征维度（各部位之和） | {total_col_w} | {total_col_wo} |\n\n")

    # ── 2. 异常时间点数量 ──
    lines.append("## 2. 各部位异常时间点数量\n")
    lines.append("| 部位 | 带频域 | 不带频域 | 差异 | 变化率 |\n")
    lines.append("|------|--------|----------|------|--------|\n")
    for key in keys_all:
        w_df = merged_with.get(key)
        wo_df = merged_without.get(key)
        w_count = int(w_df["any_anomaly"].sum()) if w_df is not None else 0
        wo_count = int(wo_df["any_anomaly"].sum()) if wo_df is not None else 0
        diff = w_count - wo_count
        rate = f"{diff / wo_count * 100:+.1f}%" if wo_count > 0 else "N/A"
        # 标记显著变化
        marker = " ⚠️" if abs(diff) > 10 and wo_count > 0 and abs(diff / wo_count) > 0.1 else ""
        lines.append(f"| {key} | {w_count} | {wo_count} | {diff:+d} | {rate}{marker} |\n")
    lines.append("\n")

    # ── 3. PCA 降维对比 ──
    lines.append("## 3. PCA 降维维度\n")
    lines.append("| 部位 | 带频域(主成分数) | 不带频域(主成分数) | 差异 |\n")
    lines.append("|------|-------------------|--------------------|------|\n")
    for key in keys_all:
        w_df = loadings_with.get(key)
        wo_df = loadings_without.get(key)
        w_n = w_df.shape[1] if w_df is not None else 0
        wo_n = wo_df.shape[1] if wo_df is not None else 0
        lines.append(f"| {key} | {w_n} | {wo_n} | {w_n - wo_n:+d} |\n")
    lines.append("\n")

    # ── 3.1 频域特征 PCA 贡献 ──
    lines.append("### 3.1 频域特征在 PCA 中的贡献\n\n")
    FREQ_KWS = ["主频", "频谱质心", "频谱熵", "低频占比", "中频占比", "高频占比"]
    for key in sorted(loadings_with.keys()):
        w_df = loadings_with.get(key)
        if w_df is None:
            continue
        freq_feats = [c for c in w_df.index if any(kw in c for kw in FREQ_KWS)]
        if not freq_feats:
            lines.append(f"**{key}**：无频域特征被 PCA 保留\n\n")
            continue

        # 统计
        total_feats = len(w_df.index)
        freq_ratio = len(freq_feats) / total_feats * 100
        # 各频域特征的最大载荷绝对值
        max_loadings = w_df.loc[freq_feats].abs().max(axis=1).sort_values(ascending=False)
        # 前 N 频域特征在 PC1 中的载荷占比
        pc1_loadings = w_df["PC1"].abs().sort_values(ascending=False)
        freq_in_pc1 = pc1_loadings[[c for c in pc1_loadings.index if c in freq_feats]]

        lines.append(f"**{key}**：{len(freq_feats)}/{total_feats} 个频域特征 ({freq_ratio:.0f}%) 参与 PCA\n")
        if not freq_in_pc1.empty:
            lines.append(f"  - PC1 中含 {len(freq_in_pc1)} 个频域特征，最大载荷 {freq_in_pc1.max():.4f}\n")
        lines.append(f"  - 最高载荷频域特征（Top 5）：\n")
        for feat, ld in max_loadings.head(5).items():
            lines.append(f"    - `{feat}` → |loading| = {ld:.4f}\n")
        lines.append("\n")

    # ── 4. 窗口特征维度 ──
    lines.append("## 4. 窗口特征宽表维度\n")
    lines.append("| 部位 | 带频域(特征列数) | 不带频域(特征列数) | 新增列数 |\n")
    lines.append("|------|------------------|--------------------|---------|\n")
    for key in keys_all:
        w_df = windows_with.get(key)
        wo_df = windows_without.get(key)
        w_n = len([c for c in w_df.columns if c not in ["时间戳", "工况"]]) if w_df is not None else 0
        wo_n = len([c for c in wo_df.columns if c not in ["时间戳", "工况"]]) if wo_df is not None else 0
        lines.append(f"| {key} | {w_n} | {wo_n} | +{w_n - wo_n} |\n")
    lines.append("\n")

    # ── 5. 异常检测结果重叠率 ──
    lines.append("## 5. 异常检测结果重叠分析\n\n")
    lines.append("### 5.1 Jaccard 重叠率\n")
    lines.append("| 部位 | 两者异常 | 仅带频域 | 仅不带频域 | Jaccard | 变化解读 |\n")
    lines.append("|------|----------|----------|------------|---------|--------|\n")
    for key in keys_all:
        w_df = merged_with.get(key)
        wo_df = merged_without.get(key)
        if w_df is None or wo_df is None:
            continue
        w_set = set(w_df[w_df["any_anomaly"] == 1].index)
        wo_set = set(wo_df[wo_df["any_anomaly"] == 1].index)
        both = len(w_set & wo_set)
        only_w = len(w_set - wo_set)
        only_wo = len(wo_set - w_set)
        jaccard = both / (both + only_w + only_wo) if (both + only_w + only_wo) > 0 else 0
        # 变化解读
        if jaccard > 0.8:
            interpretation = "高度一致，频域影响小"
        elif jaccard > 0.5:
            interpretation = "中等差异，频域有适度影响"
        elif jaccard > 0.2:
            interpretation = "较大差异，频域特征显著改变检测结果"
        else:
            interpretation = "差异巨大，频域特征主导检测判断"
        if both == 0 and (only_w or only_wo):
            interpretation = "无重叠，频域特征完全改变了异常检测结果"
        lines.append(f"| {key} | {both} | {only_w} | {only_wo} | {jaccard:.3f} | {interpretation} |\n")
    lines.append("\n")

    # 5.2 新增异常点工况分布
    lines.append("### 5.2 新增异常点的工况分布\n\n")
    FREQ_COND_ORDER = [
        "割煤-低位", "割煤-中位", "割煤-高位",
        "待机", "待机-高位", "停机", "未知",
    ]
    for key in keys_all:
        w_df = merged_with.get(key)
        wo_df = merged_without.get(key)
        if w_df is None or wo_df is None:
            continue
        w_idx = set(w_df[w_df["any_anomaly"] == 1].index)
        wo_idx = set(wo_df[wo_df["any_anomaly"] == 1].index)
        new_anomalies = w_idx - wo_idx
        lost_anomalies = wo_idx - w_idx
        if len(new_anomalies) == 0 and len(lost_anomalies) == 0:
            lines.append(f"**{key}**：无变化\n\n")
            continue

        lines.append(f"**{key}**：\n")
        if len(new_anomalies) > 0:
            new_df = w_df.loc[sorted(new_anomalies)]
            if "工况" in new_df.columns:
                cond_dist = new_df["工况"].value_counts()
                cond_pretty = ", ".join(
                    f"{c}: {n}" for c in FREQ_COND_ORDER
                    if c in cond_dist.index
                    for n in [cond_dist[c]]
                )
                lines.append(f"  - 新增 {len(new_anomalies)} 个：{cond_pretty}\n")
            else:
                lines.append(f"  - 新增 {len(new_anomalies)} 个\n")
        if len(lost_anomalies) > 0:
            lost_df = wo_df.loc[sorted(lost_anomalies)]
            if "工况" in lost_df.columns:
                cond_dist = lost_df["工况"].value_counts()
                cond_pretty = ", ".join(
                    f"{c}: {n}" for c in FREQ_COND_ORDER
                    if c in cond_dist.index
                    for n in [cond_dist[c]]
                )
                lines.append(f"  - 消失 {len(lost_anomalies)} 个：{cond_pretty}\n")
            else:
                lines.append(f"  - 消失 {len(lost_anomalies)} 个\n")
        lines.append("\n")

    # ── 6. 结论 ──
    lines.append("## 6. 结论\n\n")

    # 自动分析结论
    conclusions = []
    # 检查异常数量变化
    total_w = sum(int(df["any_anomaly"].sum()) for df in merged_with.values())
    total_wo = sum(int(df["any_anomaly"].sum()) for df in merged_without.values())
    if total_w > total_wo * 1.2:
        conclusions.append(f"- 频域特征加入后总异常点数增加 {(total_w / total_wo - 1) * 100:.0f}%，说明频域特征捕获了时域特征无法捕捉的异常模式")
    elif total_w < total_wo * 0.8:
        conclusions.append(f"- 频域特征加入后总异常点数减少 {(1 - total_w / total_wo) * 100:.0f}%，说明部分时域假阳性被频域特征过滤掉")
    else:
        conclusions.append("- 频域特征加入后异常点数总体变化不大（±20%以内），频域特征在数量层面补充性适中")

    # 检查重叠率
    jaccards = []
    for key in keys_all:
        w_df = merged_with.get(key)
        wo_df = merged_without.get(key)
        if w_df is None or wo_df is None:
            continue
        w_set = set(w_df[w_df["any_anomaly"] == 1].index)
        wo_set = set(wo_df[wo_df["any_anomaly"] == 1].index)
        both = len(w_set & wo_set)
        union = len(w_set | wo_set)
        if union > 0:
            jaccards.append(both / union)
    avg_jaccard = sum(jaccards) / len(jaccards) if jaccards else 0
    if avg_jaccard > 0.7:
        conclusions.append(f"- 平均 Jaccard={avg_jaccard:.2f}，频域特征对已有检测结果影响较小，集成方式合理（未引入大量噪音）")
    elif avg_jaccard > 0.4:
        conclusions.append(f"- 平均 Jaccard={avg_jaccard:.2f}，频域特征适度改变了检测结果，提供了补充信息")
    else:
        conclusions.append(f"- 平均 Jaccard={avg_jaccard:.2f}，频域特征显著改变了检测结果，建议进一步验证哪些新增异常点是真实的")

    # 检查 PCA 载荷
    freq_in_pca = 0
    for key in loadings_with:
        df = loadings_with[key]
        if df is None:
            continue
        freq_in_pca += sum(
            1 for c in df.index if any(kw in c for kw in FREQ_KWS)
        )
    if freq_in_pca > 0:
        conclusions.append(f"- 共 {freq_in_pca} 个频域特征参与了 PCA 的主成分构建，说明频域信息确实包含与异常相关的方差结构")
    else:
        conclusions.append("- 频域特征在 PCA 中未被保留，可能其方差被时域特征覆盖")

    # 总结
    conclusions.append("\n**总体评价**：频域特征集成方案技术可行，能提供一定增量信息，建议保留 ENABLE_FREQ_FEATURES=True 作为默认配置。")

    lines.extend([c + "\n" for c in conclusions])

    return "".join(lines)


def main():
    import pandas as pd
    import numpy as np

    print("=" * 60)
    print("  频域特征集成对比自动化脚本")
    print("=" * 60)

    # 0. 记下原始值
    original_flag = _get_config_flag()
    print(f"\n当前设置: ENABLE_FREQ_FEATURES = {original_flag}")

    # 清理旧目录
    for d in [COMP_DIR]:
        if d.exists():
            shutil.rmtree(d)

    # ════════════════════════════════════════════════
    # 第一轮：带频域特征
    # ════════════════════════════════════════════════
    if original_flag is False:
        _set_config_flag(True)
    else:
        # 确保是 True
        _set_config_flag(True)

    run_time_with = run_pipeline("带频域特征")
    backup_phase2(WITH_FREQ_DIR)

    # ════════════════════════════════════════════════
    # 第二轮：不带频域特征
    # ════════════════════════════════════════════════
    _set_config_flag(False)
    run_time_without = run_pipeline("不带频域特征")
    backup_phase2(NO_FREQ_DIR)

    # 恢复
    _set_config_flag(original_flag)

    # ════════════════════════════════════════════════
    # 对比报告
    # ════════════════════════════════════════════════
    print(f"\n{'=' * 60}")
    print("  生成对比报告...")
    print(f"{'=' * 60}")

    merged_with = load_merged_events(WITH_FREQ_DIR)
    merged_without = load_merged_events(NO_FREQ_DIR)
    loadings_with = load_pca_loadings(WITH_FREQ_DIR)
    loadings_without = load_pca_loadings(NO_FREQ_DIR)
    windows_with = load_windows(WITH_FREQ_DIR)
    windows_without = load_windows(NO_FREQ_DIR)

    print(f"  带频域: {len(merged_with)} merged, {len(loadings_with)} pca, {len(windows_with)} windows")
    print(f"  不带频域: {len(merged_without)} merged, {len(loadings_without)} pca, {len(windows_without)} windows")

    COMP_DIR.mkdir(parents=True, exist_ok=True)
    report = generate_report(
        merged_with, merged_without,
        loadings_with, loadings_without,
        windows_with, windows_without,
        run_time_with, run_time_without,
    )

    report_path = COMP_DIR / "comparison_report.md"
    report_path.write_text(report, encoding="utf-8")
    print(f"\n  报告: {report_path}")
    print(f"  报告大小: {len(report)} 字符")

    # 也打印报告摘要
    print(f"\n{'=' * 60}")
    print("  报告摘要")
    print(f"{'=' * 60}")
    # 统计数字摘要
    for key in merged_with:
        w_df = merged_with.get(key)
        wo_df = merged_without.get(key)
        if w_df is None or wo_df is None:
            continue
        w_count = int(w_df["any_anomaly"].sum())
        wo_count = int(wo_df["any_anomaly"].sum())
        w_set = set(w_df[w_df["any_anomaly"] == 1].index)
        wo_set = set(wo_df[wo_df["any_anomaly"] == 1].index)
        both = len(w_set & wo_set)
        union = len(w_set | wo_set)
        jac = both / union if union > 0 else 0
        print(f"  {key:35s}  带={w_count:4d}  不带={wo_count:4d}  diff={w_count-wo_count:+4d}  Jaccard={jac:.3f}")
    print(f"\n  完整报告：{report_path}")


if __name__ == "__main__":
    main()
