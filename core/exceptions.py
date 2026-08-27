class XiaoyouError(Exception):
    """Base exception for Xiaoyou Core"""

    def __init__(
        self, message: str, code: str = "INTERNAL_ERROR", details: dict = None
    ):
        super().__init__(message)
        self.code = code
        self.details = details or {}


class ResourceError(XiaoyouError):
    """Resource availability error (GPU, Memory)"""

    def __init__(self, message: str, details: dict = None):
        super().__init__(message, code="RESOURCE_ERROR", details=details)


class ModelError(XiaoyouError):
    """Model execution error"""

    def __init__(self, message: str, details: dict = None):
        super().__init__(message, code="MODEL_ERROR", details=details)


class ConfigError(XiaoyouError):
    """Configuration error"""

    def __init__(self, message: str, details: dict = None):
        super().__init__(message, code="CONFIG_ERROR", details=details)


class ServiceError(XiaoyouError):
    """External service error"""

    def __init__(self, message: str, details: dict = None):
        super().__init__(message, code="SERVICE_ERROR", details=details)
