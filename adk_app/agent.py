# adk_app/agent.py
import os
import sys
from pathlib import Path

import requests
from google import genai

# -------------------------------------------------
# Ensure repo root is importable
# -------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parents[1]  # .../workato
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# -------------------------------------------------
# ADK imports (version-compatible)
# -------------------------------------------------
from google.adk.agents.base_agent import BaseAgent
from google.adk.events import Event

# -------------------------------------------------
# Project imports
# -------------------------------------------------
from src.ai.qa_engine import QAEngine
from src.connectors.gdrive_connector import GDriveConnector
from src.connectors.jira_connector import JiraConnector


# -------------------------------------------------
# Concrete LLM client (used ONLY by QAEngine)
# -------------------------------------------------
class ConcreteLLMClient:
    """
    Implements the interface QAEngine expects:
      generate_response(prompt, system_instruction="")
    """

    def __init__(self, env: str):
        self.env = env

        if env == "local":
            self.ollama_base = os.getenv("OLLAMA_API_BASE", "http://localhost:11434")
            self.ollama_model = os.getenv("OLLAMA_MODEL", "gemma3:1b")
        else:
            api_key = os.environ["GOOGLE_API_KEY"]
            self.gemini_model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
            self.genai_client = genai.Client(api_key=api_key)

    def generate_response(self, prompt: str, system_instruction: str = "") -> str:
        if self.env == "local":
            payload = {
                "model": self.ollama_model,
                "messages": [
                    {"role": "system", "content": system_instruction or ""},
                    {"role": "user", "content": prompt},
                ],
                "stream": False,
            }
            r = requests.post(
                f"{self.ollama_base}/api/chat",
                json=payload,
                timeout=180,
            )
            r.raise_for_status()
            data = r.json()
            return (data.get("message") or {}).get("content", "").strip()

        # Gemini API
        contents = []
        if system_instruction:
            contents.append(
                {"role": "user", "parts": [{"text": f"[SYSTEM]\n{system_instruction}"}]}
            )
        contents.append({"role": "user", "parts": [{"text": prompt}]})

        resp = self.genai_client.models.generate_content(
            model=self.gemini_model,
            contents=contents,
        )
        return (resp.text or "").strip()


# -------------------------------------------------
# Helpers
# -------------------------------------------------
def _emit_text_event(author: str, text: str) -> Event:
    """
    Emit an Event compatible with your ADK version.
    Your schema requires: author + content.
    """
    return Event(
        author=author,
        content={"parts": [{"text": (text or "").strip()}]},
    )


def _get_last_user_text(invocation_context) -> str:
    """
    ADK Web often provides the latest user prompt in the invocation_context payload,
    not in session.events/messages. We extract it from invocation_context.model_dump().
    """

    def md(obj):
        fn = getattr(obj, "model_dump", None)
        if callable(fn):
            try:
                return fn()
            except Exception:
                return None
        return None

    payload = md(invocation_context)
    if not isinstance(payload, dict):
        return ""

    # Helper: find last text-like value inside nested structures,
    # but prefer values attached to user-like roles/authors.
    best = ""

    def walk(o):
        nonlocal best
        if o is None:
            return
        if isinstance(o, dict):
            # Prefer explicit "user" role/author blocks
            role = (o.get("role") or o.get("author") or "").lower()
            if role == "user":
                # common shapes: {"content": {"parts":[{"text":"..."}]}}
                c = o.get("content")
                if isinstance(c, dict):
                    parts = c.get("parts") or []
                    for p in parts:
                        if isinstance(p, dict) and isinstance(p.get("text"), str) and p["text"].strip():
                            best = p["text"].strip()
                # or {"content": "..."}
                if isinstance(o.get("content"), str) and o["content"].strip():
                    best = o["content"].strip()
                # or {"text": "..."}
                if isinstance(o.get("text"), str) and o["text"].strip():
                    best = o["text"].strip()

            # Also handle top-level request fields often used by ADK
            for k in ("text", "query", "prompt", "user_input"):
                v = o.get(k)
                if isinstance(v, str) and v.strip():
                    best = v.strip()

            for v in o.values():
                walk(v)
            return

        if isinstance(o, list):
            for it in o:
                walk(it)
            return

    walk(payload)

    return _sanitize_user_text(best)

def _sanitize_user_text(text: str) -> str:
    t = (text or "").strip()

    # Unwrap fenced blocks but KEEP the content
    if t.startswith("```") and t.endswith("```"):
        lines = t.splitlines()
        if len(lines) >= 3:
            # drop ```tool_code and closing ```
            t = "\n".join(lines[1:-1]).strip()

    return t



# -------------------------------------------------
# Environment
# -------------------------------------------------
ENV = os.getenv("ENV", "local")  # local | prod

# -------------------------------------------------
# Instantiate pipeline components
# -------------------------------------------------
llm = ConcreteLLMClient(ENV)

gdrive = GDriveConnector(
    credentials_path=os.getenv("GDRIVE_CREDS", "credentials.json")
)

jira = JiraConnector(
    server=os.getenv("JIRA_SERVER"),
    email=os.getenv("JIRA_EMAIL"),
    token=os.getenv("JIRA_TOKEN"),
)


engine = QAEngine(
    jira_conn=jira,
    gdrive_conn=gdrive,
    llm_client=llm,
)


# -------------------------------------------------
# Deterministic ADK Agent
# -------------------------------------------------
class DeterministicQAAgent(BaseAgent):
    """
    Deterministic agent:
    - No ADK LLM
    - No tools
    - Always runs QAEngine.answer_query()
    """

    async def run_async(self, invocation_context):
        user_text = _get_last_user_text(invocation_context)

        if not user_text:
            yield _emit_text_event(self.name, "Please type a question.")
            return

        answer = engine.answer_query(user_text)
        yield _emit_text_event(self.name, answer)

        dump = invocation_context.model_dump() if hasattr(invocation_context, "model_dump") else None
        print("DEBUG keys:", list(dump.keys())[:40] if isinstance(dump, dict) else type(dump))
        print("DEBUG extracted user_text:", repr(user_text))


# -------------------------------------------------
# Root agent (discovered by `adk web`)
# -------------------------------------------------
root_agent = DeterministicQAAgent(name="eol_agent")
