#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
pytest 全局配置文件

用于管理测试环境的全局资源，包括飞书通知资源与路由器。
"""

import os
import sys
import pytest

# 添加src目录到Python路径
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'src'))

from video_transcript_api.utils.notifications import (
    init_all_notifiers,
    shutdown_all_notifiers,
)


@pytest.fixture(scope="session", autouse=True)
def setup_global_notifiers():
    """
    Initialize all notification subsystems (Feishu + Router)
    once per test session.
    """
    init_all_notifiers()
    yield
    shutdown_all_notifiers()
