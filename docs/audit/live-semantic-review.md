# 审计轮真实模型运行的独立语义复核

复核日期：2026-10-30（Asia/Shanghai）。复核角色：与实现分工的 AI 审阅代理。这里是逐项阅读本次保存的输入、输出、工具观察和动作记录，不是额外模型端点打分，也不是真人评审。

## 复核方法与范围

检查答案断言是否由本轮成功读取的原文支持、引用片段与版本是否对应、是否将摘要或相似主题误作依据、冲突有没有查证及擅自裁决、工具错误是否恢复或明确停止。自动断言之外独立阅读 Trace 的动作与观察关系。

模型请求标识为 `deepseek-flash`；该配置标识不是对服务商内部实际模型身份的独立证明。业务资料均为合成资料，工具故障由显式本地故障注入产生。本文件只评价已经保存的样本，不宣称模型没有其他幻觉、不证明生产稳定性或所有相似问法都可靠。

## 一、基线扩展测试的两项误判不是模型答错

原基线扩展汇总显示7/9，但 A04、A09 的失败只来自过窄的引用集合断言，不能写成这两个模型任务失败：

- **A04：资料不足也可以引用已查明的有限依据。** 实际回答明确说明 MP4 是文件格式，资料没有分辨率说明，不能推断支持或不支持8K；引用 D05 只是说明资料边界，不是拿 MP4 证明8K。旧断言强制引用集合为空，因而误判。[输出](../../examples/audit-baseline/live-extra/A04/output.json) · [Trace](../../examples/audit-baseline/live-extra/A04/trace.jsonl) · [旧断言](../../examples/audit-baseline/live-extra/A04/checks.json)
- **A09：引用历史冲突条款和优先适用条款是合理的。** 模型实际读取 P103 明示优先替代条款，读取 P101 历史8人条款，依据P103回答12人；多引用P101支持冲突历史不应判错。旧断言仅允许P103一个文档，因而误判。[输出](../../examples/audit-baseline/live-extra/A09/output.json) · [Trace](../../examples/audit-baseline/live-extra/A09/trace.jsonl) · [旧断言](../../examples/audit-baseline/live-extra/A09/checks.json)

修订为允许有语义依据的引用集合，不代表放弃引用核验：每条引用仍须来自本轮成功读取的对应原文；A09必须包含明示优先替代的P103证据。旧结果原样保留，不能把旧汇总覆盖成全通过。

## 二、首轮修复后审计：19/20，不掩盖 T04 失败

证据：[要求矩阵9/10](../../examples/audit-final/required/summary.json) · [扩展矩阵10/10](../../examples/audit-final/extended/summary.json)。两组20个输出均记录同一运行源码摘要：

```text
88f5cb4f58e28a53b210c986ed306c76bc4a800f4350c128e1aad8f78190e225
```

要求矩阵39步、扩展矩阵43步；后者A10有1次`invalid_json`，修复格式后继续执行，错误未被删除。

### 要求矩阵逐项复核

