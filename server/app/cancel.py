"""Per-request cancellation for /suggest.

The API accepts concurrent clients in one process (FastAPI threadpool + shared
rate limiters). Cancel must be scoped to the request that disconnected — never
tear down a shared httpx client or a sibling in-flight suggest.
"""


class SuggestCancelled(Exception):
    """The client disconnected or the caller stopped this suggestion."""
