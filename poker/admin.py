from django.contrib import admin
from .models import Room, Participant, Story, Vote

admin.site.register(Room)
admin.site.register(Participant)
admin.site.register(Story)
admin.site.register(Vote)