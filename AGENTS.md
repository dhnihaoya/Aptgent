# AGENTS.md

本文件面向在本仓库中工作的 AI coding agent。目标是帮助你基于当前代码快速定位入口、理解边界、避免修改错误层级，并识别当前仓库里已经存在的环境与安全风险。

## 1. 仓库概览

本仓库当前只有一个 Python 项目：

- `aptgent/`：主项目，一个基于 Textual 的 TUI（终端界面）工作流应用。
- 预测器能力已经深度整合进 `aptgent`，由内部 predictor runtime 通过子进程运行，以保留重依赖隔离。

`aptgent` 的主流程是一个状态驱动的多步骤工作流，LLM 只用于自然语言解析、解释和建议，不应成为确定性评分、排序或状态流转的事实来源。

## 2. 快速定位

开始工作前，优先查看这些位置：

- `aptgent/aptgent/tui/app.py`：应用入口、配置加载、adapter 装配、注册的 screen。
- `aptgent/aptgent/tui/screens/chat.py`：当前真实主界面，整个流程都在这个 chat screen 内推进。
- `aptgent/aptgent/tui/steps/`：各 workflow step 的行为实现（每步一个模块，由 `factory.py` 分发）。
- `aptgent/aptgent/tui/commands.py`：斜杠命令注册与主题预设。
- `aptgent/aptgent/workflow/`：状态机、持久化、运行状态模型、工作流上下文。
- `aptgent/aptgent/adapters/`：外部工具与外部能力边界。
- `aptgent/aptgent/protocol/`：子进程通信共享原语（JSONL 读写、取消信号、流式子进程管理）。
- `aptgent/aptgent/jobs/`：可分离的后台任务（detached job runner）。
- `aptgent/aptgent/cli/doctor.py`：环境诊断工具（`aptgent doctor`）。
- `aptgent/aptgent/bootstrap/config.py`：配置加载与 `${VAR:-default}` 环境变量展开。
- `aptgent/aptgent/bootstrap/container.py`：依赖装配（`AppRuntime` + `build_runtime()`）。
- `aptgent/tests/`：现有 pytest 测试。

## 3. 当前真实入口与主路径

### 应用入口

- 包入口：`aptgent`
- 模块入口：`python -m aptgent`
- 入口函数：`aptgent/aptgent/tui/app.py` 中的 `run()`
- 环境诊断：`aptgent doctor`（`aptgent/aptgent/cli/doctor.py`）

### 当前真实 UI 路径

`AptgentApp` 当前注册两个主 screen：

- `welcome`
- `chat`

另有以下辅助 screen（通过 `push_screen` 使用，不在 `SCREENS` 注册表中）：

- `QuitConfirmScreen`：退出确认对话框。
- `ResumePickerScreen`：从 chat screen 内恢复已保存的 run。
- `ThemePickerScreen`：主题切换 UI。

主工作流由 `ChatScreen` 驱动，每一步的行为实现位于 `tui/steps/` 目录，每个 step 一个模块（如 `intake.py`、`structure.py`、`scoring.py` 等），由 `tui/steps/factory.py` 中的 `create_handler()` 按 `Step` 枚举分发。

排查或修改主流程时，应直接沿 `ChatScreen` → `factory.py` → 对应 step 模块这条路径工作。

chat screen 支持斜杠命令（`/resume`、`/quit`、`/export`、`/theme` 等），定义在 `tui/commands.py`。

## 4. 架构边界

### TUI 层

负责用户交互、展示、输入收集和 step 触发：

