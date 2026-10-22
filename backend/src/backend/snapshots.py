"""Run a read and its resource version inside one repeatable-read boundary."""

from collections.abc import Callable
from functools import wraps
from typing import cast

from dojo.ports import PackageStore
from fastapi import Request, Response


def versioned_snapshot[**P, T](resource: str) -> Callable[[Callable[P, T]], Callable[P, T]]:
    def decorate(method: Callable[P, T]) -> Callable[P, T]:
        @wraps(method)
        def snapshot(*args: P.args, **kwargs: P.kwargs) -> T:
            request = cast(Request, kwargs["request"])
            response = cast(Response, kwargs["response"])
            store = cast(PackageStore, request.app.state.publishing._packages)
            with store.read_snapshot():
                key = resource
                if key == "package":
                    active = store.get_active()
                    key = f"package:{active.id}" if active is not None else "dashboard"
                elif key == "upload":
                    key = f"upload:{request.path_params['upload_id']}"
                response.headers["X-Resource-Key"] = key
                response.headers["X-Resource-Version"] = str(store.get_resource_version(key))
                response.headers["Cache-Control"] = "no-store"
                return method(*args, **kwargs)
        return snapshot
    return decorate
