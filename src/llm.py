"""Accès au LLM par la passerelle Cortex (méthode du notebook agents.ipynb du prof).

Le squelette de l'étape 5 n'appelle pas encore le LLM : ce module servira
quand les nœuds factices seront remplacés (étape 7).
"""
import os
from pathlib import Path

from langchain_openai import ChatOpenAI

MODEL = "openai-gpt-5.4"


def make_llm(traceparent: str | None = None) -> ChatOpenAI:
    token = Path("/snowflake/session/token").read_text().strip()
    host = os.environ["SNOWFLAKE_HOST"]
    headers = {"X-Snowflake-Cross-Region": "ANY_REGION"}
    if traceparent:
        headers["traceparent"] = traceparent
    return ChatOpenAI(
        model=MODEL,
        base_url=f"https://{host}/api/v2/aigateways/SNOWFLAKE/v1",
        api_key=token,
        temperature=0,
        max_tokens=4096,
        default_headers=headers,
    )
