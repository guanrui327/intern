# 成果交接包 README — 煤矿设备数据分析（2026 暑期实习）

煤矿设备（采煤机 CMJ + 转载机 ZZJ）数据分析建模完整项目快照：**预处理 → 工况划分 → 单设备异常检测 → 多设备关联异常检测**。
源码 + 产物 + 报告都在包内，每个阶段可独立重跑。整理日期 2026-08-19，包大小 ≈ 244 MB（不含原始数据）。

---

## 1. 怎么用

### 1.1 装依赖

```bash
pip install -r requirements.txt
# 如需重新生成 docx 报告，再加：
pip install python-docx
```

### 1.2 放数据（只读产物可跳过）

原始 CSV 不在包内。要重跑，先把数据按下面结构放回（**目录名含中文全角括号，别改**）：

```
<阶段>/脚本/
└── data/
    ├── cmj-20240401-20240601（采煤机）/cmj-20240401-20240601.csv
    └── zzj-20240401-20240601（转载机）/zzj-20240401-20240601.csv
```

字段含义见 `0_预处理/产物/data_dict.txt` 和 `4_报告/report/大海则数据解释.xls`。

### 1.3 跑脚本

依赖链：**预处理 → 阶段一 → 阶段二 → 阶段三**。重跑输出写到各 `脚本/output/`，与包内 `产物/` 互不干扰。

```bash
# 阶段 0：重采样 + 数据概览
cd 0_预处理/脚本
python run_resample.py      # 生成 1min 宽表 → output/processed/
python run_eda.py           # 数据概览 → output/eda_overview.md, eda_summary.json

# 阶段一：工况划分 + 分工况统计
cd ../../1_阶段一_单设备分析/脚本
python run_phase1.py        # → output/phase1/

# 阶段二：异常检测 + 逐事件可视化
cd ../../2_阶段二_单设备异常检测/脚本
python run_phase2.py        # 检测主流程 → output/phase2/
python run_event_viz.py     # 每部位 Top10 异常事件窗口图

# 阶段三：多设备关联（需要阶段二产物）
cd ../../3_阶段三_多设备关联异常检测/脚本
python run_phase3.py        # → output/phase3/data/
python run_phase3_viz.py    # 可视化
```

---

## 2. 目录结构

```
handover/
├── README.md              本说明
├── requirements.txt       Python 依赖
├── 0_预处理/              原始 CSV → 1min 宽表
├── 1_阶段一_单设备分析/    工况划分 + 分工况统计
├── 2_阶段二_单设备异常检测/ 异常检测 + 事件归因
├── 3_阶段三_多设备关联异常检测/ 跨设备关联检测
└── 4_报告/                周报 / 任务书 / 反馈 / 转换脚本
```

每个阶段 = `脚本/`（入口 run_*.py + src 模块，可独立运行）+ `产物/`（图、表、报告）。

---

## 3. 0_预处理

| 文件 | 作用 |
|---|---|
| `脚本/run_resample.py` | 把原始 on-change CSV 重采样成 1 分钟等间隔宽表（后续所有阶段的输入） |
| `脚本/run_eda.py` | 数据概览：缺失率、采样频率、异常值统计 |
| `脚本/src/preprocess.py` | CSV 读取、清洗、on-change → 宽表 → 1min 重采样 |
| `脚本/src/eda.py` | 概览统计逻辑 |
| `产物/processed/` | 两张宽表：`cmj_wide_1min.parquet`、`zzj_wide_1min.parquet` |
| `产物/eda_overview.md` `eda_summary.json` | 数据质量概览 |
| `产物/data_dict.txt` `point_inventory.txt` | 数据字典（字段含义）、全部测点清单 |

## 4. 1_阶段一_单设备分析

