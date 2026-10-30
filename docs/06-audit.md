# 第二次全面审查（2026-10-30）

## 审查范围与版本

对照《考核规则.md》《项目要求.md》逐项复核，审查起点为本地提交 `2c9dbbae1f95d98d38af49c6418a12a0515404b8`。起点所有跟踪文件 SHA256 和开始时间见 [before-sha256.json](audit/before-sha256.json)。原始要求保持不变；在 Git 工作副本修订，原提交保留。

最终运行和语义复核结果见本文件后续章节。

## 已发现并修复的问题

| 问题 | 原行为与影响 | 修复 |
|---|---|---|
| 未恢复候选读取失败仍允许 answered | D02失败、D01成功后可只答30天，可能忽略潜在冲突 | 未恢复工具错误同时阻断answered和insufficient_evidence |
| 空白答案/决策摘要 | 空格长度非零，被当作有效交付或依据 | strip后校验非空 |
| 错路或畸形工具成功响应 | 请求D02却返回D01仍登记；results缺失仍当成功检索 | 校验请求身份、结果结构与类型 |
| 异常脱敏自身抛错 | code=[]或hint={}导致不可哈希类型异常 | 类型检查后再白名单匹配，不泄露原异常内容 |
| 冲突查证路径误判 | 补查后重读原文，被误认为没有补查 | 以首次集齐所需原文后是否补查判定 |
| 验收只认固定编号、单一引用集合 | 新场景检查不生效；合法多引用被误判 | 增加声明式行为与引用集合，拒绝拼错/未知检查键 |
| 故障恢复检查过弱 | 搜索失败后无关读取成功也算恢复 | 搜索须恢复搜索；读取须恢复同一片段 |
| 证据一致性仅人工核对 | 输入、摘要、stdout与原文缺少自动交叉校验 | 新增运行级核验，包括动作链与实际退出码 |

原版新增核心回归：7个测试、9个子测试失败、2个错误，[原始输出](../examples/audit-baseline/regression-before-stderr.txt)及[命令/退出码](../examples/audit-baseline/regression-before-process.json)。这些是确定性对抗测试，不冒充真实模型曾犯错。

原版新增评估回归7项失败，其中1项是原有路径误判，其余是尚未实现的新声明式检查，见[日志](../examples/audit-baseline/evaluation-before-stderr.txt)。不把所有新增功能都称为旧程序缺陷。

## 修复前补充真实运行

修复前运行9个新产品/读取故障用例：[原始汇总](../examples/audit-baseline/live-extra/summary.json)。旧评估器自动7/9：

- A04：原文仅支持MP4，不能确认8K；模型正确报告资料不足并引用D05。
- A09：引用P103明确替代条款，同时引用旧P101，正确回答12人。

这两项失败是评估器限制合法引用集合造成的假阴性，不是模型事实错误。原始checks不改写。新增A10进一步验证冲突候选读取失败后恢复、再查证的完整路径。

## 保守策略与局限

- 任何未恢复工具错误都会阻断answered，包括模型误读不存在ID后转读其他文档。这可能降低可用性，但不会无依据认定失败证据无关。重试同一片段成功可解除该片段错误。
- 自动校验只证明引用来源和原文一致，不保证所有答案语义必然成立。真实样本仍逐项由与实现分工的AI审阅，不冒充真人评审或额外模型裁判。
- 提示词已移除D01/D02的30/15数字示例；新产品样本没有加入模型提示。但样本由AI根据要求设计，不是外部盲测。
- 小样本单轮通过不证明生产可靠性、任意改写均可召回，或检索改进具有统计收益。
- GitHub地址、题号、评审权限尚未提供。本地功能验收可验证，不等于已完成远程提交规范。

## 当前版本最终验证结果

