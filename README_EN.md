# Skill Finder — Semantic Skill Discovery & Routing System

## TL;DR

Uses **domain knowledge graph + Embedding semantic vectors** for skill routing: first narrow down by semantic domain (81% reduction), then re-rank within domain using sentence embeddings. Natural language queries in Chinese/English, pure local execution, no external APIs.

---

## Core Approach

**Instead of making users find skills, let skills describe their own semantic domains, then route.**

```
User query: "Analyze A-share consumer sector trends, plot a chart"

Layer 1 — Domain Routing (keyword match, < 1ms)
  "A-share" "sector" "trend" → hit [Finance & Investment]
  "plot" "chart" → hit [Data Visualization]

Layer 2 — Graph Expansion (adjacent domains auto-added)
  Finance & Investment → adjacent → Business Ops, Data Science, Data Viz
  Data Visualization → adjacent → Content Design, Finance, Software Dev
  Reduce from 1877 → ~340 candidates (81% smaller)

Layer 3 — In-Domain Ranking (Embedding semantic matching)
  Rank 340 candidates by embedding cosine similarity → return top-k
  "预约腾讯会议" → tencent-meeting-mcp (0.912)
  "发邮件通知" → qq-mail (0.864)
```

---

## Key Features

### 1. Domain Knowledge Graph Routing
Automatically归纳 semantic domains from all local SKILL.md files (no preset required), build domain adjacency graph. Query hits domains first, then expands to adjacent domains, dramatically narrowing candidate scope.

### 2. Sentence-Transformer Embedding Ranking
Uses `intfloat/multilingual-e5-small` (384-dim, CN/EN support) to compute embedding vectors for all skill descriptions. Query uses cosine similarity for true semantic matching — synonyms and near-synonyms are auto-matched.

### 3. Multi-Intent Auto-Detection & Collaborative Routing
Complex tasks are auto-decomposed into multi-step execution plans:
```
"Analyze financial report and plot K-line chart"
→ Step 1: Finance & Investment domain (westock-data, neodata-financial-search)
→ Step 2: Data Visualization domain (content_design related skills)
```
Execution order follows heuristic: `Research/Input → Analysis → Processing → Visualization → Output`.

### 4. Self-Bootstrapping Index (Zero Config)
First run automatically: scans all SKILL.md → classifies domains → downloads model → computes embeddings → caches index. Subsequent queries load cache directly, seconds-level response. New skills are auto index incrementally.

### 5. Cross-Platform Portable
Does not depend on WorkBuddy-specific interfaces. `scripts/bootstrap.py` runs standalone and adapts to any Agent tool.

---

## 13 Semantic Domains

Auto-induced from 1877 local skills:

| Domain | Description | Typical Skills |
|---|---|---|
| Finance & Investment | Stocks, funds, financial reports, macro economy | westock-data, neodata-financial-search |
| Software Dev & Architecture | Code, Git, API, testing | github, playwright-cli |
| Content Creation & Design | Writing, drawing, video, Novel | libtv-skill, novel-writing |
| Communication & Messaging | Email, meetings, notifications, calendar | qq-mail, tencent-meeting-mcp |
| Life Sciences & Pharma | Genes, drugs, clinical, bioinformatics | — |
| Data Science & ML | ML, statistical analysis, data processing | arxiv-reader |
| WorkBuddy Meta Tools | Skill management, expert packages, installers | find-skills, skill-creator |
| Document & Format Processing | Word/Excel/PPT/PDF | xlsx, docx, pptx, pdf |
| Cloud & Infrastructure | Deployment, servers, databases, cloud | cloudstudio-deploy |
| Data Visualization | Charts, Dashboards, reports | — |
| Business Ops & Management | Projects, HR, sales, OKR | — |
| Academic & Research | Papers, literature, citations, arXiv | arxiv-watcher |
| Game Development | Godot, Unity, Unreal | — |

---

## Installation

```bash
# Method 1: Install as WorkBuddy skill
git clone https://github.com/sg1997k/skill-finder.git \
  ~/.workbuddy/skills/skill-finder

# Method 2: Standalone use (any Agent tool)
git clone https://github.com/sg1997k/skill-finder.git
cd skill-finder
python scripts/bootstrap.py "help me analyze financial report"
```

