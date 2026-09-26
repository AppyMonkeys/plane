# Jira-style priority: new work items default to "medium" instead of "none".
# Only the column default changes; existing rows keep their priority.

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("db", "0125_recreate_analyticview"),
    ]

    operations = [
        migrations.AlterField(
            model_name="issue",
            name="priority",
            field=models.CharField(
                choices=[
                    ("urgent", "Urgent"),
                    ("high", "High"),
                    ("medium", "Medium"),
                    ("low", "Low"),
                    ("none", "None"),
                ],
                default="medium",
                max_length=30,
                verbose_name="Issue Priority",
            ),
        ),
        migrations.AlterField(
            model_name="draftissue",
            name="priority",
            field=models.CharField(
                choices=[
                    ("urgent", "Urgent"),
                    ("high", "High"),
                    ("medium", "Medium"),
                    ("low", "Low"),
                    ("none", "None"),
                ],
                default="medium",
                max_length=30,
                verbose_name="Issue Priority",
            ),
        ),
    ]
