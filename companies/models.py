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



    def member_user_ids(self):

        member_ids = set(self.memberships.values_list('user_id', flat=True))

        if self.team_leader_id:

            member_ids.add(self.team_leader_id)

        return member_ids





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

        ('todo', 'To Do'),

        ('in_progress', 'In Progress'),

        ('under_review', 'Under Review'),

        ('done', 'Done'),

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

    parent_task = models.ForeignKey(

        'self',

        on_delete=models.CASCADE,

        null=True,

        blank=True,

        related_name='subtasks',

    )

    assigned_to = models.ForeignKey(

        User,

        on_delete=models.SET_NULL,

        null=True,

        blank=True,

        related_name='assigned_tasks',

    )

    title = models.CharField(max_length=255)

    description = models.TextField(blank=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='todo')

    progress_percentage = models.PositiveSmallIntegerField(default=0)

    priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES, default='medium')

    due_date = models.DateField(null=True, blank=True)

    review_notice = models.TextField(blank=True, default='')

    created_at = models.DateTimeField(auto_now_add=True)

    updated_at = models.DateTimeField(auto_now=True)



    class Meta:

        ordering = ['due_date', 'created_at']



    def __str__(self):

        return self.title



    @property

    def is_main_task(self):

        return self.parent_task_id is None



    @property

    def calculated_progress(self):

        if not self.is_main_task:

            return 100 if self.status == 'done' else 0

        subtasks = self.subtasks.all()

        if not subtasks.exists():

            return self.progress_percentage

        done_count = subtasks.filter(status='done').count()

        return int((done_count / subtasks.count()) * 100)



    def get_overall_team_progress(self):

        if self.parent_task_id:

            return 0

        if not self.team_id:

            return 0

        member_ids = list(self.team.member_user_ids())

        if not member_ids:

            return 0

        progress_sum = 0

        for member_id in member_ids:

            member_cards = self.kanban_cards.filter(assigned_to_id=member_id)

            if not member_cards.exists():

                continue

            card_total = sum(card.get_member_progress() for card in member_cards)

            progress_sum += card_total / member_cards.count()

        return int(progress_sum / len(member_ids))



    def _sync_parent_from_subtasks(self):

        parent = self.parent_task

        if parent is None:

            return



        subtasks = parent.subtasks.all()

        if not subtasks.exists():

            return



        done_count = subtasks.filter(status='done').count()

        progress = int((done_count / subtasks.count()) * 100)

        update_fields = ['progress_percentage', 'updated_at']



        parent.progress_percentage = progress

        if done_count == subtasks.count():

            parent.status = 'done'

            update_fields.append('status')

        elif parent.status == 'done':

            parent.status = 'in_progress'

            update_fields.append('status')



        parent.save(update_fields=update_fields)



    def clean(self):

        super().clean()

        if self.progress_percentage < 0 or self.progress_percentage > 100:

            raise ValidationError({'progress_percentage': 'Progress must be between 0 and 100.'})

        if self.team_id and self.company_id and self.team.company_id != self.company_id:

            raise ValidationError({'team': 'The assigned team must belong to the same company.'})

        if self.parent_task_id:

            if not self.assigned_to_id:

                raise ValidationError({'assigned_to': 'Sub-tasks must be assigned to a team member.'})

            if self.parent_task_id == self.pk:

                raise ValidationError({'parent_task': 'A task cannot be its own parent.'})

            parent = self.parent_task

            if parent.parent_task_id:

                raise ValidationError({'parent_task': 'Sub-tasks can only be attached to main tasks.'})

            if self.team_id and parent.team_id and self.team_id != parent.team_id:

                raise ValidationError({'team': 'The sub-task team must match the parent main task team.'})

            if parent.team_id and self.assigned_to_id:

                allowed_ids = parent.team.member_user_ids()

                if self.assigned_to_id not in allowed_ids:

                    raise ValidationError({'assigned_to': 'The assignee must belong to the parent task team.'})



    def save(self, *args, **kwargs):

        if self.parent_task_id:

            parent = self.parent_task

            self.company_id = parent.company_id

            self.team_id = parent.team_id

        self.full_clean()

        super().save(*args, **kwargs)

        if self.parent_task_id:

            self._sync_parent_from_subtasks()





