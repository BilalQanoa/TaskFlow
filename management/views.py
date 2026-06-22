from datetime import date

from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Avg, Count, OuterRef, Q, Subquery
from django.shortcuts import get_object_or_404, redirect, render
from django.http import JsonResponse
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils import timezone

from accounts.models import User
from companies.models import KanbanCard, Task, TaskChecklistItem, Team, TeamMessage
from dashboard.forms import StyledPasswordChangeForm

from .decorators import team_leader_required, member_required


KANBAN_COLUMNS = [
    ('todo', 'To Do'),
    ('in_progress', 'In Progress'),
    ('under_review', 'Under Review'),
    ('done', 'Done'),
]


def _accessible_teams(user):
    return (
        Team.objects.filter(Q(team_leader=user) | Q(memberships__user=user))
        .select_related('company', 'team_leader')
        .distinct()
    )


def _accessible_team_ids(user):
    return list(_accessible_teams(user).values_list('pk', flat=True))


def _leader_teams(user):
    return Team.objects.filter(team_leader=user).select_related('company')


def _leader_team_ids(user):
    return list(_leader_teams(user).values_list('pk', flat=True))


def _primary_team(user, teams=None):
    teams = teams if teams is not None else _accessible_teams(user)
    return teams.filter(team_leader=user).first() or teams.first()


def _team_member_queryset(team):
    if not team:
        return User.objects.none()
    member_ids = team.member_user_ids()
    return (
        User.objects.filter(pk__in=member_ids, is_active=True)
        .annotate(
            assigned_task_count=Count(
                'assigned_tasks',
                filter=Q(
                    assigned_tasks__parent_task__isnull=False,
                    assigned_tasks__status__in=['todo', 'in_progress', 'under_review'],
                    assigned_tasks__team=team,
                ),
                distinct=True,
            ),
        )
        .order_by('first_name', 'last_name', 'username')
    )


def _build_overview_metrics(team_ids):
    if not team_ids:
        return {
            'active_tasks': 0,
            'completed_tasks': 0,
            'team_progress_average': 0,
            'active_team_members': 0,
        }

    all_tasks = Task.objects.filter(team_id__in=team_ids)
    main_tasks = all_tasks.filter(parent_task__isnull=True)
    active_tasks = all_tasks.exclude(status='done').count()
    completed_tasks = all_tasks.filter(status='done').count()
    progress_average = main_tasks.aggregate(avg=Avg('progress_percentage'))['avg'] or 0

    active_member_ids = set()
    for team in Team.objects.filter(pk__in=team_ids):
        active_member_ids.update(team.member_user_ids())
    active_members = User.objects.filter(pk__in=active_member_ids, is_active=True).count()

    return {
        'active_tasks': active_tasks,
        'completed_tasks': completed_tasks,
        'team_progress_average': round(progress_average, 1),
        'active_team_members': active_members,
    }


def _base_context(request):
    teams = _accessible_teams(request.user)
    team_ids = _accessible_team_ids(request.user)
    primary_team = _primary_team(request.user, teams)
    return {
        'user': request.user,
        'company': request.user.company,
        'teams': teams,
        'team_ids': team_ids,
        'primary_team': primary_team,
        'has_teams': bool(team_ids),
        'led_team_ids': _leader_team_ids(request.user),
        'today': date.today(),
    }


def _redirect_back(request, default_route='management:team_leader_dashboard'):
    next_url = request.POST.get('next') or request.GET.get('next')
    if next_url and url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return redirect(next_url)
    return redirect(default_route)


def _team_messages_for_teams(team_ids, limit=8):
    if not team_ids:
        return TeamMessage.objects.none()
    return (
        TeamMessage.objects.filter(team_id__in=team_ids)
        .select_related('sender', 'team')
        .order_by('-timestamp')[:limit]
    )


def _kanban_board(main_task, member_id):
    cards = (
        KanbanCard.objects.filter(
            main_task=main_task,
            assigned_to_id=member_id,
        )
        .select_related('assigned_to', 'main_task')
        .prefetch_related('checklists')
        .order_by('-updated_at', 'title')
    )

    board = {status: [] for status, _ in KANBAN_COLUMNS}
    for card in cards:
        board.setdefault(card.status, []).append(card)
    return board


def _leader_main_tasks(user):
    """Epic main tasks for teams this user leads — board scope is leader-managed teams only."""
    return (
        Task.objects.filter(team__team_leader=user, parent_task__isnull=True)
        .select_related('team')
        .order_by('title')
    )


