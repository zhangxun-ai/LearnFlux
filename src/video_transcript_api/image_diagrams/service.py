"""Durable, manually authorized image generation and non-retrying workers."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import threading
from typing import Callable
from zoneinfo import ZoneInfo

from ..utils.logging import setup_logger
from .artifacts import ImageDiagramArtifacts
from .client import ImageDiagramAPIError
from .prompts import PROMPT_VERSION, STYLES, build_image_prompt, plan_reference_ids
from .source import select_source


logger = setup_logger("image_diagrams")
ACTIVE = {"queued", "planning", "generating", "reviewing"}
ERROR_MESSAGES = {
    "image_outcome_unknown": "请求已发出，但未能确认结果。为避免重复收费，未自动重发；请先核对 OpenAI 用量。",
    "feature_disabled": "图解生成尚未启用，请检查后端的 OpenAI 配置。",
    "source_not_ready": "原文尚未就绪，请等待解析完成后再生成。",
    "source_access_revoked": "原文的访问权限或任务状态已改变，已停止生成。",
    "source_too_long": "原文超过本次生成上限，请选择章节生成。",
    "image_diagram_daily_limit": "今天的图解生成次数已达设置上限。",
    "invalid_section": "所选章节已改变，请刷新后重新选择。",
    "invalid_revision": "无法找到同一篇内容的原图，请刷新后重新选择。",
    "generation_failed": "本次生成未完成，请查看已有版本；重新生成需手动触发。",
    "openai_access_denied": "OpenAI 拒绝访问，请检查后端密钥与模型权限。",
    "openai_quota_or_rate_limit": "OpenAI 额度不足或请求受限，未自动重试。",
    "openai_request_rejected": "OpenAI 未接受本次请求，请检查模型配置和绘图要求。",
    "openai_key_missing": "后端尚未配置 OPENAI_API_KEY。",
    "invalid_image_plan_reference": "绘图方案的原文引用未通过核对，已停止生图；可手动重试。",
}


def _hash(value: dict) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
    ).encode()).hexdigest()


class ImageDiagramService:
    """Own one bounded worker; all paid work originates from persisted POSTs."""

    def __init__(self, *, repository, settings, client, source_loader: Callable,
                 authorize: Callable, artifacts: ImageDiagramArtifacts | None = None,
                 reference_dir: Path | None = None):
        self.repository = repository
        self.settings = settings
        self.client = client
        self.source_loader = source_loader
        self.authorize = authorize
        self.artifacts = artifacts or ImageDiagramArtifacts(settings.data_dir)
        self.reference_dir = reference_dir or Path(__file__).parent / "assets"
        self._guard = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._worker: threading.Thread | None = None

    def start(self) -> None:
        """Resume queued authorized work without resubmitting uncertain images."""
        if not self.settings.enabled:
            return
        with self._guard:
            if self._worker and self._worker.is_alive():
                self._wake.set()
                return
            self._stop.clear()
            self.repository.recover_interrupted()
            self._worker = threading.Thread(target=self._run, name="image-diagrams", daemon=True)
            self._worker.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        self._wake.set()
        if self._worker:
            self._worker.join(timeout=timeout)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.repository.recover_interrupted()
                if self.process_next():
                    continue
            except Exception:
                # Do not log provider exceptions or source text.
                logger.warning("Image diagram worker paused after a local failure")
            self._wake.wait(3.0)
            self._wake.clear()

    def state(self, view_token: str, owner_user_id: str) -> dict:
        self.authorize(view_token, owner_user_id)
        try:
            source = self.source_loader(view_token)
        except ValueError as exc:
            if str(exc) != "source_not_ready":
                raise
            source = {"title": "学习内容", "sections": [], "source_hash": ""}
        versions = self.repository.list_for_source(owner_user_id, view_token)
        return {
            "enabled": self.settings.enabled,
            "source_ready": bool(source.get("source_hash")),
            "title": source["title"],
            "styles": [{"id": key, "label": value["label"]} for key, value in STYLES.items()],
            "sections": [{"id": s["id"], "title": s["title"]} for s in source["sections"]],
            "versions": [self.public(job, source["source_hash"]) for job in versions],
            "active_job": next((self.public(job, source["source_hash"])
                                for job in versions if job["status"] in ACTIVE), None),
            "source_limitation": source.get("visual_limitations"),
        }

    def prepare(self, view_token: str, owner_user_id: str, request: dict) -> dict:
        """Persist a manual action before a worker is allowed to call OpenAI."""
        self.authorize(view_token, owner_user_id)
        if not self.settings.enabled:
            raise ValueError("feature_disabled")
        if request.get("style") not in STYLES:
            raise ValueError("invalid_style")
        source = self.source_loader(view_token)
        selected = select_source(source, request)
        if selected["source_chars"] > self.settings.max_source_chars:
            raise ValueError("source_too_long")
        parent = None
        if request.get("revision_of"):
            identity = self.repository.get_identity(request["revision_of"])
            if (not identity or identity["owner_user_id"] != owner_user_id
                    or identity["view_token"] != view_token):
                raise ValueError("invalid_revision")
            parent = self.repository.get(request["revision_of"])
            if not parent.get("image_key"):
                raise ValueError("invalid_revision")
            self.artifacts.image_path(parent["image_key"])
        meaningful = {key: request.get(key) for key in (
            "scope", "section_id", "style", "instructions", "revision_of",
        )}
        recipe = _hash({
            "source_hash": source["source_hash"], "request": meaningful,
            "prompt_version": PROMPT_VERSION, "image_model": self.settings.image_model,
            "text_model": self.settings.text_model, "size": self.settings.size,
            "quality": self.settings.quality,
            "reference_hash": self._reference_hash(request["style"]),
        })
        request_key = _hash({"owner": owner_user_id, "source": view_token,
                             "request_id": request["request_id"]})
        existing = self.repository.get_by_request_key(request_key) if hasattr(self.repository, "get_by_request_key") else None
        if existing is not None:
            if existing["request"] != request:
                raise ValueError("image_diagram_request_key_conflict")
            return existing
        if not request.get("regenerate") and not parent:
            cached = self.repository.find_reusable(owner_user_id, view_token, recipe)
            if cached:
                return cached
        day = datetime.now(ZoneInfo("Asia/Shanghai")).replace(hour=0, minute=0, second=0, microsecond=0)
        return self.repository.create_or_get(
            owner_user_id=owner_user_id, view_token=view_token,
            request_key=request_key, recipe_key=recipe, source_hash=source["source_hash"],
            request=request, source=source, parent_id=parent["id"] if parent else None,
            max_daily_generations=self.settings.max_daily_generations,
            day_start=day.astimezone(timezone.utc).isoformat(),
        )

    def _references(self, style: str) -> list[Path]:
        path = self.reference_dir / ("warm-guide.png" if style == "warm-guide" else "handdrawn.png")
        if not path.is_file() or path.is_symlink():
            raise ValueError("style_reference_missing")
        return [path]

    def _reference_hash(self, style: str) -> str:
        return hashlib.sha256(self._references(style)[0].read_bytes()).hexdigest()

    def get_owned(self, job_id: str, owner_user_id: str) -> dict:
        identity = self.repository.get_identity(job_id)
        if not identity or identity["owner_user_id"] != owner_user_id:
            raise LookupError("image_diagram_not_found")
        self.authorize(identity["view_token"], owner_user_id)
        return self.repository.get(job_id)

    def _cached_plan(self, job: dict) -> dict | None:
        """Reuse only a matching authorized source and unchanged content request."""
        key = self._plan_key(job)
        for previous in self.repository.list_for_source(job["owner_user_id"], job["view_token"]):
            plan = previous.get("plan") or {}
            if (previous["status"] == "succeeded" and previous["source_hash"] == job["source_hash"]
                    and plan.get("_cache_key") == key and plan.get("mode") != "direct"):
                return dict(plan)
        return None

    def _plan_key(self, job: dict) -> str:
        request = job["request"]
        return _hash({"source": job["source_hash"], "scope": request.get("scope"),
                      "section": request.get("section_id"), "instructions": request.get("instructions") or "",
                      "parent": job.get("parent_id"),
                      "model": self.settings.text_model, "version": PROMPT_VERSION})

    def process_next(self) -> bool:
        job = self.repository.claim_next(metadata_only=True)
        if job is None:
            return False
        job_id, token = job["id"], job["generation_token"]
        submitted = False
        image_key = None
        usage = {}
        heartbeat_stop = threading.Event()

        def heartbeat():
            while not heartbeat_stop.wait(15.0):
                try:
                    if not self.repository.heartbeat(job_id, token):
                        return
                except Exception:
                    logger.warning("Image diagram heartbeat temporarily unavailable: job={}", job_id)

        heartbeat_thread = threading.Thread(target=heartbeat, name="image-diagram-heartbeat", daemon=True)
        heartbeat_thread.start()
        try:
            self.authorize(job["view_token"], job["owner_user_id"])
            job = self.repository.get(job_id)
            parent = self.get_owned(job["parent_id"], job["owner_user_id"]) if job.get("parent_id") else None
            if parent and parent["view_token"] != job["view_token"]:
                raise ValueError("invalid_revision")
            source = select_source(job["source"], job["request"])
            self.artifacts.write_json(job_id, "source", source)
            self.artifacts.write_json(job_id, "request", job["request"])
            def record_progress(progress: dict) -> None:
                try:
                    current = self.repository.update(job_id, token, plan={"progress": progress})
                except Exception:
                    raise ImageDiagramAPIError("image_progress_unavailable") from None
                if not current:
                    raise ImageDiagramAPIError("image_planning_interrupted")

            try:
                direct_prompt = build_image_prompt(source, None, job["request"])
            except ValueError as exc:
                if str(exc) != "image_diagram_prompt_too_long":
                    raise
                direct_prompt = None
            if direct_prompt is not None:
                plan = {"mode": "direct", "coverage": {"mode": "direct", "source_chars": source["source_chars"]}}
                usage["planning"] = {"calls": [], "mode": "direct"}
            else:
                plan = self._cached_plan(job)
                if plan:
                    usage["planning"] = {"calls": [], "mode": "reused"}
                else:
                    same_material = (parent and parent["source_hash"] == job["source_hash"]
                                     and parent["request"].get("scope") == job["request"].get("scope")
                                     and parent["request"].get("section_id") == job["request"].get("section_id"))
                    planning_request = {**job["request"], **({"previous_plan": parent.get("plan")} if same_material else {})}
                    plan = self.client.plan(source, planning_request, on_progress=record_progress)
                    usage["planning"] = plan.pop("usage", {})
                    plan["_cache_key"] = self._plan_key(job)
            self.artifacts.write_json(job_id, "plan", plan)
            if not self.repository.update(job_id, token, plan=plan, usage=usage):
                return True
            prompt = direct_prompt or build_image_prompt(source, plan, job["request"])
            self.artifacts.write_prompt(job_id, prompt)
            references = self._references(job["request"]["style"])
            revision = self.artifacts.image_path(parent["image_key"]) if parent else None
            # Recheck current ownership after planning, before the image submission.
            self.authorize(job["view_token"], job["owner_user_id"])
            if self._stop.is_set():
                return True  # Unsubmitted planning work can safely recover later.
            if not self.repository.update(job_id, token, status="generating", stage="generating"):
                return True
            submitted = True
            result = self.client.generate(prompt, references, revision_image=revision)
            usage["image"] = {"model": self.settings.image_model,
                              "usage": result.get("usage") or {},
                              "request_id": result.get("request_id")}
            image_key = self.artifacts.save_image(job_id, result["image_bytes"])
            self.artifacts.write_json(job_id, "usage", usage)
            self.repository.update(job_id, token, status="succeeded", stage="completed",
                                   image_key=image_key, usage=usage)
        except ImageDiagramAPIError as exc:
            usage.update(getattr(exc, "usage", {}) or {})
            status = "unknown" if submitted and exc.unknown_outcome else "failed"
            self.repository.update(job_id, token, status=status, stage=status,
                                   error_code=exc.code, usage=usage)
        except Exception:
            # A successful remote call followed by an uncertain local failure is
            # never treated as permission to submit the image request again.
            status = "unknown" if submitted else "failed"
            code = "image_outcome_unknown" if submitted else "generation_failed"
            if image_key:
                self.repository.update(job_id, token, status="succeeded", stage="completed",
                                       image_key=image_key, usage=usage)
            else:
                self.repository.update(job_id, token, status=status, stage=status,
                                       error_code=code, usage=usage)
            logger.warning("Image diagram stopped: job={} code={}", job_id, code)
        finally:
            heartbeat_stop.set()
            heartbeat_thread.join(timeout=0.2)
        return True

    @staticmethod
    def public(job: dict, current_source_hash: str | None = None) -> dict:
        request = job.get("request") or {}
        source = job.get("source") or {}
        section = next((s for s in source.get("sections", [])
                        if s["id"] == request.get("section_id")), {})
        image = f"/api/image-diagrams/jobs/{job['id']}/image" if job.get("image_key") else None
        code = job.get("error_code")
        plan = job.get("plan") or {}
        cited_refs = set(plan_reference_ids(plan))
        return {
            **{key: job.get(key) for key in ("id", "status", "stage", "created_at", "updated_at", "parent_id", "source_hash")},
            "scope": request.get("scope", "overview"), "section_id": request.get("section_id"),
            "section_title": section.get("title"), "style": request.get("style"),
            "image_url": image, "download_url": image + "?download=1" if image else None,
            "usage": job.get("usage"),
            "progress": plan.get("progress") if job.get("status") == "planning" else None,
            "error_code": code, "error_message": ERROR_MESSAGES.get(code, ERROR_MESSAGES["generation_failed"]) if code else None,
            "stale": bool(current_source_hash and job["source_hash"] != current_source_hash),
            "source_refs": [{"id": p["id"], "line_id": p.get("line_id"),
                             "source_kind": source.get("source_type", "original"),
                             "start_seconds": p.get("start_seconds"),
                             "paragraph_index": p.get("paragraph_index"), "excerpt": p["text"][:240]}
                            for p in source.get("paragraphs", [])
                            if p["id"] in cited_refs],
        }
