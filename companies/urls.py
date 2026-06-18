from django.urls import path

from . import views

app_name = 'companies'

urlpatterns = [
    path('teams/', views.team_list_create, name='teams'),
]
