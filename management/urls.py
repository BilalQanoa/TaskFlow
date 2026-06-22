from django.urls import path

from . import views

app_name = 'management'

urlpatterns = [

    # ── Team Leader workspace ────────────────────────────────────────────────
    path('team-leader/', views.team_leader_dashboard, name='team_leader_dashboard'),

    path('team-leader/teams/', views.team_leader_teams, name='team_leader_teams'),

    path('team-leader/boards/', views.team_leader_boards, name='team_leader_boards'),
    path('team-leader/boards/card/create/', views.create_board_card, name='create_board_card'),
    path('team-leader/boards/card/<int:pk>/move/', views.move_board_card, name='move_board_card'),
    path('team-leader/boards/card/<int:card_id>/delete/', views.delete_kanban_card, name='delete_kanban_card'),
    path('team-leader/boards/checklist/<int:pk>/toggle/', views.toggle_checklist_item, name='toggle_checklist_item'),
    path('team-leader/boards/checklist/<int:item_id>/delete/', views.delete_checklist_item, name='delete_checklist_item'),
    path('team-leader/boards/card/<int:pk>/mark-review/', views.mark_kanban_card_for_review, name='mark_kanban_card_for_review'),
    path('team-leader/boards/card/<int:pk>/review/', views.review_kanban_card, name='review_kanban_card'),

    path('team-leader/tasks/', views.team_leader_tasks, name='team_leader_tasks'),

    path('team-leader/discussions/', views.team_leader_discussions, name='team_leader_discussions'),

    path('team-leader/discussions/<int:team_id>/', views.team_leader_discussions, name='team_leader_discussions_team'),

    path('team-leader/settings/', views.team_leader_settings, name='team_leader_settings'),

    path('team-leader/subtask/create/', views.create_subtask, name='create_subtask'),

    path('team-leader/subtask/<int:pk>/review/', views.review_subtask, name='review_subtask'),
    path('team-leader/subtask/<int:pk>/delete/', views.delete_subtask, name='delete_subtask'),

    path('team-leader/subtask/<int:pk>/mark-review/', views.mark_subtask_for_review, name='mark_subtask_for_review'),

    path('team-leader/message/', views.post_team_message, name='post_team_message'),

    # ── Team Member workspace ────────────────────────────────────────────────
    path('member/', views.member_dashboard, name='member_dashboard'),
    path('member/board/', views.member_board, name='member_board'),
    path('member/board/card/create/', views.member_create_card, name='member_create_card'),
    path('member/board/card/<int:pk>/move/', views.member_move_card, name='member_move_card'),
    path('member/board/card/<int:pk>/send-review/', views.member_send_card_to_review, name='member_send_card_to_review'),
    path('member/board/checklist/<int:pk>/toggle/', views.member_toggle_checklist, name='member_toggle_checklist'),
    path('member/discussions/', views.member_discussions, name='member_discussions'),
    path('member/discussions/<int:team_id>/', views.member_discussions, name='member_discussions_team'),
    path('member/discussions/message/', views.member_post_message, name='member_post_message'),
    path('member/settings/', views.member_settings, name='member_settings'),
]
