from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    ROLE_CHOICES = [
        ('company', 'Company Owner'),
        ('team_leader', 'Team Leader'),
        ('member', 'Member'),
    ]

    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    company = models.ForeignKey(
        'companies.Company',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='users'
    )

    def is_company(self):
        return self.role == 'company'

    def is_team_leader(self):
        return self.role == 'team_leader'

    def is_member(self):
        return self.role == 'member'

    def __str__(self):
        return self.get_full_name() or self.username