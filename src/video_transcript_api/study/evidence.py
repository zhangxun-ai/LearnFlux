"""Small, deterministic passage retrieval over the complete source transcript.

No model or external index is needed. Selected passages retain their original
line identities, and the caller can disclose exactly what entered the model.
"""

from __future__ import annotations

from collections import Counter
import math
import re


_QUESTION_FILLER = re.compile(
    r"请问|请你|帮我|这两篇|这两份|这几篇|这个|这些|那个|那些|这篇|这段|视频|课程|资料|作者|"
    r"是什么|为什么|怎么样|怎么|如何|什么|意思|一下|哪些|之间|有什么|"
    r"介绍|解释|讲解|说说|分别|比较|对比|异同|不同|观点|方法|提到|关于"
)
_OVERVIEW = re.compile(r"总结|概括|概览|概述|讲了什么|主要讲|核心要点|主要内容|核心内容|整体|全文|梳理|overview|summari", re.I)


def query_terms(question: str) -> set[str]:
    """Use words and CJK bigrams so Chinese retrieval needs no tokenizer service."""
    clean = _QUESTION_FILLER.sub(" ", question.casefold())
    words = set(re.findall(r"[a-z0-9][a-z0-9_+.-]*", clean))
    for phrase in re.findall(r"[\u3400-\u9fff]+", clean):
        if len(phrase) == 1:
            continue
        words.update(phrase[i:i + 2] for i in range(len(phrase) - 1))
        if len(phrase) <= 8:
            words.add(phrase)
    usable = {word for word in words if len(word) >= 2 or word.isdigit()}
    return set(sorted(usable, key=lambda word: (-len(word), word))[:96])


def _timestamp(value) -> str:
    seconds = max(0, int(float(value or 0)))
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02}" if hours else f"{minutes:02}:{seconds:02}"


def _passages(lines: list[dict], size: int = 1100) -> list[dict]:
    passages, group, count = [], [], 0

    def append_group():
        if not group:
            return
        first_index, first = group[0]
        last_index = group[-1][0]
        start = next((line.get("start_seconds") for _, line in group
                      if line.get("seekable") and line.get("start_seconds") is not None), None)
        passages.append({
            "id": f"P{len(passages) + 1}",
            "line_id": first.get("id") or f"line-{first_index + 1}",
            "start_seconds": start,
            "label": _timestamp(start) if start is not None else f"段落 {first_index + 1}–{last_index + 1}",
            "text": "\n".join(str(line.get("text") or "").strip() for _, line in group),
        })

    for index, line in enumerate(lines):
        text = str(line.get("text") or "").strip()
        if not text:
            continue
        if group and count + len(text) > size:
            append_group()
            # One original line of overlap preserves context around boundaries.
            group = group[-1:] if len(group) > 1 else []
            count = sum(len(str(item.get("text") or "")) for _, item in group)
        # Extremely long unsegmented input must not defeat the context bound.
        if len(text) > size * 2:
            append_group()
            group, count = [], 0
            for offset in range(0, len(text), size):
                part = {**line, "text": text[offset:offset + size]}
                group = [(index, part)]
                append_group()
            group = []
            continue
        group.append((index, line))
        count += len(text)
    append_group()
    return passages


def retrieve_evidence(
    lines: list[dict], question: str, *, max_chars: int = 22000,
    history: list[dict] | None = None,
) -> dict:
    """Select bounded evidence from every chapter, preserving source positions.

    Short sources remain complete. Long sources use lexical ranking; broad
    overview questions sample the whole source and explicitly disclose that
    coverage. A miss is surfaced instead of pretending the first chapter is all
    the available evidence.
    """
    passages = _passages(lines)
    source_chars = sum(len(str(line.get("text") or "")) for line in lines)
    full_size = sum(len(passage["text"]) for passage in passages)
    if full_size <= max_chars:
        chosen, mode, matched = passages, "full", bool(passages)
    else:
        terms = query_terms(question)
        # Follow-ups such as "what about its limitations?" can reuse the last
        # user question, but never allow assistant prose to become source data.
        if len(terms) < 3:
            previous = [item.get("content", "") for item in (history or []) if item.get("role") == "user"]
            if previous:
                terms |= query_terms(previous[-1][-1000:])
        lowered = [passage["text"].casefold() for passage in passages]
        document_frequency = Counter(term for term in terms for text in lowered if term in text)
        ranked = []
        for index, text in enumerate(lowered):
            hits = [term for term in terms if term in text]
            score = sum((1 + math.log((len(passages) + 1) / (document_frequency[term] + 1)))
                        * min(3, text.count(term)) * (1.8 if len(term) > 2 else 1)
                        for term in hits)
            if score:
                ranked.append((score, index))
        ranked.sort(key=lambda item: (-item[0], item[1]))
        matched = bool(ranked)
        mode = "retrieved"
        if _OVERVIEW.search(question) or not terms:
            # Cover beginning, middle and end for broad questions. These are
            # samples, not a claim to have supplied the whole long source.
            largest = max(len(item["text"]) for item in passages)
            count = min(12, len(passages), max(1, max_chars // max(1, largest)))
            indices = sorted({round(i * (len(passages) - 1) / max(1, count - 1)) for i in range(count)})
            order = indices + [index for _, index in ranked if index not in indices]
            mode, matched = "sampled", bool(passages)
        else:
            order = [index for _, index in ranked]
        chosen, used = [], 0
        for index in order:
            passage = passages[index]
            cost = len(passage["text"])
            if used + cost > max_chars:
                continue
            chosen.append(passage)
            used += cost
        chosen.sort(key=lambda item: int(item["id"][1:]))
    # Model-facing identifiers are local to this request. Keep the original
    # passage identity and exact source location for provenance and navigation.
    chosen = [{**item, "original_id": item["id"], "id": f"P{index}"}
              for index, item in enumerate(chosen, 1)]
    return {
        "mode": mode,
        "matched": matched,
        "source_chars": source_chars,
        "context_chars": sum(len(item["text"]) for item in chosen),
        "passages": chosen,
    }


def evidence_text(evidence: dict, source_id: str = "") -> str:
    """Render real excerpt identifiers for model citations."""
    return "\n\n".join(
        f"[{source_id + ':' if source_id else ''}{item['id']}] {item['label']}\n{item['text']}"
        for item in evidence["passages"]
    )
