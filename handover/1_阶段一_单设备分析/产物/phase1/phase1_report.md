# 阶段一：单设备分析报告（分部位工况）

> 生成时间：2026-08-04 19:28
> 数据：大海则煤矿 2024-04-01 ~ 2024-06-01（on-change 存储）

---
## 1. 采煤机分部位工况划分结果

### 1.1 设备级工况

- **割煤中**: 17885 min (45.6%)
- **待机**: 17032 min (43.5%)
- **正常运行**: 4170 min (10.6%)
- **空载牵引**: 97 min (0.2%)

### 1.2 截割部 工况

- **待机**: 11316 min (28.9%)
- **割煤中位**: 9738 min (24.9%)
- **割煤高位**: 7812 min (19.9%)
- **调架中**: 4170 min (10.6%)
- **待机-高位**: 2962 min (7.6%)
- **停机**: 2851 min (7.3%)
- **割煤低位**: 335 min (0.9%)

### 1.2 牵引部 工况

- **重载牵引**: 18501 min (47.2%)
- **停机**: 13140 min (33.5%)
- **待机**: 7096 min (18.1%)
- **空载牵引**: 447 min (1.1%)

### 1.2 油泵 工况

- **重载**: 22603 min (57.7%)
- **停机**: 10594 min (27.0%)
- **轻载**: 5987 min (15.3%)

### 1.2 破碎机 工况

- **停机**: 22106 min (56.4%)
- **空载运行**: 16966 min (43.3%)
- **带载运行**: 112 min (0.3%)

---
## 2. 转载机工况划分结果

- **带载运行**: 51717 min (59.2%)
- **停机**: 34682 min (39.7%)
- **空载运行**: 938 min (1.1%)

---
## 3. 各工况监测参数统计

详见 CSV 文件：
- `cmj_stats_by_截割部_工况.csv` — 采煤机 截割部_工况 分工况统计
- `cmj_stats_by_牵引部_工况.csv` — 采煤机 牵引部_工况 分工况统计
- `cmj_stats_by_油泵_工况.csv` — 采煤机 油泵_工况 分工况统计
- `cmj_stats_by_破碎机_工况.csv` — 采煤机 破碎机_工况 分工况统计
- `cmj_stats_by_设备_工况.csv` — 采煤机 设备_工况 分工况统计
- `zzj_stats_by_cond.csv` — 转载机分工况统计

---
## 4. 图表输出

