"""Package version resolution."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("deltadewa")
except PackageNotFoundError:
    __version__ = "0.0.0+unknown"
