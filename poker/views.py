# poker/views.py
from __future__ import annotations

import random
from datetime import timedelta
from urllib.parse import quote

import requests
from requests.auth import HTTPBasicAuth

from django.conf import settings
from django.contrib import messages
from django.core.cache import cache
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_POST

from .cache_utils import (
    ROOM_LIST_CACHE_KEY,
    ROOM_PARTIAL_TTL,
    get_room_snapshot,
    invalidate_room_cache,
    invalidate_room_list,
    room_fragment_cache_key,
)
from .emails import send_org_access_token
from .forms import (
    JiraSettingsForm,
    JoinForm,
    OrgAccessForm,
    RoomForm,
    RoomRenameForm,
    StoryForm,
)
from .models import CARD_SETS, Participant, Room, Story, Vote
from .turnstile import is_configured as turnstile_configured, verify_turnstile


# ============================== helpers ====================================

TOKEN_SESSION_KEY = "org_pending_token"
OTP_RATE_LIMIT = 3
OTP_RATE_WINDOW_SECONDS = 60


def _next_or_home(request):
    candidate = request.POST.get("next") or request.GET.get("next")
    if candidate and url_has_allowed_host_and_scheme(candidate, allowed_hosts={request.get_host()}):
        return candidate
    return reverse("poker:room_list")


def _requested_next(request) -> str:
    candidate = request.POST.get("next") or request.GET.get("next")
    if candidate and url_has_allowed_host_and_scheme(candidate, allowed_hosts={request.get_host()}):
        return candidate
    return ""


def _generate_access_token() -> str:
    return f"{random.randint(0, 999999):06d}"


def _set_pending_token(request, email: str, token: str):
    expires_at = (timezone.now() + timedelta(seconds=settings.ORG_ACCESS_TOKEN_TTL_SECONDS)).timestamp()
    request.session[TOKEN_SESSION_KEY] = {"email": email, "token": token, "expires_at": expires_at}


def _otp_rate_limited(email: str) -> bool:
    key = f"otp:rate:{email.lower()}"
    count = cache.get(key)
    if count is None:
        cache.set(key, 1, timeout=OTP_RATE_WINDOW_SECONDS)
        return False
    if count >= OTP_RATE_LIMIT:
        return True
    cache.incr(key)
    return False


def _get_pending_token(request):
    data = request.session.get(TOKEN_SESSION_KEY)
    if not data:
        return None
    expires_at = data.get("expires_at", 0)
    if timezone.now().timestamp() > expires_at:
        request.session.pop(TOKEN_SESSION_KEY, None)
        return None
    return data


def _clear_pending_token(request):
    request.session.pop(TOKEN_SESSION_KEY, None)


def _org_login_redirect(next_url: str | None = None):
    url = reverse("poker:org_login")
    if next_url:
        url = f"{url}?next={quote(next_url)}"
    return redirect(url)


def _turnstile_valid(request) -> bool:
    if not turnstile_configured():
        return True
    token = request.POST.get("cf-turnstile-response")
    if verify_turnstile(token, request.META.get("REMOTE_ADDR")):
        return True
    messages.error(request, "Please complete the verification challenge.")
    return False


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


def _room_context(
    request,
    room: Room,
    snapshot: dict | None = None,
    version: int | None = None,
    participant: Participant | None = None,
) -> dict:
    """Build the same context used across full and partial renders."""
    participant = participant or current_participant(request, room)
    if snapshot is None or version is None:
        snapshot, version = get_room_snapshot(room)

    stories = snapshot["stories"]
    cards = snapshot["cards"]
    user_is_staff = request.user.is_authenticated and request.user.is_staff
    participant_is_facilitator = bool(participant and participant.is_facilitator)
    can_manage = bool(participant_is_facilitator or user_is_staff)
    staff_can_delete = bool(user_is_staff and not participant_is_facilitator)

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
        "participant_is_facilitator": participant_is_facilitator,
        "stories": stories,
        "cards": cards,
        "story_form": StoryForm(),
        "can_manage_room": can_manage,
        "staff_can_delete": staff_can_delete,
        "cache_version": version,
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
        {
            "room": room,
            "participant": p,
            "participant_is_facilitator": ctx["participant_is_facilitator"],
            "cards": ctx["cards"],
            "s": s,
        },
    )


