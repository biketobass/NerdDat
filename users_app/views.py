from django.shortcuts import render, redirect
from .forms import CustomRegisterForm
from django.contrib import messages

def register(request) :
    if request.method == "POST" :
        register_form = CustomRegisterForm(request.POST)
        if register_form.is_valid() :
            register_form.save()
            messages.success(request, ('New User Account Created. Log in to get started.'))
            return redirect('users_app:login')
    else :
        register_form = CustomRegisterForm()
    return render(request, 'users_app/register.html', {'register_form': register_form})



