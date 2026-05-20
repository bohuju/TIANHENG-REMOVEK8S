# 文档索引

这里是 Sherpa 的技术文档入口。目标是帮助你按“当前真实实现”理解系统，而不是按历史交接材料理解系统。

## 建议阅读顺序

1. [`../README.md`](../README.md)
   系统总览、主工作流、API 与部署模型。

2. [`CODEBASE_TECHNICAL_ANALYSIS.md`](CODEBASE_TECHNICAL_ANALYSIS.md)
   代码库分层、主入口和工作流状态机。

3. [`TECHNICAL_DEEP_DIVE.md`](TECHNICAL_DEEP_DIVE.md)
   推荐阅读顺序、核心循环与常见失败来源。

4. [`API_REFERENCE.md`](API_REFERENCE.md)
   当前后端 API 契约，供前端联调与任务控制使用。

5. [`DEPLOYMENT_GUIDE.md`](DEPLOYMENT_GUIDE.md)
   **本地部署完整流程**：前置条件、快速启动、服务架构、已修复问题、日常维护和排查清单。

6. [`PROMEFUZZ_MCP_TECHNICAL_SPEC.md`](PROMEFUZZ_MCP_TECHNICAL_SPEC.md)
   PromeFuzz companion + HTTP MCP + embedding/RAG + 新增字段技术细节。

7. [`DEPLOYMENT_PITFALLS.md`](DEPLOYMENT_PITFALLS.md)
   历史踩坑记录：磁盘 ENOSPC、无限重试修复、git ownership + 权限（三次迭代）、前端代理、API key、Plan 超时、阶段不更新、服务器启动注意事项，附快速排查检查清单。

8. [`STANDARD_CHANGE_PROCESS.md`](STANDARD_CHANGE_PROCESS.md)
   变更、验证、发布与文档同步流程。

## 部署与运行

项目通过 Docker Compose 本地部署，参见 `../docker-compose.yml`。各工作流阶段在进程内通过 `fuzz_logic()` 直接执行（`_execute_docker_stage`），不再依赖 Kubernetes。

## 历史材料

以下文件保留为历史背景，不能作为当前主手册：

- [`PROJECT_HANDOFF_STATUS.md`](PROJECT_HANDOFF_STATUS.md)

## 当前文档规则

- 工作流描述以当前阶段流转为准：`plan`、`synthesize`、`build`、`run`、`coverage-analysis`、`improve-harness`、`crash-triage`、`fix-harness`、`re-build`、`re-run`、`crash-analysis`
- 历史修复节点 `fix_build` / `fix_crash` 如果出现，只能作为兼容实现说明，不能写成主线推荐路径
- API 文档必须与 [`harness_generator/src/langchain_agent/main.py`](../harness_generator/src/langchain_agent/main.py) 保持一致
- 所有链接使用仓库相对路径
- 所有历史说明必须显式标注为“历史背景”或“遗留材料”
