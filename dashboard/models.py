from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

from accounts.models import User as BaseUser
from companies.models import Task as BaseTask, Team as BaseTeam, TeamMessage as BaseTeamMessage
from companies.models import KanbanCard as BaseKanbanCard, TaskChecklistItem as BaseTaskChecklistItem


class OTPVerification(models.Model):
    PURPOSE_CHOICES = [
        ('signup', 'Sign Up Verification'),
        ('login', 'Two-Factor Login'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='otp_verifications',
    )
    otp_code = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    purpose = models.CharField(max_length=10, choices=PURPOSE_CHOICES)

    class Meta:
        ordering = ['-created_at']

    def is_valid(self):
        expiry = self.created_at + timedelta(minutes=5)
        return timezone.now() <= expiry

    def __str__(self):
        return f'{self.user_id} · {self.purpose} · {self.otp_code}'


class User(BaseUser):
    class Meta:
        proxy = True
        verbose_name = 'Employee'
        verbose_name_plural = 'Employees'


class Task(BaseTask):
    class Meta:
        proxy = True
        verbose_name = 'Task'
        verbose_name_plural = 'Tasks'
        ordering = ['due_date', 'created_at']


class Team(BaseTeam):
    class Meta:
        proxy = True
        ordering = ['-created_at']
        verbose_name = 'Team'
        verbose_name_plural = 'Teams'


class TeamMessage(BaseTeamMessage):
    class Meta:
        proxy = True
        ordering = ['timestamp']
        verbose_name = 'Team Message'
        verbose_name_plural = 'Team Messages'


class KanbanCard(BaseKanbanCard):
    class Meta:
        proxy = True
        verbose_name = 'Kanban Card'
        verbose_name_plural = 'Kanban Cards'


class TaskChecklistItem(BaseTaskChecklistItem):
    class Meta:
        proxy = True
        verbose_name = 'Checklist Item'
        verbose_name_plural = 'Checklist Items'
