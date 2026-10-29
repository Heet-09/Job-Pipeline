from pathlib import Path
from typing import Protocol

from jobagent.core.schemas import ResumeExtract

PROMPT_PATH = Path(__file__).resolve().parents[4] / "prompts" / "profile_extract.md"
DEFAULT_MODEL = "llama-3.3-70b-versatile"


class ResumeExtractor(Protocol):
    def extract(self, resume_text: str) -> ResumeExtract: ...


class LangChainExtractor:
    """Real extractor. Needs GROQ_API_KEY in the environment."""

    def __init__(self, model: str = DEFAULT_MODEL):
        self._model = model
        self._llm = None  # created on first use so a bad PDF is reported before a missing API key

    def extract(self, resume_text: str) -> ResumeExtract:
        if self._llm is None:
            from langchain_groq import ChatGroq  # imported lazily so tests need no key

            self._llm = ChatGroq(model=self._model, temperature=0).with_structured_output(ResumeExtract)
        system = PROMPT_PATH.read_text(encoding="utf-8")
        return self._llm.invoke([("system", system), ("human", resume_text)])
