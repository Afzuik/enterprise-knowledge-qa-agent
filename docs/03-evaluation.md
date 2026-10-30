# 03 测试、实际结果与限制

## 结论范围

2026-10-30（Asia/Shanghai）本机 macOS / Python 3.9.6 验证：73 项工程测试通过，最终离线流程10/10、第二轮真实模型固定验收10/10。首轮真实模型8/10，失败保留。这里的10是具体用例数，不是10个独立业务领域；T02/T09同题用于受控资料变化对比。

模型请求标识为 `deepseek-flash`，使用用户本地配置的兼容接口；没有独立验证服务商内部模型身份或供应商其他接口。未提交基础地址或密钥。真实模型结果不依赖Mock。

## 可复核证据

- [73项测试原始输出](../examples/verification/01-stderr.txt)
- [离线验证命令、输入环境覆盖与退出码](../examples/verification/verification.json)
- [最终Mock汇总](../examples/verification/mock/summary.json)：只证明流程
- [真实首轮汇总](../examples/live-v1/summary.json)：保留失败
- [真实第二轮汇总](../examples/live-v2/summary.json)
- [逐条语义复核](live-review.md)：与实现分工的AI审阅，不是真人评审或另一个模型端点评分

每个用例文件夹均包含输入、实际输出、Trace、断言和子进程的原始标准输出/错误与退出码。批量命令：

```bash
python3 run.py evaluate --mode live --output examples/live-v2
python3 scripts/verify.py --output examples/verification
```

上述目录已存在，直接重跑会拒绝覆盖；复跑请改为新的 `examples/local/...` 路径。README提供复制命令。

## 验收矩阵：第二轮实际结果

| 编号 | 输入场景与预期 | 实际状态 | 步数 | 证据 |
|---|---|---|---:|---|
| T01 | 只有D01，回答30天并引用 | answered，30天 | 3 | [输出](../examples/live-v2/T01/output.json) / [Trace](../examples/live-v2/T01/trace.jsonl) |
| T02 | D01/D02冲突，查证后引用双方并追问 | needs_clarification，30/15天均列出 | 5 | [输出](../examples/live-v2/T02/output.json) / [Trace](../examples/live-v2/T02/trace.jsonl) |
| T03 | 停车位问题，资料不含答案 | insufficient_evidence，无编造流程 | 4 | [输出](../examples/live-v2/T03/output.json) / [Trace](../examples/live-v2/T03/trace.jsonl) |
| T04 | 改写为“费用最迟什么时候能报” | answered，30天，并注明起算日缺口 | 4 | [输出](../examples/live-v2/T04/output.json) / [Trace](../examples/live-v2/T04/trace.jsonl) |
| T05 | 上文报销，追问“那期限呢” | answered，重新检索读取后答30天 | 4 | [输出](../examples/live-v2/T05/output.json) / [Trace](../examples/live-v2/T05/trace.jsonl) |
| T06 | 首次检索工具故障 | answered，实际观察失败后恢复 | 5 | [输出](../examples/live-v2/T06/output.json) / [Trace](../examples/live-v2/T06/trace.jsonl) |
| T07 | 检索工具持续故障 | incomplete，明确是故障不是无资料 | 4 | [输出](../examples/live-v2/T07/output.json) / [Trace](../examples/live-v2/T07/trace.jsonl) |
| T08 | 原文30天替换为45天 | answered，答案和引用均45天 | 3 | [输出](../examples/live-v2/T08/output.json) / [Trace](../examples/live-v2/T08/trace.jsonl) |
| T09 | 相比T01新增冲突文档 | needs_clarification，动作和状态改变 | 5 | [输出](../examples/live-v2/T09/output.json) / [Trace](../examples/live-v2/T09/trace.jsonl) |
| T10 | 最大1次决策 | incomplete，reason=step_limit | 1 | [输出](../examples/live-v2/T10/output.json) / [Trace](../examples/live-v2/T10/trace.jsonl) |

测试成功不意味着所有业务任务都应返回answered。T07/T10的预期就是明确未完成，其单问进程实际退出2，验收断言仍通过。

自动断言检查状态、数字边界、文档引用集合、成功读取的原文/版本、冲突后补充检索、追问、故障后恢复、文档变更和上限。数字检查不会把130当成30；但仍不能自动排除所有否定关系或语义矛盾，需语义复核。

## 修订前后与动态路径证据

- 首轮：66次决策，30次 `invalid_model_output`；T03/T09耗尽预算。T04虽最终回答正确，但曾无依据称“现行”，该措辞问题已在复核中保留。
- 第二轮：38次决策，0次格式错误；正常路径为 `search_docs → read_doc → finish`，冲突路径为 `search_docs → read_doc → read_doc → search_docs → finish`。
- 第二轮工具失败路径确有 `ok=false` 观察，随后由模型选择后续动作，不是执行器硬编码的自动重试。
- 修改内容：完整finish对象示例、结构化错误反馈、每步剩余预算、无资料检索停止指导；未放宽预期。
- 第一轮处于迭代期，未绑定统一源代码哈希；不作为严格受控的单因素实验。第二轮10个输出的源代码哈希均与最终运行代码一致：

```text
1d3e43dd828fbc0b63c7c891058b4bedadcc9bf5a1b0c623dd8dcc5eacb5dbf0
```

该摘要按文件名排序，依次哈希 `src/knowledge_agent/*.py` 的文件名和字节，算法见 `Agent.run`；语料摘要各自记录在metadata。README、测试或文档不属于该运行代码摘要，最终Git提交另固定全部交付文件。

## 工程回归范围

73项测试覆盖：动作与参数白名单、历史角色、预算、合法及伪造/空白引用、读取失败不会被无关成功掩盖、模型错误脱敏、HTTP协议和本机重定向阻断、配置解析、CLI隔离与不覆盖、检索变更及故障、批量验收边界。完整命令/原始输出在 `examples/verification/`。单元/HTTP适配测试使用确定性对象或本机HTTP服务器，不算真实模型行为证据。

## 未完成与风险

- 固定小样本、公开题目示例参与提示设计，非盲测；没有多次独立重复、生产准确率或显著性结论。
- 未完成基线与改进检索在独立留出集上的对比；新增改写回归不能替代该实验。
- 权限、生产部署、大语料、长对话、真实范围/优先级消歧、多供应商兼容与成本统计未验证。
- Prompt约束和引用子串校验不构成通用幻觉消除或提示注入安全保证。
- GitHub URL、题号、评审账号权限待用户补充；已完成的是本地项目与提交，未远程发布。