| 用例 | 实际状态 / 步数 | 语义判断 | 证据 |
|---|---|---|---|
| T01 明确答案 | answered / 4 | D01明确30天，回答仅据此给出期限并注明起算/范围缺口，引用支持结论。 | [输出](../../examples/audit-final/required/T01/output.json) · [Trace](../../examples/audit-final/required/T01/trace.jsonl) |
| T02 文档冲突 | needs_clarification / 5 | 读双方原文、补搜范围/优先/废止，列出30/15天并追问，没有按较新日期或较短天数选答案。 | [输出](../../examples/audit-final/required/T02/output.json) · [Trace](../../examples/audit-final/required/T02/trace.jsonl) |
| T03 资料外问题 | insufficient_evidence / 5 | 检索结果一度出现请假、设备等噪声，模型没有把它们拼成停车流程，正确说明没有停车依据。 | [输出](../../examples/audit-final/required/T03/output.json) · [Trace](../../examples/audit-final/required/T03/trace.jsonl) |
| T04 改写相似问题 | needs_clarification / 4，验收失败 | 30天主事实与引用正确，但将未问的具体日历截止日期作为阻断因素，未交付预期answered；还无依据称制度“现行”。这不是仅靠引用子串校验能发现的问题，保留失败并修提示。 | [输出](../../examples/audit-final/required/T04/output.json) · [Trace](../../examples/audit-final/required/T04/trace.jsonl) |
| T05 上下文追问 | answered / 4 | 将“那期限呢”理解为报销期限，重新检索读取并补查起算，回答30天而非信任历史助手。 | [输出](../../examples/audit-final/required/T05/output.json) · [Trace](../../examples/audit-final/required/T05/trace.jsonl) |
| T06 检索短暂失败 | answered / 4 | 实际观察检索错误，模型重试同一查询，成功读取D01后回答30天。 | [输出](../../examples/audit-final/required/T06/output.json) · [Trace](../../examples/audit-final/required/T06/trace.jsonl) |
| T07 检索持续失败 | incomplete / 4 | 三次错误后停止，明确工具不可用不等于知识库没有规定，空引用。 | [输出](../../examples/audit-final/required/T07/output.json) · [Trace](../../examples/audit-final/required/T07/trace.jsonl) |
| T08 原文替换 | answered / 3 | D01改为45天后，答案与原文引用同步变为45天，无旧30天残留。 | [输出](../../examples/audit-final/required/T08/output.json) · [Trace](../../examples/audit-final/required/T08/trace.jsonl) |
| T09 新增冲突 | needs_clarification / 5 | 相比T01新增D02后读取双方、补搜并改变为追问状态，动态路径改变有直接证据。 | [输出](../../examples/audit-final/required/T09/output.json) · [Trace](../../examples/audit-final/required/T09/trace.jsonl) |
| T10 步数上限 | incomplete / 1 | 仅完成检索即达到预算，明确step_limit，无摘要冒充最终引用。 | [输出](../../examples/audit-final/required/T10/output.json) · [Trace](../../examples/audit-final/required/T10/trace.jsonl) |

### 扩展矩阵逐项复核

| 用例 | 实际状态 / 步数 | 语义判断 | 证据 |
|---|---|---|---|
| A01 产品FAQ | answered / 3 | D05明确标准版导出MP4，答案没有扩展成“只支持MP4”或其他格式。 | [输出](../../examples/audit-final/extended/A01/output.json) · [Trace](../../examples/audit-final/extended/A01/trace.jsonl) |
| A02 非报销新改写 | answered / 3 | “最多能拉几位同事”检索到协作者人数，P101原文支持8名。 | [输出](../../examples/audit-final/extended/A02/output.json) · [Trace](../../examples/audit-final/extended/A02/trace.jsonl) |
| A03 产品历史追问 | answered / 3 | 结合历史的影云标准版检索D05，重新读取后回答MP4，资料外格式保持未知。 | [输出](../../examples/audit-final/extended/A03/output.json) · [Trace](../../examples/audit-final/extended/A03/trace.jsonl) |
| A04 相关但不能回答8K | insufficient_evidence / 5 | 读取MP4片段，补搜分辨率规格，明确格式不等于分辨率，未断言支持或禁止8K。引用D05用于说明有限依据，合理。 | [输出](../../examples/audit-final/extended/A04/output.json) · [Trace](../../examples/audit-final/extended/A04/trace.jsonl) |
| A05 原文短暂失败 | answered / 4 | 首次读D05失败，重读同一片段成功后引用MP4；观察与恢复动作相连。 | [输出](../../examples/audit-final/extended/A05/output.json) · [Trace](../../examples/audit-final/extended/A05/trace.jsonl) |
| A06 原文持续失败 | incomplete / 5 | 虽检索摘要含MP4，但三次读取失败后没有将其升级为核实答案或引用；只说明摘要提示和无法确认。 | [输出](../../examples/audit-final/extended/A06/output.json) · [Trace](../../examples/audit-final/extended/A06/trace.jsonl) |
| A07 新主题未知优先级冲突 | needs_clarification / 5 | P101/P102同为团队版且人数8/12冲突，读双方后补搜优先替代，未知则追问，不默认日期较新优先。 | [输出](../../examples/audit-final/extended/A07/output.json) · [Trace](../../examples/audit-final/extended/A07/trace.jsonl) |
| A08 新主题原文替换 | answered / 3 | 相比A02，P101原文改为20名，答案与引用同步20，无8人旧答案残留。 | [输出](../../examples/audit-final/extended/A08/output.json) · [Trace](../../examples/audit-final/extended/A08/trace.jsonl) |
| A09 明示优先替代 | answered / 5 | 读取三份原文，P103明确生效日期、12名及优先替代P101/P102，故可消歧回答12，不机械地一律追问。 | [输出](../../examples/audit-final/extended/A09/output.json) · [Trace](../../examples/audit-final/extended/A09/trace.jsonl) |
| A10 冲突读取失败 | needs_clarification / 7 | 一次格式错误后，P101首次读失败、同片段重读成功，再读P102并补搜；最终引用8/12并追问，未忽略失败的冲突候选。 | [输出](../../examples/audit-final/extended/A10/output.json) · [Trace](../../examples/audit-final/extended/A10/trace.jsonl) |

