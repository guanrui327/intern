# -*- coding: utf-8 -*-
"""阶段二：多变量异常检测模块。

提供三种异常检测方法 + 事件合并：
1. Mahalanobis 距离（χ² 分位数阈值 + 特征贡献分解）
2. Isolation Forest（自适应 contamination）
3. 残差异常检测（AR 前向预测 + Z-score）

可解释性设计：每个异常事件附带特征贡献归因文本。
"""

from __future__ import annotations

import warnings
from pathlib import Path

import numpy as np
import pandas as pd

with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    from sklearn.ensemble import IsolationForest
    from sklearn.covariance import MinCovDet


def mahalanobis_anomaly_detection(
    df: pd.DataFrame,
    feature_cols: list[str],
    cond_col: str = "工况",
    alpha: float = 0.001,
    min_samples: int = 60,
) -> pd.DataFrame:
    """基于 Mahalanobis 距离的多变量异常检测。

    对每个工况状态：
    1. 用 MinCovDet（MCD）稳健估计均值与协方差（抗离群点干扰）
    2. 计算每个观测的马氏距离
    3. χ²(自由度=特征数) 的 (1-alpha) 分位数为阈值
    4. 对异常点分解各特征贡献百分比

    Parameters
    ----------
    df : 特征宽表 [时间戳, 工况, feat1, feat2, ...]
    feature_cols : 用于计算距离的特征列
    cond_col : 工况列名
    alpha : 显著性水平，默认 0.001（0.1% 假阳性率）
    min_samples : 工况最少样本数

    Returns
    -------
    pd.DataFrame
        [时间戳, 工况, mahal_dist, threshold, is_anomaly,
         top_contributors(: 逗号分隔的特征名), top_pcts(: 逗号分隔的贡献占比),
         interpretation(: 可读归因文本)]
    """
    if df.empty or not feature_cols:
        return pd.DataFrame()

    time_col = "时间戳"
    results = []

    for cond_val in df[cond_col].unique():
        cond_val = str(cond_val)
        subset = df[df[cond_col] == cond_val].copy()
        if len(subset) < min_samples:
            print(f"  [WARN] {cond_col}={cond_val} 样本数 {len(subset)} < {min_samples}，跳过 Mahalanobis")
            continue

        X = subset[feature_cols].values
        # 删含有 NaN 的行
        valid_mask = ~np.isnan(X).any(axis=1)
        X_valid = X[valid_mask]
        if len(X_valid) < min_samples:
            continue

        # MCD 稳健协方差估计（停机等恒定工况可能全零，兜底跳过）
        dof = X_valid.shape[1]
        try:
            mcd = MinCovDet(random_state=42).fit(X_valid)
        except ValueError as e:
            print(f"  [WARN] {cond_col}={cond_val} MCD 拟合失败 ({e})，尝试标准协方差")
            # 退化为标准（非稳健）协方差
            if X_valid.shape[1] == 1:
                var_ = np.var(X_valid, ddof=1)
                if var_ < 1e-12:
                    print(f"  [WARN] 方差接近零，跳过 {cond_col}={cond_val}")
                    continue
                cov_ = np.atleast_2d(var_)
            else:
                cov_ = np.cov(X_valid, rowvar=False)
                if np.linalg.matrix_rank(cov_) < dof or np.trace(cov_) < 1e-12:
                    print(f"  [WARN] 协方差秩亏或全零，跳过 {cond_col}={cond_val}")
                    continue
            try:
                cov_inv_ = np.linalg.inv(cov_)
            except np.linalg.LinAlgError:
                ridge = 1e-6 * np.trace(cov_) / dof * np.eye(dof)
                cov_inv_ = np.linalg.inv(cov_ + ridge)
            mean_ = np.nanmean(X_valid, axis=0)
            # 跳过后续贡献分解（无 MCD location_），直接算裸马氏
            skip_feature_breakdown = True
        else:
            mean_ = mcd.location_
            skip_feature_breakdown = False

        # 协方差矩阵求逆 → 用伪逆 / 正则化兜底（特征高度相关时矩阵奇异）
        if not skip_feature_breakdown:
            try:
                cov_inv_ = np.linalg.inv(mcd.covariance_)
            except np.linalg.LinAlgError:
                print(f"  [WARN] {cond_col}={cond_val} 协方差矩阵奇异，使用伪逆 + 正则化")
                ridge = 1e-6 * np.trace(mcd.covariance_) / dof * np.eye(dof)
                try:
                    cov_inv_ = np.linalg.inv(mcd.covariance_ + ridge)
                except np.linalg.LinAlgError:
                    print(f"  [WARN] 正则化后仍奇异，跳过 {cond_col}={cond_val}")
                    continue

        # 卡方阈值
        from scipy.stats import chi2
        threshold = chi2.ppf(1 - alpha, dof)

        # 计算距离
        diff = X_valid - mean_
        mahal = np.sqrt(np.sum((diff @ cov_inv_) * diff, axis=1))

        # 对每个点
        for i, (idx, row) in enumerate(subset[valid_mask].iterrows()):
            dist = float(mahal[i])
            is_anom = dist > threshold

            # 特征贡献分解：每一项 (x_j - μ_j) * Σ⁻¹_j_j * (x_j - μ_j)
            inv_diag = np.diag(cov_inv_)
            contributions = diff[i] ** 2 * inv_diag
            total = contributions.sum()
            if total > 0:
                pcts = contributions / total * 100
            else:
                pcts = np.zeros_like(contributions)

            # 取贡献最大的 Top-3 特征
            sorted_idx = np.argsort(pcts)[::-1]
            top_names = []
            top_pcts = []
            for j in sorted_idx[:3]:
                if pcts[j] > 1.0:  # 只保留贡献 > 1% 的
                    top_names.append(feature_cols[j])
                    top_pcts.append(round(float(pcts[j]), 1))

            if not top_names:
                top_names = [feature_cols[sorted_idx[0]]]
                top_pcts.append(round(float(pcts[sorted_idx[0]]), 1))

            top_contrib = "; ".join(
                f"{n} ({p:.1f}%)" for n, p in zip(top_names, top_pcts)
            )

            # 可读归因文本
            if is_anom:
                interp = (
                    f"Mahalanobis 距离={dist:.1f}（阈值={threshold:.1f}）。"
                    f"主要贡献特征：{top_contrib}。"
                )
            else:
                interp = "正常"

            results.append({
                "时间戳": row[time_col] if time_col in row else idx,
                "工况": cond_val,
                "mahal_dist": round(dist, 4),
                "threshold": round(threshold, 4),
                "is_anomaly": is_anom,
                "top_contributors": "; ".join(top_names),
                "top_pcts": "; ".join(f"{p:.1f}%" for p in top_pcts),
                "interpretation": interp,
            })

    result = pd.DataFrame(results)
    if not result.empty:
        result = result.sort_values("时间戳").reset_index(drop=True)
    return result


