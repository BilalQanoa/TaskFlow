from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def migrate_completed_to_done(apps, schema_editor):
    Task = apps.get_model('companies', 'Task')
    Task.objects.filter(status='completed').update(status='done')


class Migration(migrations.Migration):

    dependencies = [
        ('companies', '0008_teammessage'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='task',
            name='assigned_to',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='assigned_tasks',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name='task',
            name='parent_task',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='subtasks',
                to='companies.task',
            ),
        ),
        migrations.AddField(
            model_name='task',
            name='review_notice',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='task',
            name='updated_at',
            field=models.DateTimeField(auto_now=True),
        ),
        migrations.AlterField(
            model_name='task',
            name='status',
            field=models.CharField(
                choices=[
                    ('todo', 'To Do'),
                    ('in_progress', 'In Progress'),
                    ('under_review', 'Under Review'),
                    ('done', 'Done'),
                ],
                default='todo',
                max_length=20,
            ),
        ),
        migrations.RunPython(migrate_completed_to_done, migrations.RunPython.noop),
    ]