def _resolve_board_main_task(request, user):
    main_task_param = request.GET.get('main_task', '').strip()
    main_tasks = _leader_main_tasks(user)
    if not main_tasks.exists():
        return None, main_tasks
    if main_task_param:
        try:
            main_task_id = int(main_task_param)
        except ValueError:
            return main_tasks.first(), main_tasks
        active = main_tasks.filter(pk=main_task_id).first()
        return (active or main_tasks.first()), main_tasks
    return main_tasks.first(), main_tasks


def _board_team_members_for_task(main_task):
    """Members dropdown scoped to the active epic's team only."""
    if not main_task or not main_task.team_id:
        return User.objects.none()
    return _team_member_queryset(main_task.team)


def _boards_redirect_url(main_task=None, member_id=None):
    boards_url = reverse('management:team_leader_boards')
    query_parts = []
    if main_task:
        query_parts.append(f'main_task={main_task.pk}')
    if member_id:
        query_parts.append(f'member={member_id}')
    if not query_parts:
        return boards_url
    return f'{boards_url}?{"&".join(query_parts)}'


def _board_main_tasks(led_team_ids):
    if not led_team_ids:
        return Task.objects.none()
    return (
        Task.objects.filter(team_id__in=led_team_ids, parent_task__isnull=True)
        .select_related('team')
        .order_by('title')
    )


ADD_CARD_COLUMNS = {'todo', 'in_progress', 'done'}


@team_leader_required
def team_leader_dashboard(request):
    context = _base_context(request)
    team_ids = context['team_ids']
    context['metrics'] = _build_overview_metrics(team_ids)
    context['announcements'] = _team_messages_for_teams(team_ids, limit=6)
    return render(request, 'dashboard/team_leader_dashboard.html', context)


@team_leader_required
def team_leader_teams(request):
    context = _base_context(request)
    team_main_task_subquery = Task.objects.filter(
        team_id=OuterRef('pk'),
        parent_task__isnull=True,
    ).order_by('title', 'pk')
    teams = context['teams'].annotate(
        member_count=Count('memberships', distinct=True),
        active_task_count=Count(
            'tasks',
            filter=Q(tasks__parent_task__isnull=True) & ~Q(tasks__status='done'),
            distinct=True,
        ),
        active_main_task_id=Subquery(team_main_task_subquery.values('pk')[:1]),
    )
    context['teams'] = teams
    return render(request, 'dashboard/team_leader_teams.html', context)


@team_leader_required
def team_leader_boards(request):
    context = _base_context(request)
    user = request.user
    led_team_ids = context['led_team_ids']

    active_main_task, main_tasks = _resolve_board_main_task(request, user)
    filterable_members = _board_team_members_for_task(active_main_task)
    member_param = request.GET.get('member', '').strip()

    if member_param:
        try:
            requested_member_id = int(member_param)
        except ValueError:
            messages.error(request, 'Validation Error: Invalid team member selected.')
            return redirect('management:team_leader_boards')

        if requested_member_id == user.pk:
            if active_main_task and not filterable_members.filter(pk=user.pk).exists():
                messages.error(
                    request,
                    'Operation Denied: You are not assigned to the team for this epic main task.',
                )
                return redirect(_boards_redirect_url(active_main_task))
            board_member = user
            is_editable = True
        else:
            board_member = filterable_members.filter(pk=requested_member_id).first()
            if not board_member:
                messages.error(
                    request,
                    'Operation Denied: That user is not on the team for this epic main task.',
                )
                return redirect(_boards_redirect_url(active_main_task))
            is_editable = False
    else:
        if active_main_task and filterable_members.filter(pk=user.pk).exists():
            board_member = user
            is_editable = True
        elif filterable_members.exists():
            board_member = filterable_members.first()
            is_editable = board_member.pk == user.pk
        else:
            board_member = user
            is_editable = bool(active_main_task)

    board = {key: [] for key, _ in KANBAN_COLUMNS}
    if active_main_task:
        board = _kanban_board(active_main_task, board_member.pk)

    boards_url = reverse('management:team_leader_boards')
    query_parts = []
    if active_main_task:
        query_parts.append(f'main_task={active_main_task.pk}')
    query_parts.append(f'member={board_member.pk}')
    boards_return_query = '?' + '&'.join(query_parts)

    context.update({
        'kanban_columns': [
            {
                'key': key,
                'label': label,
                'cards': board.get(key, []),
            }
            for key, label in KANBAN_COLUMNS
        ],
        'filterable_members': filterable_members,
        'board_member': board_member,
        'selected_member_id': str(board_member.pk),
        'is_editable': is_editable,
        'is_viewing_self': board_member.pk == user.pk,
        'main_task': active_main_task,
        'main_tasks': main_tasks,
        'epic_team_progress': active_main_task.get_overall_team_progress() if active_main_task else 0,
        'board_main_tasks': _board_main_tasks(led_team_ids) if is_editable else Task.objects.none(),
        'boards_url': boards_url,
        'boards_return_query': boards_return_query,
    })
    return render(request, 'dashboard/team_leader_boards.html', context)


