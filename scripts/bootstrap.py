#!/usr/bin/env python3
"""
Skill Finder — Self-Bootstrapping Semantic Domain Router with RAG

First run: scans all SKILL.md files, extracts frontmatter, classifies into
semantic domains, builds TF-IDF corpus for in-domain RAG re-ranking,
saves index to data/skill_domains.json.

Subsequent runs: loads cached index, routes query via keyword + graph expansion,
then re-ranks within matched domains using TF-IDF cosine similarity.
Supports multi-intent queries (e.g. "analyze data and draw a chart") by
returning ordered skills from multiple domains.

Usage:
    python bootstrap.py "帮我分析财报"          # Route a query
    python bootstrap.py --rebuild               # Force full rebuild
    python bootstrap.py --stats                 # Show domain statistics
    python bootstrap.py --list-domains          # List all domains
    python bootstrap.py --test-rag              # Test RAG ranking quality
"""

import json
import os
import re
import sys
import time
import math
from collections import Counter, defaultdict
from pathlib import Path

# ── Configuration ──────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
DATA_DIR = SKILL_DIR / "data"
INDEX_FILE = DATA_DIR / "skill_domains.json"
TFIDF_FILE = DATA_DIR / "tfidf_cache.json"

# Paths to scan for SKILL.md files (platform-agnostic)
HOME = Path.home()
SKILL_SCAN_PATHS = [
    HOME / ".workbuddy" / "skills",
    HOME / ".workbuddy" / "connectors" / "skills",
    HOME / ".workbuddy" / "plugins" / "marketplaces",
    HOME / ".codebuddy" / "skills",
    HOME / ".codebuddy" / "plugins",
]

