#!/usr/bin/env python3
"""
Skill Finder — Self-Bootstrapping Semantic Domain Router with Embedding RAG

First run: scans all SKILL.md files, extracts frontmatter, classifies into
semantic domains, builds sentence-transformer embeddings for semantic ranking,
saves index to data/skill_domains.json + data/embeddings.npy.

Subsequent runs: loads cached index + embeddings, routes query via keyword + graph
expansion, then re-ranks within matched domains using embedding cosine similarity.
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
import subprocess
from collections import Counter, defaultdict
from pathlib import Path

# ── Configuration ──────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
DATA_DIR = SKILL_DIR / "data"
INDEX_FILE = DATA_DIR / "skill_domains.json"
EMBEDDING_FILE = DATA_DIR / "embeddings.npy"

# Paths to scan for SKILL.md files (platform-agnostic)
HOME = Path.home()
SKILL_SCAN_PATHS = [
    HOME / ".workbuddy" / "skills",
    HOME / ".workbuddy" / "connectors" / "skills",
    HOME / ".workbuddy" / "plugins" / "marketplaces",
    HOME / ".codebuddy" / "skills",
    HOME / ".codebuddy" / "plugins",
]

# ── Embedding Model Config ─────────────────────────────────────────
# Multilingual model with strong Chinese + English support, 384-dim
EMBEDDING_MODEL_NAME = "intfloat/multilingual-e5-small"
EMBEDDING_DIM = 384

# Local model path (auto-downloaded on first run)
LOCAL_MODEL_DIR = DATA_DIR / "model"

# Lazy-loaded model reference
_embed_model = None
_np = None  # numpy, lazy import

def _ensure_numpy():
    global _np
    if _np is None:
        import numpy
        _np = numpy
    return _np

def _ensure_local_model():
    """Ensure the embedding model is available locally.
    Downloads to data/model/ if not present (avoids HF symlink issues on Windows)."""
    if LOCAL_MODEL_DIR.exists() and (LOCAL_MODEL_DIR / "modules.json").exists():
        return str(LOCAL_MODEL_DIR)

    print(f"Embedding model not found locally. Downloading {EMBEDDING_MODEL_NAME}...", file=sys.stderr)
    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        python_exe = sys.executable
        subprocess.check_call(
            [python_exe, "-m", "pip", "install", "huggingface_hub", "--quiet"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        from huggingface_hub import snapshot_download

    LOCAL_MODEL_DIR.mkdir(parents=True, exist_ok=True)
    snapshot_download(EMBEDDING_MODEL_NAME, local_dir=str(LOCAL_MODEL_DIR))
    print("Model downloaded.", file=sys.stderr)
    return str(LOCAL_MODEL_DIR)

def _ensure_sentence_transformers():
    """Ensure sentence-transformers is installed. Auto-install if missing."""
    global _embed_model
    if _embed_model is not None:
        return _embed_model

    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        print("Installing sentence-transformers (one-time setup)...", file=sys.stderr)
        python_exe = sys.executable
        subprocess.check_call(
            [python_exe, "-m", "pip", "install", "sentence-transformers", "--quiet"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        from sentence_transformers import SentenceTransformer

    model_path = _ensure_local_model()
    print(f"Loading embedding model from: {model_path}...", file=sys.stderr)
    _embed_model = SentenceTransformer(model_path)
    print("Embedding model loaded.", file=sys.stderr)
    return _embed_model

def compute_embeddings(texts, batch_size=64):
    """Compute embeddings for a list of texts using sentence-transformers."""
    model = _ensure_sentence_transformers()
    np = _ensure_numpy()
    if not texts:
        return np.array([], dtype=np.float32)
    embeddings = model.encode(texts, batch_size=batch_size, show_progress_bar=False,
                              normalize_embeddings=True)
    return embeddings.astype(np.float32)

def compute_query_embedding(query):
    """Compute normalized embedding for a single query."""
    model = _ensure_sentence_transformers()
    np = _ensure_numpy()
    emb = model.encode([query], normalize_embeddings=True)
    return emb[0].astype(np.float32)

def embedding_cosine_similarity(query_emb, skill_embs):
    """
    Compute cosine similarity between query embedding and all skill embeddings.
    Both are already L2-normalized, so dot product = cosine similarity.
    Returns list of (index, score) sorted by descending score.
    """
    np = _ensure_numpy()
    if len(skill_embs) == 0:
        return []
    scores = np.dot(skill_embs, query_emb)
    # Get indices sorted by descending score
    sorted_indices = np.argsort(-scores)
    return [(int(i), float(scores[i])) for i in sorted_indices]

def semantic_rank_embedding(query, skills, skill_embeddings, top_n=20):
    """
    Rank skills by embedding cosine similarity to the query.
    Returns list of (skill, score) sorted by descending score.
    """
    if not skills or len(skill_embeddings) == 0:
        return [(s, 0.0) for s in skills]

    query_emb = compute_query_embedding(query)

    # Build descriptions for the skills we're ranking
    skill_texts = []
    for skill in skills:
        desc = skill.get('description', '') or ''
        name = skill.get('name', '') or ''
        skill_texts.append(desc + ' ' + name)

    # Compute embeddings for these skills (or use cached ones)
    np = _ensure_numpy()
    skill_embs = compute_embeddings(skill_texts, batch_size=min(64, len(skill_texts)))

    # Cosine similarity
    scores = np.dot(skill_embs, query_emb)

    scored = [(skills[i], float(scores[i])) for i in range(len(skills))]
    scored.sort(key=lambda x: -x[1])
    return scored[:top_n]

def semantic_rank_cached(query, skill_indices, full_embeddings, all_skills, top_n=20):
    """
    Rank skills using pre-cached embeddings (from embedding file).
    `skill_indices`: list of global indices into full_embeddings
    `full_embeddings`: numpy array of all skill embeddings
    `all_skills`: full list of skills matching the embedding array
    Returns list of (skill, score) sorted by descending score.
    """
    np = _ensure_numpy()
    if not skill_indices or full_embeddings is None or len(full_embeddings) == 0:
        return [(all_skills[i], 0.0) for i in skill_indices]

    query_emb = compute_query_embedding(query)
    subset_embs = full_embeddings[skill_indices]
    scores = np.dot(subset_embs, query_emb)

    scored = [(all_skills[skill_indices[i]], float(scores[i])) for i in range(len(skill_indices))]
    scored.sort(key=lambda x: -x[1])
    return scored[:top_n]


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
            "软件": 6, "登录": 6, "表单": 6, "组件": 6, "模块": 2,
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
            "销售": 10, "KPI": 10, "看板": 10, "绩效": 10,
            "运营": 6, "客服": 8, "CRM": 8, "ERP": 8, "报销": 10,
            "周报": 8, "月报": 8, "季度": 6,
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
                     "大涨", "大跌", "崩盘", "泡沫",
                     "主线", "题材", "热点", "龙头",
                     "K线", "均线", "成交量", "MACD", "RSI",
                     "基本面", "技术面", "资金流向"],
    },
    "data_visualization": {
        "trigger": ["画图", "图表", "可视化", "仪表盘", "作图", "绘图", "折线图",
                     "柱状图", "饼图", "K线图", "趋势图", "map", "chart",
                     "visualize", "graph", "plot", "dashboard", "画图表",
                     "数据图", "统计图", "走势图", "饼状图", "散点图",
                     "画", "图"],
    },
    "document_processing": {
        "trigger": ["word", "excel", "ppt", "pdf", "文档", "表格", "幻灯片",
                     "docx", "xlsx", "pptx", "转格式", "OCR", "markdown"],
    },
    "content_design": {
        "trigger": ["设计", "海报", "配色", "logo", "UI", "UX",
                     "图片", "视频", "翻译", "写作", "画画", "画海报",
                     "画设计", "写文章", "写文案", "写小说", "公众号",
                     "排版", "字体", "品牌设计", "VI",
                     "design", "image", "video", "create", "generate",
                     "thumbnail", "mockup", "wireframe", "typography"],
    },
    "software_development": {
        "trigger": ["编程", "代码", "开发", "API", "框架", "测试", "部署",
                     "重构", "debug", "架构", "接口", "code", "program",
                     "develop", "framework", "test", "deploy", "refactor",
                     "React", "Vue", "Angular", "Node.js", "TypeScript",
                     "组件", "登录", "表单", "npm", "Git", "后端", "前端",
                     "全栈", "微服务", "数据库", "SQL", "REST", "GraphQL",
                     "Docker", "Kubernetes", "CI/CD", "Python脚本"],
    },
    "data_science_ml": {
        "trigger": ["机器学习", "深度学习", "模型", "训练", "预测", "数据分析",
                     "统计分析", "聚类", "回归", "分类", "ML", "AI", "pandas",
                     "特征", "数据集", "machine learning", "train", "predict"],
    },
    "business_operations": {
        "trigger": ["项目管理", "审计", "法律", "合同", "合规", "发票",
                     "HR", "招聘", "简历", "OKR", "agile", "sprint", "流程",
                     "运营", "manage", "project", "audit", "legal", "hr",
                     "销售", "KPI", "看板", "绩效", "敏捷", "报销",
                     "周报", "月报", "季度报告", "考勤", "入职", "面试"],
    },
    "communication": {
        "trigger": ["邮件", "通知", "消息", "通讯", "日程", "会议记录",
                     "email", "notify", "message", "calendar", "meeting",
                     "会议", "预约", "腾讯会议", "日程安排"],
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
                     "genomic", "protein", "drug", "clinical", "bio", "pharma",
                     "CRISPR", "DNA", "RNA", "细胞", "分子", "enzyme",
                     "基因组", "测序", "病理", "诊断", "疫苗"],
    },
}

MIN_SCORE = 8


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
    """Build or rebuild the domain index, including embedding cache."""
    if not force and INDEX_FILE.exists() and EMBEDDING_FILE.exists():
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

    # Build embedding cache for semantic ranking
    print(f"Building embedding index with {EMBEDDING_MODEL_NAME}...", file=sys.stderr)
    skill_texts = []
    for skill in results:
        desc = skill.get('description', '') or ''
        name = skill.get('name', '') or ''
        skill_texts.append(desc + ' ' + name)

    embeddings = compute_embeddings(skill_texts)
    print(f"Embeddings computed: {embeddings.shape}", file=sys.stderr)

    output = {
        'built_at': time.time(),
        'total_skills': len(skills),
        'embedding_model': EMBEDDING_MODEL_NAME,
        'embedding_dim': EMBEDDING_DIM,
        'domains': [{'id': d['id'], 'name': d['name'], 'description': d['desc']} for d in DOMAINS],
        'skills': results,
        'summary': {d['id']: {'name': d['name'], 'count': domain_counts[d['id']]} for d in DOMAINS},
        'other_count': domain_counts['other'],
    }

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(INDEX_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    # Save embeddings as numpy binary file
    np = _ensure_numpy()
    np.save(str(EMBEDDING_FILE), embeddings)

    elapsed = time.time() - t0
    idx_size_mb = EMBEDDING_FILE.stat().st_size / (1024 * 1024) if EMBEDDING_FILE.exists() else 0
    print(f"Index built in {elapsed:.1f}s ({len(skills)} skills, "
          f"{sum(1 for c in domain_counts.values() if c > 0)} domains, "
          f"embeddings: {idx_size_mb:.1f}MB)",
          file=sys.stderr)

    return output


def _load_index():
    """Load cached index if valid."""
    try:
        with open(INDEX_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def _load_embeddings():
    """Load cached embeddings from .npy file. Returns numpy array or None."""
    try:
        if EMBEDDING_FILE.exists():
            np = _ensure_numpy()
            return np.load(str(EMBEDDING_FILE))
    except Exception:
        pass
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

# Multi-intent filtering: only keep domains with score >= ratio of max score
MULTI_INTENT_SCORE_RATIO = 0.25  # keep domain if score >= 25% of top domain
MAX_DOMAINS = 3                  # cap total domains for multi-intent


def detect_multi_intent(query, domain_scores):
    """
    Detect if the query has multiple intents requiring multiple skills.
    Filters weak domain matches using relative score threshold.
    Returns list of (domain_id, score) sorted by execution order.
    Always returns a list of tuples.
    """
    if not domain_scores:
        return []

    items = list(domain_scores.items())
    if len(items) == 1:
        return items

    # Filter: only keep domains with score >= threshold
    max_score = max(s for _, s in items)
    threshold = max_score * MULTI_INTENT_SCORE_RATIO
    filtered = [(did, s) for did, s in items if s >= threshold]

    # Cap at MAX_DOMAINS
    if len(filtered) > MAX_DOMAINS:
        filtered.sort(key=lambda x: -x[1])
        filtered = filtered[:MAX_DOMAINS]

    # If only one survives filtering → single intent
    if len(filtered) <= 1:
        return filtered

    # Sort by execution order for multi-intent
    ordered = sorted(filtered, key=lambda x: DOMAIN_EXEC_ORDER.get(x[0], 99))
    return ordered


# ── Query Routing (Enhanced with Embedding RAG) ─────────────────────────

def route_query(query, data, expand_depth=1, use_rag=True):
    """
    Route a query to domains and return matching skills.
    Enhanced with:
      - Multi-intent detection (returns skills from multiple domains in exec order)
      - In-domain RAG re-ranking (sentence-transformer embedding similarity)
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

    # Load cached embeddings for fast ranking
    full_embeddings = None
    if use_rag:
        full_embeddings = _load_embeddings()

    # Build global index map: skill name → global index
    name_to_idx = {}
    all_skills_list = data['skills']
    for i, s in enumerate(all_skills_list):
        name_to_idx[s['name']] = i

    # For multi-intent: return top skills from each matched domain in order
    if len(primary_ids) > 1:
        for domain_id in primary_ids:
            domain_skills = [s for s in data['skills']
                            if s['primary_domain'] == domain_id and s['name'] not in seen]
            step_skills = []
            if use_rag and domain_skills and full_embeddings is not None:
                # Use cached embedding ranking
                indices = [name_to_idx[s['name']] for s in domain_skills
                          if s['name'] in name_to_idx]
                ranked = semantic_rank_cached(query, indices, full_embeddings,
                                              all_skills_list, top_n=5)
                for skill, score in ranked:
                    if skill['name'] not in seen:
                        seen.add(skill['name'])
                        skill['rag_score'] = round(score, 4)
                        step_skills.append(skill)
                        all_skills.append(skill)
            else:
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

        if use_rag and all_skills and full_embeddings is not None:
            indices = [name_to_idx[s['name']] for s in all_skills
                      if s['name'] in name_to_idx]
            ranked = semantic_rank_cached(query, indices, full_embeddings,
                                          all_skills_list, top_n=20)
            all_skills = []
            for skill, score in ranked:
                skill['rag_score'] = round(score, 4)
                all_skills.append(skill)

    return {
        'query': query,
        'matched_domains': [{'id': d, 'name': domain_name_map.get(d, d)} for d in primary_ids],
        'expanded_domains': [{'id': d, 'name': domain_name_map.get(d, d)} for d in sorted(expanded)],
        'is_multi_intent': len(primary_ids) > 1,
        'execution_plan': execution_plan,
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
    lines.append(f"[候选] skill 数: {result['skill_count']}")
    lines.append("")
    lines.append(f"Top {top_n} skills in matched domains:")

    for s in result['skills'][:top_n]:
        domain_name = s.get('primary_domain_name', '')
        secondary = ', '.join(s.get('secondary_domains', []))
        extra = f" [also: {secondary}]" if secondary else ""
        rag = s.get('rag_score', '')
        rag_str = f" [Emb:{rag:.3f}]" if rag else ""
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
    emb_model = data.get('embedding_model', 'TF-IDF')
    emb_dim = data.get('embedding_dim', 'N/A')
    print(f"  Embedding model: {emb_model} ({emb_dim}d)")
    print()
    for d in data['domains']:
        cnt = data['summary'][d['id']]['count']
        name = d['name']
        print(f"  {name:20s}  {cnt:5d} skills")
    print(f"  {'其他':20s}  {data['other_count']:5d} skills")

    if EMBEDDING_FILE.exists():
        emb_size = EMBEDDING_FILE.stat().st_size / (1024 * 1024)
        print(f"\n  Embedding cache: {emb_size:.1f} MB")


def print_domains(data):
    """List all domains with adjacency."""
    for d in data['domains']:
        neighbors = DOMAIN_ADJACENCY.get(d['id'], [])
        dn_map = {dd['id']: dd['name'] for dd in data['domains']}
        nbr_names = [dn_map.get(n, n) for n in neighbors]
        print(f"{d['name']}  <->  {', '.join(nbr_names)}")


def test_rag_quality(data):
    """Test embedding RAG ranking quality with sample queries."""
    test_cases = [
        # (query, expected_domain, expected_top_skills)
        ("分析A股消费板块走势", "finance_investment", ["westock-data", "neodata-financial-search"]),
        ("帮我处理一个PDF转Word", "document_processing", ["pdf", "docx"]),
        ("画一个销售数据的趋势图表", "data_visualization", ["data_visualization"]),
        ("帮我发一封邮件通知团队", "communication", ["qq-mail"]),
        ("写一个React注册登录页面", "software_development", ["github", "playwright-cli"]),
        ("帮我预约一个腾讯会议", "communication", ["tencent-meeting-skill"]),
        ("训练一个图像分类模型", "data_science_ml", ["arxiv-reader"]),
        ("我需要找一篇关于CRISPR的论文", "life_sciences", []),
        ("帮我设计一个LOGO和海报", "content_design", ["libtv-skill"]),
        ("Excel表格数据分析", "document_processing", ["xlsx"]),
        ("帮我写一个微信公众号文章", "content_design", ["libtv-skill", "novel-writing"]),
        ("把代码部署到云服务器", "cloud_infrastructure", ["cloudstudio-deploy"]),
        ("分析财报并画K线图", "finance_investment", ["finance_investment", "data_visualization"]),
        ("帮我管理项目Sprint和OKR", "business_operations", []),
    ]

    print("=" * 70)
    print("  Embedding RAG Ranking Quality Test")
    print("=" * 70)

    total = 0
    domain_correct = 0
    for query, expected_domain, _ in test_cases:
        total += 1
        print(f"\n[{total}] Query: {query}")
        result = route_query(query, data)
        domains = [d['name'] for d in result['matched_domains']]
        domain_name_map = {d['id']: d['name'] for d in data['domains']}
        expected_name = domain_name_map.get(expected_domain, expected_domain)
        match = "OK" if expected_domain in [d['id'] for d in result['matched_domains']] else "MISS"
        if match == "OK":
            domain_correct += 1
        print(f"  Matched: {domains} (expect: {expected_name}) {match}")
        print(f"  Skills returned: {result['skill_count']}")
        if result['skills']:
            top3 = [(s['name'], s.get('rag_score', 0)) for s in result['skills'][:3]]
            for name, score in top3:
                score_str = f"{score:.4f}" if score else "N/A"
                print(f"    - {name} (Emb:{score_str})")
        else:
            print(f"    (no skills matched)")

    print(f"\n{'=' * 70}")
    print(f"  Domain routing accuracy: {domain_correct}/{total} ({domain_correct/total*100:.0f}%)")


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
