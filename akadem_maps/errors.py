"""Stable error codes shared by the CLI and location picker."""


class SourceError(RuntimeError):
    code = 'source_invalid'


class NetworkError(RuntimeError):
    code = 'network'

    def __init__(self, message, retry_after=0):
        super().__init__(message)
        self.retry_after = retry_after


class OfflineMissing(FileNotFoundError):
    code = 'offline_missing'


class NoRoads(ValueError):
    code = 'no_roads'


class ToolError(RuntimeError):
    code = 'sumo'


def error_code(exc):
    import urllib.error
    if isinstance(exc, (TimeoutError, urllib.error.URLError)) or str(exc).startswith('Download failed'):
        return 'network'
    if 'No suitable start road' in str(exc):
        return 'no_roads'
    return getattr(exc, 'code', type(exc).__name__)
