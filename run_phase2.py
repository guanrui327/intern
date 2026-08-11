# -*- coding: utf-8 -*-
"""阶段二：异常检测流程编排器。

主线流程：
  1. 加载阶段一输出的带工况宽表（parquet）
  2. 分工况基线计算（均值/中位数/IQR/p5/p95）
  3. 滑动窗口特征提取（RMS / 斜率）
  4. 多变量异常检测（Mahalanobis / Isolation Forest / 残差）
  5. 单变量异常检测（复用 segment_stats 的 IQR + 3σ）
  6. 工况切换频率统计
  7. 合并事件 + 可视化
  8. 输出 MD 和 DOCX 报告
"""

from __future__ import annotations

import gc
import warnings
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    from sklearn.decomposition import PCA

from src import config
from src.anomaly_mv import (
    mahalanobis_anomaly_detection,
    isolation_forest_anomaly,
    detect_residual_anomaly,
    merge_anomaly_events,
)
from src.anomaly_viz import (
    plot_mahalanobis_timeline,
    plot_anomaly_feature_breakdown,
    plot_if_comparison,
    plot_interpretation_summary,
    plot_window_feature_dashboard,
)
from src.anomaly_report import generate_markdown, build_docx_report
from src.feature_extract import (
    compute_baseline_profile,
    save_baseline_profile,
    build_window_feature_df,
    build_freq_feature_df,
    compute_condition_transition_rate,
)
from src.segment_stats import (
    compute_all_part_value_anomalies,
)


def _apply_pca(
    window_df: pd.DataFrame,
    feature_cols: list[str],
    variance_ratio: float = 0.95,
    out_prefix: str = "",
    anomalies_dir: Path | None = None,
) -> tuple[pd.DataFrame, list[str], PCA | None]:
    """PCA 降维预处理：保留方差比例的特征，返回降维后的宽表和主成分列名。

    Parameters
    ----------
    window_df : 特征宽表 [时间戳, 工况, feat1, feat2, ...]
    feature_cols : 原始特征列名
    variance_ratio : 保留的累积方差比例（默认 0.95）
    out_prefix : 输出文件名前缀
    anomalies_dir : 若指定，保存 PCA 载荷 CSV

    Returns
    -------
    (window_df_reduced, pca_feature_cols, pca_model)
    PCA 模型用于后续解释（component loadings）
    """
    if not feature_cols or len(feature_cols) < 2:
        print("  [PCA] 特征数 < 2，跳过")
        return window_df, feature_cols, None

    X = window_df[feature_cols].values
    valid_mask = ~(np.isnan(X) | np.isinf(X)).any(axis=1)
    X_valid = X[valid_mask]
    if len(X_valid) < 10:
        print("  [PCA] 有效样本 < 10，跳过")
        return window_df, feature_cols, None

    n_components = min(len(feature_cols), len(X_valid) - 1)
    pca = PCA(n_components=n_components).fit(X_valid)

    cumsum = np.cumsum(pca.explained_variance_ratio_)
    n_keep = int(np.searchsorted(cumsum, variance_ratio) + 1)
    n_keep = min(n_keep, n_components)

    # 降维变换（只对有效行变换，无效行填 NaN）
    X_valid_reduced = pca.transform(X_valid)[:, :n_keep]
    pc_cols = [f"PC{i+1}" for i in range(n_keep)]

    reduced_df = window_df[["时间戳", "工况"]].copy()
    reduced_df[pc_cols] = np.nan
    reduced_df.loc[valid_mask, pc_cols] = X_valid_reduced

    print(f"  [PCA] {len(feature_cols)} → {n_keep} 维 "
          f"(累积方差 {cumsum[n_keep-1]:.3f})")

    # 保存载荷矩阵（特征 → 主成分映射，帮助解释）
    if anomalies_dir:
        loadings = pd.DataFrame(
            pca.components_[:n_keep, :].T,
            index=feature_cols,
            columns=pc_cols,
        )
        loadings_path = Path(anomalies_dir) / f"{out_prefix}_pca_loadings.csv"
        loadings.to_csv(loadings_path, encoding="utf-8-sig")
        print(f"  [PCA] 载荷矩阵: {loadings_path}")

        # 方差解释率
        var_df = pd.DataFrame({
            "主成分": pc_cols,
            "方差解释率": pca.explained_variance_ratio_[:n_keep],
            "累积方差": cumsum[:n_keep],
        })
        var_path = Path(anomalies_dir) / f"{out_prefix}_pca_variance.csv"
        var_df.to_csv(var_path, index=False, encoding="utf-8-sig")

    return reduced_df, pc_cols, pca


