# 真实模型运行的独立语义复核

复核日期：2026-10-30（Asia/Shanghai）。复核者：与实现分工的 AI 审阅代理；这是逐条人工式检查，不是额外的独立模型裁判或真人评审。

## 方法与边界

本复核逐项阅读实际 `output.json` 和 `trace.jsonl`，核对工具读取的原文是否支持最终结论、冲突是否得到查证、错误是否被恰当区分。自动断言结果另见各批次 `summary.json`。不把“引用是原文子串”直接等同于“结论获得语义支持”，不把 Mock 结果计入真实模型效果。

模型标识来自实际运行元信息：`deepseek-flash`。该标识由配置的接口报告/请求，不是对服务商内部模型身份的独立证明。固定合成小样本的单次运行不能估计生产准确率或稳定性。

## 首轮 live-v1：8/10 自动检查通过，保留失败

证据：[首轮汇总](../examples/live-v1/summary.json)。首轮存在较多 `invalid_model_output` 格式错误；部分经重试修复，T03、T09 耗尽步数。不能以最终有安全兜底为由将这两项判为成功。

| 用例 | 实际结果与语义复核 | 证据 |
|---|---|---|
| T01 明确答案 | 4 步，含 1 次格式错误；最终 30 天与 D01 原文一致，准确注明范围未知。主结论有支持。 | [输出](../examples/live-v1/T01/output.json) · [Trace](../examples/live-v1/T01/trace.jsonl) |
| T02 文档冲突 | 5 步：检索 → 读 D01 → 读 D02 → 补搜范围/优先级/废止 → 追问。双方 30/15 天原文均引用，未擅自按新日期或较短期限裁决。符合冲突要求。 | [输出](../examples/live-v1/T02/output.json) · [Trace](../examples/live-v1/T02/trace.jsonl) |
| T03 资料外问题 | 5 次空检索后连续 5 次格式错误，最终 `incomplete/step_limit`。没有编造停车制度，但未正常返回资料不足，验收失败。 | [输出](../examples/live-v1/T03/output.json) · [Trace](../examples/live-v1/T03/trace.jsonl) |
| T04 改写相似问题 | 10 步：识别报销期限，读取 30 天原文，并补搜起算规则；6 次格式错误后才成功。期限主结论有支持，但“现行”一词没有生效状态证据，属于不必要的措辞外推；不能仅凭日期宣称制度当前有效。 | [输出](../examples/live-v1/T04/output.json) · [Trace](../examples/live-v1/T04/trace.jsonl) |
| T05 上下文追问 | 7 步，含 4 次格式错误。将“那期限呢”解析为报销期限后重新检索读取，未把历史助手消息当证据。30 天与原文一致。 | [输出](../examples/live-v1/T05/output.json) · [Trace](../examples/live-v1/T05/trace.jsonl) |
| T06 短暂工具失败 | 首次检索报 `TOOL_UNAVAILABLE`，模型调整查询后恢复并读取 D01；最终回答 30 天。9 步中有 5 次格式错误，恢复链成立但格式稳定性差。 | [输出](../examples/live-v1/T06/output.json) · [Trace](../examples/live-v1/T06/trace.jsonl) |
| T07 持续工具失败 | 三次工具错误后模型结束，另含 2 次格式错误。返回 `incomplete`、空引用，准确说明无法取得资料，而不是声称制度不存在。符合失败停止要求。 | [输出](../examples/live-v1/T07/output.json) · [Trace](../examples/live-v1/T07/trace.jsonl) |
| T08 文档内容替换 | 4 步，含 1 次格式错误。答案和引用均改为 45 天，版本日期同步为 2026-03-01，无旧 30 天结论残留。 | [输出](../examples/live-v1/T08/output.json) · [Trace](../examples/live-v1/T08/trace.jsonl) |
| T09 新增冲突 | 正确读取双方、补充检索，但之后 6 次格式错误耗尽预算，未交付冲突说明与追问。动态动作改变已观察到，最终状态验收失败。 | [输出](../examples/live-v1/T09/output.json) · [Trace](../examples/live-v1/T09/trace.jsonl) |
| T10 步数上限 | 预算 1 步，仅检索即停止，明确 `incomplete/step_limit`，未将摘要包装成已完成回答。符合预算控制要求。 | [输出](../examples/live-v1/T10/output.json) · [Trace](../examples/live-v1/T10/trace.jsonl) |

首轮缺陷不能靠放宽通过条件掩盖。资料外与新增冲突场景需在修复后重跑；应保留首轮记录，同时比较新运行的格式错误数、动作路径与最终答案。

## 冻结版本 live-v2：10/10 自动检查通过，逐项语义复核完成

证据：[第二轮汇总](../examples/live-v2/summary.json)。独立检查全部 10 条输出，`metadata.source_sha256` 均为 `1d3e43dd828fbc0b63c7c891058b4bedadcc9bf5a1b0c623dd8dcc5eacb5dbf0`。首轮处于迭代期，包含未记录源代码哈希的运行，不能作为统一冻结版本的严格对照。

