from functools import wraps
from typing import Any, Callable


def async_toolify(
    coro: Callable[..., Any],
    on_success: Callable[[Any], Any] = lambda r: {"status": "success", "result": r},
    on_error: Callable[[Any], Any] = lambda e: {"status": "error", "result": str(e)},
):
    @wraps(coro)
    async def wrapper(*args, **kwargs):
        try:
            return on_success(await coro(*args, **kwargs))
        except Exception as e:
            return on_error(e)

    return wrapper
