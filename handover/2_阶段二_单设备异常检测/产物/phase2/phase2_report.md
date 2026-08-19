# 阶段二：异常检测报告

> 生成时间：2026-08-04 20:15
> 说明：基于阶段一工况划分 + 滑动窗口特征 + 多变量异常检测

---
## 总体概览

### 采煤机 - 截割部

- **总事件记录数**: 1174355
- **异常时间点**: 410094
- **检测方法**: Mahalanobis, IsolationForest, 残差, 单变量IQR+3σ

### 采煤机 - 牵引部

- **总事件记录数**: 1487884
- **异常时间点**: 659991
- **检测方法**: Mahalanobis, IsolationForest, 残差, 单变量IQR+3σ

### 采煤机 - 油泵

- **总事件记录数**: 1331316
- **异常时间点**: 552936
- **检测方法**: Mahalanobis, IsolationForest, 残差, 单变量IQR+3σ

### 采煤机 - 破碎机

- **总事件记录数**: 1174628
- **异常时间点**: 336788
- **检测方法**: Mahalanobis, IsolationForest, 残差, 单变量IQR+3σ

### 转载机

- **总事件记录数**: 2270485
- **异常时间点**: 924482
- **检测方法**: Mahalanobis, IsolationForest, 残差, 单变量IQR+3σ

---
## 1. 分工况基线

每种工况下各监测参数的统计基线（均值、中位数、IQR、p5/p95）。

### 采煤机 - 截割部

- **截割部_工况**: 14 参数 × 7 工况

### 采煤机 - 牵引部

- **牵引部_工况**: 18 参数 × 4 工况

### 采煤机 - 油泵

- **油泵_工况**: 16 参数 × 3 工况

### 采煤机 - 破碎机

- **破碎机_工况**: 14 参数 × 3 工况

### 转载机

- **工况**: 12 参数 × 3 工况

---
## 2. 多变量异常检测

### 采煤机 - 截割部

- **Mahalanobis 距离**: 7863/39126 异常点
  - 各工况 χ² 阈值自适应计算
  - 特征贡献分解：对每个异常点输出 Top-3 贡献特征及百分比
- **Isolation Forest**: 68/39126 异常点
- **残差异常检测 (AR 前向预测)**: 9589/547827 异常点

### 采煤机 - 牵引部

- **Mahalanobis 距离**: 11987/39126 异常点
  - 各工况 χ² 阈值自适应计算
  - 特征贡献分解：对每个异常点输出 Top-3 贡献特征及百分比
- **Isolation Forest**: 40/39126 异常点
- **残差异常检测 (AR 前向预测)**: 11268/704659 异常点

### 采煤机 - 油泵

- **Mahalanobis 距离**: 7859/39126 异常点
  - 各工况 χ² 阈值自适应计算
  - 特征贡献分解：对每个异常点输出 Top-3 贡献特征及百分比
- **Isolation Forest**: 28/39126 异常点
- **残差异常检测 (AR 前向预测)**: 9331/626438 异常点

### 采煤机 - 破碎机

- **Mahalanobis 距离**: 5003/39126 异常点
  - 各工况 χ² 阈值自适应计算
  - 特征贡献分解：对每个异常点输出 Top-3 贡献特征及百分比
- **Isolation Forest**: 28/39126 异常点
- **残差异常检测 (AR 前向预测)**: 8561/548100 异常点

### 转载机

- **Mahalanobis 距离**: 24621/87327 异常点
  - 各工况 χ² 阈值自适应计算
  - 特征贡献分解：对每个异常点输出 Top-3 贡献特征及百分比
- **Isolation Forest**: 10/87327 异常点
- **残差异常检测 (AR 前向预测)**: 16594/1047834 异常点

---
## 3. 单变量异常检测（IQR + 3σ）

### 采煤机 - 截割部

- **截割部_工况**: 13134/548276 = 2.4% 异常点
    - 轻微: 9475
    - 一般: 2369
    - 严重: 948
    - 较重: 342

### 采煤机 - 牵引部

- **牵引部_工况**: 28302/704973 = 4.0% 异常点
    - 轻微: 24134
    - 一般: 1587
    - 较重: 1299
    - 严重: 1282

### 采煤机 - 油泵

- **油泵_工况**: 33947/626626 = 5.4% 异常点
    - 轻微: 27956
    - 一般: 2503
    - 严重: 2317
    - 较重: 1171

### 采煤机 - 破碎机

- **破碎机_工况**: 15964/548276 = 2.9% 异常点
    - 一般: 9839
    - 轻微: 5404
    - 严重: 652
    - 较重: 69

### 转载机

- **工况**: 26389/1047997 = 2.5% 异常点
    - 轻微: 17139
    - 一般: 4236
    - 较重: 2610
    - 严重: 2404

---
## 4. 工况切换频率

### 采煤机 - 截割部

**截割部_工况**:

| 工况 | 段数 | 总时长(min) | 平均段长(min) | 切换次数/小时 |
|------|------|------------|-------------|-------------|
| 停机 | 144 | 2851 | 19.8 | 0.22 |
| 割煤中位 | 2840 | 9738 | 3.4 | 4.35 |
| 割煤低位 | 31 | 335 | 10.8 | 0.05 |
| 割煤高位 | 2334 | 7812 | 3.3 | 3.57 |
| 待机 | 652 | 11316 | 17.4 | 1.0 |
| 待机-高位 | 426 | 2962 | 7.0 | 0.65 |
| 调架中 | 2588 | 4170 | 1.6 | 3.96 |

