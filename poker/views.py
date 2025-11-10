# poker/views.py
from __future__ import annotations

import requests
from requests.auth import HTTPBasicAuth

from django.contrib import messages
from django.http import HttpResponseBadRequest, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from .forms import JiraSettingsForm, JoinForm, RoomForm, StoryForm
from .models import CARD_SETS, Participant, Room, Story, Vote


# ============================== helpers ====================================

def current_participant(request, room: Room) -> Participant | None:
    pid = request.session.get(f"p_{room.code}")
    if not pid:
        return None
    try:
        return room.participants.get(id=pid)
    except Participant.DoesNotExist:
        return None


def facilitator_required(participant: Participant | None) -> bool:
    return bool(participant and participant.is_facilitator)


def _room_context(request, room: Room) -> dict:
    """Build the same context used across full and partial renders."""
    participant = current_participant(request, room)
    stories = list(room.stories.all())
    cards = CARD_SETS.get(room.card_set, CARD_SETS["fibonacci"])

    # annotate selected vote for highlight
    for st in stories:
        st.current_vote = ""
    if participant:
        user_votes = {v.story_id: v.value for v in Vote.objects.filter(participant=participant, story__in=stories)}
        for st in stories:
            st.current_vote = user_votes.get(st.id, "")

    return {
        "room": room,
        "participant": participant,
        "stories": stories,
        "cards": cards,
        "story_form": StoryForm(),
    }


def _is_htmx(request) -> bool:
    return bool(request.headers.get("HX-Request"))


def _render_story(request, story: Story):
    """Render just one story <li> for HTMX swaps."""
    room = story.room
    ctx = _room_context(request, room)

    # refresh the just-updated story and attach current_vote for this participant
    s = room.stories.get(pk=story.pk)
    s.current_vote = ""
    p = ctx["participant"]
    if p:
        v = Vote.objects.filter(story=s, participant=p).first()
        if v:
            s.current_vote = v.value

    return render(
        request,
        "poker/partials/_story.html",
        {"room": room, "participant": p, "cards": ctx["cards"], "s": s},
    )


# ============================== core views =================================

def room_list(request):
    rooms = Room.objects.order_by("-created_at")[:50]
    form = RoomForm()
    if request.method == "POST":
        form = RoomForm(request.POST)
        if form.is_valid():
            room = form.save()
            return redirect("poker:room_detail", code=room.code)
    return render(request, "poker/room_list.html", {"rooms": rooms, "form": form})


def room_create(request):
    if request.method != "POST":
        return HttpResponseBadRequest("POST only")
    form = RoomForm(request.POST)
    if form.is_valid():
        room = form.save()
        return redirect("poker:room_detail", code=room.code)
    rooms = Room.objects.order_by("-created_at")[:50]
    return render(request, "poker/room_list.html", {"rooms": rooms, "form": form})


def join_room(request, code: str):
    room = get_object_or_404(Room, code=code)
    if request.method == "POST":
        form = JoinForm(request.POST)
        if form.is_valid():
            p = Participant.objects.create(
                room=room,
                display_name=form.cleaned_data["display_name"],
                is_facilitator=form.cleaned_data.get("is_facilitator", False),
            )
            request.session[f"p_{room.code}"] = p.id
            return redirect("poker:room_detail", code=room.code)
    else:
        form = JoinForm()
    return render(request, "poker/join_room.html", {"room": room, "form": form})


def room_detail(request, code: str):
    room = get_object_or_404(Room, code=code)
    ctx = _room_context(request, room)
    return render(request, "poker/room_detail.html", ctx)


def story_create(request, code: str):
    room = get_object_or_404(Room, code=code)
    participant = current_participant(request, room)
    if not participant:
        return redirect("poker:join_room", code=room.code)
    if request.method == "POST":
        form = StoryForm(request.POST)
        if form.is_valid():
            s = form.save(commit=False)
            s.room = room
            s.save()

    # HTMX? re-render stories panel so the new story appears without jumping
    if _is_htmx(request):
        ctx = _room_context(request, room)
        return render(request, "poker/partials/_stories.html", ctx)

    return redirect("poker:room_detail", code=room.code)


def cast_vote(request, story_id: int):
    story = get_object_or_404(Story, id=story_id)
    room = story.room
    participant = current_participant(request, room)
    if not participant:
        return redirect("poker:join_room", code=room.code)
    if request.method != "POST":
        return HttpResponseBadRequest("POST only")

    value = request.POST.get("value")
    if value is None:
        return HttpResponseBadRequest("Missing value")

    Vote.objects.update_or_create(story=story, participant=participant, defaults={"value": value})

    if _is_htmx(request):
        return _render_story(request, story)

    return redirect("poker:room_detail", code=room.code)


