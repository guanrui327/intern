# 具体异常事件可视化汇总

覆盖当前 phase2 pipeline 的 5 组产物。事件 = 连续 any_anomaly 时间戳分组（相邻间隔 > 1min 断开）。


## cmj_截割部

- 事件总数: **2987**，代表事件图: 10（Top-10）

- 监测参数 14 个，工况列 `截割部_工况`

| 事件ID | 开始 | 结束 | 时长min | 工况 | 方法集 | 严重度 | 归因摘要 |
|---|---|---|---|---|---|---|---|
| 1652 | 04-15 15:03 | 04-17 12:00 | 2698.0 | 待机 | IsolationForest; Mahalanobis; 单变量IQR+3σ; 残差 | 49972.501 | Mahalanobis 距离=49972.5（阈值=18.5）。主要贡献特征：P |
| 1651 | 04-14 12:53 | 04-15 10:05 | 1273.0 | 待机 | IsolationForest; Mahalanobis; 单变量IQR+3σ; 残差 | 8991.736 | Mahalanobis 距离=8991.7（阈值=18.5）。主要贡献特征：PC |
| 1150 | 04-10 04:32 | 04-10 12:32 | 481.0 | 待机 | IsolationForest; Mahalanobis; 单变量IQR+3σ; 残差 | 72482.914 | Mahalanobis 距离=72482.9（阈值=18.5）。主要贡献特征：P |
| 2388 | 04-23 09:10 | 04-23 15:59 | 410.0 | 待机 | IsolationForest; Mahalanobis; 单变量IQR+3σ; 残差 | 46790.661 | Mahalanobis 距离=46790.7（阈值=18.5）。主要贡献特征：P |
| 1653 | 04-17 13:05 | 04-17 15:24 | 140.0 | 待机 | IsolationForest; Mahalanobis; 单变量IQR+3σ; 残差 | 37058.689 | Mahalanobis 距离=37058.7（阈值=18.5）。主要贡献特征：P |
| 1690 | 04-17 22:29 | 04-17 23:29 | 61.0 | 待机 | IsolationForest; Mahalanobis; 单变量IQR+3σ; 残差 | 1509.194 | Mahalanobis 距离=1509.2（阈值=18.5）。主要贡献特征：PC |
| 1559 | 04-13 21:09 | 04-13 22:02 | 54.0 | 待机-高位 | IsolationForest; Mahalanobis; 单变量IQR+3σ; 残差 | 1207.731 | Mahalanobis 距离=1207.7（阈值=18.5）。主要贡献特征：PC |
| 1013 | 04-08 17:15 | 04-08 17:59 | 45.0 | 待机 | IsolationForest; Mahalanobis; 单变量IQR+3σ; 残差 | 4841.278 | Mahalanobis 距离=4841.3（阈值=18.5）。主要贡献特征：PC |
| 40 | 04-01 08:29 | 04-01 09:04 | 36.0 | 待机 | IsolationForest; Mahalanobis; 单变量IQR+3σ; 残差 | 2781.712 | Mahalanobis 距离=2781.7（阈值=18.5）。主要贡献特征：PC |
| 2024 | 04-20 18:32 | 04-20 19:04 | 33.0 | 待机 | IsolationForest; Mahalanobis; 单变量IQR+3σ; 残差 | 3112.82 | Mahalanobis 距离=3112.8（阈值=18.5）。主要贡献特征：PC |

## cmj_牵引部

- 事件总数: **3112**，代表事件图: 10（Top-10）

- 监测参数 18 个，工况列 `牵引部_工况`

