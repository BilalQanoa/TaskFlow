from datetime import date

from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from accounts.models import User
from companies.models import ActivityLog, Team, Task


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
    return dashboard_placeholder(request, 'Employees')


@login_required(login_url='accounts:login')
def discussions_page(request):
    return dashboard_placeholder(request, 'Discussions')


@login_required(login_url='accounts:login')
def settings_page(request):
    return dashboard_placeholder(request, 'Settings')


@login_required(login_url='accounts:login')
def profile_page(request):
    return dashboard_placeholder(request, 'Profile')


@login_required(login_url='accounts:login')
def teams_page(request):
    return dashboard_placeholder(request, 'Teams')

