from django.urls import path
from . import views

app_name = "poker"

urlpatterns = [
    path("", views.room_list, name="room_list"),
    path("room/new", views.room_create, name="room_create"),
    path("room/<str:code>", views.room_detail, name="room_detail"),
    path("room/<str:code>/join", views.join_room, name="join_room"),
    path("room/<str:code>/story/new", views.story_create, name="story_create"),

    path("story/<int:story_id>/vote", views.cast_vote, name="cast_vote"),
    path("story/<int:pk>/reveal", views.reveal_votes, name="reveal_votes"),
    path("story/<int:pk>/revote", views.revote_story, name="revote_story"),
    path("story/<int:pk>/consensus", views.set_consensus, name="set_consensus"),
    path("story/<int:story_id>/delete", views.delete_story, name="delete_story"),

    path("room/<str:code>/delete", views.delete_room, name="delete_room"),
    path("room/<str:code>/leave", views.leave_room, name="leave_room"),
    path("auth/login", views.org_login, name="org_login"),
    path("auth/logout", views.org_logout, name="org_logout"),

    # Auto-update partials
    path("room/<str:code>/poll/stories", views.room_stories_partial, name="room_stories_partial"),
    path("room/<str:code>/poll/sidebar", views.room_sidebar_partial, name="room_sidebar_partial"),

    # Jira
    path("room/<str:code>/jira/settings", views.jira_settings, name="jira_settings"),
    path("room/<str:code>/jira/import-next-sprint", views.jira_import_next_sprint, name="jira_import_next_sprint"),
]