def _clean_figs(msg: str = "") -> None:
    """关闭所有图窗并回收内存。"""
    plt.close("all")
    gc.collect()


# ── 部位配置 ──
_PART_COND_TO_KEY: dict[str, str] = {
    "截割部_工况": "截割部",
    "牵引部_工况": "牵引部",
    "油泵_工况":   "油泵",
    "破碎机_工况": "破碎机",
}


def _filter_part_monitor_cols(
    monitor_cols: list[str], part_key: str,
) -> list[str]:
    """根据部位关键词筛选相关的监测参数列。"""
    kw_filter = config.CMJ_PART_MONITOR_MAP.get(part_key, [])
    if not kw_filter:
        return monitor_cols
    return [c for c in monitor_cols if any(kw in c for kw in kw_filter)]


def _load_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    """加载阶段一输出的带工况宽表。"""
    cmj_path = config.PHASE1_DIR / "cmj_with_condition.parquet"
    zzj_path = config.PHASE1_DIR / "zzj_with_condition.parquet"

    print(f"\n  加载 CMJ: {cmj_path}")
    cmj = pd.read_parquet(cmj_path)
    print(f"    行数: {len(cmj)}, 列数: {len(cmj.columns)}")

    print(f"\n  加载 ZZJ: {zzj_path}")
    zzj = pd.read_parquet(zzj_path)
    print(f"    行数: {len(zzj)}, 列数: {len(zzj.columns)}")

    return cmj, zzj