@team_leader_required
def team_leader_tasks(request):
    context = _base_context(request)
    team_ids = context['team_ids']
    led_team_ids = context['led_team_ids']

    main_tasks = (
        Task.objects.filter(team_id__in=team_ids, parent_task__isnull=True)
        .select_related('team', 'assigned_to')
        .prefetch_related('subtasks__assigned_to')
        .order_by('due_date', 'created_at')
    )

    main_tasks_with_members = [
        {
            'task': task,
            'members': _team_member_queryset(task.team),
            'epic_progress': task.get_overall_team_progress(),
        }
        for task in main_tasks
    ]

    context.update({
        'main_tasks_with_members': main_tasks_with_members,
        'can_delegate': bool(led_team_ids),
        'tasks_next': reverse('management:team_leader_tasks'),
    })
    return render(request, 'dashboard/team_leader_tasks.html', context)


@team_leader_required
@transaction.atomic
def team_leader_discussions(request, team_id=None):
    context = _base_context(request)
    teams = context['teams']
    team_ids = context['team_ids']

    if not team_ids:
        context.update({
            'active_team': None,
            'team_messages': TeamMessage.objects.none(),
        })
        return render(request, 'dashboard/team_leader_discussions.html', context)

    selected_team_id = team_id or request.GET.get('team')
    active_team = None
    team_messages = TeamMessage.objects.none()

    if selected_team_id:
        active_team = teams.filter(pk=selected_team_id).first()
        if not active_team:
            messages.error(request, 'Operation Failed: You do not have access to that team channel.')
            return redirect('management:team_leader_discussions')
        team_messages = (
            TeamMessage.objects.filter(team=active_team)
            .select_related('sender')
            .order_by('timestamp')
        )
    else:
        active_team = _primary_team(request.user, teams)
        if active_team:
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
            else:
                TeamMessage.objects.create(
                    team=post_team,
                    sender=request.user,
                    message_text=message_text,
                )
                messages.success(request, 'Message posted to the team discussion.')
                return redirect('management:team_leader_discussions_team', team_id=post_team.pk)

    context.update({
        'active_team': active_team,
        'team_messages': team_messages,
    })
    return render(request, 'dashboard/team_leader_discussions.html', context)


@team_leader_required
def team_leader_settings(request):
    context = _base_context(request)
    active_tab = request.GET.get('tab', 'security')
    password_form = StyledPasswordChangeForm(user=request.user)

    if request.method == 'POST':
        form_type = request.POST.get('form_type', '')

        if form_type == 'change_password':
            active_tab = 'security'
            password_form = StyledPasswordChangeForm(user=request.user, data=request.POST)
            if password_form.is_valid():
                password_form.save()
                update_session_auth_hash(request, password_form.user)
                messages.success(request, 'Password updated successfully!')
                return redirect(f"{reverse('management:team_leader_settings')}?tab=security")

    context.update({
        'password_form': password_form,
        'active_tab': active_tab,
    })
    return render(request, 'dashboard/team_leader_settings.html', context)


@team_leader_required
@transaction.atomic
def create_board_card(request):
    if request.method != 'POST':
        return redirect('management:team_leader_boards')

    user = request.user
    led_team_ids = _leader_team_ids(user)
    title = request.POST.get('title', '').strip()
    description = request.POST.get('description', '').strip()
    status = request.POST.get('status', 'todo').strip()
    main_task_id = request.POST.get('main_task_id', '').strip()
    checklist_raw = request.POST.get('checklist_items', '').strip()

    boards_return = reverse('management:team_leader_boards')
    boards_return = f'{boards_return}?member={user.pk}'
    if main_task_id:
        boards_return = f'{boards_return}&main_task={main_task_id}'

    if status not in ADD_CARD_COLUMNS:
        messages.error(request, 'Validation Error: Cards can only be added to To Do, In Progress, or Done.')
        return redirect(boards_return)

    main_task = Task.objects.filter(
        pk=main_task_id,
        team_id__in=led_team_ids,
        parent_task__isnull=True,
    ).select_related('team').first()

    if not main_task:
        messages.error(request, 'Operation Failed: Select a valid epic main task to attach this card.')
        return redirect(boards_return)

    if not title:
        messages.error(request, 'Validation Error: Card title is required.')
        return redirect(boards_return)

    try:
        card = KanbanCard.objects.create(
            main_task=main_task,
            assigned_to=user,
            title=title,
            description=description,
            status=status,
        )
    except ValidationError as exc:
        error_text = '; '.join([' '.join(messages_list) for messages_list in exc.message_dict.values()])
        messages.error(request, f'Validation Error: {error_text}')
        return redirect(boards_return)

    if checklist_raw:
        for line in checklist_raw.splitlines():
            item_title = line.strip()
            if item_title:
                TaskChecklistItem.objects.create(card=card, title=item_title)

    messages.success(request, f'Card "{title}" added to your board.')
    return redirect(boards_return)


