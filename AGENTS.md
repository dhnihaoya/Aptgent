# AGENTS.md

本文件面向在本仓库中工作的 AI coding agent。目标是帮助你基于当前代码快速定位入口、理解边界、避免修改错误层级，并识别当前仓库里已经存在的环境与安全风险。

## 1. 仓库概览

本仓库包含两个相关但独立的 Python 项目：

- `aptgent/`：主项目，一个基于 Textual 的 TUI（终端界面）工作流应用。
- `aptamer_predictor/`：独立 CLI 工具，提供适配体-小分子结合预测能力，由 `aptgent` 通过子进程调用。

`aptgent` 的主流程是一个状态驱动的多步骤工作流，LLM 只用于自然语言解析、解释和建议，不应成为确定性评分、排序或状态流转的事实来源。

## 2. 快速定位

开始工作前，优先查看这些位置：

- `aptgent/aptgent/tui/app.py`：应用入口、配置加载、adapter 装配、注册的 screen。
- `aptgent/aptgent/tui/screens/chat.py`：当前真实主界面，整个流程都在这个 chat screen 内推进。
- `aptgent/aptgent/tui/widgets/step_handlers.py`：各 workflow step 的主要行为实现。
- `aptgent/aptgent/workflow/`：状态机、持久化、运行状态模型。
- `aptgent/aptgent/adapters/`：外部工具与外部能力边界。
- `aptgent/tests/`：现有 pytest 测试。

## 3. 当前真实入口与主路径

### 应用入口

- 包入口：`aptgent`
- 模块入口：`python -m aptgent`
- 入口函数：`aptgent/aptgent/tui/app.py` 中的 `run()`

### 当前真实 UI 路径

`AptgentApp` 当前只注册两个 screen：

- `welcome`
- `chat`

主工作流由 `ChatScreen` 驱动，并通过 `step_handlers.py` 中的 `StepHandler` 子类完成每一步。
旧的分步 screen 已清理。排查或修改主流程时，应直接沿 `ChatScreen` 和 `step_handlers.py` 这条路径工作。

## 4. 架构边界

### TUI 层

负责用户交互、展示、输入收集和 step 触发：

- `aptgent/aptgent/tui/screens/`
- `aptgent/aptgent/tui/widgets/`

### Workflow 层

负责状态流转、暂停/恢复、完成/失败和持久化：

- `aptgent/aptgent/workflow/engine.py`
- `aptgent/aptgent/workflow/persistence.py`
- `aptgent/aptgent/workflow/state.py`

`workflow/engine.py` 中的 `TRANSITIONS` 是当前流程图的真实来源。改流程顺序时先改这里，再检查对应 handler 和测试。

### Domain 层

数据模型与枚举位于：

- `aptgent/aptgent/domain/models.py`
- `aptgent/aptgent/domain/enums.py`

涉及跨层数据传递时，优先复用这里的模型，不要在 UI 或 adapter 层重新发明结构。

### Adapter 层

所有外部工具、子进程调用和第三方能力边界都应落在：

- `aptgent/aptgent/adapters/`

当前可见的协议和实现包括：

- `StructureAdapter`
- `PredictionAdapter`
- `MoleculeAdapter`
- `SpatialRankAdapter`
- `RNAfoldAdapter`
- `EnsembleAdapter`
- `SimpleMoleculeResolver`
- `VinaAdapter`
- `HardwareProbeAdapter`

不要在 TUI screen、step handler 或 workflow engine 里直接写新的外部命令调用；先看 adapter 层是否已有合适边界，没有再补 adapter。

### LLM 层

LLM 相关代码位于：

- `aptgent/aptgent/llm/client.py`
- `aptgent/aptgent/llm/skills.py`

LLM 输出是辅助信息，不应覆盖确定性计算结果。涉及评分、排序、状态推进、持久化事实时，应以 adapter / workflow / domain 中的确定性数据为准。

## 5. 工作流事实

当前 workflow step 顺序定义在 `workflow/engine.py`：

1. `intake`
2. `secondary_structure`
3. `site_proposal`
4. `candidate_enumeration`
5. `primary_scoring`
6. `specificity_filter`
7. `docking_selection`
8. `docking_run`
9. `spatial_rank`
10. `final_report`

`ChatScreen.advance_to_step()` 会调用 `WorkflowEngine.transition_to()` 并保存状态；如果你看到状态推进异常，优先沿这条链检查。