def reveal_votes(request, pk: int):
    story = get_object_or_404(Story, pk=pk)
    participant = current_participant(request, story.room)
    if request.method != "POST":
        return HttpResponseBadRequest("POST only")
    if not facilitator_required(participant):
        return HttpResponseForbidden("Facilitator only")

    story.revealed = True
    story.save(update_fields=["revealed"])

    if _is_htmx(request):
        return _render_story(request, story)

    return redirect("poker:room_detail", code=story.room.code)


def revote_story(request, pk: int):
    story = get_object_or_404(Story, pk=pk)
    participant = current_participant(request, story.room)
    if request.method != "POST":
        return HttpResponseBadRequest("POST only")
    if not facilitator_required(participant):
        return HttpResponseForbidden("Facilitator only")

    story.revealed = False
    story.consensus_value = ""
    story.save(update_fields=["revealed", "consensus_value"])
    story.votes.all().delete()

    if _is_htmx(request):
        return _render_story(request, story)

    return redirect("poker:room_detail", code=story.room.code)


def set_consensus(request, pk: int):
    story = get_object_or_404(Story, pk=pk)
    participant = current_participant(request, story.room)
    if request.method != "POST":
        return HttpResponseBadRequest("POST only")
    if not facilitator_required(participant):
        return HttpResponseForbidden("Facilitator only")

    story.consensus_value = request.POST.get("consensus", "")
    story.save(update_fields=["consensus_value"])

    if _is_htmx(request):
        return _render_story(request, story)

    return redirect("poker:room_detail", code=story.room.code)


def delete_story(request, story_id: int):
    story = get_object_or_404(Story, id=story_id)
    participant = current_participant(request, story.room)
    if request.method != "POST":
        return HttpResponseBadRequest("POST only")
    if not facilitator_required(participant):
        return HttpResponseForbidden("Facilitator only")

    room = story.room
    story.delete()

    # For HTMX: refresh stories panel (keeps scroll position; list shrinks gracefully)
    if _is_htmx(request):
        ctx = _room_context(request, room)
        return render(request, "poker/partials/_stories.html", ctx)

    return redirect("poker:room_detail", code=room.code)


def delete_room(request, code: str):
    room = get_object_or_404(Room, code=code)
    participant = current_participant(request, room)
    if request.method != "POST":
        return HttpResponseBadRequest("POST only")
    if not facilitator_required(participant):
        return HttpResponseForbidden("Facilitator only")
    room.delete()
    return redirect("poker:room_list")


# ======================= auto-update partial endpoints =====================

@require_GET
def room_stories_partial(request, code: str):
    room = get_object_or_404(Room, code=code)
    ctx = _room_context(request, room)
    return render(request, "poker/partials/_stories.html", ctx)


@require_GET
def room_sidebar_partial(request, code: str):
    room = get_object_or_404(Room, code=code)
    ctx = _room_context(request, room)
    return render(request, "poker/partials/_sidebar.html", ctx)


# ============================== Jira integration ===========================

def _jira_auth(room: Room) -> HTTPBasicAuth | None:
    if not (room.jira_base_url and room.jira_email and room.jira_token):
        return None
    return HTTPBasicAuth(room.jira_email, room.jira_token)


