# Skill Finder — 语义技能发现与路由系统

## 一句话概述

用**领域知识图谱 + Embedding 语义向量**做技能路由：先通过关键词命中语义领域缩小范围（缩小 81%），再用句子向量做域内精排，中文自然语言查询精准命中目标 skill。纯本地运行，无需外部 API。

---

## 核心思路

**不让用户找 skill，让 skill 描述自己属于什么语义域，然后做路由。**

```
用户查询："分析A股消费板块走势，画个图"

第 1 层 — 领域路由（关键词命中，< 1ms）
  "A股" "板块" "走势" → 命中 [金融投资]
  "画图" → 命中 [数据可视化]

第 2 层 — 图谱扩展（邻接域自动加入）
  金融投资 → 邻接 → 商业运营、数据科学、数据可视化
  数据可视化 → 邻接 → 内容创作、金融投资、软件开发
  候选从 1877 → 约 340（缩小 81%）

第 3 层 — 域内精排（Embedding 语义匹配）
  在 340 个候选中用向量余弦相似度排序 → 返回 top-k
  "预约腾讯会议" → tencent-meeting-mcp (0.912)
  "发邮件通知" → qq-mail (0.864)
```

---

## 核心特性

### 1. 领域知识图谱路由
从本地所有 SKILL.md 中自动归纳语义领域（无需预设），构建领域邻接图。查询时先命中领域，再扩展邻接域，大幅缩小候选范围。

### 2. Sentence-Transformer Embedding 精排
使用 `intfloat/multilingual-e5-small`（384 维，支持中英文）对所有 skill description 计算向量，查询时用余弦相似度做真正的语义匹配。同义词、近义词自动覆盖。

### 3. 多意图自动检测与协作路由
复杂任务自动拆解为多步骤执行计划：
```
"分析财报并画K线图"
→ Step 1: 金融投资域（westock-data, neodata-financial-search）
→ Step 2: 数据可视化域（content_design 相关 skill）
```
执行顺序遵循启发式：`研究/输入 → 分析 → 处理 → 可视化 → 输出`。

### 4. 自举索引（零配置）
首次运行自动完成：扫描所有 SKILL.md → 分类领域 → 下载模型 → 计算向量 → 缓存索引。之后查询直接加载缓存，秒级响应。新增 skill 自动增量更新。

### 5. 跨平台移植
不依赖 WorkBuddy 特定接口，`scripts/bootstrap.py` 可独立运行，适配任何 Agent 工具。

---

## 13 个语义领域

从 1877 个本地 skill 中自动归纳：

| 领域 | 说明 | 典型 skill |
|---|---|---|
| 金融投资 | 股票、基金、财报、宏观经济 | westock-data, neodata-financial-search |
| 软件开发与架构 | 代码、Git、API、测试 | github, playwright-cli |
| 内容创作与设计 | 写作、绘图、视频、 Novel | libtv-skill, novel-writing |
| 通讯与消息 | 邮件、会议、通知、日程 | qq-mail, tencent-meeting-mcp |
| 生命科学与医药 | 基因、药物、临床、生物信息 | — |
| 数据科学与ML | 机器学习、统计分析、数据处理 | arxiv-reader |
| WorkBuddy元工具 | skill 管理、专家包、安装器 | find-skills, skill-creator |
| 文档与格式处理 | Word/Excel/PPT/PDF | xlsx, docx, pptx, pdf |
| 云服务与基础设施 | 部署、服务器、数据库、云 | cloudstudio-deploy |
| 数据可视化 | 图表、Dashboard、报告 | — |
| 商业运营与管理 | 项目、HR、销售、OKR | — |
| 学术与科研 | 论文、文献、引用、arXiv | arxiv-watcher |
| 游戏开发 | Godot、Unity、Unreal | — |

---

## 安装

```bash
# 方式 1：作为 WorkBuddy skill 安装
git clone https://github.com/sg1997k/skill-finder.git \
  ~/.workbuddy/skills/skill-finder

# 方式 2：独立使用（任何 Agent 工具）
git clone https://github.com/sg1997k/skill-finder.git
cd skill-finder
python scripts/bootstrap.py "帮我分析财报"
```

## 使用

### 在 WorkBuddy 中
直接在对话中说：
- "帮我找能分析股票走势的 skill"
- "有没有处理 PDF 表格的 skill"
- "我想写小说，有什么 skill 可以用"

