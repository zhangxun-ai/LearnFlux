#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import sys
import argparse

# 添加src目录到Python路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

# 在导入其他模块之前初始化日志系统
from video_transcript_api.utils.logging import setup_logger
setup_logger()

# 注意：全局 WeComNotifier 会在 FastAPI 的 startup_event 中初始化
# 在 shutdown_event 中清理，无需在 main.py 中重复初始化

from video_transcript_api.api.server import start_server

def main():
    """主程序入口函数"""
    parser = argparse.ArgumentParser(description="LearnFlux AI 内容学习工作台")

    # 添加命令行参数
    parser.add_argument("--start", action="store_true", help="启动API服务")

    # 解析命令行参数
    args = parser.parse_args()

    if args.start:
        # 启动API服务
        start_server()
    else:
        # 显示帮助信息
        parser.print_help()

if __name__ == "__main__":
    # 确保工作目录是项目根目录
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    main() 
