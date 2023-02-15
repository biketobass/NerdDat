from django.urls import path
from users_app import views
from django.contrib.auth import views as auth_views
from django.conf import settings

app_name = 'users_app'
urlpatterns = [
    path('register', views.register, name='register'),
    path('register/'+settings.INVITATION_REG_URL_LONG_PART, views.register_invite, name="register_invite"),
    path('login', auth_views.LoginView.as_view(template_name='users_app/login.html'), name='login'),
    path('logout', auth_views.LogoutView.as_view(template_name='users_app/logout.html'), name='logout'),
    path('delete_nerd_account', views.delete_nerd_account, name='delete_nerd_account'),
    path('change_password', views.change_password, name='change_password'),
]
