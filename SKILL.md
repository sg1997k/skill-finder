---
name: skill-finder
description: >
  智能技能发现与路由系统。使用语义领域知识图谱替代关键词匹配，实现自然语言到技能的精准路由。
  首次运行时自动扫描本地所有 SKILL.md 建立领域索引（自举），之后查询命中速度 < 1ms。
  触发场景：用户需要找技能、不确定用什么技能、询问"有什么技能可以..."、想发现新技能。
  支持领域扩展：命中文档处理领域后自动扩展到内容创作、数据可视化等相邻领域。
  典型查询："帮我分析财报" → 命中金融投资领域 → 推荐 westock-data 等技能。
version: 1.1.0
agent_created: true
---

# Skill Finder — 操作手册

## 你的角色

你是一个能够**自主完成任务的 Agent**。当你发现自己没有直接完成用户请求所需的技能时，使用 skill-finder 寻找合适的技能，**然后自动加载并执行**，全程不打断用户。

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

---

## 执行步骤（严格按顺序）

### Step 1：运行路由脚本，获取候选技能

```bash
# SKILL_DIR 是本 skill 所在目录，即 skill-finder/ 的绝对路径
python {SKILL_DIR}/scripts/bootstrap.py "<用户原始请求>"
```

脚本自动处理：
- **首次运行**：扫描本地全部 SKILL.md → 建立领域索引 → 执行查询（约 5-10 秒）
- **已有索引**：直接查询（< 1 秒）
- **输出**：JSON 格式的候选技能列表（见下方输出格式）

### Step 2：解读结果，做出决策

拿到 JSON 后，按以下决策树执行：

```
skill_count == 0 ?
  → 告知用户：未找到匹配技能，尝试扩展关键词后重搜
  → 结束

skill_count >= 1 ?
  → 取 skills[0]（第一个，得分最高）
  → 检查本地是否已安装：
      已安装（~/.workbuddy/skills/ 中存在同名目录）?
        → 直接加载该 skill，继续执行用户原始请求
        → 无需告知用户"我找到了一个技能"，直接做

      未安装?
        → 告知用户：找到了 {skill_name}，正在安装...
        → 执行安装（见 Step 3）
        → 安装完成后加载并执行用户原始请求

skill_count >= 3 且 skills[0].score 与 skills[1].score 差距 < 0.1 ?
  （多个技能得分接近，确实需要用户选择）
  → 展示 top-3，简短说明各自用途，请用户选择
```

**原则：只有在真正无法判断时才询问用户。大多数情况下直接选第一个。**

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
安装完成后 → 调用 Skill 工具，传入 skill_name
→ 技能加载成功后，继续执行用户的原始请求
→ 整个过程用户看到的是"任务在推进"，而不是"我需要先去找工具"
```

---

## 输出格式（bootstrap.py 的 stdout）

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
      "description": "查询A股、港股、美股个股/指数/ETF的详细数据...",
      "score": 0.91
    },
    {
      "name": "neodata-financial-search",
      "primary_domain_name": "金融投资",
      "description": "...",
      "score": 0.74
    }
  ]
}
```

---

## 判断"已安装"的方式

```bash
# 技能目录存在即视为已安装
ls ~/.workbuddy/skills/{skill_name}/ 2>/dev/null && echo "installed" || echo "not_installed"
```

---

## 13 个语义领域

| 领域 ID | 领域名称 | 典型技能 |
|---|---|---|
| finance_investment | 金融投资 | westock-data, neodata-financial-search |
| software_dev | 软件开发与架构 | github, playwright-cli |
| content_creation | 内容创作与设计 | libtv-skill, novel-writing |
| communication | 通讯与消息 | qq-email, tencent-meeting-skill |
| data_science | 数据科学与ML | arxiv-reader, arxiv-watcher |
| workbuddy_meta | WorkBuddy元工具 | skill-finder, skill-creator, expert-manager |
| document | 文档与格式处理 | xlsx, docx, pptx, pdf |
| cloud_infra | 云服务与基础设施 | cloudstudio-deploy |
| biz_ops | 商业运营与管理 | — |
| visualization | 数据可视化 | — |
| life_science | 生命科学与医药 | — |
| game_dev | 游戏开发 | — |
| academic | 学术与科研 | arxiv-reader, arxiv-watcher |

---

## 失败处理

| 情况 | 处理方式 |
|---|---|
| bootstrap.py 报 ModuleNotFoundError: yaml | 先运行 `pip install pyyaml`，再重试 |
| 脚本找不到任何 SKILL.md | 检查 `SKILL_SCAN_PATHS`，确认路径存在 |
| 输出为空 JSON `{}` | 用户查询过短，引导用户补充描述 |
| 安装失败 | 告知用户技能名，请用户手动安装 |

---

## 自举原理（了解即可，无需手动操作）

首次运行时，`bootstrap.py` 自动：
1. 扫描 `~/.workbuddy/skills/`、`~/.workbuddy/connectors/skills/`、`~/.workbuddy/plugins/marketplaces/` 下所有 SKILL.md
2. 提取每个 skill 的 `name` + `description` 字段
3. 按 13 个语义领域的关键词规则分类
4. 构建领域邻接图（查金融 → 自动扩展数据可视化等相邻域）
5. 缓存到 `data/skill_domains.json`（含 mtime，支持增量更新）

之后每次查询直接走缓存，< 1ms。
