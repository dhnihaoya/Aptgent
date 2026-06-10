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
- `aptgent/aptgent/tui/rich_theme.py`：chat markdown 主题定义。
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

主工作流由 `ChatScreen` 驱动，每一步的行为实现位于 `tui/steps/` 目录，每个 step 一个模块（如 `intake.py`、`structure.py`、`scoring.py` 等），由 `tui/steps/factory.py` 中的 `create_handler()` 按 `Step` 枚举分发。`factory.py` 同时导出 `detached_job_step_name(step)`，通过读取 handler 的 `JOB_STEP` 类属性返回对应的 detached job runner 步骤名，供 cancel/resume 流程使用。

排查或修改主流程时，应直接沿 `ChatScreen` → `factory.py` → 对应 step 模块这条路径工作。

chat screen 支持斜杠命令（`/resume`、`/quit`、`/export`、`/theme`、`/finish`、`/back`、`/cancel` 等），定义在 `tui/commands.py`。

## 4. 架构边界

### TUI 层

负责用户交互、展示、输入收集和 step 触发：

- `aptgent/aptgent/tui/screens/`：chat、welcome、quit_confirm、resume、theme_picker、`chat_commands.py`（`ChatCommandController`，从 chat.py 提取）、`chat_resume.py`（`detect_resume_target()` 通过遍历 `STEP_ORDER` + `detached_job_step_name()` 动态推导 resume 目标，新增 detached-job 步骤无需手动维护元组）。
- `aptgent/aptgent/tui/steps/`：每个 workflow step 一个模块（`intake.py`、`pdb_intake.py`、`structure.py`、`site_proposal.py`、`enumeration.py`、`scoring.py`、`specificity.py`（mixin 组合：`SpecificityAnalogMixin` + `SpecificityPanelMixin` + `SpecificityProgressMixin` + `JobAttachMixin`）、`docking_selection.py`（re-export shim，实现在 `docking/` 子包）、`docking_run.py`、`spatial_rank.py`、`report.py`），由 `factory.py` 分发。辅助模块：`intake_heuristics.py`（intake 输入启发式规则）、`intake_resolver.py`（intake 输入解析）、`state_reset.py`（状态重置辅助）、`job_progress.py`（`JobProgressTracker` dataclass，集中管理 detached job 进度状态）、`specificity_analogs.py`（`SpecificityAnalogMixin`，类似物处理）、`specificity_panels.py`（`SpecificityPanelMixin`，类似物 UI 面板）、`specificity_progress.py`（`SpecificityProgressMixin`，detached job 进度 mixin）。
- `aptgent/aptgent/tui/steps/common/`：跨 step 共用工具（`__init__.py` 重新导出所有公共符号，保持 `from aptgent.tui.steps.common import X` 兼容）。子模块：`coercion.py`（类型转换）、`docking_plan.py`（对接参数校验）、`formatting.py`（候选排名展示格式化）、`intake_format.py`（intake 输出格式化）、`llm_ui.py`（LLM UI 辅助 + `capture_streaming_result` 流式结果捕获）、`site_proposal_validate.py`（位点方案校验）、`specificity_format.py`（特异性结果格式化）。
- `aptgent/aptgent/tui/steps/empty_candidates.py`：空候选统一处理（`is_empty_enumeration_result`、`prepare_empty_candidate_recovery`、`clear_site_selection_retry_feedback`、`apply_empty_candidate_recovery_ui`），被 enumeration、scoring、chat back-handler 共用。
- `aptgent/aptgent/tui/steps/base.py`：`StepHandler` 基类（含 `allow_empty_input` 属性控制是否接受空输入提交、`_report_error()` 统一错误报告（线程安全：主线程直调，worker 线程走 `call_from_thread`）、`reload_run_state()` 从持久化重载并返回最新状态）。
- `aptgent/aptgent/tui/steps/job_mixin.py`：可分离后台任务 mixin（attach/spawn detached subprocess）。
- `aptgent/aptgent/tui/widgets/`：通用 widget（`StatusPanel`、`StepProgressBar`、`StructuredInput`、chat bubble 系列（`SystemBubble`、`StreamingBubble`、`ThinkingBubble`、`UserBubble`、`ProgressBubble`、`ActivityBubble`））。子包 `panels/`（`_core.py`、`_intake.py`、`_specificity.py`、`_docking.py`（含 `MutationRatioPanel`））和 `common.py` 提供步骤专用面板组件。
- `aptgent/aptgent/tui/commands.py`：斜杠命令注册、主题预设（当前 6 个：clear-lanes、clean-minimal-light、warm-industrial、QTY、ZYX、QJX）。

