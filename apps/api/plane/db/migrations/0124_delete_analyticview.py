# Generated manually to remove the unused AnalyticView model (in-app Analytics
# dashboard feature removal)

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("db", "0123_webpushsubscription_usernotificationpreference_browser_push"),
    ]

    operations = [
        migrations.DeleteModel(
            name="AnalyticView",
        ),
    ]
