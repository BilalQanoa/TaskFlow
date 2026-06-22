from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('companies', '0007_task_team_progress_percentage_alter_task_status'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='TeamMessage',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('message_text', models.TextField()),
                ('timestamp', models.DateTimeField(auto_now_add=True)),
                ('sender', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='team_messages', to=settings.AUTH_USER_MODEL)),
                ('team', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='messages', to='companies.team')),
            ],
            options={
                'ordering': ['timestamp'],
            },
        ),
    ]
