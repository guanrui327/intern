# -*- coding: utf-8 -*-
"""聚类验证规则工况：KMeans 聚类 vs 规则标签的对比分析。"""

from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import adjusted_rand_score, silhouette_score, silhouette_samples
from sklearn.ensemble import RandomForestClassifier


# ── 聚类 vs 规则 ──────────────────────────────────────────


def cluster_vs_rule_labels(
    df: pd.DataFrame,
    feature_cols: list[str],
    rule_col: str | None = None,
    n_clusters: int | None = None,
) -> dict:
    """KMeans 聚类后与规则标签对比。

    参数缺失过多（>50%）的行会被剔除。

    Parameters
    ----------
    df :
        宽表（已含工况列）
    feature_cols :
        聚类特征列（电流、速度、摇臂角度等）
    rule_col :
        规则工况列名
    n_clusters :
        聚类数，如果为 None 则根据规则标签实际类别数确定

    Returns
    -------
    dict
        {
            "feature_cols": 实际使用的特征列表,
            "scaler": StandardScaler 对象,
            "kmeans": KMeans 对象（已拟合）,
            "labels": 聚类标签数组,
            "confusion_df": 交叉表 DataFrame,
            "n_clusters": 实际聚类数,
            "ari": adjusted_rand_score,
            "disagreement_mask": 不一致布尔数组（与 df 等长）,
            "df_clustered": 添加了 cluster_label 列的副本,
        }
    """
    if rule_col is None or rule_col not in df.columns:
        return {"error": f"规则列 '{rule_col}' 不存在"}
    # 只保留规则列中已知类别（排除未知）
    mask_known = df[rule_col].notna() & (df[rule_col] != "未知")
    sub = df.loc[mask_known].copy()
    sub = sub.dropna(subset=feature_cols, thresh=len(feature_cols) // 2)
    if len(sub) < 50:
        return {"error": "有效样本数过少"}

    actual_features = [c for c in feature_cols if c in sub.columns]

    # 特征矩阵
    X = sub[actual_features].fillna(sub[actual_features].median())
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    # 确定聚类数
    rule_labels = sub[rule_col].dropna().unique()
    if n_clusters is None:
        n_clusters = len(rule_labels)
    n_clusters = max(n_clusters, 2)

    # KMeans
    kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
    cluster_labels = kmeans.fit_predict(X_scaled)

    # 交叉表
    crosstab = pd.crosstab(
        sub[rule_col],
        cluster_labels,
        margins=True,
        margins_name="合计",
    )

    # ARI — 聚类与规则的一致性
    ari = adjusted_rand_score(sub[rule_col], cluster_labels)

    # 找出不一致样本（在原始 df 上标记）
    disagreement = pd.Series(False, index=df.index)
    # 只对 sub 内的行判断
    sub_idx = sub.index
    # 为 sub 内每行匹配：用调整兰德对齐不一定能一一对应，简单方法：
    # 如果标准标签对应的聚类标签众数不等于该行实际聚类标签
    label_map = _mode_mapping(sub[rule_col].values, cluster_labels)
    mapped = np.array([label_map.get(l, -1) for l in cluster_labels])
    disagree_mask = mapped != cluster_labels
    disagreement.loc[sub_idx] = disagree_mask

    result_df = sub.copy()
    result_df["cluster_label"] = cluster_labels
    result_df["cluster_vs_rule_OK"] = ~disagreement.loc[sub_idx]

    return {
        "feature_cols": actual_features,
        "scaler": scaler,
        "kmeans": kmeans,
        "labels": cluster_labels,
        "confusion_df": crosstab,
        "n_clusters": n_clusters,
        "ari": ari,
        "disagreement_mask": disagreement,
        "df_clustered": result_df,
    }


def _mode_mapping(true_labels, predicted_labels):
    """用多数投票将聚类标签映射到规则标签。"""
    from collections import Counter
    df_map = pd.DataFrame({"true": true_labels, "pred": predicted_labels})
    mapping = {}
    for pred_id, group in df_map.groupby("pred"):
        most_common = group["true"].mode()
        if len(most_common) > 0:
            mapping[pred_id] = most_common.iloc[0]
        else:
            mapping[pred_id] = "未知"
    return mapping


# ── 可视化 ─────────────────────────────────────────────────


def plot_cluster_comparison(
    result: dict,
    title: str = "聚类 vs 规则工况对比",
    output_path: str | Path | None = None,
) -> plt.Figure:
    """混淆矩阵热力图 + PCA 降维散点图，双图并行。"""
    if "error" in result:
        fig, ax = plt.subplots(figsize=(6, 2))
        ax.text(0.5, 0.5, result["error"], ha="center", va="center")
        return fig

    from matplotlib.colors import Normalize

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5.5))

    # ── 左：混淆矩阵 ──
    crosstab = result["confusion_df"]
    # 去掉总计行/列用于热力
    cm = crosstab.drop(index="合计", errors="ignore").drop(columns="合计", errors="ignore")
    if not cm.empty:
        cm_norm = cm.div(cm.sum(axis=1), axis=0).fillna(0)
        im = ax1.imshow(cm_norm.values, cmap="Blues", aspect="auto",
                        vmin=0, vmax=1)
        ax1.set_xticks(range(cm.shape[1]))
        ax1.set_yticks(range(cm.shape[0]))
        ax1.set_xticklabels(cm.columns, fontsize=7)
        ax1.set_yticklabels(cm.index, fontsize=8)
        ax1.set_xlabel("聚类标签", fontsize=9)
        ax1.set_ylabel("规则标签", fontsize=9)
        fig.colorbar(im, ax=ax1, shrink=0.7)
        # 格子内标数字
        for i in range(cm.shape[0]):
            for j in range(cm_norm.shape[1]):
                val = cm_norm.values[i, j]
                ax1.text(j, i, f"{val:.2f}", ha="center", va="center",
                         fontsize=7, color="white" if val > 0.5 else "black")
    ax1.set_title("混淆矩阵（归一化）", fontsize=10)

    # ── 右：PCA 散点 ──
    dfc = result["df_clustered"]
    feature_cols = result["feature_cols"]
    X = dfc[feature_cols].fillna(dfc[feature_cols].median())
    X_scaled = result["scaler"].transform(X)

    pca = PCA(n_components=2, random_state=42)
    coords = pca.fit_transform(X_scaled)
    variance = pca.explained_variance_ratio_

    # 一致性着色
    ok_mask = dfc["cluster_vs_rule_OK"].values
    colors = np.where(ok_mask, "#4CAF50", "#E53935")
    sizes = np.where(ok_mask, 6, 12)

    scatter = ax2.scatter(coords[:, 0], coords[:, 1], c=colors,
                          s=sizes, alpha=0.6, edgecolors="none")
    ax2.set_xlabel(f"PC1 ({variance[0]:.1%})", fontsize=9)
    ax2.set_ylabel(f"PC2 ({variance[1]:.1%})", fontsize=9)
    ax2.set_title(f"PCA 降维 — 绿=一致, 红=不一致", fontsize=10)
    ax2.grid(True, alpha=0.2)

    # 图例
    from matplotlib.patches import Patch
    legend_elements = [
        Patch(facecolor="#4CAF50", label=f"一致 (ARI={result['ari']:.3f})"),
        Patch(facecolor="#E53935", label="不一致"),
    ]
    ax2.legend(handles=legend_elements, fontsize=7, loc="best")

    fig.suptitle(title, fontsize=12, fontweight="bold")
    fig.tight_layout()

    if output_path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(output_path, bbox_inches="tight", dpi=130)
    return fig


