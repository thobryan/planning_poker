from django import forms
from django.conf import settings
from django.contrib.admin.forms import AdminAuthenticationForm

from .models import CARD_SETS, Room, Story
from .turnstile import is_configured as turnstile_configured, verify_turnstile

INPUT_BASE = (
    "w-full rounded-2xl border border-slate-300/70 bg-white/80 px-4 py-2.5 text-sm text-slate-900 "
    "placeholder:text-slate-500 shadow-sm focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand/30 transition"
)


CARD_SET_CHOICES = [
    (key, f"{key.replace('_', ' ').title()} – {', '.join(values)}")
    for key, values in CARD_SETS.items()
]


class RoomForm(forms.ModelForm):
    card_set = forms.ChoiceField(
        choices=CARD_SET_CHOICES,
        widget=forms.Select(attrs={"class": INPUT_BASE}),
        label="Card set",
    )

    class Meta:
        model = Room
        fields = ["name", "card_set"]
        widgets = {
            "name": forms.TextInput(attrs={"class": INPUT_BASE, "placeholder": "Squad Alpha – Sprint 42"}),
        }


class JoinForm(forms.Form):
    display_name = forms.CharField(
        max_length=60,
        widget=forms.TextInput(attrs={"class": INPUT_BASE, "placeholder": "Sam – Design Lead"}),
        label="Display name",
    )
    is_facilitator = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={"class": "size-4 rounded border-slate-300 text-brand focus:ring-brand"}),
        label="I'm facilitating this session",
    )


class StoryForm(forms.ModelForm):
    class Meta:
        model = Story
        fields = ["title", "notes"]
        widgets = {
            "title": forms.TextInput(attrs={"class": INPUT_BASE, "placeholder": "Checkout flow regression"}),
            "notes": forms.Textarea(
                attrs={
                    "class": INPUT_BASE,
                    "rows": 3,
                    "placeholder": "Acceptance criteria, Jira link, context…",
                }
            ),
        }
        labels = {"title": "Title", "notes": "Notes"}


class JiraSettingsForm(forms.ModelForm):
    class Meta:
        model = Room
        fields = ["jira_base_url", "jira_email", "jira_token", "jira_project_key", "jira_board_id"]
        widgets = {
            "jira_base_url": forms.URLInput(attrs={"class": INPUT_BASE}),
            "jira_email": forms.EmailInput(attrs={"class": INPUT_BASE}),
            "jira_token": forms.PasswordInput(render_value=True, attrs={"class": INPUT_BASE}),
            "jira_project_key": forms.TextInput(attrs={"class": INPUT_BASE}),
            "jira_board_id": forms.NumberInput(attrs={"class": INPUT_BASE}),
        }
        help_texts = {
            "jira_token": "Jira API token (Atlassian account → Security → Create token).",
            "jira_board_id": "Optional: if empty, we'll try to detect a Scrum board for the project.",
        }


class OrgAccessForm(forms.Form):
    email = forms.EmailField(
        widget=forms.EmailInput(
            attrs={
                "class": INPUT_BASE,
                "placeholder": "you@welltech.com",
                "autocomplete": "email",
            }
        ),
        label="Work email",
    )
    token = forms.CharField(
        max_length=6,
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": INPUT_BASE,
                "placeholder": "Enter the 6-digit token",
                "inputmode": "numeric",
                "autocomplete": "one-time-code",
            }
        ),
        label="Verification code",
    )

    def __init__(self, *args, token_required: bool = False, **kwargs):
        super().__init__(*args, **kwargs)
        self.token_required = token_required
        if token_required:
            self.fields["token"].required = True
            self.fields["email"].widget.attrs["readonly"] = True

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        domain = getattr(settings, "ORG_ALLOWED_EMAIL_DOMAIN", "").lower()
        if domain and not email.endswith(f"@{domain}"):
            raise forms.ValidationError(f"Please use your {domain} email address.")
        return email

    def clean_token(self):
        token = self.cleaned_data.get("token", "").strip()
        if self.token_required and not token:
            raise forms.ValidationError("Enter the verification code.")
        if token and not token.isdigit():
            raise forms.ValidationError("The token must contain digits only.")
        if token and len(token) != 6:
            raise forms.ValidationError("The token must be 6 digits.")
        return token


class TurnstileAdminAuthenticationForm(AdminAuthenticationForm):
    error_messages = {
        **AdminAuthenticationForm.error_messages,
        "turnstile": "Please complete the verification challenge.",
    }

    def clean(self):
        cleaned_data = super().clean()
        if turnstile_configured():
            token = self.data.get("cf-turnstile-response")
            if not verify_turnstile(token, getattr(self.request, "META", {}).get("REMOTE_ADDR")):
                raise forms.ValidationError(self.error_messages["turnstile"], code="turnstile")
        return cleaned_data
class RoomRenameForm(forms.ModelForm):
    class Meta:
        model = Room
        fields = ["name"]
        widgets = {
            "name": forms.TextInput(
                attrs={"class": INPUT_BASE, "placeholder": "New room name", "required": True}
            )
        }
        labels = {"name": "Room name"}