| 用例 | 观察到的动作与结论 | 语义判断及证据 |
|---|---|---|
| T01 明确答案 | 3 步，检索 → 读 D01 → 回答 30 天；起算点和范围标为未知。 | 主结论直接由原文支持，无擅自补充起算点。[输出](../examples/live-v2/T01/output.json) · [Trace](../examples/live-v2/T01/trace.jsonl) |
| T02 文档冲突 | 5 步，读取双方原文，随后补搜适用范围、优先级和替代关系，最终 `needs_clarification`。 | 引用正确地分别支持 30 天和 15 天；明确拒绝以较新日期或较短期限擅自裁决。[输出](../examples/live-v2/T02/output.json) · [Trace](../examples/live-v2/T02/trace.jsonl) |
| T03 资料外问题 | 4 步；三次不同查询，命中过请假/设备申领的噪声候选，但识别为不相关，最终 `insufficient_evidence`。 | 没有把无关流程用于停车申请，没有虚构引用；回答限定于未检索到依据，不是宣称停车制度绝不存在。[输出](../examples/live-v2/T03/output.json) · [Trace](../examples/live-v2/T03/trace.jsonl) |
| T04 改写相似问题 | 4 步；从“费用最迟什么时候能报”转为报销时限，读原文后补搜起算规则，回答 30 天。 | 30 天有支持；未自行推定发票日等起算条件，也未复现首轮“现行”的外推措辞。附加追问不影响已回答的期限事实。[输出](../examples/live-v2/T04/output.json) · [Trace](../examples/live-v2/T04/trace.jsonl) |
| T05 上下文追问 | 4 步；根据用户历史解析指代，实际检索、读取、补搜后回答 30 天。 | 引用来源是本轮 D01，不是历史消息；起算点、范围和逾期处理均保留为缺口。[输出](../examples/live-v2/T05/output.json) · [Trace](../examples/live-v2/T05/trace.jsonl) |
| T06 短暂工具失败 | 5 步；首次检索失败，模型改查询后恢复，读取 D01，再检索可能的冲突，最后回答。 | 错误确实先于恢复；30 天与已读原文一致。没有把失败误当无资料。[输出](../examples/live-v2/T06/output.json) · [Trace](../examples/live-v2/T06/trace.jsonl) |
| T07 持续工具失败 | 4 步；三次检索故障后主动 `finish`，返回 `incomplete`、空引用及缺口。 | 明确解释工具不可用，没有凭常识回答期限；停止早于 10 步上限。[输出](../examples/live-v2/T07/output.json) · [Trace](../examples/live-v2/T07/trace.jsonl) |
| T08 文档替换 | 3 步，答案及引用同时变为 45 天、版本 2026-03-01。 | 与变更原文一致；未固守提示词示例中的 30 天，没有旧答案残留。[输出](../examples/live-v2/T08/output.json) · [Trace](../examples/live-v2/T08/trace.jsonl) |
| T09 新增冲突 | 5 步，检索候选中有额外无关文档，模型选择读取 D01/D02 后补搜，最终请求确认。 | 与 T01 的正常路径相比，多读冲突原文、多一次查证，状态由 `answered` 改为 `needs_clarification`；行为改变与资料改变相符。[输出](../examples/live-v2/T09/output.json) · [Trace](../examples/live-v2/T09/trace.jsonl) |
| T10 预算上限 | 仅 1 步检索，随后 `incomplete/step_limit`。 | 无原文读取即无引用和事实答案，预算控制准确生效。[输出](../examples/live-v2/T10/output.json) · [Trace](../examples/live-v2/T10/trace.jsonl) |

本轮 10 条记录共 38 个决策步骤，未观察到 `invalid_model_output`；首轮实际记录为 66 步、30 次该错误。以上是这两批运行的观测，不是稳定性置信区间，也不能将差异全部归因于某个单独改动。

**限定结论：**本轮固定合成样本覆盖了明确答案、文档冲突、资料外问题、改写相似问题、上下文追问、工具失败全部六个要求；同时验证了资料替换和预算上限。已保存至少正常/冲突/故障恢复三种真实模型动态路径。未发现第二轮这些答案的关键事实与其引用相矛盾，未发现冲突被擅自裁决。仍不等于任何问题都能可靠回答或达到生产可用水平。

## 核心执行器独立回归

执行命令：`PYTHONPATH=src python3 -m unittest discover -s tests -p test_agent.py -v`。

初版 18 项契约测试通过。独立审计随后补充两项回归，实际发现：

1. 空白字符串可作为原文子串被错误接受为引用。
2. 原文读取失败可被无关的成功检索清除，最终把工具故障误报成资料不足。

实现修复后，20/20 项核心回归通过（退出码 0）。这些测试证明动作白名单、参数约束、引用来源/版本校验、错误隔离、历史角色约束与步数上限，不证明模型会可靠理解所有业务语义。

## 尚不能外推的结论

- 未覆盖大规模真实制度库、长历史、多部门复杂适用范围、权限控制或真实生产故障。
- T02 与 T09 使用同一冲突数据、同一问题，不是两个独立语义难题；T09 主要用于与 T01 做受控资料变化比较。
- 文档子串校验不能自动发现“引用正确但结论错误”，本文件仅复核已保存的这些输出。
- 补充检索没有找到依据，不等于知识库中绝不存在依据；词法检索存在召回限制。
- 提示词包含 D01/D02、30/15 天的题目示例；这些冲突用例不是严格保留的盲测，45 天文档替换仅提供有限的反硬编码检查。
- 此处没有测量改进前后检索指标的因果提升，也没有声称泛化准确率。
