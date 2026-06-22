from datetime import date, timedelta

from django.conf import settings
from django.core.mail import BadHeaderError, send_mail
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth import login as auth_login, update_session_auth_hash
from django.contrib.auth.tokens import default_token_generator
from django.db.models import Case, Count, IntegerField, Max, Q, Value, When
from django.db import connection, transaction
from django.db.models.deletion import ProtectedError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import get_random_string
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from django.utils.text import slugify
import secrets
from smtplib import SMTPException
from django.views import View
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from django.views.decorators.http import require_POST
from django.views.generic import DetailView, ListView

from accounts.decorators import guest_only
from accounts.forms import CompanyRegistrationForm, UserLoginForm
from accounts.models import User
from accounts.routing import redirect_user_by_role
from companies.models import ActivityLog, Task, TeamMembership, TeamMessage

from .forms import CompanyWorkspaceForm, EmployeeActivationForm, StyledPasswordChangeForm, UserProfileForm


def _redirect_team_leader(request, section='dashboard'):
    if getattr(request.user, 'role', None) != 'team_leader':
        return None
    if section == 'employees':
        messages.error(request, 'Operation Denied: Team Leaders cannot access employee management.')
        return redirect('management:team_leader_dashboard')
    route_map = {
        'dashboard': 'management:team_leader_dashboard',
        'teams': 'management:team_leader_teams',
        'boards': 'management:team_leader_boards',
        'tasks': 'management:team_leader_tasks',
        'discussions': 'management:team_leader_discussions',
        'settings': 'management:team_leader_settings',
        'profile': 'management:team_leader_settings',
    }
    return redirect(route_map.get(section, 'management:team_leader_dashboard'))
from .models import OTPVerification, Team


class TeamNameForm(forms.ModelForm):
    class Meta:
        model = Team
        fields = ['name']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'glass-input',
                'placeholder': 'Enter team name',
                'autocomplete': 'off',
            }),
        }

    def clean_name(self):
        name = self.cleaned_data.get('name', '').strip()
        if not name:
            raise forms.ValidationError('Please enter a team name.')
        return name


def _split_full_name(full_name):
    name_parts = full_name.split()
    first_name = name_parts[0] if name_parts else ''
    last_name = ' '.join(name_parts[1:]) if len(name_parts) > 1 else ''
    return first_name, last_name


def _generate_employee_username(first_name, last_name, email):
    name_seed = slugify(f'{first_name}-{last_name}').replace('-', '') or slugify(email.split('@')[0])
    name_seed = name_seed[:140] or 'employee'
    while True:
        suffix = get_random_string(length=4, allowed_chars='0123456789')
        username = f'{name_seed}{suffix}'[:150]
        if not User.objects.filter(username=username).exists():
            return username


def _generate_secure_employee_password():
    return get_random_string(
        length=12,
        allowed_chars='abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!@#$%^&*',
    )


def _is_protected_system_account(user):
    return (
        user.is_superuser
        or user.role == 'company'
        or bool(getattr(user, 'owned_company', None))
    )


def _clear_legacy_team_member_rows(user_id):
    """Remove rows from the legacy M2M join table when it still exists."""
    with connection.cursor() as cursor:
        table_names = connection.introspection.table_names()
        if 'companies_team_members' in table_names:
            cursor.execute('DELETE FROM companies_team_members WHERE user_id = %s', [user_id])


def nuclear_delete_user(user):
    """
    Hard cascade delete: clear every resolvable User FK footprint, then eradicate the row.
    """
    if _is_protected_system_account(user):
        raise ProtectedError(
            'Protected system accounts cannot be deleted.',
            {user},
        )

    user_id = user.pk

    Team.objects.filter(team_leader_id=user_id).update(team_leader=None)
    TeamMembership.objects.filter(user_id=user_id).delete()
    _clear_legacy_team_member_rows(user_id)

    user.groups.clear()
    user.user_permissions.clear()

    user.delete()


def _nuclear_purge_email_slot(email, company):
    """
    Immediately hard-delete any non-protected user occupying an email address.
    Returns (purged: bool, error_message: str|None).
    """
    existing_user = User.objects.filter(email__iexact=email.strip().lower()).first()
    if not existing_user:
        return False, None

    if _is_protected_system_account(existing_user):
        return False, 'This email address belongs to a protected system account and cannot be reused.'

    if existing_user.company_id not in (None, company.id):
        return False, 'This email address is already registered to another workspace.'

    nuclear_delete_user(existing_user)
    return True, None


def _workspace_staff_queryset(company, *, active_only=False):
    """Return workspace staff only — never company owners or superusers."""
    queryset = (
        User.objects.filter(company=company)
        .exclude(is_superuser=True)
        .exclude(role='company')
    )
    if company.owner_id:
        queryset = queryset.exclude(pk=company.owner_id)
    if active_only:
        queryset = queryset.filter(is_active=True)
    return queryset


def _owner_main_tasks_queryset(company):
    """Top-level epic tasks only — excludes delegation sub-tasks and Kanban micro-work."""
    return Task.objects.filter(company=company, parent_task__isnull=True)