@team_leader_required
@transaction.atomic
def move_board_card(request, pk):
    if request.method != 'POST':
        return redirect('management:team_leader_boards')

    user = request.user
    team_ids = _accessible_team_ids(user)
    new_status = request.POST.get('status', '').strip()
    allowed_statuses = {key for key, _ in KANBAN_COLUMNS}
    main_task_id = request.POST.get('main_task_id', '').strip()

    boards_return = f"{reverse('management:team_leader_boards')}?member={user.pk}"
    if main_task_id:
        boards_return = f'{boards_return}&main_task={main_task_id}'

    if new_status not in allowed_statuses:
        messages.error(request, 'Validation Error: Invalid column destination.')
        return redirect(boards_return)

    card = get_object_or_404(
        KanbanCard.objects.select_related('main_task'),
        pk=pk,
        main_task__team_id__in=team_ids,
        assigned_to=user,
    )

    card.status = new_status
    if new_status != 'under_review':
        card.review_notice = ''
    card.save(update_fields=['status', 'review_notice', 'updated_at'])
    return redirect(boards_return)


@team_leader_required
@transaction.atomic
def toggle_checklist_item(request, pk):
    if request.method != 'POST':
        return redirect('management:team_leader_boards')

    user = request.user
    team_ids = _accessible_team_ids(user)
    item = get_object_or_404(
        TaskChecklistItem.objects.select_related('card', 'card__main_task'),
        pk=pk,
        card__main_task__team_id__in=team_ids,
    )
    card = item.card

    if card.assigned_to_id != user.pk:
        messages.error(request, 'Operation Denied: You can only update checklists on your own board cards.')
        return _redirect_back(request, 'management:team_leader_boards')

    if 'is_completed' in request.POST:
        item.is_completed = request.POST.get('is_completed') in ('true', '1', 'on')
    else:
        item.is_completed = not item.is_completed
    item.save(update_fields=['is_completed'])

    return _redirect_back(request, 'management:team_leader_boards')


@team_leader_required
@transaction.atomic
def delete_checklist_item(request, item_id):
    if request.method != 'POST':
        return redirect('management:team_leader_boards')

    user = request.user
    team_ids = _accessible_team_ids(user)
    item = get_object_or_404(
        TaskChecklistItem.objects.select_related('card', 'card__main_task', 'card__assigned_to'),
        pk=item_id,
        card__main_task__team_id__in=team_ids,
    )
    card = item.card
    main_task = card.main_task

    if card.assigned_to_id != user.pk:
        messages.error(request, 'Operation Denied: You can only delete checklist items on your own board cards.')
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': 'Permission denied.'}, status=403)
        return _redirect_back(request, 'management:team_leader_boards')

    item_title = item.title
    item.delete()

    card.refresh_from_db()
    member_progress = card.get_member_progress()
    epic_progress = main_task.get_overall_team_progress()

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({
            'success': True,
            'member_progress': member_progress,
            'epic_progress': epic_progress,
            'card_id': card.pk,
            'main_task_id': main_task.pk,
        })

    messages.success(request, f'Checklist item "{item_title}" was removed.')
    return _redirect_back(request, 'management:team_leader_boards')


@team_leader_required
@transaction.atomic
def delete_kanban_card(request, card_id):
    if request.method != 'POST':
        return redirect('management:team_leader_boards')

    user = request.user
    team_ids = _accessible_team_ids(user)
    card = get_object_or_404(
        KanbanCard.objects.select_related('main_task'),
        pk=card_id,
        main_task__team_id__in=team_ids,
        assigned_to=user,
    )

    main_task = card.main_task
    card_title = card.title
    main_task_id = request.POST.get('main_task_id', '').strip() or str(main_task.pk)

    boards_return = f"{reverse('management:team_leader_boards')}?member={user.pk}&main_task={main_task_id}"
    card.delete()

    messages.success(request, f'Kanban card "{card_title}" was deleted.')
    return redirect(boards_return)