def _jira_get_board_id(room: Room) -> int | None:
    """
    Prefer a board whose location.projectKey == room.jira_project_key.
    Fall back to first matching board.
    """
    if room.jira_board_id:
        return room.jira_board_id

    auth = _jira_auth(room)
    if not auth or not room.jira_project_key:
        return None

    url = f"{room.jira_base_url}/rest/agile/1.0/board"
    boards: list[dict] = []
    start_at = 0
    while True:
        r = requests.get(
            url,
            auth=auth,
            params={"projectKeyOrId": room.jira_project_key, "startAt": start_at, "maxResults": 50},
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()
        boards.extend(data.get("values", []))
        if start_at + data.get("maxResults", 0) >= data.get("total", 0):
            break
        start_at += data.get("maxResults", 0)

    if not boards:
        return None

    preferred = next((b for b in boards if (b.get("location") or {}).get("projectKey") == room.jira_project_key), None)
    board = preferred or boards[0]
    room.jira_board_id = board["id"]
    room.save(update_fields=["jira_board_id"])
    return room.jira_board_id


def _jira_next_sprint(room: Room, board_id: int) -> dict | None:
    auth = _jira_auth(room)
    if not auth:
        return None
    url = f"{room.jira_base_url}/rest/agile/1.0/board/{board_id}/sprint"
    r = requests.get(url, auth=auth, params={"state": "future"}, timeout=15)
    r.raise_for_status()
    values = r.json().get("values", [])
    if not values:
        return None
    values.sort(key=lambda s: s.get("startDate") or "9999-12-31")
    return values[0]


def _jira_issues_in_sprint_for_project(room: Room, sprint_id: int) -> list[tuple[str, str, str]]:
    """Return [(KEY, summary, browse_url)] filtered to room.jira_project_key."""
    auth = _jira_auth(room)
    if not auth:
        return []

    # Preferred: JQL (REST v3)
    try:
        search_url = f"{room.jira_base_url}/rest/api/3/search"
        jql = f'project = "{room.jira_project_key}" AND sprint = {sprint_id}'
        out: list[tuple[str, str, str]] = []

        def page(start_at: int):
            r = requests.get(
                search_url,
                auth=auth,
                params={"jql": jql, "fields": "summary", "startAt": start_at, "maxResults": 100},
                timeout=20,
            )
            r.raise_for_status()
            return r.json()

        data = page(0)
        total = data.get("total", 0)
        start_at = data.get("startAt", 0)
        max_results = data.get("maxResults", 100)

        for issue in data.get("issues", []):
            key = issue.get("key", "")
            fields = issue.get("fields", {}) or {}
            summary = fields.get("summary", "")
            browse = f"{room.jira_base_url}/browse/{key}" if key else ""
            out.append((key, summary, browse))

        while start_at + max_results < total:
            start_at += max_results
            data = page(start_at)
            for issue in data.get("issues", []):
                key = issue.get("key", "")
                summary = (issue.get("fields", {}) or {}).get("summary", "")
                browse = f"{room.jira_base_url}/browse/{key}" if key else ""
                out.append((key, summary, browse))

        return out

    except requests.HTTPError:
        pass  # fall back to Agile endpoint

    # Fallback: Agile sprint issues (may include multiple projects) -> filter client-side
    issues_url = f"{room.jira_base_url}/rest/agile/1.0/sprint/{sprint_id}/issue"
    filtered: list[tuple[str, str, str]] = []
    start = 0
    step = 50
    while True:
        r = requests.get(issues_url, auth=auth, params={"startAt": start, "maxResults": step}, timeout=20)
        r.raise_for_status()
        data = r.json()
        for it in data.get("issues", []):
            fields = it.get("fields", {}) or {}
            project_key = (fields.get("project") or {}).get("key")
            if project_key == room.jira_project_key:
                key = it.get("key", "")
                summary = fields.get("summary", "")
                browse = f"{room.jira_base_url}/browse/{key}" if key else ""
                filtered.append((key, summary, browse))
        if start + data.get("maxResults", 0) >= data.get("total", 0):
            break
        start += data.get("maxResults", 0)
    return filtered


def jira_settings(request, code: str):
    room = get_object_or_404(Room, code=code)
    participant = current_participant(request, room)
    if not facilitator_required(participant):
        return HttpResponseForbidden("Facilitator only")
    if request.method == "POST":
        form = JiraSettingsForm(request.POST, instance=room)
        if form.is_valid():
            form.save()
            messages.success(request, "Jira settings saved.")
            return redirect("poker:room_detail", code=room.code)
    else:
        form = JiraSettingsForm(instance=room)
    return render(request, "poker/jira_settings.html", {"room": room, "form": form, "participant": participant})


@require_POST
def jira_import_next_sprint(request, code: str):
    room = get_object_or_404(Room, code=code)
    participant = current_participant(request, room)
    if not facilitator_required(participant):
        return HttpResponseForbidden("Facilitator only")

    if not (room.jira_base_url and room.jira_email and room.jira_token and room.jira_project_key):
        messages.error(request, "Fill Jira settings first (base URL, email, API token, project key).")
        return redirect("poker:room_detail", code=room.code)

    try:
        board_id = _jira_get_board_id(room)
        if not board_id:
            messages.error(request, "Could not determine a board; set Board ID in Jira settings.")
            return redirect("poker:room_detail", code=room.code)

        sprint = _jira_next_sprint(room, board_id)
        if not sprint:
            messages.info(request, "No upcoming sprint found.")
            return redirect("poker:room_detail", code=room.code)

        issues = _jira_issues_in_sprint_for_project(room, sprint["id"])
        created = 0
        existing_titles = set(room.stories.values_list("title", flat=True))
        for key, summary, browse_url in issues:
            title = f"{key} — {summary}"[:200]
            if title in existing_titles:
                continue
            Story.objects.create(room=room, title=title, notes=f"Issue: {key}\n{browse_url}")
            created += 1

        if created:
            messages.success(request, f"Imported {created} issue(s) for {room.jira_project_key}.")
        else:
            messages.info(request, f"No new {room.jira_project_key} issues to import.")

    except requests.HTTPError as e:
        messages.error(request, f"Jira API error: {e.response.status_code} {e.response.text[:200]}")
    except Exception as e:
        messages.error(request, f"Import failed: {e}")

    return redirect("poker:room_detail", code=room.code)
