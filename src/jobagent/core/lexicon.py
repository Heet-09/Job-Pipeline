"""Shared vocabulary: known tech terms (used by the rule-based JD extractor and the resume claim validator)."""
import re

TECH_TERMS = [
    "python", "java", "javascript", "typescript", "go", "golang", "rust", "c++", "c#", "scala", "kotlin", "swift", "sql", "nosql",
    "langchain", "langgraph", "llamaindex", "llm", "llms", "rag", "genai", "openai", "anthropic", "claude", "gpt", "hugging face",
    "transformers", "pytorch", "tensorflow", "keras", "scikit-learn", "sklearn", "pandas", "numpy", "spark", "pyspark", "hadoop",
    "kafka", "airflow", "dbt", "snowflake", "bigquery", "redshift", "databricks", "tableau", "power bi",
    "fastapi", "flask", "django", "spring", "node", "nodejs", "react", "angular", "vue", "graphql", "rest",
    "docker", "kubernetes", "k8s", "terraform", "ansible", "jenkins", "git", "ci/cd", "aws", "azure", "gcp",
    "postgresql", "postgres", "mysql", "mongodb", "redis", "elasticsearch", "pinecone", "qdrant", "faiss", "chroma",
    "playwright", "selenium", "pytest", "streamlit", "vector database", "prompt engineering", "fine-tuning", "nlp", "mlops",
    "sap", "salesforce", "oracle", "excel",
]
SYNONYMS = {"k8s": "kubernetes", "postgres": "postgresql", "sklearn": "scikit-learn", "golang": "go", "llms": "llm",
            "nodejs": "node", "gpt": "openai"}

_SORTED = sorted(TECH_TERMS, key=len, reverse=True)


def canon(term: str) -> str:
    t = term.strip().lower()
    return SYNONYMS.get(t, t)


def find_terms(text: str) -> list[str]:
    """Known tech terms present in text (canonical lower-case), in order of first appearance."""
    low = text.lower()
    hits: list[tuple[int, str]] = []
    for term in _SORTED:
        m = re.search(rf"(?<![a-z0-9+#]){re.escape(term)}(?![a-z0-9+#])", low)
        if m:
            hits.append((m.start(), canon(term)))
    seen, out = set(), []
    for _, t in sorted(hits):
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out