@team_leader_required
@transaction.atomic
def mark_kanban_card_for_review(request, pk):
    if request.method != 'POST':
        return redirect('management:team_leader_boards')

    user = request.user
    team_ids = _accessible_team_ids(user)
    card = get_object_or_404(
        KanbanCard,
        pk=pk,
        main_task__team_id__in=team_ids,
        assigned_to=user,
    )

    if card.status not in ('todo', 'in_progress'):
        messages.error(request, 'Only active cards can be moved into review.')
        return _redirect_back(request, 'management:team_leader_boards')

    card.status = 'under_review'
    card.save(update_fields=['status', 'updated_at'])
    messages.info(request, f'Card "{card.title}" is now under review.')
    return _redirect_back(request, 'management:team_leader_boards')


@team_leader_required
@transaction.atomic
def review_kanban_card(request, pk):
    if request.method != 'POST':
        return redirect('management:team_leader_boards')

    led_team_ids = _leader_team_ids(request.user)
    card = get_object_or_404(
        KanbanCard.objects.select_related('assigned_to', 'main_task'),
        pk=pk,
        main_task__team_id__in=led_team_ids,
    )

    action = request.POST.get('action', '').strip().lower()
    review_notice = request.POST.get('review_notice', '').strip()

    if card.status != 'under_review':
        messages.error(request, 'This card is not awaiting review.')
        return _redirect_back(request, 'management:team_leader_boards')

    if action == 'approve':
        card.status = 'done'
        card.review_notice = ''
        card.save(update_fields=['status', 'review_notice', 'updated_at'])
        messages.success(request, f'Card "{card.title}" approved and marked as done.')
    elif action == 'reject':
        card.status = 'in_progress'
        card.review_notice = review_notice or 'Please revise and resubmit this card for review.'
        card.save(update_fields=['status', 'review_notice', 'updated_at'])
        messages.warning(request, f'Card "{card.title}" returned for revision.')
    else:
        messages.error(request, 'Validation Error: Please choose Approve or Reject.')
        return _redirect_back(request, 'management:team_leader_boards')

    return _redirect_back(request, 'management:team_leader_boards')


@team_leader_required
@transaction.atomic
def create_subtask(request):
    if request.method != 'POST':
        return redirect('management:team_leader_tasks')

    led_team_ids = _leader_team_ids(request.user)
    parent_task_id = request.POST.get('parent_task_id', '').strip()
    title = request.POST.get('title', '').strip()
    description = request.POST.get('description', '').strip()
    due_date_raw = request.POST.get('due_date', '').strip()
    assigned_to_id = request.POST.get('assigned_to_id', '').strip()

    parent_task = Task.objects.filter(
        pk=parent_task_id,
        team_id__in=led_team_ids,
        parent_task__isnull=True,
    ).select_related('team').first()

    if not parent_task:
        messages.error(request, 'Operation Failed: The selected main task was not found in your led teams.')
        return _redirect_back(request, 'management:team_leader_tasks')

    if not title or not due_date_raw or not assigned_to_id:
        messages.error(request, 'Validation Error: Title, due date, and assignee are required for sub-tasks.')
        return _redirect_back(request, 'management:team_leader_tasks')

    assignee = User.objects.filter(pk=assigned_to_id, is_active=True).first()
    allowed_member_ids = parent_task.team.member_user_ids()
    if not assignee or assignee.pk not in allowed_member_ids:
        messages.error(request, 'Operation Denied: The selected employee is not part of this team.')
        return _redirect_back(request, 'management:team_leader_tasks')

    try:
        due_date = date.fromisoformat(due_date_raw)
    except ValueError:
        messages.error(request, 'Validation Error: Please provide a valid due date.')
        return _redirect_back(request, 'management:team_leader_tasks')

    try:
        Task.objects.create(
            company=parent_task.company,
            team=parent_task.team,
            parent_task=parent_task,
            assigned_to=assignee,
            title=title,
            description=description,
            due_date=due_date,
            status='todo',
            priority=parent_task.priority,
        )
    except ValidationError as exc:
        error_text = '; '.join([' '.join(messages_list) for messages_list in exc.message_dict.values()])
        messages.error(request, f'Validation Error: {error_text}')
        return _redirect_back(request, 'management:team_leader_tasks')

    messages.success(request, f'Sub-task "{title}" assigned to {assignee.get_full_name() or assignee.username}.')
    return _redirect_back(request, 'management:team_leader_tasks')