# ============================== core views =================================

def room_list(request):
    rooms = cache.get(ROOM_LIST_CACHE_KEY)
    if rooms is None:
        rooms = list(Room.objects.order_by("-created_at")[:50])
        cache.set(ROOM_LIST_CACHE_KEY, rooms, 30)
    form = RoomForm()
    if request.method == "POST":
        form = RoomForm(request.POST)
        if form.is_valid():
            room = form.save()
            invalidate_room_list()
            return redirect("poker:room_detail", code=room.code)
    return render(request, "poker/room_list.html", {"rooms": rooms, "form": form})


def room_create(request):
    if request.method != "POST":
        messages.info(request, "Use the form below to create a room.")
        return redirect("poker:room_list")

    form = RoomForm(request.POST)
    if form.is_valid():
        room = form.save()
        invalidate_room_list()
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
            invalidate_room_cache(room)
            return redirect("poker:room_detail", code=room.code)
    else:
        form = JoinForm()
    return render(request, "poker/join_room.html", {"room": room, "form": form})


def room_detail(request, code: str):
    room = get_object_or_404(Room, code=code)
    ctx = _room_context(request, room)
    ctx["rename_form"] = RoomRenameForm(instance=room)
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
            invalidate_room_cache(room)

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
    invalidate_room_cache(room)

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
    invalidate_room_cache(story.room)

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
    invalidate_room_cache(story.room)

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
    invalidate_room_cache(story.room)

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
    invalidate_room_cache(room)

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
    user_is_admin = request.user.is_authenticated and request.user.is_staff
    if not (facilitator_required(participant) or user_is_admin):
        return HttpResponseForbidden("Facilitator or staff only")
    room.delete()
    invalidate_room_list()
    return redirect("poker:room_list")


@require_POST
def leave_room(request, code: str):
    room = get_object_or_404(Room, code=code)
    participant = current_participant(request, room)
    request.session.pop(f"p_{room.code}", None)
    if participant:
        participant.delete()
        messages.info(request, "You have left the room.")
        invalidate_room_cache(room)
    return redirect("poker:room_detail", code=room.code)


@require_POST
def rename_room(request, code: str):
    room = get_object_or_404(Room, code=code)
    participant = current_participant(request, room)
    user_is_admin = request.user.is_authenticated and request.user.is_staff
    if not (facilitator_required(participant) or user_is_admin):
        return HttpResponseForbidden("Facilitator or staff only")

    form = RoomRenameForm(request.POST, instance=room)
    if form.is_valid():
        form.save()
        invalidate_room_cache(room)
        invalidate_room_list()
        messages.success(request, "Room renamed.")
    else:
        for error in form.errors.get("name", []):
            messages.error(request, error)

    return redirect("poker:room_detail", code=room.code)


