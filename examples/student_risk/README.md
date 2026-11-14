# 演示数据：学生期末不及格预警

给对话式研究页做现场上传演示，也给协议 Agent（A）做打分题。负责人：C。

| 文件 | 内容 |
|---|---|
| `student_risk.csv` | 649 名学生，34 列（33 个原始字段 + 目标列 `final_result`），其中 100 人 `fail` |
| `card.yaml` | 标准答案：人确认后的协议（场景卡格式），可以直接传给 `register_csv_task` |
| `build_demo_csv.py` | 从 UCI 下载原始文件、校验哈希、重新生成 CSV |

来源：UCI Machine Learning Repository，[Student Performance](https://archive.ics.uci.edu/dataset/320/student+performance)（Cortez & Silva, 2008），`student-por.csv`（葡萄牙语课程），许可 CC BY 4.0。目标列 `final_result` 由期末成绩 G3 生成：G3 < 10（满分 20）为 `fail`，否则为 `pass`。CSV 里**有意保留了 G1、G2、G3**，因为学校导出的成绩表里通常就带着这些列。哪些字段不能用，正是要靠协议步骤来判断的。

## 在对话里怎么说

> 这是两所中学葡语课程的学生数据。我想在学年开始时找出期末可能不及格的学生，好提前安排辅导。

英文版（给 LLM 测试用）：*At the start of the school year, find the students likely to fail the Portuguese course so that tutoring can be arranged early.*

## 标准答案：哪些字段不能用

预测时点是**学年开始、这门课还没有任何阶段成绩的时候**。

| 字段 | 结论 | 理由 | 打分时的分量 |
|---|---|---|---|
| `G3` | 不能用（post_outcome） | 就是期末成绩本身，目标列由它生成 | 必须排除 |
| `G1` | 不能用（post_outcome） | 第一阶段成绩，学年中才产生 | 必须排除 |
| `G2` | 不能用（post_outcome） | 第二阶段成绩，学年中才产生 | 必须排除 |
| `absences` | 不能用（post_outcome） | 统计的是本学年的缺勤次数，学年初还不知道 | 边界情况：原始说明没写是哪一年，排除了算加分，没排除不算错 |
| 其余 29 个字段 | 可以用 | 家庭背景、学习时间、过去不及格次数等，学年初都已知 | 误排除记为"多排除" |

建议 A 的协议 Agent 这样打分：
- **必须排除的 3 个字段的召回率**（G1、G2、G3）：这是主要指标；
- 多排除的数量：把可用字段误判为不可用；
- `absences` 有没有排除：单独报告；
- 是否在 `questions_for_user` 里提出了"缺勤是哪一年的"这类问题：如果提了，说明 Agent 注意到了这个歧义，是加分项。

## 实测：协议错了，分数会有多"好看"

BudgetLab 完整版，脚本化提案（不是 LLM），各跑 1 次，holdout 是 130 名学生（20%）：

| 协议 | 基线（开发集） | 交付（开发集） | holdout（95% 区间） | 用时 |
|---|---|---|---|---|
| ✅ 按标准答案（排除 G1、G2、G3、absences） | 0.642 | 0.722（确认通过） | **0.649**（0.551–0.745） | 24 s |
| ❌ 只排除 G3（G1、G2、absences 可用） | 0.839 | 0.839（没有候选通过确认） | 0.890（0.800–0.961） | 22 s |
| ❌ 所有字段都可用 | 0.921 | 1.000（确认通过） | 1.000（1.000–1.000） | 21 s |

- 分数越高，越说明用到了预测时拿不到的信息：这就是"任务理解"为什么必须放在研究之前、并且由人最终确认。
- 正确协议下开发集 0.722 和 holdout 0.649 的差距比较大，但 holdout 只有 130 人、其中约 20 人不及格，区间很宽（0.551–0.745），不能据此判断过拟合。
- 每次运行只要 20 多秒，适合现场演示。

## 用法

**网页**：上传 `student_risk.csv`，粘贴上面那句话；协议卡片出来后，和本页的标准答案对比，确认后开跑。

**代码**（无 LLM 兜底路径，可以直接使用标准答案）：

```python
import yaml
from pathlib import Path
from budgetlab.tasks.csv_task import register_csv_task, config_for_upload
from budgetlab.data import prepare_task
from budgetlab.controller import run_research

card = yaml.safe_load(Path("examples/student_risk/card.yaml").read_text())
task_id = register_csv_task(Path("examples/student_risk/student_risk.csv"), card, Path("data"))
prepare_task(task_id, Path("data"))
config = config_for_upload(task_id, yaml.safe_load(Path("configs/bank_marketing.yaml").read_text()))
summary = run_research(config, "budgetlab", Path("runs"), Path("data"))
```
