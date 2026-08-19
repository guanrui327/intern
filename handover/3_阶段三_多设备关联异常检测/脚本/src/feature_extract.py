# -*- coding: utf-8 -*-
"""阶段二：特征提取模块。

提供分工况统计基线、滑动窗口时域特征、工况切换频率计算。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


def compute_baseline_profile(
    df: pd.DataFrame,
    cond_col: str,
    monitor_cols: list[str] | None = None,
    min_samples: int = 60,
) -> pd.DataFrame:
    """对每个工况状态计算各监测参数的统计基线。

    Parameters
    ----------
    df : 等间隔宽表（1min DatetimeIndex）
    cond_col : 工况列名
    monitor_cols : 待分析的监测参数列（默认从 config 读取）
    min_samples : 工况最少样本数，不足则跳过

    Returns
    -------
    pd.DataFrame
        [工况, 参数, 样本数, 均值, 标准差, 中位数, IQR, p5, p95, 最小值, 最大值]
    """
    if monitor_cols is None:
        try:
            from src import config
            monitor_cols = [c for c in df.columns if c in config.CMJ_MONITOR_POINTS]
        except ImportError:
            monitor_cols = [c for c in df.columns if c not in df.select_dtypes("object").columns]

    numeric_cols = [c for c in monitor_cols if c in df.columns
                    and pd.api.types.is_numeric_dtype(df[c])]
    if not numeric_cols:
        return pd.DataFrame()

    cond = df[cond_col].fillna("未知")
    records = []

    for state in cond.unique():
        state = str(state)
        if state == "未知":
            continue
        mask = cond.values == state
        n = int(mask.sum())
        if n < min_samples:
            continue

        for col in numeric_cols:
            vals = df[col].values[mask]
            valid = vals[~np.isnan(vals)]
            if len(valid) < min_samples:
                continue

            records.append({
                "工况": state,
                "参数": col,
                "样本数": len(valid),
                "均值": float(np.mean(valid)),
                "标准差": float(np.std(valid)),
                "中位数": float(np.median(valid)),
                "IQR": float(np.percentile(valid, 75) - np.percentile(valid, 25)),
                "p5": float(np.percentile(valid, 5)),
                "p95": float(np.percentile(valid, 95)),
                "最小值": float(np.min(valid)),
                "最大值": float(np.max(valid)),
            })

    return pd.DataFrame(records)


def save_baseline_profile(
    profile: pd.DataFrame,
    cond_col: str,
    device: str,
    output_dir: str | Path,
) -> Path:
    """保存基线 profile 为 CSV，返回路径。"""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_name = cond_col.replace("_", "_")
    path = output_dir / f"{device}_baseline_{safe_name}.csv"
    profile.to_csv(path, index=False, encoding="utf-8-sig")
    print(f"  基线 profile: {path}  ({len(profile)} 行)")
    return path


def extract_sliding_window_features(
    df: pd.DataFrame,
    monitor_cols: list[str] | None = None,
    window: int = 5,
    step: int = 1,
) -> pd.DataFrame:
    """提取滑动窗口时域特征。

    对每个监测参数，在每个滑动窗口内计算：
      - RMS（均方根）
      - 均值
      - 斜率（一阶线性拟合）
      - 峰峰值（max - min）
      - 标准差

    Parameters
    ----------
    df : 等间隔宽表（1min DatetimeIndex）
    monitor_cols : 监测参数列
    window : 窗口大小（帧数，默认 5 = 5 分钟）
    step : 步长（帧数，默认 1 = 1 分钟）

    Returns
    -------
    pd.DataFrame
        [时间戳, 参数, RMS, 均值, 斜率, 峰峰值, 标准差]
        每行 = 一个参数在一个窗口上的特征
    """
    if monitor_cols is None:
        try:
            from src import config
            monitor_cols = [c for c in df.columns if c in config.CMJ_MONITOR_POINTS]
        except ImportError:
            monitor_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]

    numeric_cols = [c for c in monitor_cols if c in df.columns
                    and pd.api.types.is_numeric_dtype(df[c])]
    if not numeric_cols:
        return pd.DataFrame()

    time_idx = df.index
    n = len(time_idx)
    records = []

    for col in numeric_cols:
        vals = df[col].values
        for start in range(0, n - window + 1, step):
            end = start + window
            chunk = vals[start:end]
            valid = chunk[~np.isnan(chunk)]
            if len(valid) < max(3, window // 2):
                continue

            rms = float(np.sqrt(np.mean(valid ** 2)))
            mean_v = float(np.mean(valid))
            p2p = float(np.max(valid) - np.min(valid))
            std_v = float(np.std(valid))

            # 斜率：线性回归 y = ax + b
            x = np.arange(len(valid))
            if np.std(valid) > 0 and np.std(x) > 0:
                a, _ = np.polyfit(x, valid, 1)
                slope = float(a)
            else:
                slope = 0.0

            records.append({
                "时间戳": time_idx[end - 1],
                "参数": col,
                "RMS": rms,
                "均值": mean_v,
                "斜率": slope,
                "峰峰值": p2p,
                "标准差": std_v,
            })

    result = pd.DataFrame(records)
    return result


def extract_rolling_correlations(
    df: pd.DataFrame,
    window: int = 5,
) -> pd.DataFrame:
    """提取参数间滚动相关系数特征。

    自动检测并计算以下配对的相关性：
    - 左右同名电机电流
    - 同电机电流-温度
    - 电流-速度
    - 油压-电流

    Returns
    -------
    pd.DataFrame
        [时间戳, {pair_label}_corr, ...]
        时间戳与 df 对齐
    """
    numeric_cols = [c for c in df.columns
                    if pd.api.types.is_numeric_dtype(df[c])]

    # 自动匹配配对规则
    pairs: list[tuple[str, str, str]] = []  # (col_a, col_b, label)
    for c in numeric_cols:
        # 左右电流配对
        if "电流" in c:
            for other in numeric_cols:
                if other <= c:
                    continue
                if "电流" not in other:
                    continue
                # 检查是否为左右配对（部位相同，左右不同）
                base_a = c.replace("左", "").replace("右", "")
                base_b = other.replace("左", "").replace("右", "")
                if base_a == base_b and ("左" in c or "右" in c) and ("左" in other or "右" in other):
                    label = f"{c.split('_')[-3]}_{c.split('_')[-2]}_左右电流" if len(c.split('_')) >= 3 else "左右电流"
                    pairs.append((c, other, label))

        # 电流-温度配对（同电机）
        if "电流" in c:
            temp_col = c.replace("电流", "温度")
            if temp_col in numeric_cols:
                short_name = "_".join(c.split("_")[-3:-1]) if len(c.split("_")) >= 3 else c
                pairs.append((c, temp_col, f"{short_name}_电流温度"))

        # 电流-速度配对
        if "电流" in c and ("牵引" in c or "速度" in c):
            speed_cols = [x for x in numeric_cols if "速度" in x]
            for sc in speed_cols:
                pairs.append((c, sc, f"{c.split('_')[-2]}_电流速度"))

        # 油压-电流配对
        if "油压" in c:
            current_cols = [x for x in numeric_cols if "油泵" in x and "电流" in x]
            for cc in current_cols:
                pairs.append((c, cc, "油压电流"))

    # 去重（同一对可能被多次匹配）
    seen = set()
    unique_pairs = []
    for a, b, label in pairs:
        key = tuple(sorted([a, b]))
        if key not in seen:
            seen.add(key)
            # 简化 label：尽量短
            short_label = label
            unique_pairs.append((a, b, short_label))

    if not unique_pairs:
        return pd.DataFrame()

    # 滚动计算 Pearson 相关系数（C 级 .rolling().corr() 替代 Python 循环）
    min_periods = max(3, window // 2)
    pieces = {}
    for col_a, col_b, label in unique_pairs:
        with np.errstate(invalid="ignore", divide="ignore"):
            corr_series = (
                df[col_a]
                .rolling(window, center=True, min_periods=min_periods)
                .corr(df[col_b])
            )
        pieces[label] = corr_series.values  # keep index alignment

    result = pd.DataFrame(pieces, index=df.index)
    # rolling corr 在窗口内方差为零时产出 inf，替换为 nan
    result.replace([np.inf, -np.inf], np.nan, inplace=True)
    return result


def build_window_feature_df(
    df: pd.DataFrame,
    cond_col: str,
    monitor_cols: list[str] | None = None,
    window: int = 5,
    step: int = 1,
    add_corr_features: bool = True,
) -> pd.DataFrame:
    """构建用于异常检测的滑动窗口特征宽表。

    对每个窗口，将所有参数的 RMS 和 斜率 展开为宽表，
    并附上该窗口结束时刻对应的工况。
    可选添加参数间滚动相关系数特征。

    Returns
    -------
    pd.DataFrame
        [时间戳, 工况, {param}_RMS, {param}_斜率, ...{pair}_corr]
    """
    # 1. 提取滑动窗口特征（长格式）
    long_features = extract_sliding_window_features(df, monitor_cols, window, step)
    if long_features.empty:
        return pd.DataFrame()

    # 2. 将 RMS 和 斜率 分别展开为宽表
    # RMS 宽表
    rms_wide = long_features.pivot_table(
        index="时间戳", columns="参数", values="RMS", aggfunc="first",
    )
    rms_wide.columns = [f"{c}_RMS" for c in rms_wide.columns]

    # 斜率宽表
    slope_wide = long_features.pivot_table(
        index="时间戳", columns="参数", values="斜率", aggfunc="first",
    )
    slope_wide.columns = [f"{c}_斜率" for c in slope_wide.columns]

    # 合并
    result = rms_wide.join(slope_wide, how="outer").reset_index()
    result = result.sort_values("时间戳").reset_index(drop=True)

    # 3. 附加工况（窗口结束时刻的工况）
    cond = df[cond_col].fillna("未知")
    result["工况"] = result["时间戳"].map(lambda t: cond.loc[t] if t in cond.index else "未知")
    result["工况"] = result["工况"].fillna("未知")

    # 4. 参数间相关系数特征
    if add_corr_features:
        corr_df = extract_rolling_correlations(df, window=window)
        if not corr_df.empty:
            corr_flat = corr_df.reset_index()
            # 确保索引列名为"时间戳"（corr_df 可能无 index name）
            corr_flat = corr_flat.rename(
                columns={corr_flat.columns[0]: "时间戳"},
            )
            base_cols = set(result.columns)
            result = result.merge(corr_flat, on="时间戳", how="left")
            # corr 列在参数恒定段（待机/停机）无定义 → NaN。
            # 用 merge 前后的列差定位 corr 列（pair label 不以 _corr 结尾），
            # 填 0.0：参数恒定 → "无动态相关"记 0，中性且不丢样本。
            # 只填 corr 列，RMS/斜率全 NaN 行仍按原逻辑 drop（见第 6 步）。
            corr_cols = [c for c in result.columns if c not in base_cols]
            if corr_cols:
                result[corr_cols] = result[corr_cols].fillna(0.0)
                print(f"    + {len(corr_cols)} 个相关系数特征列 (恒定段 NaN→0)")
            else:
                print(f"    + {len(corr_df.columns)} 个相关系数特征列")

    # 5. 移到第二列
    cols = ["时间戳", "工况"] + [c for c in result.columns if c not in ["时间戳", "工况"]]
    result = result[cols]

    # 6. 删除全 NaN 行（窗口特征没算出来的）
    feat_cols = [c for c in result.columns if c not in ["时间戳", "工况"]]
    result = result.dropna(subset=feat_cols, how="all")

    print(f"  滑动窗口特征宽表: {result.shape}")
    return result


def extract_frequency_features(
    df: pd.DataFrame,
    monitor_cols: list[str] | None = None,
    window: int = 30,
    step: int = 5,
    sampling_period: float = 1.0,
) -> pd.DataFrame:
    """提取滑动窗口频域特征（FFT 功率谱）。

    对每个监测参数在每个窗口内计算：
      - 主频（功率谱峰值对应频率）
      - 频谱质心（各频率的功率加权平均频率）
      - 频谱熵（功率谱归一化后信息熵，反映分布均匀度）
      - 低频段功率占比 (0~f_max/3)
      - 中频段功率占比 (f_max/3~2*f_max/3)
      - 高频段功率占比 (2*f_max/3~f_max)

    Parameters
    ----------
    df : 等间隔宽表（DatetimeIndex，假设采样间隔 = sampling_period 分钟）
    monitor_cols : 监测参数列
    window : 窗口大小（帧数，默认 30 = 30 分钟，保证 FFT 分辨率）
    step : 步长（帧数，默认 5 = 5 分钟）
    sampling_period : 采样间隔（分钟），用于计算物理频率

    Returns
    -------
    pd.DataFrame
        [时间戳, 参数, 主频, 频谱质心, 频谱熵, 低频占比, 中频占比, 高频占比]
    """
    if monitor_cols is None:
        try:
            from src import config
            monitor_cols = [c for c in df.columns if c in config.CMJ_MONITOR_POINTS]
        except ImportError:
            return pd.DataFrame()

    numeric_cols = [c for c in monitor_cols if c in df.columns
                    and pd.api.types.is_numeric_dtype(df[c])]
    if not numeric_cols:
        return pd.DataFrame()

    time_idx = df.index
    n = len(time_idx)
    records = []

    for col in numeric_cols:
        vals = df[col].values
        for start in range(0, n - window + 1, step):
            end = start + window
            chunk = vals[start:end]
            valid = chunk[~np.isnan(chunk)]
            if len(valid) < max(10, window // 2):
                continue

            # 去均值（直流分量归零）+ 汉宁窗
            detrended = valid - np.mean(valid)
            windowed = detrended * np.hanning(len(detrended))

            # FFT
            n_fft = len(windowed)
            fft_vals = np.fft.rfft(windowed)
            power = np.abs(fft_vals) ** 2
            freqs = np.fft.rfftfreq(n_fft, d=sampling_period)

            # 避免 DC 分量掩蔽
            if len(power) > 1:
                power[0] = 0.0

            total_power = power.sum()
            if total_power < 1e-12:
                continue

            # 1. 主频
            peak_idx = np.argmax(power[1:]) + 1 if len(power) > 1 else 0
            dominant_freq = float(freqs[peak_idx]) if peak_idx < len(freqs) else 0.0

            # 2. 频谱质心
            centroid = float(np.sum(freqs * power) / total_power)

            # 3. 频谱熵（归一化到 [0, 1]）
            p_norm = power / total_power
            # 避免 log(0)
            p_safe = np.where(p_norm > 0, p_norm, 1.0)
            entropy = -np.sum(p_norm * np.log(p_safe))
            max_entropy = np.log(len(p_norm)) if len(p_norm) > 1 else 1.0
            spectral_entropy = float(entropy / max_entropy) if max_entropy > 0 else 0.0

            # 4. 频段功率占比
            f_max = float(freqs[-1]) if len(freqs) > 0 else 1.0
            low_cut = f_max / 3.0
            high_cut = 2.0 * f_max / 3.0
            low_mask = freqs < low_cut
            mid_mask = (freqs >= low_cut) & (freqs < high_cut)
            high_mask = freqs >= high_cut

            low_ratio = float(power[low_mask].sum() / total_power) if low_mask.any() else 0.0
            mid_ratio = float(power[mid_mask].sum() / total_power) if mid_mask.any() else 0.0
            high_ratio = float(power[high_mask].sum() / total_power) if high_mask.any() else 0.0

            records.append({
                "时间戳": time_idx[end - 1],
                "参数": col,
                "主频": round(dominant_freq, 6),
                "频谱质心": round(centroid, 6),
                "频谱熵": round(spectral_entropy, 4),
                "低频占比": round(low_ratio, 4),
                "中频占比": round(mid_ratio, 4),
                "高频占比": round(high_ratio, 4),
            })

    result = pd.DataFrame(records)
    return result


def build_freq_feature_df(
    df: pd.DataFrame,
    cond_col: str,
    monitor_cols: list[str] | None = None,
    window: int = 30,
    step: int = 5,
) -> pd.DataFrame:
    """提取频域特征并透转为宽表，附加工况标签。

    对每个频域指标（主频/频谱质心/频谱熵/低频占比/中频占比/高频占比）
    分别透转为宽表（行=时间戳，列={param}_{metric}），然后合并。

    返回值的时间戳是滑动窗口结束时刻（与 ``build_window_feature_df`` 的索引对齐子集）。

    Parameters
    ----------
    df : 等间隔宽表（DatetimeIndex）
    cond_col : 工况列名
    monitor_cols : 监测参数列
    window : FFT 窗口大小（帧数，默认 30）
    step : 步长（帧数，默认 5）

    Returns
    -------
    pd.DataFrame
        [时间戳, 工况, {param}_主频, {param}_频谱质心, {param}_频谱熵,
         {param}_低频占比, {param}_中频占比, {param}_高频占比]
    """
    # 1. 提取频域特征（长表）
    long_df = extract_frequency_features(df, monitor_cols, window, step)
    if long_df.empty:
        return pd.DataFrame()

    # 2. 对每个频域指标分别透转
    freq_metrics = ["主频", "频谱质心", "频谱熵", "低频占比", "中频占比", "高频占比"]
    pivot_dfs = []
    for metric in freq_metrics:
        if metric not in long_df.columns:
            continue
        wide = long_df.pivot_table(
            index="时间戳", columns="参数", values=metric, aggfunc="first",
        )
        wide.columns = [f"{c}_{metric}" for c in wide.columns]
        pivot_dfs.append(wide)

    if not pivot_dfs:
        return pd.DataFrame()

    # 3. 合并所有指标宽表
    from functools import reduce
    freq_wide = reduce(lambda l, r: l.join(r, how="outer"), pivot_dfs)
    freq_wide = freq_wide.reset_index().sort_values("时间戳").reset_index(drop=True)

    # 4. 附加工况标签（取窗口结束时刻的工况）
    cond = df[cond_col].fillna("未知")
    freq_wide["工况"] = freq_wide["时间戳"].map(
        lambda t: cond.loc[t] if t in cond.index else "未知"
    )
    freq_wide["工况"] = freq_wide["工况"].fillna("未知")

    # 5. 重排列：时间戳, 工况, ...
    cols = ["时间戳", "工况"] + [
        c for c in freq_wide.columns if c not in ["时间戳", "工况"]
    ]
    freq_wide = freq_wide[cols]

    print(f"  频域特征宽表: {freq_wide.shape}")
    return freq_wide


def compute_condition_transition_rate(
    df: pd.DataFrame,
    cond_col: str,
) -> pd.DataFrame:
    """计算工况切换频率。

    Returns
    -------
    pd.DataFrame
        [工况, 段数, 总时长(min), 平均段长(min), 切换次数/小时]
    """
    cond = df[cond_col].fillna("未知")
    values = cond.values
    n = len(values)
    if n == 0:
        return pd.DataFrame()

    # 游程编码
    change_points = np.where(values[:-1] != values[1:])[0] + 1
    starts = np.concatenate([[0], change_points])
    ends = np.concatenate([change_points, [n]])
    run_lengths = ends - starts
    run_values = values[starts]

    total_hours = n / 60.0

    records = []
    for state in np.unique(run_values):
        mask = run_values == state
        durations = run_lengths[mask]
        n_segments = len(durations)
        total_min = int(durations.sum())
        avg_dur = round(float(np.mean(durations)), 1)
        # 切换次数 = 进入该状态的次数 ≈ 段数
        transitions_per_hour = round(n_segments / total_hours, 2) if total_hours > 0 else 0

        records.append({
            "工况": str(state),
            "段数": n_segments,
            "总时长(min)": total_min,
            "平均段长(min)": avg_dur,
            "切换次数/小时": transitions_per_hour,
        })

    return pd.DataFrame(records)
