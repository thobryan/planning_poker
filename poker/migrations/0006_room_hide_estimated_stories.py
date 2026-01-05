from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("poker", "0005_room_jira_token_encrypted"),
    ]

    operations = [
        migrations.AddField(
            model_name="room",
            name="hide_estimated_stories",
            field=models.BooleanField(default=False),
        ),
    ]