def isolation_forest_anomaly(
    df: pd.DataFrame,
    feature_cols: list[str],
    cond_col: str = "工况",
    contamination: float | str = "auto",
    min_samples: int = 60,
) -> pd.DataFrame:
    """基于 Isolation Forest 的多变量异常检测。

    Parameters
    ----------
    df : 特征宽表 [时间戳, 工况, feat1, feat2, ...]
    feature_cols : 特征列
    cond_col : 工况列
    contamination : 异常比例估计，默认 'auto'
    min_samples : 工况最少样本数

    Returns
    -------
    pd.DataFrame
        [时间戳, 工况, if_score, is_anomaly, top_features, interpretation]
    """
    if df.empty or not feature_cols:
        return pd.DataFrame()

    time_col = "时间戳"
    results = []

    for cond_val in df[cond_col].unique():
        cond_val = str(cond_val)
        subset = df[df[cond_col] == cond_val].copy()
        if len(subset) < min_samples:
            print(f"  [WARN] {cond_col}={cond_val} 样本数 {len(subset)} < {min_samples}，跳过 IF")
            continue

        X = subset[feature_cols].values
        valid_mask = ~np.isnan(X).any(axis=1)
        X_valid = X[valid_mask]
        if len(X_valid) < min_samples:
            continue

        # 自适应 contamination：如果 auto 则用 10% 兜底
        if contamination == "auto":
            est_contam = min(0.1, 10.0 / len(X_valid))
        else:
            est_contam = contamination

        model = IsolationForest(
            contamination=est_contam,
            random_state=42,
            n_estimators=200,
        ).fit(X_valid)

        scores = model.decision_function(X_valid)  # 越大越正常
        preds = model.predict(X_valid)  # -1=异常, 1=正常

        X_mean = np.nanmean(X_valid, axis=0)
        for i, (idx, row) in enumerate(subset[valid_mask].iterrows()):
            is_anom = preds[i] == -1
            # 特征贡献：该特征偏离均值的程度（标准化距离）
            deviations = np.abs(X_valid[i] - X_mean)
            dev_total = deviations.sum()
            if dev_total > 0:
                feat_pcts = deviations / dev_total * 100
            else:
                feat_pcts = np.zeros_like(deviations)

            sorted_idx = np.argsort(feat_pcts)[::-1]
            top_names = []
            for j in sorted_idx[:3]:
                if feat_pcts[j] > 1.0:
                    top_names.append(f"{feature_cols[j]} ({feat_pcts[j]:.1f}%)")

            if not top_names:
                top_names = [f"{feature_cols[sorted_idx[0]]} ({feat_pcts[sorted_idx[0]]:.1f}%)"]

            top_feat = "; ".join(top_names)

            interp = (
                f"Isolation Forest 异常判定（score={scores[i]:.4f}）。"
                f"偏离中位数最大的特征：{top_feat}。"
                if is_anom else "正常"
            )

            results.append({
                "时间戳": row[time_col] if time_col in row else idx,
                "工况": cond_val,
                "if_score": round(float(scores[i]), 4),
                "is_anomaly": is_anom,
                "top_features": top_feat,
                "interpretation": interp,
            })

    result = pd.DataFrame(results)
    if not result.empty:
        result = result.sort_values("时间戳").reset_index(drop=True)
    return result


