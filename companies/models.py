from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from accounts.models import User


class Company(models.Model):
    owner = models.OneToOneField(
        'accounts.User',
        on_delete=models.CASCADE,
        related_name='owned_company'
    )
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    logo = models.ImageField(upload_to='company_logos/', null=True, blank=True)
    website = models.URLField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    address = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.name


class Team(models.Model):
    name = models.CharField(max_length=255)
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name='teams',
    )
    team_leader = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='led_teams',
    )
    members = models.ManyToManyField(
        User,
        through='TeamMembership',
        related_name='teams',
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()
        if self.team_leader and self.company_id and self.team_leader.company_id != self.company_id:
            raise ValidationError({'team_leader': 'The team leader must belong to the same company.'})

        invalid_members = []
        if self.pk:
            invalid_members = [
                membership.user
                for membership in self.memberships.all()
                if self.company_id and membership.user.company_id != self.company_id
            ]
        if invalid_members:
            invalid_names = ', '.join([member.get_full_name() or member.username for member in invalid_members])
            raise ValidationError({'members': f'The following members must belong to the same company as the team: {invalid_names}.'})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class TeamMembership(models.Model):
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='memberships')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='team_memberships')
    role = models.CharField(max_length=120, blank=True, default='Member')
    joined_at = models.DateTimeField(default=timezone.now)

    class Meta:
        unique_together = ('team', 'user')
        ordering = ['joined_at', 'user__first_name', 'user__last_name']

    def __str__(self):
        return f'{self.user} — {self.role or "Member"} @ {self.team}'


class Task(models.Model):
    STATUS_CHOICES = [
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
    ]
    PRIORITY_CHOICES = [
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
    ]

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='tasks')
    team = models.ForeignKey(
        Team,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='tasks',
    )
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='in_progress')
    progress_percentage = models.PositiveSmallIntegerField(default=0)
    priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES, default='medium')
    due_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['due_date', 'created_at']

    def __str__(self):
        return self.title

    def clean(self):
        super().clean()
        if self.progress_percentage < 0 or self.progress_percentage > 100:
            raise ValidationError({'progress_percentage': 'Progress must be between 0 and 100.'})
        if self.team_id and self.company_id and self.team.company_id != self.company_id:
            raise ValidationError({'team': 'The assigned team must belong to the same company.'})


class ActivityLog(models.Model):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='activity_logs')
    action = models.CharField(max_length=255)
    description = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.description