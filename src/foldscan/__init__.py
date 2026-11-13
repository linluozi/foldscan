"""foldscan: exact case-insensitive bytes search with a measured fast path."""

from .core import SMALL_BUFFER, contains, count, count_many, reference_count

__version__ = "0.1.0"
__all__ = ["count", "contains", "count_many", "reference_count", "SMALL_BUFFER", "__version__"]
