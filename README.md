# GameNexus 游戏RAG问答系统 — 质量闭环模块

**技术栈**：Python、FastAPI、LangGraph、BM25+jieba、DeepSeek LLM、TapTap、React、TypeScript

---

## 概述

这是 GameNexus 系统的质量闭环子模块，在已有 RAG 问答架构之上新增五层防护机制，解决 LLM 输出的幻觉、事实错误、不可追溯问题。

## 五层防护架构

```
用户输入 ──→ 第一层：事实白库（关键词匹配命中直接返回）
             │ 未命中
             ▼
         ┌── Retriever (BM25) ── ToolAgent (TapTap) ──┐
         │             第二层：交叉验证                 │
         │   BM25 vs TapTap 双通道互验，单通道标黄     │
         └──────────────────┬──────────────────────────┘
                            ▼
                  第三层：事实抽取校验
                  从 draft 提取数值/名称，对比参考源
                  发现矛盾 → 自动重写
                            ▼
                        Summarizer
                            ▼
                        Validator
                            ▼
                        输出 ──── 用户反馈循环 ────┐
                            ▲                      │
                            └── 第四层：反馈闭环 ──┘
                                分级(1-5) → 过滤 → AI审核 → 权重调整

             第五层：监控与回滚
             权重时间衰减(30天半衰期) + 变更历史可回滚
```

## 模块详解

### 1. 事实白库 (`app/quality/whitelist.py`)

高频错误问题的固定标准答案库，检索命中直接覆盖 LLM 输出。

- 匹配策略：完全匹配 → 关键词匹配 → 模糊匹配（字符重叠度 > 80%）
- 集成位置：`orchestrator.run_stream()` 入口处优先拦截
- 数据持久化：`data/quality/white_list.json`

### 2. 交叉验证 (`app/quality/cross_validate.py`)

BM25（关键词）与 TapTap（实时数据）双通道互验：

- 内容同时在两路出现 → `cross_validated`，置信度 `high`
- 仅 BM25 或仅 Tool 出现 → `bm25_only` / `tool_only`，置信度 `low`
- 集成位置：`summarizer.run()` 素材拼装时标注数据可信度

### 3. 事实抽取校验 (`app/quality/extractor.py`)

从生成草稿中自动提取关键信息并验证：

- 抽取类型：价格（元/美元）、评分（分/星）、年份、百分比、数字、中文书名、英文名
- 验证方式：提取 draft 中的事实 → 在参考素材中搜索对应 → 未找到则标记为异常
- 集成位置：`summarizer.run()` 生成 draft 后自动校验，发现问题追加修正指令

### 4. 用户反馈闭环 (`app/quality/feedback.py`)

全链路反馈处理系统：

- **分级机制**：1-2分负面 / 3分中性 / 4-5分正面
- **自动过滤**：毒性内容 / PII 个人信息 / 重复反馈（1h窗口）
- **AI预审核**：LLM-as-a-Judge 评估反馈内容风险（low/medium/high）
- **自动修正**：
  - 正面反馈 → 提升对应 chunk 权重（+0.1）
  - 负面反馈 → 降低对应 chunk 权重（-0.2）+ 白库新增正确条目
  - 高风险内容 → 标记待人工审核
- **数据持久化**：`data/quality/feedback_log.jsonl`

### 5. 权重管理 (`app/quality/weight_manager.py`)

chunk 级别的检索权重动态调节：

| 操作 | 效果 |
|------|------|
| 正面反馈 | 权重 +0.1 |
| 负面反馈 | 权重 -0.2 |
| 权重范围 | 0.0 ~ 2.0（默认 1.0） |
| 时间衰减 | 30 天半衰期指数衰减趋近 1.0 |
| 回滚能力 | 按分钟回滚所有权重变更 |
- 集成位置：`RAGEngine.search()` 中 `score *= weight`

## API 端点

### 事实白库

```
GET    /api/v1/quality/whitelist      # 列表
POST   /api/v1/quality/whitelist      # 新增 {question, answer, keywords}
DELETE /api/v1/quality/whitelist/{id} # 删除
```