| 事件ID | 开始 | 结束 | 时长min | 工况 | 方法集 | 严重度 | 归因摘要 |
|---|---|---|---|---|---|---|---|
| 1751 | 04-14 12:42 | 04-17 16:03 | 4522.0 | 待机 | IsolationForest; Mahalanobis; 单变量IQR+3σ; 残差 | 49986.438 | Mahalanobis 距离=49986.4（阈值=18.5）。主要贡献特征：P |
| 1223 | 04-10 04:30 | 04-10 12:40 | 491.0 | 待机 | IsolationForest; Mahalanobis; 单变量IQR+3σ; 残差 | 72040.858 | Mahalanobis 距离=72040.9（阈值=18.5）。主要贡献特征：P |
| 2496 | 04-23 09:10 | 04-23 15:59 | 410.0 | 待机 | IsolationForest; Mahalanobis; 单变量IQR+3σ; 残差 | 48692.489 | Mahalanobis 距离=48692.5（阈值=18.5）。主要贡献特征：P |
| 1116 | 04-08 20:10 | 04-08 23:26 | 197.0 | 停机 | IsolationForest; Mahalanobis; 单变量IQR+3σ; 残差 | 2176.748 | Mahalanobis 距离=2176.7（阈值=18.5）。主要贡献特征：PC |
| 1987 | 04-19 13:16 | 04-19 16:01 | 166.0 | 待机 | IsolationForest; Mahalanobis; 单变量IQR+3σ; 残差 | 4245.47 | Mahalanobis 距离=4245.5（阈值=18.5）。主要贡献特征：PC |
| 441 | 04-04 02:01 | 04-04 03:42 | 102.0 | 待机 | IsolationForest; Mahalanobis; 单变量IQR+3σ; 残差 | 4903.46 | Mahalanobis 距离=4903.5（阈值=18.5）。主要贡献特征：PC |
| 2394 | 04-22 12:28 | 04-22 14:34 | 127.0 | 停机 | IsolationForest; Mahalanobis; 单变量IQR+3σ; 残差 | 573.188 | Mahalanobis 距离=573.2（阈值=18.5）。主要贡献特征：PC1 |
| 1172 | 04-09 11:57 | 04-09 13:33 | 97.0 | 待机 | IsolationForest; Mahalanobis; 单变量IQR+3σ; 残差 | 3316.523 | Mahalanobis 距离=3316.5（阈值=18.5）。主要贡献特征：PC |
| 37 | 04-01 12:00 | 04-01 13:42 | 103.0 | 停机 | IsolationForest; Mahalanobis; 单变量IQR+3σ; 残差 | 583.169 | Mahalanobis 距离=583.2（阈值=18.5）。主要贡献特征：PC3 |
| 1664 | 04-13 19:04 | 04-13 20:31 | 88.0 | 停机 | IsolationForest; Mahalanobis; 单变量IQR+3σ; 残差 | 1613.075 | Mahalanobis 距离=1613.1（阈值=18.5）。主要贡献特征：PC |

## cmj_油泵

- 事件总数: **2491**，代表事件图: 10（Top-10）

- 监测参数 16 个，工况列 `油泵_工况`