### Workflow 层

负责状态流转、暂停/恢复、完成/失败和持久化：

- `aptgent/aptgent/workflow/engine.py`：状态机 + `TRANSITIONS` 流程图。
- `aptgent/aptgent/workflow/persistence.py`：JSON 持久化 + 日志追加。
- `aptgent/aptgent/workflow/state.py`：`RunState` + 各步骤的 `WorkflowContext` 子模型。
- `aptgent/aptgent/workflow/context.py`：context 读写辅助函数（`record_intake_context()`、`build_site_proposal_llm_context()` 等）。
- `aptgent/aptgent/workflow/run_card.py`：工作流完成时自动生成 `run_card.json`（版本、模型哈希、工具版本、LLM 配置、步骤时间）。

`workflow/engine.py` 中的 `TRANSITIONS` 是当前流程图的真实来源。改流程顺序时先改这里，再检查对应 handler 和测试。`STEP_ORDER` 是公开的步骤顺序常量，被 resume 逻辑（`chat_resume.py`）和步骤显示编号使用；新增 detached-job 步骤时只需在 handler 上定义 `JOB_STEP`，resume 会自动发现。

完成（`engine.complete()`）时会自动调用 `write_run_card()` 写入可复现性记录。

### Domain 层

数据模型与枚举位于：

- `aptgent/aptgent/domain/models.py`
- `aptgent/aptgent/domain/enums.py`
- `aptgent/aptgent/domain/text_utils.py`：文本规范化（`clean_text`：strip + 折叠内部空白）。
- `aptgent/aptgent/domain/ranking.py`：基于精确概率值的 dense ranking（`ProbHistogramRanker`：以精确浮点概率值为 dict key 累计计数，dense rank = 严格大于的不同概率值个数 + 1）、`rank_sums_from_model_probs`、通用 `competition_ranks` / `dense_ranks` 函数、`select_top_y_by_affinity`。
- `aptgent/aptgent/domain/sequence.py`：标准序列转换（`rna_to_dna`、`dna_to_rna`）和残基→碱基映射（`NUCLEOTIDE_TO_BASE`）。adapter 层和 predictor_runtime 均从此导入，避免各处重复定义。

涉及跨层数据传递时，优先复用这里的模型，不要在 UI 或 adapter 层重新发明结构。

### Protocol 层

子进程通信的共享原语，被 adapter、jobs、predictor_runtime 共用：

- `aptgent/aptgent/protocol/line_json.py`：`JsonlEmitter`（行式 JSON 写入）和 `iter_jsonl`（行式 JSON 迭代读取）。
- `aptgent/aptgent/protocol/cancel.py`：`CmdFileCancelPoller`（命令文件轮询取消）和 `StdinCancelWatcher`（stdin cancel 信号监听）。
- `aptgent/aptgent/protocol/subprocess_stream.py`：`SubprocessSession`（流式子进程生命周期管理：stdout JSONL 读取、stderr 收集、cancel/terminate/kill 三阶段终止，各阶段等待时间可通过 `shutdown_waits` 参数配置，默认 `(30, 10, 5)` 秒）。

不要在 adapter 或 jobs 层内联新的子进程协议实现，优先复用或扩展 protocol 层的原语。

### Adapter 层

所有外部工具、子进程调用和第三方能力边界都应落在：

- `aptgent/aptgent/adapters/`

当前可见的协议和实现包括：