- `aptgent/aptgent/tui/screens/`：chat、welcome、quit_confirm、resume、theme_picker。
- `aptgent/aptgent/tui/steps/`：每个 workflow step 一个模块（`intake.py`、`pdb_intake.py`、`structure.py`、`site_proposal.py`、`enumeration.py`、`scoring.py`、`specificity.py`、`docking_selection.py`、`docking_run.py`、`spatial_rank.py`、`report.py`），由 `factory.py` 分发。
- `aptgent/aptgent/tui/steps/common/`：跨 step 共用工具（`__init__.py` 重新导出所有公共符号，保持 `from aptgent.tui.steps.common import X` 兼容）。子模块：`coercion.py`（类型转换）、`docking_plan.py`（对接参数校验）、`intake_format.py`（intake 输出格式化）、`llm_ui.py`（LLM UI 辅助）、`site_proposal_validate.py`（位点方案校验）、`specificity_format.py`（特异性结果格式化）。
- `aptgent/aptgent/tui/steps/empty_candidates.py`：空候选统一处理（`is_empty_enumeration_result`、`prepare_empty_candidate_recovery`、`clear_site_selection_retry_feedback`），被 enumeration、scoring、chat back-handler 共用。
- `aptgent/aptgent/tui/steps/base.py`：`StepHandler` 基类。
- `aptgent/aptgent/tui/steps/job_mixin.py`：可分离后台任务 mixin（attach/spawn detached subprocess）。
- `aptgent/aptgent/tui/widgets/`：通用 widget（`StatusPanel`、`StepProgressBar`、`StructuredInput`、chat bubble 系列）。
- `aptgent/aptgent/tui/commands.py`：斜杠命令注册、主题预设。

### Workflow 层

负责状态流转、暂停/恢复、完成/失败和持久化：

- `aptgent/aptgent/workflow/engine.py`：状态机 + `TRANSITIONS` 流程图。
- `aptgent/aptgent/workflow/persistence.py`：JSON 持久化 + 日志追加。
- `aptgent/aptgent/workflow/state.py`：`RunState` + 各步骤的 `WorkflowContext` 子模型。
- `aptgent/aptgent/workflow/context.py`：context 读写辅助函数（`record_intake_context()`、`build_site_proposal_llm_context()` 等）。
- `aptgent/aptgent/workflow/run_card.py`：工作流完成时自动生成 `run_card.json`（版本、模型哈希、工具版本、LLM 配置、步骤时间）。

`workflow/engine.py` 中的 `TRANSITIONS` 是当前流程图的真实来源。改流程顺序时先改这里，再检查对应 handler 和测试。

完成（`engine.complete()`）时会自动调用 `write_run_card()` 写入可复现性记录。

### Domain 层

数据模型与枚举位于：

- `aptgent/aptgent/domain/models.py`
- `aptgent/aptgent/domain/enums.py`
- `aptgent/aptgent/domain/text_utils.py`：文本规范化（`clean_text`：strip + 折叠内部空白）。

涉及跨层数据传递时，优先复用这里的模型，不要在 UI 或 adapter 层重新发明结构。

### Protocol 层

子进程通信的共享原语，被 adapter、jobs、predictor_runtime 共用：

- `aptgent/aptgent/protocol/line_json.py`：`JsonlEmitter`（行式 JSON 写入）和 `iter_jsonl`（行式 JSON 迭代读取）。
- `aptgent/aptgent/protocol/cancel.py`：`CmdFileCancelPoller`（命令文件轮询取消）和 `StdinCancelWatcher`（stdin cancel 信号监听）。
- `aptgent/aptgent/protocol/subprocess_stream.py`：`SubprocessSession`（流式子进程生命周期管理：stdout JSONL 读取、stderr 收集、cancel/terminate/kill 三阶段终止）。

不要在 adapter 或 jobs 层内联新的子进程协议实现，优先复用或扩展 protocol 层的原语。

### Adapter 层

所有外部工具、子进程调用和第三方能力边界都应落在：

- `aptgent/aptgent/adapters/`

当前可见的协议和实现包括：

