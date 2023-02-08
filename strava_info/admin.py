from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from .models import StravaUser, StravaActivity

# Register your models here.
# Define an inline admin descriptor for StravaUser model
# which acts a bit like a singleton
class StravaUserInline(admin.StackedInline):
    model = StravaUser
    can_delete = False
    verbose_name_plural = 'stravauser'
    
# Use this if you want to see all of a user's Strava
# activities in the admin panel.
# class StravaActivityInline(admin.StackedInline):
#     model = StravaActivity
#     can_delete = False
#     verbose_name_plural = 'stravaactivity'


# Define a new User admin
class UserAdmin(BaseUserAdmin):
    # If you want to see all of a user's strava activities
    # linked to the user in the admin panel,
    # switch the comments.
    inlines = (StravaUserInline,)
    #inlines = (StravaUserInline, StravaActivityInline)

# Re-register UserAdmin
admin.site.unregister(User)
admin.site.register(User, UserAdmin)
admin.site.register(StravaActivity)
admin.site.register(StravaUser)