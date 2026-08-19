# -*- coding: utf-8 -*-
"""阶段三：物理耦合回归模块。

模型：CMJ 产量代理 → ZZJ 负载。
- 训练域：联合工况=生产运行（正常采煤基线）
- 滞后测试：煤流传播滞后，对 X 做 lag 0~5min 测试选最佳 R²
- 残差异常：全表预测 → 残差 = 实际 − 预测 → IQR 阈值
- 物理语义：残差<0 = 下游欠载（堵煤/卡链/断链风险）；残差>0 = 下游过载（煤流堆积）
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, r2_score

from src import config


def _lag_align(df: pd.DataFrame, x_cols: list[str], y_col: str,
               lag: int) -> pd.DataFrame:
    """按滞后对齐：t 时刻的负载 y 由 t-lag 时刻的产量 X 决定（煤流传播）。

    对 X 列整体 shift(lag)，即第 t 行的 X = t-lag 时刻的产量。
    返回 dropna 后的对齐表。
    """
    d = df.copy()
    if lag > 0:
        d[x_cols] = d[x_cols].shift(lag)
    d = d.dropna(subset=x_cols + [y_col])
    return d


def fit_coupling_regression(sys_df: pd.DataFrame, x_cols: list[str] | None = None,
                            y_col: str | None = None,
                            train_cond: str = "生产运行",
                            max_lag: int = config.MAX_LAG_MIN,
                            model: str = "linear") -> dict:
    """训练物理耦合回归，滞后测试选最佳 R²。返回 fit 结果 dict。

    model: "linear"（基线，可解释）| "rf"（非线性兜底）
    """
    x_cols = x_cols or config.CMJ_PROD_FEATURES
    y_col = y_col or config.ZZJ_LOAD_TARGET
    cond_col = config.JOINT_COND_COL

    lag_results = []
    for lag in range(max_lag + 1):
        d = _lag_align(sys_df, x_cols, y_col, lag)
        train = d[d[cond_col] == train_cond]
        if len(train) < 100:
            continue
        X = train[x_cols].values
        y = train[y_col].values
        est = (RandomForestRegressor(n_estimators=200, random_state=0, n_jobs=-1)
               if model == "rf" else LinearRegression())
        est.fit(X, y)
        r2 = r2_score(y, est.predict(X))
        lag_results.append({"lag": lag, "r2": r2, "n": len(y)})
    if not lag_results:
        raise ValueError(f"训练域 [{train_cond}] 样本不足")

    best = max(lag_results, key=lambda r: r["r2"])
    best_lag = best["lag"]

    # 用最佳 lag 重建模型 + 系数/特征重要性
    d = _lag_align(sys_df, x_cols, y_col, best_lag)
    train = d[d[cond_col] == train_cond]
    X, y = train[x_cols].values, train[y_col].values
    est = (RandomForestRegressor(n_estimators=200, random_state=0, n_jobs=-1)
           if model == "rf" else LinearRegression())
    est.fit(X, y)

    fit = {
        "model": model,
        "best_lag": best_lag,
        "best_r2": best["r2"],
        "est": est,
        "x_cols": x_cols,
        "y_col": y_col,
        "train_cond": train_cond,
        "n_train": len(y),
        "lag_results": lag_results,
    }
    if model == "rf":
        fit["importances"] = dict(zip(x_cols, est.feature_importances_))
    else:
        fit["coef"] = dict(zip(x_cols, est.coef_.tolist()))
        fit["intercept"] = float(est.intercept_)
    return fit


def evaluate_generalization(sys_df: pd.DataFrame, fit: dict,
                            val_ratio: float = 0.3) -> dict:
    """RF 时间序 train/val 泛化评估（识别 in-sample 过拟合）。

    恒流控制域内产量幅度→负载不可学时，RF 训练 R² 虚高但验证 R²<0。
    """
    x_cols, y_col = fit["x_cols"], fit["y_col"]
    lag = fit["best_lag"]
    d = _lag_align(sys_df, x_cols, y_col, lag)
    train = d[d[config.JOINT_COND_COL] == fit["train_cond"]]
    n = len(train)
    cut = int(n * (1 - val_ratio))
    Xtr, ytr = train[x_cols].iloc[:cut].values, train[y_col].iloc[:cut].values
    Xva, yva = train[x_cols].iloc[cut:].values, train[y_col].iloc[cut:].values
    est = RandomForestRegressor(n_estimators=200, random_state=0, n_jobs=-1)
    est.fit(Xtr, ytr)
    return {
        "train_r2": float(r2_score(ytr, est.predict(Xtr))),
        "val_r2": float(r2_score(yva, est.predict(Xva))),
        "val_mae": float(mean_absolute_error(yva, est.predict(Xva))),
        "y_val_std": float(yva.std()),
        "n_train": len(Xtr),
        "n_val": len(Xva),
    }


def _residual_band(train_resid: pd.Series, iqr_mult: float,
                   abs_threshold: float | None) -> tuple[float, float]:
    """训练域残差 → 异常带 [lo, hi]。IQR 或绝对阈值。"""
    q1, q3 = train_resid.quantile(0.25), train_resid.quantile(0.75)
    iqr = q3 - q1
    lo = q1 - iqr_mult * iqr
    hi = q3 + iqr_mult * iqr
    if abs_threshold is not None:
        lo = min(lo, -abs_threshold)
        hi = max(hi, abs_threshold)
    return float(lo), float(hi)


def detect_residual_anomaly(sys_df: pd.DataFrame, fit: dict,
                            iqr_mult: float = config.RESIDUAL_IQR_MULT,
                            abs_threshold: float | None = None,
                            detect_conds: list[str] | None = None) -> pd.DataFrame:
    """回归残差异常（仅检测域内判定）。

    只在 detect_conds（默认=训练域"生产运行"）内做残差异常判定——
    模型只在正常采煤域训练，非生产运行域（停机/待机/错配等）的外推无意义，
    那些域由联合工况物理规则直接覆盖（错配=堵煤、余流=滞后）。

    返回带 [y, y_pred, resid, resid_anomaly, resid_dir] 列的 DataFrame。
    resid_dir: "欠载"(实际<期望，半堵/断链风险) / "过载"(实际>期望，煤流堆积)
    """
    x_cols, y_col = fit["x_cols"], fit["y_col"]
    cond_col = config.JOINT_COND_COL
    lag = fit["best_lag"]
    detect_conds = detect_conds or [fit["train_cond"]]

    d = _lag_align(sys_df, x_cols, y_col, lag)
    d["y_pred"] = fit["est"].predict(d[x_cols].values)
    d["resid"] = d[y_col] - d["y_pred"]

    # 阈值取自训练域（正常采煤）残差分布
    train_resid = d.loc[d[cond_col] == fit["train_cond"], "resid"]
    lo, hi = _residual_band(train_resid, iqr_mult, abs_threshold)

    d["resid_anomaly"] = False
    d["resid_dir"] = "正常"
    in_detect = d[cond_col].isin(detect_conds)
    d.loc[in_detect, "resid_anomaly"] = ((d.loc[in_detect, "resid"] < lo)
                                          | (d.loc[in_detect, "resid"] > hi))
    d.loc[in_detect & (d["resid"] < lo), "resid_dir"] = "欠载"
    d.loc[in_detect & (d["resid"] > hi), "resid_dir"] = "过载"
    d["resid_lo"] = lo
    d["resid_hi"] = hi
    d.attrs["band"] = (lo, hi)
    d.attrs["train_std"] = float(train_resid.std())
    d.attrs["detect_conds"] = detect_conds
    return d


def eventize_anomalies(resid_df: pd.DataFrame,
                       gap_min: int = 5) -> pd.DataFrame:
    """连续异常点聚合成事件区间（间隔 > gap_min 分钟则断开）。"""
    ev = resid_df[resid_df["resid_anomaly"]].copy()
    if ev.empty:
        return ev
    idx_name = ev.index.name or "time"
    ev = ev.reset_index()
    delta_min = ev[idx_name].diff().dt.total_seconds() / 60.0
    new_seg = (delta_min.fillna(999.0) > gap_min).cumsum()  # 首点强制新段
    ev["event_id"] = new_seg
    out = ev.groupby("event_id").agg(
        start=(idx_name, "first"),
        end=(idx_name, "last"),
        duration_min=(idx_name,
                      lambda s: (s.max() - s.min()).total_seconds() / 60.0 + 1),
        n_points=(idx_name, "size"),
        min_resid=("resid", "min"),
        max_resid=("resid", "max"),
        dominates=("resid_dir",
                   lambda s: s.mode().iloc[0] if len(s) else ""),
    ).reset_index(drop=True)
    return out
