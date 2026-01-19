from django.db import models
from django.utils.crypto import get_random_string

from .fields import EncryptedTextField
CARD_SETS = {
    "fibonacci": ["?", "☕", "0", "1", "2", "3", "5", "8", "13", "21", "34"],
    "tshirt": ["?", "XS", "S", "M", "L", "XL"],
}

class Room(models.Model):
    code = models.CharField(max_length=8, unique=True, editable=False)
    name = models.CharField(max_length=120)
    created_at = models.DateTimeField(auto_now_add=True)
    card_set = models.CharField(max_length=20, default="fibonacci")

    # --- Jira integration (MVP) ---
    jira_base_url = models.URLField(blank=True, help_text="e.g. https://your-domain.atlassian.net")
    jira_email = models.CharField(max_length=200, blank=True)
    jira_token = EncryptedTextField(blank=True)
    jira_project_key = models.CharField(max_length=32, blank=True)
    jira_board_id = models.IntegerField(null=True, blank=True)
    hide_estimated_stories = models.BooleanField(default=False)
    show_todo_tasks_only = models.BooleanField(default=False)

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = get_random_string(6).upper()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} ({self.code})"


class Participant(models.Model):
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name="participants")
    display_name = models.CharField(max_length=60)
    is_facilitator = models.BooleanField(default=False)
    joined_at = models.DateTimeField(auto_now_add=True)


class Story(models.Model):
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name="stories")
    title = models.CharField(max_length=200)
    notes = models.TextField(blank=True)
    jira_issue_type = models.CharField(max_length=50, blank=True)
    jira_estimate = models.CharField(max_length=20, blank=True)
    jira_status_category = models.CharField(max_length=20, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    revealed = models.BooleanField(default=False)
    consensus_value = models.CharField(max_length=10, blank=True)


class Vote(models.Model):
    story = models.ForeignKey(Story, on_delete=models.CASCADE, related_name="votes")
    participant = models.ForeignKey(Participant, on_delete=models.CASCADE, related_name="votes")
    value = models.CharField(max_length=10)

    class Meta:
        unique_together = ("story", "participant")