def _owner_main_task_progress(task):
    """Aggregate hidden sub-tasks and kanban cards for owner-facing progress bars."""
    subtask_progress = task.calculated_progress
    kanban_progress = task.get_overall_team_progress()
    return max(subtask_progress, kanban_progress)


def _employees_queryset(company, search_query=''):
    employees = _workspace_staff_queryset(company)

    if search_query:
        employees = employees.filter(
            Q(username__icontains=search_query) |
            Q(email__icontains=search_query) |
            Q(first_name__icontains=search_query) |
            Q(last_name__icontains=search_query) |
            Q(job_title__icontains=search_query)
        )

    return employees.annotate(
        role_weight=Case(
            When(role='team_leader', then=Value(2)),
            When(role='member', then=Value(3)),
            default=Value(4),
            output_field=IntegerField(),
        )
    ).order_by('role_weight', 'username')


def _can_delete_employee(actor, employee):
    if employee.pk == actor.pk:
        return False, 'Operation Denied: You cannot delete your own account.'
    if employee.is_superuser:
        return False, 'Operation Denied: Superuser accounts cannot be deleted from the dashboard.'
    if employee.role == 'company':
        return False, 'Operation Denied: Company owners cannot be deleted.'
    if getattr(employee, 'owned_company', None):
        return False, 'Operation Denied: Company owners cannot be deleted.'
    return True, None


def _create_employee_profile(company, first_name, last_name, email, job_title, system_role):
    username = _generate_employee_username(first_name, last_name, email)
    random_password = _generate_secure_employee_password()
    employee = User(
        username=username,
        email=email.strip().lower(),
        first_name=first_name.strip(),
        last_name=last_name.strip(),
        company=company,
        role=system_role,
        job_title=job_title,
        is_active=True,
        invitation_status='active',
    )
    employee.set_password(random_password)
    employee.save()
    return employee, random_password