- `StructureAdapter`（协议）：RNA 折叠。实现：`RNAfoldAdapter`（`rna_fold.py`）。
- `PredictionAdapter`（协议）：批量预测。实现：`EnsembleAdapter`（`predictor.py`）。
- `MoleculeAdapter`（协议）：分子解析。实现：`SimpleMoleculeResolver`（`molecule.py`）。
- `SpatialRankAdapter`（协议 + 实现）：空间互作排序（`spatial_rank.py`）。
- `VinaAdapter`：AutoDock Vina 对接（`docking.py`）。
- `ReceptorPrepAdapter`：受体 PDBQT 准备（`receptor_prep.py`）。
- `RNAComposerAdapter`：RNAComposer 三级结构预测（`rnacomposer.py`）。
- `PdbAnalysisAdapter`：PDB 文件下载、解析、链/配体提取（`pdb_analysis.py`）。
- `StructureLookupAdapter`（协议）：3D 结构数据库查询（`structure_services.py`）。
- `StructureFetchAdapter`（协议）：3D 结构文件下载（`structure_services.py`）。
- `TertiaryStructureAdapter`（协议）：三级结构预测任务提交/轮询（`structure_services.py`）。

不在 `AppRuntime` 中直接暴露但不再需要的旧 adapter（如 `HardwareProbeAdapter`）已移除；硬件检测逻辑内联在 docking selection handler 中。

不要在 TUI screen、step handler 或 workflow engine 里直接写新的外部命令调用；先看 adapter 层是否已有合适边界，没有再补 adapter。

### LLM 层

LLM 相关代码位于：

- `aptgent/aptgent/llm/client.py`
- `aptgent/aptgent/llm/skills/`（每个 skill 一个子目录，包含 `SKILL.md`、`system.md`、`schema.py`、`skill.py`）
- `aptgent/aptgent/llm/skills/base.py`：`BaseSkill`、`SkillMetadata`、`SkillRegistry` 基类。

LLM 输出是辅助信息，不应覆盖确定性计算结果。涉及评分、排序、状态推进、持久化事实时，应以 adapter / workflow / domain 中的确定性数据为准。

当前 LLM skills（全部注册在 `llm/skills/__init__.py` 的 `registry` 中）：

- `intake`：自然语言输入解析，提取序列、靶标分子、修饰区域、类似物列表和时间预算等字段。
- `pdb_review`：PDB 结构语义审查，7 类分类 + 靶标匹配 + 置信度。输出用于 review gate 机制（不合适的 PDB 会暂停流程等待用户确认）。
- `site_proposal`：突变位点提议（含 rephrase 能力）。先产出区域级风险评估（`region_assessment`），将序列区域分为 `safer_scaffold`、`suspected_binding_core` 或 `uncertain`，解释每个区域的分类依据；再给出恰好 3 个备选 mutation 方案，按保守 → 激进（含保守位点）→ LLM 自选方向排序；每个方案包含独立的位点、推理和置信度，若使用了 suspected binding/core 风险位点需显式说明理由；首选方案会镜像到 legacy 字段保持兼容。UI 层以 `expanded` 模式展示全部选项。支持 retry feedback：当枚举或打分步骤未找到阳性候选时，通过 `extra_context.site_selection_feedback` 回传失败原因、上下文引导（`guidance`）、需保留的方案索引（`preserve_proposal_indexes`）和前一轮方案（`previous_proposals`），LLM 据此只替换失败的方案槽位。
- `analog_suggestion`：结构类似物建议，用于特异性过滤步骤，LLM 推荐靶标的类似物供交叉预测。
- `docking_planner`：对接参数建议（advisory 级别），LLM 可建议 `top_k`、`grid_size`、`exhaustiveness`，但所有数值经 `validate_docking_recommendation_result()` 钳位后才生效。
- `report`：最终报告生成，LLM 基于确定性 workflow 结果撰写 Markdown 报告。TUI 先直接展示 Markdown；导出时用户侧主产物为 `final_report.md`，同时保留 `final_report.json` 作为机器可读 sidecar。报告只详细展开进入 docking 的序列，未 docking 的候选只汇总预测、筛选、得分范围等概况，不逐条展示。

LLM 调用日志记录到 `<run_dir>/logs/llm_calls.jsonl`，默认对用户输入做 SHA-256 脱敏（`APTGENT_LLM_REDACT=0` 关闭）。

