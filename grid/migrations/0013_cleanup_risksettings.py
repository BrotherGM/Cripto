from django.db import migrations

def cleanup_risksettings(apps, schema_editor):
    """Оставляет только одну RiskSettings запись."""
    RiskSettings = apps.get_model('grid', 'RiskSettings')
    all_rs = RiskSettings.objects.all()
    
    if all_rs.count() > 1:
        first = all_rs.first()
        to_delete = all_rs.exclude(pk=first.pk)
        to_delete.delete()

def reverse_cleanup(apps, schema_editor):
    pass

class Migration(migrations.Migration):
    dependencies = [
        ('grid', '0012_gridstrategy_leverage_alter_gridstrategy_td_mode'),
    ]

    operations = [
        migrations.RunPython(cleanup_risksettings, reverse_cleanup),
    ]
