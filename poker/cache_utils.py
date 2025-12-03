from __future__ import annotations

from typing import Any, Tuple

from django.core.cache import cache
from django.db.models import Q

from .models import CARD_SETS, Room

ROOM_SNAPSHOT_TTL = 30
ROOM_PARTIAL_TTL = 5
ROOM_VERSION_KEY = "room:version:{room_id}"
ROOM_SNAPSHOT_KEY = "room:snapshot:{room_id}:{version}"
ROOM_LIST_CACHE_KEY = "room:list:latest"


def _ensure_room_version(room_id: int) -> int:
    key = ROOM_VERSION_KEY.format(room_id=room_id)
    version = cache.get(key)
    if version is None:
        version = 1
        cache.set(key, version)
    return version


def _bump_room_version(room_id: int) -> int:
    key = ROOM_VERSION_KEY.format(room_id=room_id)
    try:
        return cache.incr(key)
    except ValueError:
        cache.set(key, 2)
        return 2


def get_room_snapshot(room: Room) -> Tuple[dict[str, Any], int]:
    version = _ensure_room_version(room.id)
    key = ROOM_SNAPSHOT_KEY.format(room_id=room.id, version=version)
    data = cache.get(key)
    if data is None:
        stories_qs = room.stories.exclude(jira_issue_type__iexact="Epic")

        # If this room is linked to a Jira project, suppress imported issues from other projects.
        # Imported stories carry notes like "Issue: KEY\n{browse_url}", so we check the prefix.
        if room.jira_project_key:
            wrong_project = Q(notes__startswith="Issue: ") & ~Q(
                notes__startswith=f"Issue: {room.jira_project_key}-"
            )
            stories_qs = stories_qs.exclude(wrong_project)

        data = {
            "stories": list(stories_qs.prefetch_related("votes__participant").all()),
            "participants": list(room.participants.all()),
            "cards": CARD_SETS.get(room.card_set, CARD_SETS["fibonacci"]),
        }
        cache.set(key, data, timeout=ROOM_SNAPSHOT_TTL)
    return data, version


def invalidate_room_cache(room: Room) -> None:
    _bump_room_version(room.id)


def room_fragment_cache_key(room_id: int, fragment: str, version: int, participant_id: Any) -> str:
    return f"room:{room_id}:{fragment}:{version}:{participant_id}"


def invalidate_room_list() -> None:
    cache.delete(ROOM_LIST_CACHE_KEY)
