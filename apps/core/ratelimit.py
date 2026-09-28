"""A small cache-backed rate limiter for the login and password-reset views."""

import hashlib

from django.core.cache import cache


def client_ip(request) -> str | None:
    # Behind nginx the real address arrives in X-Real-IP; nginx sets it, clients cannot.
    return request.META.get("HTTP_X_REAL_IP") or request.META.get("REMOTE_ADDR")


def _key(scope: str, ident: str) -> str:
    return "rl:" + scope + ":" + hashlib.sha256(ident.encode()).hexdigest()


def is_limited(scope: str, ident: str, limit: int) -> bool:
    return cache.get(_key(scope, ident), 0) >= limit


def hit(scope: str, ident: str, window: int) -> int:
    key = _key(scope, ident)
    if cache.add(key, 1, timeout=window):
        return 1
    try:
        return cache.incr(key)
    except ValueError:
        cache.set(key, 1, timeout=window)
        return 1


def reset(scope: str, ident: str) -> None:
    cache.delete(_key(scope, ident))