def _run_device_pipeline(
    df: pd.DataFrame,
    device_key: str,
    monitor_cols: list[str],
    cond_cols: list[str],
    device_cond_col: str,
    phase2_dir: Path,
) -> dict:
    """对单个设备运行完整阶段二 pipeline。

    Parameters
    ----------
    df : 带工况宽表（DatetimeIndex）
    device_key : 'cmj' 或 'zzj'
    monitor_cols : 监测参数列
    cond_cols : 所有工况列
    device_cond_col : 设备级主工况列（用于异常检测的 cond_col）
    phase2_dir : 输出根目录

    Returns
    -------
    dict : {
        "merged_events": DataFrame,
        "mahal_events": DataFrame | None,
        "if_events": DataFrame | None,
        "residual_events": DataFrame | None,
        "value_anomalies": dict[str, DataFrame],
        "profiles": dict[str, DataFrame],
        "transition_rates": dict[str, DataFrame],
        "n_anomaly_timepoints": int,
        "methods": list[str],
    }
    """
    print(f"\n{'=' * 50}")
    print(f"设备: {'采煤机' if device_key == 'cmj' else '转载机'}")
    print(f"{'=' * 50}")

    profiles_dir = phase2_dir / "profiles"
    windows_dir = phase2_dir / "windows"
    anomalies_dir = phase2_dir / "anomalies"
    for d in [profiles_dir, windows_dir, anomalies_dir]:
        d.mkdir(parents=True, exist_ok=True)

    device_name = "cmj" if device_key == "cmj" else "zzj"

    # ════════════════════════════════════════════════════════
    # 1. 分工况基线计算
    # ════════════════════════════════════════════════════════
    print("\n--- 1. 分工况基线 ---")
    profiles = {}
    for cond_col in cond_cols:
        if cond_col not in df.columns:
            continue
        profile = compute_baseline_profile(
            df, cond_col, monitor_cols,
            min_samples=config.MIN_BASELINE_SAMPLES,
        )
        if not profile.empty:
            save_baseline_profile(profile, cond_col, device_name, profiles_dir)
            profiles[cond_col] = profile
            print(f"  {cond_col}: {len(profile)} 行 ("
                  f"{profile['工况'].nunique()} 工况 × {profile['参数'].nunique()} 参数)")
        else:
            print(f"  [SKIP] {cond_col}: 无有效数据")

    # ════════════════════════════════════════════════════════
    # 2. 滑动窗口特征提取
    # ════════════════════════════════════════════════════════
    print("\n--- 2. 滑动窗口特征 ---")
    window_df = build_window_feature_df(
        df, device_cond_col, monitor_cols,
        window=config.SLIDING_WINDOW,
        step=config.SLIDING_STEP,
    )
    if not window_df.empty:
        win_path = windows_dir / f"{device_name}_sliding_windows.csv"
        window_df.to_csv(win_path, index=False, encoding="utf-8-sig")
        print(f"  宽表: {win_path}  {window_df.shape}")
    else:
        print("  [WARN] 窗口特征为空，跳过后续多变量检测")

    # ════════════════════════════════════════════════════════
    # 3. PCA 降维（可选）
    # ════════════════════════════════════════════════════════
    print("\n--- 3. PCA 降维 ---")

    feature_cols = [c for c in window_df.columns
                    if c not in ["时间戳", "工况"]] if not window_df.empty else []
    pca_model = None

    if config.USE_PCA and feature_cols and len(feature_cols) > 2:
        window_df, feature_cols, pca_model = _apply_pca(
            window_df, feature_cols,
            variance_ratio=config.PCA_VARIANCE_RATIO,
            out_prefix=device_name,
            anomalies_dir=anomalies_dir,
        )
    else:
        print(f"  [PCA] 跳过（USE_PCA={config.USE_PCA}, 特征数={len(feature_cols)}）")

    # ════════════════════════════════════════════════════════
    # 4. 多变量异常检测
    # ════════════════════════════════════════════════════════
    print("\n--- 4. 多变量异常检测 ---")

    mahal_events = None
    if_events = None
    residual_events = None

    # 注：build_window_feature_df 硬编码工况列名为 "工况"
    window_cond_col = "工况"

    # 4a. Mahalanobis
    print("\n  4a. Mahalanobis 距离")
    if feature_cols:
        mahal_events = mahalanobis_anomaly_detection(
            window_df, feature_cols, cond_col=window_cond_col,
            alpha=config.MAHALANOBIS_ALPHA,
            min_samples=config.MIN_BASELINE_SAMPLES,
        )
        if mahal_events is not None and not mahal_events.empty:
            mahal_path = anomalies_dir / f"{device_name}_mahalanobis.csv"
            mahal_events.to_csv(mahal_path, index=False, encoding="utf-8-sig")
            n_anom = mahal_events["is_anomaly"].sum()
            print(f"    异常: {n_anom}/{len(mahal_events)} = "
                  f"{n_anom / len(mahal_events) * 100:.1f}%")
            print(f"    CSV: {mahal_path}")
        else:
            print("    无有效结果")
    else:
        print("    无特征列，跳过")

    # 4b. Isolation Forest
    print("\n  4b. Isolation Forest")
    if feature_cols:
        if_events = isolation_forest_anomaly(
            window_df, feature_cols, cond_col=window_cond_col,
            contamination=config.IF_CONTAMINATION,
            min_samples=config.MIN_BASELINE_SAMPLES,
        )
        if if_events is not None and not if_events.empty:
            if_path = anomalies_dir / f"{device_name}_iforest.csv"
            if_events.to_csv(if_path, index=False, encoding="utf-8-sig")
            n_anom = if_events["is_anomaly"].sum()
            print(f"    异常: {n_anom}/{len(if_events)} = "
                  f"{n_anom / len(if_events) * 100:.1f}%")
            print(f"    CSV: {if_path}")
        else:
            print("    无有效结果")
    else:
        print("    无特征列，跳过")

    # 4c. 残差异常检测
    print("\n  4c. 残差异常检测（AR 前向预测）")
    residual_events = detect_residual_anomaly(
        df, monitor_cols, cond_col=device_cond_col,
        window=config.RESIDUAL_WINDOW,
        min_samples=config.MIN_BASELINE_SAMPLES,
    )
    if residual_events is not None and not residual_events.empty:
        residual_path = anomalies_dir / f"{device_name}_residual.csv"
        residual_events.to_csv(residual_path, index=False, encoding="utf-8-sig")
        n_anom = residual_events["is_anomaly"].sum()
        print(f"    异常: {n_anom}/{len(residual_events)} = "
              f"{n_anom / len(residual_events) * 100:.1f}%")
        print(f"    CSV: {residual_path}")
    else:
        print("    无有效结果")

    # ════════════════════════════════════════════════════════
    # 5. 单变量异常检测（复用 segment_stats）
    # ════════════════════════════════════════════════════════
    print("\n--- 5. 单变量异常检测（IQR + 3σ） ---")
    value_anomalies = compute_all_part_value_anomalies(
        df, anomalies_dir, part_cols=cond_cols, monitor_cols=monitor_cols,
    )
    _clean_figs("value-anom")

    # ════════════════════════════════════════════════════════
    # 6. 合并事件
    # ════════════════════════════════════════════════════════
    print("\n--- 6. 合并异常事件 ---")
    # 从 value_anomalies 中取主工况列的检测结果作为单变量输入
    value_events = value_anomalies.get(device_cond_col, None)

    merged_events = merge_anomaly_events(
        mahal_events=mahal_events,
        if_events=if_events,
        residual_events=residual_events,
        value_anomalies=value_events,
    )
    if not merged_events.empty:
        merged_path = anomalies_dir / f"{device_name}_merged_events.csv"
        merged_events.to_csv(merged_path, index=False, encoding="utf-8-sig")
        print(f"    合并表: {merged_path}")

    n_anomaly_timepoints = int(
        merged_events["any_anomaly"].sum() if not merged_events.empty else 0
    )

    methods = []
    if mahal_events is not None and not mahal_events.empty:
        methods.append("Mahalanobis")
    if if_events is not None and not if_events.empty:
        methods.append("IsolationForest")
    if residual_events is not None and not residual_events.empty:
        methods.append("残差")
    if value_events is not None and not value_events.empty:
        methods.append("单变量IQR+3σ")

    # ════════════════════════════════════════════════════════
    # 7. 工况切换频率
    # ════════════════════════════════════════════════════════
    print("\n--- 7. 工况切换频率 ---")
    transition_rates = {}
    for cond_col in cond_cols:
        if cond_col not in df.columns:
            continue
        tr = compute_condition_transition_rate(df, cond_col)
        if not tr.empty:
            tr_path = anomalies_dir / f"{device_name}_transition_rate_{cond_col}.csv"
            tr.to_csv(tr_path, index=False, encoding="utf-8-sig")
            transition_rates[cond_col] = tr
            print(f"  {cond_col}: {len(tr)} 种工况")

    # ════════════════════════════════════════════════════════
    # 8. 可视化
    # ════════════════════════════════════════════════════════
    print("\n--- 8. 可视化 ---")

    # 7a. Mahalanobis 时间线
    if mahal_events is not None and not mahal_events.empty:
        plot_mahalanobis_timeline(
            df, mahal_events, monitor_cols,
            cond_col=device_cond_col,
            output_path=anomalies_dir / f"{device_name}_mahalanobis_timeline.png",
        )
        plot_anomaly_feature_breakdown(
            mahal_events, feature_cols, top_n=10,
            output_path=anomalies_dir / f"{device_name}_feature_breakdown.png",
        )
        _clean_figs("mahal-viz")

    # 7b. IF vs Mahalanobis 对比
    plot_if_comparison(
        if_events, mahal_events,
        output_path=anomalies_dir / f"{device_name}_if_comparison.png",
    )
    _clean_figs("if-viz")

    # 7c. 归因总结
    if not merged_events.empty:
        plot_interpretation_summary(
            merged_events, top_n=20,
            output_path=anomalies_dir / f"{device_name}_interpretation_summary.png",
        )
        _clean_figs("summary-viz")

    # 7d. 滑动窗口特征仪表板
    if not window_df.empty:
        plot_window_feature_dashboard(
            window_df, monitor_cols, max_params=8,
            output_path=anomalies_dir / f"{device_name}_window_features.png",
        )
        _clean_figs("win-viz")

    return {
        "merged_events": merged_events,
        "mahal_events": mahal_events,
        "if_events": if_events,
        "residual_events": residual_events,
        "value_anomalies": value_anomalies,
        "profiles": profiles,
        "transition_rates": transition_rates,
        "n_anomaly_timepoints": n_anomaly_timepoints,
        "methods": methods,
    }