- `StructureAdapter`（协议）：RNA 折叠。实现：`RNAfoldAdapter`（`rna_fold.py`）。
- `PredictionAdapter`（协议）：批量预测。实现：`EnsembleAdapter`（`predictor.py`）。
- `MoleculeAdapter`（协议）：分子解析。实现：`SimpleMoleculeResolver`（`molecule.py`）。
- `SpatialRankAdapter`（协议 + 实现）：空间互作排序（`spatial_rank.py`）。有两种模式：当对接 pose（PDBQT）可用时走 **pose-based 二值规则匹配**（解析受体碱基 + 第一个 pose 原子，按官能团→期望碱基的近距离接触计数，与对接亲和力联合排名）；否则回退到序列组成加权评分。`rank_batch(candidates, target, docking_results=None)` 据此分发。
- `VinaAdapter`：AutoDock Vina 对接（`docking.py`）。
- `ReceptorPreparationAdapter`：受体 PDBQT 准备（`receptor_prep.py`）。
- `RNAComposerAdapter`：RNAComposer 三级结构预测（`rnacomposer.py`）。
- `MoePreparationAdapter`（可选）：MOE 受体准备（`moe_prep.py`）。当 `moebatch` 可用时，替代 `revert_ribose_to_deoxyribose` + `obminimize`，使用 AmberEHT 力场 RNA→DNA 转换和能量最小化。内含 SVL 脚本 `resources/scripts/moe_rna2dna_min.svl`（sdev 0.5 Å, gtest 0.1 的全重原子 tether 约束最小化）。通过 `APTGENT_MOEBATCH` 或 `tools.toml` `[moe]` 配置；不可用时自动隐藏 MOE 选项。
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

- `intake`：自然语言输入解析，提取序列、靶标分子、修饰区域、类似物列表、时间预算和突变比例（`mutation_ratio`，0.0–1.0）等字段。
- `pdb_review`：PDB 结构语义审查，7 类分类 + 靶标匹配 + 置信度。输出用于 review gate 机制（不合适的 PDB 会暂停流程等待用户确认）。
- `site_proposal`：突变位点提议。进入此步骤后，TUI 先展示 intake 阶段提取的已有突变要求（`modification_region`、`proposed_sites`），并邀请用户输入额外偏好（`site_preference`，存入 `SiteProposalContext`）；用户可直接按 Enter 跳过。偏好通过 `build_site_proposal_llm_context()` 的 `user_request.site_preference` 传入 LLM。LLM 先产出区域级风险评估（`region_assessment`），将序列区域分为 `safer_scaffold`、`suspected_binding_core` 或 `uncertain`，解释每个区域的分类依据；再给出恰好 3 个备选 mutation 方案，按保守 → 激进（含保守位点）→ LLM 自选方向排序；每个方案包含独立的位点、推理和置信度，若使用了 suspected binding/core 风险位点需显式说明理由；首选方案会镜像到 legacy 字段保持兼容。UI 层以 `expanded` 模式展示全部选项。支持 retry feedback：当枚举或打分步骤未找到阳性候选时，通过 `extra_context.site_selection_feedback` 回传失败原因、上下文引导（`guidance`）、需保留的方案索引（`preserve_proposal_indexes`）和前一轮方案（`previous_proposals`），LLM 据此只替换失败的方案槽位。
- `analog_suggestion`：结构类似物建议，用于特异性过滤步骤，LLM 推荐靶标的类似物供交叉预测。
- `analog_parse`：类似物自然语言解析，将用户输入的类似物描述（如"用咖啡因做特异性筛选"）解析为结构化的靶标名称列表。特异性步骤使用。
- `docking_planner`：对接参数建议（advisory 级别），LLM 可建议 `top_k`、`exhaustiveness`，但所有数值经 `validate_docking_recommendation_result()` 钳位后才生效。
- `docking_params_parse`：对接参数自然语言解析，将用户输入的对接参数描述（如"对接前 10 个候选"）解析为结构化的参数对象。docking selection 步骤使用。
- `report`：最终报告生成，LLM 基于确定性 workflow 结果撰写 Markdown 报告。TUI 先直接展示 Markdown；导出时用户侧主产物为 `final_report.md`，同时保留 `final_report.json` 作为机器可读 sidecar。报告只详细展开进入 docking 的序列，未 docking 的候选只汇总预测、筛选、得分范围等概况，不逐条展示。

LLM 调用日志记录到 `<run_dir>/logs/llm_calls.jsonl`，默认对用户输入做 SHA-256 脱敏（`APTGENT_LLM_REDACT=0` 关闭）。

