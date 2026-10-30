# 企业知识问答 Agent

面向校招考核的可运行 CLI 原型：**真实模型选择动作 → 本地检索/读取 → 工具观察 → 模型调整或结束**。业务资料全部为合成内容，不用于真实企业政策判断。

## 本次结果与评审入口

- Python 3.9.6 / macOS 实际运行，标准库实现，无第三方依赖。
- **109 项自动化测试通过**：[原始日志](examples/audit-final-v3/verification/01-stderr.txt)、[命令和退出状态](examples/audit-final-v3/verification/verification.json)。
- 真实模型（配置标识 `deepseek-flash`）审查后 **原必验10/10 + 扩展10/10通过**：[原必验汇总](examples/audit-final-v3/required/summary.json)、[扩展汇总](examples/audit-final-v3/extended/summary.json)、[全面审查](docs/06-audit.md)、[逐项语义复核](docs/audit/live-semantic-review.md)。这是固定合成小样本的结果，不是生产准确率承诺。
- 离线 Mock **10/10 流程用例通过**：[汇总](examples/audit-final-v3/verification/mock/summary.json)。Mock 不证明模型决策效果。
- 第一轮真实模型 **8/10**，两个用例格式错误耗尽预算，失败记录完整保留：[首轮汇总](examples/live-v1/summary.json)。
- 两份原始要求未修改，SHA256 见 [源文件摘要](docs/source-sha256.json)。

先看三条真实路径：

1. [明确回答](examples/audit-final-v3/required/T01/output.json) / [Trace](examples/audit-final-v3/required/T01/trace.jsonl)：检索→读 D01→回答30天。
2. [冲突处理](examples/audit-final-v3/required/T02/output.json) / [Trace](examples/audit-final-v3/required/T02/trace.jsonl)：读取双方→补查→列出30/15天并追问，不选择较新版本。
3. [工具恢复](examples/audit-final-v3/required/T06/output.json) / [Trace](examples/audit-final-v3/required/T06/trace.jsonl)：错误观察→重新检索→读取→回答。

## 环境与快速运行

安装 Python 3.9 或以上，在仓库根目录执行（不需要 pip 安装）：

```bash
python3 --version
python3 run.py ask --mode mock --question '报销期限多久？'
python3 run.py ask --mode mock --question '报销期限多久？' --corpus data/corpus_conflict.json
```

每次自动写入新的 `examples/local/<UTC时间>-<mode>/`，终端输出完整结果及产物路径。显式 `--output` 目录若已存在则拒绝覆盖，以保护历史证据。

### 真实模型配置

首次配置（已有 `.env` 时不要覆盖）：

```bash
test -f .env || cp .env.example .env
```

用编辑器填写 `.env`：

```dotenv
LLM_API_KEY=供应商提供的密钥
LLM_MODEL=你可用的模型名称
LLM_BASE_URL=https://api.openai.com/v1
```

`LLM_BASE_URL` 必须是所选供应商的 **Chat Completions 兼容基础地址**，不要包括 `/chat/completions`；上面只是默认地址，不意味着本次 `deepseek-flash` 必须通过此地址运行。接口需支持 `response_format: json_object`、`store: false`。其他供应商或模型未验证，不保证直接兼容。密钥、模型和地址必须属于同一可用配置。

程序自动加载项目根目录 `.env`；同名非空进程环境变量优先，也兼容 `OPENAI_API_KEY/OPENAI_MODEL/OPENAI_BASE_URL`。Mock 不加载 `.env`。该简易解析器不执行 shell、不展开变量、不支持行尾注释。不要将真实密钥粘贴到聊天、运行记录或 Git。

```bash
python3 run.py ask --mode live --question '报销期限多久？'
python3 run.py ask --mode live --question '报销期限多久？' --corpus data/corpus_conflict.json
python3 run.py ask --mode live --question '那期限呢？' --history data/history.json
python3 run.py ask --mode live --question '报销期限多久？' --fault search_once
```

真实模式会向所配置端点发送问题、历史、检索及读取结果；仅使用已获准发送的资料。缺配置、网络失败不自动切换 Mock。

## 验证与复跑

```bash
# 工程单元/集成测试（不调用外部模型）
PYTHONPATH=src python3 -m unittest discover -s tests -v

# 十项验收，包含资料外、冲突、历史、文档变更、失败和预算
python3 run.py evaluate --mode mock --output examples/local/mock-review
python3 run.py evaluate --mode live --output examples/local/live-review
python3 run.py evaluate --mode live --cases data/audit_cases.json --output examples/local/extended-review

# 离线完整验证，保留每条实际命令、stdout/stderr、退出码
python3 scripts/verify.py --output examples/local/verification-review
```

上面的显式输出路径需不存在；重复验证请换新目录。真实验收会产生模型请求费用，步数上限不是费用预算。默认最多10次模型决策、每次外部请求30秒超时；支持 `--max-steps 1` 和 `--timeout 15`。参数说明：`python3 run.py ask --help`。

故障模式：`none/search_once/search_always/read_once/read_always`。故障注入仅用于本地工具测试，不代表真实线上故障分布。

退出码：单问任务正常交付（含追问/资料不足）为0，`incomplete` 或输入/配置错误为2；批量验收全部满足预期为0，否则为1。T07/T10预期就是未完成，所以子进程退出2不等于批量评估失败。

## 产物结构

```text
src/knowledge_agent/    原生执行器、模型适配器、检索工具、Mock、校验与日志
run.py                 CLI入口
scripts/verify.py      捕获实际验证命令、输出、退出码
requirements.txt       标准库项目，无第三方依赖
.env.example           变量模板；Mock无需配置
.env                   本地私密配置，Git忽略，不提交
data/                  合成语料、验收输入、历史
examples/live-v1/       首轮真实运行及失败
examples/live-v2/       首次交付历史真实运行
examples/audit-baseline/ 第二次审查修复前记录
examples/audit-final*/  审查迭代记录（最终为audit-final-v3）
examples/verification/  首次交付历史验证；当前见audit-final-v3/verification
examples/local/        用户复跑输出，Git忽略
tests/                 可执行测试
docs/                  要求、设计、评估、AI使用、复盘、审计记录
```

每个验收目录含 `input.json/output.json/trace.jsonl/checks.json/process.json/stdout.txt/stderr.txt`；`process.json` 记录实际子进程命令、目录与退出码。单问 CLI 的该文件仅给出自身对应退出码。Trace 包含工具参数、结果、简要依据、下一动作，不提交模型内部思维。

文档入口：[需求](docs/01-requirements.md) · [方案](docs/02-solution.md) · [评估](docs/03-evaluation.md) · [AI辅助](docs/04-ai-usage.md) · [复盘](docs/05-retrospective.md) · [改动与恢复](docs/change-summary.md)。

## 边界与尚未完成

- 引用存在/版本/子串是自动校验；语义支持依赖模型和对已保存样本的人工式复核，无法保证所有生成答案都不幻觉。
- 词法检索有召回盲点；没有向量库、权限体系、生产级重试/会话持久化、界面或部署。
- Mock是有限规则模拟器，不能处理通用语义消歧。测试集含公开题目示例，非盲测；未证明广泛泛化、长期稳定性或检索收益。
- 程序输入/配置启动失败仅输出安全错误，尚未创建模型运行记录；批量评估会保存对应stdout/stderr与失败状态。
- 题号、GitHub URL、指定评审账号尚未提供，**未发布远程仓库**。本地提交可用 `git rev-parse HEAD` 获取；发布前检查 `.env` 未跟踪并补齐题号、URL、最终SHA及私有库读权限。