# ── Domain Definitions ─────────────────────────────────────────────────────
DOMAINS = [
    {
        "id": "finance_investment", "name": "金融投资",
        "desc": "股票、基金、投资研究、交易策略、财务分析、风险管理",
        "keywords": {
            "股票": 10, "基金": 10, "投资": 10, "交易": 10, "金融": 10,
            "财报": 10, "财务": 10, "分红": 10, "估值": 10, "选股": 10,
            "仓位": 10, "收益率": 10, "股息": 8, "期货": 8, "CTA": 8,
            "证券": 8, "期权": 8, "对冲": 8, "量化": 8, "IPO": 8,
            "equity": 10, "portfolio": 10, "invest": 10, "trading": 10,
            "financial": 8, "earnings": 10, "dividend": 10, "market": 6,
            "stock": 10, "fund": 10, "bond": 8, "crypto": 8,
            "revenue": 6, "balance sheet": 10, "income statement": 10,
            "cash flow": 10, "GAAP": 8, "valuation": 10, "DCF": 10,
            "analyst": 8, "broker": 8, "thesis": 6, "catalyst": 6,
            "macro": 4, "capital": 6, "returns": 6, "risk": 4,
            "asset": 6, "liability": 6, "equity research": 12,
            "financial model": 12, "journal entry": 10, "SOX": 6,
            "deal": 4, "M&A": 8, "acquisition": 8, "due diligence": 8,
            "credit": 6, "loan": 6, "insurance": 6,
            "报表": 8, "会计": 8, "审计": 6, "预算": 6,
            "position": 6, "持仓": 10, "泡沫": 10, "主线": 10,
            "capital market": 8, "私募": 8, "风投": 8, "VC": 8, "PE": 8,
        }
    },
    {
        "id": "life_sciences", "name": "生命科学与医药",
        "desc": "基因、蛋白质、药物发现、生物信息、医学影像、临床试验",
        "keywords": {
            "基因": 10, "蛋白质": 10, "药物": 10, "生物": 10, "医学": 10,
            "临床": 10, "DNA": 10, "RNA": 10, "酶": 10, "分子": 8,
            "细胞": 8, "疫苗": 8, "DICOM": 12, "genomic": 10,
            "protein": 10, "drug": 10, "bio": 8, "clinical": 10,
            "enzyme": 10, "molecule": 10, "pharma": 10,
            "healthcare": 8, "诊断": 10, "病理": 10, "ISO 13485": 12,
            "genome": 12, "ensembl": 12, "BRENDA": 12, "PubChem": 12,
            "OpenTargets": 12, "sequencing": 10, "pathway": 8,
            "cheminformatics": 10, "QSAR": 10, "featurizer": 8,
            "phylogenetic": 12, "taxonomy": 6, "operons": 12,
            "protocol": 2, "lab": 4, "assay": 8, "screening": 2,
            "molecular": 10, "biotech": 10, "compounds": 8,
            "bioactivity": 10, "ligand": 10, "binding": 6,
        }
    },
    {
        "id": "software_development", "name": "软件开发与架构",
        "desc": "编程语言、框架、API设计、测试、架构、DevOps、代码质量",
        "keywords": {
            "API": 8, "REST": 8, "GraphQL": 8, "React": 10, "Next.js": 10,
            "Vue": 8, "Angular": 8, "TypeScript": 8, "JavaScript": 6,
            "Python": 4, "Rust": 8, "Go": 6, "Java": 6,
            "Docker": 8, "Kubernetes": 8, "microservice": 8, "Spring": 8,
            "JWT": 8, "OAuth": 8, "CI/CD": 8, "Terraform": 12,
            "Istio": 12, "Spark": 6, "LangChain": 10,
            "Solidity": 12, "web3": 12, "smart contract": 12,
            "pytest": 8, "Jest": 8, "Vitest": 8, "TDD": 8,
            "测试": 8, "部署": 8, "架构": 8, "服务网格": 8, "智能合约": 10,
            "app-router": 10, "server component": 10, "测试驱动": 10,
            "framework": 4, "library": 2, "package": 4, "npm": 4,
            "backend": 8, "frontend": 8, "devops": 10, "refactor": 6,
            "debug": 4, "lint": 6, "compiler": 6, "runtime": 4,
            "middleware": 8, "plugin": 4, "extension": 4,
            "Git": 4, "GitHub": 4, "PR": 2, "pull request": 4,
            "code review": 8, "development": 2, "programming": 4,
            "coding": 4, "stack": 2, "full-stack": 6,
            "nextjs": 10, "nodejs": 8, "nestjs": 10, "express": 6,
            "django": 8, "flask": 6, "fastapi": 8,
        }
    },
    {
        "id": "data_science_ml", "name": "数据科学与ML",
        "desc": "机器学习、深度学习、数据处理、统计分析、模型训练",
        "keywords": {
            "机器学习": 10, "深度学习": 10, "神经网络": 10, "模型训练": 10,
            "scikit-learn": 12, "pandas": 10, "polars": 10, "vaex": 10,
            "特征工程": 10, "分类": 6, "回归": 6, "聚类": 8,
            "NLP": 10, "CV": 10, "LLM": 8, "transformer": 10,
            "PyTorch": 12, "TensorFlow": 12, "jupyter": 6,
            "embeddings": 8, "RAG": 10, "向量": 10,
            "machine learning": 12, "deep learning": 12,
            "neural network": 10, "dataset": 4, "dataframe": 6,
            "data analysis": 6, "data science": 10,
            "statistical": 8, "statistics": 8, "regression": 6,
            "clustering": 8, "classification": 6,
            "training": 4, "inference": 6, "fine-tune": 8,
            "data exploration": 8, "data profiling": 8,
            "feature": 6, "predict": 6, "forecast": 4,
            "xgboost": 10, "catboost": 10, "lightgbm": 10,
            "大模型": 8, "AI": 4, "智能": 4,
        }
    },
    {
        "id": "document_processing", "name": "文档与格式处理",
        "desc": "Word/Excel/PPT/PDF处理、Markdown、OCR、文档生成",
        "keywords": {
            "docx": 12, "pptx": 12, "xlsx": 12, "pdf": 10,
            "markdown": 8, "OCR": 10, "word": 8, "excel": 8,
            "powerpoint": 10, "文档": 10, "表格": 6, "幻灯片": 10,
            "documents": 8, "spreadsheet": 8, "presentation": 6,
            "file": 2, "convert": 4, "format": 4, "parse": 4,
            "extract": 2, "rename": 2, "organize": 2,
            "markitdown": 12, "invoice": 4, "receipt": 4,
            "csv": 4, "json": 2, "xml": 4, "html": 2,
            "template": 2, "report": 2,
        }
    },
    {
        "id": "data_visualization", "name": "数据可视化",
        "desc": "图表、仪表盘、地图、Canvas、数据展示",
        "keywords": {
            "图表": 10, "可视化": 10, "dashboard": 10, "仪表盘": 10,
            "Canvas": 8, "map": 6, "地图": 10, "geopandas": 12,
            "plot": 8, "visualization": 8, "绘图": 8, "统计图": 8,
            "echarts": 10, "d3": 10, "chart": 8, "graph": 6,
            "diagram": 6, "流程图": 10, "拓扑": 8, "mind map": 8,
            "svg": 6, "webgl": 8, "three.js": 8, "3D": 4,
            "interactive": 2, "widget": 4, "gauge": 6,
            "tmap": 12, "JSAPI": 8, "GIS": 10, "geographic": 8,
            "treemap": 8, "heatmap": 8, "sankey": 8,
        }
    },
    {
        "id": "communication", "name": "通讯与消息",
        "desc": "邮件、日程、会议、Slack、通知、IM",
        "keywords": {
            "邮件": 12, "email": 12, "日程": 10, "日历": 10, "calendar": 10,
            "Slack": 12, "Teams": 10, "meeting": 6, "通知": 8,
            "通讯": 8, "messaging": 8, "newsletter": 8, "chat": 6,
            "消息": 6, "IM": 10, "wecom": 10, "飞书": 10, "钉钉": 10,
            "notify": 6, "remind": 4, "alert": 4,
            "share": 4, "mention": 6, "DM": 8, "channel": 4,
        }
    },
    {
        "id": "content_design", "name": "内容创作与设计",
        "desc": "写作、图像/视频生成、设计、翻译、配色、UX",
        "keywords": {
            "写作": 10, "文章": 8, "创作": 8, "设计": 8, "图像": 10,
            "视频": 10, "生成": 4, "翻译": 8, "海报": 10, "演讲稿": 10,
            "配色": 10, "创意": 8, "故事": 10, "小说": 10,
            "image": 8, "video": 10, "animation": 10, "generate": 2,
            "palette": 10, "design": 4, "photo": 8, "illustration": 10,
            "UX": 10, "UI": 8, "mockup": 10, "wireframe": 10,
            "prototype": 8, "Figma": 10, "Sketch": 6,
            "typography": 8, "accessibility": 4, "WCAG": 8,
            "brand": 6, "logo": 8, "content": 2, "copy": 4,
            "marketing": 4, "campaign": 6, "social media": 4,
            "thumbnail": 8, "banner": 6, "editor": 2,
            "style": 4, "theme": 4, "color": 4, "font": 4,
            "drawing": 8, "draw": 6, "art": 6, "creative": 6,
        }
    },
    {
        "id": "academic_research", "name": "学术与科研",
        "desc": "论文检索、文献综述、引用分析、科研写作、学术工具",
        "keywords": {
            "论文": 12, "学术": 10, "ArXiv": 12, "文献": 10, "引用": 8,
            "期刊": 8, "research": 6, "paper": 6, "citation": 8,
            "scholar": 8, "综述": 10, "OpenAlex": 12, "PubMed": 12,
            "scientific": 6, "academic": 6, "DOI": 10, "bibliography": 10,
            "preprint": 10, "manuscript": 8, "peer review": 10,
            "publish": 4, "conference": 4, "proceedings": 6,
            "index": 2, "impact factor": 8, "h-index": 8,
            "literature": 4, "knowledge graph": 4,
        }
    },
    {
        "id": "business_operations", "name": "商业运营与管理",
        "desc": "项目管理、敏捷、OKR、审计、法务、合规、HR、运营",
        "keywords": {
            "sprint": 10, "agile": 10, "OKR": 10, "招聘": 10, "简历": 10,
            "发票": 10, "invoice": 10, "合规": 10, "SOX": 10, "HR": 8,
            "入职": 8, "onboarding": 8, "项目管理": 10, "roadmap": 8,
            "RICE": 10, "MoSCoW": 10, "审计": 10, "法律": 10,
            "合同": 10, "税务": 10, "组织": 6, "handoff": 8,
            "on-call": 8, "close": 4, "month-end": 10,
            "workflow": 4, "process": 2, "operations": 6,
            "finance work": 8, "accounting": 6, "reconciliation": 8,
            "closing": 6, "controller": 8, "rollforward": 10,
            "workpaper": 10, "variance": 4, "FP&A": 10,
            "planning": 2, "project management": 8,
            "scrum": 10, "kanban": 8, "standup": 8,
            "legal": 10, "contract": 8, "compliance": 8,
            "risk management": 6, "GRC": 10,
            "due diligence": 8, "dd meeting": 10,
            "internal comm": 8, "memo": 4, "announcement": 6,
            "stakeholder": 4, "executive": 2,
        }
    },
    {
        "id": "cloud_infrastructure", "name": "云服务与基础设施",
        "desc": "CloudBase、AWS、部署、数据库、认证、serverless、CDN",
        "keywords": {
            "cloudbase": 12, "CloudBase": 12, "AWS": 10, "Azure": 10,
            "GCP": 10, "serverless": 10, "部署": 6, "认证": 6,
            "auth": 6, "cloud": 8, "函数计算": 8, "存储": 6, "CDN": 8,
            "hosting": 8, "static site": 8, "边缘": 8, "edge": 6,
            "Firebase": 10, "Supabase": 10, "数据库": 4,
            "database": 2, "sql": 2, "nosql": 6, "mongo": 6,
            "redis": 6, "postgres": 6, "mysql": 6,
            "backend": 4, "server": 2, "deployment": 4,
            "storage": 4, "bucket": 6, "lambda": 8,
            "kubernetes": 6, "container": 4, "orchestration": 4,
            "infrastructure": 6, "networking": 6,
            "VPC": 8, "subnet": 6, "firewall": 4,
        }
    },
    {
        "id": "game_development", "name": "游戏开发",
        "desc": "Godot、Unity、游戏引擎、Shader、2D/3D",
        "keywords": {
            "Godot": 12, "Unity": 12, "Unreal": 12, "游戏": 12,
            "game": 10, "2D": 6, "3D": 4, "shader": 10, "sprite": 10,
            "物理引擎": 10, "game engine": 10, "rendering": 4,
            "animation": 2, "character": 2, "level": 2,
            "asset": 2, "texture": 6, "mesh": 6,
        }
    },
    {
        "id": "workbuddy_meta", "name": "WorkBuddy元工具",
        "desc": "Skill管理、MCP配置、安全审计、插件开发、子代理",
        "keywords": {
            "skill": 8, "plugin": 8, "MCP": 10, "安全审计": 12,
            "模板": 6, "bootstrap": 6, "setup": 2, "CodeBuddy": 10,
            "workbuddy": 10, "marketplace": 8, "creator": 4,
            "expert": 4, "connector": 8, "subagent": 10,
            "spec workflow": 10, "code review": 6,
            "agent": 2, "automation": 2, "prompt": 2,
            "find skills": 12, "install skill": 12,
        }
    },
]