def _run_part_pipeline(
    df: pd.DataFrame,
    part_cond_col: str,
    part_key: str,
    monitor_cols: list[str],
    device_key: str,
    phase2_dir: Path,
) -> dict:
    """对单个部位跑完整的异常检测 pipeline。

    与 ``_run_device_pipeline`` 的区别：
    - 使用部位工况列（如 "截割部_工况"）作为主检测维度
    - 监测参数已按部位关键词筛选
    - 输出文件名带部位前缀
    - 基线和切换率只算该部位自己的工况列
    """
    profiles_dir = phase2_dir / "profiles"
    windows_dir = phase2_dir / "windows"
    anomalies_dir = phase2_dir / "anomalies"
    for d in [profiles_dir, windows_dir, anomalies_dir]:
        d.mkdir(parents=True, exist_ok=True)

    device_name = "cmj" if device_key == "cmj" else "zzj"
    out_prefix = f"{device_name}_{part_key}"

    # ════════════════════════════════════════════════════════
    # 1. 分工况基线计算（只算本部位工况列）
    # ════════════════════════════════════════════════════════
    print("\n--- 1. 分工况基线 ---")
    profiles = {}
    if part_cond_col in df.columns:
        profile = compute_baseline_profile(
            df, part_cond_col, monitor_cols,
            min_samples=config.MIN_BASELINE_SAMPLES,
        )
        if not profile.empty:
            save_baseline_profile(profile, part_cond_col, device_name, profiles_dir)
            profiles[part_cond_col] = profile
            print(f"  {part_cond_col}: {len(profile)} 行 ("
                  f"{profile['工况'].nunique()} 工况 × {profile['参数'].nunique()} 参数)")
        else:
            print(f"  [SKIP] {part_cond_col}: 无有效数据")

    # ════════════════════════════════════════════════════════
    # 2. 滑动窗口特征提取
    # ════════════════════════════════════════════════════════
    print("\n--- 2. 滑动窗口特征 ---")
    window_df = build_window_feature_df(
        df, part_cond_col, monitor_cols,
        window=config.SLIDING_WINDOW,
        step=config.SLIDING_STEP,
    )
    if not window_df.empty:
        win_path = windows_dir / f"{out_prefix}_windows.csv"
        window_df.to_csv(win_path, index=False, encoding="utf-8-sig")
        print(f"  宽表: {win_path}  {window_df.shape}")
    else:
        print("  [WARN] 窗口特征为空，跳过后续多变量检测")

    # ════════════════════════════════════════════════════════
    # 2b. 频域特征集成（可选，默认开启）
    # ════════════════════════════════════════════════════════
    if config.ENABLE_FREQ_FEATURES and not window_df.empty:
        print("\n--- 2b. 频域特征集成 ---")
        freq_df = build_freq_feature_df(
            df, part_cond_col, monitor_cols,
            window=config.FREQ_WINDOW, step=config.FREQ_STEP,
        )
        if not freq_df.empty:
            freq_cols = [c for c in freq_df.columns
                         if c not in ["时间戳", "工况"]]
            window_df = window_df.merge(
                freq_df.drop(columns=["工况"]), on="时间戳", how="left",
            )
            window_df[freq_cols] = window_df[freq_cols].ffill().bfill()
            print(f"    + {len(freq_cols)} 个频域特征列合并完成")
        else:
            print("    [SKIP] 频域特征提取结果为空")
    elif config.ENABLE_FREQ_FEATURES and window_df.empty:
        print("    [SKIP] 窗口特征为空，跳过频域集成")

    # ════════════════════════════════════════════════════════
    # 3. PCA 降维（可选）
    # ════════════════════════════════════════════════════════
    print("\n--- 3. PCA 降维 ---")

    feature_cols = [c for c in window_df.columns
                    if c not in ["时间戳", "工况"]] if not window_df.empty else []
    pca_model = None

    if config.USE_PCA and feature_cols and len(feature_cols) > 2:
        window_df, feature_cols, pca_model = _apply_pca(
            window_df, feature_cols,
            variance_ratio=config.PCA_VARIANCE_RATIO,
            out_prefix=out_prefix,
            anomalies_dir=anomalies_dir,
        )
    else:
        print(f"  [PCA] 跳过（USE_PCA={config.USE_PCA}, 特征数={len(feature_cols)}）")

    # ════════════════════════════════════════════════════════
    # 4. 多变量异常检测
    # ════════════════════════════════════════════════════════
    print("\n--- 4. 多变量异常检测 ---")

    mahal_events = None
    if_events = None
    residual_events = None

    window_cond_col = "工况"  # build_window_feature_df 硬编码的列名

    # 4a. Mahalanobis
    print("\n  4a. Mahalanobis 距离")
    if feature_cols:
        mahal_events = mahalanobis_anomaly_detection(
            window_df, feature_cols, cond_col=window_cond_col,
            alpha=config.MAHALANOBIS_ALPHA,
            min_samples=config.MIN_BASELINE_SAMPLES,
        )
        if mahal_events is not None and not mahal_events.empty:
            mahal_path = anomalies_dir / f"{out_prefix}_mahalanobis.csv"
            mahal_events.to_csv(mahal_path, index=False, encoding="utf-8-sig")
            n_anom = mahal_events["is_anomaly"].sum()
            print(f"    异常: {n_anom}/{len(mahal_events)} = "
                  f"{n_anom / len(mahal_events) * 100:.1f}%")
            print(f"    CSV: {mahal_path}")
        else:
            print("    无有效结果")
    else:
        print("    无特征列，跳过")

    # 4b. Isolation Forest
    print("\n  4b. Isolation Forest")
    if feature_cols:
        if_events = isolation_forest_anomaly(
            window_df, feature_cols, cond_col=window_cond_col,
            contamination=config.IF_CONTAMINATION,
            min_samples=config.MIN_BASELINE_SAMPLES,
        )
        if if_events is not None and not if_events.empty:
            if_path = anomalies_dir / f"{out_prefix}_iforest.csv"
            if_events.to_csv(if_path, index=False, encoding="utf-8-sig")
            n_anom = if_events["is_anomaly"].sum()
            print(f"    异常: {n_anom}/{len(if_events)} = "
                  f"{n_anom / len(if_events) * 100:.1f}%")
            print(f"    CSV: {if_path}")
        else:
            print("    无有效结果")
    else:
        print("    无特征列，跳过")

    # 4c. 残差异常检测
    print("\n  4c. 残差异常检测（AR 前向预测）")
    residual_events = detect_residual_anomaly(
        df, monitor_cols, cond_col=part_cond_col,
        window=config.RESIDUAL_WINDOW,
        min_samples=config.MIN_BASELINE_SAMPLES,
    )
    if residual_events is not None and not residual_events.empty:
        residual_path = anomalies_dir / f"{out_prefix}_residual.csv"
        residual_events.to_csv(residual_path, index=False, encoding="utf-8-sig")
        n_anom = residual_events["is_anomaly"].sum()
        print(f"    异常: {n_anom}/{len(residual_events)} = "
              f"{n_anom / len(residual_events) * 100:.1f}%")
        print(f"    CSV: {residual_path}")
    else:
        print("    无有效结果")

    # ════════════════════════════════════════════════════════
    # 4. 单变量异常检测
    # ════════════════════════════════════════════════════════
    print("\n--- 5. 单变量异常检测（IQR + 3σ） ---")
    value_anomalies = compute_all_part_value_anomalies(
        df, anomalies_dir, part_cols=[part_cond_col], monitor_cols=monitor_cols,
    )
    _clean_figs("value-anom")

    # ════════════════════════════════════════════════════════
    # 6. 合并事件
    # ════════════════════════════════════════════════════════
    print("\n--- 6. 合并异常事件 ---")
    value_events = value_anomalies.get(part_cond_col, None)

    merged_events = merge_anomaly_events(
        mahal_events=mahal_events,
        if_events=if_events,
        residual_events=residual_events,
        value_anomalies=value_events,
    )
    if not merged_events.empty:
        merged_path = anomalies_dir / f"{out_prefix}_merged_events.csv"
        merged_events.to_csv(merged_path, index=False, encoding="utf-8-sig")
        print(f"    合并表: {merged_path}")

    n_anomaly_timepoints = int(
        merged_events["any_anomaly"].sum() if not merged_events.empty else 0
    )

    methods = []
    if mahal_events is not None and not mahal_events.empty:
        methods.append("Mahalanobis")
    if if_events is not None and not if_events.empty:
        methods.append("IsolationForest")
    if residual_events is not None and not residual_events.empty:
        methods.append("残差")
    if value_events is not None and not value_events.empty:
        methods.append("单变量IQR+3σ")

    # ════════════════════════════════════════════════════════
    # 7. 工况切换频率（只算本部位）
    # ════════════════════════════════════════════════════════
    print("\n--- 7. 工况切换频率 ---")
    transition_rates = {}
    if part_cond_col in df.columns:
        tr = compute_condition_transition_rate(df, part_cond_col)
        if not tr.empty:
            tr_path = anomalies_dir / f"{device_name}_transition_rate_{part_cond_col}.csv"
            tr.to_csv(tr_path, index=False, encoding="utf-8-sig")
            transition_rates[part_cond_col] = tr
            print(f"  {part_cond_col}: {len(tr)} 种工况")

    # ════════════════════════════════════════════════════════
    # 8. 可视化
    # ════════════════════════════════════════════════════════
    print("\n--- 8. 可视化 ---")

    # 7a. Mahalanobis 时间线
    if mahal_events is not None and not mahal_events.empty:
        plot_mahalanobis_timeline(
            df, mahal_events, monitor_cols,
            cond_col=part_cond_col,
            output_path=anomalies_dir / f"{out_prefix}_mahalanobis_timeline.png",
        )
        plot_anomaly_feature_breakdown(
            mahal_events, feature_cols, top_n=10,
            output_path=anomalies_dir / f"{out_prefix}_feature_breakdown.png",
        )
        _clean_figs("mahal-viz")

    # 7b. IF vs Mahalanobis 对比
    plot_if_comparison(
        if_events, mahal_events,
        output_path=anomalies_dir / f"{out_prefix}_if_comparison.png",
    )
    _clean_figs("if-viz")

    # 7c. 归因总结
    if not merged_events.empty:
        plot_interpretation_summary(
            merged_events, top_n=20,
            output_path=anomalies_dir / f"{out_prefix}_interpretation_summary.png",
        )
        _clean_figs("summary-viz")

    # 7d. 滑动窗口特征仪表板
    if not window_df.empty:
        plot_window_feature_dashboard(
            window_df, monitor_cols, max_params=8,
            output_path=anomalies_dir / f"{out_prefix}_window_features.png",
        )
        _clean_figs("win-viz")

    return {
        "merged_events": merged_events,
        "mahal_events": mahal_events,
        "if_events": if_events,
        "residual_events": residual_events,
        "value_anomalies": value_anomalies,
        "profiles": profiles,
        "transition_rates": transition_rates,
        "n_anomaly_timepoints": n_anomaly_timepoints,
        "methods": methods,
    }


