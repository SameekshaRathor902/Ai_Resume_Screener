"""Skills vocabulary used by the scorer.

Skills count three times as much as ordinary words, so this list decides what the
score treats as important. It covers software, data, cloud, security, design,
QA, product, business, marketing, finance, HR and healthcare.

To add your own terms without editing code, set CUSTOM_SKILLS_FILE to a text file
(see custom_skills.example.txt). Lines look like:

    terraform                      # a single-word skill
    supply chain planning          # a multi-word skill
    s&op = sales and operations planning   # a variant that means the same thing
"""
import re

# Bumped whenever the vocabulary changes, so the scorer knows to rebuild its phrase regex.
VERSION = 0

# ---------------------------------------------------------------------------
# Multi-word skills. Each becomes one term, e.g. "machine learning" -> machine_learning.
# ---------------------------------------------------------------------------
_MULTIWORD = """
machine learning|deep learning|computer vision|data science|data analysis|data engineering
data warehouse|data modeling|data visualization|data structures|big data|feature engineering
reinforcement learning|neural networks|generative ai|prompt engineering|rest api|unit testing
integration testing|test automation|manual testing|regression testing|performance testing
version control|project management|product management|program management|supply chain
customer service|customer success|account management|business development|lead generation
market research|content marketing|email marketing|social media|digital marketing|brand management
financial analysis|financial modeling|financial reporting|accounts payable|accounts receivable
risk management|risk assessment|quality assurance|quality control|six sigma|lean manufacturing
root cause analysis|stakeholder management|change management|public speaking|technical writing
user research|interaction design|graphic design|visual design|design systems|responsive design
web design|mobile development|web development|cloud computing|system design|software architecture
event driven|design patterns|code review|technical support|help desk|network security
penetration testing|incident response|threat modeling|vulnerability assessment|load balancing
infrastructure as code|site reliability|pair programming|talent acquisition|employee relations
performance management|clinical research|patient care|project planning|time management
team leadership|cross functional|strategic planning|data entry|google analytics|google ads
sql server|power bi|react native|machine vision|time series
a/b testing|business analysis|business intelligence|requirements gathering|process improvement
sales forecasting|inventory management|vendor management|contract negotiation|budget management
tax preparation|internal audit|financial planning|investment banking|equity research
medical coding|clinical documentation|health informatics|infection control|case management
curriculum development|instructional design|classroom management|lesson planning
""".replace("\n", "|").split("|")

# ---------------------------------------------------------------------------
# Single-word skills (already canonical tokens).
# ---------------------------------------------------------------------------
_SINGLE = """
python java javascript typescript c++ c# f# rust ruby php swift kotlin scala perl haskell elixir
dart lua matlab fortran cobol groovy bash powershell sql nosql plsql graphql solidity assembly
html css sass react angular vue svelte nextjs nuxt nodejs express django flask fastapi spring
dotnet aspnet laravel rails symfony jquery bootstrap tailwind webpack vite redux webassembly
mysql postgresql mongodb redis sqlite oracle cassandra dynamodb elasticsearch neo4j snowflake
bigquery redshift databricks mariadb firebase supabase sql_server
aws azure gcp docker kubernetes terraform ansible jenkins puppet helm prometheus grafana
nginx apache linux unix git github gitlab bitbucket cicd devops gitops serverless cloud
agile scrum kanban jira confluence microservices kafka rabbitmq spark hadoop airflow dbt flink
pandas numpy scipy matplotlib seaborn scikit_learn tensorflow pytorch keras xgboost opencv nltk
spacy huggingface langchain llm ai nlp mlops ml_ops statistics etl elt tableau looker qlik excel
vba sas spss stata
selenium cypress playwright pytest junit jest mocha postman jmeter tdd bdd qa
android ios flutter xamarin kotlin_multiplatform unity unreal blender
figma sketch photoshop illustrator indesign ux ui wireframing prototyping
oop algorithms api frontend backend fullstack security cybersecurity networking encryption siem
firewall vpn tcp iot embedded fpga rtos plc scada autocad solidworks revit cad cam
salesforce hubspot sap erp crm zendesk servicenow workday netsuite quickbooks tally
seo sem ppc copywriting branding kpi okr roi saas b2b b2c
gaap ifrs auditing taxation bookkeeping forecasting budgeting payroll recruiting onboarding
ehr hipaa phlebotomy triage pharmacology
powerpoint ms_office
""".split()

