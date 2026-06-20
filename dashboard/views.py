from datetime import date

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count, IntegerField, Value
from django.contrib.auth.hashers import make_password
from django.db import connection, transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.text import slugify
import secrets
import string
from django.views import View
from django.views.generic import DetailView, ListView

from accounts.models import User
from companies.models import ActivityLog, Task, TeamMembership

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
    upcoming_deadlines = all_tasks.filter(due_date__gte=date.today()).order_by('due_date', 'priority')[:4]

    for task in upcoming_deadlines:
        task.priority_label = task.get_priority_display()

    pending_count = all_tasks.filter(status='pending').count()
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
            'pending': pending_count,
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
def tasks_page(request):
    return dashboard_placeholder(request, 'Tasks')


@login_required(login_url='accounts:login')
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
        full_name = request.POST.get('full_name', '').strip()
        email = request.POST.get('email', '').strip().lower()
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
        elif User.objects.filter(email__iexact=email).exists():
            messages.error(request, 'Operation Failed: An employee with this email address is already registered in the system.')
        else:
            name_parts = full_name.split()
            first_name = name_parts[0] if name_parts else ''
            last_name = ' '.join(name_parts[1:]) if len(name_parts) > 1 else ''

            username_base = slugify(full_name) if full_name else email.split('@')[0]
            username = username_base[:150] if username_base else email.split('@')[0]
            original_username = username
            counter = 1
            while User.objects.filter(username=username).exists():
                username = f'{original_username}{counter}'[:150]
                counter += 1

            alphabet = string.ascii_letters + string.digits
            temp_password = ''.join(secrets.choice(alphabet) for _ in range(12))
            with transaction.atomic():
                employee = User(
                    username=username,
                    email=email,
                    first_name=first_name,
                    last_name=last_name,
                    company=company,
                    role=system_role,
                    job_title=job_title,
                )
                employee.set_password(temp_password)
                employee.save()

            messages.success(request, 'Employee successfully onboarded to the workspace.')
            return redirect('dashboard:employees')

    employees = User.objects.filter(company=company).order_by('first_name', 'last_name', 'email')
    return render(request, 'dashboard/employees.html', {
        'company': company,
        'user': request.user,
        'employees': employees,
        'form_data': form_data,
    })


@login_required(login_url='accounts:login')
def discussions_page(request):
    return dashboard_placeholder(request, 'Discussions')


@login_required(login_url='accounts:login')
def settings_page(request):
    return dashboard_placeholder(request, 'Settings')


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
        context.update({
            'team_leader': team.team_leader,
            'team_leader_name': team_leader_name,
            'team_members': team_memberships,
            'company_employees': User.objects.filter(company=company),
            'available_employees': User.objects.filter(company=company).exclude(pk__in=member_pks),
            'company': company,
            'user': self.request.user,
        })
        return context


def get_or_create_company_user(company, name, email, role='member'):
    if not email:
        return None, 'Email is required.'

    email = email.strip().lower()
    name = (name or '').strip()
    user = User.objects.filter(company=company, email__iexact=email).first()
    if user:
        if role == 'team_leader' and user.role != 'team_leader':
            user.role = 'team_leader'
            user.save(update_fields=['role'])
        return user, None

    username = slugify(name) if name else email.split('@')[0]
    if not username:
        username = email.split('@')[0]
    username = username[:150]
    original_username = username
    counter = 1
    while User.objects.filter(username=username).exists():
        username = f'{original_username}{counter}'
        if len(username) > 150:
            username = username[:150]
        counter += 1

    first_name = ''
    last_name = ''
    if name:
        parts = name.split()
        first_name = parts[0]
        last_name = ' '.join(parts[1:]) if len(parts) > 1 else ''

    password = 'TempPassword123!'
    user = User(
        username=username,
        email=email,
        first_name=first_name,
        last_name=last_name,
        company=company,
        role=role,
    )
    user.set_password(password)
    user.save()
    return user, None


@login_required(login_url='accounts:login')
def assign_leader(request, pk):
    company = getattr(request.user, 'owned_company', None) or getattr(request.user, 'company', None)
    team = get_object_or_404(Team.objects.filter(company=company), pk=pk)

    if request.method == 'POST':
        leader_name = request.POST.get('leader_name', '').strip()
        leader_email = request.POST.get('leader_email', '').strip()

        if not leader_name or not leader_email:
            messages.error(
                request,
                'Validation Error: Both Leader Name and Email fields are strictly required and cannot be left blank.',
            )
        elif team.team_leader_id:
            messages.error(
                request,
                'Operation Denied: This team already has an active Team Leader assigned. Please remove or unassign the current leader before appointing a new one.',
            )
        else:
            leader, error = get_or_create_company_user(company, leader_name, leader_email, role='team_leader')
            if leader:
                team.team_leader = leader
                team.save(update_fields=['team_leader'])
                TeamMembership.objects.update_or_create(
                    team=team,
                    user=leader,
                    defaults={'role': 'Team Leader'},
                )
                messages.success(request, 'Team Leader successfully appointed.')
            else:
                messages.error(request, error)

    return redirect('dashboard:team_detail', pk=team.pk)


@login_required(login_url='accounts:login')
def add_team_member(request, pk):
    company = getattr(request.user, 'owned_company', None) or getattr(request.user, 'company', None)
    team = get_object_or_404(Team.objects.filter(company=company), pk=pk)

    if request.method == 'POST':
        member_name = request.POST.get('member_name', '').strip()
        member_email = request.POST.get('member_email', '').strip()
        member_role = request.POST.get('member_role', '').strip()

        if not member_name or not member_email or not member_role:
            messages.error(
                request,
                'Validation Error: Member Name, Email, and Role in Team are mandatory. Please fill out all fields before submitting.',
            )
        else:
            existing_membership = TeamMembership.objects.filter(team=team, user__email__iexact=member_email).first()
            if existing_membership:
                messages.error(
                    request,
                    'Operation Denied: A team member with this email address is already assigned to this team. Please use a unique email.',
                )
            else:
                member, error = get_or_create_company_user(company, member_name, member_email, role='member')
                if member:
                    TeamMembership.objects.update_or_create(
                        team=team,
                        user=member,
                        defaults={'role': member_role},
                    )
                    messages.success(request, 'New team member successfully added to the squad.')
                else:
                    messages.error(request, error)

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

