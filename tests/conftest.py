import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from jobagent.core.config import Settings
from jobagent.core.db import Database
from jobagent.core.llm import LLMClient, LLMResponse
from jobagent.core.logging import clear_secrets
from jobagent.core.notify import MemoryNotifier
from jobagent.core.schemas import (
    Bullet, Education, Experience, Personal, Profile, Project, Sensitive, Skills,
)

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 10, 29, 9, 0, 0)


@pytest.fixture(autouse=True)
def _reset_secrets():
    clear_secrets()
    yield
    clear_secrets()


class Clock:
    def __init__(self):
        self.t = NOW

    def __call__(self):
        return self.t

    def advance(self, seconds=0, days=0):
        self.t = self.t + timedelta(seconds=seconds, days=days)


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def db(clock):
    d = Database(":memory:", clock=clock)
    yield d
    d.close()


@pytest.fixture
def settings():
    return Settings()


@pytest.fixture
def notifier():
    return MemoryNotifier()


def make_profile(**sensitive) -> Profile:
    return Profile(
        version=1,
        personal=Personal(name="Aarav Mehta", email="aarav.mehta@example.com", phone="+91 98765 43210",
                          location="Mumbai", links={"github": "github.com/aarav", "linkedin": "linkedin.com/in/aarav"}),
        sensitive=Sensitive(**sensitive),
        summary="GenAI engineer with 2 years of experience building LLM agents.",
        experience=[
            Experience(company="Acme AI Labs", role="GenAI Engineer", start="2022-01", end="present", bullets=[
                Bullet(id="e1b1", text="Built a LangGraph agent that automated support triage.", skills=["LangGraph"]),
                Bullet(id="e1b2", text="Reduced latency by 40% using caching.", skills=["Redis"]),
                Bullet(id="e1b3", text="Built LangChain retrieval pipelines serving 5000 users.", skills=["LangChain"])]),
            Experience(company="Beta Systems", role="Software Engineer", start="2020-06", end="2021-12", bullets=[
                Bullet(id="e2b1", text="Developed REST APIs in Python and FastAPI.", skills=["Python", "FastAPI"])]),
        ],
        projects=[
            Project(name="Job Pipeline Agent", bullets=[
                Bullet(id="p1b1", text="Automated job applications with Playwright and LangChain.", skills=["Playwright", "LangChain"])]),
            Project(name="Sales Dashboard", bullets=[
                Bullet(id="p2b1", text="Built an analytics dashboard in SQL.", skills=["SQL"])]),
        ],
        skills=Skills(core=["Python", "LangGraph", "LangChain", "FastAPI", "Redis"], familiar=["SQL", "Playwright"]),
        education=[Education(institution="Mumbai University", degree="B.Tech Computer Science", start="2016", end="2020")],
    )


@pytest.fixture
def profile():
    return make_profile(current_ctc=12.0, expected_ctc=18.0, notice_period_days=30, relocation=True, work_auth="Indian citizen")


class FakeBackend:
    """Scripted LLM backend. `replies` is a list of strings/dicts/exceptions, or a callable(model, system, user)."""

    def __init__(self, replies):
        self.replies, self.calls = replies, []

    def __call__(self, model, system, user):
        self.calls.append((model, system, user))
        r = self.replies(model, system, user) if callable(self.replies) else self.replies[min(len(self.calls) - 1, len(self.replies) - 1)]
        if isinstance(r, Exception):
            raise r
        if isinstance(r, dict):
            r = json.dumps(r)
        return LLMResponse(r, prompt_tokens=100, completion_tokens=50)


@pytest.fixture
def make_llm(db):
    def _make(replies, **kw):
        backend = FakeBackend(replies)
        client = LLMClient(backend, db=db, sleep=lambda s: None, **kw)
        client.backend_obj = backend
        return client
    return _make


_counter = [0]


def insert_job(db, title="GenAI Engineer", company="Acme AI Labs", location="Mumbai", status="DISCOVERED",
               source="linkedin_alert", **cols):
    _counter[0] += 1
    n = _counter[0]
    row = dict(dedupe_key=f"k{n}-{title}-{company}", canonical_url=f"https://x.test/{n}", source=source, title=title,
               company=company, location=location, discovered_at=db.now_iso(), status=status, status_updated_at=db.now_iso(),
               apply_url=f"https://x.test/apply/{n}")
    row.update(cols)
    keys = ",".join(row)
    cur = db.write(f"INSERT INTO jobs({keys}) VALUES ({','.join('?' * len(row))})", tuple(row.values()))
    return cur.lastrowid
