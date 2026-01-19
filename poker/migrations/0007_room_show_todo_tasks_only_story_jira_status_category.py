from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("poker", "0006_room_hide_estimated_stories"),
    ]

    operations = [
        migrations.AddField(
            model_name="room",
            name="show_todo_tasks_only",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="story",
            name="jira_status_category",
            field=models.CharField(blank=True, max_length=20),
        ),
    ]