@team_leader_required
@transaction.atomic
def review_subtask(request, pk):
    if request.method != 'POST':
        return redirect('management:team_leader_tasks')

    led_team_ids = _leader_team_ids(request.user)
    subtask = get_object_or_404(
        Task.objects.select_related('parent_task', 'assigned_to'),
        pk=pk,
        team_id__in=led_team_ids,
        parent_task__isnull=False,
    )

    action = request.POST.get('action', '').strip().lower()
    review_notice = request.POST.get('review_notice', '').strip()

    if subtask.status != 'under_review':
        messages.error(request, 'This sub-task is not awaiting review.')
        return _redirect_back(request, 'management:team_leader_tasks')

    if action == 'approve':
        subtask.status = 'done'
        subtask.review_notice = ''
        subtask.save(update_fields=['status', 'review_notice', 'updated_at'])
        messages.success(request, f'Sub-task "{subtask.title}" approved and marked as done.')
    elif action == 'reject':
        subtask.status = 'in_progress'
        subtask.review_notice = review_notice or 'Please revise and resubmit this sub-task for review.'
        subtask.save(update_fields=['status', 'review_notice', 'updated_at'])
        messages.warning(request, f'Sub-task "{subtask.title}" returned to the assignee for revision.')
    else:
        messages.error(request, 'Validation Error: Please choose Approve or Reject.')
        return _redirect_back(request, 'management:team_leader_tasks')

    return _redirect_back(request, 'management:team_leader_tasks')


@team_leader_required
@transaction.atomic
def delete_subtask(request, pk):
    if request.method != 'POST':
        return redirect('management:team_leader_tasks')

    led_team_ids = _leader_team_ids(request.user)
    subtask = get_object_or_404(
        Task.objects.select_related('parent_task'),
        pk=pk,
        team_id__in=led_team_ids,
        parent_task__isnull=False,
    )

    parent_task = subtask.parent_task
    subtask_title = subtask.title
    subtask.delete()

    if parent_task:
        remaining = parent_task.subtasks.first()
        if remaining:
            remaining.save()
        else:
            parent_task.progress_percentage = 0
            update_fields = ['progress_percentage', 'updated_at']
            if parent_task.status == 'done':
                parent_task.status = 'in_progress'
                update_fields.append('status')
            parent_task.save(update_fields=update_fields)

    messages.success(request, f'Sub-task "{subtask_title}" was deleted.')
    return _redirect_back(request, 'management:team_leader_tasks')


@team_leader_required
@transaction.atomic
def mark_subtask_for_review(request, pk):
    if request.method != 'POST':
        return redirect('management:team_leader_boards')

    led_team_ids = _leader_team_ids(request.user)
    subtask = get_object_or_404(
        Task,
        pk=pk,
        team_id__in=led_team_ids,
        parent_task__isnull=False,
    )

    if subtask.status not in ('todo', 'in_progress'):
        messages.error(request, 'Only active sub-tasks can be moved into review.')
        return _redirect_back(request, 'management:team_leader_boards')

    subtask.status = 'under_review'
    subtask.save(update_fields=['status', 'updated_at'])
    messages.info(request, f'Sub-task "{subtask.title}" is now under review.')
    return _redirect_back(request, 'management:team_leader_boards')


@team_leader_required
@transaction.atomic
def post_team_message(request):
    if request.method != 'POST':
        return redirect('management:team_leader_discussions')

    team_ids = _accessible_team_ids(request.user)
    team_id = request.POST.get('team_id', '').strip()
    message_text = request.POST.get('message_text', '').strip()

    if not team_id or not message_text:
        messages.error(request, 'Validation Error: Please enter a message before sending.')
        return _redirect_back(request, 'management:team_leader_discussions')

    team = Team.objects.filter(pk=team_id, pk__in=team_ids).first()
    if not team:
        messages.error(request, 'Operation Failed: You do not have permission to post in this team channel.')
        return _redirect_back(request, 'management:team_leader_discussions')

    TeamMessage.objects.create(
        team=team,
        sender=request.user,
        message_text=message_text,
    )
    messages.success(request, 'Message posted to the team discussion hub.')
    return redirect('management:team_leader_discussions_team', team_id=team.pk)


# ═══════════════════════════════════════════════════════════════════════════
#  TEAM MEMBER WORKSPACE
# ═══════════════════════════════════════════════════════════════════════════

# Columns a member can drag between (cannot drop to 'done')
MEMBER_ALLOWED_MOVE_COLUMNS = {'todo', 'in_progress', 'under_review'}


def _member_teams(user):
    """Teams where this user holds a membership (as a regular member)."""
    return (
        Team.objects.filter(memberships__user=user)
        .select_related('company', 'team_leader')
        .distinct()
    )


def _member_primary_team(user):
    return _member_teams(user).first()


