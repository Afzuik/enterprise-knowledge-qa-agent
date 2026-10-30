# 企业知识问答 Agent · 提交入口

| 项目 | 当前信息 |
|---|---|
| GitHub 仓库 | [Afzuik/enterprise-knowledge-qa-agent](https://github.com/Afzuik/enterprise-knowledge-qa-agent) |
| 可见性 | 私有 |
| 默认分支 | main |
| 考核题号 | 尚未提供，正式提交前需补充 |
| 评审账号 | 尚未提供，尚未邀请或验证评审访问权限 |
| 通过验收的实现提交 | `51874e87d5c7ba179d070bd2957c28557620390b` |
| 当前交付提交 SHA | 文档发布提交可能晚于实现提交；以 `git rev-parse HEAD` 或 GitHub main 分支最新提交的完整 SHA 为准，提交表单中请填写该完整值 |

## 快速评审

1. 阅读 [README](README.md)，按说明运行 CLI。
2. 查看 [全面审查报告](docs/06-audit.md)：六类必验的逐项证据映射、发现的问题、修复与剩余边界。
3. 查看 [原必验10/10](examples/audit-final-v3/required/summary.json)、[扩展真实10/10](examples/audit-final-v3/extended/summary.json) 和 [逐项语义复核](docs/audit/live-semantic-review.md)。
4. 工程测试109/109通过，见 [最终测试原始日志](examples/audit-final-v3/final-tests/stderr.txt) 与 [实际命令/退出码](examples/audit-final-v3/final-tests/process.json)。
5. 模型模式、源码摘要、语料摘要、工具参数、真实观察与后续动作均在每个用例的 output/trace 中。历史失败保留，不只提供成功截图。

## 复现命令

在仓库根目录执行：

```bash
python3 run.py ask --mode mock --question '报销期限多久？'
PYTHONPATH=src python3 -m unittest discover -s tests -v
python3 run.py evaluate --mode live --output examples/local/submission-review
```

真实模式需按 `.env.example` 自行配置 `.env`。仓库没有提供真实密钥；Mock只验证流程，不能证明模型决策效果。输出目录必须不存在。

## 发布检查与剩余事项

- 私有仓库和首次推送提交已通过 GitHub API 核对，见 [发布记录](docs/publication.json)。
- `.env` 未跟踪，发布前扫描历史822个blob，未发现所配置模型密钥或常见凭据/私钥标记。
- 发布使用命令级代理覆盖，没有修改系统或全局 Git 代理。
- 日志含本机路径等环境信息，因此默认私有。不要未审阅就改为公开仓库。
- 必须补充题号，并邀请指定评审账号、确认其可读后，才能声称完成全部提交规范。
- 固定合成样本通过不代表生产可靠性；未完成项和保守策略详见审查报告。
