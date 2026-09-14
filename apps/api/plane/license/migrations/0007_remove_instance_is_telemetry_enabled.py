# Removes anonymous usage-metrics telemetry (previously pushed to
# telemetry.plane.so via OTLP by plane.license.bgtasks.telemetry_metrics,
# which this drops entirely, along with its admin setup/settings toggle).

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("license", "0006_instance_is_current_version_deprecated"),
    ]

    operations = [
        migrations.RemoveField(model_name="instance", name="is_telemetry_enabled")
    ]