def _send_employee_credentials_email(request, employee, company, password):
    employee_name = employee.get_full_name() or employee.first_name or employee.username
    company_name = company.name
    login_url = request.build_absolute_uri(reverse('accounts:login'))

    subject = f'Your TaskFlow AI login credentials for {company_name}'
    plain_message = (
        f'Hello {employee_name},\n\n'
        f'An administrator at {company_name} has created your TaskFlow AI employee account.\n\n'
        'Your secure login credentials:\n'
        f'  Username: {employee.username}\n'
        f'  Corporate email: {employee.email}\n'
        f'  Temporary password: {password}\n\n'
        f'Sign in here: {login_url}\n\n'
        'You can log in using either your username or corporate email address.\n'
        'Please change your password after your first login.\n\n'
        '— TaskFlow AI Security'
    )
    html_message = f"""
<!DOCTYPE html>
<html lang="en">
<body style="margin:0;padding:0;background:#f8fafc;font-family:Inter,Segoe UI,sans-serif;color:#0f172a;">
  <table width="100%" cellpadding="0" cellspacing="0" style="padding:40px 16px;">
    <tr>
      <td align="center">
        <table width="100%" cellpadding="0" cellspacing="0" style="max-width:560px;background:#ffffff;border:1px solid #e2e8f0;border-radius:24px;overflow:hidden;box-shadow:0 24px 80px rgba(15,23,42,0.08);">
          <tr>
            <td style="padding:36px 32px 12px;">
              <p style="margin:0 0 10px;font-size:12px;font-weight:700;letter-spacing:0.16em;text-transform:uppercase;color:#1d4ed8;">Workspace Access</p>
              <h1 style="margin:0 0 12px;font-size:28px;line-height:1.2;letter-spacing:-0.03em;color:#1e293b;">Welcome to {company_name}</h1>
              <p style="margin:0;font-size:16px;line-height:1.6;color:#64748b;">
                Hello {employee_name}, an administrator at <strong>{company_name}</strong> has created your
                TaskFlow AI employee account. Use the credentials below to sign in immediately.
              </p>
            </td>
          </tr>
          <tr>
            <td style="padding:12px 32px;">
              <table width="100%" cellpadding="0" cellspacing="0" style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:16px;">
                <tr>
                  <td style="padding:16px 18px;font-size:14px;color:#64748b;">Username</td>
                  <td style="padding:16px 18px;font-size:15px;font-weight:700;color:#1e293b;text-align:right;">{employee.username}</td>
                </tr>
                <tr>
                  <td style="padding:16px 18px;font-size:14px;color:#64748b;border-top:1px solid #e2e8f0;">Corporate Email</td>
                  <td style="padding:16px 18px;font-size:15px;font-weight:700;color:#1e293b;text-align:right;">{employee.email}</td>
                </tr>
                <tr>
                  <td style="padding:16px 18px;font-size:14px;color:#64748b;border-top:1px solid #e2e8f0;">Temporary Password</td>
                  <td style="padding:16px 18px;font-size:15px;font-weight:700;color:#1e293b;text-align:right;font-family:Consolas,Monaco,monospace;">{password}</td>
                </tr>
              </table>
            </td>
          </tr>
          <tr>
            <td style="padding:8px 32px 28px;">
              <a href="{login_url}" style="display:inline-block;padding:14px 28px;border-radius:999px;background:linear-gradient(135deg,#1d4ed8,#06b6d4);color:#ffffff;text-decoration:none;font-weight:700;font-size:15px;">
                Sign In to TaskFlow AI
              </a>
            </td>
          </tr>
          <tr>
            <td style="padding:0 32px 32px;">
              <p style="margin:0;font-size:13px;line-height:1.6;color:#94a3b8;">
                Sign in with your username or corporate email. Change your password after your first login.
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""

    send_mail(
        subject,
        plain_message,
        settings.DEFAULT_FROM_EMAIL,
        [employee.email],
        html_message=html_message,
        fail_silently=False,
    )


def _resolve_employee_from_uid(uidb64):
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        return User.objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        return None


@login_required(login_url='accounts:login')
def redirect_router(request):
    return redirect_user_by_role(request.user)


@login_required(login_url='accounts:login')
def admin_dashboard(request):
    team_leader_redirect = _redirect_team_leader(request, 'dashboard')
    if team_leader_redirect:
        return team_leader_redirect
    if not getattr(request.user, 'company', None):
        return redirect('accounts:profile')

    company = request.user.company
    teams = Team.objects.filter(company=company)
    employees = _workspace_staff_queryset(company)
    all_tasks = _owner_main_tasks_queryset(company)
    active_tasks = all_tasks.exclude(status='done')
    completed_tasks = all_tasks.filter(status='done')
    
    # Recent Activities Widget: dynamic from ActivityLog, ordered chronologically (latest)
    recent_activities = ActivityLog.objects.filter(company=company).order_by('-created_at')[:4]
    
    # Upcoming Deadlines Widget: closest upcoming
    upcoming_deadlines = (
        all_tasks.exclude(status='done')
        .filter(due_date__isnull=False)
        .select_related('team', 'team__team_leader')
        .order_by('due_date')[:5]
    )

    # Calculate real task counts
    total_tasks_count = all_tasks.count()
    todo_count = all_tasks.filter(status='todo').count()
    in_progress_count = all_tasks.filter(status__in=['in_progress', 'under_review']).count()
    completed_count = completed_tasks.count()

    overall_progress = int((completed_count / total_tasks_count) * 100) if total_tasks_count > 0 else 0

    # Progress chart logic
    import calendar
    import json
    from django.utils import timezone
    today = timezone.now()
    current_year = today.year
    progress_labels = []
    progress_points = []
    
    # Calculate cumulative completion percentage for Jan through Jun of the current year
    for month_num in range(1, 7):
        progress_labels.append(calendar.month_abbr[month_num])
        
        month_total_tasks = all_tasks.filter(
            created_at__year=current_year,
            created_at__month__lte=month_num
        ).count()
        
        month_completed_tasks = all_tasks.filter(
            status='done',
            updated_at__year=current_year,
            updated_at__month__lte=month_num
        ).count()
        
        progress_percentage = round((month_completed_tasks / month_total_tasks) * 100) if month_total_tasks > 0 else 0
        progress_points.append(progress_percentage)

    context = {
        'company': company,
        'user': request.user,
        'total_teams': teams.count(),
        'total_employees': employees.count(),
        'active_tasks': active_tasks.count(),
        'completed_tasks': completed_count,
        'recent_activities': recent_activities,
        'upcoming_deadlines': upcoming_deadlines,
        
        # Chart Data JSON
        'progress_labels_json': json.dumps(progress_labels),
        'progress_points_json': json.dumps(progress_points),
        'tasks_status_data_json': json.dumps([completed_count, in_progress_count, todo_count]),
        'overall_progress': overall_progress,
    }

    return render(request, 'dashboard/dashboard.html', context)


@login_required(login_url='accounts:login')
def dashboard_placeholder(request, page_name):
    company = getattr(request.user, 'owned_company', None) or getattr(request.user, 'company', None)
    context = {
        'company': company,
        'page_name': page_name,
        'title': page_name,
        'user': request.user,
    }
    return render(request, 'dashboard/placeholder.html', context)


@login_required(login_url='accounts:login')
@transaction.atomic
def tasks_view(request):
    team_leader_redirect = _redirect_team_leader(request, 'tasks')
    if team_leader_redirect:
        return team_leader_redirect
    company = getattr(request.user, 'owned_company', None) or getattr(request.user, 'company', None)
    if not company:
        return redirect('accounts:profile')

    form_data = {
        'title': '',
        'team_id': '',
        'due_date': '',
    }
    show_add_modal = False

    if request.method == 'POST':
        title = request.POST.get('title', '').strip()
        team_id = request.POST.get('team_id', '').strip()
        due_date_raw = request.POST.get('due_date', '').strip()

        form_data.update({
            'title': title,
            'team_id': team_id,
            'due_date': due_date_raw,
        })

        if not title or not team_id or not due_date_raw:
            messages.error(request, 'Validation Error: Please complete all task fields before submitting.')
            show_add_modal = True
        else:
            team = Team.objects.filter(company=company, pk=team_id).first()
            if not team:
                messages.error(request, 'Operation Failed: The selected team was not found in your workspace.')
                show_add_modal = True
            else:
                try:
                    due_date = date.fromisoformat(due_date_raw)
                except ValueError:
                    messages.error(request, 'Validation Error: Please provide a valid due date.')
                    show_add_modal = True
                else:
                    Task.objects.create(
                        company=company,
                        title=title,
                        team=team,
                        due_date=due_date,
                        status='todo',
                        progress_percentage=0,
                    )
                    messages.success(request, 'Task assigned successfully!')
                    return redirect('dashboard:tasks')

    tasks = list(
        _owner_main_tasks_queryset(company)
        .select_related('team', 'team__team_leader')
        .prefetch_related('subtasks', 'kanban_cards')
        .order_by('due_date')
    )
    for task in tasks:
        task.display_progress = _owner_main_task_progress(task)
    teams = Team.objects.filter(company=company).select_related('team_leader').order_by('name')

    return render(request, 'dashboard/tasks.html', {
        'company': company,
        'user': request.user,
        'tasks': tasks,
        'teams': teams,
        'form_data': form_data,
        'today': date.today(),
        'show_add_modal': show_add_modal,
    })


@login_required(login_url='accounts:login')
@transaction.atomic
def employees_view(request):
    team_leader_redirect = _redirect_team_leader(request, 'employees')
    if team_leader_redirect:
        return team_leader_redirect
    company = getattr(request.user, 'owned_company', None) or getattr(request.user, 'company', None)
    if not company:
        return redirect('accounts:profile')

    form_data = {
        'first_name': '',
        'last_name': '',
        'email': '',
        'job_title': '',
        'system_role': 'member',
    }

    if request.method == 'POST':
        email = request.POST.get('email', '').strip().lower()
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        job_title = request.POST.get('job_title', '').strip()
        system_role = request.POST.get('system_role', '').strip()
        company_name = company.name

        form_data.update({
            'first_name': first_name,
            'last_name': last_name,
            'email': email,
            'job_title': job_title,
            'system_role': system_role,
        })

        if not first_name or not last_name or not email or not job_title or system_role not in ['member', 'team_leader']:
            messages.error(request, 'Validation Error: Please complete all employee fields before submitting.')
        else:
            email_was_purged = False
            if User.objects.filter(email__iexact=email).exists():
                try:
                    email_was_purged, purge_error = _nuclear_purge_email_slot(email, company)
                except ProtectedError:
                    messages.error(
                        request,
                        'Operation Failed: A previous account with this email is linked to protected records and could not be purged.',
                    )
                    return redirect('dashboard:employees')

                if purge_error:
                    messages.error(request, f'Operation Failed: {purge_error}')
                    return redirect('dashboard:employees')

            employee, random_password = _create_employee_profile(
                company,
                first_name,
                last_name,
                email,
                job_title,
                system_role,
            )
            try:
                _send_employee_credentials_email(request, employee, company, random_password)
            except (SMTPException, OSError, ConnectionError, TimeoutError, BadHeaderError):
                employee.delete()
                messages.error(
                    request,
                    'This email address does not appear to exist. Please verify the spelling.',
                )
                return render(request, 'dashboard/employees.html', {
                    'company': company,
                    'user': request.user,
                    'employees': _employees_queryset(company, search_query=''),
                    'form_data': form_data,
                    'search_query': '',
                })

            if email_was_purged:
                messages.success(
                    request,
                    f'Employee account recreated and credentials sent to {employee.email} for {company_name}.',
                )
            else:
                messages.success(
                    request,
                    f'Employee account created. Login credentials were sent to {employee.email} for {company_name}.',
                )
            return redirect('dashboard:employees')

    # Search functionality
    search_query = request.GET.get('search', '').strip()
    employees = _employees_queryset(company, search_query)

    return render(request, 'dashboard/employees.html', {
        'company': company,
        'user': request.user,
        'employees': employees,
        'form_data': form_data,
        'search_query': search_query,
    })


@login_required(login_url='accounts:login')
@transaction.atomic
def delete_employee(request, employee_id):
    if request.method != 'POST':
        return redirect('dashboard:employees')

    company = getattr(request.user, 'owned_company', None) or getattr(request.user, 'company', None)
    if not company:
        return redirect('accounts:profile')

    employee = get_object_or_404(User.objects.filter(company=company), pk=employee_id)

    allowed, denial_message = _can_delete_employee(request.user, employee)
    if not allowed:
        messages.error(request, denial_message)
        return redirect('dashboard:employees')

    employee_name = employee.get_full_name() or employee.username
    try:
        nuclear_delete_user(employee)
    except ProtectedError:
        messages.error(
            request,
            'Operation Failed: This employee is linked to protected records and could not be permanently removed.',
        )
        return redirect('dashboard:employees')

    messages.success(
        request,
        f'{employee_name} has been permanently removed from the workspace. Their email is now available for re-registration.',
    )
    return redirect('dashboard:employees')


def _get_workspace_company(user):
    return getattr(user, 'owned_company', None) or getattr(user, 'company', None)


def _accessible_teams_for_user(user, company):
    base_qs = (
        Team.objects.filter(company=company)
        .select_related('team_leader', 'company')
        .annotate(
            member_count=Count('memberships', distinct=True),
            last_message_at=Max('messages__timestamp'),
        )
    )

    if user.is_superuser or user.role == 'company':
        return base_qs.order_by('name')

    return base_qs.filter(
        Q(team_leader=user) | Q(memberships__user=user),
    ).distinct().order_by('name')


@login_required(login_url='accounts:login')
@transaction.atomic
def discussions_view(request, team_id=None):
    team_leader_redirect = _redirect_team_leader(request, 'discussions')
    if team_leader_redirect:
        return team_leader_redirect
    company = _get_workspace_company(request.user)
    if not company:
        return redirect('accounts:profile')

    teams = _accessible_teams_for_user(request.user, company)
    selected_team_id = team_id or request.GET.get('team')
    active_team = None
    team_messages = TeamMessage.objects.none()

    if selected_team_id:
        active_team = teams.filter(pk=selected_team_id).first()
        if not active_team:
            messages.error(request, 'Operation Failed: You do not have access to that team channel.')
            return redirect('dashboard:discussions')
        team_messages = (
            TeamMessage.objects.filter(team=active_team)
            .select_related('sender')
            .order_by('timestamp')
        )

    if request.method == 'POST':
        post_team_id = request.POST.get('team_id', '').strip()
        message_text = request.POST.get('message_text', '').strip()

        if not post_team_id or not message_text:
            messages.error(request, 'Validation Error: Please enter a message before sending.')
        else:
            post_team = teams.filter(pk=post_team_id).first()
            if not post_team:
                messages.error(request, 'Operation Failed: You do not have permission to post in this channel.')
                return redirect('dashboard:discussions')
            TeamMessage.objects.create(
                team=post_team,
                sender=request.user,
                message_text=message_text,
            )
            return redirect('dashboard:discussions_team', team_id=post_team.pk)

    return render(request, 'dashboard/discussions.html', {
        'company': company,
        'user': request.user,
        'teams': teams,
        'active_team': active_team,
        'team_messages': team_messages,
    })


@login_required(login_url='accounts:login')
def settings_view(request):
    team_leader_redirect = _redirect_team_leader(request, 'settings')
    if team_leader_redirect:
        return team_leader_redirect
    company = getattr(request.user, 'owned_company', None) or getattr(request.user, 'company', None)
    can_manage_workspace = request.user.role == 'company' or request.user.is_superuser
    active_tab = request.GET.get('tab', 'security')

    profile_form = UserProfileForm(instance=request.user)
    password_form = StyledPasswordChangeForm(user=request.user)
    workspace_form = CompanyWorkspaceForm(instance=company) if can_manage_workspace and company else None

    if request.method == 'POST':
        form_type = request.POST.get('form_type', '')

        if form_type == 'update_profile':
            profile_form = UserProfileForm(request.POST, instance=request.user)
            active_tab = 'profile'
            if profile_form.is_valid():
                profile_form.save()
                messages.success(request, 'Profile updated successfully!')
                return redirect(f"{reverse('dashboard:settings')}?tab=profile")

        elif form_type == 'change_password':
            password_form = StyledPasswordChangeForm(user=request.user, data=request.POST)
            active_tab = 'security'
            if password_form.is_valid():
                password_form.save()
                update_session_auth_hash(request, password_form.user)
                messages.success(request, 'Password updated successfully!')
                return redirect(f"{reverse('dashboard:settings')}?tab=security")

        elif form_type == 'update_workspace':
            active_tab = 'workspace'
            if not can_manage_workspace:
                messages.error(request, 'Operation Denied: You do not have permission to modify workspace settings.')
            elif not company:
                messages.error(request, 'Operation Failed: No workspace is associated with your account.')
            else:
                workspace_form = CompanyWorkspaceForm(request.POST, request.FILES, instance=company)
                if workspace_form.is_valid():
                    workspace_form.save()
                    messages.success(request, 'Workspace settings updated successfully!')
                    return redirect(f"{reverse('dashboard:settings')}?tab=workspace")

    return render(request, 'dashboard/settings.html', {
        'company': company,
        'user': request.user,
        'profile_form': profile_form,
        'password_form': password_form,
        'workspace_form': workspace_form,
        'can_manage_workspace': can_manage_workspace,
        'active_tab': active_tab,
    })


@login_required(login_url='accounts:login')
def profile_page(request):
    team_leader_redirect = _redirect_team_leader(request, 'profile')
    if team_leader_redirect:
        return team_leader_redirect
    return dashboard_placeholder(request, 'Profile')


class TeamsListView(LoginRequiredMixin, ListView):
    model = Team
    template_name = 'dashboard/teams.html'
    context_object_name = 'teams'
    login_url = 'accounts:login'

    def dispatch(self, request, *args, **kwargs):
        team_leader_redirect = _redirect_team_leader(request, 'teams')
        if team_leader_redirect:
            return team_leader_redirect
        if not getattr(request.user, 'owned_company', None) and not getattr(request.user, 'company', None):
            return redirect('accounts:profile')
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        company = getattr(self.request.user, 'owned_company', None) or getattr(self.request.user, 'company', None)
        if not company:
            return Team.objects.none()

        return (
            Team.objects.filter(company=company)
            .select_related('company', 'team_leader')
            .prefetch_related('members')
            .annotate(
                member_count=Count('members', distinct=True),
                active_projects_count=Value(0, output_field=IntegerField()),
            )
            .order_by('-created_at')
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        company = getattr(self.request.user, 'owned_company', None) or getattr(self.request.user, 'company', None)
        form = kwargs.pop('form', None)
        if form is None:
            form = TeamNameForm()
        context.update({
            'company': company,
            'user': self.request.user,
            'form': form,
        })
        return context


class TeamDetailView(LoginRequiredMixin, DetailView):
    model = Team
    template_name = 'dashboard/team_detail.html'
    context_object_name = 'team'
    login_url = 'accounts:login'

    def dispatch(self, request, *args, **kwargs):
        team_leader_redirect = _redirect_team_leader(request, 'teams')
        if team_leader_redirect:
            return team_leader_redirect
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        company = getattr(self.request.user, 'owned_company', None) or getattr(self.request.user, 'company', None)
        return Team.objects.filter(company=company).prefetch_related('memberships__user', 'team_leader')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        company = getattr(self.request.user, 'owned_company', None) or getattr(self.request.user, 'company', None)
        team = self.object
        team_memberships = team.memberships.select_related('user').order_by('joined_at', 'user__first_name', 'user__last_name')
        member_pks = list(team_memberships.values_list('user_id', flat=True))
        team_leader_name = team.team_leader.get_full_name() or team.team_leader.username if team.team_leader else 'Unassigned'
        company_employee_qs = _workspace_staff_queryset(company, active_only=True).order_by(
            'first_name', 'last_name', 'username',
        )
        available_leaders = company_employee_qs.filter(role='team_leader')
        available_employees = company_employee_qs.exclude(pk__in=member_pks).filter(role__in=['team_leader', 'member'])
        context.update({
            'team_leader': team.team_leader,
            'team_leader_name': team_leader_name,
            'team_members': team_memberships,
            'company_employees': company_employee_qs,
            'available_leaders': available_leaders,
            'available_employees': available_employees,
            'company': company,
            'user': self.request.user,
        })
        return context


def get_or_create_company_user(company, name, email, role='member', job_title=''):
    """Legacy helper — uses nuclear email purge then creates a fresh profile."""
    email = (email or '').strip().lower()
    if not email:
        return None, 'Email is required.'

    try:
        if User.objects.filter(email__iexact=email).exists():
            _, purge_error = _nuclear_purge_email_slot(email, company)
            if purge_error:
                return None, purge_error
        first_name, last_name = _split_full_name(name)
        employee, _ = _create_employee_profile(
            company,
            first_name,
            last_name,
            email,
            job_title or 'Member',
            role if role in ('member', 'team_leader') else 'member',
        )
        return employee, None
    except ProtectedError:
        return None, 'A previous account with this email is linked to protected records and could not be purged.'


@login_required(login_url='accounts:login')
def assign_leader(request, pk):
    team_leader_redirect = _redirect_team_leader(request, 'teams')
    if team_leader_redirect:
        return team_leader_redirect
    company = getattr(request.user, 'owned_company', None) or getattr(request.user, 'company', None)
    team = get_object_or_404(Team.objects.filter(company=company), pk=pk)

    if request.method == 'POST':
        leader_id = request.POST.get('leader_id', '').strip()

        if not leader_id:
            messages.error(
                request,
                'Validation Error: Please select a team leader from the dropdown before submitting.',
            )
        elif team.team_leader_id:
            messages.error(
                request,
                'Operation Denied: This team already has an active Team Leader assigned. Please remove or unassign the current leader before appointing a new one.',
            )
        else:
            leader = User.objects.filter(company=company, pk=leader_id).first()
            if not leader:
                messages.error(request, 'Operation Failed: The selected employee was not found in your workspace.')
            elif leader.role != 'team_leader':
                messages.error(request, 'Operation Denied: Only employees with the Team Leader role can be appointed.')
            else:
                team.team_leader = leader
                team.save(update_fields=['team_leader'])
                TeamMembership.objects.update_or_create(
                    team=team,
                    user=leader,
                    defaults={'role': 'Team Leader'},
                )
                messages.success(request, 'Team Leader successfully appointed.')

    return redirect('dashboard:team_detail', pk=team.pk)


@login_required(login_url='accounts:login')
def add_team_member(request, pk):
    team_leader_redirect = _redirect_team_leader(request, 'teams')
    if team_leader_redirect:
        return team_leader_redirect
    company = getattr(request.user, 'owned_company', None) or getattr(request.user, 'company', None)
    team = get_object_or_404(Team.objects.filter(company=company), pk=pk)

    if request.method == 'POST':
        member_id = request.POST.get('member_id', '').strip()

        if not member_id:
            messages.error(
                request,
                'Validation Error: Please select a teammate from the dropdown before submitting.',
            )
        else:
            member = User.objects.filter(company=company, pk=member_id).first()
            if not member:
                messages.error(request, 'Operation Failed: The selected employee was not found in your workspace.')
            elif member.role not in ('team_leader', 'member'):
                messages.error(request, 'Operation Denied: Only team leaders and members can be added to a squad.')
            elif TeamMembership.objects.filter(team=team, user=member).exists():
                messages.error(
                    request,
                    'Operation Denied: This employee is already assigned to this team.',
                )
            else:
                member_role = member.job_title or 'Member'
                TeamMembership.objects.update_or_create(
                    team=team,
                    user=member,
                    defaults={'role': member_role},
                )
                messages.success(request, 'New team member successfully added to the squad.')

    return redirect('dashboard:team_detail', pk=team.pk)


@login_required(login_url='accounts:login')
def remove_team_member(request, team_id, user_id):
    team_leader_redirect = _redirect_team_leader(request, 'teams')
    if team_leader_redirect:
        return team_leader_redirect
    if request.method != 'POST':
        return redirect('dashboard:teams')

    company = getattr(request.user, 'owned_company', None) or getattr(request.user, 'company', None)
    team = get_object_or_404(Team.objects.filter(company=company), pk=team_id)
    membership = get_object_or_404(TeamMembership.objects.filter(team=team, user_id=user_id))

    if membership.user_id == team.team_leader_id:
        team.team_leader = None
        team.save(update_fields=['team_leader'])

    membership.delete()
    messages.success(request, f'{membership.user.get_full_name() or membership.user.email} has been removed from the team.')
    return redirect('dashboard:team_detail', pk=team.pk)


@login_required(login_url='accounts:login')
def delete_team(request, pk):
    team_leader_redirect = _redirect_team_leader(request, 'teams')
    if team_leader_redirect:
        return team_leader_redirect
    if request.method != 'POST':
        return redirect('dashboard:teams')

    company = getattr(request.user, 'owned_company', None) or getattr(request.user, 'company', None)
    team = get_object_or_404(Team.objects.filter(company=company), pk=pk)

    TeamMembership.objects.filter(team=team).delete()

    with connection.cursor() as cursor:
        table_names = connection.introspection.table_names()
        if 'companies_team_members' in table_names:
            cursor.execute('DELETE FROM companies_team_members WHERE team_id = %s', [team.pk])

    team.delete()
    messages.success(request, 'The team has been successfully dissolved and all associated records deleted.')
    return redirect('dashboard:teams')


class CreateTeamView(LoginRequiredMixin, View):
    login_url = 'accounts:login'

    def dispatch(self, request, *args, **kwargs):
        team_leader_redirect = _redirect_team_leader(request, 'teams')
        if team_leader_redirect:
            return team_leader_redirect
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, *args, **kwargs):
        return redirect('dashboard:teams')

    def post(self, request, *args, **kwargs):
        company = getattr(request.user, 'owned_company', None) or getattr(request.user, 'company', None)
        if not company:
            return redirect('accounts:profile')

        form = TeamNameForm(request.POST)
        if form.is_valid():
            team = form.save(commit=False)
            team.company = company
            team.save()
            return redirect('dashboard:teams')

        teams = Team.objects.filter(company=company).annotate(
            member_count=Count('members', distinct=True),
            active_projects_count=Value(0, output_field=IntegerField()),
        ).order_by('-created_at')

        return render(request, 'dashboard/teams.html', {
            'company': company,
            'user': request.user,
            'teams': teams,
            'form': form,
        })


def _generate_otp_code():
    return f'{secrets.randbelow(1_000_000):06d}'


def _create_and_send_otp(user, purpose):
    otp_code = _generate_otp_code()
    OTPVerification.objects.create(
        user=user,
        otp_code=otp_code,
        purpose=purpose,
    )

    if purpose == 'signup':
        subject = 'Verify your TaskFlow AI account'
        body = (
            f'Hello {user.get_full_name() or user.username},\n\n'
            f'Your sign-up verification code is: {otp_code}\n\n'
            'This code expires in 5 minutes. If you did not create an account, '
            'you can safely ignore this email.\n\n'
            '— TaskFlow AI Security'
        )
    else:
        subject = 'Your TaskFlow AI login verification code'
        body = (
            f'Hello {user.get_full_name() or user.username},\n\n'
            f'Your two-factor login code is: {otp_code}\n\n'
            'This code expires in 5 minutes. If you did not attempt to sign in, '
            'please secure your account immediately.\n\n'
            '— TaskFlow AI Security'
        )

    send_mail(
        subject,
        body,
        settings.DEFAULT_FROM_EMAIL,
        [user.email],
        fail_silently=False,
    )
    return otp_code


def _find_user_by_credentials(username, password):
    if not username or not password:
        return None

    user = User.objects.filter(
        Q(username=username) | Q(email__iexact=username)
    ).first()
    if user and user.check_password(password):
        return user
    return None


def _resolve_otp_purpose(user):
    return 'signup' if not user.is_active else 'login'


def _otp_resend_available_at(user):
    latest = OTPVerification.objects.filter(user=user).order_by('-created_at').first()
    if not latest:
        return None
    return latest.created_at + timedelta(seconds=60)


def _resend_seconds_remaining(user):
    available_at = _otp_resend_available_at(user)
    if not available_at:
        return 0
    remaining = (available_at - timezone.now()).total_seconds()
    return max(0, int(remaining))


@guest_only
@ensure_csrf_cookie
@csrf_protect
def register(request):
    if request.method == 'POST':
        form = CompanyRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            _create_and_send_otp(user, 'signup')
            request.session['otp_verify_user_id'] = user.pk
            request.session.modified = True
            return redirect('accounts:verify_otp')
    else:
        form = CompanyRegistrationForm()

    context = {'form': form}
    return render(request, 'accounts/register.html', context)


@guest_only
@ensure_csrf_cookie
@csrf_protect
def login(request):
    if request.method == 'POST':
        form = UserLoginForm(request, data=request.POST)
        user = None

        if form.is_valid():
            user = form.get_user()
        else:
            username = request.POST.get('username', '').strip()
            password = request.POST.get('password', '')
            candidate = _find_user_by_credentials(username, password)
            if candidate and not candidate.is_active:
                user = candidate

        if user is not None:
            _create_and_send_otp(user, _resolve_otp_purpose(user))
            request.session['otp_verify_user_id'] = user.pk
            request.session.modified = True
            return redirect('accounts:verify_otp')
    else:
        form = UserLoginForm()

    context = {'form': form}
    return render(request, 'accounts/login.html', context)


@ensure_csrf_cookie
@csrf_protect
def verify_otp(request):
    user_id = request.session.get('otp_verify_user_id')
    if not user_id:
        messages.error(request, 'Your verification session has expired. Please sign in again.')
        return redirect('accounts:login')

    user = get_object_or_404(User, pk=user_id)
    resend_seconds_remaining = _resend_seconds_remaining(user)

    if request.method == 'POST':
        otp_code = request.POST.get('otp_code', '').strip()
        otp_record = (
            OTPVerification.objects
            .filter(user=user, otp_code=otp_code)
            .order_by('-created_at')
            .first()
        )

        if otp_record is None or not otp_record.is_valid():
            messages.error(request, 'Invalid or expired verification code. Please try again.')
            context = {
                'user': user,
                'resend_seconds_remaining': _resend_seconds_remaining(user),
            }
            return render(request, 'accounts/verify_otp.html', context)

        if otp_record.purpose == 'signup':
            user.is_active = True
            user.save(update_fields=['is_active'])

        auth_login(request, user)
        request.session.pop('otp_verify_user_id', None)

        messages.success(request, 'Verification successful! Welcome to your workspace.')
        return redirect_user_by_role(user)

    context = {
        'user': user,
        'resend_seconds_remaining': resend_seconds_remaining,
    }
    return render(request, 'accounts/verify_otp.html', context)


@require_POST
@csrf_protect
def resend_otp(request):
    user_id = request.session.get('otp_verify_user_id')
    if not user_id:
        messages.error(request, 'Your verification session has expired. Please sign in again.')
        return redirect('accounts:login')

    user = get_object_or_404(User, pk=user_id)
    available_at = _otp_resend_available_at(user)
    if available_at and timezone.now() < available_at:
        messages.error(request, 'Please wait before requesting a new verification code.')
        return redirect('accounts:verify_otp')

    purpose = _resolve_otp_purpose(user)
    _create_and_send_otp(user, purpose)
    messages.success(request, f'A new verification code has been sent to {user.email}.')
    return redirect('accounts:verify_otp')


@ensure_csrf_cookie
@csrf_protect
def activate_employee(request, uidb64, token):
    user = _resolve_employee_from_uid(uidb64)
    token_is_valid = (
        user is not None
        and user.invitation_status == 'pending'
        and default_token_generator.check_token(user, token)
    )

    if not token_is_valid:
        return render(request, 'accounts/activate_employee_invalid.html', status=400)

    if request.method == 'POST':
        form = EmployeeActivationForm(request.POST)
        if form.is_valid():
            user.set_password(form.cleaned_data['password1'])
            user.is_active = True
            user.invitation_status = 'active'
            user.save(update_fields=['password', 'is_active', 'invitation_status'])
            auth_login(request, user)
            messages.success(request, 'Your profile is active. Welcome to your workspace.')
            return redirect_user_by_role(user)
    else:
        form = EmployeeActivationForm()

    context = {
        'form': form,
        'employee': user,
        'company': user.company,
    }
    return render(request, 'accounts/activate_employee.html', context)