`LLMClient` 支持四种调用模式：`chat_json`（同步 JSON 请求）、`chat_json_events`（流式 SSE，逐步 yield reasoning/content 事件，最终 yield `{"type": "result", "value": parsed_json}`）、`chat_json_stream`（流式 JSON 文本，`chat_stream` 为其旧别名）、`chat_text_stream`（纯文本流式）。site proposal skill 已通过 `propose_events_from_context` 接入 `chat_json_events`，在生成方案时实时展示 LLM reasoning。analog_suggestion skill 正在迁移到统一的 `suggest_events` 流式接口（测试已更新，生产代码待迁移）。

### Jobs 层（可分离后台任务）

长时间运行的步骤（如 docking）可以作为独立子进程执行，TUI 不需要保持运行：

- `aptgent/aptgent/jobs/runner.py`：`aptgent run-job <run_id> <step>` 入口，在隔离进程中加载 RunState 并执行 step 逻辑。当前注册的 step：`candidate_enumeration`、`specificity_filter`、`docking_run`。
- `aptgent/aptgent/jobs/events.py`：事件写入/读取（`runs/<id>/jobs/<step>/events.jsonl`）。
- `aptgent/aptgent/jobs/pid.py`：PID 文件管理，用于检测子进程存活状态。
- `aptgent/aptgent/tui/steps/job_mixin.py`：TUI 端 mixin，提供 `attach_or_spawn_job()`——自动判断附加到正在运行的 job、加载已完成结果、或启动新子进程。

## 5. 工作流事实

当前 workflow step 顺序定义在 `workflow/engine.py`：

1. `intake`
2. `secondary_structure`
3. `site_proposal`
4. `candidate_enumeration`
5. `primary_scoring`
6. `specificity_filter`
7. `docking_selection`（可跳过 docking 直接到 `spatial_rank`，见下方 docking skip 说明）
8. `docking_run`
9. `spatial_rank`
10. `final_report`

`ChatScreen.advance_to_step()` 会调用 `WorkflowEngine.transition_to()` 并保存状态；如果你看到状态推进异常，优先沿这条链检查。

intake step 内部包含 PDB 输入子流程（`tui/steps/pdb_intake.py`），当用户提供 PDB ID 时会自动触发 PDB 下载、解析、链/配体选择和 LLM 语义审查。这是 intake step 内部的分支，不是独立的 workflow step。

### Docking skip 路径

当 docking 不可用（Vina 未安装或配置禁用）时，`docking_selection` step 可直接跳转到 `spatial_rank`，跳过 `docking_run`。`DOCKING_SELECTION → SPATIAL_RANK` 转换已在 `TRANSITIONS` 中注册。TUI 层通过 `_is_docking_enabled()` 检测可用性，`_skip()` 执行跳转。

## 6. Predictor 集成事实

预测能力内聚在 `aptgent` 包内，predictor runtime 通过子进程运行。在默认的单环境安装中，所有依赖（包括 RDKit、torch、xgboost）都在同一个 conda 环境中，predictor 直接使用当前 Python 执行。如需隔离环境，可通过 `tools.toml` 中的 `conda_env` / `conda_python` 配置。

对预测功能做修改时，通常需要同时检查：

- `aptgent/aptgent/adapters/predictor.py`
- `aptgent/aptgent/predictor_runtime/runner.py`
- `aptgent/aptgent/predictor_runtime/predictor.py`
- `aptgent/aptgent/predictor_runtime/features.py`
- `aptgent/aptgent/predictor_runtime/cuda.py`
- `aptgent/aptgent/predictor_runtime/paths.py`（模型目录默认路径解析）
- `aptgent/aptgent/resources/predictor_models/`

当前 predictor runtime 中的 ensemble 规则是严格规则：只有所有模型都预测为 `1`，ensemble label 才为 `1`。不要把旧文档或历史措辞当作真实实现来源，真实行为以代码为准。

### mutation-batch 加速路径