## 三、针对 T04 的通用修订与完整复测

修订原则不是更改T04问题、放宽其预期或建立特定问句映射：对一般规则/时长，已有资料足以回答主问题时给出`answered`并列出附加缺口；只有用户确实要求具体日期或缺口影响核心答案时才追问。出处表述用“根据本轮读取资料”，不凭版本日期称“现行/最新”。修改后使用新目录完整重跑20项，不覆盖上面的19/20记录。

第二轮实际已完成：[要求矩阵原始汇总9/10](../../examples/audit-final-v2/required/summary.json) · [扩展矩阵10/10](../../examples/audit-final-v2/extended/summary.json)。全部20个输出对应源码摘要 `9b91aba1f752d57d5a2c85735ef6e3fd445d2d82e3069bc868faa900bb21e1be`。要求矩阵39步，含T02/T09各一次格式错误后恢复；扩展矩阵40步，无格式错误。

T04已实际修复为`answered`，去掉无依据“现行”，保留30天与起算缺口。**新T10不是模型错误，而是第二个评估口径问题**：模型识别只有一次决策预算，主动以`finish/incomplete`结束，明确尚未检索、读取而不能给可靠期限。没有超限或伪造引用，但旧断言只接受引擎自动停止的`reason=step_limit`，因此自动汇总仍记失败。主动安全结束与持续调用被引擎截停是两种合法路径，不能为了得到预期日志逼模型先做一次检索。自动硬上限另由确定性持续动作测试证明；若调整停止断言，应明确是修正评估器而非模型效果提升，并保留本次原始9/10汇总。

### 第二轮逐项语义复核