| 文件 | 作用 |
|---|---|
| `脚本/run_phase1.py` | 阶段一全流程入口 |
| `脚本/src/condition.py` | 分部位工况划分规则（截割部 7 态、牵引/油泵/破碎机/ZZJ 各自工况） |
| `脚本/src/significance.py` | Kruskal-Wallis 显著性检验 + BH 校正（哪些状态量影响哪些参数） |
| `脚本/src/transition.py` | 工况转换时序分析 |
| `脚本/src/segment_stats.py` | 状态段统计（每个工况段的时长/次数） |
| `脚本/src/cluster_validate.py` | KMeans vs 规则聚类对比（ARI），验证工况划分合理性 |
| `脚本/src/param_map.py` | 参数层级图谱 |
| `脚本/src/visualize.py` | 绘图函数 |
| `脚本/src/generate_report_docx.py` | 生成阶段一 docx 报告 |

`产物/phase1/`（147 文件，按文件名规律分组）：

| 文件 | 作用 |
|---|---|
| `cmj_*_timeline.png` `*_condition_*.png` `*_pie.png` | 工况时间条 / 占比饼图 |
| `cmj_*_boxplot.png` | 各部位关键参数分工况箱线图 |
| `*_stats_by_*.csv/png` | 分工况统计表（均值/分位数）与图 |
| `cmj_corr_heatmap.png` `cmj_lagged_corr_*.png` | 参数相关性与滞后互相关图 |
| `kruskal_*.csv/png` | 显著性检验结果表 + 热力图 |
| `feature_importance_*.csv/png` | 状态量对参数的影响强度 |
| `cluster_vs_*.png` `cluster_disagreement_*.csv` | 聚类对比图 + 分歧明细 |
| `transition_*.png/csv` | 工况转换图 / 转换率表 |
| `segment_duration_*.png` `segment_stats_*.csv` | 状态段时长分布 / 段统计 |
| `gap_detection.png` `gap_report.csv` | 数据缺口检测 |
| `anomalous_segments_*.png/csv` | 异常工况段标注 |
| `outlier_report.csv` | 离群值汇总 |
| `param_hierarchy*.png/csv` | 参数层级图谱 |
| `cmj_with_condition.parquet` `zzj_with_condition.parquet` | 带工况列的分设备宽表 |
| `phase1_report.md` `phase1_technical_report.md` | 阶段一分析报告（文字版） |
| `阶段一_单设备分析报告_v2.docx` 及 `阶段一_单设备分析报告_v2/` | 正式 docx 报告 + 周报合集（管睿_第X周报告.docx、工作复盘.docx 等） |

## 5. 2_阶段二_单设备异常检测

| 文件 | 作用 |
|---|---|
| `脚本/run_phase2.py` | 异常检测主流程（分工况基线 → 多变量/单变量/残差检测 → 事件归因） |
| `脚本/run_event_viz.py` | 每个部位 Top10 代表异常事件的窗口图 |
| `脚本/run_compare_freq.py` | 频域特征工况区分度分析（仅分析用，检测集成已关闭） |
| `脚本/src/feature_extract.py` | 滑动窗口特征提取（5min 窗口 / 1min 步长） |
| `脚本/src/anomaly_mv.py` | 多变量检测：PCA 降维 + 马氏距离 + Isolation Forest |
| `脚本/src/anomaly_report.py` | 异常汇总与归因 |
| `脚本/src/anomaly_viz.py` | 异常图（时间线、打分分布） |
| `脚本/src/anomaly_event_viz.py` | 单事件窗口图绘制 |
| `脚本/src/analyze_freq_by_condition.py` | 频域特征分工况区分度 |
| `脚本/src/generate_tech_report.py` 等 4 个 generate_* | 各报告 docx 生成 |

`产物/phase2/`（195 文件）：

