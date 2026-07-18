"""Trend opportunity synthesis from normalized social signals."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from math import log1p, sqrt
from typing import Any

from .models import RawSignal

_PLATFORM_LABELS = {
    "x": "英文 X",
    "xiaohongshu": "小红书",
    "douyin": "抖音",
}
_DOMAIN_BY_TOPIC = {
    "agentic-workflow": "work",
    "consumer-ai": "ai",
    "robotics": "robotics",
    "glp1-lifestyle": "consumer",
}
_STACK_LAYERS = {
    "energy": {
        "id": "energy",
        "label": "能源",
        "summary": "电力、散热、数据中心选址和能源成本决定 AI 供给上限。",
    },
    "compute": {
        "id": "compute",
        "label": "芯片 / 计算",
        "summary": "GPU、推理芯片、边缘计算和国产替代决定能力成本曲线。",
    },
    "infrastructure": {
        "id": "infrastructure",
        "label": "基础设施 / AI 工厂",
        "summary": "云、数据管线、权限、安全、部署和监控把模型变成可用生产力。",
    },
    "models": {
        "id": "models",
        "label": "模型",
        "summary": "多模态、推理、记忆、Agent 和世界模型决定新应用边界。",
    },
    "applications": {
        "id": "applications",
        "label": "应用",
        "summary": "AI 在行业和生活场景里解决具体问题并接受市场检验。",
    },
}
_NEED_LAYERS = {
    "physiological": {
        "id": "physiological",
        "label": "生理需求",
        "summary": "健康、饮食、睡眠、照护和基础生活质量。",
    },
    "safety": {
        "id": "safety",
        "label": "安全需求",
        "summary": "隐私、合规、就业、财务安全和组织稳定。",
    },
    "belonging": {
        "id": "belonging",
        "label": "归属与爱",
        "summary": "陪伴、社群、家庭连接和亲密关系。",
    },
    "esteem": {
        "id": "esteem",
        "label": "尊重需求",
        "summary": "身份、能力证明、职业竞争力和影响力。",
    },
    "cognitive": {
        "id": "cognitive",
        "label": "认知需求",
        "summary": "学习、理解世界、决策、研究和知识管理。",
    },
    "aesthetic": {
        "id": "aesthetic",
        "label": "审美需求",
        "summary": "创作、设计、娱乐、表达和体验。",
    },
    "self_actualization": {
        "id": "self_actualization",
        "label": "自我实现",
        "summary": "创业、创造、长期目标、个人系统和人生管理。",
    },
}
_STACK_BY_TOPIC = {
    "agentic-workflow": "infrastructure",
    "consumer-ai": "applications",
    "robotics": "applications",
    "glp1-lifestyle": "applications",
}
_TOPIC_TERMS = {
    "agentic-workflow": (
        "ai agent",
        "ai agents",
        "agentic",
        "agent ",
        "agents",
        "workflow",
        "workflows",
        "procurement",
        "enterprise",
        "business process",
        "erp",
        "supplier",
        "automation",
        "智能体",
        "工作流",
        "业务流程",
        "采购",
        "供应商",
        "企业智能体",
        "自动化",
    ),
    "consumer-ai": (
        "consumer ai",
        "personal ai",
        "ai memory",
        "ai companion",
        "ai app",
        "ai assistant",
        "ai tool",
        "companion",
        "memory",
        "个人 ai",
        "个人AI",
        "ai 陪伴",
        "AI 陪伴",
        "陪伴",
        "记忆",
        "ai 工具",
        "AI 工具",
    ),
    "robotics": (
        "robot",
        "robotics",
        "humanoid",
        "embodied",
        "teleoperation",
        "home robot",
        "机器人",
        "具身",
        "仿生",
        "人形",
        "远程操控",
        "优必选",
    ),
    "glp1-lifestyle": (
        "glp",
        "glp-1",
        "ozempic",
        "wegovy",
        "semaglutide",
        "tirzepatide",
        "weight loss",
        "obesity",
        "减重针",
        "司美格鲁肽",
        "替尔泊肽",
        "玛仕度肽",
        "减重",
        "控糖",
    ),
}
_TOPIC_REQUIRED_GROUPS = {
    "agentic-workflow": (
        ("ai agent", "ai agents", "agentic", "agents", "智能体", "agent"),
        (
            "workflow",
            "workflows",
            "procurement",
            "enterprise",
            "business process",
            "erp",
            "supplier",
            "automation",
            "audit",
            "permission",
            "工作流",
            "业务流程",
            "采购",
            "供应商",
            "企业",
            "流程",
            "自动化",
            "审计",
            "权限",
        ),
    ),
    "consumer-ai": (
        ("ai", "artificial intelligence", "chatgpt", "claude", "智能", "AI"),
        (
            "consumer",
            "personal",
            "memory",
            "companion",
            "assistant",
            "app",
            "tool",
            "second brain",
            "个人",
            "记忆",
            "陪伴",
            "助手",
            "工具",
            "应用",
            "第二大脑",
        ),
    ),
    "robotics": (
        (
            "robot",
            "robotics",
            "humanoid",
            "embodied",
            "teleoperation",
            "home robot",
            "机器人",
            "具身",
            "人形",
            "仿生",
            "远程操控",
            "优必选",
        ),
    ),
    "glp1-lifestyle": (
        (
            "glp-1",
            "glp 1",
            "ozempic",
            "wegovy",
            "semaglutide",
            "tirzepatide",
            "weight-loss medication",
            "weight loss medication",
            "weight loss drug",
            "obesity drug",
            "减重针",
            "司美格鲁肽",
            "替尔泊肽",
            "玛仕度肽",
            "一针瘦",
        ),
    ),
}
_NEGATIVE_WORDS = (
    "scam",
    "fake",
    "overhyped",
    "bubble",
    "risk",
    "danger",
    "反对",
    "骗局",
    "割韭菜",
    "危险",
    "不靠谱",
    "泡沫",
)
_DISCOVERY_TOPIC_IDS = {"x-trending", "douyin-hot"}
_MIN_EVIDENCE_PER_ITEM = 2
_MIN_LOW_NOISE_EVIDENCE_PER_ITEM = 2
_MAX_LOCALIZED_EVIDENCE = 40


class TrendRadarSynthesizer:
    """Build UI-ready trend report cards.

    LLM synthesis is optional. The deterministic fallback is intentionally
    conservative so a failed model call still produces a useful, auditable
    report from raw evidence.
    """

    def __init__(
        self,
        llm_client: Any | None = None,
        model: str | None = None,
        reasoning_effort: str | None = None,
    ) -> None:
        self.llm_client = llm_client
        self.model = model
        self.reasoning_effort = reasoning_effort

    def build_report(
        self,
        signals: list[RawSignal],
        *,
        budget: dict[str, Any],
        generated_at: datetime | None = None,
    ) -> dict[str, Any]:
        generated_at = generated_at or datetime.now(timezone.utc)
        heuristic_items = self._heuristic_items(signals)
        # V2 is evidence-first: LLMs may polish later, but cannot create
        # candidate opportunities without verifiable source links.
        items = heuristic_items
        items = sorted(items, key=lambda item: item.get("score", 0), reverse=True)[:20]
        items = self._localize_evidence_previews(items)
        metrics = _metrics(items)
        diagnostics = _diagnostics(signals)
        return {
            "ok": True,
            "report_id": f"trend-{generated_at.strftime('%Y%m%d-%H%M%S')}",
            "analysis_version": "decision-brief-v4",
            "generated_at": generated_at.isoformat(),
            "summary": {
                "title": _summary_title(metrics, diagnostics),
                "subtitle": (
                    "英文 X 用来捕捉全球前沿，小红书看中文年轻用户需求，"
                    "抖音判断大众扩散与过热风险。"
                ),
            },
            "metrics": metrics,
            "stack_summary": _layer_summary(items, "stackLayer"),
            "need_summary": _layer_summary(items, "needLayer"),
            "diagnostics": diagnostics,
            "budget": budget,
            "collection_strategy": {
                "trigger": "manual",
                "new_signal_window_hours": 24,
                "rolling_windows_days": [7, 30, 90],
                "note": "每日只抓新增信号，但机会判断使用滚动窗口和跨平台扩散差。",
            },
            "items": items,
            "raw_signal_count": len(signals),
        }

    def _llm_items(
        self,
        signals: list[RawSignal],
        fallback_items: list[dict[str, Any]],
    ) -> list[dict[str, Any]] | None:
        if not self.llm_client or not self.model or not signals:
            return None
        payload = {
            "fallback_candidates": fallback_items[:12],
            "evidence": [signal.to_dict() for signal in _top_signals(signals, limit=80)],
        }
        response = self.llm_client.call(
            model=self.model,
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=json.dumps(payload, ensure_ascii=False),
            response_schema=_REPORT_SCHEMA,
            reasoning_effort=self.reasoning_effort,
            task_type="trend_radar_report",
        )
        data = response.structured_output or {}
        items = data.get("items")
        if not isinstance(items, list):
            return None
        normalized = [_normalize_item(item) for item in items if isinstance(item, dict)]
        return [item for item in normalized if item.get("title")]

    def _heuristic_items(self, signals: list[RawSignal]) -> list[dict[str, Any]]:
        grouped: dict[str, list[RawSignal]] = defaultdict(list)
        for signal in signals:
            if _is_verifiable_candidate(signal):
                grouped[signal.topic_id].append(signal)
        items = []
        for topic_id, group in grouped.items():
            if len(group) < _MIN_EVIDENCE_PER_ITEM:
                continue
            label = _specific_label(group[0].topic_label or topic_id, topic_id, group)
            platform_stats = _platform_stats(group)
            stage = _stage(platform_stats)
            score = _score(platform_stats, stage)
            top = _top_signals(group, limit=8)
            all_evidence = _evidence(top)
            evidence = [row for row in all_evidence if row["noiseRisk"] != "高"]
            if len(evidence) < _MIN_LOW_NOISE_EVIDENCE_PER_ITEM:
                continue
            source_quality = _source_quality(evidence, platform_stats)
            decision = _decision(stage, source_quality)
            stack_layer = _stack_layer(topic_id, label)
            need_layer = _need_layer(topic_id, label)
            items.append(
                {
                    "id": topic_id,
                    "title": _opportunity_title(label, stage, platform_stats),
                    "domain": _DOMAIN_BY_TOPIC.get(topic_id, "ai"),
                    "stackLayer": stack_layer,
                    "needLayer": need_layer,
                    "socialNeed": _social_need(label, need_layer, stage),
                    "supplyShift": _supply_shift(label, stack_layer, platform_stats),
                    "counterEvidence": _counter_evidence(stage, source_quality),
                    "opportunityType": _opportunity_type(stage, platform_stats, stack_layer),
                    "stage": stage,
                    "score": score,
                    "decision": decision,
                    "confidence": _confidence(group, platform_stats),
                    "cognitiveGap": _cognitive_gap(platform_stats),
                    "velocity": _velocity(group),
                    "gapMonths": _gap_months(platform_stats),
                    "verdict": _verdict(stage),
                    "marketWindow": _market_window(stage),
                    "summary": _summary_sentence(label, stage),
                    "userValue": _user_value(label, stage, platform_stats),
                    "whyNow": _why_now(label, platform_stats),
                    "validationAction": _validation_action(label, stage),
                    "exitSignal": "如果 10 个目标用户里少于 2 个愿意给真实场景或付费试用，先降级为观察。",
                    "bestFor": "能快速访谈用户、做窄场景验证、并把服务交付产品化的人。",
                    "notFor": "只追热点、没有一手用户或交付能力的人。",
                    "brief": _decision_brief(label, stage, platform_stats, evidence, source_quality),
                    "signals": platform_stats,
                    "evidence": evidence,
                    "evidenceCount": len(evidence),
                    "evidenceSummary": _evidence_summary(evidence, platform_stats),
                    "sourceQuality": source_quality,
                    "evidenceGrade": _evidence_grade(evidence, platform_stats),
                    "timeline": [],
                    "opposition": [],
                    "business": [],
                    "risks": [],
                }
            )
        return items

    def _localize_evidence_previews(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        _ensure_evidence_display_fields(items)
        if not self.llm_client or not self.model:
            return items

        rows: list[dict[str, Any]] = []
        row_by_id: dict[str, dict[str, Any]] = {}
        for item in items:
            for row in item.get("evidence") or []:
                if not isinstance(row, dict) or not _needs_chinese_preview(row):
                    continue
                row_id = str(row.get("id") or "")
                rows.append(
                    {
                        "id": row_id,
                        "platform": row.get("platform") or "",
                        "title": row.get("title") or "",
                        "summary": row.get("summary") or row.get("text") or "",
                    }
                )
                row_by_id[row_id] = row
                if len(rows) >= _MAX_LOCALIZED_EVIDENCE:
                    break
            if len(rows) >= _MAX_LOCALIZED_EVIDENCE:
                break

        if not rows:
            return items

        try:
            response = self.llm_client.call(
                model=self.model,
                system_prompt=_LOCALIZATION_SYSTEM_PROMPT,
                user_prompt=json.dumps({"evidence": rows}, ensure_ascii=False),
                response_schema=_LOCALIZATION_SCHEMA,
                reasoning_effort=self.reasoning_effort,
                task_type="trend_radar_evidence_localization",
            )
        except Exception:
            return items

        localized = (response.structured_output or {}).get("items")
        if not isinstance(localized, list):
            return items
        for entry in localized:
            if not isinstance(entry, dict):
                continue
            row = row_by_id.get(str(entry.get("id") or ""))
            if not row:
                continue
            title = str(entry.get("titleZh") or "").strip()
            summary = str(entry.get("summaryZh") or "").strip()
            if title:
                row["displayTitle"] = _compact_text(title, 90)
            if summary:
                row["displaySummary"] = _compact_text(summary, 220)
            if title or summary:
                row["translationStatus"] = "localized"
        return items


def _platform_stats(group: list[RawSignal]) -> dict[str, dict[str, Any]]:
    stats = {}
    for platform in ("x", "xiaohongshu", "douyin"):
        platform_group = [signal for signal in group if signal.platform == platform]
        sample = len(platform_group)
        engagement = sum(_engagement(signal) for signal in platform_group)
        negative = sum(_negative_count(signal.text + " " + signal.title) for signal in platform_group)
        accept = min(88, int(sample * 10 + sqrt(engagement) * 2.2))
        oppose = min(45, int(negative * 9 + sample * 1.5))
        unknown = max(0, 100 - accept - oppose)
        stats[platform] = {
            "label": _PLATFORM_LABELS[platform],
            "accept": accept,
            "oppose": oppose,
            "unknown": unknown,
            "signal": _platform_reading(platform, accept, oppose, unknown),
            "sample": sample,
        }
    return stats


def _stage(stats: dict[str, dict[str, Any]]) -> str:
    x = stats["x"]["accept"]
    xhs = stats["xiaohongshu"]["accept"]
    dy = stats["douyin"]["accept"]
    if x >= 75 and xhs >= 65 and dy >= 45:
        return "overheated"
    if x >= 60 and xhs >= 45 and dy >= 35:
        return "mature"
    if x >= 40 and xhs < 45 and dy < 35:
        return "opportunity"
    if x < 35 and xhs < 20 and dy < 20:
        return "too-early"
    return "noise"


def _score(stats: dict[str, dict[str, Any]], stage: str) -> int:
    x = stats["x"]["accept"]
    xhs = stats["xiaohongshu"]["accept"]
    dy = stats["douyin"]["accept"]
    gap = max(x - max(xhs, dy), 0)
    stage_bonus = {
        "opportunity": 28,
        "mature": 12,
        "too-early": 2,
        "overheated": -18,
        "noise": -8,
    }.get(stage, 0)
    return max(0, min(100, int(x * 0.45 + gap * 0.45 + stage_bonus)))


def _confidence(group: list[RawSignal], stats: dict[str, dict[str, Any]]) -> int:
    coverage = sum(1 for value in stats.values() if value["sample"] > 0)
    sample = min(len(group), 50)
    return min(92, 35 + coverage * 13 + sample)


def _cognitive_gap(stats: dict[str, dict[str, Any]]) -> int:
    x = stats["x"]["accept"]
    mass = (stats["xiaohongshu"]["accept"] + stats["douyin"]["accept"]) / 2
    return max(0, min(100, int(50 + x - mass)))


def _velocity(group: list[RawSignal]) -> int:
    engagement = sum(_engagement(signal) for signal in group)
    return min(95, int(len(group) * 6 + sqrt(engagement) * 1.8))


def _gap_months(stats: dict[str, dict[str, Any]]) -> int:
    gap = _cognitive_gap(stats)
    if gap >= 80:
        return 12
    if gap >= 65:
        return 9
    if gap >= 50:
        return 6
    return 3


def _metrics(items: list[dict[str, Any]]) -> dict[str, Any]:
    if not items:
        return {"new_window": 0, "mature": 0, "hot": 0, "confidence": 0, "gap_months": 0}
    return {
        "new_window": sum(1 for item in items if item.get("stage") == "opportunity"),
        "mature": sum(1 for item in items if item.get("stage") == "mature"),
        "hot": sum(1 for item in items if item.get("stage") == "overheated"),
        "confidence": int(sum(item.get("confidence", 0) for item in items) / len(items)),
        "gap_months": max(int(item.get("gapMonths", 0)) for item in items),
    }


def _layer_summary(items: list[dict[str, Any]], field: str) -> dict[str, int]:
    summary: dict[str, int] = {}
    for item in items:
        layer = item.get(field)
        layer_id = ""
        if isinstance(layer, dict):
            layer_id = str(layer.get("id") or "")
        if not layer_id:
            continue
        summary[layer_id] = summary.get(layer_id, 0) + 1
    return summary


def _diagnostics(signals: list[RawSignal]) -> dict[str, Any]:
    reasons: dict[str, int] = {}
    verifiable = 0
    for signal in signals:
        reason = _discard_reason(signal)
        if reason:
            reasons[reason] = reasons.get(reason, 0) + 1
        else:
            verifiable += 1
    return {
        "raw_signal_count": len(signals),
        "verifiable_signal_count": verifiable,
        "discarded_signal_count": len(signals) - verifiable,
        "discarded_reasons": reasons,
        "quality_gate": (
            "候选必须来自非泛热榜主题，包含可打开原文链接，"
            f"且每个趋势至少有 {_MIN_EVIDENCE_PER_ITEM} 条可复核依据。"
        ),
    }


def _discard_reason(signal: RawSignal) -> str:
    if signal.topic_id in _DISCOVERY_TOPIC_IDS:
        return "discovery_only"
    if not str(signal.url or "").startswith("http"):
        return "missing_source_url"
    text = (signal.text or signal.title or "").strip()
    if len(text) < 12:
        return "thin_text"
    if not _topic_relevant(signal):
        return "topic_mismatch"
    return ""


def _is_verifiable_candidate(signal: RawSignal) -> bool:
    return not _discard_reason(signal)


def _top_signals(signals: list[RawSignal], *, limit: int) -> list[RawSignal]:
    return sorted(signals, key=_signal_rank, reverse=True)[:limit]


def _signal_rank(signal: RawSignal) -> float:
    return log1p(max(_engagement(signal), 0)) * 8 + _freshness_weight(signal)


def _freshness_weight(signal: RawSignal) -> int:
    age_days = _age_days(signal)
    if age_days is None:
        return 20
    if age_days <= 3:
        return 90
    if age_days <= 7:
        return 70
    if age_days <= 30:
        return 35
    if age_days <= 90:
        return 5
    return -80


def _topic_relevant(signal: RawSignal) -> bool:
    required_groups = _TOPIC_REQUIRED_GROUPS.get(signal.topic_id)
    if required_groups:
        text = _normalized_text(f"{signal.title} {signal.text}")
        return all(any(term.casefold() in text for term in group) for group in required_groups)
    terms = _TOPIC_TERMS.get(signal.topic_id)
    if not terms:
        return True
    text = _normalized_text(f"{signal.title} {signal.text}")
    return any(term.casefold() in text for term in terms)


def _normalized_text(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").casefold())


def _engagement(signal: RawSignal) -> int:
    metrics = signal.metrics or {}
    return (
        max(metrics.get("like_count", 0), 0)
        + max(metrics.get("collect_count", 0), 0) * 2
        + max(metrics.get("comment_count", 0), 0) * 3
        + max(metrics.get("share_count", 0), 0) * 2
        + max(metrics.get("view_count", 0), 0) // 50
    )


def _negative_count(text: str) -> int:
    text = (text or "").casefold()
    return sum(1 for word in _NEGATIVE_WORDS if word in text)


def _evidence(signals: list[RawSignal]) -> list[dict[str, Any]]:
    evidence = []
    for signal in signals:
        if not _is_verifiable_candidate(signal):
            continue
        noise_risk = _noise_risk(signal)
        evidence.append(
            {
                "platform": _PLATFORM_LABELS.get(signal.platform, signal.platform),
                "type": _evidence_type(signal),
                "time": signal.published_at or "本次采样",
                "title": signal.title,
                "summary": _source_summary(signal),
                "keyFacts": _key_facts(signal),
                "text": _compact_text(signal.text or signal.title, 260),
                "rawText": _compact_text(signal.text or signal.title, 520),
                "url": signal.url,
                "author": signal.author,
                "metrics": dict(signal.metrics or {}),
                "engagement": _engagement(signal),
                "why": _evidence_reason(signal),
                "quality": _evidence_quality(signal, noise_risk),
                "noiseRisk": noise_risk,
                "sourceEndpoint": signal.source_endpoint,
            }
        )
    return sorted(evidence, key=_evidence_sort_key, reverse=True)[:8]


def _ensure_evidence_display_fields(items: list[dict[str, Any]]) -> None:
    for item in items:
        item_id = str(item.get("id") or "trend")
        for index, row in enumerate(item.get("evidence") or []):
            if not isinstance(row, dict):
                continue
            row.setdefault("id", f"{item_id}-{index}")
            title = str(row.get("title") or row.get("author") or "原始依据")
            summary = str(row.get("summary") or row.get("text") or title)
            row.setdefault("displayTitle", title)
            row.setdefault("displaySummary", summary)
            row.setdefault("translationStatus", "raw")


def _needs_chinese_preview(row: dict[str, Any]) -> bool:
    preview = f"{row.get('displayTitle') or ''} {row.get('displaySummary') or ''}"
    if _contains_cjk(preview):
        return False
    source = f"{row.get('title') or ''} {row.get('summary') or ''} {row.get('text') or ''}"
    return bool(source.strip()) and not _contains_cjk(source)


def _contains_cjk(value: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", value or ""))


def _evidence_sort_key(row: dict[str, Any]) -> tuple[int, int]:
    risk_weight = {"低": 3, "中": 2, "高": 1}.get(row.get("noiseRisk"), 1)
    platform_weight = {"英文 X": 3, "小红书": 2, "抖音": 1}.get(row.get("platform"), 1)
    return (risk_weight * platform_weight, int(row.get("engagement") or 0))


def _source_summary(signal: RawSignal) -> str:
    title = _compact_text(signal.title, 90)
    body = _compact_text(signal.text, 180)
    if title and body and title not in body:
        return _compact_text(f"{title}。{body}", 220)
    return _compact_text(body or title, 220)


def _key_facts(signal: RawSignal) -> list[str]:
    facts = [_PLATFORM_LABELS.get(signal.platform, signal.platform)]
    if signal.author:
        facts.append(f"作者：{signal.author}")
    if signal.published_at:
        facts.append(f"时间：{signal.published_at}")
    metric_facts = _metric_facts(signal.metrics or {})
    facts.extend(metric_facts[:2])
    return facts[:4]


def _metric_facts(metrics: dict[str, int]) -> list[str]:
    labels = (
        ("like_count", "赞"),
        ("comment_count", "评论"),
        ("share_count", "分享"),
        ("collect_count", "收藏"),
        ("view_count", "播放/浏览"),
    )
    facts = []
    for key, label in labels:
        value = int(metrics.get(key) or 0)
        if value > 0:
            facts.append(f"{label} {value}")
    return facts


def _noise_risk(signal: RawSignal) -> str:
    if signal.topic_id in _DISCOVERY_TOPIC_IDS:
        return "高"
    if not str(signal.url or "").startswith("http"):
        return "高"
    content = _strip_urls(f"{signal.title} {signal.text}").strip()
    if len(content) < 32:
        return "高"
    if _looks_like_hashtag_or_link_only(content):
        return "高"
    age_days = _age_days(signal)
    if age_days is not None and age_days > 90:
        return "高"
    if age_days is not None and age_days > 30:
        return "中"
    if not signal.author:
        return "中"
    return "低"


def _evidence_quality(signal: RawSignal, noise_risk: str) -> str:
    if noise_risk == "高":
        return "丢弃级噪音"
    if signal.platform == "x" and _engagement(signal) >= 300:
        return "高权重英文依据"
    if signal.platform in {"xiaohongshu", "douyin"} and _engagement(signal) >= 80:
        return "可复核中文依据"
    return "普通可复核依据"


def _strip_urls(text: str) -> str:
    return re.sub(r"https?://\S+|t\.co/\S+", "", text or "")


def _looks_like_hashtag_or_link_only(text: str) -> bool:
    tokens = [token for token in re.split(r"\s+", text.strip()) if token]
    if not tokens:
        return True
    hashtag_count = sum(1 for token in tokens if token.startswith("#"))
    return hashtag_count >= max(1, len(tokens) - 1)


def _age_days(signal: RawSignal) -> int | None:
    parsed = _parse_datetime(signal.published_at)
    if not parsed:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return max(0, (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).days)


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        pass
    try:
        return parsedate_to_datetime(text)
    except (TypeError, ValueError, IndexError, OverflowError):
        return None


def _compact_text(value: str | None, limit: int) -> str:
    text = re.sub(r"\s+", " ", (value or "").strip())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _evidence_type(signal: RawSignal) -> str:
    if signal.platform == "x":
        return "英文高质量依据"
    if signal.platform == "xiaohongshu":
        return "中文需求苗头"
    if signal.platform == "douyin":
        return "大众扩散依据"
    return "可复核依据"


def _evidence_reason(signal: RawSignal) -> str:
    if signal.platform == "x":
        return "用于判断英文区是否已有前沿讨论或精英分歧。"
    if signal.platform == "xiaohongshu":
        return "用于判断中文年轻用户是否出现真实问题和需求苗头。"
    if signal.platform == "douyin":
        return "用于判断大众层是否已经常识化、误解或过热。"
    return "用于人工复核趋势判断。"


def _opportunity_title(label: str, stage: str, stats: dict[str, dict[str, Any]]) -> str:
    if stage == "opportunity" and stats["x"]["sample"] and stats["douyin"]["sample"] == 0:
        return f"{label}：英文区已有信号，中文大众仍未常识化"
    if stage == "opportunity":
        return f"{label}：跨平台认知差仍在，适合小验证"
    if stage == "mature":
        return f"{label}：中文区开始扩散，进入最后窗口"
    if stage == "overheated":
        return f"{label}：多层共识偏高，警惕过热"
    return f"{label}：信号不足，继续观察"


def _specific_label(default_label: str, topic_id: str, group: list[RawSignal]) -> str:
    text = _normalized_text(" ".join(f"{signal.title} {signal.text}" for signal in group[:20]))
    if topic_id == "agentic-workflow":
        if _has_any(text, ("procurement", "supplier", "quote", "erp", "采购", "供应商", "报价", "询价")):
            return "AI 采购与供应商流程代理"
        if _has_any(text, ("audit", "permission", "governance", "权限", "审计", "治理")):
            return "企业 AI 智能体权限与审计"
        return "企业业务流程 AI 智能体"
    if topic_id == "consumer-ai":
        if _has_any(text, ("memory", "second brain", "记忆", "第二大脑")):
            return "个人 AI 记忆层"
        if _has_any(text, ("companion", "陪伴", "情绪", "女友")):
            return "AI 陪伴与情绪服务"
        return "消费级 AI 应用入口"
    if topic_id == "robotics":
        if _has_any(text, ("home robot", "chores", "家用", "家务", "伴侣")):
            return "家用与陪伴机器人"
        if _has_any(text, ("teleoperation", "data", "training", "远程操控", "训练数据")):
            return "机器人远程操控与训练数据"
        return "人形机器人商业化"
    if topic_id == "glp1-lifestyle":
        if _has_any(text, ("nutrition", "diet", "lifestyle", "饮食", "生活方式", "副作用")):
            return "GLP-1 后饮食与生活方式服务"
        if _has_any(text, ("access", "insurance", "$50", "eligible seniors", "可及", "医保", "老年")):
            return "GLP-1 药物可及性与后服务"
        return "GLP-1 后减重管理"
    return default_label


def _has_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term.casefold() in text for term in terms)


def _stack_layer(topic_id: str, label: str) -> dict[str, str]:
    layer_id = _STACK_BY_TOPIC.get(topic_id, "applications")
    text = _normalized_text(label)
    if _has_any(text, ("数据中心", "电力", "能源", "散热", "data center", "energy")):
        layer_id = "energy"
    elif _has_any(text, ("gpu", "芯片", "算力", "compute", "inference chip")):
        layer_id = "compute"
    elif _has_any(text, ("模型", "多模态", "推理", "world model", "memory layer")):
        layer_id = "models"
    elif _has_any(text, ("权限", "审计", "治理", "erp", "workflow", "基础设施")):
        layer_id = "infrastructure"
    return dict(_STACK_LAYERS[layer_id])


def _need_layer(topic_id: str, label: str) -> dict[str, str]:
    text = _normalized_text(label)
    if topic_id == "glp1-lifestyle" or _has_any(text, ("健康", "饮食", "睡眠", "照护", "减重", "医疗")):
        layer_id = "physiological"
    elif topic_id == "agentic-workflow" or _has_any(text, ("安全", "合规", "权限", "审计", "供应商", "财务")):
        layer_id = "safety"
    elif _has_any(text, ("陪伴", "社群", "家庭", "情绪", "关系")):
        layer_id = "belonging"
    elif _has_any(text, ("职业", "影响力", "身份", "能力证明")):
        layer_id = "esteem"
    elif _has_any(text, ("记忆", "学习", "知识", "研究", "决策", "第二大脑")):
        layer_id = "cognitive"
    elif _has_any(text, ("创作", "设计", "娱乐", "审美", "表达")):
        layer_id = "aesthetic"
    elif _has_any(text, ("创业", "人生", "目标", "个人系统")):
        layer_id = "self_actualization"
    else:
        layer_id = "cognitive"
    return dict(_NEED_LAYERS[layer_id])


def _social_need(label: str, need_layer: dict[str, str], stage: str) -> str:
    urgency = {
        "opportunity": "已经出现可验证缺口",
        "mature": "正在形成规模化需求",
        "overheated": "需求已被大量供给争夺",
        "too-early": "需求仍需要继续观察",
        "noise": "真实需求尚未分离",
    }.get(stage, "仍需复核")
    return (
        f"社会实际需求：{label} 对应{need_layer['label']}，"
        f"核心是{need_layer['summary']}当前判断为{urgency}。"
    )


def _supply_shift(
    label: str,
    stack_layer: dict[str, str],
    stats: dict[str, dict[str, Any]],
) -> str:
    return (
        f"供给侧变化：{stack_layer['label']}正在改变 {label} 的可行性。"
        f"本次样本中英文 X {stats['x']['sample']} 条、小红书 "
        f"{stats['xiaohongshu']['sample']} 条、抖音 {stats['douyin']['sample']} 条，"
        "需要用跨平台扩散差判断是否进入验证窗口。"
    )


def _counter_evidence(stage: str, source_quality: str) -> list[str]:
    if source_quality == "弱":
        return ["低噪音来源不足，不能仅凭热度判断机会。"]
    if stage == "overheated":
        return ["多平台已经形成较高共识，新入场可能面对同质化供给。"]
    if stage == "mature":
        return ["如果找不到明确垂直场景，泛方向投入的边际收益会下降。"]
    if stage == "opportunity":
        return ["如果访谈中没有真实预算、真实流程或持续使用场景，应降级观察。"]
    return ["如果连续两次报告没有新增高质量来源，应移出优先队列。"]


def _opportunity_type(
    stage: str,
    stats: dict[str, dict[str, Any]],
    stack_layer: dict[str, str],
) -> str:
    if stage == "overheated":
        return "过热预警"
    if stack_layer.get("id") in {"energy", "compute"}:
        return "底层约束"
    if stack_layer.get("id") in {"models", "infrastructure"} and stats["x"]["sample"] > 0:
        if stats["xiaohongshu"]["sample"] or stats["douyin"]["sample"]:
            return "需求爆发"
        return "能力突破"
    if stats["xiaohongshu"]["sample"] or stats["douyin"]["sample"]:
        return "需求爆发"
    return "前沿线索"


def _coerce_layer(value: Any, layers: dict[str, dict[str, str]], default_id: str) -> dict[str, str]:
    if isinstance(value, dict):
        layer_id = str(value.get("id") or "")
        if layer_id in layers:
            merged = dict(layers[layer_id])
            if value.get("label"):
                merged["label"] = str(value["label"])
            if value.get("summary"):
                merged["summary"] = str(value["summary"])
            return merged
    if isinstance(value, str) and value in layers:
        return dict(layers[value])
    return dict(layers[default_id])


def _user_value(label: str, stage: str, stats: dict[str, dict[str, Any]]) -> str:
    if stage == "opportunity":
        return (
            f"对你有价值的地方在于：{label} 已经有英文区可复核信号，"
            "但中文大众认知尚未充分扩散，可以优先做内容占位、用户访谈或窄场景服务验证。"
        )
    if stage == "mature":
        return f"{label} 已经开始进入中文区，适合寻找尚未被满足的垂直细分，不适合再做泛方向。"
    if stage == "overheated":
        return f"{label} 的共识可能过高，对你更有价值的是避开同质化供给，寻找反向退出或细分迁移信号。"
    return f"{label} 目前证据不足，价值在于继续观察，不建议立即投入产品化资源。"


def _why_now(label: str, stats: dict[str, dict[str, Any]]) -> str:
    return (
        f"{label} 的关键不是热度，而是平台之间的认知差："
        f"英文 X 有 {stats['x']['sample']} 条可复核信号，"
        f"小红书有 {stats['xiaohongshu']['sample']} 条，"
        f"抖音有 {stats['douyin']['sample']} 条。"
    )


def _evidence_summary(
    evidence: list[dict[str, Any]],
    stats: dict[str, dict[str, Any]],
) -> str:
    platforms = "、".join(
        label
        for key, label in (("x", "英文 X"), ("xiaohongshu", "小红书"), ("douyin", "抖音"))
        if stats[key]["sample"] > 0
    )
    quality_counts: dict[str, int] = {}
    for row in evidence:
        quality_counts[row["noiseRisk"]] = quality_counts.get(row["noiseRisk"], 0) + 1
    low_noise = quality_counts.get("低", 0) + quality_counts.get("中", 0)
    return (
        f"本趋势保留 {low_noise} 条低/中噪音可打开来源，覆盖 {platforms or '单一平台'}。"
        "先人工复核英文 X，再看中文平台是否只是跟风。"
    )


def _source_quality(
    evidence: list[dict[str, Any]],
    stats: dict[str, dict[str, Any]],
) -> str:
    low_noise = sum(1 for row in evidence if row.get("noiseRisk") == "低")
    has_x = any(row.get("platform") == "英文 X" for row in evidence)
    if has_x and low_noise >= 2 and len(evidence) >= 4:
        return "强"
    if has_x and len(evidence) >= 2:
        return "中"
    return "弱"


def _evidence_grade(
    evidence: list[dict[str, Any]],
    stats: dict[str, dict[str, Any]],
) -> str:
    quality = _source_quality(evidence, stats)
    if quality == "强":
        return "A"
    if quality == "中":
        return "B"
    return "C"


def _decision(stage: str, source_quality: str) -> str:
    if source_quality == "弱":
        return "继续观察"
    return {
        "opportunity": "现在验证",
        "mature": "只做垂直细分",
        "overheated": "不建议新入场",
        "too-early": "继续观察",
        "noise": "暂不入场",
    }.get(stage, "继续观察")


def _decision_brief(
    label: str,
    stage: str,
    stats: dict[str, dict[str, Any]],
    evidence: list[dict[str, Any]],
    source_quality: str,
) -> dict[str, str]:
    return {
        "verdict": _decision(stage, source_quality),
        "value": _brief_value(label, stage),
        "whyNow": _why_now(label, stats),
        "nextAction": _validation_action(label, stage),
        "killCriteria": _kill_criteria(stage),
        "limitations": _evidence_limitations(evidence, source_quality),
    }


def _brief_value(label: str, stage: str) -> str:
    if stage == "opportunity":
        return f"{label} 的价值在于认知差仍可能存在：先用小样本验证真实需求，不急着做大产品。"
    if stage == "mature":
        return f"{label} 已经开始扩散，价值只剩垂直细分和交付效率，不适合泛方向入场。"
    if stage == "overheated":
        return f"{label} 更像避坑信号：共识过高时，赚钱空间通常转向反向、细分或退出。"
    if stage == "too-early":
        return f"{label} 可能太早，价值是建立观察列表，不投入重资源。"
    return f"{label} 目前不构成机会，只保留为监控线索。"


def _kill_criteria(stage: str) -> str:
    if stage == "overheated":
        return "如果原始来源主要是泛教程、带货、复述和情绪讨论，直接判定为过热，不投入。"
    if stage == "mature":
        return "如果找不到明确垂直人群、付费场景或交付差异，放弃泛方向。"
    if stage == "opportunity":
        return "如果 10 个目标用户里少于 2 个愿意提供真实场景或付费试用，降级为观察。"
    return "如果连续 2 次报告仍没有低噪音原始来源，不进入验证。"


def _evidence_limitations(evidence: list[dict[str, Any]], source_quality: str) -> str:
    platforms = sorted({row.get("platform", "") for row in evidence if row.get("platform")})
    return (
        f"证据质量为{source_quality}，只代表本次采样；"
        f"当前可复核平台：{'、'.join(platforms) or '无'}。"
        "报告不替代人工阅读原文和访谈验证。"
    )


def _timeline(stats: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    x = stats["x"]["accept"]
    xhs = stats["xiaohongshu"]["accept"]
    dy = stats["douyin"]["accept"]
    return [
        {"label": "30 天前", "x": max(x - 24, 0), "xhs": max(xhs - 12, 0), "douyin": max(dy - 9, 0)},
        {"label": "7 天前", "x": max(x - 10, 0), "xhs": max(xhs - 5, 0), "douyin": max(dy - 4, 0)},
        {"label": "今天", "x": x, "xhs": xhs, "douyin": dy},
    ]


def _opposition(group: list[RawSignal], stats: dict[str, dict[str, Any]]) -> list[dict[str, str]]:
    opposition = []
    if stats["x"]["oppose"] >= 10:
        opposition.append(
            {
                "type": "精英分歧",
                "group": "英文 X 专业讨论者",
                "strength": "中",
                "reading": "反对不一定是坏事，重点看争议是否围绕真实落地约束。",
            }
        )
    if stats["douyin"]["unknown"] >= 55:
        opposition.append(
            {
                "type": "大众未知",
                "group": "抖音大众用户",
                "strength": "低",
                "reading": "大众尚未形成共识，说明中文市场仍可能存在认知差。",
            }
        )
    if not opposition:
        opposition.append(
            {
                "type": "反对较弱",
                "group": "跨平台样本",
                "strength": "低",
                "reading": "需要继续抓评论和真实需求，防止把热度误判为机会。",
            }
        )
    return opposition


def _platform_reading(platform: str, accept: int, oppose: int, unknown: int) -> str:
    if platform == "x" and accept >= 40 and unknown <= 45:
        return "高质量英文讨论已经开始出现，可作为前沿信号。"
    if platform != "x" and unknown >= 55:
        return "中文大众认知仍弱，适合继续验证需求而非追热度。"
    if accept >= 60:
        return "接受度已经较高，注意是否进入成熟或过热阶段。"
    if oppose >= 25:
        return "反对声音偏强，需要区分低信息反对与真实约束。"
    return "信号较弱，样本不足时只作为观察项。"


def _summary_title(metrics: dict[str, Any], diagnostics: dict[str, Any] | None = None) -> str:
    if not metrics.get("new_window") and not metrics.get("mature") and not metrics.get("hot"):
        if diagnostics and diagnostics.get("raw_signal_count"):
            return "本次没有足够可信的机会信号"
        return "今天适合观察，不急于下注"
    if metrics.get("new_window"):
        return "英文区已经动起来，中文市场仍有认知差"
    if metrics.get("hot"):
        return "今天过热信号更强，适合筛掉晚期机会"
    return "今天适合观察，不急于下注"


def _summary_sentence(label: str, stage: str) -> str:
    if stage == "opportunity":
        return f"{label} 已在英文高质量讨论中出现，但中文平台尚未形成共识。"
    if stage == "mature":
        return f"{label} 已经扩散到中文年轻用户，可能是最后入场窗口。"
    if stage == "overheated":
        return f"{label} 的跨层共识过高，新入场性价比下降。"
    if stage == "too-early":
        return f"{label} 仍偏前沿，需要更多耐心和资源。"
    return f"{label} 信号混杂，需要等待更清晰的需求证据。"


def _verdict(stage: str) -> str:
    return {
        "opportunity": "现在做窄场景验证",
        "mature": "最后窗口，必须垂直化",
        "overheated": "不建议新入场",
        "too-early": "长期观察，不急",
        "noise": "暂不作为主机会",
    }.get(stage, "继续观察")


def _market_window(stage: str) -> str:
    return {
        "opportunity": "精英层开始接受或分裂，大众尚未常识化。",
        "mature": "精英层普遍接受，中文年轻用户已有明显认知。",
        "overheated": "多层人群已经形成共识，红利正在消失。",
        "too-early": "前沿圈仍未形成足够一致的落地判断。",
        "noise": "热度和真实需求尚未分离。",
    }.get(stage, "需要继续采样。")


def _validation_action(label: str, stage: str) -> str:
    if stage == "opportunity":
        return f"3 天内访谈 5 个目标用户，用 {label} 做一个可点击样例或服务化交付。"
    if stage == "mature":
        return f"只选 {label} 的垂直细分，验证是否还有未被服务的人群。"
    return f"继续监控 {label} 的评论和真实付费线索，不急于产品化。"


def _business(label: str, stage: str) -> list[str]:
    if stage in {"opportunity", "mature"}:
        return [
            f"围绕 {label} 做窄场景 SaaS 或自动化工具。",
            "先用咨询/服务交付拿真实数据，再产品化。",
            "内容占位：案例库、模板、清单和决策指南。",
        ]
    return ["保留监控，不作为主产品方向。", "只在出现强需求样本后再开验证。"]


def _risks(stage: str) -> list[str]:
    if stage == "overheated":
        return ["共识过高，获客成本可能已经超过机会收益。", "容易被大量同质化供给淹没。"]
    if stage == "too-early":
        return ["教育成本高，现金流周期长。", "可能需要技术或产业资源才能等到成熟期。"]
    return ["样本可能被平台算法放大，需要人工复核证据。", "必须用真实访谈验证，不要只看热度。"]


def _normalize_item(item: dict[str, Any]) -> dict[str, Any]:
    item_id = str(item.get("id") or item.get("title") or "trend").lower().replace(" ", "-")
    title = str(item.get("title") or "")
    stack_layer = _coerce_layer(
        item.get("stackLayer") or item.get("stack_layer") or _stack_layer(item_id, title),
        _STACK_LAYERS,
        "applications",
    )
    need_layer = _coerce_layer(
        item.get("needLayer") or item.get("need_layer") or _need_layer(item_id, title),
        _NEED_LAYERS,
        "cognitive",
    )
    base = {
        "id": item_id,
        "title": title,
        "domain": item.get("domain") or "ai",
        "stackLayer": stack_layer,
        "needLayer": need_layer,
        "socialNeed": item.get("socialNeed") or item.get("social_need") or _social_need(title, need_layer, item.get("stage") or "noise"),
        "supplyShift": item.get("supplyShift") or item.get("supply_shift") or "",
        "counterEvidence": item.get("counterEvidence") or item.get("counter_evidence") or [],
        "opportunityType": item.get("opportunityType") or item.get("opportunity_type") or "前沿线索",
        "stage": item.get("stage") or "noise",
        "score": int(item.get("score") or 0),
        "decision": item.get("decision") or item.get("verdict") or "继续观察",
        "confidence": int(item.get("confidence") or 0),
        "cognitiveGap": int(item.get("cognitiveGap") or item.get("cognitive_gap") or 0),
        "velocity": int(item.get("velocity") or 0),
        "gapMonths": int(item.get("gapMonths") or item.get("gap_months") or 0),
        "verdict": item.get("verdict") or "继续观察",
        "marketWindow": item.get("marketWindow") or item.get("market_window") or "",
        "summary": item.get("summary") or "",
        "userValue": item.get("userValue") or item.get("user_value") or "",
        "whyNow": item.get("whyNow") or item.get("why_now") or "",
        "validationAction": item.get("validationAction") or item.get("validation_action") or "",
        "exitSignal": item.get("exitSignal") or item.get("exit_signal") or "",
        "bestFor": item.get("bestFor") or item.get("best_for") or "",
        "notFor": item.get("notFor") or item.get("not_for") or "",
        "brief": item.get("brief") or {},
        "signals": item.get("signals") or {},
        "evidence": item.get("evidence") or [],
        "evidenceCount": int(item.get("evidenceCount") or item.get("evidence_count") or 0),
        "evidenceSummary": item.get("evidenceSummary") or item.get("evidence_summary") or "",
        "sourceQuality": item.get("sourceQuality") or item.get("source_quality") or "弱",
        "evidenceGrade": item.get("evidenceGrade") or item.get("evidence_grade") or "C",
        "timeline": item.get("timeline") or [],
        "opposition": item.get("opposition") or [],
        "business": item.get("business") or [],
        "risks": item.get("risks") or [],
    }
    return base


_SYSTEM_PROMPT = """你是一个趋势机会雷达分析师。
目标：识别“英文高质量人群开始接受/分裂，但中文年轻用户和大众尚未形成共识”的商业机会窗口。
不要追求大而全，只输出最值得验证的 10-20 个趋势卡片。
判断阶段必须区分：too-early、opportunity、mature、overheated、noise。
所有结论必须引用 evidence 中可见的跨平台信号，不要编造不存在的事实。"""

_LOCALIZATION_SYSTEM_PROMPT = """你只负责把趋势雷达的英文证据预览转换成中文。
规则：
1. 只翻译和压缩用户给出的 title/summary，不添加原文没有的信息。
2. 保留产品名、人名、公司名、数字、金额、百分比和专有名词。
3. titleZh 用一句中文说明这条来源在说什么，尽量少于 36 个汉字。
4. summaryZh 用中文概括关键信息和可核查点，尽量少于 90 个汉字。
5. 如果原文信息不足，直接说明“原文信息不足，只能看到……”。"""

_REPORT_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "title": {"type": "string"},
                    "domain": {"type": "string"},
                    "stage": {"type": "string"},
                    "score": {"type": "integer"},
                    "decision": {"type": "string"},
                    "confidence": {"type": "integer"},
                    "cognitiveGap": {"type": "integer"},
                    "velocity": {"type": "integer"},
                    "gapMonths": {"type": "integer"},
                    "verdict": {"type": "string"},
                    "marketWindow": {"type": "string"},
                    "summary": {"type": "string"},
                    "whyNow": {"type": "string"},
                    "validationAction": {"type": "string"},
                    "exitSignal": {"type": "string"},
                    "bestFor": {"type": "string"},
                    "notFor": {"type": "string"},
                    "brief": {"type": "object"},
                    "signals": {"type": "object"},
                    "evidence": {"type": "array", "items": {"type": "object"}},
                    "evidenceGrade": {"type": "string"},
                    "timeline": {"type": "array", "items": {"type": "object"}},
                    "opposition": {"type": "array", "items": {"type": "object"}},
                    "business": {"type": "array", "items": {"type": "string"}},
                    "risks": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["title", "stage", "score", "summary", "signals", "evidence"],
            },
        }
    },
    "required": ["items"],
}

_LOCALIZATION_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "titleZh": {"type": "string"},
                    "summaryZh": {"type": "string"},
                },
                "required": ["id", "titleZh", "summaryZh"],
            },
        }
    },
    "required": ["items"],
}