`LLMClient` 支持四种调用模式：`chat_json`（同步 JSON 请求）、`chat_json_events`（流式 SSE，逐步 yield reasoning/content 事件，最终 yield `{"type": "result", "value": parsed_json}`）、`chat_json_stream`（流式 JSON 文本）、`chat_text_stream`（纯文本流式）。site proposal skill 已通过 `propose_events_from_context` 接入 `chat_json_events`，在生成方案时实时展示 LLM reasoning。analog_suggestion skill 已迁移到统一的 `suggest_events` 流式接口（`specificity.py:140`）。

### Jobs 层（可分离后台任务）

长时间运行的步骤（如 docking）可以作为独立子进程执行，TUI 不需要保持运行：

- `aptgent/aptgent/jobs/runner/`：`aptgent run-job <run_id> <step>` 入口，在隔离进程中加载 RunState 并执行 step 逻辑。包结构：`__init__.py`（注册表 + CLI 入口）、`_shared.py`（心跳 + 持久化）、`enumeration.py`（`_run_enumeration`）、`specificity.py`（`_run_specificity`）、`docking.py`（`_run_docking`）。当前注册的 step：`candidate_enumeration`、`specificity_filter`、`docking_run`。
- `aptgent/aptgent/jobs/events.py`：事件写入/读取（`runs/<id>/jobs/<step>/events.jsonl`）。
- `aptgent/aptgent/jobs/pid.py`：PID 文件管理，用于检测子进程存活状态。
- `aptgent/aptgent/jobs/cancel.py`：`CancelContext` 取消上下文，用于管理 job 取消信号。
- `aptgent/aptgent/jobs/resume.py`：断点续跑辅助，处理 job 中断后恢复逻辑。
- `aptgent/aptgent/tui/steps/job_mixin.py`：TUI 端 mixin，提供 `attach_or_spawn_job()`——自动判断附加到正在运行的 job、加载已完成结果、或启动新子进程。

## 5. 工作流事实

当前 workflow step 顺序定义在 `workflow/engine.py`：

1. `intake`
2. `secondary_structure`
3. `site_proposal`
4. `candidate_enumeration`
5. `primary_scoring`
6. `docking_selection`（可跳过 docking 直接到 `specificity_filter`，见下方 docking skip 说明）
7. `docking_run`
8. `specificity_filter`（仅对按结合自由能排名前 y 名的候选运行）
9. `spatial_rank`
10. `final_report`

`ChatScreen.advance_to_step()` 会调用 `WorkflowEngine.transition_to()` 并保存状态；如果你看到状态推进异常，优先沿这条链检查。

### Primary scoring（rank_sum 展示）

`primary_scoring` 步骤的排序和展示与 `spatial_rank` 一致，使用 **rank_sum（各模型竞争排名之和，越小越好）**。快速路径（枚举时已产出预测）按 `cumulative_rank` 排序；回退路径（`predict_batch`）从 `raw_outputs["individual"]` 提取各模型概率，调用 `domain.ranking.rank_sums_from_model_probs` 计算 rank_sum 后排序。两条路径均以 `#rank {candidate_id}: rank_sum=..., P=...` 格式展示。

intake step 内部包含 PDB 输入子流程（`tui/steps/pdb_intake.py`），当用户提供 PDB ID 时会自动触发 PDB 下载、解析、链/配体选择和 LLM 语义审查。这是 intake step 内部的分支，不是独立的 workflow step。

### Docking skip 路径

当 docking 不可用（Vina 未安装或配置禁用）时，`docking_selection` step 可直接跳转到 `specificity_filter`，跳过 `docking_run`。`DOCKING_SELECTION → SPECIFICITY_FILTER` 转换已在 `TRANSITIONS` 中注册。TUI 层通过 `_is_docking_enabled()` 检测可用性，`_skip()` 执行跳转。跳过后 specificity filter 会对全部候选运行（无亲和力筛选）。

### Docking selection 阶段流