- **109/109工程测试通过**：[原始日志](../examples/audit-final-v3/verification/01-stderr.txt)、[实际命令和退出码](../examples/audit-final-v3/verification/verification.json)。
- **原必验10/10真实运行通过**：[汇总](../examples/audit-final-v3/required/summary.json)。
- **扩展10/10真实运行通过**：[汇总](../examples/audit-final-v3/extended/summary.json)。
- **Mock10/10流程测试通过**：[汇总](../examples/audit-final-v3/verification/mock/summary.json)，不计入真实模型结果。
- 20项真实样本均完成[逐条语义复核](audit/live-semantic-review.md)，83次决策，其中3次JSON格式错误反馈后恢复，不宣称零格式错误。
- 20项模式均为live、批次及单次源码摘要一致，与当前源码匹配：

```text
a1d89f0df39a1468846d554468f2958f7ea2c82e568f454217d29c4e6a7e6369
```

两个批次均为同一源码；真实命令的stdout/stderr、开始/结束时间和退出码见 [commands目录](../examples/audit-final-v3/commands/)。未回退Mock，未覆盖旧运行。

### 六项必验与真实证据对应表

| 必验点 | 当前真实运行 | 核心观察 |
|---|---|---|
| 明确答案 | [T01输出](../examples/audit-final-v3/required/T01/output.json) / [Trace](../examples/audit-final-v3/required/T01/trace.jsonl)；[A01产品答案](../examples/audit-final-v3/extended/A01/output.json) | 30天和MP4均来自实际读取的原文 |
| 文档冲突 | [T02输出](../examples/audit-final-v3/required/T02/output.json) / [Trace](../examples/audit-final-v3/required/T02/trace.jsonl)；[A07非报销冲突](../examples/audit-final-v3/extended/A07/output.json) | 分别列出双方事实与引用，补查仍缺依据则追问，不凭日期裁决 |
| 资料外问题 | [T03输出](../examples/audit-final-v3/required/T03/output.json) / [Trace](../examples/audit-final-v3/required/T03/trace.jsonl)；[A04噪声候选](../examples/audit-final-v3/extended/A04/output.json) | 区分没有命中与命中资料不支持8K，不推断支持或不支持 |
| 改写后的相似问题 | [T04输出](../examples/audit-final-v3/required/T04/output.json) / [Trace](../examples/audit-final-v3/required/T04/trace.jsonl)；[A02新改写](../examples/audit-final-v3/extended/A02/output.json) | 不使用完整问题映射，答案仍对应30天/8名协作者 |
| 上下文追问 | [T05输入](../examples/audit-final-v3/required/T05/input.json) / [Trace](../examples/audit-final-v3/required/T05/trace.jsonl)；[A03产品历史](../examples/audit-final-v3/extended/A03/output.json) | 利用历史解析指代，但重新检索、读取，而非照抄历史回答 |
| 工具失败 | [T06恢复Trace](../examples/audit-final-v3/required/T06/trace.jsonl)、[T07持续失败](../examples/audit-final-v3/required/T07/output.json)、[A05读取恢复](../examples/audit-final-v3/extended/A05/trace.jsonl)、[A06持续读取失败](../examples/audit-final-v3/extended/A06/output.json)、[A10冲突与故障](../examples/audit-final-v3/extended/A10/trace.jsonl) | 实际收到错误后模型调整；持续失败明确未完成，不能拿摘要作已核验原文 |

### 其他考核规则逐项核对