`EnsembleAdapter.predict_mutation_batch()` 提供了大空间突变筛选的加速管线，通过 `runner.py mutation-batch` 子命令以子进程方式运行。子进程 stdout 使用行式 JSON 协议（`ready` / `progress` / `hit` / `done` / `error`），stdin 接受 `cancel` 取消信号。

加速技术包括：
- 描述子预计算（SMILES → 209 维 RDKit 描述子只算一次，跨所有 mutant tile）
- 向量化 k-mer（base-4 编码 + offset bincount）
- 动态模型校准（采 64 个 mutant 确定最优模型顺序）
- 级联早退过滤（每个模型只处理上一模型的幸存者）
- 分块枚举（65536 为块，纯 NumPy 字节操作生成 mutant）
- CUDA 加速（PyTorch RNN/biRNN `.to("cuda")`，XGBoost `DMatrix(device="cuda")`）

`EnumerationHandler`（`tui/steps/enumeration.py`）自动检测 adapter 是否有 `predict_mutation_batch` 方法来决定走加速路径还是慢速回退路径。只保留阳性命中（positives-only）写入 `scored_candidates.jsonl`。配置见 `workflow.toml` 的 `[enumeration]` 下 `sub_batch_size` 和 `progress_every`。

`predict_mutation_batch()` 支持 `skip_first` 参数，用于在部分运行中断后从上次进度恢复。

### Enumeration 取消处理

用户可通过命令文件（`<run_dir>/jobs/candidate_enumeration/cmd.jsonl`）发送取消信号。Runner 层使用独立的 `stop_cancel_poller` 事件控制轮询线程的生命周期，并在 `predict_mutation_batch()` 返回后 join 线程。取消来源有两个：用户主动取消（命令文件写入 `cancel`）和 adapter 内部取消（返回 `{"cancelled": true}`）。

TUI 层（`enumeration.py`）在检测到取消时，显示警告信息并回退到 `site_proposal` 步骤（`rewind_to_step`），让用户重新选择突变位点，而非直接终止工作流。

### specificity-batch 加速路径

`EnsembleAdapter.predict_specificity_batch()` 把 `(candidates × targets)` 交叉打分搬到 predictor 子进程里流式执行，避免 in-process worker 长时间无响应。子进程通过 `runner.py specificity-batch` 子命令运行，stdout 协议与 mutation-batch 风格一致：

- `ready`：模型加载完成（含 `device`、`model_order`、`total`）。
- `row`：单个 `(target_idx, candidate_id)` 完成（含 `label`、`probability`、`target_name`）。
- `progress`：每 `--progress-every` 个 row（以及 target 切换时）发一次。
- `done` / `error`：终止事件。
- stdin 接受 `cancel\n` 软取消信号。

`SpecificityHandler`（`tui/steps/specificity.py`）继承 `JobAttachMixin`，`JOB_STEP="specificity_filter"`；analog 选择完成后通过 `attach_or_spawn_job()` 启动 detached job runner（`_run_specificity` in `jobs/runner.py`）。runner 持续维护 `runs/<id>/artifacts/specificity_results.jsonl`（首行为 meta，其余按 candidate 写入 kept/removed/failed_analogs），断点续跑时通过 meta 匹配 + `skip_pairs` 把已完成的 `(target_idx, candidate_id)` 让子进程跳过。

UI 上 `ProgressBubble` 与 candidate enumeration 完全一致，信息行格式为 `Progress: X/Y | Kept: K | Removed: R | Target: <name>`。

## 7. 配置与环境注意事项

配置文件位于 `aptgent/aptgent/config/`：

- `workflow.toml`：workflow 参数（enumeration、docking、LLM 超参）与 `runs_dir`
- `tools.toml`：外部工具路径（RNAfold、Vina）、预测器模型目录、PDB 下载配置
- `llm.toml`：LLM provider 配置
- `spatial_interaction_matrix.csv`：空间互作矩阵

`tools.toml` 中的命令默认从 PATH 查找（如 `RNAfold`、`vina`），在单环境安装下零配置即可工作。可通过环境变量 `APTGENT_RNAFOLD`、`APTGENT_VINA` 等覆盖。`predictor.model_dir` 为空时自动使用包内 bundled 模型目录（`resources/predictor_models/`）。