| 用例 | 实际状态 / 步数 | 独立检查结论 | 证据 |
|---|---|---|---|
| T01 | answered / 3 | D01支持30天；一般规则直接回答，起算和范围缺口单列，无“现行”断言。 | [输出](../../examples/audit-final-v2/required/T01/output.json) · [Trace](../../examples/audit-final-v2/required/T01/trace.jsonl) |
| T02 | needs_clarification / 6 | 一次JSON格式错误后恢复，读双方、补搜，准确列30/15并请求确认。 | [输出](../../examples/audit-final-v2/required/T02/output.json) · [Trace](../../examples/audit-final-v2/required/T02/trace.jsonl) |
| T03 | insufficient_evidence / 4 | 三次不同检索含无关候选，未把请假、设备、访客内容用于停车答案。 | [输出](../../examples/audit-final-v2/required/T03/output.json) · [Trace](../../examples/audit-final-v2/required/T03/trace.jsonl) |
| T04 | answered / 4 | 30天与引用正确，一般规则已回答，未载明起算点作为附加缺口而非阻断；无“现行”措辞。 | [输出](../../examples/audit-final-v2/required/T04/output.json) · [Trace](../../examples/audit-final-v2/required/T04/trace.jsonl) |
| T05 | answered / 3 | 历史指代正确，重新读取D01，回答30天并说明未知范围和起算。 | [输出](../../examples/audit-final-v2/required/T05/output.json) · [Trace](../../examples/audit-final-v2/required/T05/trace.jsonl) |
| T06 | answered / 4 | 首次搜索失败，模型改写查询后恢复，再读原文，30天有依据。 | [输出](../../examples/audit-final-v2/required/T06/output.json) · [Trace](../../examples/audit-final-v2/required/T06/trace.jsonl) |
| T07 | incomplete / 4 | 三次工具故障后明确未完成，不称制度不存在，空引用。 | [输出](../../examples/audit-final-v2/required/T07/output.json) · [Trace](../../examples/audit-final-v2/required/T07/trace.jsonl) |
| T08 | answered / 4 | 原文变45后答案/引用均变45；细节不足不阻断一般期限答案。 | [输出](../../examples/audit-final-v2/required/T08/output.json) · [Trace](../../examples/audit-final-v2/required/T08/trace.jsonl) |
| T09 | needs_clarification / 6 | 一次格式修复后仍完成双方读取和补查，对比T01正确改变状态。 | [输出](../../examples/audit-final-v2/required/T09/output.json) · [Trace](../../examples/audit-final-v2/required/T09/trace.jsonl) |
| T10 | incomplete / 1，自动断言失败 | 一步内主动安全结束；并未触发执行器`step_limit`，不可把这条记录写成硬上限截停证据。 | [输出](../../examples/audit-final-v2/required/T10/output.json) · [Trace](../../examples/audit-final-v2/required/T10/trace.jsonl) |
| A01 | answered / 3 | D05支持MP4，未扩展其他格式。 | [输出](../../examples/audit-final-v2/extended/A01/output.json) · [Trace](../../examples/audit-final-v2/extended/A01/trace.jsonl) |
| A02 | answered / 3 | 新改写问题正确对应P101协作者人数，8名有原文支持。 | [输出](../../examples/audit-final-v2/extended/A02/output.json) · [Trace](../../examples/audit-final-v2/extended/A02/trace.jsonl) |
| A03 | answered / 3 | 历史的产品指代正确，读D05后回答MP4，其他格式保留未知。 | [输出](../../examples/audit-final-v2/extended/A03/output.json) · [Trace](../../examples/audit-final-v2/extended/A03/trace.jsonl) |
| A04 | insufficient_evidence / 5 | 补查分辨率后仍区分MP4格式与8K能力，不做支持/不支持推断。 | [输出](../../examples/audit-final-v2/extended/A04/output.json) · [Trace](../../examples/audit-final-v2/extended/A04/trace.jsonl) |
| A05 | answered / 4 | 读取失败后重读同一D05片段，成功取得原文才引用。 | [输出](../../examples/audit-final-v2/extended/A05/output.json) · [Trace](../../examples/audit-final-v2/extended/A05/trace.jsonl) |
| A06 | incomplete / 5 | 两次原文读取失败后虽有一次成功搜索，仍未误判故障已恢复；不把摘要升级成确定答案。 | [输出](../../examples/audit-final-v2/extended/A06/output.json) · [Trace](../../examples/audit-final-v2/extended/A06/trace.jsonl) |
| A07 | needs_clarification / 5 | 未知优先级的8/12冲突：读双方、补搜、追问，未因新版日期选12。 | [输出](../../examples/audit-final-v2/extended/A07/output.json) · [Trace](../../examples/audit-final-v2/extended/A07/trace.jsonl) |
| A08 | answered / 3 | P101从8改20，答案和引用随之变化，无旧数字残留。 | [输出](../../examples/audit-final-v2/extended/A08/output.json) · [Trace](../../examples/audit-final-v2/extended/A08/trace.jsonl) |
| A09 | answered / 3 | 直接读取P103原文已明确范围、12人和替代关系，足以消歧；不应强制固定“读所有旧条款再搜索”的无效步骤。 | [输出](../../examples/audit-final-v2/extended/A09/output.json) · [Trace](../../examples/audit-final-v2/extended/A09/trace.jsonl) |
| A10 | needs_clarification / 6 | 失败的P101原文重读成功后，继续读P102和补查，最终8/12冲突与双引用完整。 | [输出](../../examples/audit-final-v2/extended/A10/output.json) · [Trace](../../examples/audit-final-v2/extended/A10/trace.jsonl) |

