"""
临时文件管理器

提供统一的临时文件管理机制，确保临时文件不会泄漏。
支持：
- 自动跟踪所有创建的临时文件
- 程序退出时自动清理
- 启动时清理旧的临时文件
- 上下文管理器支持
- 跨平台兼容性
"""

import os
import time
import shutil
import tempfile
import signal
import atexit
from pathlib import Path
from typing import List, Optional
from contextlib import contextmanager

from .logging import setup_logger

logger = setup_logger("tempfile_manager")


class TempFileManager:
    """
    统一的临时文件管理器

    负责跟踪和管理所有临时文件，确保不会发生文件泄漏。
    支持程序退出时的自动清理和启动时的旧文件清理。
    """

    def __init__(self, base_dir: str = "./data/temp"):
        """
        初始化临时文件管理器

        Args:
            base_dir: 临时文件基础目录
        """
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

        # 跟踪所有创建的临时文件和目录
        self.temp_files: List[Path] = []

        # 设置信号处理和清理钩子
        self._setup_cleanup_handlers()

        logger.info(f"临时文件管理器已初始化，基础目录: {self.base_dir}")

    def create_temp_file(self, suffix: str = None, prefix: str = None) -> Path:
        """
        创建临时文件并自动跟踪

        Args:
            suffix: 文件后缀（如 '.mp3'）
            prefix: 文件前缀

        Returns:
            Path: 临时文件路径

        Examples:
            >>> manager = TempFileManager()
            >>> temp_file = manager.create_temp_file(suffix='.txt')
            >>> temp_file.write_text('content')
            >>> # 文件会在程序退出时自动删除
        """
        try:
            temp_file = tempfile.NamedTemporaryFile(
                dir=self.base_dir,
                suffix=suffix,
                prefix=prefix,
                delete=False,  # 手动管理删除
            )
            temp_path = Path(temp_file.name)
            self.temp_files.append(temp_path)
            logger.debug(f"创建临时文件: {temp_path}")
            return temp_path
        except Exception as e:
            logger.error(f"创建临时文件失败: {e}")
            raise

    def create_temp_dir(self, prefix: str = None) -> Path:
        """
        创建临时目录并自动跟踪

        Args:
            prefix: 目录前缀

        Returns:
            Path: 临时目录路径

        Examples:
            >>> manager = TempFileManager()
            >>> temp_dir = manager.create_temp_dir(prefix='download_')
            >>> # 目录会在程序退出时自动删除
        """
        try:
            temp_dir = tempfile.mkdtemp(dir=self.base_dir, prefix=prefix)
            temp_path = Path(temp_dir)
            self.temp_files.append(temp_path)
            logger.debug(f"创建临时目录: {temp_path}")
            return temp_path
        except Exception as e:
            logger.error(f"创建临时目录失败: {e}")
            raise

    def track_file(self, file_path: Path) -> None:
        """
        手动跟踪一个已存在的文件/目录

        Args:
            file_path: 文件或目录路径

        Use Cases:
            - 跟踪由外部工具创建的临时文件
            - 跟踪下载的文件
        """
        file_path = Path(file_path)
        if file_path not in self.temp_files:
            self.temp_files.append(file_path)
            logger.debug(f"手动跟踪文件: {file_path}")

    def untrack_file(self, file_path: Path) -> None:
        """
        取消跟踪文件/目录（不会被自动清理）

        Args:
            file_path: 文件或目录路径

        Use Cases:
            - 文件已移动到缓存目录
            - 文件需要持久化保存
        """
        file_path = Path(file_path)
        if file_path in self.temp_files:
            self.temp_files.remove(file_path)
            logger.debug(f"取消跟踪文件: {file_path}")

    def clean_up(self, silent: bool = False) -> int:
        """
        清理所有跟踪的临时文件和目录

        Args:
            silent: 是否静默模式（不记录日志）

        Returns:
            int: 成功清理的文件数量
        """
        cleaned_count = 0

        for path in self.temp_files[:]:  # 使用副本进行迭代
            try:
                if path.exists():
                    if path.is_file():
                        path.unlink()
                    elif path.is_dir():
                        shutil.rmtree(path)
                    cleaned_count += 1
                    if not silent:
                        logger.debug(f"已清理: {path}")
                # 从跟踪列表中移除
                self.temp_files.remove(path)
            except Exception as e:
                if not silent:
                    logger.warning(f"清理临时文件失败: {path}, 错误: {e}")

        if not silent and cleaned_count > 0:
            logger.info(f"临时文件清理完成，共清理 {cleaned_count} 个文件/目录")

        return cleaned_count

    def clean_up_old_files(
        self,
        hours: int = 24,
        silent: bool = False,
        *,
        protected_roots=(),
    ) -> int:
        """
        清理旧的临时文件（启动时调用）

        Args:
            hours: 清理多少小时前的文件
            silent: 是否静默模式

        Returns:
            int: 清理的文件数量
        """
        cleaned_count = 0
        cutoff_time = time.time() - hours * 3600

        if not self.base_dir.exists():
            return 0

        base_resolved = self.base_dir.resolve()
        validated_protected = []
        for root in protected_roots or ():
            try:
                resolved = Path(root).resolve()
                resolved.relative_to(base_resolved)
            except (OSError, ValueError):
                continue
            if resolved != base_resolved:
                validated_protected.append(resolved)

        def is_protected(item: Path) -> bool:
            try:
                resolved = item.resolve()
            except OSError:
                return False
            for protected in validated_protected:
                if resolved == protected:
                    return True
                try:
                    resolved.relative_to(protected)
                    return True
                except ValueError:
                    pass
                try:
                    protected.relative_to(resolved)
                    return True
                except ValueError:
                    pass
            return False

        # 遍历所有文件和目录
        for item in self.base_dir.rglob("*"):
            try:
                # 跳过目录本身和跟踪列表中的文件
                if item == self.base_dir or item in self.temp_files:
                    continue
                if is_protected(item):
                    continue

                if item.is_file() or (item.is_dir() and any(item.rglob("*"))):
                    # 检查修改时间
                    mtime = item.stat().st_mtime
                    if mtime < cutoff_time:
                        if item.is_file():
                            item.unlink()
                        else:
                            shutil.rmtree(item)
                        cleaned_count += 1
                        if not silent:
                            logger.debug(f"清理旧文件: {item}")
            except Exception as e:
                if not silent:
                    logger.warning(f"清理旧文件失败: {item}, 错误: {e}")

        if not silent:
            logger.info(
                f"启动时清理完成，清理了 {hours} 小时前的 {cleaned_count} 个文件"
            )

        return cleaned_count

    def get_temp_dir(self) -> Path:
        """
        获取临时文件基础目录

        Returns:
            Path: 临时目录路径
        """
        return self.base_dir

    def get_stats(self) -> dict:
        """
        获取临时文件统计信息

        Returns:
            dict: 统计信息
        """
        tracked_count = len(self.temp_files)
        tracked_size = 0

        for path in self.temp_files:
            if path.exists():
                if path.is_file():
                    tracked_size += path.stat().st_size
                elif path.is_dir():
                    for file in path.rglob("*"):
                        if file.is_file():
                            tracked_size += file.stat().st_size

        return {
            "base_dir": str(self.base_dir),
            "tracked_count": tracked_count,
            "tracked_size_mb": round(tracked_size / 1024 / 1024, 2),
            "temp_files_count": len([f for f in self.temp_files if f.is_file()]),
            "temp_dirs_count": len([d for d in self.temp_files if d.is_dir()]),
        }

    def _setup_cleanup_handlers(self) -> None:
        """设置自动清理处理程序"""
        # 程序正常退出时清理
        atexit.register(self._atexit_cleanup)

        # 捕获退出信号（仅在主进程中）
        if os.getpid() == os.getppid():
            try:
                signal.signal(signal.SIGTERM, self._signal_handler)
                signal.signal(signal.SIGINT, self._signal_handler)
            except Exception as e:
                logger.warning(f"设置信号处理失败: {e}")

    def _atexit_cleanup(self) -> None:
        """atexit 清理回调"""
        try:
            self.clean_up(silent=True)
        except Exception as e:
            # atexit 中不能记录日志，静默处理
            pass

    def _signal_handler(self, signum, frame) -> None:
        """信号处理回调"""
        try:
            logger.info(f"收到退出信号 {signum}，清理临时文件...")
            self.clean_up()
        except Exception as e:
            logger.error(f"信号处理失败: {e}")
        finally:
            # 恢复默认信号处理并退出
            signal.signal(signum, signal.SIG_DFL)
            os.kill(os.getpid(), signum)

    @contextmanager
    def temp_directory(self, prefix: str = None):
        """
        上下文管理器：创建临时目录并在退出时清理

        Args:
            prefix: 目录前缀

        Yields:
            Path: 临时目录路径

        Examples:
            >>> manager = TempFileManager()
            >>> with manager.temp_directory(prefix='work_') as temp_dir:
            ...     # 使用临时目录
            ...     temp_file = temp_dir / "test.txt"
            ...     temp_file.write_text('content')
            ... # 退出时自动清理
        """
        temp_dir = self.create_temp_dir(prefix=prefix)
        try:
            yield temp_dir
        finally:
            try:
                if temp_dir.exists():
                    shutil.rmtree(temp_dir)
                self.untrack_file(temp_dir)
            except Exception as e:
                logger.warning(f"清理临时目录失败: {temp_dir}, 错误: {e}")

    @contextmanager
    def temp_file(self, suffix: str = None, prefix: str = None):
        """
        上下文管理器：创建临时文件并在退出时清理

        Args:
            suffix: 文件后缀
            prefix: 文件前缀

        Yields:
            Path: 临时文件路径

        Examples:
            >>> manager = TempFileManager()
            >>> with manager.temp_file(suffix='.txt') as temp_file:
            ...     temp_file.write_text('content')
            ... # 退出时自动清理
        """
        temp_file = self.create_temp_file(suffix=suffix, prefix=prefix)
        try:
            yield temp_file
        finally:
            try:
                if temp_file.exists():
                    temp_file.unlink()
                self.untrack_file(temp_file)
            except Exception as e:
                logger.warning(f"清理临时文件失败: {temp_file}, 错误: {e}")

    def __enter__(self):
        """上下文管理器支持"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """退出时清理"""
        self.clean_up()

    def __del__(self):
        """析构时清理"""
        try:
            self.clean_up(silent=True)
        except Exception:
            pass
