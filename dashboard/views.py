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
    active_tasks = Task.objects.filter(company=company).exclude(status='completed')
    completed_tasks = Task.objects.filter(company=company, status='completed')
    recent_activities = ActivityLog.objects.filter(company=company)[:4]
    upcoming_deadlines = Task.objects.filter(company=company, due_date__gte=date.today()).order_by('due_date', 'priority')[:4]

    for task in upcoming_deadlines:
        task.priority_label = task.get_priority_display()

    context = {
        'company': company,
        'user': request.user,
        'total_teams': teams.count(),
        'total_employees': employees.count(),
        'active_tasks': active_tasks.count(),
        'completed_tasks': completed_tasks.count(),
        'recent_activities': recent_activities,
        'upcoming_deadlines': upcoming_deadlines,
    }

    return render(request, 'dashboard/dashboard.html', context)