def detect_residual_anomaly(
    df_raw: pd.DataFrame,
    monitor_cols: list[str] | None = None,
    cond_col: str = "工况",
    window: int = 5,
    zscore_threshold: float = 3.0,
    min_samples: int = 30,
) -> pd.DataFrame:
    """残差异常检测：前向窗口均值作为预测值，残差的 Z-score 检测。

    对每个参数 + 每种工况独立计算：
    - 预测值 = 前 window 帧的滑动均值
    - 残差 = 实际值 - 预测值
    - 残差 Z-score > threshold 标记为异常

    Parameters
    ----------
    df_raw : 原始等间隔宽表（1min DatetimeIndex）
    monitor_cols : 监测参数列
    cond_col : 工况列
    window : 前向窗口大小（帧数）
    zscore_threshold : 残差 Z-score 阈值
    min_samples : 每种工况最少样本

    Returns
    -------
    pd.DataFrame
        [时间戳, 参数, 工况, 实际值, 预测值, 残差, z_residual, is_anomaly, interpretation]
    """
    if monitor_cols is None:
        try:
            from src import config
            monitor_cols = [c for c in df_raw.columns if c in config.CMJ_MONITOR_POINTS]
        except ImportError:
            return pd.DataFrame()

    numeric_cols = [c for c in monitor_cols if c in df_raw.columns
                    and pd.api.types.is_numeric_dtype(df_raw[c])]
    if not numeric_cols:
        return pd.DataFrame()

    cond = df_raw[cond_col].fillna("未知")
    records = []

    for col in numeric_cols:
        vals = df_raw[col].values
        for state in cond.unique():
            state = str(state)
            mask = cond.values == state
            indices = np.where(mask)[0]
            if len(indices) < min_samples:
                continue

            for idx in indices:
                if idx < window:
                    continue
                # 前 window 帧（必须是同工况）
                prev_idxs = indices[indices < idx]
                if len(prev_idxs) < window:
                    continue
                prev_vals = vals[prev_idxs[-window:]]
                valid_prev = prev_vals[~np.isnan(prev_vals)]
                if len(valid_prev) < max(3, window // 2):
                    continue

                actual = float(vals[idx])
                if np.isnan(actual):
                    continue

                predicted = float(np.mean(valid_prev))
                residual = actual - predicted

                records.append({
                    "时间戳": df_raw.index[idx],
                    "参数": col,
                    "工况": state,
                    "实际值": actual,
                    "预测值": round(predicted, 4),
                    "残差": round(residual, 4),
                })

    if not records:
        return pd.DataFrame()

    result = pd.DataFrame(records)
    # 按参数+工况分组，计算残差的 Z-score
    result["z_residual"] = 0.0
    result["is_anomaly"] = False

    for (col, state), group in result.groupby(["参数", "工况"]):
        residuals = group["残差"].values
        r_mean = np.mean(residuals)
        r_std = np.std(residuals)
        if r_std > 0:
            z_scores = (residuals - r_mean) / r_std
        else:
            z_scores = np.zeros_like(residuals)
        result.loc[group.index, "z_residual"] = np.round(z_scores, 4)
        result.loc[group.index, "is_anomaly"] = np.abs(z_scores) > zscore_threshold

    # interpret
    def _interp(row):
        if not row["is_anomaly"]:
            return "正常"
        direction = "偏高" if row["残差"] > 0 else "偏低"
        return (
            f"残差异常：{row['参数']} {direction}（残差 Z-score={row['z_residual']:.1f}，"
            f"实际={row['实际值']:.1f} vs 预测={row['预测值']:.1f}）"
        )

    result["interpretation"] = result.apply(_interp, axis=1)
    result = result.sort_values(["时间戳", "参数"]).reset_index(drop=True)
    return result


def merge_anomaly_events(
    mahal_events: pd.DataFrame | None = None,
    if_events: pd.DataFrame | None = None,
    residual_events: pd.DataFrame | None = None,
    value_anomalies: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """合并多种异常检测方法的事件，生成统一的异常事件日志。

    Returns
    -------
    pd.DataFrame
        [时间戳, 工况, 方法, 分数, 是否异常, 归因文本]
        is_anomaly=True 表示该事件被至少一种方法标记为异常
    """
    parts = []

    if mahal_events is not None and not mahal_events.empty:
        m = mahal_events.rename(columns={"mahal_dist": "分数"})
        m["方法"] = "Mahalanobis"
        m["分数"] = m["分数"].fillna(0)
        parts.append(m[["时间戳", "工况", "方法", "分数", "is_anomaly", "interpretation"]])

    if if_events is not None and not if_events.empty:
        i = if_events.rename(columns={"if_score": "分数"})
        i["方法"] = "IsolationForest"
        i["分数"] = i["分数"].fillna(0)
        parts.append(i[["时间戳", "工况", "方法", "分数", "is_anomaly", "interpretation"]])

    if residual_events is not None and not residual_events.empty:
        r = residual_events.rename(columns={"z_residual": "分数"})
        r["方法"] = "残差"
        r["分数"] = r["分数"].fillna(0)
        parts.append(r[["时间戳", "工况", "方法", "分数", "is_anomaly", "interpretation"]])

    if value_anomalies is not None and not value_anomalies.empty:
        v = value_anomalies.rename(columns={"z-score": "分数"})
        v["方法"] = "单变量IQR+3σ"
        v["分数"] = v["分数"].fillna(0)
        # value_anomalies 每行是单参数，用参数名丰富归因
        def _v_interp(row):
            if not row.get("异常(短段过滤)", False):
                return "正常"
            return (
                f"单变量异常：{row['参数']}（z-score={row['分数']:.1f}，"
                f"实际={row['实际值']:.1f}，"
                f"均值={row['均值']:.1f}±{row['标准差']:.1f}）"
            )
        v["interpretation"] = v.apply(_v_interp, axis=1)
        parts.append(v[["时间", "工况", "方法", "分数", "异常(短段过滤)", "interpretation"]].rename(
            columns={"异常(短段过滤)": "is_anomaly", "时间": "时间戳"}))

    if not parts:
        return pd.DataFrame()

    result = pd.concat(parts, ignore_index=True)
    result = result.sort_values(["时间戳", "方法"]).reset_index(drop=True)

    # 按时间戳聚合：如果有任意方法标记异常则视为异常
    anom_by_time = result.groupby("时间戳")["is_anomaly"].any().reset_index()
    anom_by_time.columns = ["时间戳", "any_anomaly"]

    # 每条记录补充全局异常标记
    result = result.merge(anom_by_time, on="时间戳", how="left")
    result["any_anomaly"] = result["any_anomaly"].fillna(False)

    print(f"  合并异常事件: {len(result)} 条记录, "
          f"{result['any_anomaly'].sum()} 个异常时间点")
    return result