# Domain adjacency graph (edges derived from skill co-classification)
DOMAIN_ADJACENCY = {
    "finance_investment":       ["business_operations", "data_science_ml", "data_visualization"],
    "life_sciences":            ["academic_research", "data_science_ml"],
    "software_development":     ["cloud_infrastructure", "data_science_ml", "workbuddy_meta"],
    "data_science_ml":         ["data_visualization", "software_development", "finance_investment"],
    "document_processing":      ["content_design", "business_operations"],
    "data_visualization":       ["content_design", "finance_investment", "software_development"],
    "communication":            ["business_operations", "workbuddy_meta"],
    "content_design":           ["data_visualization", "document_processing", "software_development"],
    "academic_research":        ["life_sciences", "data_science_ml"],
    "business_operations":       ["finance_investment", "communication", "document_processing"],
    "cloud_infrastructure":     ["software_development", "communication"],
    "game_development":         ["software_development", "content_design"],
    "workbuddy_meta":           ["software_development", "communication"],
}

# Query → domain routing triggers
DOMAIN_ROUTING = {
    "finance_investment": {
        "trigger": ["股票", "基金", "投资", "财报", "交易", "金融", "经济", "市场",
                     "分红", "估值", "选股", "仓位", "宏观", "IPO", "并购", "上市",
                     "stock", "fund", "invest", "market", "finance", "earnings",
                     "portfolio", "trading", "dividend", "valuation",
                     "A股", "港股", "美股", "板块", "走势", "行情",
                     "消费板块", "科技股", "蓝筹", "成长股",
                     "季报", "年报", "业绩", "ROE", "PE", "PB", "EPS",
                     "分析", "预测", "趋势", "大涨", "大跌", "崩盘", "泡沫",
                     "主线", "题材", "热点", "龙头"],
    },
    "data_visualization": {
        "trigger": ["画图", "图表", "可视化", "仪表盘", "作图", "绘图", "折线图",
                     "柱状图", "饼图", "k线图", "趋势图", "map", "chart",
                     "visualize", "graph", "plot", "dashboard"],
    },
    "document_processing": {
        "trigger": ["word", "excel", "ppt", "pdf", "文档", "表格", "幻灯片",
                     "docx", "xlsx", "pptx", "转格式", "OCR", "markdown"],
    },
    "content_design": {
        "trigger": ["设计", "海报", "配色", "画", "logo", "UI", "UX", "图",
                     "图片", "视频", "生成", "创作", "文章", "写", "翻译",
                     "design", "image", "video", "create", "generate"],
    },
    "software_development": {
        "trigger": ["编程", "代码", "开发", "API", "框架", "测试", "部署",
                     "重构", "debug", "架构", "接口", "code", "program",
                     "develop", "framework", "test", "deploy", "refactor"],
    },
    "data_science_ml": {
        "trigger": ["机器学习", "深度学习", "模型", "训练", "预测", "数据分析",
                     "统计分析", "聚类", "回归", "分类", "ML", "AI", "pandas",
                     "特征", "数据集", "machine learning", "train", "predict"],
    },
    "business_operations": {
        "trigger": ["项目", "管理", "审计", "法律", "合同", "合规", "发票",
                     "HR", "招聘", "简历", "OKR", "agile", "sprint", "流程",
                     "运营", "manage", "project", "audit", "legal", "hr"],
    },
    "communication": {
        "trigger": ["邮件", "通知", "消息", "通讯", "日程", "会议记录",
                     "email", "notify", "message", "calendar", "meeting"],
    },
    "academic_research": {
        "trigger": ["论文", "学术", "文献", "期刊", "arXiv", "引用", "综述",
                     "research", "paper", "citation", "academic", "publish"],
    },
    "cloud_infrastructure": {
        "trigger": ["部署", "上线", "发布", "服务器", "数据库", "云", "CDN",
                     "deploy", "cloud", "server", "host", "database", "CDN"],
    },
    "game_development": {
        "trigger": ["游戏", "godot", "unity", "unreal", "game", "shader", "sprite"],
    },
    "life_sciences": {
        "trigger": ["基因", "蛋白质", "药物", "医学", "临床", "生物",
                     "genomic", "protein", "drug", "clinical", "bio", "pharma"],
    },
}

