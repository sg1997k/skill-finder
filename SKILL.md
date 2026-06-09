---
name: skill-finder
description: >
  智能技能发现与路由系统。通过领域知识图谱 + TF-IDF 语义重排序实现自然语言到技能包的精准路由。
  支持多意图查询（如"分析财报并画图"）自动拆解并按执行顺序返回跨领域技能包。
  首次运行自动扫描本地所有 SKILL.md 建立索引（自举），之后查询 < 1ms。
  触发场景：用户需要找技能、不确定用什么技能、任务需要多个技能协作完成。
version: 1.2.0
agent_created: true
---

# Skill Finder — 操作手册

## 你的角色

你是一个能够**自主完成任务的 Agent**。当你发现自己没有直接完成用户请求所需的技能时，使用 skill-finder 寻找合适的技能包，**然后自动加载并按执行顺序依次执行**，全程不打断用户。

**核心原则：不问用户，自己判断，自动执行。**

---

## 何时触发本 skill

以下任一情况，**立即**触发 skill-finder，不等用户说"帮我找技能"：

1. **用户请求超出你当前已加载技能的能力范围**，例如：
   - "帮我分析一只股票" → 你没有股票分析技能
   - "把这个 PDF 转成 Word" → 你没有 PDF 处理技能
   - "帮我预约一个腾讯会议" → 你没有会议管理技能

2. **用户明确询问是否有某类技能**：
   - "你有什么可以做 XX 的技能吗？"
   - "find skill for XX"
   - "有没有技能能帮我..."

3. **你正在执行任务中发现缺少某个工具**（主动寻找，不是放弃）

4. **【新增】用户请求需要多个步骤/多个领域协作完成**：
   - "分析财报并画图表" → 金融分析 + 数据可视化
   - "写代码然后部署上线" → 软件开发 + 云服务
   - 识别出多意图 → 自动触发多技能协作模式

---

## 执行步骤（严格按顺序）

### Step 1：运行路由脚本，获取候选技能

```bash
# SKILL_DIR 是本 skill 所在目录，即 skill-finder/ 的绝对路径
python {SKILL_DIR}/scripts/bootstrap.py "<用户原始请求>"
```

脚本自动处理：
- **首次运行**：扫描本地全部 SKILL.md → 建立领域索引 + TF-IDF 语义库 → 执行查询（约 2-3 秒）
- **已有索引**：直接查询（< 1 秒）
- **输出**：JSON 格式的候选技能列表（见下方输出格式）

### Step 2：解读结果，做出决策

拿到 JSON 后，按以下决策树执行：

```
skill_count == 0 ?
  → 告知用户：未找到匹配技能，尝试扩展关键词后重搜
  → 结束

is_multi_intent == true ?
  → 这是多步骤任务！按 execution_plan 中的顺序执行：
    Step 1: 加载并执行第一个领域的 skill
    Step 2: 将上一步结果传给下一步
    Step 3: 依次完成所有步骤
  → 全程不打断用户，自主完成整个流程

is_multi_intent == false ?
  → skill_count >= 1，取 skills[0]（RAG 得分最高）
  → 检查本地是否已安装：
      已安装（~/.workbuddy/skills/ 中存在同名目录）?
        → 直接加载该 skill，继续执行用户原始请求
        → 无需告知用户"我找到了一个技能"，直接做

      未安装?
        → 告知用户：找到了 {skill_name}，正在安装...
        → 执行安装（见 Step 3）
        → 安装完成后加载并执行用户原始请求

  → skill_count >= 3 且 skills[0].rag_score 与 skills[1].rag_score 差距 < 0.05 ?
    （多个技能得分接近，确实需要用户选择）
    → 展示 top-3，简短说明各自用途，请用户选择
```

**原则：只有在 RAG 得分真正接近时才询问用户。大多数情况下直接选第一个。**

### Step 3：安装未安装的技能（如需要）

```bash
# 方式一：市场缓存中直接复制（速度最快）
MARKET_DIR="~/.workbuddy/plugins/marketplaces"
SKILL_NAME="{skill_name}"
find $MARKET_DIR -type d -name "$SKILL_NAME" | head -1 | xargs -I{} cp -r {} ~/.workbuddy/skills/

# 方式二：市场缓存不存在时，用 npx 安装
npx skills add {skill_name}
```

### Step 4：加载并执行技能

```
单意图：
  安装完成后 → 调用 Skill 工具，传入 skill_name
  → 技能加载成功后，继续执行用户的原始请求

多意图（按 execution_plan 顺序）：
  Step 1: 加载第一个 skill → 执行 → 保存中间结果
  Step 2: 加载第二个 skill → 将中间结果作为输入 → 执行
  Step 3: 依次完成所有步骤
  → 向用户展示最终结果
```

---

## 输出格式（bootstrap.py 的 stdout）

