# GameNexus 游戏RAG问答系统

**技术栈**：Python、FastAPI、LangGraph、BM25+jieba、BGE Embedding、DeepSeek LLM、TapTap、React、TypeScript、SSE 流式交互

---

## S 情境

开发过程中遇到了以下实际问题需要解决：

1. **数据源不可用** — 原定 Steam API（`store.steampowered.com`）从国内直连经常超时、丢包，甚至 SNI 阻断，导致工具 Agent 无法获取实时游戏数据
2. **依赖兼容性** — LangGraph 从 0.0.57 升级到 1.2.9，`Annotated[list, operator.add]` reducer 在 `from __future__ import annotations` 下失效，并行扇出状态下冲突
3. **前后端数据格式脱节** — 后端 `/kb/documents` 返回字段与前端 `KBDocument` 类型不一致，`/rate-limit/stats` 缺少 `llm_pool` 字段，导致前端渲染空白
4. **LLM 单点故障** — 单 API Key 被限流或超时后全站不可用，缺乏熔断降级机制
5. **黑盒输出不可控** — 大模型直接输出存在幻觉、捏造数据，用户无法追溯回答来源，也无法干预生成过程
6. **测试积压** — `needs_realtime_search`、`is_stale_response` 等函数已删除但测试仍未清理；`RAGEngine.search()` 实为同步但测试用 `await` 调用；`format_context` 已不存在

## T 任务

1. **架构建设**：独立完成全栈开发，搭建白盒可观测的多Agent RAG问答架构，打造流程透明、可干预、可追溯的游戏领域智能问答服务。
2. **精度优化**：针对大模型幻觉、知识库滞后痛点，设计双通道检索方案，依托多源数据融合提升问答精准度与时效性。
3. **可控可视化建设**：打破传统黑盒AI问答弊端，搭建全链路白盒可视化体系，配套人工审批、容错重试机制，解决AI输出不可控、流程不透明问题。
4. **工程落地**：实现流式对话、智能记忆、状态监控等能力，保障系统低延迟、高并发稳定落地。

## A 行动

核心独立完成架构设计与功能开发，落地多Agent RAG完整解决方案，关键开发动作如下：

1. **多Agent架构搭建**：基于LangGraph构建五节点闭环工作流，采用并行扇出机制同步执行本地检索与TapTap数据拉取，通过状态归约整合多源结果，为所有节点配置异常捕获与自动重试机制，有效规避单节点故障。

2. **双通道检索优化**：设计本地知识库+实时API双检索架构，依托BM25+jieba实现轻量化高速检索，对接TapTap抓取游戏实时评分、价格、简介等数据，弥补静态知识库更新滞后问题，提升问答准确性。

3. **白盒可视化全链路搭建**：摒弃传统大模型黑盒输出模式，自研完整白盒观测体系，通过SVG实时渲染Agent工作流程图，结合SSE流式事件推送，动态展示节点空闲、运行、完成全状态。支持问答步骤、Token输出、暂停报错全流程可视化追溯，搭配核心节点人工审批、内容修改、结果覆盖能力，实现AI生成过程**全透明、可监控、可干预**。

4. **服务稳定性优化**：搭建大模型多密钥资源池，配置熔断退避策略解决接口限流、超时问题；设计短时会话记忆+BGE向量长时记忆双层架构，显著提升多轮对话连贯性。

## R 成果

创新性落地白盒可观测RAG方案，彻底解决传统AI问答黑盒不可控、无法追溯的痛点，有效抑制模型幻觉、弥补知识库滞后问题。性能表现优异：本地检索耗时低至**5ms**，系统冷启动**＜1s**，单服务QPS达**851**。依托白盒可视化链路、人工干预机制、熔断重试策略，实现问答流程透明化、结果可纠错、服务高可用，成功落地高性能、可观测、可管控的游戏领域智能问答系统。

## 量化成果

| 指标 | 数值 |
|---|---|
| 首字输出时延 | 3.5s（受限于LLM API全量返回） |
| BM25检索 | 5ms |
| 健康检查QPS | 851（单worker） |
| 系统冷启动 | <1s |
| 知识库规模 | 19 chunks / 4 文档 |
| 系统自检 | 7 项全覆盖（LLM池/知识库/BM25/长短记忆/MCP/配置） |

## 架构概览

```
用户 → FastAPI → LangGraph Orchestrator ──→ Planner
                                        │
                               ┌────────┴────────┐
                               ▼                 ▼
                          Retriever          ToolAgent
                        (BM25+jieba 知识库)  (TapTap)
                               │                 │
                               └────────┬────────┘
                                        ▼
                                    Summarizer
                                        │
                                        ▼
                                    Validator (幻觉检测)
                                        │
                           ┌────────────┼────────────┐
                           ▼            ▼            ▼
                       通过 → 输出   触发重写 → 回到Summarizer
```

## API端点

| 端点 | 说明 |
|---|---|
| `GET /health` | 健康检查 |
| `POST /api/v1/chat` | 同步问答 |
| `POST /api/v1/chat/stream` | SSE标准流式 |
| `POST /api/v1/chat/flow` | SSE全链路流式（step/token/pause/done/error） |
| `POST /api/v1/chat/resume` | 人工审批恢复 |
| `GET /api/v1/graph/workflow` | 流程图节点边定义 |
| `GET /api/v1/system/self-check` | 全组件自检 |
| `GET /api/v1/kb/documents` | 知识库文档列表 |
| `POST /api/v1/kb/upload` | 上传文档 |
| `DELETE /api/v1/kb/documents/{id}` | 删除文档 |
| `GET /api/v1/rate-limit/stats` | 限流熔断状态 |
| `POST /api/v1/auth/login` | 登录 |
| `POST /api/v1/auth/register` | 注册 |
| `GET /api/v1/lora/status` | LoRA状态 |
| `GET /api/v1/mcp/tools` | MCP工具列表 |

## 快速开始

```bash
# 安装后端依赖
pip install -r requirements.txt

# 安装前端依赖
cd frontend && npm install

# 环境变量（复制后修改）
# LLM_API_KEYS=sk-xxx,sk-yyy
# GLOBAL_RATE=50

# 启动服务
uvicorn main:app --reload --port 8000

# 前端开发模式（另开终端）
cd frontend && npm run dev
```

## CI/CD

GitHub Actions 自动流水线（`.github/workflows/ci.yml`）：

- **backend** — ruff lint + pytest（10 个测试）
- **frontend** — tsc 类型检查 + vite 构建

## 环境变量

| 变量 | 说明 | 默认 |
|---|---|---|
| `LLM_API_KEYS` | DeepSeek API Key列表（逗号分隔） | `sk-***` |
| `LLM_MODEL` | 模型名称 | `deepseek-v4-flash` |
| `LLM_BASE_URL` | API地址 | `https://api.deepseek.com/v1` |
| `MAX_HISTORY` | 短时记忆轮数 | `10` |
| `GLOBAL_RATE` | 全局速率限制 | `50` |
| `TAP_API_TIMEOUT` | TapTap 请求超时（秒） | `8` |
| `TAP_PROXY` | TapTap 代理地址 | `空` |