## Usage

### In WorkBuddy
Simply say in conversation:
- "Help me find a skill to analyze stock trends"
- "Is there a skill for processing PDF tables"
- "I want to write a novel, what skills can I use"

AI auto-loads `skill-finder`, runs routing query, returns matched skill list.

### CLI Commands

```bash
# Route query
python scripts/bootstrap.py "Analyze A-share consumer sector trends"

# Multi-intent query (auto-decompose)
python scripts/bootstrap.py "Analyze financial report and plot K-line chart"

# View domain statistics
python scripts/bootstrap.py --stats

# View domain adjacency
python scripts/bootstrap.py --list-domains

# Force rebuild index
python scripts/bootstrap.py --rebuild
```

### Output Format

```json
{
  "query": "Analyze financial report and plot K-line chart",
  "matched_domains": [
    {"id": "finance_investment", "name": "Finance & Investment"},
    {"id": "data_visualization", "name": "Data Visualization"}
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

## Bootstrapping Mechanism

**No manual initialization needed.** First run auto-completes:

1. Scan all `SKILL.md` files under `~/.workbuddy/skills/`, `~/.workbuddy/plugins/marketplaces/`, etc.
2. Extract YAML frontmatter → `name` + `description`
3. Classify into 13 semantic domains using keyword rules
4. Build domain adjacency graph (based on multi-domain skill relationships)
5. Auto-download `intfloat/multilingual-e5-small` embedding model (~120MB, first time only)
6. Compute 384-dim vectors for all skill descriptions, cache to `data/embeddings.npy`
7. Save to `data/skill_domains.json`

Subsequent queries load cache + model directly, seconds-level response.

---

## Cross-Platform Porting

`skill-finder` is designed to be platform-agnostic. Porting to another Agent tool requires only:

1. Copy `skill-finder/` directory to target environment
2. Modify `SKILL_SCAN_PATHS` in `scripts/bootstrap.py` to point to target platform's skill directories
3. First run auto-builds index

Currently supported scan paths (auto-detected):
- `~/.workbuddy/skills/`
- `~/.workbuddy/connectors/skills/`
- `~/.workbuddy/plugins/marketplaces/`
- `~/.codebuddy/skills/`
- `~/.codebuddy/plugins/`

---

## Dependencies

- Python 3.8+
- `sentence-transformers` (auto-installed)
- `numpy` (auto-installed)
- Zero external API calls
- Embedding model: `intfloat/multilingual-e5-small` (~120MB, auto-downloaded)
- Index size: `skill_domains.json` ~500KB + `embeddings.npy` ~2.7MB (for 1,877 skills)
- Query latency: ~2-3s (including model inference)

---

## Architecture

```
skill-finder/
├── SKILL.md                # WorkBuddy skill definition
├── README.md               # Chinese documentation
├── README_EN.md            # This file
├── scripts/
│   └── bootstrap.py        # Bootstrap script (build index + route query + embedding inference)
├── data/
│   ├── skill_domains.json  # Runtime-generated domain index
│   ├── embeddings.npy      # Skill embedding cache (384-dim × N)
│   └── model/              # Local embedding model (auto-downloaded)
└── .gitignore
```

---

## Test Results

14 scenarios domain routing accuracy: **14/14 = 100%**

| Query | Matched Skill | Embedding Score |
|---|---|---|
| "预约腾讯会议" | tencent-meeting-mcp | 0.912 |
| "发邮件通知团队" | qq-mail | 0.864 |
| "分析A股消费板块走势" | market-overview | 0.877 |
| "分析财报并画K线图" | westock-data | 0.879 |

---

## Future Roadmap

- [x] ✅ Embedding semantic ranking (intfloat/multilingual-e5-small)
- [x] ✅ Multi-intent detection & collaborative routing (execution_plan)
- [ ] User feedback learning: user selects a skill → prioritize similar queries in future
- [ ] Incremental market discovery: auto-index newly installed skills
- [ ] Optional sentence-transformers enhancement: use `all-MiniLM-L6-v2` for further semantic quality improvement
