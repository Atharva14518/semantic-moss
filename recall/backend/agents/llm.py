"""
agents/llm.py — LLM factory backed by Groq (langchain-groq).

Returns a ChatGroq instance.  All agent nodes import from here so
the model is configured in one place.
"""

from functools import lru_cache
from langchain_groq import ChatGroq
from config import get_settings


@lru_cache(maxsize=1)
def get_llm(temperature: float = 0.2) -> ChatGroq:
    cfg = get_settings()
    return ChatGroq(
        api_key=cfg.groq_api_key,
        model=cfg.groq_model,
        temperature=temperature,
    )
