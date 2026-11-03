"""Feishu URL routing, complete source retention, and text-only processing."""
from pathlib import Path
import json
import subprocess
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from video_transcript_api.document_sources import feishu
from video_transcript_api.utils.url_parser import URLParser


URL = 'https://team.feishu.cn/wiki/DocumentToken12345?from=from_copylink#share-section'
CANONICAL = 'https://team.feishu.cn/wiki/DocumentToken12345'
BODY = '<title>Original title</title>\n# First\n\nFirst paragraph.\n\n<grid><column>Last paragraph.</column></grid>\n'


def payload(content=BODY):
    return {'ok': True, 'data': {'document': {
        'document_id': 'resolved-docx', 'revision_id': 3, 'content': content,
        'reference_map': {'images': {'one': {'token': 'original-reference'}}},
    }}}


def install_cli(monkeypatch, response=None, code=0):
    runner = Mock(return_value=SimpleNamespace(
        returncode=code, stdout=json.dumps(response if response is not None else payload()),
        stderr='private-cli-authorization-output',
    ))
    monkeypatch.setattr(feishu.shutil, 'which', lambda _: '/configured/lark-cli')
    monkeypatch.setattr(feishu.subprocess, 'run', runner)
    return runner


def test_wiki_share_variants_have_one_identity_and_never_resolve_short_urls(monkeypatch):
    parser = URLParser()
    head = Mock(side_effect=AssertionError('Document URLs must not use HTTP media probes'))
    monkeypatch.setattr(parser, '_resolve_short_url', head)
    first = parser.parse(URL)
    second = parser.parse(CANONICAL + '?from=xhslink.com')
    assert first.platform == second.platform == 'feishu'
    assert first.video_id == second.video_id
    assert first.normalized_url == CANONICAL
    assert first.is_short_url is False
    head.assert_not_called()


@pytest.mark.parametrize('url', [
    'https://team.feishu.cn/docx/DocumentToken12345',
    'https://team.larksuite.com/wiki/DocumentToken12345',
])
def test_native_document_hosts_and_types(url):
    assert parse(url).platform == 'feishu'


def parse(url):
    return URLParser().parse(url)


@pytest.mark.parametrize('url', [
    'https://feishu.cn.evil.example/wiki/DocumentToken12345',
    'https://evil.example/wiki/DocumentToken12345',
    'https://team.feishu.cn@evil.example/wiki/DocumentToken12345',
    'https://user:password@team.feishu.cn/wiki/DocumentToken12345',
    'http://team.feishu.cn/wiki/DocumentToken12345',
    'https://team.feishu.cn:8000/wiki/DocumentToken12345',
    'https://team.feishu.cn/wiki/DocumentToken12345;cmd',
    'https://team.feishu.cn/wiki/DocumentToken12345/more',
])
def test_untrusted_or_unsupported_links_do_not_reach_cli(url, monkeypatch, tmp_path):
    runner = install_cli(monkeypatch)
    assert feishu.parse_feishu_url(url) is None
    with pytest.raises(feishu.FeishuDocumentError):
        feishu.fetch_feishu_document(url, settings={}, snapshot_dir=tmp_path)
    runner.assert_not_called()


def test_fetch_reads_full_doc_and_preserves_original_response(monkeypatch, tmp_path):
    raw = payload()
    runner = install_cli(monkeypatch, raw)
    doc = feishu.fetch_feishu_document(URL, settings={}, snapshot_dir=tmp_path)
    args = runner.call_args.args[0]
    assert args == ['/configured/lark-cli', 'docs', '+fetch', '--doc', CANONICAL,
                    '--as', 'user', '--scope', 'full', '--doc-format', 'markdown']
    assert runner.call_args.kwargs.get('shell') is not True
    assert doc.title == 'Original title'
    assert '# First' in doc.text and 'First paragraph.' in doc.text and 'Last paragraph.' in doc.text
    assert '<grid>' not in doc.text
    assert json.loads(Path(doc.snapshot_path).read_text()) == raw
    assert Path(doc.snapshot_path).stat().st_mode & 0o777 == 0o600


def test_visual_content_is_retained_and_disclosed_without_claiming_ocr(monkeypatch, tmp_path):
    raw = payload(BODY + '\n![Original caption](https://cdn.example/image.png)\n<whiteboard token="board-reference"/>')
    install_cli(monkeypatch, raw)
    doc = feishu.fetch_feishu_document(URL, settings={}, snapshot_dir=tmp_path)
    assert '![Original caption](https://cdn.example/image.png)' in doc.text
    assert len(doc.warnings) == 2
    assert '尚未识别' in doc.text and '飞书画板' in doc.text
    assert 'board-reference' in Path(doc.snapshot_path).read_text()
    assert 'board-reference' not in doc.text


def test_literal_code_is_not_stripped_as_document_layout():
    title, text, warnings = feishu._reading_text(BODY + '\n```xml\n<column>code</column>\n```')
    assert '<column>code</column>' in text


@pytest.mark.parametrize('content', [
    '<title>Empty</title>',
    '<title>Images only</title>\n![](https://cdn.example/image.png)',
    '<title>Board only</title>\n<whiteboard token="board"/>',
])
def test_missing_readable_body_is_not_an_ai_success(content, monkeypatch, tmp_path):
    install_cli(monkeypatch, payload(content))
    with pytest.raises(feishu.FeishuDocumentError, match='正文'):
        feishu.fetch_feishu_document(URL, settings={}, snapshot_dir=tmp_path)


