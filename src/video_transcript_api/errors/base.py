"""错误基类模块"""


class TranscriptAPIError(Exception):
    """LearnFlux 项目级错误基类

    所有自定义异常都应继承此类，便于统一捕获和分类。

    Attributes:
        message: 人类可读的错误信息
        retryable: 该错误是否可重试
    """

    def __init__(self, message: str = "", retryable: bool = False):
        self.message = message
        self.retryable = retryable
        super().__init__(message)
