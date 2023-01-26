from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User

class CustomRegisterForm(UserCreationForm) :
    email = forms.EmailField()
    
    class Meta :
        model = User # This sets up the User database
        fields = ['username', 'first_name', 'email', 'password1', 'password2']