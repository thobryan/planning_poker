from django import forms
from .models import Room, Story

class RoomForm(forms.ModelForm):
    class Meta:
        model = Room
        fields = ["name", "card_set"]

class JoinForm(forms.Form):
    display_name = forms.CharField(max_length=60)
    is_facilitator = forms.BooleanField(required=False)

class StoryForm(forms.ModelForm):
    class Meta:
        model = Story
        fields = ["title", "notes"]
        widgets = {
            "title": forms.TextInput(attrs={"class": "w-full border rounded px-3 py-2"}),
            "notes": forms.Textarea(attrs={"class": "w-full border rounded px-3 py-2", "rows": 3}),
        }
        labels = {"title": "Title", "notes": "Notes"}

class JiraSettingsForm(forms.ModelForm):
    class Meta:
        model = Room
        fields = ["jira_base_url", "jira_email", "jira_token", "jira_project_key", "jira_board_id"]
        widgets = {
            "jira_base_url": forms.URLInput(attrs={"class": "w-full border rounded px-3 py-2"}),
            "jira_email": forms.EmailInput(attrs={"class": "w-full border rounded px-3 py-2"}),
            "jira_token": forms.PasswordInput(render_value=True, attrs={"class": "w-full border rounded px-3 py-2"}),
            "jira_project_key": forms.TextInput(attrs={"class": "w-full border rounded px-3 py-2"}),
            "jira_board_id": forms.NumberInput(attrs={"class": "w-full border rounded px-3 py-2"}),
        }
        help_texts = {
            "jira_token": "Jira API token (Atlassian account → Security → Create token).",
            "jira_board_id": "Optional: if empty, we'll try to detect a Scrum board for the project.",
        }