# ── 分歧分析 ──────────────────────────────────────────────


def analyze_disagreement(
    result: dict,
    df_original: pd.DataFrame | None = None,
    rule_col: str | None = None,
) -> pd.DataFrame:
    """分析规则与聚类不一致的样本：时序分布、参数特征。

    Returns
    -------
    pd.DataFrame
        [时间, 规则标签, 聚类标签, 一致否, 各参数值]
    """
    if "error" in result:
        return pd.DataFrame(columns=["结果"]) if "error" in result else pd.DataFrame()

    dfc = result["df_clustered"]
    mask = ~dfc["cluster_vs_rule_OK"]

    if mask.sum() == 0:
        return pd.DataFrame(columns=["时间", "规则标签", "聚类标签",
                                      "一致否", "参数"])

    disagree = dfc.loc[mask, [c for c in dfc.columns if c not in
                              ("cluster_label", "cluster_vs_rule_OK")] + ["cluster_label"]].copy()
    disagree["一致否"] = False

    # 加入时间索引
    disagree = disagree.reset_index().rename(columns={"index": "时间"})
    if rule_col is None or rule_col not in disagree.columns:
        # fallback: 扫描已知工况列
        for candidate in ["设备_工况", "截割部_工况", "牵引部_工况", "L2", "L1"]:
            if candidate in disagree.columns:
                rule_col = candidate
                break
        else:
            rule_col = ""
    disagree["规则标签"] = disagree.get(rule_col, "")

    columns = ["时间", "规则标签", "cluster_label", "一致否"]
    extra_cols = [c for c in disagree.columns if c not in columns]
    result_cols = [c for c in columns if c in disagree.columns] + extra_cols
    return disagree[result_cols]