`DockingSelectionHandler`（`tui/steps/docking/_handler.py`）通过 mixin 组合实现多阶段 UI：
1. **Phase 1 — 策略表单**（`_StrategyMixin`）：设置 top_k、affinity_top_k、exhaustiveness 等 Vina 参数。
2. **Phase 1.5 — 突变比例过滤**（`_FilterMixin`，`_filter.py`）：根据 `mutation_ratio`（0.0–1.0）筛选候选，保留突变比例 ≥ 阈值的候选。无 `confirmed_mutation_sites` 时自动跳过。默认值从 intake LLM 提取或 1.0（全部位点必须突变）。
3. **Phase 2 — 来源选择**（`_SourceMixin`）：手动上传 / RNAComposer / MOE。

`mutation_ratio` 流经 intake LLM → `IntakeContext.mutation_ratio` → `DockingRecommendationContext.mutation_ratio` → `_filtered_top_k_bundle()` 在 source 和 structures 阶段过滤候选。`MutationRatioPanel`（Input-based，无 Slider）实时显示剩余候选数。`affinity_top_k` 在过滤后自动 clamp 到剩余候选数。`Mutation.position` 和 `confirmed_mutation_sites` 均为 0-based。

当 MOE 可用时，docking source 面板额外显示两个选项：RNAComposer + MOE（自动获取 RNA 结构后 MOE 处理）和 MOE only（用户上传 RNA PDB 后 MOE 处理）。MOE 处理完成后走与现有路径相同的 Vina docking、spatial_rank 等后续步骤。

### Pose-based spatial ranking（论文 Section 3.4.3）

`docking_run` 在每个成功的 `DockingResult.raw_outputs` 中写入 `output_pdbqt` / `receptor_pdbqt` / `ligand_pdbqt` 路径（断点续跑结果同样补 `output_pdbqt` / `receptor_pdbqt`）。`spatial_rank` step 把这些 `docking_results` 传给 `SpatialRankAdapter.rank_batch`：

- **pose 模式**（`raw_outputs.mode = "pose_rule_match"`）：对每个候选解析受体碱基与第一个 pose 原子，将靶标分子的官能团（SMARTS 命中的 RDKit 重原子索引，滤掉氢后映射到 pose 重原子）与该官能团"期望碱基"（矩阵中概率最高的碱基类型）做 4.0 Å 接触计数，得到 `interaction_count`。排名 = `interaction_rank`（competition/1224，count 降序）+ `docking_rank`（dense/1223，亲和力升序、None 最差），按 `rank_sum` 升序、再 docking_score、再稳定输入序定最终 `rank`。原子顺序映射依赖 meeko 是否保留 RDKit 重原子序，`raw_outputs.atom_map_reliable` 通过重原子数一致性给出可靠性提示（不阻断计算）。
- **no_pose**：候选无可用 pose 文件时标 `raw_outputs.mode = "no_pose"`，以 count=0/score=None 参与联合排名。
- **sequence_fallback**：无 `docking_results` 时回退到序列组成加权评分（`raw_outputs.mode = "sequence_fallback"`）。

### 特异性硬门控

`spatial_rank` step 在筛选候选时排除 specificity 结果为 `removed` 的候选，UI 显示被排除计数。`final_report` 的 `build_report_context` 同步过滤这些候选并在 `screening_overview.specificity_excluded_from_docked_count` 给出数量，确定性 Markdown 报告中显示一行排除说明。

## 6. Predictor 集成事实

预测能力内聚在 `aptgent` 包内，predictor runtime 通过子进程运行。在默认的单环境安装中，所有依赖（包括 RDKit、torch、xgboost）都在同一个 conda 环境中，predictor 直接使用当前 Python 执行。如需隔离环境，可通过 `tools.toml` 中的 `conda_env` / `conda_python` 配置。

对预测功能做修改时，通常需要同时检查：

- `aptgent/aptgent/adapters/predictor.py`
- `aptgent/aptgent/predictor_runtime/runner.py`
- `aptgent/aptgent/predictor_runtime/predictor.py`
- `aptgent/aptgent/predictor_runtime/features.py`
- `aptgent/aptgent/predictor_runtime/cuda.py`
- `aptgent/aptgent/predictor_runtime/paths.py`（模型目录默认路径解析）
- `aptgent/aptgent/predictor_runtime/descriptor_schema.py`（规范化 RDKit 描述子名称列表，保证特征维度与训练模型一致）
- `aptgent/aptgent/resources/predictor_models/`

