# results/

正式对照的精简结果放在这里，每个 run 一个子目录 `results/<run_id>/`，只放以下三个文件：

- `summary.json`：开发集指标、计数、Token、轨迹、代码版本
- `final_evaluation.json`：holdout 一次性评测结果
- `report.md`：人读报告

不要放模型文件或数据。PPT 和项目说明里的数字只能从这里取。正式矩阵只在一台机器上跑，并且基于 tag `benchmark-freeze` 的代码。