| 规则 | 结论与证据 |
|---|---|
| 业务问题、范围、成功标准 | 已有docs/01-requirements.md和合成制度/产品材料 |
| 3小时优先核心链路、记录用时/未完成 | 已记录首次实施与本轮审查区间，见work-log.md；没有将AI并行墙钟时间冒充个人工时 |
| 技术取舍、框架职责 | 原生Python标准库，无框架依赖；版本与取舍见README、02-solution.md |
| 可复制CLI运行，不以截图替代 | run.py、README提供单问/批量/测试命令，实际命令保存于examples |
| 真实模型与离线Mock分离 | live模式实际发请求，Mock明确标识且不加载密钥；没有静默回退 |
| 模型→工具→观察→下一动作 | T01正常、T02冲突、T06失败恢复形成不同真实路径；业务选择由模型产生 |
| 至少两条执行路径及完整Trace | 当前20条，包含步骤、参数、观察、下一动作、简要依据与耗时，不提交内部思维 |
| 执行步数上限与未完成状态 | [T10最终Trace](../examples/audit-final-v3/required/T10/trace.jsonl)真实执行1步检索后引擎step_limit；持续动作的确定性测试另证明硬上限 |
| 至少3组输入/实际输出/记录 | 当前20组包含正常、资料不足与故障；每组有input/output/trace/checks/process/stdout/stderr |
| 替换资料后答案和动作改变 | T01→T08改变30为45；T01→T09新增冲突改变动作与状态；A02→A08改8为20、A02→A07改变冲突路径，见[对比检查](audit/contrast-checks.json) |
| 显式依据可消除冲突 | [A09输出](../examples/audit-final-v3/extended/A09/output.json)及[Trace](../examples/audit-final-v3/extended/A09/trace.jsonl)：P103明确优先/替代才采用12人，不单凭日期 |
| README/src/tests/examples/data/docs五文档/依赖/env模板 | 全部存在，文档链接在交付前复核；无第三方依赖 |
| AI辅助、个人修改、复盘真实 | 已如实区分AI实现/测试与用户提出要求、提供本地配置；没有虚构个人贡献 |
| 密钥及隐私 | .env被忽略、未跟踪；提交前按实际密钥扫描跟踪文件。语料全部合成，未提交业务隐私资料；日志含本机路径，公开前仍建议审阅环境元信息 |
| 题号、GitHub URL、最终SHA、私有访问权限 | **本地提交可完成；题号/GitHub URL/评审权限未提供，远程提交尚未完成** |

## 本轮迭代中的真实失败与误判

1. `audit-final`：19/20自动通过。T04虽然给出正确30天，却将未问的具体日历日期作为阻断、返回needs_clarification，并含无依据“现行”。修正通用回答粒度与出处表述，不修改T04的answered预期。
2. `audit-final-v2`：19/20自动通过。T04已修复；T10模型在唯一允许步骤主动finish incomplete、明确预算不足，被硬编码reason=step_limit误判。考核要求是到达预算明确未完成，并不要求模型必须先做工具动作才停止。评估允许经校验的最后一步主动未完成，仍拒绝已回答/超预算，并保留引擎强制上限测试。没有改日志或逼模型走固定路径。
3. `audit-final-v3`：20/20自动及语义复核通过，本轮T10实际为引擎强制step_limit。主动停止与强制截断是不同证据，不能混称。
4. 中间两次工程验证的单项失败是追加A10后测试资料数量仍写9造成的fixture维护遗漏，日志保留；将资料ID集合与唯一性同步为A01～A10后，最终109项全部通过。

## 复跑、差异与恢复

```bash
python3 run.py evaluate --mode live --output examples/local/review-required
python3 run.py evaluate --mode live --cases data/audit_cases.json --output examples/local/review-extended
python3 scripts/verify.py --output examples/local/review-verification
git diff 2c9dbba HEAD -- src tests data docs README.md
```

输出目录必须不存在。完整测试会产生模型调用费用；本地Mock复跑不访问模型。恢复前版本可在另一空目录运行 `git worktree add --detach ../knowledge-agent-pre-audit 2c9dbba`。已在额外临时工作树核对旧版本342个文件哈希，见[恢复验证](audit/recovery-verification.json)，最终修改版和运行记录仍保留。

## 尚待用户或后续工作

1. 提供题号、GitHub仓库及评审账号/权限，才能完成提交规范；没有擅自创建或上传远程仓库。
2. 可用性边界：错误ID等未恢复失败也会保守阻断完成；暂无可靠“此失败与问题无关”的自动判定。
3. 检索改进的独立留出实验、复杂多段资料、生产权限/部署、安全与长期稳定性均未验证，不属于本轮已完成承诺。
4. 语义校验不是通用证明器；自动通过率仅指这些固定样本和声明的检查。原文引用准确仍可能被不当解释，接入真实业务前需要更大规模审查。
