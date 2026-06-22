from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('companies', '0009_task_hierarchy_leader_workflow'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='KanbanCard',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=255)),
                ('description', models.TextField(blank=True)),
                ('status', models.CharField(
                    choices=[
                        ('todo', 'To Do'),
                        ('in_progress', 'In Progress'),
                        ('under_review', 'Under Review'),
                        ('done', 'Done'),
                    ],
                    default='todo',
                    max_length=20,
                )),
                ('review_notice', models.TextField(blank=True, default='')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('assigned_to', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='kanban_cards',
                    to=settings.AUTH_USER_MODEL,
                )),
                ('main_task', models.ForeignKey(
                    limit_choices_to={'parent_task__isnull': True},
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='kanban_cards',
                    to='companies.task',
                )),
            ],
            options={
                'ordering': ['-updated_at', 'title'],
            },
        ),
        migrations.CreateModel(
            name='TaskChecklistItem',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=255)),
                ('is_completed', models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('card', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='checklists',
                    to='companies.kanbancard',
                )),
            ],
            options={
                'ordering': ['created_at', 'pk'],
            },
        ),
    ]