### 采煤机 - 牵引部

**牵引部_工况**:

| 工况 | 段数 | 总时长(min) | 平均段长(min) | 切换次数/小时 |
|------|------|------------|-------------|-------------|
| 停机 | 1565 | 13140 | 8.4 | 2.4 |
| 待机 | 1428 | 7096 | 5.0 | 2.19 |
| 空载牵引 | 409 | 447 | 1.1 | 0.63 |
| 重载牵引 | 2522 | 18501 | 7.3 | 3.86 |

### 采煤机 - 油泵

**油泵_工况**:

| 工况 | 段数 | 总时长(min) | 平均段长(min) | 切换次数/小时 |
|------|------|------------|-------------|-------------|
| 停机 | 1233 | 10594 | 8.6 | 1.89 |
| 轻载 | 236 | 5987 | 25.4 | 0.36 |
| 重载 | 1178 | 22603 | 19.2 | 1.8 |

### 采煤机 - 破碎机

**破碎机_工况**:

| 工况 | 段数 | 总时长(min) | 平均段长(min) | 切换次数/小时 |
|------|------|------------|-------------|-------------|
| 停机 | 858 | 22106 | 25.8 | 1.31 |
| 带载运行 | 107 | 112 | 1.0 | 0.16 |
| 空载运行 | 927 | 16966 | 18.3 | 1.42 |

### 转载机

**工况**:

| 工况 | 段数 | 总时长(min) | 平均段长(min) | 切换次数/小时 |
|------|------|------------|-------------|-------------|
| 停机 | 1369 | 34682 | 25.3 | 0.94 |
| 带载运行 | 1152 | 51717 | 44.9 | 0.79 |
| 空载运行 | 703 | 938 | 1.3 | 0.48 |

---
## 5. 图表输出

### 采煤机 - 截割部

- [Mahalanobis 时间线](anomalies/cmj_截割部_mahalanobis_timeline.png)
- [Mahalanobis 特征贡献分解](anomalies/cmj_截割部_feature_breakdown.png)
- [Isolation Forest vs Mahalanobis 对比](anomalies/cmj_截割部_if_comparison.png)
- [归因总结](anomalies/cmj_截割部_interpretation_summary.png)
- [滑动窗口特征仪表板](anomalies/cmj_截割部_window_features.png)

### 采煤机 - 牵引部

- [Mahalanobis 时间线](anomalies/cmj_牵引部_mahalanobis_timeline.png)
- [Mahalanobis 特征贡献分解](anomalies/cmj_牵引部_feature_breakdown.png)
- [Isolation Forest vs Mahalanobis 对比](anomalies/cmj_牵引部_if_comparison.png)
- [归因总结](anomalies/cmj_牵引部_interpretation_summary.png)
- [滑动窗口特征仪表板](anomalies/cmj_牵引部_window_features.png)

### 采煤机 - 油泵

- [Mahalanobis 时间线](anomalies/cmj_油泵_mahalanobis_timeline.png)
- [Mahalanobis 特征贡献分解](anomalies/cmj_油泵_feature_breakdown.png)
- [Isolation Forest vs Mahalanobis 对比](anomalies/cmj_油泵_if_comparison.png)
- [归因总结](anomalies/cmj_油泵_interpretation_summary.png)
- [滑动窗口特征仪表板](anomalies/cmj_油泵_window_features.png)

### 采煤机 - 破碎机

- [Mahalanobis 时间线](anomalies/cmj_破碎机_mahalanobis_timeline.png)
- [Mahalanobis 特征贡献分解](anomalies/cmj_破碎机_feature_breakdown.png)
- [Isolation Forest vs Mahalanobis 对比](anomalies/cmj_破碎机_if_comparison.png)
- [归因总结](anomalies/cmj_破碎机_interpretation_summary.png)
- [滑动窗口特征仪表板](anomalies/cmj_破碎机_window_features.png)

### 转载机

- [Mahalanobis 时间线](anomalies/zzj_mahalanobis_timeline.png)
- [Mahalanobis 特征贡献分解](anomalies/zzj_feature_breakdown.png)
- [Isolation Forest vs Mahalanobis 对比](anomalies/zzj_if_comparison.png)
- [归因总结](anomalies/zzj_interpretation_summary.png)
- [滑动窗口特征仪表板](anomalies/zzj_window_features.png)

---
## 6. 关键发现

详细异常事件列表见 CSV 文件：

- `anomalies/cmj_截割部_merged_events.csv`
- `anomalies/cmj_牵引部_merged_events.csv`
- `anomalies/cmj_油泵_merged_events.csv`
- `anomalies/cmj_破碎机_merged_events.csv`
- `anomalies/zzj_merged_events.csv`

---
## 7. 下一步建议

1. 对持续异常时段进行根因追溯
2. 结合设备维修记录验证异常检测准确性
3. 建立在线 anomaly scoring 接口
