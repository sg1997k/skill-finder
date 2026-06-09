# Skill Finder — Semantic Domain Knowledge Graph Router

## TL;DR

A **self-bootstrapping semantic skill discovery system**. First run auto-builds a domain knowledge graph index; subsequent queries find skills via natural language in < 1ms. No embedding API. Purely local. Works across platforms.

## The Problem

> "I have a task to do, but with 100+ skills installed, I don't know which one to use."

Traditional keyword search (`find-skills`) hits a wall:
- "Is this stock in a bubble?" → won't find the "reflexivity & bubble detection" skill
- "Analyze financial reports" → won't connect `xlsx` + `westock-data`
- Scanning 1800+ market skills linearly → slow, imprecise
- Cross-domain workflows (analyze data then visualize) → must be manually chained

## The Approach

**Don't make users find skills. Let skills declare their semantic domain, then route.**

```
User query: "Analyze A-share consumer sector, draw a chart"

Layer 1 — Domain routing (keyword hit, < 1ms)
  "A-share" "sector" "trend" → hits [Finance & Investment]
  "draw chart" → hits [Data Visualization]

Layer 2 — Graph expansion (adjacent domains auto-join)
  Finance → adjacent → Business Ops, Data Science, Data Viz
  Data Viz → adjacent → Content Design, Finance, Software Dev
  Candidates: 1836 → ~340 (81% reduction)

Layer 3 — In-domain ranking (description matching)
  Rank 340 candidates by relevance → return top-k
```

## 13 Semantic Domains

Auto-discovered from 1,836 marketplace skills (not pre-defined):

| Domain | Skills | Examples |
|---|---|---|
| Finance & Investment | 376 | westock-data, neodata-financial-search |
| Software Development | 300 | github, playwright-cli |
| Content Creation & Design | 209 | libtv-skill, novel-writing |
| Communication & Messaging | 185 | qq-email, tencent-meeting-skill |
| Life Sciences & Medicine | 132 | — |
| Data Science & ML | 108 | arxiv-reader, arxiv-watcher |
| WorkBuddy Meta-tools | 103 | find-skills, skill-creator |
| Document Processing | 98 | xlsx, docx, pptx, pdf |
| Cloud & Infrastructure | 83 | cloudstudio-deploy |
| Data Visualization | 53 | — |
| Business Operations | 52 | — |
| Academic Research | 46 | arxiv-reader |
| Game Development | 42 | — |

## Installation

```bash
# Option 1: As a WorkBuddy skill
git clone https://github.com/YOUR_USERNAME/skill-finder.git \
  ~/.workbuddy/skills/skill-finder
```

```bash
# Option 2: Standalone (any agent tool)
git clone https://github.com/YOUR_USERNAME/skill-finder.git
cd skill-finder
python scripts/bootstrap.py "analyze stock financials"
```

## Usage

### In WorkBuddy

Just ask naturally:
- "Find me a skill for stock analysis"
- "Is there a skill for processing PDF tables?"
- "What skills can help me write a novel?"

The AI loads `skill-finder`, runs the route query, and returns matching skills.

### CLI

```bash
# Route a query
python scripts/bootstrap.py "analyze A-share consumer sector trends"

# View domain statistics
python scripts/bootstrap.py --stats

# List domain adjacency
python scripts/bootstrap.py --list-domains

# Force rebuild index
python scripts/bootstrap.py --rebuild
```

### Output Format

```json
{
  "matched_domains": [
    {"id": "finance_investment", "name": "Finance & Investment"}
  ],
  "expanded_domains": [
    {"id": "data_visualization", "name": "Data Visualization"}
  ],
  "skill_count": 42,
  "skills": [
    {
      "name": "westock-data",
      "primary_domain_name": "Finance & Investment",
      "description": "Query A-share, HK, US stock/index/ETF data..."
    }
  ]
}
```

## Self-Bootstrapping

**No manual initialization needed.** On first run:

1. Scans `~/.workbuddy/skills/`, `~/.workbuddy/plugins/marketplaces/`, etc. for all `SKILL.md` files
2. Extracts YAML frontmatter from each → `name` + `description`
3. Classifies into 13 semantic domains using keyword rules (no LLM calls, sub-second)
4. Builds domain adjacency graph (from skill co-classification patterns)
5. Saves to `data/skill_domains.json`

Subsequent queries hit the cache directly (milliseconds). New skills are detected via mtime and incrementally re-indexed.

## Cross-Platform Portability

`skill-finder` is platform-agnostic. To use in another agent tool:

1. Copy the `skill-finder/` directory to the target environment
2. Edit `SKILL_SCAN_PATHS` in `scripts/bootstrap.py` to point to the target platform's skill directories
3. First run auto-builds the index

Currently scanned paths (existence auto-detected):
- `~/.workbuddy/skills/`
- `~/.workbuddy/connectors/skills/`
- `~/.workbuddy/plugins/marketplaces/`
- `~/.codebuddy/skills/`
- `~/.codebuddy/plugins/`

## Dependencies

- Python 3.8+
- Zero pip packages (uses built-in string parsing, no PyYAML needed)
- Zero external API calls
- Index size: ~200KB (for 1,800 skills)
- Query latency: < 1ms

## vs. find-skills

| Dimension | find-skills | skill-finder |
|---|---|---|
| Matching | Keywords → npm registry | Semantic domain → routing + graph |
| Index | None | Local 200KB knowledge graph |
| Latency | Seconds (npx overhead) | < 1ms |
| Miss rate | High | Low (domain routing covers generalizations) |
| Cross-domain | Not supported | Graph adjacency auto-expansion |
| Offline | No | Yes |

## Custom Domains

To adapt for industry-specific skill collections, edit three config blocks in `scripts/bootstrap.py`:

1. `DOMAINS[].keywords` — domain membership rules
2. `DOMAIN_ROUTING[].trigger` — query routing rules
3. `DOMAIN_ADJACENCY` — domain adjacency graph

## Architecture

```
skill-finder/
├── SKILL.md                # WorkBuddy skill definition
├── README.md               # Chinese documentation
├── README_EN.md            # This file
├── scripts/
│   └── bootstrap.py        # Self-bootstrapping script (index + route)
├── data/
│   └── skill_domains.json  # Runtime-generated domain index
└── .gitignore
```

## Future Directions

- [ ] Embedding-based semantic fallback when KG routing returns empty
- [ ] Multi-skill orchestration: auto-recommend "use A to analyze, then B to visualize" chains
- [ ] User feedback learning: preferred skills bubble up for similar queries
- [ ] Incremental marketplace discovery: auto-index newly installed skills