| 事件ID | 开始 | 结束 | 时长min | 工况 | 方法集 | 严重度 | 归因摘要 |
|---|---|---|---|---|---|---|---|
| 1387 | 04-14 12:42 | 04-17 16:02 | 4521.0 | 轻载 | IsolationForest; Mahalanobis; 单变量IQR+3σ; 残差 | 50991.421 | Mahalanobis 距离=50991.4（阈值=18.5）。主要贡献特征：P |
| 987 | 04-10 04:30 | 04-10 12:32 | 483.0 | 轻载 | IsolationForest; Mahalanobis; 单变量IQR+3σ; 残差 | 74089.398 | Mahalanobis 距离=74089.4（阈值=18.5）。主要贡献特征：P |
| 2006 | 04-23 09:10 | 04-23 15:59 | 410.0 | 轻载 | IsolationForest; Mahalanobis; 单变量IQR+3σ; 残差 | 48067.111 | Mahalanobis 距离=48067.1（阈值=18.5）。主要贡献特征：P |
| 899 | 04-08 20:10 | 04-08 23:36 | 207.0 | 停机 | IsolationForest; Mahalanobis; 单变量IQR+3σ; 残差 | 2761.503 | Mahalanobis 距离=2761.5（阈值=18.5）。主要贡献特征：PC |
| 1583 | 04-19 13:18 | 04-19 16:10 | 173.0 | 轻载 | IsolationForest; Mahalanobis; 单变量IQR+3σ; 残差 | 12720.642 | Mahalanobis 距离=12720.6（阈值=18.5）。主要贡献特征：P |
| 164 | 04-02 13:36 | 04-02 16:04 | 149.0 | 停机 | IsolationForest; Mahalanobis; 单变量IQR+3σ; 残差 | 32756.938 | Mahalanobis 距离=32756.9（阈值=18.5）。主要贡献特征：P |
| 1671 | 04-20 10:26 | 04-20 13:51 | 206.0 | 停机 | IsolationForest; Mahalanobis; 单变量IQR+3σ; 残差 | 1271.504 | Mahalanobis 距离=1271.5（阈值=18.5）。主要贡献特征：PC |
| 31 | 04-01 12:00 | 04-01 13:41 | 102.0 | 停机 | IsolationForest; Mahalanobis; 单变量IQR+3σ; 残差 | 10740.909 | Mahalanobis 距离=10740.9（阈值=18.5）。主要贡献特征：P |
| 347 | 04-04 02:01 | 04-04 03:42 | 102.0 | 停机 | IsolationForest; Mahalanobis; 单变量IQR+3σ; 残差 | 10429.457 | Mahalanobis 距离=10429.5（阈值=18.5）。主要贡献特征：P |
| 885 | 04-08 16:46 | 04-08 18:03 | 78.0 | 轻载 | IsolationForest; Mahalanobis; 单变量IQR+3σ; 残差 | 49758.997 | Mahalanobis 距离=49759.0（阈值=18.5）。主要贡献特征：P |

## cmj_破碎机

- 事件总数: **2473**，代表事件图: 10（Top-10）

- 监测参数 14 个，工况列 `破碎机_工况`

| 事件ID | 开始 | 结束 | 时长min | 工况 | 方法集 | 严重度 | 归因摘要 |
|---|---|---|---|---|---|---|---|
| 1416 | 04-14 12:42 | 04-17 16:01 | 4520.0 | 空载运行 | IsolationForest; Mahalanobis; 单变量IQR+3σ; 残差 | 87.225 | Mahalanobis 距离=87.2（阈值=18.5）。主要贡献特征：PC1  |
| 1004 | 04-10 04:30 | 04-10 12:32 | 483.0 | 停机 | IsolationForest; Mahalanobis; 单变量IQR+3σ; 残差 | 132.914 | Mahalanobis 距离=132.9（阈值=18.5）。主要贡献特征：PC2 |
| 1217 | 04-12 12:55 | 04-12 16:51 | 237.0 | 停机 | IsolationForest; Mahalanobis; 单变量IQR+3σ; 残差 | 12.958 | 残差异常：采煤机_油泵_左电机_温度 偏高（残差 Z-score=13.0，实际 |
| 1593 | 04-19 13:27 | 04-19 16:00 | 154.0 | 空载运行 | IsolationForest; Mahalanobis; 单变量IQR+3σ; 残差 | 17.155 | 残差异常：采煤机_油泵_右电机_温度 偏高（残差 Z-score=17.2，实际 |
| 39 | 04-01 12:00 | 04-01 13:42 | 103.0 | 停机 | IsolationForest; Mahalanobis; 单变量IQR+3σ; 残差 | 59.242 | Mahalanobis 距离=59.2（阈值=18.5）。主要贡献特征：PC4  |
| 1884 | 04-22 12:28 | 04-22 14:30 | 123.0 | 停机 | IsolationForest; Mahalanobis; 单变量IQR+3σ; 残差 | 15.364 | 残差异常：采煤机_油泵_右电机_温度 偏高（残差 Z-score=15.4，实际 |
| 1224 | 04-12 17:49 | 04-12 19:08 | 80.0 | 停机 | IsolationForest; Mahalanobis; 单变量IQR+3σ; 残差 | 60.287 | Mahalanobis 距离=60.3（阈值=18.5）。主要贡献特征：PC2  |
| 645 | 04-06 09:57 | 04-06 11:33 | 97.0 | 停机 | IsolationForest; Mahalanobis; 单变量IQR+3σ; 残差 | 6.441 | 正常 |
| 1005 | 04-10 12:47 | 04-10 13:56 | 70.0 | 停机 | IsolationForest; Mahalanobis; 单变量IQR+3σ; 残差 | 14.62 | 残差异常：采煤机_油泵_左电机_温度 偏高（残差 Z-score=14.6，实际 |
| 2391 | 04-27 14:47 | 04-27 15:50 | 64.0 | 停机 | IsolationForest; Mahalanobis; 单变量IQR+3σ; 残差 | 13.36 | 残差异常：采煤机_油泵_右电机_温度 偏高（残差 Z-score=13.4，实际 |