class ActivityLog(models.Model):

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='activity_logs')

    action = models.CharField(max_length=255)

    description = models.CharField(max_length=255)

    created_at = models.DateTimeField(auto_now_add=True)



    class Meta:

        ordering = ['-created_at']



    def __str__(self):

        return self.description





class TeamMessage(models.Model):

    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='messages')

    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name='team_messages')

    message_text = models.TextField()

    timestamp = models.DateTimeField(auto_now_add=True)



    class Meta:

        ordering = ['timestamp']



    def __str__(self):

        return f'{self.sender}: {self.message_text[:40]}'



    def clean(self):

        super().clean()

        if self.team_id and self.sender_id and self.sender.company_id:

            if self.sender.company_id != self.team.company_id:

                raise ValidationError({'sender': 'The sender must belong to the same company as the team.'})





class KanbanCard(models.Model):

    STATUS_CHOICES = Task.STATUS_CHOICES



    title = models.CharField(max_length=255)

    description = models.TextField(blank=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='todo')

    assigned_to = models.ForeignKey(

        User,

        on_delete=models.CASCADE,

        related_name='kanban_cards',

    )

    main_task = models.ForeignKey(

        Task,

        on_delete=models.CASCADE,

        related_name='kanban_cards',

        limit_choices_to={'parent_task__isnull': True},

    )

    review_notice = models.TextField(blank=True, default='')

    created_at = models.DateTimeField(auto_now_add=True)

    updated_at = models.DateTimeField(auto_now=True)



    class Meta:

        ordering = ['-updated_at', 'title']



    def __str__(self):

        return self.title



    def get_member_progress(self):
        # Card progress display is removed from UI, but backend treats 'done' column as 100%
        if self.status == 'done':
            return 100
        return 0



    def clean(self):

        super().clean()

        if self.main_task_id and self.main_task.parent_task_id:

            raise ValidationError({'main_task': 'Kanban cards must attach to an epic main task.'})

        if self.main_task_id and self.assigned_to_id:

            if self.main_task.team_id:

                allowed_ids = self.main_task.team.member_user_ids()

                if self.assigned_to_id not in allowed_ids:

                    raise ValidationError({'assigned_to': 'The assignee must belong to the main task team.'})



    def save(self, *args, **kwargs):

        self.full_clean()

        return super().save(*args, **kwargs)





class TaskChecklistItem(models.Model):

    card = models.ForeignKey(

        KanbanCard,

        on_delete=models.CASCADE,

        related_name='checklists',

    )

    title = models.CharField(max_length=255)

    is_completed = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)



    class Meta:

        ordering = ['created_at', 'pk']



    def __str__(self):

        return self.title



from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

@receiver(pre_save, sender=Task)
def capture_task_original_status(sender, instance, **kwargs):
    if instance.pk:
        try:
            instance._original_status = Task.objects.get(pk=instance.pk).status
        except Task.DoesNotExist:
            instance._original_status = None
    else:
        instance._original_status = None

@receiver(post_save, sender=Task)
def log_task_activity(sender, instance, created, **kwargs):
    if created:
        if instance.is_main_task:
            ActivityLog.objects.create(company=instance.company, action='task_created', description=f"Task created: {instance.title}")
    elif getattr(instance, '_original_status', None) != 'done' and instance.status == 'done':
        if instance.is_main_task:
            ActivityLog.objects.create(company=instance.company, action='task_completed', description=f"Task completed: {instance.title}")

@receiver(post_save, sender=Team)
def log_team_activity(sender, instance, created, **kwargs):
    if created:
        ActivityLog.objects.create(company=instance.company, action='team_created', description=f"Team created: {instance.name}")

@receiver(post_save, sender=User)
def log_user_activity(sender, instance, created, **kwargs):
    if created and getattr(instance, 'company_id', None):
        ActivityLog.objects.create(company=instance.company, action='employee_invited', description=f"Employee added: {instance.get_full_name() or instance.username}")

@receiver(post_save, sender=TeamMessage)
def log_message_activity(sender, instance, created, **kwargs):
    if created:
        ActivityLog.objects.create(company=instance.team.company, action='message_sent', description=f"New discussion in {instance.team.name}")
