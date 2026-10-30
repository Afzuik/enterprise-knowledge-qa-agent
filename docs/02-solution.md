# 02 方案、动态决策与技术取舍

## 架构

```text
CLI 问题 + 可选历史 + 知识库
              ↓
        单 Agent 决策循环
              ↓
    模型生成 JSON action
              ↓
        参数 / 动作校验
      ┌───────┼────────┐
 search_docs read_doc  finish
      │        │        ↓
      └─ 工具观察 ── 引用与状态校验
              ↓        ↓
          再次模型决策  最终输出 + Trace
```

固定的是执行骨架，不是业务决策路径。真正模式下，模型决定检索词、读取哪个片段、是否补充查证以及何时结束。引擎没有 D01/D02 专用答案分支。

## 源码分工

| 文件 | 职责 |
|---|---|
| `run.py`、`src/knowledge_agent/cli.py` | `ask`/`evaluate` 子命令、参数、退出码和产物位置 |
| `src/knowledge_agent/agent.py` | 有界循环、历史校验、证据登记、动作与最终输出校验 |
| `src/knowledge_agent/model.py` | Chat Completions HTTP 适配、响应解析、脱敏错误 |
| `src/knowledge_agent/mock.py` | 明确标识为规则模拟的离线模型，不参与真实模式 |
| `src/knowledge_agent/prompts.py` | 证据、冲突、历史、工具失败和动作格式约束 |
| `src/knowledge_agent/tools.py` | 词法检索、片段读取、故障注入、语料哈希 |
| `src/knowledge_agent/config.py` | 模型配置读取，不执行 shell，不输出密钥 |
| `src/knowledge_agent/trace.py` | 保存本轮输入、结果、Trace，拒绝覆盖旧目录 |
| `src/knowledge_agent/evaluate.py` | 子进程运行验收、保存原始 stdout/stderr、断言与汇总 |

## 模型协议与配置

使用标准库 `urllib.request` 向配置的基础 URL 拼接 `/chat/completions` 发送请求，模型每轮返回：

```json
{
  "action": "search_docs",
  "arguments": {"query": "报销期限", "top_k": 5},
  "decision_summary": "先检索与问题相关的制度。"
}
```

允许的动作仅为 `search_docs`、`read_doc`、`finish`。这里采用 **JSON action 协议**，不是服务端原生 function calling。HTTP 请求设置 JSON object 响应模式，但 JSON 格式不等于动作字段和业务内容正确，因此应用仍严格校验。协议参考 [OpenAI 官方 Chat Completions API 文档](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)；第三方兼容服务对参数的支持和模型行为需要单独实测，不能由文档推定兼容。

真实模式读取项目根目录 `.env`，支持 `LLM_API_KEY`、`LLM_MODEL`、`LLM_BASE_URL`，并兼容对应的 `OPENAI_*` 变量。已有非空环境变量优先；同类配置中 `LLM_*` 优先。解析器只接受白名单变量，不执行 `.env` 内容。Mock 无须密钥，也不发模型请求。具体模型标识记录在每次输出元信息中，不在代码中固定型号。

HTTP 适配器设置请求超时与响应体大小限制，拒绝转发 HTTP 重定向，以避免向重定向目标发送授权头。非本机接口要求 HTTPS。网络错误不会悄悄重试或切换 Mock；动作格式错误可以反馈给模型修正，并消耗相同预算。

## 资料与工具

知识库包含稳定的文档、片段 ID 和版本日期。`scope`、`priority` 为 `null` 表示未知。版本日期是出处信息，不构成制度优先级。

`search_docs(query, top_k)` 使用中文字符二元组、英文/数字词、通用短语归一化和停用词；标题、关键词、正文分别加权。返回候选 ID、版本、短摘要、分数及 `truncated`。默认取前 5，最大 10；分数仅代表词法匹配，不代表权威性或答案置信度。已移除针对完整验收问题的整句同义词映射。

`read_doc(doc_id, chunk_id)` 校验文档及片段归属后返回原文与元信息。即使摘要很短且碰巧包含全文，仍要求模型实际调用读取工具后才能引用。

故障模式为 `none`、`search_once`、`search_always`、`read_once`、`read_always`。故障只影响工具返回，不修改语料。检索无结果为 `ok=true` 且结果为空；工具失败为 `ok=false` 和错误对象，两者不可混淆。

## 引用、状态与预算

- 每轮成功读取的片段登记为证据；历史助手消息和搜索摘要不能直接充当引用来源。
- 引用必须具有非空的文档 ID、片段 ID、版本和原文；版本一致，原文必须是已读取正文的连续子串。
- `answered` 必须附引用；其他状态必须说明资料缺口或未完成原因。
- `needs_clarification` 必须有具体追问。
- `insufficient_evidence` 需要成功检索，且不能存在未恢复工具故障。
- 未恢复故障按搜索工具或具体读取片段区分；读取别的片段成功不代表原读取故障已经恢复。
- 默认最多 10 次模型决策，可配置 1～30；工具调用、格式修复、失败重试均占决策预算。耗尽后明确返回 `incomplete` 和 `step_limit`。

子串校验只能证明引用存在，不能证明它支持结论。语义支持、冲突是否被不当裁决，依赖模型行为及验收复核，不宣称已由字符串校验彻底解决。

## Trace 与复现

每步记录动作、参数、返回观察、简要决策依据、下一动作和耗时，不索要或保存模型内部思维过程。结果元信息记录运行模式、模型标识、语料 SHA256、源代码 SHA256、运行 ID、预算与时间。验收器还保存实际命令、输入、stdout、stderr 和退出状态。

运行目录存在时拒绝覆盖。旧轮失败记录保留；调整提示或代码后使用新目录重新运行，避免把不同版本证据混作一次实验。单问正常业务结束退出 0，`incomplete` 退出 2；批量验收有不符合预期的结果时返回非零。

## 取舍和限制

1. 原生 Python 3.9 CLI 与标准库减少依赖和框架学习成本；没有采用 ADK、AgentScope、LangGraph，也不因不用框架而重新实现完整 Runtime。
2. 词法检索适合小规模合成样本，但有误召回、漏召回、中文语义改写和长查询覆盖不足的风险。未实施独立留出集上的检索提升实验，不声称泛化提升。
3. Mock 按规则模拟冲突及恢复，便于离线回归，但不是模型能力或 ReAct 达标证据。
4. 无生产权限、租户隔离、企业 ACL、敏感数据治理和线上部署。当前数据均为合成资料。
5. 提示约束能降低文档提示注入风险，但不能代替生产级安全隔离；工具白名单仅含只读本地检索与读取，无 shell 执行动作。
6. 固定样本的单次真实运行不是可靠性统计。最终行为结论必须对应实际产物和版本。