# ---------------------------------------------------------------------------
# Phrases and spellings that should become one canonical token.
# ---------------------------------------------------------------------------
PHRASES = {
    "natural language processing": "nlp",
    "data analytics": "data_analysis",
    "restful api": "rest_api",
    "restful apis": "rest_api",
    "rest apis": "rest_api",
    "unit tests": "unit_testing",
    "object oriented": "oop",
    "object-oriented": "oop",
    "ci/cd": "cicd",
    "ci cd": "cicd",
    "continuous integration": "cicd",
    "continuous delivery": "cicd",
    "continuous deployment": "cicd",
    "amazon web services": "aws",
    "google cloud platform": "gcp",
    "google cloud": "gcp",
    "asp.net": "aspnet",
    ".net": "dotnet",
    "node.js": "nodejs",
    "node js": "nodejs",
    "react.js": "react",
    "reactjs": "react",
    "vue.js": "vue",
    "vuejs": "vue",
    "next.js": "nextjs",
    "express.js": "express",
    "scikit-learn": "scikit_learn",
    "sklearn": "scikit_learn",
    "artificial intelligence": "ai",
    "large language models": "llm",
    "large language model": "llm",
    "problem solving": "problem_solving",
    "problem-solving": "problem_solving",
    "front end": "frontend",
    "front-end": "frontend",
    "back end": "backend",
    "back-end": "backend",
    "full stack": "fullstack",
    "full-stack": "fullstack",
    "golang": "go_lang",
    "postgres": "postgresql",
    "mongo": "mongodb",
    "k8s": "kubernetes",
    "mssql": "sql_server",
    "c sharp": "c#",
    "user experience": "ux",
    "user interface": "ui",
    "test driven development": "tdd",
    "test-driven development": "tdd",
    "behavior driven development": "bdd",
    "behaviour driven development": "bdd",
    "electronic health records": "ehr",
    "electronic medical records": "ehr",
    "microsoft office": "ms_office",
    "ms office": "ms_office",
    "microsoft excel": "excel",
    "ms excel": "excel",
    "microsoft powerpoint": "powerpoint",
    "ms powerpoint": "powerpoint",
    "return on investment": "roi",
    "search engine optimization": "seo",
    "search engine optimisation": "seo",
    "customer relationship management": "crm",
    "enterprise resource planning": "erp",
    "key performance indicators": "kpi",
    "software as a service": "saas",
    "internet of things": "iot",
    "generative artificial intelligence": "generative_ai",
    "gen ai": "generative_ai",
    "genai": "generative_ai",
    "kpis": "kpi",
    "okrs": "okr",
}

# Single-token aliases applied after tokenising.
ALIASES = {
    "js": "javascript", "ts": "typescript", "py": "python", "ml": "machine_learning",
    "tf": "tensorflow", "cpp": "c++", "csharp": "c#", "powerbi": "power_bi", "apis": "api",
    "llms": "llm", "restful": "rest_api", "microservice": "microservices",
    "postgre": "postgresql",
}

SKILLS: set = set()

