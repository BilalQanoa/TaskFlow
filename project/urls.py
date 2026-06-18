
from django.contrib import admin
from django.urls import include, path

from dashboard import views as dashboard_views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('pages.urls')),
    path('accounts/', include('accounts.urls')),
    path('companies/', include('companies.urls')),
    path('dashboard/', include(('dashboard.urls', 'dashboard'), namespace='dashboard')),
]
