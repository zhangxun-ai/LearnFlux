import asyncio
import copy
import datetime
import inspect
import os
import subprocess
import threading
import time
from typing import Optional, Dict, Any

from fastapi import HTTPException, Header, Request
from pydantic import BaseModel, Field, field_validator

from ..context import (
    get_audit_logger,
    get_cache_manager,
    get_config,
    get_executor,
    get_llm_queue,
    get_logger,
    get_task_queue,
    get_temp_manager,
    get_user_manager,
)
from ...downloaders import create_downloader
from ...transcriber import FunASRSpeakerClient, Transcriber
from ...utils.notifications import (
    WechatNotifier,
    send_long_text_wechat,
    get_notification_router,
)
from ...utils.notifications.channel import _clean_url
from ...utils.rendering import get_base_url
from ...utils.perf_tracker import PerfTracker
from ...utils.task_status import TaskStatus
from ...utils.task_progress import estimate_eta_seconds

logger = get_logger()
config = get_config()
user_manager = get_user_manager()
audit_logger = get_audit_logger()
cache_manager = get_cache_manager()
task_queue = get_task_queue()
llm_task_queue = get_llm_queue()
executor = get_executor()


def _safe_update_progress(task_id: str, **kwargs):
    """Best-effort task progress update; progress must not break the task."""
    try:
        return cache_manager.update_task_progress(task_id, **kwargs)
    except Exception as exc:
        logger.debug(f"task progress update failed: {task_id}, error={exc}")
        return None


def _extract_audio_to_file(src_path: str, out_dir: str, media_id: str) -> Optional[str]:
    """用 ffmpeg 抽取 16kHz 单声道压缩音频(m4a)，体积远小于原视频。

    本地上传转写时先抽小音频、删原视频，避免几个 G 的文件在整个转写期间一直占盘
    （参考本地 video2audio.sh 的做法）。失败返回 None，调用方退回直接转写原文件。
    """
    try:
        out_path = os.path.join(out_dir, f"{media_id}.audio.m4a")
        cmd = [
            "ffmpeg", "-y", "-i", src_path,
            "-vn", "-ac", "1", "-ar", "16000", "-c:a", "aac", "-b:a", "64k",
            out_path,
        ]
        proc = subprocess.run(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3600
        )
        if proc.returncode == 0 and os.path.exists(out_path) and os.path.getsize(out_path) > 0:
            return out_path
        logger.warning(f"ffmpeg 抽音频返回码 {proc.returncode}，退回直接转写原文件")
    except Exception as exc:
        logger.warning(f"ffmpeg 抽音频异常，退回直接转写原文件: {exc}")
    return None


# 文档类扩展名：走文本提取（而非音视频转写）
_DOC_EXTS = {".txt", ".md", ".markdown", ".csv", ".log", ".pdf", ".docx"}


def _extract_document_text(path: str, ext: str) -> str:
    """从本地文档提取纯文本：txt/md/csv/log 直接读，pdf 用 pypdf，docx 用 python-docx。"""
    ext = (ext or "").lower()
    if ext in (".txt", ".md", ".markdown", ".csv", ".log"):
        with open(path, "rb") as f:
            raw = f.read()
        for enc in ("utf-8", "gb18030", "latin-1"):
            try:
                return raw.decode(enc).strip()
            except UnicodeDecodeError:
                continue
        return raw.decode("utf-8", errors="ignore").strip()
    if ext == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(path)
        parts = [(page.extract_text() or "") for page in reader.pages]
        return "\n".join(parts).strip()
    if ext == ".docx":
        import docx

        document = docx.Document(path)
        return "\n".join(p.text for p in document.paragraphs).strip()
    raise ValueError(f"不支持的文档格式: {ext}")


def process_local_upload(
    task_id: str,
    file_path: str,
    original_name: str,
    display_url: str,
    media_id: str,
    use_speaker_recognition: bool = False,
) -> Dict[str, Any]:
    """处理本地上传的音视频或文档，复用 LLM 后处理与结果页。

    音视频：本地 mlx-whisper 转写（先抽小音频省空间）。文档(txt/md/pdf/docx)：直接提取文本。
    两者都与平台字幕路径同构地 save_cache + 入 LLM 队列；/view/<view_token> 查看；临时文件用后即删。
    """
    tracker = PerfTracker(task_id=task_id)
    audio_path = None
    try:
        cache_manager.update_task_status(task_id, TaskStatus.PROCESSING)

        if not os.path.exists(file_path):
            cache_manager.update_task_status(
                task_id, TaskStatus.FAILED, error_message="上传文件不存在"
            )
            return {"status": "failed", "message": "上传文件不存在"}

        ext = os.path.splitext(original_name)[1].lower()

        if ext in _DOC_EXTS:
            # 文档：直接提取文本，不走转写
            _safe_update_progress(
                task_id, stage="transcribing", stage_label="正在解析文档",
                basis="local_upload", confidence="high",
            )
            transcript = _extract_document_text(file_path, ext).strip()
            empty_msg = "未能从文档中提取到文本（可能是扫描件/图片型 PDF）"
        else:
            # 音视频：省空间——先抽 16kHz 单声道小音频、立即删原视频，再转写音频，
            # 避免几个 G 的视频在整个转写期间占盘。抽取失败则退回直接转写原文件。
            _safe_update_progress(
                task_id, stage="transcribing", stage_label="正在提取音频",
                basis="local_upload", confidence="high",
            )
            audio_path = _extract_audio_to_file(file_path, os.path.dirname(file_path), media_id)
            transcribe_target = file_path
            if audio_path:
                transcribe_target = audio_path
                try:
                    os.remove(file_path)
                    logger.info(
                        f"已抽音频并删除原文件，省空间: task={task_id}, audio={os.path.basename(audio_path)}"
                    )
                except OSError:
                    pass

            _safe_update_progress(
                task_id, stage="transcribing", stage_label="正在转录本地文件",
                basis="local_upload", confidence="high",
            )
            # 长视频（如 1-2 小时）可能超过默认 30 分钟的转写超时，
            # 这里为本地上传放宽到 4 小时，避免长内容半途超时失败。
            upload_cfg = copy.deepcopy(get_config())
            _lw = upload_cfg.setdefault("local_whisper", {})
            _lw["timeout"] = max(int(_lw.get("timeout") or 1800), 14400)
            transcriber = Transcriber(
                config=upload_cfg,
                progress_callback=_make_asr_progress_callback(task_id, "local-upload"),
            )
            output_base = (
                datetime.datetime.now().strftime("%y%m%d-%H%M%S") + "_" + media_id[:8]
            )
            result = transcriber.transcribe(transcribe_target, output_base)
            transcript = (result.get("transcript") or "").strip()
            empty_msg = "转录结果为空"

        if not transcript:
            cache_manager.update_task_status(
                task_id, TaskStatus.FAILED, error_message=empty_msg
            )
            return {"status": "failed", "message": empty_msg}

        cache_manager.save_cache(
            platform="generic",
            url=display_url,
            media_id=media_id,
            use_speaker_recognition=False,
            transcript_data=transcript,
            transcript_type="capswriter",
            title=original_name,
            author="本地上传",
            description="",
        )

        llm_task_queue.put(
            {
                "task_id": task_id,
                "url": display_url,
                "display_url": original_name,
                "platform": "generic",
                "media_id": media_id,
                "video_title": original_name,
                "author": "本地上传",
                "description": "",
                "transcript": transcript,
                "use_speaker_recognition": False,
                "is_generic": True,
                "wechat_webhook": None,
                "notification_channel": None,
                "notification_webhooks": {},
                "include_comments": False,
                "comment_limit": 100,
                "perf_tracker": tracker,
            }
        )
        cache_manager.update_task_status(
            task_id, TaskStatus.CALIBRATING, platform="generic", media_id=media_id
        )
        logger.info(
            f"本地上传转录完成，已入 LLM 队列: {task_id}, file={original_name}, chars={len(transcript)}"
        )
        return {"status": "success", "message": "本地转录成功"}
    except Exception as exc:
        logger.exception(f"本地上传转录失败: {task_id}, error={exc}")
        cache_manager.update_task_status(
            task_id, TaskStatus.FAILED, error_message=f"本地转录失败: {exc}"
        )
        return {"status": "failed", "message": str(exc)}
    finally:
        # 清理全部临时文件：原上传文件 + 抽出的音频，不留任何重复存储
        for _p in (file_path, audio_path):
            if _p and os.path.exists(_p):
                try:
                    os.remove(_p)
                except OSError:
                    pass


