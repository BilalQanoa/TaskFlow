from datetime import date

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth import update_session_auth_hash
from django.db.models import Case, Count, IntegerField, Q, Value, When
from django.db import connection, transaction
from django.db.models.deletion import ProtectedError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.text import slugify
import secrets
import string
from django.views import View
from django.views.generic import DetailView, ListView

from accounts.models import User
from companies.models import ActivityLog, Task, TeamMembership

from .forms import CompanyWorkspaceForm, StyledPasswordChangeForm, UserProfileForm
from .models import Team


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


def _generate_unique_username(full_name, email, exclude_user_id=None):
    username_base = slugify(full_name) if full_name else email.split('@')[0]
    username = username_base[:150] if username_base else email.split('@')[0]
    original_username = username
    counter = 1
    while True:
        conflict_qs = User.objects.filter(username=username)
        if exclude_user_id:
            conflict_qs = conflict_qs.exclude(pk=exclude_user_id)
        if not conflict_qs.exists():
            return username
        username = f'{original_username}{counter}'[:150]
        counter += 1


def _generate_temp_password():
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(12))


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


def _create_employee_profile(company, full_name, email, job_title, system_role):
    first_name, last_name = _split_full_name(full_name)
    username = _generate_unique_username(full_name, email)
    employee = User(
        username=username,
        email=email.strip().lower(),
        first_name=first_name,
        last_name=last_name,
        company=company,
        role=system_role,
        job_title=job_title,
        is_active=True,
    )
    employee.set_password(_generate_temp_password())
    employee.save()
    return employee


@login_required(login_url='accounts:login')
def admin_dashboard(request):
    if not getattr(request.user, 'company', None):
        return redirect('accounts:profile')

    company = request.user.company
    teams = Team.objects.filter(company=company)
    employees = User.objects.filter(company=company)
    all_tasks = Task.objects.filter(company=company)
    active_tasks = all_tasks.exclude(status='completed')
    completed_tasks = all_tasks.filter(status='completed')
    recent_activities = ActivityLog.objects.filter(company=company)[:4]
    upcoming_deadlines = (
        all_tasks.exclude(status='completed')
        .filter(due_date__isnull=False)
        .select_related('team', 'team__team_leader')
        .order_by('due_date')[:5]
    )

    in_progress_count = all_tasks.filter(status='in_progress').count()
    completed_count = completed_tasks.count()

    context = {
        'company': company,
        'user': request.user,
        'total_teams': teams.count(),
        'total_employees': employees.count(),
        'active_tasks': active_tasks.count(),
        'completed_tasks': completed_tasks.count(),
        'recent_activities': recent_activities,
        'upcoming_deadlines': upcoming_deadlines,
        'tasks_status_data': {
            'completed': completed_count,
            'in_progress': in_progress_count,
        },
        'progress_points': [40, 58, 70, 82, 88, 96],
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
                        status='in_progress',
                        progress_percentage=0,
                    )
                    messages.success(request, 'Task assigned successfully!')
                    return redirect('dashboard:tasks')

    tasks = (
        Task.objects.filter(company=company)
        .select_related('team', 'team__team_leader')
        .order_by('due_date')
    )
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
def employees_page(request):
    company = getattr(request.user, 'owned_company', None) or getattr(request.user, 'company', None)
    if not company:
        return redirect('accounts:profile')

    form_data = {
        'full_name': '',
        'email': '',
        'job_title': '',
        'system_role': 'member',
    }

    if request.method == 'POST':
        email = request.POST.get('email', '').strip().lower()
        full_name = request.POST.get('full_name', '').strip()
        job_title = request.POST.get('job_title', '').strip()
        system_role = request.POST.get('system_role', '').strip()

        form_data.update({
            'full_name': full_name,
            'email': email,
            'job_title': job_title,
            'system_role': system_role,
        })

        if not full_name or not email or not job_title or system_role not in ['member', 'team_leader']:
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

            _create_employee_profile(company, full_name, email, job_title, system_role)
            if email_was_purged:
                messages.success(
                    request,
                    'Employee successfully re-registered to the workspace with a fresh profile.',
                )
            else:
                messages.success(request, 'Employee successfully onboarded to the workspace.')
            return redirect('dashboard:employees')

    # Search functionality
    search_query = request.GET.get('search', '').strip()
    employees = User.objects.filter(company=company, is_active=True)

    if search_query:
        employees = employees.filter(
            Q(username__icontains=search_query) |
            Q(email__icontains=search_query) |
            Q(first_name__icontains=search_query) |
            Q(last_name__icontains=search_query) |
            Q(job_title__icontains=search_query)
        )

    # Strict role ordering using Case/When (Owner first, then Leaders, then Members)
    employees = employees.annotate(
        role_weight=Case(
            When(is_superuser=True, then=Value(1)),
            When(role='company', then=Value(1)),
            When(role='team_leader', then=Value(2)),
            When(role='member', then=Value(3)),
            default=Value(4),
            output_field=IntegerField(),
        )
    ).order_by('role_weight', 'username')

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


@login_required(login_url='accounts:login')
def discussions_page(request):
    return dashboard_placeholder(request, 'Discussions')


@login_required(login_url='accounts:login')
def settings_view(request):
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
    return dashboard_placeholder(request, 'Profile')


class TeamsListView(LoginRequiredMixin, ListView):
    model = Team
    template_name = 'dashboard/teams.html'
    context_object_name = 'teams'
    login_url = 'accounts:login'

    def dispatch(self, request, *args, **kwargs):
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
        company_employee_qs = User.objects.filter(company=company, is_active=True).order_by(
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
        employee = _create_employee_profile(
            company,
            name,
            email,
            job_title or 'Member',
            role if role in ('member', 'team_leader') else 'member',
        )
        return employee, None
    except ProtectedError:
        return None, 'A previous account with this email is linked to protected records and could not be purged.'


@login_required(login_url='accounts:login')
def assign_leader(request, pk):
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

