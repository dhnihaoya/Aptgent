# Aptgent 中文使用指南

Aptgent 是一个基于终端的适体（aptamer）设计工作流工具。它通过对话式界面引导你完成从自然语言输入到候选序列评分、特异性筛选、分子对接、空间排序和报告导出的全流程。

## 环境要求

- **操作系统**：Linux（推荐 Ubuntu 20.04+）
- **Conda**：Miniconda 或 Anaconda
- **GPU**（可选）：NVIDIA GPU + CUDA，用于加速预测器推理
- **网络**：需要访问智谱 GLM API（用于 LLM 功能）

## 安装步骤

### 1. 克隆仓库

```bash
git clone <仓库地址>
cd Aptgent
```

### 2. 创建 Conda 环境

```bash
cd aptgent
conda env create -f environment.yml
```

这一步会安装所有依赖，包括：

- Python 3.10
- ViennaRNA（RNA 二级结构预测）
- AutoDock Vina（分子对接）
- Open Babel（受体 PDBQT 准备）
- RDKit（分子处理）
- PyTorch、XGBoost、scikit-learn（预测器运行时）
- Textual（终端 UI 框架）
- 以及 `aptgent` 本身（可编辑安装模式）

### 3. 激活环境

```bash
conda activate aptgent
```

### 4. 配置 API Key

Aptgent 使用智谱 GLM 模型提供 LLM 能力。你需要设置 API Key：

```bash
export GLM_API_KEY="你的智谱API Key"
```

建议将这行加入 `~/.bashrc` 或 `~/.zshrc` 中，避免每次手动设置：

```bash
echo 'export GLM_API_KEY="你的智谱API Key"' >> ~/.bashrc
source ~/.bashrc
```

获取 API Key：访问 [智谱开放平台](https://open.bigmodel.cn/) 注册并创建 API Key。

### 5. 验证安装

```bash
aptgent doctor
```

这个命令会检查所有外部工具（RNAfold、Vina 等）和依赖是否就绪。全部显示 OK 即可开始使用。

## 启动

```bash
aptgent
```

或者：

```bash
python -m aptgent
```

启动后会进入终端对话界面，按提示操作即可。

## 使用流程

1. **新建或恢复**：启动后从欢迎界面新建一个 run，或恢复之前保存的 run。
2. **输入信息**：描述适体序列、靶标分子、类似物（可选）、修饰区域和时间预算。如果提供 PDB ID，会自动下载并分析结构。
3. **二级结构预测**：RNAfold 预测 RNA 二级结构。
4. **位点提议**：LLM 基于结构上下文提出 3 个备选突变位点方案（保守 → 激进 → LLM 自选），你选择一个或输入自定义位点。
5. **候选枚举**：对突变空间进行批量评分，筛选阳性候选。
6. **特异性筛选**：将候选与靶标类似物交叉比对，去除非特异性结合的候选。
7. **对接参数设置**：LLM 建议对接参数（数值经钳位校验后生效），你确认或修改。
8. **分子对接**：AutoDock Vina 执行对接计算（需要 Vina 已安装）。
9. **空间排序**：基于空间互作矩阵重新排序候选。
10. **最终报告**：导出 JSON 和 Markdown 格式的报告，完成工作流。

## 斜杠命令

在对话界面中可以使用以下命令：

- `/resume [run_id]`：恢复已保存的工作流
- `/quit`：退出确认
- `/theme`：切换终端主题
- `/cancel`：取消正在运行的后台任务
- `/export`：导出最终报告（在报告步骤可用）
- `/finish`：标记工作流完成（在报告步骤可用）

## 配置说明

配置文件位于 `aptgent/aptgent/config/`：

| 文件 | 用途 |
|------|------|
| `workflow.toml` | 工作流参数（枚举批量大小、对接超时等） |
| `tools.toml` | 外部工具路径（RNAfold、Vina 等） |
| `llm.toml` | LLM 模型配置（默认使用智谱 GLM） |

### 环境变量

| 变量 | 用途 |
|------|------|
| `GLM_API_KEY` | 智谱 API Key（必须设置） |
| `APTGENT_RNAFOLD` | RNAfold 可执行文件路径（默认从 PATH 查找） |
| `APTGENT_VINA` | Vina 可执行文件路径（默认从 PATH 查找） |
| `APTGENT_RUNS_DIR` | 运行数据存储目录（默认 `./runs`） |

## 运行数据

所有运行数据保存在 `runs/` 目录下（可通过 `APTGENT_RUNS_DIR` 修改）：

```text
runs/
  <run_id>/
    state.json              # 工作流状态
    run_card.json           # 完成后的可复现性记录
    artifacts/
      final_report.json     # 机器可读报告
      final_report.md       # Markdown 报告
      scored_candidates.jsonl
      specificity_results.jsonl
    docking/
      *.pdbqt               # 对接结果文件
    logs/
      workflow.jsonl         # 工作流日志
      llm_calls.jsonl        # LLM 调用日志
```

## 常见问题

**`aptgent doctor` 报 RNAfold 缺失**
→ 确认 conda 环境已激活，重新运行 `conda env update -f environment.yml`。

**`aptgent doctor` 报 Vina 缺失**
→ 同上。如果使用非 conda 安装的 Vina，设置 `APTGENT_VINA` 环境变量指向其路径。

**LLM 调用失败**
→ 检查 `GLM_API_KEY` 是否已设置，网络是否能访问 `open.bigmodel.cn`。

**运行数据找不到**
→ `runs_dir` 默认是相对路径，数据写在进程工作目录下的 `runs/`。如果在不同目录启动，之前的 run 可能不在当前目录。设置 `APTGENT_RUNS_DIR` 为绝对路径可以避免这个问题。

**更新已有环境**
→ `conda env update -f environment.yml`，然后 `pip install -e .` 确保最新代码生效。

## 开发

```bash
cd aptgent
conda activate aptgent
pytest                    # 运行全部测试
pytest tests/test_xxx.py  # 运行单个测试文件
```
