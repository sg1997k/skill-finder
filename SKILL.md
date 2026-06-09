---
name: skill-finder
description: >
  智能技能发现与路由系统。使用语义领域知识图谱替代关键词匹配，实现自然语言到技能的精准路由。
  首次运行时自动扫描本地所有 SKILL.md 建立领域索引（自举），之后查询命中速度 < 1ms。
  触发场景：用户需要找技能、不确定用什么技能、询问"有什么技能可以..."、想发现新技能。
  支持领域扩展：命中文档处理领域后自动扩展到内容创作、数据可视化等相邻领域。
  典型查询："帮我分析财报" → 命中金融投资领域 → 推荐 westock-data 等技能。
version: 1.0.0
agent_created: true
---
# Skill Finder — 语义领域知识图谱路由

## 概述

`skill-finder` 不是传统的关键词搜索引擎，而是一个基于**语义领域知识图谱**的技能路由系统。它不依赖 embedding API，不调用外部向量数据库，纯本地运行，毫秒级响应。

## 核心设计

```
用户查询 → 领域路由(关键词命中) → 图谱扩展(邻接域) → 域内精排(描述匹配) → 推荐技能列表
```

**三层检索架构：**

1. **领域路由** — 关键词命中目标领域（金融投资 / 软件开发 / 数据科学 ...），从全量缩小到 100-400 个技能
2. **图谱扩展** — 邻接领域自动加入（查财报 → 自动挂数据可视化，查机器学习 → 自动挂数据可视化）
3. **域内精排** — 在缩小后的候选集中做描述语义匹配，返回 top-k 结果

## 触发条件

当用户意图包含以下任一模式时，加载本技能：

- 询问"有什么技能可以..."、"能帮我找技能吗"、"find skill for X"
- 需要做某个任务但不知道用什么技能
- 想探索本地/市场中有哪些可用技能
- AI 发现自己无法直接完成用户请求，需要寻找技能扩展能力

## 自举机制

本技能**首次执行自动建立索引**，无需手动配置：

1. 检查 `data/skill_domains.json` 是否存在
2. 若不存在 → 扫描以下路径的 SKILL.md：
   - `~/.workbuddy/skills/` — 用户技能
   - `~/.workbuddy/connectors/skills/` — 连接器技能
   - `~/.workbuddy/plugins/marketplaces/` — 市场技能
3. 提取每个 SKILL.md 的 YAML frontmatter → `name` + `description`
4. 用 13 个语义领域的关键词规则做领域分类
5. 构建领域邻接图（哪个领域和哪个领域关联）
6. 存入 `data/skill_domains.json`
7. 之后每次查询直接命中，< 1ms

**增量更新**：`data/skill_domains.json` 存有每个 skill 的 mtime。每次查询前扫描文件变化，自动增量重索引。

## 13 个语义领域

| 领域 | 示例技能 |
|---|---|
| 金融投资 | westock-data, neodata-financial-search |
| 软件开发与架构 | github, playwright-cli |
| 内容创作与设计 | libtv-skill, novel-writing |
| 通讯与消息 | qq-email, tencent-meeting-skill |
| 数据科学与ML | arxiv-reader, arxiv-watcher |
| WorkBuddy元工具 | find-skills, skill-creator, expert-manager |
| 文档与格式处理 | xlsx, docx, pptx, pdf |
| 云服务与基础设施 | cloudstudio-deploy |
| 商业运营与管理 | — |
| 数据可视化 | — |
| 生命科学与医药 | — |
| 游戏开发 | — |
| 学术与科研 | arxiv-reader, arxiv-watcher |

## 执行流程

1. AI 收到用户请求 → 识别为 "技能查找" 意图 → 加载本 skill
2. 运行 `scripts/bootstrap.py "<用户查询>"` → 自动建索引（若需要）+ 路由查询
3. 读取 stdout 输出的 JSON 结果
4. 解析 `matched_domains`、`skills` 列表
5. 告知用户匹配到哪些领域，列出 top-k 技能
6. 如用户选择某个技能 → 加载该技能执行任务

## 输出格式

```json
{
  "matched_domains": [{"id": "finance_investment", "name": "金融投资"}],
  "expanded_domains": [{"id": "data_visualization", "name": "数据可视化"}],
  "skill_count": 42,
  "skills": [
    {"name": "westock-data", "primary_domain_name": "金融投资", "description": "..."},
    ...
  ]
}
```

## 依赖

- Python 3.8+
- PyYAML（仅用于解析 SKILL.md frontmatter）
- 无外部 API，纯本地运行

## 跨平台移植

本技能设计为在任意 Agent 工具中使用：
1. 将 `skill-finder/` 目录复制到目标环境的 skills 目录
2. 首次运行时自动扫描目标环境的 SKILL.md 建立索引
3. 如需适配非 WorkBuddy 平台，修改 `SKILL_SCAN_PATHS` 中的扫描路径即可
