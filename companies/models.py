from django.core.exceptions import ValidationError
from django.db import models

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
    members = models.ManyToManyField(User, related_name='teams', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()
        if self.team_leader and self.company_id and self.team_leader.company_id != self.company_id:
            raise ValidationError({'team_leader': 'The team leader must belong to the same company.'})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class Task(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
    ]
    PRIORITY_CHOICES = [
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
    ]

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='tasks')
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES, default='medium')
    due_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['due_date', 'created_at']

    def __str__(self):
        return self.title


class ActivityLog(models.Model):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='activity_logs')
    action = models.CharField(max_length=255)
    description = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.description