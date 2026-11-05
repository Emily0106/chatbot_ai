from __future__ import annotations

from typing import Any, Dict, List

from app.agents.guardrail import GuardrailConfig, get_global_guardrail


def _get_agent_system_prompt(agent: Any) -> str:
    for attr in ("system_prompt", "prompt"):
        v = getattr(agent, attr, None)
        if isinstance(v, str) and v.strip():
            return v.strip()

    for fn_name in ("get_system_prompt", "build_system_prompt"):
        fn = getattr(agent, fn_name, None)
        if callable(fn):
            try:
                out = fn()
                if isinstance(out, str) and out.strip():
                    return out.strip()
            except Exception:
                continue
    return ""


def _format_sources(citations: List[Any], *, max_sources: int = 12) -> str:
    lines: List[str] = []
    n = min(len(citations), max_sources)

    for i in range(n):
        c = citations[i]
        if isinstance(c, dict):
            get = lambda k, d=None: c.get(k, d)
        else:
            get = lambda k, d=None: getattr(c, k, d)

        title = get("title", None) or "Tài liệu hệ thống"
        url = get("source_url", None) or get("file_url", None)
        page = get("page_number", None)
        snippet = get("snippet", None)

        meta = []
        if url:
            meta.append(f"url={url}")
        if page is not None:
            meta.append(f"page={page}")
        meta_str = (" | " + ", ".join(meta)) if meta else ""

        snippet_str = f"\n  - Snippet: {snippet}" if snippet else ""
        lines.append(f"[SOURCE {i+1}] {title}{meta_str}{snippet_str}")

    if not lines:
        return "[SOURCE LIST] (none)"
    return "[SOURCE LIST]\n" + "\n".join(lines)


def build_messages(
    *,
    agent: Any,
    question: str,
    context: str,
    citations: List[Any],
    language: str = "vi",
    require_citations: bool = True,
    max_sources_in_prompt: int = 12,
) -> List[Dict[str, str]]:
    guardrail = get_global_guardrail(
        GuardrailConfig(language=language, require_citations=require_citations)
    )
    agent_prompt = _get_agent_system_prompt(agent)
    system = (guardrail + "\n\n" + agent_prompt).strip() if agent_prompt else guardrail

    sources_block = _format_sources(citations, max_sources=max_sources_in_prompt)

    user = f"""
[QUESTION]
{(question or "").strip()}

[CONTEXT]
{(context or "").strip()}

{sources_block}

[INSTRUCTIONS]
- Chỉ dùng CONTEXT để trả lời.
- Mỗi ý quan trọng phải có trích dẫn dạng [SOURCE i].
- Nếu không đủ thông tin trong CONTEXT: nói rõ và hỏi lại 1–2 câu.
""".strip()

    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def get_agent_rag_config(agent: Any) -> Dict[str, Any]:
    v = getattr(agent, "rag_config", None)
    if isinstance(v, dict):
        return dict(v)

    fn = getattr(agent, "get_rag_config", None)
    if callable(fn):
        try:
            out = fn()
            if isinstance(out, dict):
                return dict(out)
        except Exception:
            pass
    return {}