def _member_base_context(request):
    teams = _member_teams(request.user)
    primary_team = teams.first()
    return {
        'user': request.user,
        'company': request.user.company,
        'teams': teams,
        'primary_team': primary_team,
        'has_teams': teams.exists(),
        'today': date.today(),
    }


def _member_kanban_stats(user):
    """Personal Kanban card statistics for dashboard rings."""
    base = KanbanCard.objects.filter(
        assigned_to=user,
        main_task__team__memberships__user=user,
    )
    total = base.count()
    in_progress = base.filter(status='in_progress').count()
    under_review = base.filter(status='under_review').count()
    done = base.filter(status='done').count()
    todo = base.filter(status='todo').count()
    completion_pct = int((done / total) * 100) if total else 0
    return {
        'total_cards': total,
        'in_progress_count': in_progress,
        'under_review_count': under_review,
        'done_count': done,
        'todo_count': todo,
        'completion_pct': completion_pct,
    }


def _member_personal_board(user, main_task=None):
    """All KanbanCards assigned to the member across all their teams."""
    cards = KanbanCard.objects.filter(
        assigned_to=user,
        main_task__team__memberships__user=user,
    )
    if main_task:
        cards = cards.filter(main_task=main_task)

    cards = (
        cards.select_related('main_task', 'main_task__team', 'assigned_to')
        .prefetch_related('checklists')
        .order_by('-updated_at', 'title')
        .distinct()
    )
    board = {status: [] for status, _ in KANBAN_COLUMNS}
    for card in cards:
        board.setdefault(card.status, []).append(card)
    return board


@member_required
def member_dashboard(request):
    context = _member_base_context(request)
    context['stats'] = _member_kanban_stats(request.user)
    return render(request, 'dashboard/member_dashboard.html', context)


@member_required
def member_board(request):
    context = _member_base_context(request)
    member = request.user
    
    # Fetch the user's active team
    member_team = member.teams.first()

    # Fetch the active Epic Main Task assigned to this team
    member_main_tasks = Task.objects.filter(team=member_team, parent_task__isnull=True).order_by('title') if member_team else Task.objects.none()
    active_main_task = member_main_tasks.first()

    # Fetch ONLY the Kanban cards assigned to this specific member for this active project
    if active_main_task:
        cards = KanbanCard.objects.filter(assigned_to=member, main_task=active_main_task)
    else:
        cards = KanbanCard.objects.none()

    board = {status: [] for status, _ in KANBAN_COLUMNS}
    for card in cards:
        board.setdefault(card.status, []).append(card)

    context.update({
        'kanban_columns': [
            {'key': key, 'label': label, 'cards': board.get(key, [])}
            for key, label in KANBAN_COLUMNS
        ],
        'active_main_task': active_main_task,
        'member_main_tasks': member_main_tasks,
    })
    return render(request, 'dashboard/member_board.html', context)


@member_required
@transaction.atomic
def member_create_card(request):
    if request.method != 'POST':
        return redirect('management:member_board')

    user = request.user
    title = request.POST.get('title', '').strip()
    description = request.POST.get('description', '').strip()
    status = request.POST.get('status', 'todo').strip()
    checklist_raw = request.POST.get('checklist_items', '').strip()

    boards_return = reverse('management:member_board')

    if status not in ['todo', 'in_progress', 'under_review']:
        messages.error(request, 'Validation Error: Cards can only be added to To Do, In Progress, or Under Review.')
        return redirect(boards_return)
        
    member_team = user.teams.first()
    if not member_team:
        messages.error(request, 'Operation Failed: You must be assigned to a team to create cards.')
        return redirect(boards_return)

    active_main_task = Task.objects.filter(team=member_team, parent_task__isnull=True).first()
    if not active_main_task:
        messages.error(request, 'Operation Failed: No active epic main task found for your team.')
        return redirect(boards_return)

    if not title:
        messages.error(request, 'Validation Error: Card title is required.')
        return redirect(boards_return)

    try:
        card = KanbanCard.objects.create(
            main_task=active_main_task,
            assigned_to=user,
            title=title,
            description=description,
            status=status,
        )
    except ValidationError as exc:
        error_text = '; '.join([' '.join(messages_list) for messages_list in exc.message_dict.values()])
        messages.error(request, f'Validation Error: {error_text}')
        return redirect(boards_return)

    if checklist_raw:
        for line in checklist_raw.splitlines():
            item_title = line.strip()
            if item_title:
                TaskChecklistItem.objects.create(card=card, title=item_title)

    messages.success(request, f'Card "{title}" added to your board.')
    return redirect(boards_return)