AI 自动加载 `skill-finder`，运行路由查询，返回匹配技能列表。

### CLI 命令

```bash
# 路由查询
python scripts/bootstrap.py "分析A股消费板块走势"

# 多意图查询（自动拆解）
python scripts/bootstrap.py "分析财报并画K线图"

# 查看领域统计
python scripts/bootstrap.py --stats

# 查看领域邻接关系
python scripts/bootstrap.py --list-domains

# 强制重建索引
python scripts/bootstrap.py --rebuild
```

### 输出格式

```json
{
  "query": "分析财报并画K线图",
  "matched_domains": [
    {"id": "finance_investment", "name": "金融投资"},
    {"id": "data_visualization", "name": "数据可视化"}
  ],
  "is_multi_intent": true,
  "execution_plan": [
    {"step": 1, "domain": "finance_investment", "skills": ["westock-data", ...]},
    {"step": 2, "domain": "data_visualization", "skills": [...]}
  ],
  "skill_count": 42,
  "skills": [...]
}
```

---

## 自举机制

**不需要手动初始化。** 首次运行时自动完成：

1. 扫描 `~/.workbuddy/skills/`、`~/.workbuddy/plugins/marketplaces/` 等目录下所有 `SKILL.md`
2. 提取每个文件的 YAML frontmatter → `name` + `description`
3. 用 13 个语义领域的关键词规则做领域分类
4. 构建领域邻接图（基于技能的多域归属关系）
5. 自动下载 `intfloat/multilingual-e5-small` embedding 模型（~120MB，仅首次）
6. 对所有 skill description 计算 384 维向量，缓存到 `data/embeddings.npy`
7. 存为 `data/skill_domains.json`

之后每次查询直接加载缓存 + 模型，秒级响应。

---

## 跨平台移植

`skill-finder` 设计为平台无关。移植到其他 Agent 工具只需：

1. 复制 `skill-finder/` 目录到目标环境
2. 修改 `scripts/bootstrap.py` 中的 `SKILL_SCAN_PATHS` 指向目标平台的 skill 目录
3. 首次运行自动建索引

当前支持的扫描路径（自动检测存在性）：
- `~/.workbuddy/skills/`
- `~/.workbuddy/connectors/skills/`
- `~/.workbuddy/plugins/marketplaces/`
- `~/.codebuddy/skills/`
- `~/.codebuddy/plugins/`

---

## 依赖

- Python 3.8+
- `sentence-transformers`（自动安装）
- `numpy`（自动安装）
- 无外部 API 调用
- Embedding 模型：`intfloat/multilingual-e5-small`（~120MB，自动下载）
- 索引大小：`skill_domains.json` ~500KB + `embeddings.npy` ~2.7MB（1877 个 skill）
- 查询延迟：~2-3 秒（含模型推理）

---

## 架构

```
skill-finder/
├── SKILL.md                # WorkBuddy skill 定义
├── README.md               # 本文档
├── README_EN.md            # English documentation
├── scripts/
│   └── bootstrap.py        # 自举脚本（建索引 + 查路由 + embedding 推理）
├── data/
│   ├── skill_domains.json  # 运行时生成的领域索引
│   ├── embeddings.npy      # 技能向量缓存（384维 × N）
│   └── model/              # 本地 embedding 模型（自动下载）
└── .gitignore
```

---

## 测试结果

14 个场景领域路由准确率：**14/14 = 100%**

| 查询 | 命中 skill | Embedding 得分 |
|---|---|---|
| "预约腾讯会议" | tencent-meeting-mcp | 0.912 |
| "发邮件通知团队" | qq-mail | 0.864 |
| "分析A股消费板块走势" | market-overview | 0.877 |
| "分析财报并画K线图" | westock-data | 0.879 |

---

## 后续演进

- [x] ✅ Embedding 语义精排（intfloat/multilingual-e5-small）
- [x] ✅ 多意图检测与协作路由（execution_plan）
- [ ] 用户反馈学习：用户选择了某个 skill → 该类型查询未来优先推荐
- [ ] 增量市场发现：新 skill 安装后自动加入索引
- [ ] 可选 sentence-transformers 增强：用 `all-MiniLM-L6-v2` 进一步提升语义质量
