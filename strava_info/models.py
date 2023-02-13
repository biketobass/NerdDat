from django.db import models
from django.contrib.auth.models import User

class StravaUser(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    token_type = models.CharField(max_length=100)
    access_token = models.CharField(max_length=200)
    expires_at = models.PositiveIntegerField(default=1)
    expires_in = models.PositiveIntegerField(default=1)
    refresh_token = models.CharField(max_length=200)
    is_strava_verified = models.BooleanField(default=False)
    has_completed_initial_download = models.BooleanField(default=False)
    preferred_units = models.CharField(max_length=10, default="imperial")
    pie_color_palette = models.JSONField(default=dict)
    
class StravaActivity(models.Model) :
    site_user = models.ForeignKey(User, on_delete=models.CASCADE, default=None)
    activity_id = models.PositiveBigIntegerField()
    name = models.CharField(max_length=500)
    distance_meters = models.FloatField()
    moving_time_sec = models.PositiveIntegerField()
    elapsed_time_sec = models.PositiveIntegerField()
    total_elevation_gain_m = models.FloatField()
    type = models.CharField(max_length=100)
    sport_type = models.CharField(max_length=100)
    start_date = models.DateTimeField()
    start_date_local = models.DateTimeField()
    timezone = models.CharField(max_length=100)
    utc_offset = models.IntegerField()
    location_country = models.CharField(max_length=100)
    achievement_count = models.IntegerField()
    kudos_count = models.IntegerField()
    average_speed_mps = models.FloatField()
    max_speed_mps = models.FloatField()
    has_heartrate = models.BooleanField(default=False)
    elev_high_m = models.FloatField()
    elev_low_m = models.FloatField()
    pr_count = models.IntegerField()
    average_cadence = models.FloatField()
    average_watts = models.FloatField()
    max_watts = models.FloatField()
    weighted_average_watts = models.FloatField()
    kilojoules = models.FloatField()
    average_heartrate = models.FloatField()
    max_heartrate = models.FloatField()
    suffer_score = models.FloatField()
    elapsed_time_min = models.FloatField()
    moving_time_min = models.FloatField(default=0.0)
    elev_high_ft = models.FloatField()
    elev_low_ft = models.FloatField()
    elev_gain_ft = models.FloatField()
    distance_miles = models.FloatField()
    distance_km = models.FloatField()
    feet_per_mile = models.FloatField()
    meters_per_km = models.FloatField()
    average_speed_mph = models.FloatField()
    average_speed_kph = models.FloatField()
    max_speed_mph = models.FloatField()
    max_speed_kph = models.FloatField()
    average_temp = models.FloatField()
    
    
class WebhookSubscription(models.Model) :
    service = models.CharField(max_length=100)
    sub_id = models.PositiveIntegerField(default=0)
    
    

