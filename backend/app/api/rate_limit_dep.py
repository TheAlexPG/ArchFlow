from fastapi import Depends, HTTPException, Request, Response

from app.api.deps import get_current_user
from app.core.rate_limit import check
from app.models.user import User


def _set_headers(response: Response, result) -> None:
    response.headers["X-RateLimit-Limit"] = str(result.limit)
    response.headers["X-RateLimit-Remaining"] = str(result.remaining)
    response.headers["X-RateLimit-Reset"] = str(result.reset_at)


async def enforce_rate_limit(
    request: Request,
    response: Response,
    current_user: User = Depends(get_current_user),
) -> User:
    """Depend on this to cap an authenticated caller.

    Prefers the API key id as the caller scope (so two services sharing a
    human user but using their own keys each get their own budget); falls
    back to user id for JWT callers.
    """
    api_key = getattr(request.state, "api_key", None)
    if api_key is not None:
        caller_id = f"ak:{api_key.id}"
    else:
        caller_id = f"user:{current_user.id}"

    result = await check(caller_id)
    _set_headers(response, result)
    if not result.allowed:
        response.headers["Retry-After"] = str(result.retry_after)
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded",
            headers={
                "X-RateLimit-Limit": str(result.limit),
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(result.reset_at),
                "Retry-After": str(result.retry_after),
            },
        )
    return current_user