```json
{
  "query": "分析财报并画图表",
  "matched_domains": [
    {"id": "finance_investment", "name": "金融投资"},
    {"id": "data_visualization", "name": "数据可视化"}
  ],
  "expanded_domains": [
    {"id": "finance_investment", "name": "金融投资"},
    {"id": "data_visualization", "name": "数据可视化"},
    {"id": "software_development", "name": "软件开发与架构"}
  ],
  "is_multi_intent": true,
  "execution_plan": [
    {
      "step": 1,
      "domain": "finance_investment",
      "domain_name": "金融投资",
      "skills": ["westock-data", "financial-report"]
    },
    {
      "step": 2,
      "domain": "data_visualization",
      "domain_name": "数据可视化",
      "skills": ["data-visualization"]
    }
  ],
  "skill_count": 8,
  "skills": [
    {
      "name": "westock-data",
      "primary_domain_name": "金融投资",
      "description": "查询A股、港股、美股个股/指数/ETF的详细数据...",
      "rag_score": 0.268
    },
    {
      "name": "financial-report",
      "primary_domain_name": "金融投资",
      "description": "...",
      "rag_score": 0.241
    }
  ]
}
```

**关键字段说明：**
- `is_multi_intent`: 是否为多意图查询
- `execution_plan`: **多意图时必看**——按 Step 顺序执行，每个 Step 对应一个领域
- `rag_score`: TF-IDF 语义相似度得分（0~1，越高越相关）
- `expanded_domains`: 知识图谱扩展后的领域范围

---

## RAG 语义重排序（了解即可）

脚本在域内使用 **TF-IDF + 余弦相似度** 对候选技能做语义重排序：

1. **建索引时**：对所有技能包的 description 建立 TF-IDF 词频-逆文档频率模型
2. **查询时**：将用户 query 和每个 skill 的 description 转为 TF-IDF 向量
3. **排序**：计算余弦相似度，得分高的排前面

**优势**：纯 Python 实现，零外部依赖，无需联网，< 1ms 完成排序。

---

## 13 个语义领域

| 领域 ID | 领域名称 | 执行顺序 | 典型技能 |
|---|---|---|---|
| academic_research | 学术与科研 | 1 | arxiv-reader, arxiv-watcher |
| life_sciences | 生命科学与医药 | 1 | — |
| document_processing | 文档与格式处理 | 2 | xlsx, docx, pptx, pdf |
| finance_investment | 金融投资 | 3 | westock-data, neodata-financial-search |
| data_science_ml | 数据科学与ML | 3 | arxiv-reader, data-analysis |
| software_development | 软件开发与架构 | 3 | github, playwright-cli |
| business_operations | 商业运营与管理 | 4 | — |
| data_visualization | 数据可视化 | 5 | data-visualization, tmap-jsapi-gl |
| content_design | 内容创作与设计 | 5 | libtv-skill, novel-writing |
| communication | 通讯与消息 | 6 | qq-mail, tencent-meeting-skill |
| cloud_infrastructure | 云服务与基础设施 | 6 | cloudstudio-deploy |
| game_development | 游戏开发 | 6 | — |
| workbuddy_meta | WorkBuddy元工具 | 7 | skill-finder, skill-creator |

**执行顺序**用于多意图查询：先执行顺序小的领域，再执行顺序大的领域。
例如"分析财报并画图" = 金融投资(3) → 数据可视化(5)。

---

## 判断"已安装"的方式

```bash
# 技能目录存在即视为已安装
ls ~/.workbuddy/skills/{skill_name}/ 2>/dev/null && echo "installed" || echo "not_installed"
```

---

## 失败处理

| 情况 | 处理方式 |
|---|---|
| bootstrap.py 运行失败 | 确认使用 Python 3.8+；脚本无需任何外部包 |
| 脚本找不到任何 SKILL.md | 检查 `SKILL_SCAN_PATHS`，确认路径存在 |
| 输出 `skill_count: 0` | 用户查询过短，引导用户补充描述 |
| 安装失败 | 告知用户技能名，请用户手动安装 |
| 多意图执行中某一步失败 | 向用户报告已完成步骤 + 失败步骤，询问是否继续 |

---

## 自举原理（了解即可，无需手动操作）

首次运行时，`bootstrap.py` 自动：

1. 扫描 `~/.workbuddy/skills/`、`~/.workbuddy/connectors/skills/`、`~/.workbuddy/plugins/marketplaces/` 下所有 SKILL.md
2. 提取每个 skill 的 `name` + `description` 字段
3. 按 13 个语义领域的关键词规则分类
4. 构建领域邻接图（查金融 → 自动扩展数据可视化等相邻域）
5. 构建 TF-IDF 语义索引（用于域内 RAG 重排序）
6. 缓存到 `data/skill_domains.json`（含 mtime，支持增量更新）

之后每次查询直接走缓存，< 1ms。

---

## CLI 参数（调试用）

```bash
python bootstrap.py "帮我分析财报"       # 路由查询（最常用）
python bootstrap.py --rebuild              # 强制全量重建索引
python bootstrap.py --stats                # 显示各领域统计
python bootstrap.py --list-domains       # 列出领域邻接关系
python bootstrap.py --test-rag             # 测试 RAG 排名质量
```
