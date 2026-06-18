from django.urls import path

from . import views

app_name = 'dashboard'

urlpatterns = [
    path('', views.admin_dashboard, name='dashboard'),
    path('teams/', views.teams_page, name='teams'),
    path('tasks/', views.tasks_page, name='tasks'),
    path('employees/', views.employees_page, name='employees'),
    path('discussions/', views.discussions_page, name='discussions'),
    path('settings/', views.settings_page, name='settings'),
    path('profile/', views.profile_page, name='profile'),
]