MIN_SCORE = 8

# ── Zero-Dependency TF-IDF Semantic Similarity ────────────────────────
#
# Tokenizer: splits on word boundaries + extracts Chinese characters.
# IDF is computed once at index build time and cached.
# Cosine similarity of TF-IDF vectors gives semantic ranking.
# Handles both Chinese and English text.

def tokenize(text):
    """
    Tokenize text into words + Chinese character bigrams.
    Uses character-level bigrams for Chinese (captures more semantic signal
    than single chars), and word-level tokens for ASCII.
    Returns a list of tokens.
    """
    if not text:
        return []
    text = text.lower()
    tokens = []

    # Extract ASCII words (English, numbers, coding terms)
    for word in re.findall(r'[a-z0-9_]+', text):
        if len(word) >= 2:
            tokens.append(word)

    # Extract Chinese characters
    chinese_chars = [ch for ch in text if '\u4e00' <= ch <= '\u9fff']

    # Add single Chinese chars
    for ch in chinese_chars:
        tokens.append(ch)

    # Add Chinese character bigrams (captures local word semantics)
    for i in range(len(chinese_chars) - 1):
        tokens.append(chinese_chars[i] + chinese_chars[i + 1])

    return tokens


def build_idf(skills):
    """
    Build IDF (Inverse Document Frequency) from all skill descriptions.
    Returns: { token: idf_value }
    """
    N = len(skills)
    doc_freq = Counter()

    for skill in skills:
        desc = skill.get('description', '') or ''
        name = skill.get('name', '') or ''
        text = desc + ' ' + name
        tokens = set(tokenize(text))
        for t in tokens:
            doc_freq[t] += 1

    idf = {}
    for token, df in doc_freq.items():
        if df > 0:
            idf[token] = math.log((N + 1) / (df + 1)) + 1  # smooth
    return idf