## zzj

- 事件总数: **2024**，代表事件图: 10（Top-10）

- 监测参数 13 个，工况列 `工况`

| 事件ID | 开始 | 结束 | 时长min | 工况 | 方法集 | 严重度 | 归因摘要 |
|---|---|---|---|---|---|---|---|
| 1621 | 05-17 19:48 | 05-20 23:13 | 4526.0 | 停机 | IsolationForest; Mahalanobis; 单变量IQR+3σ; 残差 | 7899.044 | Mahalanobis 距离=7899.0（阈值=10.8）。主要贡献特征：PC |
| 267 | 04-07 02:56 | 04-07 09:19 | 384.0 | 停机 | IsolationForest; Mahalanobis; 单变量IQR+3σ; 残差 | 8031.091 | Mahalanobis 距离=8031.1（阈值=10.8）。主要贡献特征：PC |
| 1140 | 05-02 17:34 | 05-02 23:47 | 374.0 | 停机 | IsolationForest; Mahalanobis; 单变量IQR+3σ; 残差 | 4100.597 | Mahalanobis 距离=4100.6（阈值=10.8）。主要贡献特征：PC |
| 1485 | 05-12 23:44 | 05-13 05:32 | 349.0 | 停机 | IsolationForest; Mahalanobis; 单变量IQR+3σ; 残差 | 7046.265 | Mahalanobis 距离=7046.3（阈值=10.8）。主要贡献特征：PC |
| 1400 | 05-10 23:51 | 05-11 05:32 | 342.0 | 停机 | IsolationForest; Mahalanobis; 单变量IQR+3σ; 残差 | 8059.795 | Mahalanobis 距离=8059.8（阈值=10.8）。主要贡献特征：PC |
| 1006 | 04-28 18:39 | 04-28 23:48 | 310.0 | 停机 | IsolationForest; Mahalanobis; 单变量IQR+3σ; 残差 | 9400.557 | Mahalanobis 距离=9400.6（阈值=10.8）。主要贡献特征：PC |
| 923 | 04-26 00:12 | 04-26 04:58 | 287.0 | 停机 | IsolationForest; Mahalanobis; 单变量IQR+3σ; 残差 | 7367.402 | Mahalanobis 距离=7367.4（阈值=10.8）。主要贡献特征：PC |
| 1550 | 05-15 04:07 | 05-15 08:26 | 260.0 | 停机 | IsolationForest; Mahalanobis; 单变量IQR+3σ; 残差 | 7037.865 | Mahalanobis 距离=7037.9（阈值=10.8）。主要贡献特征：PC |
| 1572 | 05-16 09:32 | 05-16 15:01 | 330.0 | 停机 | IsolationForest; Mahalanobis; 单变量IQR+3σ; 残差 | 1071.614 | Mahalanobis 距离=1071.6（阈值=10.8）。主要贡献特征：PC |
| 1901 | 05-27 21:07 | 05-28 00:56 | 230.0 | 停机 | IsolationForest; Mahalanobis; 单变量IQR+3σ; 残差 | 6712.877 | Mahalanobis 距离=6712.9（阈值=10.8）。主要贡献特征：PC |