当前 predictor runtime 中的 ensemble 规则是严格规则：只有所有模型都预测为 `1`，ensemble label 才为 `1`。不要把旧文档或历史措辞当作真实实现来源，真实行为以代码为准。

`aptgent doctor` 含描述子环境守护（`cli/doctor.py:_check_feature_dimensions`）：加载一个 bundled 模型读取其 `n_features_in_`，与当前 `features.py` 的 k-mer 维度 + `_DESCRIPTOR_FUNCS` 长度比对。不匹配报 `feature_mismatch`（通常是 RDKit 版本漂移改变了描述子集合——应对齐训练时的 RDKit 版本，不要改描述子过滤）；缺依赖/无可比模型时优雅 `skipped`，不阻塞其他检查。

### mutation-batch 加速路径

`EnsembleAdapter.predict_mutation_batch()` 提供了大空间突变筛选的加速管线，通过 `runner.py mutation-batch` 子命令以子进程方式运行。子进程 stdout 使用行式 JSON 协议（`ready` / `progress` / `hit` / `done` / `error`），stdin 接受 `cancel` 取消信号。

加速技术包括：
- 描述子预计算（SMILES → 209 维 RDKit 描述子只算一次，跨所有 mutant tile）
- 向量化 k-mer（base-4 编码 + offset bincount）
- 动态模型校准（采 64 个 mutant 确定最优模型顺序）
- 级联早退过滤（每个模型只处理上一模型的幸存者）
- 分块枚举（65536 为块，纯 NumPy 字节操作生成 mutant）
- CUDA 加速（PyTorch RNN/biRNN `.to("cuda")`，XGBoost `DMatrix(device="cuda")`）
- k-mer 缓存（`build_kmer_cache` 预计算所有 k 值的归一化 k-mer 计数矩阵，`assemble_features_from_cache` 按模型需要的 k 值列选取并拼接描述子，避免每个模型独立重复 k-mer index / bincount 计算）

`EnumerationHandler`（`tui/steps/enumeration.py`）自动检测 adapter 是否有 `predict_mutation_batch` 方法来决定走加速路径还是慢速回退路径。只保留阳性命中（positives-only）写入 `scored_candidates.jsonl`。配置见 `workflow.toml` 的 `[enumeration]` 下 `sub_batch_size` 和 `progress_every`。

`predict_mutation_batch()` 支持 `skip_first` 参数，用于在部分运行中断后从上次进度恢复。实际的枚举进度（`done_count`）被持久化到 `scored_candidates.jsonl` 的头部元数据中；恢复时 `skip_first` 会从此元数据读取，而非从 JSONL 行数推断（因为 JSONL 只包含阳性命中，数量远少于总枚举空间）。取消或超时时，`_update_meta_done_count()` 会用最新进度更新头部。

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

`SpecificityHandler`（`tui/steps/specificity.py`）通过 mixin 组合（`SpecificityAnalogMixin`、`SpecificityPanelMixin`、`SpecificityProgressMixin` + `JobAttachMixin`），`JOB_STEP="specificity_filter"`；analog 选择完成后通过 `attach_or_spawn_job()` 启动 detached job runner（`_run_specificity` in `jobs/runner/specificity.py`）。runner 持续维护 `runs/<id>/artifacts/specificity_results.jsonl`（首行为 meta，其余按 candidate 写入 kept/removed/failed_analogs），断点续跑时通过 meta 匹配 + `skip_pairs` 把已完成的 `(target_idx, candidate_id)` 让子进程跳过。

UI 上 `ProgressBubble` 与 candidate enumeration 完全一致，信息行格式为 `Progress: X/Y | Kept: K | Removed: R | Target: <name>`。

## 7. 配置与环境注意事项

配置文件位于 `aptgent/aptgent/config/`：

- `workflow.toml`：workflow 参数（enumeration、docking）与 `runs_dir`
- `tools.toml`：外部工具路径（RNAfold、Vina）、预测器模型目录、PDB 下载配置、RNAComposer 轮询超时（`max_poll_seconds`、`poll_interval_seconds`）
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