def _make_download_progress_callback(task_id: str):
    started_at = time.time()
    state = {"last_percent": -1, "last_time": 0.0}

    def _callback(downloaded: int, total: int | None):
        if not total or total <= 0:
            return
        fraction = max(0.0, min(1.0, downloaded / total))
        percent = int(fraction * 100)
        now = time.time()
        if percent < 100 and percent - state["last_percent"] < 5 and now - state["last_time"] < 5:
            return
        state["last_percent"] = percent
        state["last_time"] = now
        eta = estimate_eta_seconds(
            completed=downloaded,
            total=total,
            elapsed_seconds=now - started_at,
        )
        _safe_update_progress(
            task_id,
            stage="downloading",
            stage_label="正在下载音视频",
            fraction=fraction,
            basis="download_bytes",
            confidence="high",
            evidence={
                "completed": downloaded,
                "total": total,
                "unit": "bytes",
            },
            eta_seconds=eta,
        )

    return _callback


def _download_file_with_progress(downloader, url: str, filename: str, task_id: str):
    callback = _make_download_progress_callback(task_id)
    try:
        params = inspect.signature(downloader.download_file).parameters
    except (TypeError, ValueError):
        params = {}
    if "progress_callback" in params:
        return downloader.download_file(url, filename, progress_callback=callback)
    return downloader.download_file(url, filename)


def _make_asr_progress_callback(task_id: str, source: str):
    started_at = time.time()

    def _callback(payload: dict):
        progress_value = payload.get("progress")
        fraction = None
        if progress_value is not None:
            fraction = max(0.0, min(1.0, float(progress_value) / 100))

        completed = payload.get("completed")
        total = payload.get("total")
        eta = estimate_eta_seconds(
            completed=completed,
            total=total,
            elapsed_seconds=time.time() - started_at,
        )
        if source == "funasr":
            phase = payload.get("phase")
            basis = (
                "funasr_upload_progress"
                if phase == "upload"
                else "funasr_server_progress"
            )
            confidence = "high"
            unit = "chunks" if phase == "upload" else "percent"
        else:
            basis = "capswriter_audio_sent"
            confidence = "medium"
            unit = "seconds"

        evidence = {
            "source": source,
            "phase": payload.get("phase"),
            "unit": unit,
        }
        if completed is not None:
            evidence["completed"] = completed
        if total is not None:
            evidence["total"] = total
        if progress_value is not None:
            evidence["progress"] = progress_value

        _safe_update_progress(
            task_id,
            stage="transcribing",
            stage_label="正在转录音视频",
            fraction=fraction,
            basis=basis,
            confidence=confidence,
            evidence=evidence,
            eta_seconds=eta,
            message=payload.get("message"),
        )

    return _callback


class MetadataOverride(BaseModel):
    """元数据覆盖模型"""
    title: Optional[str] = Field(None, description="视频标题", max_length=200)
    description: Optional[str] = Field(None, description="视频描述", max_length=2000)
    author: Optional[str] = Field(None, description="视频作者", max_length=200)


class NotificationConfig(BaseModel):
    """通知配置（可选，用于 per-request 指定渠道）"""
    channel: Optional[str] = Field(None, description="通知渠道: wechat / feishu / None(全部)")
    webhook: Optional[str] = Field(None, description="自定义 webhook URL")

    @field_validator("webhook")
    @classmethod
    def validate_webhook_url(cls, v):
        if v is None or v.strip() == "":
            return v
        from ...utils.url_validator import validate_url_safe, URLValidationError
        try:
            validate_url_safe(v)
        except URLValidationError as e:
            raise ValueError(f"webhook URL is not allowed: {e}")
        return v


class TranscribeRequest(BaseModel):
    """转录请求数据模型"""

    url: str = Field(..., description="视频URL（平台链接，用于 view_token 和缓存）")
    use_speaker_recognition: bool = Field(False, description="是否使用说话人识别功能")
    wechat_webhook: Optional[str] = Field(
        None, description="企业微信webhook地址"
    )
    feishu_webhook: Optional[str] = Field(
        None, description="飞书webhook地址"
    )
    download_url: Optional[str] = Field(
        None, description="实际下载地址（可选，如果提供则优先使用）"
    )
    metadata_override: Optional[MetadataOverride] = Field(
        None, description="元数据覆盖（用于补充或覆盖解析的元数据）"
    )
    notification_config: Optional[NotificationConfig] = Field(
        None, description="通知配置（可选，指定渠道和自定义 webhook）"
    )
    include_comments: bool = Field(
        False, description="是否获取高赞评论并生成评论洞察"
    )
    comment_limit: int = Field(
        100, ge=1, le=200, description="热评拉取上限，仅在 include_comments=true 时生效"
    )

    @field_validator("wechat_webhook", "feishu_webhook")
    @classmethod
    def validate_webhook_url(cls, v):
        """验证 webhook URL 安全性（防止 SSRF）"""
        if v is None or v.strip() == "":
            return v
        from ...utils.url_validator import validate_url_safe, URLValidationError
        try:
            validate_url_safe(v)
        except URLValidationError as e:
            raise ValueError(f"webhook URL is not allowed: {e}")
        return v


class RecalibrateRequest(BaseModel):
    """重新校对请求数据模型"""

    view_token: str = Field(..., description="查看页面的 view_token")
    wechat_webhook: Optional[str] = Field(
        None, description="企业微信webhook地址，用于发送通知"
    )

    @field_validator("wechat_webhook")
    @classmethod
    def validate_webhook_url(cls, v):
        """验证 webhook URL 安全性（防止 SSRF）"""
        if v is None or v.strip() == "":
            return v
        from ...utils.url_validator import validate_url_safe, URLValidationError
        try:
            validate_url_safe(v)
        except URLValidationError as e:
            raise ValueError(f"webhook URL is not allowed: {e}")
        return v


class TranscribeResponse(BaseModel):
    """转录响应数据模型"""

    code: int = Field(200, description="状态码")
    message: str = Field("success", description="状态信息")
    data: Optional[Dict[str, Any]] = Field(None, description="响应数据")


def extract_filename_from_url(url: str) -> str:
    """
    从URL中提取文件名

    参数:
        url: URL地址

    返回:
        str: 提取的文件名，如果无法提取则返回空字符串
    """
    try:
        from urllib.parse import urlparse, unquote
        parsed_url = urlparse(url)
        path = unquote(parsed_url.path)
        filename = os.path.basename(path)
        # 移除扩展名
        if filename:
            return os.path.splitext(filename)[0]
        return ""
    except Exception:
        return ""


def generate_media_id_from_url(url: str) -> str:
    """
    从URL生成唯一的media_id

    参数:
        url: URL地址

    返回:
        str: 16位哈希字符串
    """
    import hashlib
    return hashlib.md5(url.encode()).hexdigest()[:16]