# ── 特征重要性（Random Forest） ─────────────────────────


def analyze_feature_importance(result: dict) -> pd.DataFrame:
    """用 Random Forest 评估每个特征对聚类标签的贡献度。

    Parameters
    ----------
    result : dict
        cluster_vs_rule_labels() 返回的结果字典

    Returns
    -------
    pd.DataFrame
        [特征名, 重要性, 累积重要性] 按重要性降序排列。
    """
    if "error" in result:
        return pd.DataFrame()

    dfc = result["df_clustered"]
    feature_cols = result["feature_cols"]
    if len(dfc) < 20 or len(feature_cols) < 2:
        return pd.DataFrame()

    X = dfc[feature_cols].fillna(dfc[feature_cols].median())
    X_scaled = result["scaler"].transform(X)
    y = np.asarray(result["labels"])

    # ── RF 训练数据按工况分层抽样到 ≤15k 行 ──
    # 仅影响特征重要性展示（n_estimators/种子不变），不影响 ARI/聚类标签。
    MAX_TRAIN_ROWS = 15_000
    if len(y) > MAX_TRAIN_ROWS:
        sample_mask = np.zeros(len(y), dtype=bool)
        rng = np.random.RandomState(42)
        labels_u = np.unique(y)
        per_class = max(1, MAX_TRAIN_ROWS // len(labels_u))
        for lbl in labels_u:
            idx_lbl = np.where(y == lbl)[0]
            take = min(len(idx_lbl), per_class)
            sample_mask[rng.choice(idx_lbl, size=take, replace=False)] = True
        X_scaled = X_scaled[sample_mask]
        y = y[sample_mask]

    rf = RandomForestClassifier(
        n_estimators=100, random_state=42, n_jobs=-1,
        class_weight="balanced",
    )
    rf.fit(X_scaled, y)

    importance_df = pd.DataFrame({
        "特征名": feature_cols,
        "重要性": rf.feature_importances_,
    }).sort_values("重要性", ascending=False).reset_index(drop=True)
    importance_df["累积重要性"] = importance_df["重要性"].cumsum()

    return importance_df


def analyze_cluster_quality(result: dict) -> dict:
    """计算聚类质量指标（轮廓系数、簇内方差等）。

    Parameters
    ----------
    result : dict
        cluster_vs_rule_labels() 返回的结果字典

    Returns
    -------
    dict
        {"silhouette_score": float, "per_label_silhouette": dict, "inertia": float|None}
    """
    if "error" in result:
        return {"error": result["error"]}

    dfc = result["df_clustered"]
    feature_cols = result["feature_cols"]
    if len(dfc) < 20 or len(feature_cols) < 2:
        return {"error": "有效样本数过少"}

    X = dfc[feature_cols].fillna(dfc[feature_cols].median())
    X_scaled = result["scaler"].transform(X)
    labels = result["labels"]

    # ── silhouette 按标签分层抽样到 ≤15k 行 ──
    # 全量 O(n²) 配对距离约 34s/部位（5 部位 ≈ 170s）。抽样后 ~5s/部位。
    # 仅影响报告的 silhouette 值（抽样估计，报告标注），不影响 ARI/聚类标签。
    MAX_SIL_ROWS = 15_000
    if len(labels) > MAX_SIL_ROWS:
        sil_mask = np.zeros(len(labels), dtype=bool)
        rng = np.random.RandomState(42)
        sil_labels_u = np.unique(labels)
        per_class = max(1, MAX_SIL_ROWS // len(sil_labels_u))
        for lbl in sil_labels_u:
            idx_lbl = np.where(labels == lbl)[0]
            take = min(len(idx_lbl), per_class)
            sil_mask[rng.choice(idx_lbl, size=take, replace=False)] = True
        X_sil = X_scaled[sil_mask]
        labels_sil = labels[sil_mask]
    else:
        X_sil, labels_sil = X_scaled, labels

    try:
        sil_score = silhouette_score(X_sil, labels_sil)
        sil_samples = silhouette_samples(X_sil, labels_sil)

        per_label = {}
        for label in np.unique(labels_sil):
            mask = labels_sil == label
            per_label[int(label)] = float(np.mean(sil_samples[mask]))

        inertia = result.get("kmeans", None)
        inertia_val = inertia.inertia_ if hasattr(inertia, "inertia_") else None

        return {
            "silhouette_score": float(sil_score),
            "per_label_silhouette": per_label,
            "inertia": inertia_val,
        }
    except Exception as e:
        return {"error": str(e)}


def plot_feature_importance(
    importance_df: pd.DataFrame,
    title: str = "特征重要性（Random Forest）",
    output_path: str | Path | None = None,
    silhouette: float | None = None,
) -> plt.Figure:
    """水平条形图：各特征对聚类的重要性排名。"""
    if importance_df.empty:
        fig, ax = plt.subplots(figsize=(6, 2))
        ax.text(0.5, 0.5, "无特征重要性数据", ha="center", va="center")
        return fig

    fig, ax = plt.subplots(figsize=(8, max(3, len(importance_df) * 0.4)))

    names = importance_df["特征名"].values
    values = importance_df["重要性"].values

    y_pos = np.arange(len(names))
    bars = ax.barh(y_pos, values[::-1], color="#2196F3", edgecolor="white", height=0.6)
    ax.set_yticks(y_pos)
    ax.set_yticklabels(names[::-1], fontsize=8)
    ax.invert_yaxis()
    ax.set_xlabel("特征重要性", fontsize=9)
    ax.set_title(title, fontsize=11, fontweight="bold")

    for bar, val in zip(bars, values[::-1]):
        ax.text(bar.get_width() + 0.005, bar.get_y() + bar.get_height() / 2,
                f"{val:.1%}", va="center", fontsize=7)

    if silhouette is not None:
        ax.text(0.95, 0.95, f"Silhouette Score = {silhouette:.3f}",
                transform=ax.transAxes, ha="right", va="top",
                fontsize=9, bbox=dict(facecolor="white", alpha=0.8, edgecolor="#ccc"))

    fig.tight_layout()
    if output_path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(output_path, bbox_inches="tight", dpi=130)
    plt.close(fig)
    return fig


def generate_cluster_report(
    df: pd.DataFrame,
    feature_cols: list[str],
    rule_col: str | None = None,
    output_dir: str | Path | None = None,
    suffix: str = "",
) -> dict:
    """一键完成聚类 → 可视化 → CSV 导出。

    Parameters
    ----------
    df : 宽表
    feature_cols : 聚类特征列
    rule_col : 规则工况列名（如 "截割部_工况"）
    output_dir : 输出目录
    suffix : 文件名后缀，如 "_截割部" → cluster_vs_截割部.png

    Returns
    -------
    dict
        { "result": dict, "plot_path": Path|None, "csv_path": Path|None,
          "feature_importance": DataFrame, "quality": dict,
          "feature_importance_csv": Path|None, "feature_importance_png": Path|None }
    """
    result = cluster_vs_rule_labels(df, feature_cols, rule_col)

    plot_path = None
    csv_path = None
    fi_df = pd.DataFrame()
    quality = {}
    fi_csv_path = None
    fi_png_path = None

    if output_dir:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        if "error" not in result:
            plot_name = f"cluster_vs{suffix}.png" if suffix else "cluster_vs.png"
            plot_path = output_dir / plot_name
            plot_cluster_comparison(result, output_path=plot_path)

            # 特征重要性
            fi_df = analyze_feature_importance(result)
            quality = analyze_cluster_quality(result)
            sil = quality.get("silhouette_score") if "error" not in quality else None

            fi_csv_name = f"feature_importance{suffix}.csv" if suffix else "feature_importance.csv"
            fi_csv_path = output_dir / fi_csv_name
            fi_df.to_csv(fi_csv_path, index=False, encoding="utf-8-sig")

            fi_png_name = f"feature_importance{suffix}.png" if suffix else "feature_importance.png"
            fi_png_path = output_dir / fi_png_name
            plot_feature_importance(fi_df, output_path=fi_png_path, silhouette=sil)

        disagree = analyze_disagreement(result, rule_col=rule_col)
        csv_name = f"cluster_disagreement{suffix}.csv" if suffix else "cluster_disagreement.csv"
        csv_path = output_dir / csv_name
        disagree.to_csv(csv_path, index=False, encoding="utf-8-sig")

    return {
        "result": result,
        "plot_path": plot_path,
        "csv_path": csv_path,
        "feature_importance": fi_df,
        "quality": quality,
        "feature_importance_csv": fi_csv_path,
        "feature_importance_png": fi_png_path,
    }


def generate_per_part_cluster_reports(
    df: pd.DataFrame,
    output_dir: str | Path,
    part_feature_map: dict[str, list[str]] | None = None,
) -> dict[str, dict]:
    """一键为所有 4 个部位跑聚类验证。

    part_feature_map: { "截割部": [feature_cols...], ... }
    """
    if part_feature_map is None:
        from src import config
        # 用正则匹配列名
        import re
        part_feature_map = {}
        for part, keywords in config.CMJ_PART_CLUSTER_FEATURES.items():
            matched = []
            for kw in keywords:
                pattern = re.compile(kw.replace(".*", ".*"))
                matched.extend([c for c in df.columns if pattern.search(c)])
            part_feature_map[part] = list(set(matched))

    results = {}
    part_col_map = {
        "截割部": "截割部_工况",
        "牵引部": "牵引部_工况",
        "油泵": "油泵_工况",
        "破碎机": "破碎机_工况",
        "转载机": "工况",
    }

    for part, features in part_feature_map.items():
        rule_col = part_col_map.get(part)
        if not rule_col or rule_col not in df.columns:
            print(f"  跳过 {part}: 缺少工况列 {rule_col}")
            continue
        if not features:
            print(f"  跳过 {part}: 无匹配特征列")
            continue

        safe_part = part
        report = generate_cluster_report(
            df, features, rule_col=rule_col,
            output_dir=output_dir, suffix=f"_{safe_part}",
        )
        results[part] = report
        if "error" not in report["result"]:
            ari = report["result"]["ari"]
            quality = report.get("quality", {})
            if "error" not in quality:
                sil = quality.get("silhouette_score", "N/A")
                print(f"  {part}: ARI={ari:.4f}, Silhouette={sil:.4f}")
            else:
                print(f"  {part}: ARI={ari:.4f}")
        else:
            print(f"  {part}: {report['result']['error']}")

    return results