def org_login(request):
    if request.session.get("org_email"):
        return redirect(_next_or_home(request))

    if request.GET.get("reset_token") == "1":
        _clear_pending_token(request)

    pending = _get_pending_token(request)
    token_required = bool(pending)
    initial = {"email": pending["email"]} if pending else None
    form = OrgAccessForm(request.POST or None, token_required=token_required, initial=initial)

    if request.method == "POST":
        action = request.POST.get("action")
        turnstile_ok = _turnstile_valid(request)
        if turnstile_ok and token_required and action == "resend" and pending:
            if _otp_rate_limited(pending["email"]):
                messages.error(request, "Too many verification attempts. Please wait a minute.")
                return _org_login_redirect(_requested_next(request))
            new_token = _generate_access_token()
            sent = send_org_access_token(pending["email"], new_token)
            if sent or settings.DEBUG:
                _set_pending_token(request, pending["email"], new_token)
                if settings.DEBUG:
                    messages.info(request, f"[dev] Verification code: {new_token}")
                messages.info(request, f"We sent a new code to {pending['email']}.")
            else:
                messages.error(request, "We could not send the code. Contact an administrator.")
            return _org_login_redirect(_requested_next(request))

        if turnstile_ok and form.is_valid():
            if token_required and pending:
                if form.cleaned_data["email"] != pending["email"]:
                    form.add_error("email", "Use the same email address that requested the code.")
                elif form.cleaned_data["token"] != pending["token"]:
                    form.add_error("token", "That code is incorrect or has expired.")
                else:
                    _clear_pending_token(request)
                    request.session["org_email"] = pending["email"]
                    messages.success(request, "Access granted. Welcome to planning mode!")
                    return redirect(_next_or_home(request))
            else:
                email = form.cleaned_data["email"]
                if _otp_rate_limited(email):
                    form.add_error(None, "Too many verification attempts. Please wait a minute.")
                    return render(
                        request,
                        "poker/org_login.html",
                        {
                            "form": form,
                            "allowed_domain": settings.ORG_ALLOWED_EMAIL_DOMAIN,
                            "token_required": token_required,
                            "pending_email": pending["email"] if pending else "",
                            "token_expires_in": settings.ORG_ACCESS_TOKEN_TTL_SECONDS,
                            "token_expires_minutes": max(settings.ORG_ACCESS_TOKEN_TTL_SECONDS // 60, 1),
                            "next_param": _requested_next(request),
                            "turnstile_enabled": turnstile_configured(),
                        },
                    )
                token = _generate_access_token()
                sent = send_org_access_token(email, token)
                if sent or settings.DEBUG:
                    _set_pending_token(request, email, token)
                    if settings.DEBUG:
                        messages.info(request, f"[dev] Verification code: {token}")
                    messages.info(request, f"We sent a 6-digit code to {email}.")
                    return _org_login_redirect(_requested_next(request))
                form.add_error(None, "We could not send the verification code. Contact an administrator.")

    context = {
        "form": form,
        "allowed_domain": settings.ORG_ALLOWED_EMAIL_DOMAIN,
        "token_required": token_required,
        "pending_email": pending["email"] if pending else "",
        "token_expires_in": settings.ORG_ACCESS_TOKEN_TTL_SECONDS,
        "token_expires_minutes": max(settings.ORG_ACCESS_TOKEN_TTL_SECONDS // 60, 1),
        "next_param": _requested_next(request),
        "turnstile_enabled": turnstile_configured(),
    }
    return render(request, "poker/org_login.html", context)


@require_POST
def org_logout(request):
    for key in list(request.session.keys()):
        if key.startswith("p_"):
            request.session.pop(key, None)
    request.session.pop("org_email", None)
    _clear_pending_token(request)
    messages.info(request, "Signed out. See you soon!")
    return redirect("poker:org_login")


# ======================= auto-update partial endpoints =====================

@require_GET
def room_stories_partial(request, code: str):
    room = get_object_or_404(Room, code=code)
    participant = current_participant(request, room)
    snapshot, version = get_room_snapshot(room)
    participant_id = participant.id if participant else "anon"
    cache_key = room_fragment_cache_key(room.id, "stories", version, participant_id)
    html = cache.get(cache_key)
    if html is None:
        ctx = _room_context(request, room, snapshot=snapshot, version=version, participant=participant)
        html = render_to_string("poker/partials/_stories.html", ctx, request=request)
        cache.set(cache_key, html, ROOM_PARTIAL_TTL)
    return HttpResponse(html)


@require_GET
def room_sidebar_partial(request, code: str):
    room = get_object_or_404(Room, code=code)
    participant = current_participant(request, room)
    snapshot, version = get_room_snapshot(room)
    participant_id = participant.id if participant else "anon"
    cache_key = room_fragment_cache_key(room.id, "sidebar", version, participant_id)
    html = cache.get(cache_key)
    if html is None:
        ctx = _room_context(request, room, snapshot=snapshot, version=version, participant=participant)
        html = render_to_string("poker/partials/_sidebar.html", ctx, request=request)
        cache.set(cache_key, html, ROOM_PARTIAL_TTL)
    return HttpResponse(html)


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

    # Prefer sprints created for this board. Jira may return cross-board sprints
    # (different originBoardId) when they’re shared.
    scoped = [s for s in values if s.get("originBoardId") == board_id]
    candidates = scoped or values

    def sort_key(s: dict):
        # Use startDate if provided, otherwise createdDate to keep chronology stable.
        return s.get("startDate") or s.get("createdDate") or "9999-12-31"

    candidates.sort(key=sort_key)
    return candidates[0]


def _is_epic(issue_type: str | None) -> bool:
    return (issue_type or "").strip().lower() == "epic"


def _jira_issues_in_sprint_for_project(room: Room, sprint_id: int) -> list[tuple[str, str, str, str]]:
    """Return [(KEY, summary, browse_url, issue_type)] filtered to room.jira_project_key."""
    auth = _jira_auth(room)
    if not auth:
        return []

    # Preferred: JQL (REST v3)
    try:
        search_url = f"{room.jira_base_url}/rest/api/3/search"
        jql = f'project = "{room.jira_project_key}" AND sprint = {sprint_id}'
        out: list[tuple[str, str, str, str]] = []

        def page(start_at: int):
            r = requests.get(
                search_url,
                auth=auth,
                params={"jql": jql, "fields": "summary,issuetype", "startAt": start_at, "maxResults": 100},
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
            issue_type = (fields.get("issuetype") or {}).get("name", "")
            if _is_epic(issue_type):
                continue
            out.append((key, summary, browse, issue_type))

        while start_at + max_results < total:
            start_at += max_results
            data = page(start_at)
            for issue in data.get("issues", []):
                key = issue.get("key", "")
                fields = issue.get("fields", {}) or {}
                summary = fields.get("summary", "")
                browse = f"{room.jira_base_url}/browse/{key}" if key else ""
                issue_type = (fields.get("issuetype") or {}).get("name", "")
                if _is_epic(issue_type):
                    continue
                out.append((key, summary, browse, issue_type))

        return out

    except requests.HTTPError:
        pass  # fall back to Agile endpoint

    # Fallback: Agile sprint issues (may include multiple projects) -> filter client-side
    issues_url = f"{room.jira_base_url}/rest/agile/1.0/sprint/{sprint_id}/issue"
    filtered: list[tuple[str, str, str, str]] = []
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
                issue_type = (fields.get("issuetype") or {}).get("name", "")
                if _is_epic(issue_type):
                    continue
                filtered.append((key, summary, browse, issue_type))
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
        for key, summary, browse_url, issue_type in issues:
            title = f"{key} — {summary}"[:200]
            if title in existing_titles:
                continue
            Story.objects.create(
                room=room,
                title=title,
                notes=f"Issue: {key}\n{browse_url}",
                jira_issue_type=issue_type or "",
            )
            created += 1

        if created:
            invalidate_room_cache(room)
            messages.success(request, f"Imported {created} issue(s) for {room.jira_project_key}.")
        else:
            messages.info(request, f"No new {room.jira_project_key} issues to import.")

    except requests.HTTPError as e:
        messages.error(request, f"Jira API error: {e.response.status_code} {e.response.text[:200]}")
    except Exception as e:
        messages.error(request, f"Import failed: {e}")

    return redirect("poker:room_detail", code=room.code)