### 用户反馈

```
POST  /api/v1/quality/feedback                # 提交反馈（自动过滤+AI审核）
GET   /api/v1/quality/feedback?status=        # 列表（可选按状态筛选）
POST  /api/v1/quality/feedback/{id}/review    # 人工审核 {action, note}
```

### 权重管理

```
GET   /api/v1/quality/weights                 # 列表
POST  /api/v1/quality/weights/rollback        # 回滚 {minutes: 30}
```

### 其他

```
GET   /api/v1/quality/cross-validate  # 交叉验证统计
GET   /api/v1/quality/stats           # 查询统计
GET   /api/v1/quality/records         # 查询记录
```

## 反馈处理流程

```
用户提交(评分+纠错内容)
  │
  ▼
第一层过滤：毒性检测 → 敏感词拦截
           PII检测  → 个人信息拦截
           重复检测  → 1h窗口去重
  │
  ▼
评分判断
  ├─ 3分(中性) → 仅记录日志，结束
  ├─ 4-5分(正面) → 提升权重(+0.1)，结束
  └─ 1-2分(负面) → 检查是否补充错误点
       ├─ 未补充 → 标记待补充，结束
       └─ 已补充 → AI预审核(LLM评估风险)
            ├─ 高风险 → 人工审核队列
            └─ 低风险 → 降权(-0.2) + 白库新增正确条目
```

## 快速调试

```bash
# 新增白库条目
curl -X POST http://localhost:8000/api/v1/quality/whitelist \
  -H "Content-Type: application/json" \
  -d '{"question":"黑神话悟空多少钱","answer":"268元","keywords":["黑神话","价格"]}'

# 提交反馈
curl -X POST http://localhost:8000/api/v1/quality/feedback \
  -H "Content-Type: application/json" \
  -d '{"query":"黑神话悟空评分","answer":"10分","score":2,"error_points":"分数不对","correct_answer":"IGN 8分"}'

# 查看权重
curl http://localhost:8000/api/v1/quality/weights

# 回滚30分钟内权重变更
curl -X POST http://localhost:8000/api/v1/quality/weights/rollback \
  -H "Content-Type: application/json" \
  -d '{"minutes":30}'
```

## GraphViewer 前端流程图

React SVG 实时渲染 LangGraph 编排拓扑，双模式（缩略图 + Modal 弹窗）。

### 布局（当前）

```
规划 ──→ ┌──── 并行执行 ────┐
  (x=50) │ 检索 (x=160,y=50) │ ← 列示纵向堆叠
         │ 工具 (x=160,y=80) │
         └──────┬───────────┘
                ├──→ 摘要 (x=370,y=110) ←── 回环 ── 校验 (x=530,y=145)
```

- **列示排列**：检索/工具纵向堆叠（同 x=160，y=50/80），绿框 78×70
- **单根绿箭头**：规划→框左缘(127,25) 一根入线，框内纵向分叉
- **汇聚点 x=205**：框右缘三线对齐（汇聚线/回环左竖边）
- 正交折线 + roundPath R=6 圆角，edgeW=1.5 统一粗细
- 标注色：branch 绿 / merge 紫 / loop 黄 / default 灰

### 演进

| 版本 | 布局 | 汇聚点 |
|------|------|--------|
| v1 | 检索/工具 横向并排 | x=293 |
| v2 | 横向并排 + 右扩 | x=305 |
| v3 | 纵向列示 + 单箭头 | x=205 |

## 环境变量

| 变量 | 说明 | 默认 |
|---|---|---|
| `LLM_API_KEYS` | DeepSeek API Key列表 | `sk-***` |
| `LLM_MODEL` | 模型名称 | `deepseek-v4-flash` |
| `LLM_BASE_URL` | API地址 | `https://api.deepseek.com/v1` |
| `TAP_API_TIMEOUT` | TapTap 请求超时（秒） | `8` |
| `TAP_PROXY` | TapTap 代理地址 | 空 |
| `EMBED_LOCAL_MODEL` | 本地嵌入模型路径 | `BAAI/bge-base-zh-v1.5` |
