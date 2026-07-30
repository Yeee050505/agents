# 项目遇到的实际问题

## 1. 数据源不可用
部分海外游戏 API 从国内直连超时、丢包，甚至 SNI 阻断，导致工具 Agent 无法获取实时游戏数据。

**解决方案**：替换为 TapTap 国内数据源，支持 `TAP_PROXY` 代理配置。

## 2. 依赖兼容性
LangGraph 从 0.0.57 升级到 1.2.9 后，`Annotated[list, operator.add]` reducer 在 `from __future__ import annotations` 下失效，导致并行扇出状态下状态归约冲突。

**解决方案**：移除 `from __future__ import annotations` 使 Annotated reducer 恢复正常。

## 3. 前后端数据格式脱节
后端 `/kb/documents` 返回字段与前端 `KBDocument` 类型不一致，`/rate-limit/stats` 缺少 `llm_pool` 字段，导致前端渲染空白。

**解决方案**：统一全站响应格式为 `{code, msg, data}`，补充缺失字段对齐前端类型定义。

## 4. LLM 单点故障
单 API Key 被限流或超时后全站不可用，缺乏熔断降级机制。

**解决方案**：搭建多密钥资源池，配置三态断路器 + 指数退避熔断策略（重试区间 10s~120s）。

## 5. 黑盒输出不可控
大模型直接输出存在幻觉、捏造数据，用户无法追溯回答来源，也无法干预生成过程。

**解决方案**：
- 增加 Validator 节点用 LLM 检测幻觉，不通过则带 feedback 重写
- 搭建白盒流程图（`/api/v1/graph/workflow`），SSE 实时推送节点状态
- 人工审批机制，关键节点可 pause、modify、override

## 6. 测试积压
`needs_realtime_search`、`is_stale_response` 等函数已删除但测试仍未清理；`RAGEngine.search()` 实为同步但测试用 `await` 调用；`format_context` 已不存在。

**解决方案**：清理测试文件，修正 async/sync 调用，对齐实际 API。