def merge_metadata(parsed_metadata: Optional[dict], metadata_override: Optional[dict], url: str) -> dict:
    """
    合并解析的元数据和用户提供的元数据覆盖

    参数:
        parsed_metadata: 从url解析的元数据（可能为None）
        metadata_override: 用户提供的元数据覆盖（可能为None）
        url: 平台链接（用于生成默认值）

    返回:
        dict: 合并后的完整元数据
    """
    # 步骤1：元数据合并
    if parsed_metadata is not None:
        # 解析成功：metadata_override 作为补充
        # 注意：过滤掉 metadata_override 中的 None 值和空字符串，避免覆盖解析出的有效值
        filtered_override = {
            k: v
            for k, v in (metadata_override or {}).items()
            if v is not None and (not isinstance(v, str) or v.strip())
        }
        final_metadata = {**parsed_metadata, **filtered_override}
        logger.info("元数据解析成功，使用 metadata_override 作为补充")

        # 字段名标准化：将 video_title 映射为 title（如果存在）
        if 'video_title' in final_metadata and 'title' not in final_metadata:
            final_metadata['title'] = final_metadata['video_title']
            logger.debug("已将 video_title 映射为 title")
    else:
        # 解析失败或未提供：metadata_override 作为覆盖
        final_metadata = metadata_override or {}
        logger.info("元数据解析失败或未提供，使用 metadata_override 作为覆盖")

    # 步骤2：填充默认值（如果仍然缺失或为空）
    # 注意：不能用 setdefault，因为它不会覆盖空字符串或 None
    if not (final_metadata.get('title') or '').strip():
        final_metadata['title'] = extract_filename_from_url(url) or "Untitled"
    final_metadata.setdefault('description', "")
    if not (final_metadata.get('author') or '').strip():
        final_metadata['author'] = "Unknown"
    final_metadata.setdefault('platform', 'generic')
    if not final_metadata.get('video_id'):
        final_metadata['video_id'] = generate_media_id_from_url(url)

    logger.info(
        f"最终元数据: platform={final_metadata['platform']}, "
        f"video_id={final_metadata['video_id']}, "
        f"title={final_metadata['title'][:50]}, "
        f"author={final_metadata['author']}"
    )

    return final_metadata


def _should_use_cached_llm_results(cache_data: dict, include_comments: bool) -> bool:
    """Return whether a cache hit fully satisfies the current request."""
    has_llm_results = (
        cache_data is not None
        and "llm_calibrated" in cache_data
        and "llm_summary" in cache_data
    )
    if not has_llm_results:
        return False
    if include_comments and not cache_data.get("comment_insight"):
        return False
    return True


async def verify_token(authorization: str = Header(None), request: Request = None):
    """
    验证API令牌（支持多用户）
    """
    if not authorization:
        logger.warning("请求未提供Authorization头")
        raise HTTPException(status_code=401, detail="未提供授权令牌")

    token_parts = authorization.split()
    if len(token_parts) != 2 or token_parts[0].lower() != "bearer":
        logger.warning("授权令牌格式错误")
        raise HTTPException(status_code=401, detail="授权令牌格式错误")

    token = token_parts[1]
    user_info = user_manager.validate_token(token)
    if not user_info:
        logger.warning(f"授权令牌无效: {token[:8]}...")
        raise HTTPException(status_code=401, detail="授权令牌无效")

    logger.debug(f"用户认证成功: {user_info.get('user_id')}")
    if request:
        request.state.user_info = user_info
    return user_info


async def process_task_queue():
    """处理任务队列的后台任务"""
    logger.info("启动任务队列处理器")

    while True:
        try:
            task = await task_queue.get()
            task_id = task["id"]
            url = task["url"]
            use_speaker_recognition = task.get("use_speaker_recognition", False)
            wechat_webhook = task.get("wechat_webhook")
            notification_channel = task.get("notification_channel")
            notification_webhooks = task.get("notification_webhooks", {})
            download_url = task.get("download_url")
            metadata_override = task.get("metadata_override")
            include_comments = task.get("include_comments", False)
            comment_limit = task.get("comment_limit", 100)

            try:
                cache_manager.update_task_status(task_id, TaskStatus.PROCESSING, download_url=download_url)
                _safe_update_progress(
                    task_id,
                    stage="url_parsing",
                    stage_label="任务已开始，正在解析链接",
                    basis="task_started",
                    confidence="high",
                )

                future = executor.submit(
                    process_transcription,
                    task_id,
                    url,
                    use_speaker_recognition,
                    wechat_webhook,
                    download_url,
                    metadata_override,
                    notification_channel=notification_channel,
                    notification_webhooks=notification_webhooks,
                    include_comments=include_comments,
                    comment_limit=comment_limit,
                )

                def task_completed(future_result):
                    # 各阶段（process_transcription / LLM）会在内部把状态写入 DB；
                    # 但「下载失败」等早退路径只是正常 return 一个 {"status":"failed"} 字典、
                    # 并不抛异常，若不在此兜底写回终态，任务会永远停留在 processing。
                    try:
                        result = future_result.result()
                        if isinstance(result, dict) and result.get("status") == "failed":
                            # 早退失败路径：写回终态，避免页面一直显示"处理中"
                            error_message = result.get("message", "任务失败")
                            logger.warning(f"任务失败: {task_id}, 原因: {error_message}")
                            cache_manager.update_task_status(
                                task_id, TaskStatus.FAILED,
                                error_message=error_message,
                            )
                        else:
                            logger.info(f"任务完成: {task_id}")
                    except Exception as exc:
                        logger.exception(
                            f"任务处理失败: {task_id}, URL: {url}, 错误: {exc}"
                        )
                        cache_manager.update_task_status(
                            task_id, TaskStatus.FAILED,
                            error_message=f"转录任务失败: {exc}",
                        )
                        display_url = url
                        get_notification_router().notify_task_status(
                            url=display_url, status="转录失败", error=str(exc),
                            channel_name=notification_channel, webhooks=notification_webhooks,
                        )

                future.add_done_callback(task_completed)
                logger.info(f"任务已提交到线程池: {task_id}, URL: {url}")
            except Exception as exc:
                logger.exception(
                    f"提交任务到线程池失败: {task_id}, URL: {url}, 错误: {exc}"
                )
                cache_manager.update_task_status(
                    task_id, TaskStatus.FAILED,
                    error_message=f"提交任务失败: {exc}",
                )
            finally:
                task_queue.task_done()
        except Exception as exc:
            logger.exception(f"任务队列处理器异常: {exc}")
            await asyncio.sleep(1)


