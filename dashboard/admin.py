from django.contrib import admin
from django.db.models import Count
from django.utils.html import format_html

from .models import OTPVerification, Task, Team, TeamMessage, User


@admin.register(User)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = (
        'username',
        'email',
        'role',
        'job_title',
        'invitation_status',
        'is_active',
        'date_joined',
    )
    list_filter = ('role', 'invitation_status', 'is_active')
    search_fields = ('username', 'email', 'job_title')
    list_editable = ('is_active',)
    list_display_links = ('username', 'email')
    ordering = ('-date_joined',)
    readonly_fields = ('date_joined', 'last_login')
    fieldsets = (
        (None, {
            'fields': ('username',),
        }),
        ('Profile', {
            'fields': ('first_name', 'last_name', 'email', 'role', 'job_title', 'company', 'invitation_status'),
        }),
        ('Permissions', {
            'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions'),
        }),
        ('Activity', {
            'fields': ('last_login', 'date_joined'),
        }),
    )


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = (
        'name',
        'leader',
        'member_count',
        'company',
        'created_at',
    )
    list_filter = ('team_leader', 'company')
    search_fields = ('name', 'team_leader__username', 'team_leader__email')
    ordering = ('-created_at',)
    raw_id_fields = ('team_leader', 'company')

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        return queryset.select_related('team_leader', 'company').annotate(
            _member_count=Count('members', distinct=True),
        )

    @admin.display(description='Leader', ordering='team_leader__username')
    def leader(self, obj):
        if obj.team_leader_id is None:
            return '—'
        return obj.team_leader.get_full_name() or obj.team_leader.username

    @admin.display(description='Members', ordering='_member_count')
    def member_count(self, obj):
        return obj._member_count


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = (
        'title',
        'team',
        'parent_task',
        'assigned_to',
        'status',
        'progress_percentage',
        'due_date',
        'company',
    )
    list_filter = ('status', 'team', 'due_date', 'parent_task')
    search_fields = ('title', 'team__name', 'company__name', 'assigned_to__username')
    ordering = ('due_date', 'created_at')
    date_hierarchy = 'due_date'
    list_editable = ('status', 'progress_percentage')
    list_display_links = ('title',)
    raw_id_fields = ('team', 'company')

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('team', 'company')


@admin.register(TeamMessage)
class TeamMessageAdmin(admin.ModelAdmin):
    list_display = (
        'team',
        'sender',
        'message_preview',
        'timestamp',
    )
    list_filter = ('team', 'timestamp')
    search_fields = ('message_text', 'sender__username', 'sender__email', 'team__name')
    ordering = ('-timestamp',)
    date_hierarchy = 'timestamp'
    readonly_fields = ('timestamp',)
    raw_id_fields = ('team', 'sender')

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('team', 'sender')

    @admin.display(description='Message')
    def message_preview(self, obj):
        text = obj.message_text.strip()
        if len(text) <= 80:
            return text
        return format_html('<span title="{}">{}&hellip;</span>', text, text[:80])


@admin.register(OTPVerification)
class OTPVerificationAdmin(admin.ModelAdmin):
    list_display = (
        'user',
        'otp_code',
        'purpose',
        'created_at',
        'is_still_valid',
    )
    list_filter = ('purpose', 'created_at')
    search_fields = ('user__username', 'user__email', 'otp_code')
    ordering = ('-created_at',)
    date_hierarchy = 'created_at'
    readonly_fields = ('user', 'otp_code', 'purpose', 'created_at')

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('user')

    @admin.display(description='Valid', boolean=True)
    def is_still_valid(self, obj):
        return obj.is_valid()