def tfidf_vector(text, idf):
    """
    Compute TF-IDF vector as a Counter { token: tfidf }.
    Only includes tokens present in the IDF vocabulary.
    """
    tokens = tokenize(text)
    if not tokens:
        return Counter()
    tf = Counter(tokens)
    max_tf = max(tf.values())
    vec = Counter()
    for t, cnt in tf.items():
        if t in idf:
            tf_norm = cnt / max_tf
            vec[t] = tf_norm * idf[t]
    return vec


def cosine_similarity(vec1, vec2):
    """Cosine similarity between two Counter vectors."""
    if not vec1 or not vec2:
        return 0.0
    dot = sum(vec1[t] * vec2.get(t, 0) for t in vec1)
    norm1 = math.sqrt(sum(v * v for v in vec1.values()))
    norm2 = math.sqrt(sum(v * v for v in vec2.values()))
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return dot / (norm1 * norm2)


def semantic_rank(query, skills, idf, top_n=20):
    """
    Rank skills by semantic similarity to the query using TF-IDF cosine.
    Returns list of (skill, score) sorted by descending score.
    """
    query_vec = tfidf_vector(query, idf)
    if not query_vec:
        return [(s, 0.0) for s in skills]

    scored = []
    for skill in skills:
        desc = skill.get('description', '') or ''
        name = skill.get('name', '') or ''
        text = desc + ' ' + name
        skill_vec = tfidf_vector(text, idf)
        sim = cosine_similarity(query_vec, skill_vec)
        scored.append((skill, sim))

    scored.sort(key=lambda x: -x[1])
    return scored[:top_n]