def main() -> None:
    phase2_dir = config.PHASE2_DIR
    phase2_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 50)
    print("阶段二：异常检测 pipeline")
    print("=" * 50)

    # ── 1. 加载数据 ──
    print("\n--- 加载阶段一输出数据 ---")
    cmj_df, zzj_df = _load_data()

    # ── 2. 采煤机 — 分部位异常检测 ──
    cmj_monitor_all = [c for c in cmj_df.columns if c in config.CMJ_MONITOR_POINTS]
    cmj_results: dict[str, dict] = {}
    for part_cond_col in config.CMJ_PART_COND_COLS:
        part_key = _PART_COND_TO_KEY[part_cond_col]
        part_monitor = _filter_part_monitor_cols(cmj_monitor_all, part_key)
        print(f"\n{'=' * 50}")
        print(f"部位: {part_key}  |  工况列: {part_cond_col}")
        print(f"监测参数: {len(part_monitor)} 个")
        print(f"{'=' * 50}")
        result = _run_part_pipeline(
            cmj_df, part_cond_col, part_key, part_monitor,
            device_key="cmj", phase2_dir=phase2_dir,
        )
        cmj_results[part_cond_col] = result
        _clean_figs(f"cmj_{part_key}")
        gc.collect()

    # ── 3. 转载机 pipeline ──
    zzj_monitor = [c for c in zzj_df.columns if c in config.ZZJ_MONITOR_POINTS]
    # 排除母线电压：物理上是开关量（停机断电≈5V / 带载≈4412V，双峰分布），
    # 在每个工况内方差趋零，毁掉 Mahalanobis 距离分母 → 异常率虚高 45.8%
    # （归因见 _diag_zzj_bus.py）。「是否带电」信息已被工况标签覆盖，检测特征不再重复。
    zzj_monitor = [c for c in zzj_monitor if "母线电压" not in c]
    zzj_results = _run_device_pipeline(
        zzj_df, "zzj", zzj_monitor, ["工况"],
        device_cond_col="工况",
        phase2_dir=phase2_dir,
    )
    _clean_figs("zzj")

    # ── 4. 生成报告 ──
    device_results = {
        "cmj": cmj_results,
        "zzj": zzj_results,
    }

    print("\n--- 8. 生成报告 ---")

    # Markdown
    md_path = phase2_dir / "phase2_report.md"
    generate_markdown(device_results, md_path)

    # DOCX
    docx_path = phase2_dir / "phase2_report.docx"
    try:
        build_docx_report(device_results, docx_path, phase2_dir / "anomalies")
    except Exception as e:
        print(f"  [WARN] DOCX 生成失败: {e}")
        import traceback
        traceback.print_exc()

    print(f"\n{'=' * 50}")
    print(f"阶段二分析完成。结果目录: {phase2_dir}")
    print(f"{'=' * 50}")


if __name__ == "__main__":
    main()