def test_cli_errors_do_not_expose_private_output(monkeypatch, tmp_path):
    install_cli(monkeypatch, code=1)
    with pytest.raises(feishu.FeishuDocumentError) as error:
        feishu.fetch_feishu_document(URL, settings={}, snapshot_dir=tmp_path)
    assert 'private-cli' not in str(error.value)
    assert '权限' in str(error.value)


def test_cli_timeout_is_actionable(monkeypatch, tmp_path):
    runner = install_cli(monkeypatch)
    runner.side_effect = subprocess.TimeoutExpired('lark-cli', 60, stderr='private-cli-output')
    with pytest.raises(feishu.FeishuDocumentError, match='超时'):
        feishu.fetch_feishu_document(URL, settings={}, snapshot_dir=tmp_path)


def test_partial_document_is_rejected(monkeypatch, tmp_path):
    install_cli(monkeypatch, payload('<fragment><excerpt>Only part</excerpt></fragment>'))
    with pytest.raises(feishu.FeishuDocumentError, match='片段'):
        feishu.fetch_feishu_document(URL, settings={}, snapshot_dir=tmp_path)


def test_missing_cli_is_actionable(monkeypatch, tmp_path):
    monkeypatch.setattr(feishu.shutil, 'which', lambda _: None)
    with pytest.raises(feishu.FeishuDocumentError, match='CLI'):
        feishu.fetch_feishu_document(URL, settings={}, snapshot_dir=tmp_path)


@pytest.mark.parametrize('response', [{'ok': False}, {'ok': True, 'data': {}}, ['invalid']])
def test_invalid_cli_contract_is_not_content(response, monkeypatch, tmp_path):
    install_cli(monkeypatch, response)
    with pytest.raises(feishu.FeishuDocumentError, match='有效文档正文'):
        feishu.fetch_feishu_document(URL, settings={}, snapshot_dir=tmp_path)


@pytest.mark.parametrize('settings,task', [
    ({}, {'owner_user_id': 'owner'}),
    ({'enabled': True}, {'owner_user_id': 'owner'}),
    ({'enabled': True, 'owner_user_id': 'owner'}, {'owner_user_id': 'other'}),
    ({'enabled': True, 'owner_user_id': 'owner'}, {}),
])
def test_local_cli_identity_is_not_shared_with_arbitrary_api_users(settings, task):
    with pytest.raises(feishu.FeishuDocumentError):
        feishu.require_feishu_access(settings, task)


def install_flow(monkeypatch, tmp_path, owner='owner'):
    from video_transcript_api.api.services import transcription
    from video_transcript_api.cache.cache_manager import CacheManager
    cache = CacheManager(cache_dir=str(tmp_path / 'cache'))
    task = cache.create_task(url=URL, use_speaker_recognition=False, owner_user_id=owner)
    queue = SimpleNamespace(items=[])
    queue.put = queue.items.append
    monkeypatch.setattr(transcription, 'cache_manager', cache)
    monkeypatch.setattr(transcription, 'llm_task_queue', queue)
    monkeypatch.setattr(transcription, 'get_notification_router', lambda: Mock())
    monkeypatch.setattr(transcription, 'get_config', lambda: {
        'feishu_documents': {'enabled': True, 'owner_user_id': 'owner'},
        'storage': {'source_files_dir': str(tmp_path / 'sources')},
    })
    monkeypatch.setattr(transcription, 'create_downloader', Mock(side_effect=AssertionError('No media/ASR path')))
    return transcription, cache, task, queue


def test_document_enters_text_pipeline_without_media_download_or_asr(monkeypatch, tmp_path):
    transcription, cache, task, queue = install_flow(monkeypatch, tmp_path)
    install_cli(monkeypatch)
    result = transcription.process_transcription(task['task_id'], URL)
    assert result['status'] == 'success'
    assert result['data']['media_type'] == 'document'
    assert len(queue.items) == 1
    queued = queue.items[0]
    assert queued['platform'] == 'feishu'
    assert queued['include_comments'] is False
    assert 'Last paragraph.' in queued['transcript']
    saved = cache.get_cache('feishu', feishu.parse_feishu_url(URL).media_id, False)
    assert saved['transcript_data'] == queued['transcript']
    assert cache.get_task_by_id(task['task_id'])['status'] == 'calibrating'
    transcription.create_downloader.assert_not_called()


def test_owner_gate_precedes_even_cached_private_content(monkeypatch, tmp_path):
    transcription, cache, task, queue = install_flow(monkeypatch, tmp_path, owner='other')
    reader = Mock(side_effect=AssertionError('Do not inspect private cache'))
    monkeypatch.setattr(cache, 'get_cache', reader)
    result = transcription.process_transcription(task['task_id'], URL)
    assert result['status'] == 'failed'
    assert '身份' in result['message']
    assert not queue.items
    reader.assert_not_called()
    transcription.create_downloader.assert_not_called()


def test_source_link_and_history_type_are_documents():
    from video_transcript_api.api.routes.views import _decorate_source_link
    from video_transcript_api.api.routes.audit import _history_content_type
    view = {'url': URL, 'platform': 'feishu'}
    _decorate_source_link(view)
    assert view['source_link_label'] == '查看原文'
    assert _history_content_type('feishu', 'Original title', None, URL) == 'file'