# ── YAML Frontmatter Extraction ──────────────────────────────────────────

def extract_frontmatter(filepath):
    """Extract YAML frontmatter from a SKILL.md file without pyyaml dependency."""
    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
    except Exception:
        return None

    if not content.startswith('---'):
        return None

    parts = content.split('---', 2)
    if len(parts) < 3:
        return None

    frontmatter_text = parts[1]
    fm = {}
    for line in frontmatter_text.strip().split('\n'):
        if ':' in line:
            key, _, value = line.partition(':')
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            fm[key] = value

    return fm


def scan_skills():
    """Scan all SKILL.md files in configured paths."""
    skills = []
    seen_paths = set()

    for scan_path in SKILL_SCAN_PATHS:
        if not scan_path.exists():
            continue
        for root, _, files in os.walk(scan_path):
            for f in files:
                if f == 'SKILL.md':
                    filepath = Path(root) / f
                    if str(filepath) in seen_paths:
                        continue
                    seen_paths.add(str(filepath))

                    fm = extract_frontmatter(filepath)
                    if fm and 'name' in fm and fm['name']:
                        skills.append({
                            'name': fm['name'],
                            'description': fm.get('description', ''),
                            'path': str(filepath),
                            'mtime': filepath.stat().st_mtime,
                        })

    return skills


# ── Domain Classification ─────────────────────────────────────────────────────

def classify_skill(desc, name):
    """Classify a skill into primary + secondary domains."""
    text = (name + ' ' + desc).lower()
    scores = []

    for domain in DOMAINS:
        score = 0
        for kw, weight in domain['keywords'].items():
            if kw.lower() in text:
                score += weight
        if score > 0:
            scores.append((score, domain['id']))

    scores.sort(reverse=True)

    if not scores or scores[0][0] < MIN_SCORE:
        return 'other', []

    primary = scores[0][1]
    secondary = [s[1] for s in scores[1:3] if s[0] >= MIN_SCORE]
    return primary, secondary


