"""Committed package snapshots and compact, durable view invalidations."""

from collections.abc import Callable
from dataclasses import dataclass
from functools import wraps
from typing import TYPE_CHECKING, cast

from dojo.model import (
    Client,
    ConsentAcceptance,
    ConsentPolicy,
    Job,
    MetaConnectionStatus,
    Package,
    Upload,
    YayinIncelemesi,
    YayinZamani,
)

if TYPE_CHECKING:
    from dojo.ports import PackageStore, UploadStore


@dataclass(frozen=True)
class PackageState:
    package_id: int
    content_revision: int
    view_revision: int
    document: dict


@dataclass(frozen=True)
class ChangeEvent:
    event_id: str
    versions: dict[str, int]
    revoked_client_ids: list[int]


def _result_resources(value: object, store: "PackageStore") -> list[str]:
    if isinstance(value, Package):
        return ["dashboard", "completed", "publication", f"package:{value.id}"]
    if isinstance(value, Upload):
        return ["dashboard", f"upload:{value.upload_id}", f"package:{value.package_id}"]
    if isinstance(value, Job):
        keys = ["dashboard", "publication"]
        if value.upload_id is not None:
            upload = cast("UploadStore", store).get_by_pk(value.upload_id)
            if upload is not None:
                keys.extend([f"package:{upload.package_id}", f"upload:{upload.upload_id}"])
        else:
            package = store.get_by_folder(str(value.payload.get("package", "")))
            if package is not None:
                keys.append(f"package:{package.id}")
        return keys
    if isinstance(value, YayinIncelemesi):
        return ["dashboard", "publication", f"review:{value.id}"]
    if isinstance(value, YayinZamani):
        return ["dashboard", "publication"]
    if isinstance(value, Client):
        return ["auth", "settings", "setup"]
    if isinstance(value, (ConsentPolicy, ConsentAcceptance, MetaConnectionStatus)):
        return ["settings", "setup", "dashboard"]
    return []


def emits[**P, T](
    *resources: str, result: bool = False,
) -> Callable[[Callable[P, T]], Callable[P, T]]:
    """Keep store writes and their invalidations in the existing transaction."""
    def decorate(method: Callable[P, T]) -> Callable[P, T]:
        @wraps(method)
        def changed(*args: P.args, **kwargs: P.kwargs) -> T:
            store = cast("PackageStore", args[0])
            with store.command_transaction():
                returned = method(*args, **kwargs)
                value: object = returned
                if result:
                    if isinstance(value, tuple) and len(value) == 2 \
                            and isinstance(value[1], bool):
                        if not value[1]:
                            return returned
                        value = value[0]
                    if value is None or value is False:
                        return returned
                keys = [*resources, *(_result_resources(value, store) if result else [])]
                if keys:
                    store.queue_change(keys)
                return returned
        return changed
    return decorate