`workflow.toml` 中 `runs_dir` 使用 `${APTGENT_RUNS_DIR:-./runs}` 格式，支持环境变量展开。`mutation_batch_timeout_seconds = 0` 表示不限时。docking 部分有 `per_ligand_timeout_seconds`（默认 1800 秒）。

`llm.toml` 使用“环境变量优先、配置文件回退”的加载逻辑；仓库内默认值应保持为空占位，不要新增、复制或扩散任何明文密钥。

`LLMClient` 当前的取值优先级是“环境变量优先，配置文件回退”。如果你在修 LLM 配置问题，先看 `aptgent/aptgent/llm/client.py`，不要只改文档。

## 8. 运行与验证

推荐使用 `environment.yml` 一次性安装所有依赖（单一 conda 环境，Python 3.10）：

```bash
cd aptgent
conda env create -f environment.yml
conda activate aptgent
aptgent doctor   # 检查环境
aptgent          # 启动 TUI
```

开发模式：

```bash
conda activate aptgent
pip install -e .
pytest
```

后台任务入口：

```bash
aptgent run-job <run_id> <step>
```

说明：

- 所有依赖（包括 RDKit、torch、xgboost、ViennaRNA、AutoDock Vina、BioPython）都在同一个 conda 环境中。
- `workflow.toml` 当前默认 `runs_dir = "${APTGENT_RUNS_DIR:-./runs}"`，未设环境变量时为相对路径，效果取决于进程工作目录。

## 9. 测试位置

当前测试位于 `aptgent/tests/`：

- `test_workflow_engine.py`：workflow 状态机流转测试
- `test_workflow.py`：workflow 辅助逻辑测试
- `test_persistence.py`：持久化层测试
- `test_skills.py`：LLM skill 注册与基础行为测试
- `test_llm_client_retry.py`：LLM 客户端重试逻辑测试
- `test_llm_client_payloads.py`：LLM 请求 payload、thinking 与 SSE 事件测试
- `test_llm_result_validation.py`：LLM 输出校验与展示格式测试
- `test_workflow_context_helpers.py`：workflow context 构建与记录辅助测试
- `test_predictor_adapter_mutation_protocol_success.py`、`test_predictor_adapter_mutation_protocol_cancel.py`、`test_predictor_adapter_mutation_protocol_errors.py`：mutation-batch 子进程行式 JSON 协议成功/取消/错误测试
- `test_predictor_feature_matrix_batch.py`：批量特征矩阵测试
- `test_predictor_mutation_batch_runtime.py`：predictor runtime mutation-batch 规则测试
- `test_predictor_specificity_batch_protocol.py`：specificity-batch 子进程协议测试
- `test_tui_enumeration_acceleration.py`：TUI enumeration detached mutation-batch job 启动测试
- `test_feature_matrix.py`：特征矩阵计算测试
- `test_predictor_adapter.py`：预测器 adapter 测试
- `test_jobs_events.py`、`test_jobs_persistence_paths.py`、`test_jobs_pid.py`、`test_jobs_runner_cli.py`、`test_jobs_specificity_runner.py`：jobs 层事件、路径、PID、CLI 与 specificity runner 测试
- `test_tui_job_mixin.py`：TUI detached job attach/spawn 行为测试
- `test_tui_app_navigation.py`、`test_tui_chat_widgets.py`、`test_tui_docking_selection.py`、`test_tui_intake_pdb.py`、`test_tui_scoring_retry.py`、`test_tui_secondary_structure.py`、`test_tui_site_proposal.py`、`test_tui_specificity.py`：TUI 行为测试
- `test_tui_markdown_theme.py`：chat markdown 主题测试
- `test_enumeration_ui.py`：枚举步骤 UI 测试
- `test_pdb_analysis.py`：PDB 分析 adapter 测试
- `test_spatial_rank.py`：空间排序测试
- `test_tui_report.py`：最终 Markdown 报告上下文、fallback 展示与导出测试
- `test_receptor_prep.py`：受体 PDBQT 准备 adapter 测试
- `test_rnacomposer_adapter.py`：RNAComposer adapter 测试
- `test_protocol_cancel.py`、`test_protocol_line_json.py`、`test_protocol_subprocess_stream.py`：protocol 层取消、JSONL、子进程流测试
- `test_domain_text_utils.py`：domain 文本工具测试
- `test_docking_skip_path.py`：docking skip 路径测试

