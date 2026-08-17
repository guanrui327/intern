# -*- coding: utf-8 -*-
"""阶段三：多设备关联异常检测 pipeline。

Step 1 关联数据处理：CMJ/ZZJ 宽表对齐 → 系统宽表
Step 2 联合工况划分：设备_工况 × 工况 → 联合系统工况
Step 3 物理耦合分析：回归验证（诚实报告不可学）+ 联合工况规则事件（主检测器）
Step 4 跨设备 Mahalanobis：联合特征 + 联合工况
Step 5 事件传导关联：CMJ/ZZJ 异常事件时间对齐

复用：src/anomaly_mv.py / src/feature_extract.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

from src import config
from src.relation_data import (
    load_wide_tables,
    validate_alignment,
    build_system_table,
    add_joint_condition,
    condition_crosstab,
    joint_cond_stats,
)
from src.relation_model import (
    fit_coupling_regression,
    evaluate_generalization,
    detect_residual_anomaly,
    eventize_anomalies,
)
from src.relation_event import (
    extract_merged_events,
    rule_condition_events,
    propagate_events,
    propagation_stats,
)


def setup_dirs() -> None:
    for d in (config.PHASE3_DIR, config.PHASE3_DATA,
              config.PHASE3_FIGURES, config.PHASE3_REPORTS):
        d.mkdir(parents=True, exist_ok=True)


def step1_build_system_table() -> pd.DataFrame:
    """Step 1：对齐验证 + 系统宽表。"""
    cmj, zzj = load_wide_tables()
    info = validate_alignment(cmj, zzj)
    print("[Step1] 时间戳对齐:", info)
    # 系统宽表时间范围受限于较短的上游 CMJ（4-01~04-28）；ZZJ 覆盖到 5-31，
    # 其 4-28 后额外时间段为"CMJ 无数据期"，阶段三用不上但不算对齐缺失。
    # 关键验证：上游每个时间点都必须有下游对应（inner join 无损失）。
    assert info["cmj_only"] == 0, "CMJ 时间点存在无 ZZJ 对应，需检查重采样一致性"
    sys_df = build_system_table(cmj, zzj)
    # 数据质量：缺失检查
    null_pct = sys_df.isna().mean()
    print("[Step1] 系统宽表:", sys_df.shape)
    print("[Step1] 各列缺失率:\n", null_pct[null_pct > 0].to_string())
    return sys_df


def step2_joint_condition(sys_df: pd.DataFrame) -> pd.DataFrame:
    """Step 2：联合工况划分 + crosstab 验证。"""
    sys_df = add_joint_condition(sys_df)
    print("[Step2] 设备×ZZJ crosstab:\n", condition_crosstab(sys_df).to_string())
    print("[Step2] 联合工况占比:\n", joint_cond_stats(sys_df).to_string())
    return sys_df


def step3_coupling_analysis(sys_df: pd.DataFrame) -> pd.DataFrame:
    """Step 3：物理耦合分析（诚实版）。

    生产运行域（正常采煤）内 ZZJ 变频恒流控制 → 产量幅度→负载电流幅度
    不可学（线性 R²≈0、RF 验证 R²<0）。如实报告该结论，然后转用
    联合工况规则事件作为主检测器——错配/余流标签本身即编码物理规则。
    """
    print("\n[Step3] 物理耦合回归验证（训练域=生产运行）...")
    fit = fit_coupling_regression(sys_df)
    print("[Step3] 滞后测试 R²:\n", pd.DataFrame(fit["lag_results"]).to_string(index=False))
    print(f"[Step3] 最佳 lag={fit['best_lag']}min, R²={fit['best_r2']:.4f}, n={fit['n_train']}")
    if fit.get("coef"):
        print("[Step3] 回归系数:\n", pd.Series(fit["coef"]).to_string())
        print(f"[Step3] 截距: {fit['intercept']:.2f} A")

    # RF 泛化验证：识别 in-sample 过拟合（恒流域不可学的铁证）
    gen = evaluate_generalization(sys_df, fit)
    print(f"[Step3] RF 泛化验证: train_R²={gen['train_r2']:.4f}, "
          f"val_R²={gen['val_r2']:.4f}, val_MAE={gen['val_mae']:.2f}A, "
          f"y_val std={gen['y_val_std']:.2f}A (n_tr={gen['n_train']}, n_va={gen['n_val']})")
    if gen["val_r2"] <= 0:
        print("[Step3] 结论: 恒流控制域内幅度耦合不可学，回归 R² 仅为 in-sample 噪音。")
        print("[Step3] 耦合真身在二元开关层（割煤↔带载）+ 规则事件层，主检测器切换。")
        fit["learnable"] = False
    else:
        fit["learnable"] = True
        resid_df = detect_residual_anomaly(sys_df, fit)
        events = eventize_anomalies(resid_df)
        print(f"[Step3] 回归残差异常事件: {len(events)} 个")
        return resid_df

    # ── 主检测器：联合工况规则事件 ──
    mis = rule_condition_events(sys_df, ["采煤-转载错配"])
    yuli = rule_condition_events(sys_df, ["转载余流"])
    print(f"[Step3] 规则事件(采煤-转载错配=堵煤/断链风险): {len(mis)} 段, "
          f"覆盖 {int(sys_df[config.JOINT_COND_COL].eq('采煤-转载错配').sum())} 点")
    print(f"[Step3] 规则事件(转载余流=煤流滞后): {len(yuli)} 段, "
          f"覆盖 {int(sys_df[config.JOINT_COND_COL].eq('转载余流').sum())} 点")
    if not mis.empty:
        print("[Step3] 错配事件最长 5 段:\n", mis.sort_values("duration_min",
              ascending=False).head(5).to_string(index=False))

    # 保存规则事件
    out = config.PHASE3_DATA / "rule_events.csv"
    pd.concat([mis, yuli], ignore_index=True).to_csv(out, index=False)
    print(f"[Step3] 规则事件已保存: {out}")
    # 返回带 联合工况 的系统宽表（后续 Step4/5 用）
    return sys_df


def step4_joint_mahalanobis(sys_df: pd.DataFrame) -> pd.DataFrame:
    """Step 4：跨设备 Mahalanobis（联合特征 + 联合工况）。"""
    from src.anomaly_mv import mahalanobis_anomaly_detection

    print("\n[Step4] 跨设备 Mahalanobis（联合特征="
          f"{len(config.JOINT_MAHAL_FEATURES)} 维, cond=联合工况）...")
    d = sys_df.copy()
    d["时间戳"] = d.index
    mahal = mahalanobis_anomaly_detection(
        d, config.JOINT_MAHAL_FEATURES, cond_col=config.JOINT_COND_COL,
        alpha=0.001, min_samples=60)
    if mahal.empty:
        print("[Step4] 无输出")
        return mahal
    n_anom = int(mahal["is_anomaly"].sum())
    n_all = len(mahal)
    by_cond = (mahal[mahal["is_anomaly"]]
               .groupby("工况").size().sort_values(ascending=False))
    print(f"[Step4] 异常率: {n_anom}/{n_all} ({n_anom / n_all * 100:.2f}%)")
    print("[Step4] 异常点按联合工况分布:\n", by_cond.to_string())
    # 归因：异常点主要贡献特征
    top = (mahal.loc[mahal["is_anomaly"], "top_contributors"].str.split(", ")
           .explode().value_counts().head(5))
    print("[Step4] 异常点主要贡献特征:\n", top.to_string())
    out = config.PHASE3_DATA / "joint_mahalanobis.csv"
    mahal.to_csv(out, index=False)
    print(f"[Step4] 已保存: {out}")
    return mahal


def step5_event_propagation(sys_df: pd.DataFrame) -> dict:
    """Step 5：事件传导关联（阶段二单设备事件 + 规则事件）。"""
    p2 = config.PHASE2_DIR / "anomalies"
    print("\n[Step5] 事件传导关联...")
    cmj_ev = extract_merged_events(p2 / "cmj_merged_events.csv")
    zzj_ev = extract_merged_events(p2 / "zzj_merged_events.csv")
    print(f"[Step5] 单设备事件段: CMJ={len(cmj_ev)}, ZZJ={len(zzj_ev)}")

    # 双向验证：CMJ先行→ZZJ跟随 vs 反向，比较传导率
    fwd = propagate_events(cmj_ev, zzj_ev, window_min=config.PROPAGATION_WINDOW_MIN)
    rev = propagate_events(zzj_ev, cmj_ev, window_min=config.PROPAGATION_WINDOW_MIN)
    fs, rs = propagation_stats(fwd, len(cmj_ev)), propagation_stats(rev, len(zzj_ev))
    print(f"[Step5] CMJ→ZZJ: 传导率={fs['rate']}%, n_chain={fs['n_chain']}/{fs['n_up']}, "
          f"滞后中位={fs['lag_median']}min")
    print(f"[Step5] ZZJ→CMJ: 传导率={rs['rate']}%, n_chain={rs['n_chain']}/{rs['n_up']}, "
          f"滞后中位={rs['lag_median']}min")
    if fs["rate"] > rs["rate"]:
        print("[Step5] 方向结论: CMJ 先行→ZZJ 跟随 主导，传导假设成立。")
    else:
        print("[Step5] 方向结论: 传导方向偏反向或无主导，需人工核查。")
    if not fwd.empty:
        fwd.to_csv(config.PHASE3_DATA / "propagation_chains.csv", index=False)
        print("[Step5] 传导链样例:\n", fwd.sort_values("滞后_min").head(5).to_string(index=False))

    # 规则事件传导：错配→(余流) 或 余流→(停机后恢复) 的时间关联
    mis = rule_condition_events(sys_df, ["采煤-转载错配"])
    yuli = rule_condition_events(sys_df, ["转载余流"])
    mc = propagate_events(mis, yuli, window_min=config.PROPAGATION_WINDOW_MIN)
    ms = propagation_stats(mc, len(mis))
    print(f"[Step5] 规则事件传导: 错配→余流 传导率={ms['rate']}% "
          f"({ms['n_chain']}/{ms['n_up']} 条)")
    return {"fwd": fs, "rev": rs, "rule": ms}


def main() -> None:
    setup_dirs()
    sys_df = step1_build_system_table()
    sys_df = step2_joint_condition(sys_df)
    out_path = config.PHASE3_DATA / "system_table.parquet"
    sys_df.to_parquet(out_path)
    print(f"[Done] 系统宽表已保存: {out_path}")
    sys_df = step3_coupling_analysis(sys_df)
    step4_joint_mahalanobis(sys_df)
    step5_event_propagation(sys_df)


if __name__ == "__main__":
    main()
