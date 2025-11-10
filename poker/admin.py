from django.contrib import admin

from .forms import TurnstileAdminAuthenticationForm
from .models import Participant, Room, Story, Vote

admin.site.register(Room)
admin.site.register(Participant)
admin.site.register(Story)
admin.site.register(Vote)

admin.site.login_form = TurnstileAdminAuthenticationForm