| 子目录 | 内容 |
|---|---|
| `anomalies/` | 检测打分与图：`*_mahalanobis.csv` 马氏打分、`*_iforest.csv`、`*_pca_*.csv` 降维、`*_transition_rate_*.csv` 工况转换率、特征归因图 |
| `anomaly_events/` | 每部位 **Top10 事件窗口图** + `*_events.csv` 事件表（含归因摘要）+ `anomaly_events_summary.md` 事件汇总 |
| `cause_analysis/` | 根因分析：fig1–fig7 根因图、`cause_summary.json` 根因汇总、`*_attribution.csv` 归因表 |
| `event_analysis/` | 逐事件归因明细：`event_cause_detail.csv`（每条事件归因）、`events_cause_label.csv`（事件标签）、`representative_events.csv`（代表事件）+ `viz/` 图 |
| `freq_analysis/` | 频域特征工况区分度（KW 检验、判别力、PCA 散点） |
| `profiles/` | 分工况基线表（异常检测的基准） |
| 根目录 | 5 份报告：`phase2_tech_report.docx`、`phase2_report.docx/.md`、`optimization_report.docx`、`phase2_comparison_report.docx`、`金天反馈新增功能报告.docx` |

## 6. 3_阶段三_多设备关联异常检测

| 文件 | 作用 |
|---|---|
| `脚本/run_phase3.py` | 多设备关联 pipeline |
| `脚本/run_phase3_viz.py` | 关联分析可视化 |
| `脚本/src/relation_data.py` | CMJ/ZZJ 时间对齐 + 联合工况 |
| `脚本/src/relation_model.py` | 跨设备物理耦合（上游产量 → 下游负载回归） |
| `脚本/src/relation_event.py` | 事件传导链（异常事件的跨设备滞后匹配） |
| `脚本/src/relation_viz.py` | 绘图 |
| `脚本/src/generate_phase3_tech_report.py` | 阶段三报告生成 |

`产物/`：

| 文件 | 作用 |
|---|---|
| `phase3/data/joint_mahalanobis.csv` | 逐分钟跨设备异常打分 |
| `phase3/data/rule_events.csv` | 规则检测事件（1655 条） |
| `phase3/data/propagation_chains.csv` | 跨设备事件传导链 |
| `phase3/data/system_table.parquet` | 联合分钟表 |
| `phase3/data/zzj_bus_0415.parquet` | 04-15 母线电压秒级数据（案例用） |
| `phase3/phase3_tech_report.docx` | 阶段三技术报告 |
| `阶段三_深度核查/` | 04-15 转载机错配案例：7 张核查图 + 深度核查报告 md/docx |

> 注：`phase3/figures/`、`phase3/reports/` 为空目录，相关图与报告已并入 `阶段三_深度核查/`。

## 7. 4_报告

`report/` 原样拷贝，含：

| 文件 | 作用 |
|---|---|
| `煤矿设备数据分析-2026暑期实习任务书.docx` | 任务书 |
| `大海则数据解释.xls` | 数据字段说明 |
| `工作总结.docx/.md` | 实习工作总结 |
| `阶段二_异常事件逐事件分析.docx/.md` | 阶段二事件分析报告 |
| `阶段二_异常检测结果可视化与原因分析复盘.docx/.md` | 阶段二复盘报告 |
| `阶段三_周报.docx/.md` + `阶段三/` | 阶段三周报 + 深度核查（7 图 + 报告） |
| `吴昊天_阶段一第一周汇报.pptx` | 阶段一汇报 PPT |
| `feedback.txt` | 反馈记录 |
| `md2docx_0415_mismatch.py` 等 3 个 | md → docx 转换脚本（改报告改 md，跑脚本转 docx） |

---

## 8. 注意事项

- 每个阶段 `脚本/src/` 是**同一份 28 模块副本**，保证该阶段独立可跑；改了 src 要同步各阶段副本。
- 配置集中在 `src/config.py`（测点、工况阈值、路径），改阈值只动它。
- 阶段二/三的产物与报告文件是当时跑出的快照，重跑若参数变了，产物会更新到 `脚本/output/`。