- [cmj_device_condition_timeline.png](phase1\cmj_device_condition_timeline.png)
- [cmj_device_condition_pie.png](phase1\cmj_device_condition_pie.png)
- [cmj_截割部_timeline.png](phase1\cmj_截割部_timeline.png)
- [cmj_牵引部_timeline.png](phase1\cmj_牵引部_timeline.png)
- [cmj_油泵_timeline.png](phase1\cmj_油泵_timeline.png)
- [cmj_破碎机_timeline.png](phase1\cmj_破碎机_timeline.png)
- [cmj_截割部_cut_current_boxplot.png](phase1\cmj_截割部_cut_current_boxplot.png)
- [cmj_牵引部_traction_current_boxplot.png](phase1\cmj_牵引部_traction_current_boxplot.png)
- [cmj_油泵_pump_current_boxplot.png](phase1\cmj_油泵_pump_current_boxplot.png)
- [cmj_破碎机_crusher_current_boxplot.png](phase1\cmj_破碎机_crusher_current_boxplot.png)
- [cmj_corr_heatmap.png](phase1\cmj_corr_heatmap.png)
- [cmj_lagged_corr_电流_vs_温度.png](phase1\cmj_lagged_corr_电流_vs_温度.png)
- [cmj_lagged_corr_电流_vs_采煤机速度.png](phase1\cmj_lagged_corr_电流_vs_采煤机速度.png)
- [cmj_lagged_corr_俯仰角_vs_位置架号.png](phase1\cmj_lagged_corr_俯仰角_vs_位置架号.png)
- [cmj_lagged_corr_截割部.png](phase1\cmj_lagged_corr_截割部.png)
- [cmj_lagged_corr_牵引部.png](phase1\cmj_lagged_corr_牵引部.png)
- [cmj_lagged_corr_油泵.png](phase1\cmj_lagged_corr_油泵.png)
- [cmj_lagged_corr_破碎机.png](phase1\cmj_lagged_corr_破碎机.png)
- [cmj_all_params_by_device_profile.png](phase1\cmj_all_params_by_device_profile.png)
- [zzj_condition_timeline.png](phase1\zzj_condition_timeline.png)
- [zzj_condition_pie.png](phase1\zzj_condition_pie.png)
- [zzj_current_by_cond.png](phase1\zzj_current_by_cond.png)
- [zzj_corr_heatmap.png](phase1\zzj_corr_heatmap.png)
- [zzj_lagged_corr_电流_vs_转速.png](phase1\zzj_lagged_corr_电流_vs_转速.png)
- [transition_截割部_工况_电流.png](phase1\transition_截割部_工况_电流.png)
- [transition_牵引部_工况_电流.png](phase1\transition_牵引部_工况_电流.png)
- [transition_油泵_工况_电流.png](phase1\transition_油泵_工况_电流.png)
- [transition_破碎机_工况_电流.png](phase1\transition_破碎机_工况_电流.png)
- [transition_device_电流.png](phase1\transition_device_电流.png)
- [transition_device_采煤机速度.png](phase1\transition_device_采煤机速度.png)
- [transition_device_角度.png](phase1\transition_device_角度.png)
- [transition_profile_device_速度.png](phase1\transition_profile_device_速度.png)
- [transition_profile_device_电流.png](phase1\transition_profile_device_电流.png)
- [transition_profile_device_温度.png](phase1\transition_profile_device_温度.png)
- [transition_multi_param_电流速度_0.png](phase1\transition_multi_param_电流速度_0.png)
- [transition_multi_param_电流速度_1.png](phase1\transition_multi_param_电流速度_1.png)
- [transition_multi_param_电流速度_2.png](phase1\transition_multi_param_电流速度_2.png)
- [transition_multi_param_电流温度_0.png](phase1\transition_multi_param_电流温度_0.png)
- [transition_multi_param_电流温度_1.png](phase1\transition_multi_param_电流温度_1.png)
- [transition_multi_param_电流温度_2.png](phase1\transition_multi_param_电流温度_2.png)
- [transition_multi_param_全关键参数_0.png](phase1\transition_multi_param_全关键参数_0.png)
- [transition_multi_param_全关键参数_1.png](phase1\transition_multi_param_全关键参数_1.png)
- [transition_multi_param_全关键参数_2.png](phase1\transition_multi_param_全关键参数_2.png)
- [cluster_vs_截割部.png](phase1\cluster_vs_截割部.png)
- [cluster_vs_牵引部.png](phase1\cluster_vs_牵引部.png)
- [cluster_vs_油泵.png](phase1\cluster_vs_油泵.png)
- [cluster_vs_破碎机.png](phase1\cluster_vs_破碎机.png)
- [transition_工况_current.png](phase1\transition_工况_current.png)
- [cluster_vs_转载机.png](phase1\cluster_vs_转载机.png)

---
## 5. 数据空洞分析

基于 on-change 存储特性，对重采样后连续相同值游程 ≥120min 的参数进行检测。
详见 `gap_detection.png`（热力图）和 `gap_report.csv`。

---
## 6. 参数层级图谱

按 `设备_部位_组件_传感器_指标` 命名规则解析测点层级关系。

---
## 7. 工况转换分析

分部位检测工况切换事件（截割部/牵引部/油泵/破碎机各自独立），
详见各 `transition_*_stats.csv` 和转换时序图。

---
## 8. 聚类验证规则工况

以关键监测参数为特征，KMeans 聚类后与规则标签对比，
ARI 反映规则划分的合理性。

---
## 9. 显著性检验 (Kruskal-Wallis)

对 4 个部位做分部位 Kruskal-Wallis 检验 + FDR 校正 + epsilon² 效应量。

---
## 10. 关键发现

### 采煤机

- **设备级工况占比**反映设备利用率
- **截割部**: 割煤中电流显著高于调架中
- **牵引部**: 牵引中电流变化与负载相关
- 滞后互相关揭示电流与温度、速度的延时耦合关系

### 转载机

- **带载运行** 占比反映转载机实际输送负荷率
- 电流-转矩-转速 三者联动关系有助于判断传动链健康状态

---
## 11. 下一步（阶段二）

1. 分工况建立 3σ / IQR 基线
2. 提取时域特征：RMS、斜率、启停次数
3. 滑动窗口 + 马氏距离多维异常检测