def process_transcription(
    task_id, url, use_speaker_recognition=False, wechat_webhook=None,
    download_url=None, metadata_override=None, notification_channel=None,
    notification_webhooks=None, include_comments=False, comment_limit=100,
):
    """
    处理视频转录

    参数:
        task_id: 任务ID
        url: 平台链接（用于元数据解析、view_token 生成、缓存查询）
        use_speaker_recognition: 是否使用说话人识别
        wechat_webhook: 企业微信webhook（向后兼容）
        download_url: 实际下载地址（可选，如果提供则优先使用）
        metadata_override: 元数据覆盖（dict）
        notification_channel: 指定通知渠道（wechat/feishu/None=全部）
        notification_webhooks: per-channel webhook dict {"wechat": "...", "feishu": "..."}
        include_comments: 是否在 LLM 阶段生成高赞评论洞察
        comment_limit: 热评拉取上限
    """
    if notification_webhooks is None:
        notification_webhooks = {}
    # 性能追踪器：记录各阶段耗时
    tracker = PerfTracker(task_id=task_id)

    try:
        # 规范化 download_url：将空字符串转换为 None
        if download_url is not None and isinstance(download_url, str) and not download_url.strip():
            download_url = None

        # SSRF 防护：验证 download_url 安全性
        if download_url:
            from ...utils.url_validator import validate_url_safe, URLValidationError
            try:
                validate_url_safe(download_url)
            except URLValidationError as e:
                logger.warning(f"download_url SSRF check failed: {download_url}, reason: {e}")
                raise ValueError(f"download_url is not allowed: {e}")

        logger.info(f"开始处理转录任务: {task_id}, URL: {url}, download_url: {download_url}")

        # url 本身就是平台链接，直接使用
        display_url = url
        logger.info(f"通知将使用URL: {display_url}")

        _router = get_notification_router()

        class _TaskNotifier:
            """Bound notifier for this task — wraps router with channel/webhook context."""
            def notify_task_status(self, url, status, error=None, title=None, author=None, transcript=None):
                return _router.notify_task_status(
                    url=url, status=status, error=error, title=title,
                    author=author, transcript=transcript,
                    channel_name=notification_channel, webhooks=notification_webhooks,
                )
            def send_text(self, content, skip_risk_control=False):
                return _router.send_text(
                    content, channel_name=notification_channel, webhooks=notification_webhooks,
                )

        task_notifier = _TaskNotifier()
        engine_info = (
            "说话人识别(FunASR)" if use_speaker_recognition else "普通转录(CapsWriter)"
        )
        task_notifier.notify_task_status(display_url, f"开始处理 - {engine_info}")

        # ==================== 阶段1: URL 解析（提取 platform 和 video_id）====================
        from ...utils.url_parser import URLParser

        # url 本身就是平台链接，直接解析
        check_url = url
        logger.info(f"[URL解析] 开始解析 URL: {check_url[:100]}")
        _safe_update_progress(
            task_id,
            stage="url_parsing",
            stage_label="正在解析链接",
            basis="stage_transition",
            confidence="medium",
        )

        with tracker.track("url_parse"):
            try:
                # 使用 URLParser 统一解析（支持短链接自动解析）
                url_parser = URLParser()
                parsed_url = url_parser.parse(check_url)

                platform = parsed_url.platform
                video_id = parsed_url.video_id

                logger.info(
                    f"[URL解析] 解析成功: platform={platform}, video_id={video_id}, "
                    f"is_short_url={parsed_url.is_short_url}"
                )

            except Exception as e:
                # URL 解析失败，回退到 generic 模式
                logger.warning(f"[URL解析] 解析失败: {e}，使用 generic 模式")
                platform = 'generic'
                video_id = generate_media_id_from_url(url)
                logger.info(f"[URL解析] 回退到通用标识: platform={platform}, video_id={video_id}")

        # ==================== 阶段2: 缓存检测（在创建下载器之前）====================
        cache_data = None
        is_generic_downloader = platform == 'generic'
        _safe_update_progress(
            task_id,
            stage="cache_check",
            stage_label="正在检查缓存",
            basis="url_parse_result",
            confidence="high",
            evidence={"platform": platform, "media_id": video_id},
        )

        with tracker.track("cache_check"):
            if video_id and platform and not is_generic_downloader:
                logger.info(
                    f"[缓存检测] 检查缓存: platform={platform}, video_id={video_id}, "
                    f"use_speaker_recognition={use_speaker_recognition}"
                )
                cache_data = cache_manager.get_cache(
                    platform=platform,
                    media_id=video_id,
                    use_speaker_recognition=use_speaker_recognition,
                )
            else:
                logger.info(
                    f"[缓存检测] 跳过缓存检查 (platform={platform}, is_generic={is_generic_downloader})"
                )

        if cache_data:
            logger.info("[缓存检测] ✅ 缓存命中，直接返回")
            logger.info("找到已存在的缓存记录，跳过下载和转录步骤")
            video_title = cache_data.get("title", "已缓存视频")
            author = cache_data.get("author", "")
            description = cache_data.get("description", "")
            has_speaker_recognition = cache_data.get("use_speaker_recognition", False)
            # 缓存命中时，is_from_generic 必然是 False（第 365 行条件保证了 generic 不会被缓存）
            is_from_generic = False

            transcript = ""
            transcription_data = None
            if cache_data["transcript_type"] == "funasr":
                transcription_data = cache_data["transcript_data"]
                funasr_client = FunASRSpeakerClient()
                transcript = funasr_client.format_transcript_with_speakers(
                    transcription_data
                )
                logger.info("使用 FunASR 缓存，包含说话人信息")
            else:
                transcript = cache_data["transcript_data"]
                logger.info("使用 CapsWriter 缓存文本")

            has_llm_calibrated = "llm_calibrated" in cache_data
            has_llm_summary = "llm_summary" in cache_data

            if _should_use_cached_llm_results(cache_data, include_comments):
                logger.info("缓存中已有 LLM 结果，直接使用")
                cache_type = "含说话人识别" if has_speaker_recognition else "普通转录"
                engine_info = "FunASR" if has_speaker_recognition else "CapsWriter"
                task_notifier.notify_task_status(
                    display_url,
                    f"使用已有缓存({cache_type}-{engine_info}，含LLM结果)",
                    title=video_title,
                    author=author,
                    transcript="使用缓存的校对和总结文本...",
                )

                # 直接发送缓存的 LLM 结果（仅发送总结文本）
                logger.info("缓存模式 - 发送总结文本")

                # 获取查看链接
                task_info = cache_manager.get_task_by_id(task_id)
                view_url = ""
                if task_info and task_info.get("view_token"):
                    base_url = get_base_url()
                    view_url = f"{base_url}/view/{task_info['view_token']}"

                # 计算统计信息
                original_length = len(transcript)
                calibrated_length = len(cache_data.get("llm_calibrated", ""))
                summary_text = cache_data["llm_summary"]
                calibrated_text = cache_data.get("llm_calibrated", "")

                # 判断是否跳过了总结（总结文本和校对文本相同）
                skip_summary = summary_text == calibrated_text

                # 构建完整的消息格式
                speaker_info = "（含说话人识别）" if has_speaker_recognition else ""
                if skip_summary:
                    # 短文本，未生成总结
                    full_message = f"""## 总结和校对
🌐 网页查看：{view_url}
📄 直接获取：{view_url}?raw=calibrated

## 转录统计
原始 {original_length:,} 字 | 校对 {calibrated_length:,} 字 | 总结 未生成

## 校对文本{speaker_info}
{summary_text}"""
                    logger.info("缓存模式 - 发送校对文本（未总结）")
                else:
                    # 长文本，有总结
                    summary_length = len(summary_text)
                    full_message = f"""## 总结和校对
🌐 网页查看：{view_url}
📄 直接获取：{view_url}?raw=calibrated

## 转录统计
原始 {original_length:,} 字 | 校对 {calibrated_length:,} 字 | 总结 {summary_length:,} 字

## 总结{speaker_info}
{summary_text}"""
                    logger.info("缓存模式 - 发送总结文本")

                # 发送（跳过自动添加的内容类型标题）
                _router.send_long_text(
                    title=video_title,
                    url=display_url,
                    text=full_message,
                    is_summary=not skip_summary,
                    has_speaker_recognition=has_speaker_recognition,
                    channel_name=notification_channel,
                    webhooks=notification_webhooks,
                    skip_content_type_header=True,
                )

                # 确保总结文本完全加入队列后再发送完成通知
                logger.info("[缓存模式] 总结文本发送完成，延迟100ms后发送完成通知")
                time.sleep(0.1)

                # 发送任务完成通知，包含查看链接
                task_info = cache_manager.get_task_by_id(task_id)
                if task_info and task_info.get("view_token"):
                    base_url = get_base_url()
                    view_url = f"{base_url}/view/{task_info['view_token']}"

                    from ...utils.notifications.channel import _apply_risk_control_safe
                    clean = _clean_url(display_url)
                    sanitized_title = _apply_risk_control_safe(video_title, text_type="title")

                    completion_message = f"# {sanitized_title}\n\n{clean}\n\n🔗 总结和校对：\n{view_url}\n\n✅ **【任务完成】**"
                    logger.info(f"[缓存模式] 准备发送任务完成通知: {sanitized_title}")
                    task_notifier.send_text(completion_message, skip_risk_control=True)
                    logger.info(f"[缓存模式] 任务完成通知已加入限流队列: {task_id}")

                logger.info(f"已发送缓存的 LLM 结果: {video_title}")

                # 缓存全命中（含 LLM 结果）：无后续 LLM 工作，直接置终态 success
                cache_manager.update_task_status(
                    task_id,
                    TaskStatus.SUCCESS,
                    platform=cache_data.get("platform"),
                    media_id=cache_data.get("media_id"),
                    title=video_title,
                    author=author,
                    cache_id=cache_data.get("cache_id"),
                    download_url=download_url,
                )

                # 缓存完全命中（含 LLM 结果），记录计数并输出性能摘要
                tracker.count("cache_hit")
                tracker.log_summary()

                return {
                    "status": "success",
                    "message": "使用已有缓存成功",
                    "data": {
                        "video_title": video_title,
                        "author": author,
                        "transcript": transcript,
                        "cached": True,
                        "speaker_recognition": has_speaker_recognition,
                    },
                }

            task_notifier.notify_task_status(
                display_url,
                "使用已有缓存",
                title=video_title,
                author=author,
                transcript="正在处理已存在的转录文本...",
            )

            # 缓存部分命中（有转录但无 LLM 结果），记录计数
            tracker.count("cache_hit_partial")
            _safe_update_progress(
                task_id,
                stage="calibrating",
                stage_label="已命中转录缓存，正在校对和总结",
                basis="cache_lookup",
                confidence="high",
                evidence={"transcript_chars": len(transcript)},
            )

            try:
                llm_task_queue.put(
                    {
                        "task_id": task_id,
                        "url": url,
                        "display_url": display_url,
                        "platform": cache_data.get("platform"),
                        "media_id": cache_data.get("media_id"),
                        "video_title": video_title,
                        "author": author,
                        "description": description,
                        "transcript": transcript,
                        "use_speaker_recognition": has_speaker_recognition,
                        "transcription_data": transcription_data
                        if has_speaker_recognition
                        else None,
                        "is_generic": is_generic_downloader or is_from_generic,
                        "wechat_webhook": wechat_webhook,
                        "notification_channel": notification_channel,
                        "notification_webhooks": notification_webhooks,
                        "include_comments": include_comments,
                        "comment_limit": comment_limit,
                        "comment_only": has_llm_calibrated and has_llm_summary and include_comments,
                        "cached_calibrated": cache_data.get("llm_calibrated"),
                        "cached_summary": cache_data.get("llm_summary"),
                        "perf_tracker": tracker,
                    }
                )
                logger.info(
                    f"将LLM任务加入队列: {task_id}, 标题: {video_title}, 说话人识别: {has_speaker_recognition}"
                )
                # 转录已就绪、LLM 校对/总结进行中 → calibrating（终态由 LLM 阶段写）
                cache_manager.update_task_status(
                    task_id,
                    TaskStatus.CALIBRATING,
                    platform=cache_data.get("platform"),
                    media_id=cache_data.get("media_id"),
                    title=video_title,
                    author=author,
                    download_url=download_url,
                )
            except Exception as exc:
                logger.exception(f"将LLM任务加入队列失败（缓存）: {exc}")
                task_notifier.send_text(f"【LLM任务加入队列失败】{exc}")
                cache_manager.update_task_status(
                    task_id, TaskStatus.FAILED,
                    error_message=f"LLM任务加入队列失败: {exc}",
                )

            return {
                "status": "success",
                "message": "使用已有缓存成功",
                "data": {
                    "video_title": video_title,
                    "author": author,
                    "transcript": transcript,
                    "cached": True,
                    "speaker_recognition": has_speaker_recognition,
                },
            }
        else:
            logger.info("[缓存检测] ❌ 缓存未命中，准备下载和转录")

            # ==================== 阶段3: 元数据获取（创建下载器实例）====================
            parsed_metadata = None
            metadata_downloader = None
            metadata_obj = None
            download_info_obj = None
            parse_url = url
            _safe_update_progress(
                task_id,
                stage="metadata",
                stage_label="正在获取视频信息",
                basis="cache_lookup",
                confidence="medium",
            )

            with tracker.track("metadata"):
                try:
                    logger.info(f"[元数据获取] 创建下载器实例: {parse_url}")
                    metadata_downloader = create_downloader(parse_url)
                    logger.info(
                        f"[元数据获取] 下载器类型: {metadata_downloader.__class__.__name__}"
                    )

                    metadata_obj = metadata_downloader.get_metadata(parse_url)
                    parsed_metadata = {
                        "video_id": metadata_obj.video_id,
                        "video_title": metadata_obj.title,
                        "title": metadata_obj.title,
                        "author": metadata_obj.author,
                        "description": metadata_obj.description,
                        "platform": metadata_obj.platform,
                    }
                    logger.info(
                        f"[元数据获取] 成功: platform={metadata_obj.platform}, "
                        f"video_id={metadata_obj.video_id}, "
                        f"title={metadata_obj.title[:50]}"
                    )
                except Exception as e:
                    logger.warning(f"[元数据获取] 失败: {e}")
                    parsed_metadata = None
                    metadata_obj = None

            # 合并元数据（metadata_override 作为补充或覆盖）
            if parsed_metadata:
                final_metadata = merge_metadata(parsed_metadata, metadata_override, url)
                video_title = final_metadata.get('title') or final_metadata.get('video_title', '')
                author = final_metadata.get('author', '')
                description = final_metadata.get('description', '')
                # 更新 platform 和 video_id（用完整数据覆盖 URLParser 提取的值）
                platform = final_metadata.get('platform', platform)
                video_id = final_metadata.get('video_id', video_id)
                logger.info(f"[元数据合并] 元数据解析成功，metadata_override 作为补充")
            else:
                # 元数据获取失败，使用 metadata_override 或默认值
                final_metadata = metadata_override or {}
                video_title = final_metadata.get('title') or extract_filename_from_url(url) or "Untitled"
                author = final_metadata.get('author', 'Unknown')
                description = final_metadata.get('description', '')
                logger.info(f"[元数据合并] 元数据解析失败，使用 metadata_override 或默认值")

            media_id = video_id
            is_from_generic = (platform == 'generic')
            logger.info(
                f"[元数据合并] 最终元数据: platform={platform}, video_id={video_id}, "
                f"title={video_title[:50]}, author={author}"
            )

            # 判断是否提供了 download_url
            # 如果提供，说明需要从 download_url 下载，而 url 仅用于元数据解析
            has_separate_download_url = (
                download_url is not None and
                download_url.strip() != ""
            )

            # 下载器准备
            from ...downloaders.generic import GenericDownloader
            download_downloader = None
            if has_separate_download_url:
                download_downloader = GenericDownloader()
            elif metadata_downloader:
                download_downloader = metadata_downloader
            else:
                download_downloader = create_downloader(url)

            # 获取下载信息（仅在需要使用解析URL下载时）
            if not has_separate_download_url and download_downloader:
                try:
                    download_info_obj = download_downloader.get_download_info(parse_url)
                    logger.info(
                        f"[下载信息] 获取成功: platform={platform}, video_id={video_id}"
                    )
                except Exception as e:
                    logger.warning(f"[下载信息] 获取失败: {e}")
                    download_info_obj = None

            # ========== YouTube API Server 快速路径 ==========
            # 如果提供了 download_url，则跳过 API Server，强制使用 download_url 下载
            if has_separate_download_url:
                logger.info("[youtube-api] download_url provided; skip API Server fast path")
            # 如果是 YouTube URL 且启用了 API Server，使用一次请求获取所有资源
            elif (
                metadata_downloader
                and metadata_downloader.__class__.__name__ == "YoutubeDownloader"
                and hasattr(metadata_downloader, "use_api_server")
                and metadata_downloader.use_api_server
            ):
                logger.info(f"[youtube-api] Using API Server for: {url}")
                try:
                    from ...downloaders.youtube_api_errors import YouTubeApiError

                    # 一次 API 请求获取所有信息（含下载）
                    _safe_update_progress(
                        task_id,
                        stage="downloading",
                        stage_label="正在通过 YouTube API Server 获取资源",
                        basis="stage_transition",
                        confidence="low",
                    )
                    with tracker.track("download"):
                        api_result = metadata_downloader.fetch_for_transcription(
                            url, use_speaker_recognition
                        )

                    # 将 API 返回的数据作为 parsed_metadata，与 metadata_override 合并
                    api_metadata = {
                        'video_id': api_result["video_id"],
                        'video_title': api_result["video_title"],
                        'title': api_result["video_title"],  # 字段名标准化
                        'author': api_result["author"],
                        'description': api_result["description"],
                        'platform': api_result["platform"],
                    }
                    youtube_merged = merge_metadata(api_metadata, metadata_override, url)

                    video_title = youtube_merged.get('title', '')
                    author = youtube_merged.get('author', '')
                    description = youtube_merged.get('description', '')
                    platform = youtube_merged.get('platform', 'youtube')
                    media_id = youtube_merged.get('video_id', '')

                    if not api_result["need_transcription"]:
                        # 有平台字幕，直接使用
                        transcript = api_result["transcript"]
                        logger.info(
                            f"[youtube-api] Using platform transcript, length={len(transcript)}"
                        )

                        task_notifier.notify_task_status(
                            display_url,
                            "平台字幕获取成功 - 使用 YouTube API Server",
                            title=video_title,
                            author=author,
                        )
                        _safe_update_progress(
                            task_id,
                            stage="calibrating",
                            stage_label="已获取平台字幕，正在校对和总结",
                            basis="platform_subtitle",
                            confidence="high",
                            evidence={"transcript_chars": len(transcript)},
                        )

                        # 保存到缓存
                        cache_result = cache_manager.save_cache(
                            platform=platform,
                            url=url,
                            media_id=media_id,
                            use_speaker_recognition=False,
                            transcript_data=transcript,
                            transcript_type="capswriter",
                            title=video_title,
                            author=author,
                            description=description,
                        )
                        if not cache_result:
                            logger.error(
                                "[youtube-api] Failed to save transcript cache"
                            )

                        # 加入 LLM 处理队列
                        try:
                            llm_task_queue.put(
                                {
                                    "task_id": task_id,
                                    "url": url,
                                    "display_url": display_url,
                                    "platform": platform,
                                    "media_id": media_id,
                                    "video_title": video_title,
                                    "author": author,
                                    "description": description,
                                    "transcript": transcript,
                                    "use_speaker_recognition": False,
                                    "is_generic": False,
                                    "wechat_webhook": wechat_webhook,
                                    "notification_channel": notification_channel,
                                    "notification_webhooks": notification_webhooks,
                                    "include_comments": include_comments,
                                    "comment_limit": comment_limit,
                                    "perf_tracker": tracker,
                                }
                            )
                            logger.info(f"[youtube-api] LLM task queued: {task_id}")
                        except Exception as exc:
                            logger.exception(
                                f"[youtube-api] Failed to queue LLM task: {exc}"
                            )
                            task_notifier.send_text(f"【LLM任务加入队列失败】{exc}")
                            cache_manager.update_task_status(
                                task_id, TaskStatus.FAILED,
                                error_message=f"LLM任务加入队列失败: {exc}",
                            )
                            return {"status": "failed", "message": f"LLM任务加入队列失败: {exc}"}

                        # 转录就绪、LLM 校对/总结进行中 → calibrating（终态由 LLM 阶段写）
                        _safe_update_progress(
                            task_id,
                            stage="calibrating",
                            stage_label="转录已完成，正在校对和总结",
                            basis="llm_started",
                            confidence="medium",
                            evidence={"transcript_chars": len(transcript)},
                        )
                        cache_manager.update_task_status(
                            task_id,
                            TaskStatus.CALIBRATING,
                            platform=platform,
                            media_id=media_id,
                            title=video_title,
                            author=author,
                            download_url=download_url,
                        )
                        return {
                            "status": "success",
                            "message": "使用 YouTube API Server 获取字幕成功",
                            "data": {
                                "video_title": video_title,
                                "author": author,
                                "transcript": transcript,
                            },
                        }
                    else:
                        # 需要转录，使用已下载的音频
                        local_file = api_result["audio_path"]
                        logger.info(
                            f"[youtube-api] Audio downloaded, need transcription: {local_file}"
                        )

                        task_notifier.notify_task_status(
                            display_url,
                            f"正在转录音视频 - {engine_info}",
                            title=video_title,
                            author=author,
                        )
                        _safe_update_progress(
                            task_id,
                            stage="transcribing",
                            stage_label="正在转录音视频",
                            basis="stage_transition",
                            confidence="low",
                        )

                        # 根据是否需要说话人识别选择转录器
                        with tracker.track("transcription"):
                            if use_speaker_recognition:
                                logger.info("[youtube-api] Using FunASR for transcription")
                                funasr_client = FunASRSpeakerClient(
                                    progress_callback=_make_asr_progress_callback(task_id, "funasr")
                                )
                                funasr_result = funasr_client.transcribe_sync(local_file)
                                transcript = funasr_result["formatted_text"]
                                transcription_data = funasr_result["transcription_result"]

                                cache_result = cache_manager.save_cache(
                                    platform=platform,
                                    url=url,
                                    media_id=media_id,
                                    use_speaker_recognition=True,
                                    transcript_data=transcription_data,
                                    transcript_type="funasr",
                                    title=video_title,
                                    author=author,
                                    description=description,
                                )
                                transcription_result = {
                                    "transcript": transcript,
                                    "speaker_recognition": True,
                                    "transcription_data": transcription_data,
                                }
                            else:
                                logger.info(
                                    "[youtube-api] Using CapsWriter for transcription"
                                )
                                transcriber = Transcriber(
                                    progress_callback=_make_asr_progress_callback(task_id, "capswriter")
                                )
                                temp_output_base = datetime.datetime.now().strftime(
                                    "%y%m%d-%H%M%S"
                                )
                                transcription_result = transcriber.transcribe(
                                    local_file, temp_output_base
                                )
                                transcript = transcription_result.get("transcript", "")

                                cache_result = cache_manager.save_cache(
                                    platform=platform,
                                    url=url,
                                    media_id=media_id,
                                    use_speaker_recognition=False,
                                    transcript_data=transcript,
                                    transcript_type="capswriter",
                                    title=video_title,
                                    author=author,
                                    description=description,
                                )

                        if not cache_result:
                            logger.error(
                                "[youtube-api] Failed to save transcription cache"
                            )

                        task_notifier.notify_task_status(
                            display_url,
                            f"转录完成 - {engine_info}",
                            title=video_title,
                            author=author,
                            transcript=transcript,
                        )

                        # 加入 LLM 处理队列
                        try:
                            llm_task_queue.put(
                                {
                                    "task_id": task_id,
                                    "url": url,
                                    "display_url": display_url,
                                    "platform": platform,
                                    "media_id": media_id,
                                    "video_title": video_title,
                                    "author": author,
                                    "description": description,
                                    "transcript": transcript,
                                    "use_speaker_recognition": use_speaker_recognition,
                                    "transcription_data": transcription_result.get(
                                        "transcription_data"
                                    )
                                    if use_speaker_recognition
                                    else None,
                                    "is_generic": False,
                                    "wechat_webhook": wechat_webhook,
                                    "notification_channel": notification_channel,
                                    "notification_webhooks": notification_webhooks,
                                    "include_comments": include_comments,
                                    "comment_limit": comment_limit,
                                    "perf_tracker": tracker,
                                }
                            )
                            logger.info(f"[youtube-api] LLM task queued: {task_id}")
                        except Exception as exc:
                            logger.exception(
                                f"[youtube-api] Failed to queue LLM task: {exc}"
                            )
                            task_notifier.send_text(f"【LLM任务加入队列失败】{exc}")
                            cache_manager.update_task_status(
                                task_id, TaskStatus.FAILED,
                                error_message=f"LLM任务加入队列失败: {exc}",
                            )
                            return {"status": "failed", "message": f"LLM任务加入队列失败: {exc}"}

                        # 转录就绪、LLM 校对/总结进行中 → calibrating（终态由 LLM 阶段写）
                        _safe_update_progress(
                            task_id,
                            stage="calibrating",
                            stage_label="转录已完成，正在校对和总结",
                            basis="llm_started",
                            confidence="medium",
                            evidence={"transcript_chars": len(transcript)},
                        )
                        cache_manager.update_task_status(
                            task_id,
                            TaskStatus.CALIBRATING,
                            platform=platform,
                            media_id=media_id,
                            title=video_title,
                            author=author,
                            download_url=download_url,
                        )
                        return {
                            "status": "success",
                            "message": "使用 YouTube API Server 下载并转录成功",
                            "data": {
                                "video_title": video_title,
                                "author": author,
                                "transcript": transcript,
                                "speaker_recognition": use_speaker_recognition,
                            },
                        }

                except YouTubeApiError as api_error:
                    # API Server 失败，不降级，直接返回错误
                    error_msg = f"YouTube API Server error: [{api_error.code}] {api_error.message}"
                    logger.error(f"[youtube-api] {error_msg}")
                    task_notifier.notify_task_status(display_url, "下载失败", error_msg)
                    return {"status": "failed", "message": error_msg}

                except Exception as exc:
                    # 其他异常也不降级
                    error_msg = f"YouTube API Server unexpected error: {exc}"
                    logger.exception(f"[youtube-api] {error_msg}")
                    task_notifier.notify_task_status(display_url, "下载失败", error_msg)
                    return {"status": "failed", "message": error_msg}

            # ========== 原有逻辑（非 YouTube API Server 路径）==========
            # 已在前面完成元数据解析与下载器准备
            original_downloader = None
            if not download_url:
                original_downloader = metadata_downloader or create_downloader(url)
            else:
                logger.info("已提供 download_url，使用解析的元数据，跳过传统下载器的 get_video_info")
                is_from_generic = (platform == 'generic')

            # 根据 use_speaker_recognition 参数决定处理优先级
            subtitle = None

            if has_separate_download_url:
                # 提供了 download_url，说明用户已有下载地址
                # 跳过字幕获取，直接使用 download_url 进行下载和转录
                logger.info(
                    f"检测到提供了独立的下载地址，跳过字幕获取，直接使用 download_url 进行转录: "
                    f"url={url}, download_url={download_url}"
                )
                subtitle = None
            elif use_speaker_recognition:
                # 如果需要说话人识别，强制跳过平台字幕，直接进行下载转录
                logger.info(f"需要说话人识别，跳过平台字幕获取，强制下载转录: {url}")
                subtitle = None
            else:
                # 只有在不需要说话人识别时，才尝试获取平台字幕
                if metadata_downloader and metadata_downloader.__class__.__name__ == "YoutubeDownloader":
                    logger.info(f"不需要说话人识别，尝试获取YouTube平台字幕: {url}")
                    subtitle = metadata_downloader.get_subtitle(url)
                elif not download_url and original_downloader:
                    if original_downloader.__class__.__name__ == "YoutubeDownloader":
                        logger.info(f"不需要说话人识别，尝试获取YouTube平台字幕: {url}")
                        subtitle = original_downloader.get_subtitle(url)

            if subtitle:
                # 如果有字幕，直接使用
                logger.info(f"使用平台提供的字幕: {url}")

                task_notifier.notify_task_status(
                    display_url,
                    "平台字幕获取成功 - 直接使用平台字幕",
                    title=video_title,
                    author=author,
                )
                _safe_update_progress(
                    task_id,
                    stage="calibrating",
                    stage_label="已获取平台字幕，正在校对和总结",
                    basis="platform_subtitle",
                    confidence="high",
                    evidence={"transcript_chars": len(subtitle)},
                )

                # 使用新的缓存系统保存平台字幕
                cache_result = cache_manager.save_cache(
                    platform=platform,
                    url=url,
                    media_id=video_id,
                    use_speaker_recognition=False,  # 平台字幕没有说话人识别
                    transcript_data=subtitle,
                    transcript_type="capswriter",  # 平台字幕按文本格式保存
                    title=video_title,
                    author=author,
                    description=description,
                )

                if not cache_result:
                    logger.error("保存平台字幕到缓存失败")

                # 将LLM处理任务加入队列
                try:
                    llm_task_queue.put(
                        {
                            "task_id": task_id,
                            "url": url,
                            "display_url": display_url,
                            "platform": platform,
                            "media_id": video_id,
                            "video_title": video_title,
                            "author": author,
                            "description": description,
                            "transcript": subtitle,
                            "use_speaker_recognition": False,  # 平台字幕没有说话人信息
                            "is_generic": is_generic_downloader or is_from_generic,
                            "wechat_webhook": wechat_webhook,
                            "notification_channel": notification_channel,
                            "notification_webhooks": notification_webhooks,
                            "include_comments": include_comments,
                            "comment_limit": comment_limit,
                            "perf_tracker": tracker,
                        }
                    )
                    logger.info(
                        f"将LLM任务加入队列（平台字幕）: {task_id}, 标题: {video_title}"
                    )
                except Exception as exc:
                    logger.exception(f"将LLM任务加入队列失败（平台字幕）: {exc}")
                    task_notifier.send_text(f"【LLM任务加入队列失败】{exc}")
                    cache_manager.update_task_status(
                        task_id, TaskStatus.FAILED,
                        error_message=f"LLM任务加入队列失败: {exc}",
                    )
                    return {"status": "failed", "message": f"LLM任务加入队列失败: {exc}"}

                result = {
                    "status": "success",
                    "message": "使用平台字幕成功",
                    "data": {
                        "video_title": video_title,
                        "author": author,
                        "transcript": subtitle,
                    },
                }
                # 转录就绪、LLM 校对/总结进行中 → calibrating（终态由 LLM 阶段写）
                cache_manager.update_task_status(
                    task_id,
                    TaskStatus.CALIBRATING,
                    platform=platform,
                    media_id=video_id,
                    title=video_title,
                    author=author,
                    download_url=download_url,
                )
                return result
            else:
                # 没有字幕，需要下载音视频并转录
                logger.info(f"下载视频进行转录: {url}")
                task_notifier.notify_task_status(
                    display_url,
                    f"正在下载视频 - {engine_info}",
                    title=video_title,
                    author=author,
                )
                _safe_update_progress(
                    task_id,
                    stage="downloading",
                    stage_label="正在下载音视频",
                    basis="stage_transition",
                    confidence="low",
                )

                # 下载文件
                local_file = None
                if has_separate_download_url:
                    actual_download_url = download_url or url
                    logger.info(f"使用 GenericDownloader 下载文件: {actual_download_url}")
                    # 从 URL 提取文件名
                    from urllib.parse import urlparse, unquote
                    parsed_url = urlparse(actual_download_url)
                    path = unquote(parsed_url.path)
                    filename = os.path.basename(path)
                    if not filename:
                        filename = f"{platform}_{video_id}.mp4"

                    if download_info_obj and download_info_obj.filename:
                        filename = download_info_obj.filename

                    with tracker.track("download"):
                        local_file = _download_file_with_progress(
                            download_downloader,
                            actual_download_url,
                            filename,
                            task_id,
                        )
                else:
                    # 确保下载信息已获取
                    if download_info_obj is None and download_downloader:
                        try:
                            download_info_obj = download_downloader.get_download_info(parse_url)
                        except Exception as e:
                            logger.warning(f"[下载信息] 获取失败: {e}")

                    # 检查是否已有本地文件
                    if download_info_obj and download_info_obj.downloaded and download_info_obj.local_file:
                        local_file = download_info_obj.local_file
                        logger.info(f"使用已下载的本地文件: {local_file}")
                    else:
                        download_info_url = download_info_obj.download_url if download_info_obj else None
                        filename = download_info_obj.filename if download_info_obj else None

                        original_downloader = download_downloader or create_downloader(url)
                        if hasattr(original_downloader, "download_video_with_priority") and (
                            "youtube.com" in url or "youtu.be" in url
                        ):
                            logger.info(f"YouTube视频，使用优先级下载（yt-dlp优先）: {url}")
                            legacy_video_info = {
                                "video_id": video_id,
                                "video_title": video_title,
                                "author": author,
                                "description": description,
                                "platform": platform,
                                "download_url": download_info_url,
                                "filename": filename,
                            }
                            with tracker.track("download"):
                                local_file = original_downloader.download_video_with_priority(
                                    url, legacy_video_info
                                )
                        elif download_info_url and filename:
                            with tracker.track("download"):
                                local_file = _download_file_with_progress(
                                    original_downloader,
                                    download_info_url,
                                    filename,
                                    task_id,
                                )
                        else:
                            error_msg = f"无法获取下载信息: {url}"
                            logger.error(error_msg)
                            task_notifier.notify_task_status(
                                display_url, "下载失败", error_msg, title=video_title, author=author
                            )
                            return {"status": "failed", "message": error_msg}

                if not local_file:
                    error_msg = f"下载文件失败: {url}"
                    logger.error(error_msg)
                    task_notifier.notify_task_status(
                        display_url, "下载失败", error_msg, title=video_title, author=author
                    )
                    return {"status": "failed", "message": error_msg}

                try:
                    # 开始转录
                    logger.info(f"开始转录音视频: {local_file}")
                    task_notifier.notify_task_status(
                        display_url,
                        f"正在转录音视频 - {engine_info}",
                        title=video_title,
                        author=author,
                    )
                    _safe_update_progress(
                        task_id,
                        stage="transcribing",
                        stage_label="正在转录音视频",
                        basis="stage_transition",
                        confidence="low",
                    )

                    # platform 和 video_id 已在前面设置

                    # 根据是否需要说话人识别选择转录器（用 PerfTracker 记录转录阶段耗时）
                    with tracker.track("transcription"):
                        if use_speaker_recognition:
                            # 使用 FunASR 说话人识别服务器
                            logger.info("使用 FunASR 说话人识别服务器进行转录")
                            funasr_client = FunASRSpeakerClient(
                                progress_callback=_make_asr_progress_callback(task_id, "funasr")
                            )
                            funasr_result = funasr_client.transcribe_sync(local_file)

                            # 获取格式化的转录文本
                            transcript = funasr_result["formatted_text"]
                            transcription_data = funasr_result["transcription_result"]

                            # 使用新缓存系统保存
                            cache_result = cache_manager.save_cache(
                                platform=platform,
                                url=url,
                                media_id=media_id,
                                use_speaker_recognition=True,
                                transcript_data=transcription_data,
                                transcript_type="funasr",
                                title=video_title,
                                author=author,
                                description=description,
                            )

                            if not cache_result:
                                logger.error("保存FunASR转录结果到缓存失败")

                            # 构造与普通转录器兼容的结果
                            transcription_result = {
                                "transcript": transcript,
                                "speaker_recognition": True,
                                "transcription_data": transcription_data,
                            }
                        else:
                            # 使用普通 CapsWriter 转录器
                            transcriber = Transcriber(
                                progress_callback=_make_asr_progress_callback(task_id, "capswriter")
                            )
                            # 使用时间戳作为临时输出基础名
                            temp_output_base = datetime.datetime.now().strftime(
                                "%y%m%d-%H%M%S"
                            )
                            transcription_result = transcriber.transcribe(
                                local_file, temp_output_base
                            )
                            transcript = transcription_result.get("transcript", "")

                            # 使用新缓存系统保存
                            cache_result = cache_manager.save_cache(
                                platform=platform,
                                url=url,
                                media_id=media_id,
                                use_speaker_recognition=False,
                                transcript_data=transcript,
                                transcript_type="capswriter",
                                title=video_title,
                                author=author,
                                description=description,
                            )

                            if not cache_result:
                                logger.error("保存CapsWriter转录结果到缓存失败")

                    # 获取转录文本
                    transcript = transcription_result.get("transcript", "")

                    # 通知转录完成，包含转录文本预览和服务器类型信息
                    task_notifier.notify_task_status(
                        display_url,
                        f"转录完成 - {engine_info}",
                        title=video_title,
                        author=author,
                        transcript=transcript,
                    )

                    # 将LLM处理任务加入队列
                    try:
                        llm_task_queue.put(
                            {
                                "task_id": task_id,
                                "url": url,
                                "display_url": display_url,
                                "platform": platform,
                                "media_id": media_id,
                                "video_title": video_title,
                                "author": author,
                                "description": description,
                                "transcript": transcript,
                                "use_speaker_recognition": use_speaker_recognition,
                                "transcription_data": transcription_result.get(
                                    "transcription_data"
                                )
                                if use_speaker_recognition
                                else None,
                                "is_generic": is_generic_downloader or is_from_generic,
                                "wechat_webhook": wechat_webhook,
                                "notification_channel": notification_channel,
                                "notification_webhooks": notification_webhooks,
                                "include_comments": include_comments,
                                "comment_limit": comment_limit,
                                "perf_tracker": tracker,
                            }
                        )
                        logger.info(
                            f"将LLM任务加入队列（常规转录）: {task_id}, 标题: {video_title}"
                        )
                    except Exception as exc:
                        logger.exception(f"将LLM任务加入队列失败（常规转录）: {exc}")
                        task_notifier.send_text(f"【LLM任务加入队列失败】{exc}")
                        cache_manager.update_task_status(
                            task_id, TaskStatus.FAILED,
                            error_message=f"LLM任务加入队列失败: {exc}",
                        )
                        return {"status": "failed", "message": f"LLM任务加入队列失败: {exc}"}

                    # 返回结果
                    result = {
                        "status": "success",
                        "message": "转录成功",
                        "data": {
                            "video_title": video_title,
                            "author": author,
                            "transcript": transcript,
                            "speaker_recognition": use_speaker_recognition,
                        },
                    }
                finally:
                    pass

                # 转录就绪、LLM 校对/总结进行中 → calibrating（终态由 LLM 阶段写）
                _safe_update_progress(
                    task_id,
                    stage="calibrating",
                    stage_label="转录已完成，正在校对和总结",
                    basis="llm_started",
                    confidence="medium",
                    evidence={"transcript_chars": len(transcript)},
                )
                cache_manager.update_task_status(
                    task_id,
                    TaskStatus.CALIBRATING,
                    platform=platform,
                    media_id=video_id,
                    title=video_title,
                    author=author,
                    download_url=download_url,
                )

        return result
    except Exception as exc:
        logger.exception(f"转录处理异常: {exc}")
        # 任务失败时输出已记录的性能摘要
        tracker.log_summary()
        display_url = url
        get_notification_router().notify_task_status(
            url=display_url, status="转录异常", error=str(exc),
            channel_name=notification_channel, webhooks=notification_webhooks,
        )
        cache_manager.update_task_status(
            task_id, TaskStatus.FAILED, download_url=download_url,
            error_message=f"转录任务异常: {exc}",
        )
        return {
            "status": "failed",
            "message": f"转录任务异常: {exc}",
            "error": str(exc),
        }


def process_llm_queue():
    """处理LLM队列的后台任务（委托给 llm_ops 模块）"""
    from .llm_ops import process_llm_queue as _process_llm_queue
    _process_llm_queue()


def _handle_llm_task(llm_task: dict):
    """Worker entry for processing a single LLM task（委托给 llm_ops 模块）"""
    from .llm_ops import _handle_llm_task as _handle
    _handle(llm_task)