## 6. `aptamer_predictor` 集成事实

`aptamer_predictor/` 是仓库内的独立 CLI 包，不是通过 wheel 依赖引入。`aptgent` 通过 prediction adapter 调用它。

对预测功能做修改时，通常需要同时检查：

- `aptgent/aptgent/adapters/predictor.py`
- `aptamer_predictor/aptamer_predictor/cli.py`
- `aptamer_predictor/aptamer_predictor/predictor.py`
- `aptamer_predictor/aptamer_predictor/features.py`

当前 `aptamer_predictor` 中的 ensemble 规则是严格规则：只有所有模型都预测为 `1`，ensemble label 才为 `1`。不要把 README 中更宽泛的措辞当作真实实现来源，真实行为以代码为准。

## 7. 配置与环境注意事项

配置文件位于 `aptgent/aptgent/config/`：

- `workflow.toml`：workflow 参数与 `runs_dir`
- `tools.toml`：外部工具路径、预测器模型目录、conda Python 路径
- `llm.toml`：LLM provider 配置
- `spatial_interaction_matrix.csv`：空间互作矩阵

当前仓库存在两个需要明确注意的现实问题：

- `llm.toml` 里当前包含硬编码 `api_key`。这应视为原型遗留配置，不是推荐实践。不要新增、复制或扩散任何明文密钥。
- `tools.toml` 里当前包含环境相关的绝对路径，例如 `/home/dh/...`。这不是可移植配置。修改相关逻辑或文档时，不要假定这些路径在其他机器上成立。

`LLMClient` 当前的取值优先级是“环境变量优先，配置文件回退”。如果你在修 LLM 配置问题，先看 `aptgent/aptgent/llm/client.py`，不要只改文档。

## 8. 运行与验证

常用命令：

```bash
cd aptgent
pip install -e .
python -m aptgent
pytest
```

预测器单独检查：

```bash
cd aptamer_predictor
python -m aptamer_predictor predict --help
```

说明：

- `aptgent` 依赖 Textual、Pydantic、httpx 等。
- `aptamer_predictor` 依赖 RDKit、scikit-learn、xgboost、torch 等更重的科学计算栈。
- `workflow.toml` 当前默认 `runs_dir = "./runs"`，这是相对路径，效果取决于进程工作目录。

## 9. 测试位置

当前测试位于 `aptgent/tests/`：

- `test_workflow.py`
- `test_tui.py`
- `test_spatial_rank.py`

修改以下内容后，至少应重新检查对应测试：

- workflow step / 状态流转
- chat 主流程
- spatial ranking
- predictor adapter 行为

如果你修改的是 `aptamer_predictor/` 内部逻辑，还需要额外做 CLI 或模块级验证；仓库当前没有看到与 `aptamer_predictor` 对称的完整 pytest 目录。

## 10. 推荐修改策略

### 适合改在 TUI 层的问题

- 文案、输入交互、StructuredInput 展示
- chat 中 step 的用户体验
- 某一步的界面触发逻辑

### 适合改在 Workflow 层的问题

- step 合法流转
- 暂停/恢复
- 状态持久化与日志

### 适合改在 Adapter 层的问题

- 外部命令调用
- 模型子进程集成
- 分子解析、空间打分、对接调用

### 适合改在 `aptamer_predictor` 的问题

- 特征提取
- 单模型/ensemble 预测逻辑
- CLI 输入输出行为

## 11. 不要这样改

- 不要在 UI 或 workflow 层直接增加新的 `subprocess` 调用。
- 不要让 LLM 直接决定最终分数、排序或流程状态。
- 不要把当前本地绝对路径写成通用默认值。
- 不要继续提交或复制明文 API key。

## 12. 已知高风险点

- `tools.toml` 的绝对路径说明当前配置明显带有机器依赖。
- `llm.toml` 的明文 key 是安全风险；如果本轮任务涉及配置治理，应优先处理。
- `runs_dir` 是相对路径，调试时容易因为工作目录不同而把运行数据写到不同位置。

## 13. 修改前的最小检查清单

在开始实现前，先确认：

- 你要改的是主流程中的哪一层。
- 变更应该落在 TUI、workflow、adapter 还是 predictor。
- 相关配置是否是环境特定行为。
- 相关测试是否存在，或是否需要补最小验证。

如果文档与代码冲突，以代码为准，并在修改代码后同步更新此文件。