# Special capitalisation for skills shown in the UI. Everything else is Title Cased.
DISPLAY = {
    "nodejs": "Node.js", "nextjs": "Next.js", "cicd": "CI/CD", "rest_api": "REST API",
    "nlp": "NLP", "aws": "AWS", "gcp": "GCP", "llm": "LLM", "ai": "AI", "oop": "OOP",
    "go_lang": "Go", "scikit_learn": "scikit-learn", "power_bi": "Power BI", "sql": "SQL",
    "nosql": "NoSQL", "html": "HTML", "css": "CSS", "api": "API", "dotnet": ".NET",
    "aspnet": "ASP.NET", "mysql": "MySQL", "postgresql": "PostgreSQL", "mongodb": "MongoDB",
    "javascript": "JavaScript", "typescript": "TypeScript", "graphql": "GraphQL",
    "pytorch": "PyTorch", "tensorflow": "TensorFlow", "etl": "ETL", "elt": "ELT", "ios": "iOS",
    "devops": "DevOps", "github": "GitHub", "gitlab": "GitLab", "fastapi": "FastAPI",
    "opencv": "OpenCV", "huggingface": "Hugging Face", "jquery": "jQuery", "php": "PHP",
    "ui": "UI", "ux": "UX", "qa": "QA", "tdd": "TDD", "bdd": "BDD", "seo": "SEO", "sem": "SEM",
    "ppc": "PPC", "kpi": "KPI", "okr": "OKR", "roi": "ROI", "saas": "SaaS", "b2b": "B2B",
    "b2c": "B2C", "crm": "CRM", "erp": "ERP", "sap": "SAP", "ehr": "EHR", "hipaa": "HIPAA",
    "gaap": "GAAP", "ifrs": "IFRS", "iot": "IoT", "tcp": "TCP", "vpn": "VPN", "siem": "SIEM",
    "fpga": "FPGA", "rtos": "RTOS", "plc": "PLC", "scada": "SCADA", "cad": "CAD", "cam": "CAM",
    "autocad": "AutoCAD", "solidworks": "SolidWorks", "ms_office": "MS Office",
    "powerpoint": "PowerPoint", "mlops": "MLOps", "ml_ops": "MLOps", "dbt": "dbt",
    "vba": "VBA", "sas": "SAS", "spss": "SPSS", "plsql": "PL/SQL", "sql_server": "SQL Server",
    "bigquery": "BigQuery", "dynamodb": "DynamoDB", "elasticsearch": "Elasticsearch",
    "rabbitmq": "RabbitMQ", "gitops": "GitOps", "numpy": "NumPy", "scipy": "SciPy",
    "xgboost": "XGBoost", "nltk": "NLTK", "spacy": "spaCy", "langchain": "LangChain",
    "webassembly": "WebAssembly", "indesign": "InDesign", "hubspot": "HubSpot",
    "servicenow": "ServiceNow", "netsuite": "NetSuite", "quickbooks": "QuickBooks",
    "jmeter": "JMeter", "junit": "JUnit", "pytest": "pytest", "matlab": "MATLAB",
    "cobol": "COBOL", "fortran": "Fortran", "a/b_testing": "A/B Testing",
    "kotlin_multiplatform": "Kotlin Multiplatform", "generative_ai": "Generative AI",
}


def _canonical(text: str) -> str:
    return re.sub(r"[\s\-]+", "_", text.strip().lower())


def _register_multiword(phrase: str) -> None:
    phrase = phrase.strip().lower()
    if not phrase:
        return
    canon = _canonical(phrase)
    SKILLS.add(canon)
    PHRASES.setdefault(phrase, canon)


for _phrase in _MULTIWORD:
    _register_multiword(_phrase)
SKILLS.update(_SINGLE)
# Every canonical target of a phrase or alias is a skill, except generic soft-skill words.
SKILLS.update(v for v in PHRASES.values() if v not in {"problem_solving"})
SKILLS.update(v for v in ALIASES.values())
# "a/b testing" contains a slash, which the scorer would split, so give it a clean token.
PHRASES["a/b testing"] = "ab_testing"
SKILLS.discard("a/b_testing")
SKILLS.add("ab_testing")
DISPLAY["ab_testing"] = "A/B Testing"
PHRASES["a/b tests"] = "ab_testing"
PHRASES["a/b test"] = "ab_testing"
PHRASES["ab testing"] = "ab_testing"
PHRASES["ruby on rails"] = "rails"
PHRASES["spring boot"] = "spring"


def add_custom_skills(lines) -> int:
    """Add skills from lines of text. Returns how many lines were applied."""
    global VERSION
    applied = 0
    for raw in lines:
        line = raw.split("#", 1)[0].strip().lower()
        if not line:
            continue
        variant, target = (part.strip() for part in line.split("=", 1)) if "=" in line else (line, line)
        if not variant or not target:
            continue
        canon = _canonical(target)
        SKILLS.add(canon)
        if " " in target and canon not in DISPLAY:
            DISPLAY[canon] = target.title()
        if variant != canon:
            if re.fullmatch(r"[a-z0-9+#_]+", variant):
                ALIASES[variant] = canon
            else:
                PHRASES[variant] = canon
        if " " in target:
            PHRASES.setdefault(target, canon)
        applied += 1
    VERSION += 1
    return applied


def load_custom_skills(path: str) -> int:
    with open(path, encoding="utf-8") as handle:
        return add_custom_skills(handle.read().splitlines())
