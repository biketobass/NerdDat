from django.shortcuts import render, redirect
from .forms import CustomRegisterForm
from django.contrib import messages
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.decorators import login_required
from django.contrib.auth import update_session_auth_hash

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

@login_required
def delete_nerd_account(request) :
    if request.method == "POST" :
        user = request.user
        user.delete()
        messages.success(request, "Sucessfully deleted your account. Sorry to see you go.")
        return redirect('index')
    return render(request, "users_app/delete_nerd_account.html", {})

@login_required
def change_password(request) :
    if request.method == "POST" :
        change_form = PasswordChangeForm(request.user, request.POST)
        if change_form.is_valid() :
            change_form.save()
            update_session_auth_hash(request, change_form.user)
            messages.success(request, ('Successfully changed your password'))
            return redirect('strava_info:strava_settings')
    else :
        change_form = PasswordChangeForm(request.user)
    return render(request, 'users_app/change_password.html', {'change_form': change_form})
