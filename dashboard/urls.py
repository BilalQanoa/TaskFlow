from django.urls import path

from . import views

app_name = 'dashboard'

urlpatterns = [
    path('', views.admin_dashboard, name='dashboard'),
    path('teams/', views.TeamsListView.as_view(), name='teams'),
    path('teams/create/', views.CreateTeamView.as_view(), name='create_team'),
    path('teams/<int:pk>/', views.TeamDetailView.as_view(), name='team_detail'),
    path('teams/<int:pk>/assign-leader/', views.assign_leader, name='assign_leader'),
    path('teams/<int:pk>/add-member/', views.add_team_member, name='add_team_member'),
    path('teams/<int:pk>/delete/', views.delete_team, name='delete_team'),
    path('teams/<int:team_id>/remove-member/<int:user_id>/', views.remove_team_member, name='remove_team_member'),
    path('tasks/', views.tasks_page, name='tasks'),
    path('employees/', views.employees_page, name='employees'),
    path('discussions/', views.discussions_page, name='discussions'),
    path('settings/', views.settings_page, name='settings'),
    path('profile/', views.profile_page, name='profile'),
]
