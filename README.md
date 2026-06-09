# Skill Finder — 语义领域知识图谱路由

## 一句话概述

一个**自举的语义技能发现系统**。首次运行自动建立领域知识图谱索引，之后用中文自然语言查询就能精准找到技能。不依赖 embedding API，纯本地运行，毫秒级响应。

## 核心问题

> "我有个任务要做，但 WorkBuddy 安装了上百个 skill，我不知道该用哪个。"

传统方案——关键词搜索 `find-skills`——有天然短板：
- "判断这个股票是不是泡沫" ← 搜不到 "反身性与泡沫识别" skill
- "帮我做报表分析" ← 搜不到 `xlsx` + `westock-data`  
- 1800+ market skill 全量扫，精度差、速度慢
- 跨领域组合（先分析数据再画图）需要手动串联

## 核心思路

**不让用户找 skill，让 skill 描述自己的语义域，然后做路由。**

```
用户查询："分析A股消费板块走势，画个图"

第 1 层 — 领域路由（关键词命中，< 1ms）
  "A股" "板块" "走势" → 命中 [金融投资]
  "画图" → 命中 [数据可视化]

第 2 层 — 图谱扩展（邻接域自动加入）
  金融投资 → 邻接 → 商业运营、数据科学、数据可视化
  数据可视化 → 邻接 → 内容创作、金融投资、软件开发
  候选从 1836 → 约 340（缩小 81%）

第 3 层 — 域内精排（描述匹配）
  在 340 个候选中按描述相关性排序 → 返回 top-k
```

## 13 个语义领域

从 1836 个市场 skill 中自动归纳（非预设）：

| 领域 | Skill 数 | 示例 |
|---|---|---|
| 金融投资 | 376 | westock-data, neodata-financial-search |
| 软件开发与架构 | 300 | github, playwright-cli |
| 内容创作与设计 | 209 | libtv-skill, novel-writing |
| 通讯与消息 | 185 | qq-email, tencent-meeting-skill |
| 生命科学与医药 | 132 | — |
| 数据科学与ML | 108 | arxiv-reader, arxiv-watcher |
| WorkBuddy元工具 | 103 | find-skills, skill-creator |
| 文档与格式处理 | 98 | xlsx, docx, pptx, pdf |
| 云服务与基础设施 | 83 | cloudstudio-deploy |
| 数据可视化 | 53 | — |
| 商业运营与管理 | 52 | — |
| 学术与科研 | 46 | arxiv-reader |
| 游戏开发 | 42 | — |

## 安装

```bash
# 方式 1：作为 WorkBuddy skill 安装
# 将 skill-finder/ 目录复制到 ~/.workbuddy/skills/

git clone https://github.com/sg1997k/skill-finder.git \
  ~/.workbuddy/skills/skill-finder
```

```bash
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

AI 会自动加载 `skill-finder`，运行路由查询，返回匹配的技能列表。

### CLI 命令

```bash
# 路由查询
python scripts/bootstrap.py "分析A股消费板块走势"

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
  "matched_domains": [
    {"id": "finance_investment", "name": "金融投资"}
  ],
  "expanded_domains": [
    {"id": "data_visualization", "name": "数据可视化"}
  ],
  "skill_count": 42,
  "skills": [
    {
      "name": "westock-data",
      "primary_domain_name": "金融投资",
      "description": "查询A股、港股、美股个股/指数/ETF的详细数据..."
    }
  ]
}
```

## 自举机制

**不需要手动初始化。** 首次运行时自动完成以下步骤：

1. 扫描 `~/.workbuddy/skills/`、`~/.workbuddy/plugins/marketplaces/` 等目录下所有 `SKILL.md`
2. 提取每个文件的 YAML frontmatter → `name` + `description`
3. 用 13 个语义领域的关键词规则做领域分类（不调 LLM，纯规则，秒级完成）
4. 构建领域邻接图（基于技能的多域归属关系）
5. 存为 `data/skill_domains.json`

之后每次查询直接命中缓存，毫秒级。新增 skill 会被增量检测并自动索引。

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

## 依赖

- Python 3.8+
- **零外部依赖**（无需任何 pip 包，内置 frontmatter 解析器）
- 无外部 API 调用
- 索引大小：约 200KB（1800 个 skill）
- 查询延迟：< 1ms

## 与 find-skills 的对比

| 维度 | find-skills | skill-finder |
|---|---|---|
| 匹配方式 | 关键词 → npx 注册表 | 语义域 → 领域路由 + 图谱扩展 |
| 索引 | 无 | 本地 200KB 知识图谱 |
| 查询延迟 | 秒级（需 npx 调用） | < 1ms |
| 失配率 | 高（"财报"搜不到"westock-data"） | 低（领域路由覆盖泛化需求） |
| 跨领域组合 | 不支持 | 图谱邻接扩展自动关联 |
| 离线可用 | 否 | 是 |

## 定制领域

如果需要适配特定行业的 skill 集合，编辑 `scripts/bootstrap.py` 中的 `DOMAINS` 和 `DOMAIN_ROUTING` 配置即可。三个要点：

1. `DOMAINS[].keywords` — 领域归属判定规则
2. `DOMAIN_ROUTING[].trigger` — 用户查询路由规则  
3. `DOMAIN_ADJACENCY` — 领域邻接图

## 架构

```
skill-finder/
├── SKILL.md                # WorkBuddy skill 定义
├── README.md               # 本文档
├── README_EN.md            # English documentation
├── scripts/
│   └── bootstrap.py        # 自举脚本（建索引 + 查路由）
├── data/
│   └── skill_domains.json  # 运行时生成的领域索引
└── .gitignore
```

## 后续演进方向

- [ ] 领域路由支持 embedding 语义兜底（KG 命中为空时启用）
- [ ] 多 skill 编排：自动推荐"先用 A 分析数据，再用 B 可视化"的协作链
- [ ] 用户反馈学习：用户选择了某个 skill 完成任务 → 该类型查询未来优先推荐
- [ ] 增量市场发现：新 skill 安装后自动加入索引