- `test_bootstrap_config.py`：配置加载与环境变量展开测试
- `test_bootstrap_container.py`：依赖装配（`AppRuntime` + `build_runtime()`）测试
- `test_cli_doctor.py`：环境诊断命令测试
- `test_domain_models.py`：domain 层数据模型测试
- `test_domain_ranking.py`：dense ranking 与 rank_sum 计算测试
- `test_skill_base.py`：skill 基类与注册表测试
- `test_workflow_state.py`：workflow 状态模型测试
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
- `test_tui_job_progress.py`：TUI detached job 进度追踪测试
- `test_tui_app_navigation.py`、`test_tui_chat_widgets.py`、`test_tui_docking_selection.py`、`test_tui_docking_run.py`、`test_tui_intake_pdb.py`、`test_tui_scoring_retry.py`、`test_tui_secondary_structure.py`、`test_tui_site_proposal.py`、`test_tui_specificity.py`：TUI 行为测试
- `test_tui_markdown_theme.py`：chat markdown 主题测试
- `test_enumeration_ui.py`：枚举步骤 UI 测试
- `test_pdb_analysis.py`：PDB 分析 adapter 测试
- `test_spatial_rank.py`：空间排序测试（PDBQT 解析、官能团→pose 重原子映射、接触计数、competition/dense 排名、论文 Table 2 复现、no_pose / atom_map_reliable 标记、sequence fallback 与 pose 分发）
- `test_tui_report.py`：最终 Markdown 报告上下文、fallback 展示与导出测试
- `test_receptor_prep.py`：受体 PDBQT 准备 adapter 测试
- `test_rnacomposer_adapter.py`：RNAComposer adapter 测试
- `test_protocol_cancel.py`、`test_protocol_line_json.py`、`test_protocol_subprocess_stream.py`：protocol 层取消、JSONL、子进程流测试
- `test_domain_text_utils.py`：domain 文本工具测试
- `test_docking_skip_path.py`：docking skip 路径测试
- `test_moe_prep.py`：MOE 受体准备 adapter 测试
- `test_tui_docking_moe.py`：MOE 源选择与 worker 测试
- `test_mutation_ratio_filter.py`：突变比例过滤逻辑与辅助函数测试

修改以下内容后，至少应重新检查对应测试：

- 配置加载 / 环境变量展开 → `test_bootstrap_config.py`
- 依赖装配 / AppRuntime → `test_bootstrap_container.py`
- 环境诊断命令 → `test_cli_doctor.py`
- domain 数据模型 → `test_domain_models.py`、`test_domain_ranking.py`（含 exact-float dense ranking）
- skill 基类 / 注册表 → `test_skill_base.py`
- workflow 状态模型 → `test_workflow_state.py`
- workflow step / 状态流转 → `test_workflow_engine.py`、`test_persistence.py`（含 `STEP_ORDER` 公开常量）
- LLM skill 行为 / 输出校验 → `test_skills.py`、`test_llm_client_retry.py`、`test_llm_client_payloads.py`、`test_llm_result_validation.py`、`test_workflow_context_helpers.py`
- predictor / 特征提取 → `test_predictor_adapter_mutation_protocol_*.py`、`test_predictor_feature_matrix_batch.py`、`test_predictor_mutation_batch_runtime.py`、`test_predictor_specificity_batch_protocol.py`、`test_tui_enumeration_acceleration.py`、`test_feature_matrix.py`、`test_predictor_adapter.py`（含 k-mer cache `build_kmer_cache` / `assemble_features_from_cache`）
- TUI step handler / UI → `test_tui_*.py`、`test_enumeration_ui.py`、`test_tui_markdown_theme.py`
- PDB / 结构分析 → `test_pdb_analysis.py`
- 受体准备 → `test_receptor_prep.py`
- RNAComposer → `test_rnacomposer_adapter.py`
- 空间排序 → `test_spatial_rank.py`
- detached job 系统 → `test_jobs_*.py`、`test_tui_job_mixin.py`、`test_tui_job_progress.py`（含 `JobProgressTracker` dataclass）
- resume / STEP_ORDER 动态推导 → `test_tui_app_navigation.py`
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

- `llm.toml` 中已不含明文 API key。密钥通过 `aptgent.local.toml`（项目根目录，gitignored）或 `GLM_API_KEY` 环境变量提供。不要在 bundled 配置中重新引入明文密钥。
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