细粒度措辞边界：第二轮T04把“报销期限30天”释义成“期限内提交”，而合成原文没有专门区分提交、审批或到账阶段。主数值与一般报销期限含义有支持，但严格业务应用仍宜只复述原文并把阶段定义列入缺口。本复核不将每个自然语言扩写都视为得到形式化证明。


## 四、最终 v3 完整复测：20/20，保留三次格式修复

最终已实际完成：[要求矩阵10/10](../../examples/audit-final-v3/required/summary.json) · [扩展矩阵10/10](../../examples/audit-final-v3/extended/summary.json)。20项均为真实模型模式，每项输出和Trace已逐条重新阅读。全部运行源码摘要相同，并与复核时当前源码计算值一致：

```text
a1d89f0df39a1468846d554468f2958f7ea2c82e568f454217d29c4e6a7e6369
```

本轮相对v2不修改模型提示词，仅修正T10对合法停止方式的过严判定。仍完整重新运行，而非改写旧输出。实际v3 T10选择了先检索再由引擎返回`step_limit`，因此它本身就是硬预算截停的真实证据；v2 T10主动`finish/incomplete`的合法记录也保留。

最终要求矩阵40步、扩展矩阵43步。T04、T09、A10各发生一次`invalid_json`，均在相同步数预算内恢复；**不能把最终成功说成完全没有格式错误**。失败与修复事件可直接在Trace检查。