def build_index(force=False):
    """Build or rebuild the domain index, including TF-IDF cache."""
    if not force and INDEX_FILE.exists():
        cached = _load_index()
        if cached:
            return cached

    print("Building skill domain index...", file=sys.stderr)
    t0 = time.time()

    skills = scan_skills()
    print(f"Scanned {len(skills)} SKILL.md files", file=sys.stderr)

    domain_counts = Counter()
    results = []

    for skill in skills:
        primary, secondary = classify_skill(skill['description'], skill['name'])
        domain_counts[primary] += 1
        domain_name = next((d['name'] for d in DOMAINS if d['id'] == primary), '其他')
        results.append({
            'name': skill['name'],
            'description': skill['description'],
            'path': skill['path'],
            'mtime': skill['mtime'],
            'primary_domain': primary,
            'primary_domain_name': domain_name,
            'secondary_domains': secondary,
        })

    # Build TF-IDF IDF cache for semantic ranking
    print("Building TF-IDF semantic index...", file=sys.stderr)
    idf = build_idf(results)
    print(f"TF-IDF vocabulary size: {len(idf)}", file=sys.stderr)

    output = {
        'built_at': time.time(),
        'total_skills': len(skills),
        'domains': [{'id': d['id'], 'name': d['name'], 'description': d['desc']} for d in DOMAINS],
        'skills': results,
        'summary': {d['id']: {'name': d['name'], 'count': domain_counts[d['id']]} for d in DOMAINS},
        'other_count': domain_counts['other'],
        'tfidf_idf': idf,   # cached IDF for query-time ranking
    }

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(INDEX_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    elapsed = time.time() - t0
    print(f"Index built in {elapsed:.1f}s ({len(skills)} skills, {sum(1 for c in domain_counts.values() if c > 0)} domains)",
          file=sys.stderr)

    return output


def _load_index():
    """Load cached index if valid."""
    try:
        with open(INDEX_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


# ── Multi-Intent Detection ────────────────────────────────────────────────

# Domain execution order heuristic:
# Research/Input → Analysis → Processing → Visualization → Output
DOMAIN_EXEC_ORDER = {
    "academic_research":        1,
    "life_sciences":            1,
    "document_processing":      2,
    "finance_investment":       3,
    "data_science_ml":         3,
    "software_development":     3,
    "business_operations":      4,
    "data_visualization":      5,
    "content_design":          5,
    "communication":           6,
    "cloud_infrastructure":     6,
    "game_development":        6,
    "workbuddy_meta":          7,
}


def detect_multi_intent(query, domain_scores):
    """
    Detect if the query has multiple intents requiring multiple skills.
    Returns list of (domain_id, score) sorted by execution order.
    Always returns a list of tuples, never a dict.
    """
    items = list(domain_scores.items())
    if len(items) <= 1:
        return items

    # Sort by execution order (not by score) for multi-intent
    ordered = sorted(items, key=lambda x: DOMAIN_EXEC_ORDER.get(x[0], 99))
    return ordered


# ── Query Routing (Enhanced) ─────────────────────────────────────────────

def route_query(query, data, expand_depth=1, use_rag=True):
    """
    Route a query to domains and return matching skills.
    Enhanced with:
      - Multi-intent detection (returns skills from multiple domains in exec order)
      - In-domain RAG re-ranking (TF-IDF semantic similarity)
    """
    query_lower = query.lower()

    # Step 1: Match query to domains via trigger keywords
    domain_scores = {}
    for domain_id, config in DOMAIN_ROUTING.items():
        score = 0
        for kw in config['trigger']:
            if kw.lower() in query_lower:
                score += 1
        if score > 0:
            domain_scores[domain_id] = score

    if not domain_scores:
        return {
            'matched_domains': [],
            'expanded_domains': [],
            'skill_count': 0,
            'skills': [],
            'message': '未匹配到领域。尝试用更具体的关键词描述你的需求。'
        }

    # Step 2: Determine if multi-intent
    sorted_domains = detect_multi_intent(query, domain_scores)
    primary_ids = [d[0] for d in sorted_domains]

    # Step 3: Expand to adjacent domains (KG walk)
    expanded = set(primary_ids)
    for _ in range(expand_depth):
        new_domains = set()
        for d in expanded:
            neighbors = DOMAIN_ADJACENCY.get(d, [])
            for n in neighbors:
                if n not in expanded:
                    new_domains.add(n)
        expanded.update(new_domains)

    # Step 4: Collect skills in matched domains (in execution order for multi-intent)
    domain_name_map = {d['id']: d['name'] for d in data['domains']}
    all_skills = []
    seen = set()
    execution_plan = []

    # For multi-intent: return top skills from each matched domain in order
    if len(primary_ids) > 1:
        for domain_id in primary_ids:
            domain_skills = [s for s in data['skills']
                            if s['primary_domain'] == domain_id and s['name'] not in seen]
            # RAG re-ranking within domain
            if use_rag and domain_skills:
                idf = data.get('tfidf_idf', {})
                ranked = semantic_rank(query, domain_skills, idf, top_n=5)
                step_skills = []
                for skill, score in ranked:
                    if skill['name'] not in seen:
                        seen.add(skill['name'])
                        skill['rag_score'] = round(score, 4)
                        step_skills.append(skill)
                        all_skills.append(skill)
            else:
                step_skills = []
                for s in domain_skills[:5]:
                    if s['name'] not in seen:
                        seen.add(s['name'])
                        step_skills.append(s)
                        all_skills.append(s)
            execution_plan.append({
                'step': len(execution_plan) + 1,
                'domain': domain_id,
                'domain_name': domain_name_map.get(domain_id, domain_id),
                'skills': [s['name'] for s in step_skills],
            })
    else:
        # Single intent: collect all skills in expanded domains, RAG re-rank
        for skill in data['skills']:
            if skill['primary_domain'] in expanded:
                if skill['name'] not in seen:
                    seen.add(skill['name'])
                    all_skills.append(skill)

        if use_rag and all_skills:
            idf = data.get('tfidf_idf', {})
            ranked = semantic_rank(query, all_skills, idf, top_n=20)
            all_skills = []
            for skill, score in ranked:
                skill['rag_score'] = round(score, 4)
                all_skills.append(skill)

    return {
        'query': query,
        'matched_domains': [{'id': d, 'name': domain_name_map.get(d, d)} for d in primary_ids],
        'expanded_domains': [{'id': d, 'name': domain_name_map.get(d, d)} for d in sorted(expanded)],
        'is_multi_intent': len(primary_ids) > 1,
        'execution_plan': execution_plan,   # NEW: ordered steps for multi-intent
        'skill_count': len(all_skills),
        'skills': all_skills[:50],
    }


# ── CLI ────────────────────────────────────────────────────────────────────

def format_results(result, top_n=10):
    """Pretty-print routing results."""
    if 'message' in result:
        return result['message']

    md = result['matched_domains']
    ed = result['expanded_domains']
    multi = result.get('is_multi_intent', False)

    lines = []
    lines.append(f"[主领域] 直接命中: {', '.join(d['name'] for d in md)}")
    lines.append(f"[扩展域] 邻接扩展: {', '.join(d['name'] for d in ed)}")
    if multi:
        lines.append("[模式] 多意图检测：按执行顺序返回跨领域 skill")
    lines.append(f"[候选] skill 数: {result['skill_count']} (从 1836 缩小到 {result['skill_count']})")
    lines.append("")
    lines.append(f"Top {top_n} skills in matched domains:")

    for s in result['skills'][:top_n]:
        domain_name = s.get('primary_domain_name', '')
        secondary = ', '.join(s.get('secondary_domains', []))
        extra = f" [also: {secondary}]" if secondary else ""
        rag = s.get('rag_score', '')
        rag_str = f" [RAG:{rag:.3f}]" if rag else ""
        lines.append(f"  * {s['name']} ({domain_name}{extra}){rag_str}")

    if len(result['skills']) > top_n:
        lines.append(f"  ... and {len(result['skills']) - top_n} more")

    return "\n".join(lines)


def print_stats(data):
    """Print domain statistics."""
    print("=" * 60)
    print("  Skill Finder — Domain Statistics")
    print("=" * 60)
    print(f"  Total skills indexed: {data['total_skills']}")
    print()
    for d in data['domains']:
        cnt = data['summary'][d['id']]['count']
        name = d['name']
        print(f"  {name:20s}  {cnt:5d} skills")
    print(f"  {'其他':20s}  {data['other_count']:5d} skills")
    idf_size = len(data.get('tfidf_idf', {}))
    print(f"\n  TF-IDF vocabulary: {idf_size} tokens")


def print_domains(data):
    """List all domains with adjacency."""
    for d in data['domains']:
        neighbors = DOMAIN_ADJACENCY.get(d['id'], [])
        dn_map = {dd['id']: dd['name'] for dd in data['domains']}
        nbr_names = [dn_map.get(n, n) for n in neighbors]
        print(f"{d['name']}  <->  {', '.join(nbr_names)}")


def test_rag_quality(data):
    """Test RAG ranking quality with sample queries."""
    test_cases = [
        ("分析A股消费板块走势", "finance_investment", ["westock-data", "neodata-financial-search"]),
        ("画个K线图", "data_visualization", ["data_visualization"]),
        ("帮我发一封邮件", "communication", ["qq-mail"]),
        ("写一个React登录组件", "software_development", ["software_development"]),
        ("分析财报并画图表", "finance_investment", ["finance_investment", "data_visualization"]),
    ]

    print("=" * 60)
    print("  RAG Ranking Quality Test")
    print("=" * 60)

    for query, expected_domain, _ in test_cases:
        print(f"\nQuery: {query}")
        result = route_query(query, data)
        domains = [d['name'] for d in result['matched_domains']]
        print(f"  Matched domains: {domains}")
        print(f"  Skills returned: {result['skill_count']}")
        if result['skills']:
            top3 = [(s['name'], s.get('rag_score', 0)) for s in result['skills'][:3]]
            for name, score in top3:
                score_str = f"{score:.3f}" if score else "N/A"
                print(f"    - {name} (RAG:{score_str})")


def main():
    if len(sys.argv) < 2:
        print("Usage: python bootstrap.py <query> | --rebuild | --stats | --list-domains | --test-rag", file=sys.stderr)
        sys.exit(1)

    arg = sys.argv[1]

    if arg == '--rebuild':
        data = build_index(force=True)
        print_stats(data)

    elif arg == '--stats':
        data = build_index()
        print_stats(data)

    elif arg == '--list-domains':
        data = build_index()
        print_domains(data)

    elif arg == '--test-rag':
        data = build_index()
        test_rag_quality(data)

    else:
        query = ' '.join(sys.argv[1:])
        data = build_index()
        result = route_query(query, data)
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
