"""自定义异常模块，定义应用程序的异常层次结构。"""


class OCRAppError(Exception):
    """应用程序基础异常，所有自定义异常均继承自此类。"""


class ConfigError(OCRAppError):
    """配置异常，当必填配置项缺失或配置值无效时抛出。"""


class S3AccessError(OCRAppError):
    """S3 访问异常，当 S3 桶不存在或无访问权限时抛出。"""


class S3UploadError(OCRAppError):
    """S3 上传异常，当文件上传超过最大重试次数后仍失败时抛出。"""


class MinerUError(OCRAppError):
    """MinerU 执行异常，当 MinerU CLI 返回非零退出码时抛出。"""


class UnsupportedFormatError(OCRAppError):
    """不支持的文件格式异常，当输入文件的扩展名不在支持列表中时抛出。"""