| 用例 | 实际状态 / 步数 | 最终语义复核 | 证据 |
|---|---|---|---|
| T01 | answered / 3 | D01原文直接支持30天，起算和范围未知单列，没有推定现行状态或具体日期。 | [输出](../../examples/audit-final-v3/required/T01/output.json) · [Trace](../../examples/audit-final-v3/required/T01/trace.jsonl) |
| T02 | needs_clarification / 5 | 读双方原文、补搜效力/优先关系，列30/15并追问，没有裁决未知冲突。 | [输出](../../examples/audit-final-v3/required/T02/output.json) · [Trace](../../examples/audit-final-v3/required/T02/trace.jsonl) |
| T03 | insufficient_evidence / 4 | 检索出现设备/请假/访客噪声，明确主题不相关；无停车流程编造。 | [输出](../../examples/audit-final-v3/required/T03/output.json) · [Trace](../../examples/audit-final-v3/required/T03/trace.jsonl) |
| T04 | answered / 5 | 一次格式修复后回答一般期限30天，起算、自然日/工作日及逾期列为未知；没有无依据“现行”或提交阶段释义。 | [输出](../../examples/audit-final-v3/required/T04/output.json) · [Trace](../../examples/audit-final-v3/required/T04/trace.jsonl) |
| T05 | answered / 4 | 正确承接报销历史，重新读D01后答30天，未拿历史助手消息作证。 | [输出](../../examples/audit-final-v3/required/T05/output.json) · [Trace](../../examples/audit-final-v3/required/T05/trace.jsonl) |
| T06 | answered / 5 | 检索故障后模型改查询恢复、读原文并补查，30天答案有依据。 | [输出](../../examples/audit-final-v3/required/T06/output.json) · [Trace](../../examples/audit-final-v3/required/T06/trace.jsonl) |
| T07 | incomplete / 4 | 三次检索故障后明确未完成，未声称没有制度；无原文引用。 | [输出](../../examples/audit-final-v3/required/T07/output.json) · [Trace](../../examples/audit-final-v3/required/T07/trace.jsonl) |
| T08 | answered / 3 | 原文变45后答案及引用均变45，无30残留。 | [输出](../../examples/audit-final-v3/required/T08/output.json) · [Trace](../../examples/audit-final-v3/required/T08/trace.jsonl) |
| T09 | needs_clarification / 6 | 一次格式修复后读双方、补查，新增冲突使输出从直接回答改为追问。 | [输出](../../examples/audit-final-v3/required/T09/output.json) · [Trace](../../examples/audit-final-v3/required/T09/trace.jsonl) |
| T10 | incomplete / 1 | 1步检索后由引擎自动step_limit，未把检索摘要当作完整回答。 | [输出](../../examples/audit-final-v3/required/T10/output.json) · [Trace](../../examples/audit-final-v3/required/T10/trace.jsonl) |
| A01 | answered / 3 | D05支持MP4；“未说明其他格式”不被偷换为“只支持MP4”。 | [输出](../../examples/audit-final-v3/extended/A01/output.json) · [Trace](../../examples/audit-final-v3/extended/A01/trace.jsonl) |
| A02 | answered / 3 | 新主题改写正确定位P101，8名与原文一致，角色是否计入上限仅列未知。 | [输出](../../examples/audit-final-v3/extended/A02/output.json) · [Trace](../../examples/audit-final-v3/extended/A02/trace.jsonl) |
| A03 | answered / 3 | 产品历史指代正确，重新读D05并引用MP4，其他格式保持未知。 | [输出](../../examples/audit-final-v3/extended/A03/output.json) · [Trace](../../examples/audit-final-v3/extended/A03/trace.jsonl) |
| A04 | insufficient_evidence / 5 | 读取并补查分辨率，正确区分MP4文件格式与8K能力；不推断支持或不支持8K。 | [输出](../../examples/audit-final-v3/extended/A04/output.json) · [Trace](../../examples/audit-final-v3/extended/A04/trace.jsonl) |
| A05 | answered / 4 | D05首次读失败后同片段重读成功，再以原文支持MP4答案。 | [输出](../../examples/audit-final-v3/extended/A05/output.json) · [Trace](../../examples/audit-final-v3/extended/A05/trace.jsonl) |
| A06 | incomplete / 5 | 三次原文读取失败（初次加两次重试）后incomplete，空引用，最终答案不把摘要里的MP4当已核实结论。 | [输出](../../examples/audit-final-v3/extended/A06/output.json) · [Trace](../../examples/audit-final-v3/extended/A06/trace.jsonl) |
| A07 | needs_clarification / 5 | 同范围P101/P102的8/12冲突，读双方后补搜，仍无优先关系则追问。 | [输出](../../examples/audit-final-v3/extended/A07/output.json) · [Trace](../../examples/audit-final-v3/extended/A07/trace.jsonl) |
| A08 | answered / 3 | P101从8变20后，引用和答案同步20；没有凭空说明所有者/管理员计数。 | [输出](../../examples/audit-final-v3/extended/A08/output.json) · [Trace](../../examples/audit-final-v3/extended/A08/trace.jsonl) |
| A09 | answered / 5 | 读三份原文，P103明示12人、日期、优先与替代关系，答案按此消歧并引用各条款，不凭新日期猜测。 | [输出](../../examples/audit-final-v3/extended/A09/output.json) · [Trace](../../examples/audit-final-v3/extended/A09/trace.jsonl) |
| A10 | needs_clarification / 7 | 一次格式错误与一次P101读取失败后恢复；成功读P101/P102、补查，最终8/12双引用与追问完整。 | [输出](../../examples/audit-final-v3/extended/A10/output.json) · [Trace](../../examples/audit-final-v3/extended/A10/trace.jsonl) |

最终20个样本的主要回答事实和引用有支持，冲突、资料外、改写、上下文、工具失败都有真实运行证据。没有观察到最后一轮输出无依据选择冲突数字或无依据声称“现行/最新”。这不是对所有未来输出的保证。

仍需谨慎的表达边界：A04用“全文未提及”描述读到的D05，当前合成D05确实只有这一段，因此本用例没有事实矛盾；换成多片段文档时，只有读取单片段就宣称全文没有某事实将不成立。模型对可见范围的措辞仍需扩展测试，而不是把本轮小样本通过外推成文档完整性证明。

## 五、不能外推的结论

- 文档子串/版本检查不能验证全部语义蕴含，T04正展示了引用正确而措辞和状态仍有问题。
- 此批次是少量合成题，含公开考核示例及审查中新构造的问题；不是随机抽样、真人标注的大规模盲测。
- 适用范围/优先级消歧只覆盖给定明确替代关系，未覆盖复杂组织政策或任意真实文档。
- 提示词修订后最终单轮全过仍不保证未来每次稳定通过；保留失败而非只提交成功输出。
- 工具持续失败时宁可未完成；错误ID的未恢复失败也可能保守阻断回答，这是已记录的可用性限制。