修改以下内容后，至少应重新检查对应测试：

- workflow step / 状态流转 → `test_workflow_engine.py`、`test_persistence.py`
- LLM skill 行为 / 输出校验 → `test_skills.py`、`test_llm_client_retry.py`、`test_llm_client_payloads.py`、`test_llm_result_validation.py`、`test_workflow_context_helpers.py`
- predictor / 特征提取 → `test_predictor_adapter_mutation_protocol_*.py`、`test_predictor_feature_matrix_batch.py`、`test_predictor_mutation_batch_runtime.py`、`test_predictor_specificity_batch_protocol.py`、`test_tui_enumeration_acceleration.py`、`test_feature_matrix.py`、`test_predictor_adapter.py`
- TUI step handler / UI → `test_tui_*.py`、`test_enumeration_ui.py`、`test_tui_markdown_theme.py`
- PDB / 结构分析 → `test_pdb_analysis.py`
- 受体准备 → `test_receptor_prep.py`
- RNAComposer → `test_rnacomposer_adapter.py`
- 空间排序 → `test_spatial_rank.py`
- detached job 系统 → `test_jobs_*.py`、`test_tui_job_mixin.py`
- protocol 层子进程通信 → `test_protocol_*.py`
- domain 文本工具 → `test_domain_text_utils.py`
- docking skip 路径 → `test_docking_skip_path.py`
- workflow 辅助逻辑 → `test_workflow.py`

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
- PDB 分析与 3D 结构服务

### 适合改在 Protocol 层的问题

- 子进程 JSONL 通信协议
- 取消信号（命令文件轮询、stdin 监听）
- 流式子进程生命周期管理（启动、stderr 收集、三阶段终止）

### 适合改在 predictor runtime 的问题

- 特征提取
- 单模型/ensemble 预测逻辑
- 内部 runner 输入输出行为

### 适合改在 Jobs 层的问题

- 长时间步骤的后台执行逻辑
- 事件协议（events.jsonl 格式）
- PID 管理与进程生命周期

## 11. 不要这样改

- 不要在 UI 或 workflow 层直接增加新的 `subprocess` 调用。
- 不要让 LLM 直接决定最终分数、排序或流程状态。
- 不要把当前本地绝对路径写成通用默认值。
- 不要继续提交或复制明文 API key。

## 12. 已知高风险点

- `llm.toml` 中当前存有一个真实 API key（`sk-3Pfd...`），这是安全风险。配置治理时应优先保持 env-only 用法，长期目标是清除该明文密钥。
- `runs_dir` 默认是相对路径（`${APTGENT_RUNS_DIR:-./runs}`），调试时容易因为工作目录不同而把运行数据写到不同位置。
- detached job 子进程在 TUI 退出后继续运行；如果 events.jsonl 或 PID 文件损坏，TUI 重启后可能无法正确 attach。

## 13. 修改前的最小检查清单

在开始实现前，先确认：

- 你要改的是主流程中的哪一层。
- 变更应该落在 TUI、workflow、adapter、predictor 还是 jobs。
- 相关配置是否是环境特定行为。
- 相关测试是否存在，或是否需要补最小验证。
- 如果涉及新的外部命令调用，是否应先在 adapter 层封装。

## 14. 推送前检查

Before pushing to remote, always review and update CLAUDE.md and AGENTS.md to ensure they reflect the current codebase state (directory layout, entry points, workflow steps, new features, config changes).

如果文档与代码冲突，以代码为准，并在修改代码后同步更新此文件。