@member_required
@transaction.atomic
def member_move_card(request, pk):
    """Move a card between todo / in_progress / under_review — done is BLOCKED."""
    if request.method != 'POST':
        return redirect('management:member_board')

    user = request.user
    new_status = request.POST.get('status', '').strip()

    if new_status not in MEMBER_ALLOWED_MOVE_COLUMNS:
        messages.error(request, 'Operation Denied: Team Members cannot move cards to Done. Only the Team Leader can approve completion.')
        return redirect('management:member_board')

    card = get_object_or_404(
        KanbanCard.objects.select_related('main_task'),
        pk=pk,
        assigned_to=user,
        main_task__team__memberships__user=user,
    )

    card.status = new_status
    if new_status != 'under_review':
        card.review_notice = ''
    card.save(update_fields=['status', 'review_notice', 'updated_at'])
    return redirect('management:member_board')


@member_required
@transaction.atomic
def member_send_card_to_review(request, pk):
    """Promote a card to 'under_review' — the member's equivalent of Done."""
    if request.method != 'POST':
        return redirect('management:member_board')

    user = request.user
    card = get_object_or_404(
        KanbanCard,
        pk=pk,
        assigned_to=user,
        main_task__team__memberships__user=user,
    )

    if card.status not in ('todo', 'in_progress'):
        messages.error(request, 'Only active cards can be sent to review.')
        return redirect('management:member_board')

    card.status = 'under_review'
    card.save(update_fields=['status', 'updated_at'])
    messages.success(request, f'"{card.title}" has been submitted for review.')
    return redirect('management:member_board')


@member_required
@transaction.atomic
def member_toggle_checklist(request, pk):
    if request.method != 'POST':
        return redirect('management:member_board')

    user = request.user
    item = get_object_or_404(
        TaskChecklistItem.objects.select_related('card', 'card__main_task'),
        pk=pk,
        card__assigned_to=user,
        card__main_task__team__memberships__user=user,
    )

    if 'is_completed' in request.POST:
        item.is_completed = request.POST.get('is_completed') in ('true', '1', 'on')
    else:
        item.is_completed = not item.is_completed
    item.save(update_fields=['is_completed'])

    next_url = request.POST.get('next') or ''
    if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return redirect(next_url)
    return redirect('management:member_board')


@member_required
@transaction.atomic
def member_discussions(request, team_id=None):
    context = _member_base_context(request)
    teams = context['teams']

    if not teams.exists():
        context.update({'active_team': None, 'team_messages': TeamMessage.objects.none()})
        return render(request, 'dashboard/member_discussions.html', context)

    selected_team_id = team_id or request.GET.get('team')
    active_team = None
    team_messages = TeamMessage.objects.none()

    if selected_team_id:
        active_team = teams.filter(pk=selected_team_id).first()
        if not active_team:
            messages.error(request, 'You do not have access to that team channel.')
            return redirect('management:member_discussions')
        team_messages = TeamMessage.objects.filter(team=active_team).select_related('sender').order_by('timestamp')
    else:
        active_team = teams.first()
        if active_team:
            team_messages = TeamMessage.objects.filter(team=active_team).select_related('sender').order_by('timestamp')

    context.update({'active_team': active_team, 'team_messages': team_messages})
    return render(request, 'dashboard/member_discussions.html', context)


@member_required
@transaction.atomic
def member_post_message(request):
    if request.method != 'POST':
        return redirect('management:member_discussions')

    teams = _member_teams(request.user)
    team_id = request.POST.get('team_id', '').strip()
    message_text = request.POST.get('message_text', '').strip()

    if not team_id or not message_text:
        messages.error(request, 'Please enter a message before sending.')
        return redirect('management:member_discussions')

    team = teams.filter(pk=team_id).first()
    if not team:
        messages.error(request, 'You do not have permission to post in this team channel.')
        return redirect('management:member_discussions')

    TeamMessage.objects.create(team=team, sender=request.user, message_text=message_text)
    messages.success(request, 'Message posted to the team channel.')
    return redirect('management:member_discussions_team', team_id=team.pk)


@member_required
def member_settings(request):
    context = _member_base_context(request)
    active_tab = request.GET.get('tab', 'security')
    password_form = StyledPasswordChangeForm(user=request.user)

    if request.method == 'POST':
        form_type = request.POST.get('form_type', '')
        if form_type == 'change_password':
            active_tab = 'security'
            password_form = StyledPasswordChangeForm(user=request.user, data=request.POST)
            if password_form.is_valid():
                password_form.save()
                update_session_auth_hash(request, password_form.user)
                messages.success(request, 'Password updated successfully!')
                return redirect(f"{reverse('management:member_settings')}?tab=security")

    context.update({'password_form': password_form, 'active_tab': active_tab})
    return render(request, 'dashboard/member_settings.html', context)
