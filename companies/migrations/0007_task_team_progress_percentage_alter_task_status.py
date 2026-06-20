from django.db import migrations, models
import django.db.models.deletion


def migrate_pending_to_in_progress(apps, schema_editor):
    Task = apps.get_model('companies', 'Task')
    Task.objects.filter(status='pending').update(status='in_progress')


class Migration(migrations.Migration):

    dependencies = [
        ('companies', '0006_alter_team_members'),
    ]

    operations = [
        migrations.AddField(
            model_name='task',
            name='progress_percentage',
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='task',
            name='team',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='tasks',
                to='companies.team',
            ),
        ),
        migrations.RunPython(migrate_pending_to_in_progress, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='task',
            name='status',
            field=models.CharField(
                choices=[('in_progress', 'In Progress'), ('completed', 'Completed')],
                default='in_progress',
                max_length=20,
            ),
        ),
    ]
