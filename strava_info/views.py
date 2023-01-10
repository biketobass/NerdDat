from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Sum, Max, Min, Avg
from django.http import JsonResponse
import requests
from .models import StravaUser, StravaActivity
from .forms import ImperialStravaSearchForm, MetricStravaSearchForm
from django.conf import settings
import time
from dateutil import parser
import pytz


# Helper method for saving strava data after downloading

def save_strava_data(results, the_user) :
    # results is a list. Each element is a dictionary.
    for result in results :
        sa = StravaActivity()
        sa.site_user = the_user
        sa.activity_id = result.get("id")
        sa.name = result.get("name")
        sa.distance_meters = result.get("distance",0.0)
        sa.moving_time_sec = result.get("moving_time",0)
        sa.elapsed_time_sec = result.get("elapsed_time")
        sa.total_elevation_gain_m = result.get("total_elevation_gain",0.0)
        sa.type = result.get("type", "Unknown")
        sa.sport_type = result.get("sport_type", "Unknown")
        sa.start_date = result.get("start_date")
        sa.start_date_local = result.get("start_date_local")
        sa.timezone = result.get("timezone")
        sa.utc_offset = result.get("utc_offset")
        sa.location_country = result.get("location_country")
        sa.achievement_count = result.get("achievement_count")
        sa.kudos_count = result.get("kudos_count")
        sa.average_speed_mps = result.get("average_speed", 0.0)
        sa.max_speed_mps = result.get("max_speed", 0.0)
        sa.has_heartrate = result.get("has_heartrate")
        sa.elev_high_m = result.get("elev_high", 0.0)
        sa.elev_low_m = result.get("elev_low", 0.0)
        sa.pr_count = result.get("pr_count")
        sa.average_cadence = result.get("average_cadence", 0.0)
        sa.average_watts = result.get("average_watts", 0.0)
        sa.max_watts = result.get("max_watts", 0.0)
        sa.weighted_average_watts = result.get("weighted_average_watts", 0.0)
        sa.kilojoules = result.get("kilojoules", 0.0)
        sa.average_heartrate = result.get("average_heartrate", 0.0)
        sa.max_heartrate = result.get("max_heartrate", 0.0)
        sa.suffer_score = result.get("suffer_score", 0.0)
        sa.elapsed_time_min = result["elapsed_time"] / 60
        sa.moving_time_min = result.get("moving_time", 0) / 60
        sa.elev_high_ft = result.get("elev_high", 0.0) * 3.28084
        sa.elev_low_ft = result.get('elev_low',0.0) * 3.28084
        sa.elev_gain_ft = result.get('total_elevation_gain',0.0) * 3.28084
        sa.distance_miles = result.get('distance',0.0) * 0.000621371
        sa.distance_km = result.get('distance',0.0)/1000
        sa.feet_per_mile = sa.elev_gain_ft / sa.distance_miles if sa.distance_miles > 0.0 else 0.0
        sa.meters_per_km = result.get("total_elevation_gain",0.0) / sa.distance_km if sa.distance_km > 0.0 else 0.0
        sa.average_speed_mph = result.get('average_speed',0.0) * 2.23694
        sa.average_speed_kph = result.get('average_speed',0.0) * 3.6
        sa.max_speed_mph = result.get('max_speed',0.0) * 2.23694
        sa.max_speed_kph = result.get('max_speed',0.0) * 3.6
        sa.average_temp = result.get("average_temp",0.0)
        sa.save()
        

def index(request) :
    user = request.user
    context = {}
    if user.is_authenticated :
        try :
            su = user.stravauser
        except StravaUser.DoesNotExist as e :
            print("Darn")
        else :
            if su.is_strava_verified and su.has_completed_initial_download :
                all_acts = StravaActivity.objects.filter(site_user=user)
                # Get the five most recent activities
                most_recent = all_acts.order_by('-start_date')[0:5]
                context = get_base_context(request)
                context["most_recent"] = most_recent
    return render(request, 'strava_info/index.html', context)


def get_strava_activity_type_list(user) :
    type_list = []
    if user.is_authenticated :
        su = user.stravauser
        if su.is_strava_verified and su.has_completed_initial_download :
            all_acts = StravaActivity.objects.filter(site_user=user)
            type_list = all_acts.values_list('type', flat=True).distinct()
    return type_list
            
# @login_required
# def strava_index(request) :
#     user = request.user
#     su = user.stravauser
#     context = {}
#     if su.has_completed_initial_download :
#         all_acts = StravaActivity.objects.filter(site_user=user)
#         # Get a list of all the activity types the user has ever done.
#         # For each type get the number of activities of that type.
#         act_type_counts = {}
#         for a in all_acts :
#             if a.type not in act_type_counts :
#                 count = len(all_acts.filter(type=a.type))
#                 act_type_counts[a.type] = count
#         context["type_counts"] = act_type_counts
#         # Get the most recent activity
#         #most_recent = all_acts.aggregate(Max('start_date')).get('start_date__max')
#         most_recent = all_acts.order_by('-start_date')[0:5]
#         context["most_recent"] = most_recent
#         context["type_list"] = get_strava_activity_type_list(user)
#         context["metric"] = "distance"
#     return render(request, 'strava_info/strava_index.html', context)

@login_required
def get_strava_data(request) :
    try :
        download_strava_data(request)
    except requests.exceptions.RequestException as e :
        redirect('index')
    return redirect('index')


def download_strava_data(request, start_from=None) :
    su = request.user.stravauser
    
    # Here need to get the user's access and refresh tokens from the DB.
    # If access_token has expired, use the refresh_token to get the new access_token
    try :
        check_and_refresh_access_token(su)
    except requests.exceptions.RequestException as e :
        messages.error(request, "Encountered an exception trying to refresh tokens.")
        raise(e)
    
    page = 1
    url = "https://www.strava.com/api/v3/activities"
    if not start_from :
        # Parse the start date by parsing it into a Datetime object.
        # Set the timezone to UTC
        start_date = "January 1, 1970"
        startDT = parser.parse(start_date)
        timezone = pytz.timezone("UTC")
        startDT = timezone.localize(startDT)
    else :
        startDT = start_from
    start_stamp = str(int(startDT.timestamp()))
    results = []
    while True:        
        # get page of activities from Strava
        # We're going to get 200 at a time.
        #payload = {'access_token': su.access_token, 'after': start_stamp, 'before': end_stamp, 'per_page' : '200', 'page': str(page)}
        payload = {'access_token': su.access_token, 'after': start_stamp, 'per_page' : '200', 'page': str(page)}
        try:
            r = requests.get(url, params = payload)
        except requests.exceptions.RequestException as e:
            messages.error(request, "Encountered an exception downloading data.")
            raise(e)
        r = r.json()
        results = results + r
        # If no results, then exit loop
        if (not r):
            break
        # increment page.
        page += 1

    # Now that you have it all, save it.
    save_strava_data(results, request.user)

    su.has_completed_initial_download = True
    su.save()
    if not start_from :
        messages.success(request, "Sucessfully downloaded!")
    else :
        messages.success(request, "Sucessfully updated! Found " + str(len(results)) + " new activities.")
    


def check_and_refresh_access_token(stravauser) :
    if stravauser.expires_at < time.time():
        # Make Strava auth API call with current refresh token
        # Make the request and get the response..
        try :
            response = requests.post(
                url = 'https://www.strava.com/oauth/token',
                data = {
                    'client_id': settings.STRAVA_CLIENT_ID,
                    'client_secret': settings.STRAVA_CLIENT_SECRET,
                    'grant_type': 'refresh_token',
                    'refresh_token': stravauser.refresh_token
                }
            )
        except requests.exceptions.RequestException as e:
            raise(e)
        # Replace the old strava_tokens with the response.
        tokens = response.json()
        stravauser.token_type = tokens["token_type"]
        stravauser.access_token = tokens['access_token']
        stravauser.expires_at = tokens['expires_at']
        stravauser.expires_in = tokens['expires_in']
        stravauser.refresh_token = tokens['refresh_token']
        stravauser.save()


@login_required
def update_strava_data(request) :
    user = request.user
    su = user.stravauser
    most_recent = StravaActivity.objects.filter(site_user=request.user).order_by('-start_date')[0]
    most_recent_date = most_recent.start_date
    try :
        download_strava_data(request, most_recent_date)
    except requests.exceptions.RequestException as e :
        return redirect('index')
    return redirect('index')




@login_required
def delete_strava_data(request) :
    # Need to add some safeguards here so that no one deletes all by mistake.
    user = request.user
    # Get all of this user's StavaActivities.
    all_acts = StravaActivity.objects.filter(site_user=request.user)
    all_acts.all().delete()
    su = user.stravauser
    su.has_completed_initial_download = False
    su.save()
    messages.success(request, "Sucessfully deleted!")
    return redirect('index')

@login_required
def analyze_activity_type(request, act_type) :
    su = request.user.stravauser
    # Get all activites that are of this type.
    all_acts = StravaActivity.objects.filter(site_user=request.user, type=act_type)
#    type_list = get_strava_activity_type_list(request.user)
    # Get the first and last year, the user has been on Strava
    first_year = all_acts.aggregate(Min('start_date')).get('start_date__min').year
    last_year = all_acts.aggregate(Max('start_date')).get('start_date__max').year
    
    # Calculate stats for each year
    context = get_base_context(request)
    # context["type_list"] = type_list
    # context["metric"] = "distance"
    # context["time_span"] = "monthly"
    context["act_type"] = act_type
    context["year_list"] = [] #[ y for y in range(first_year, last_year+1)]
    for y in range(first_year, last_year+1) :
        year_acts = all_acts.filter(start_date__year=y)
        year_dict = {}
        year_dict["year"] = y
        compute_metrics(year_acts, year_dict)
        context["year_list"].append(year_dict)
        
    
    summary_dict = {}
    compute_metrics(all_acts, summary_dict)
    # summary_dict["num_rides"] = all_acts.count()
    # total_dist_m = all_acts.aggregate(Sum('distance_meters')).get("distance_meters__sum")
    # summary_dict["tot_dist_miles"] = round(total_dist_m * 0.000621371,2)
    # summary_dict["tot_dist_km"] = round(total_dist_m / 1000, 2)
    #summary_dict["tot_elev_gain_m"]
    context["summary"] = summary_dict
    if su.preferred_units == "imperial" :
        headings = ["Number of " + act_type + "s", "Total Distance (miles)", "Average Distance (miles)", "Greatest Distance (miles)", "Greatest Distance Date",
                        "Total Elev. Gain (ft)", "Total Elev. Gain (miles)", "Total Duration (hours)",
                        "Total Duration (days)", "Average Duration (min)", "Total Moving Time (hours)", "Total Moving Time (days)",
                        "Average Moving Time (min)", "Average Speed (mph)", "Max Speed (mph)", "Max Speed Date",
                        "Max Elevation Gain(ft)", "Max Elevation Gain Date", "Max Heart Rate", "Max HR Date"]
        dict_keys = ["num_acts", "tot_dist_miles", "avg_dist_miles", "greatest_dist_miles", "greatest_dist_date", "tot_elev_gain_feet", "tot_elev_gain_miles",
                        "tot_dur_hours", "tot_dur_days", "avg_dur_min", "tot_moving_time_hours", "tot_moving_time_days", "avg_mov_time_min", 
                        "avg_speed_mph", "max_speed_mph", "max_speed_date", "max_elev_gain_ft", 
                        "max_elev_gain_date", "max_hr", "max_hr_date"]
    else :
        headings = ["Number of " + act_type + "s", "Total Distance (km)", "Average Distance (km)", "Greatest Distance (km)", "Greatest Distance Date",
                        "Total Elev. Gain (meters)", "Total Elev. Gain (km)", "Total Duration (hours)",
                        "Total Duration (days)", "Average Duration (min)", "Total Moving Time (hours)", "Total Moving Time (days)",
                        "Average Moving Time (min)", "Average Speed (kph)", "Max Speed (kph)", "Max Speed Date",
                        "Max Elevation Gain(m)", "Max Elevation Gain Date", "Max Heart Rate", "Max HR Date"]
        dict_keys = ["num_acts", "tot_dist_km", "avg_dist_km", "greatest_dist_km", "greatest_dist_date", "tot_elev_gain_m", "tot_elev_gain_km",
                        "tot_dur_hours", "tot_dur_days", "avg_dur_min", "tot_moving_time_hours", "tot_moving_time_days", "avg_mov_time_min", 
                        "avg_speed_kph", "max_speed_kph", "max_speed_date", "max_elev_gain_m", 
                        "max_elev_gain_date", "max_hr", "max_hr_date"]        
    # headings = ["Number of " + act_type + "s", "Total Distance (miles)", "Total Distance (km)", "Average Distance (miles)", "Average Distance (km)",
    #                     "Total Elev. Gain (meters)", "Total Elev. Gain (ft)", "Total Elev. Gain (miles)", "Total Elev. Gain (km)", "Total Duration (hours)",
    #                     "Total Duration (days)", "Average Duration (min)", "Total Moving Time (hours)", "Total Moving Time (days)",
    #                     "Average Moving Time (min)", "Average Speed (mph)", "Average Speed (kph)", "Max Speed (mph)", "Max Speed (kph)", "Max Speed Date",
    #                     "Max Elevation Gain(ft)", "Max Elevation Gain(m)", "Max Elevation Gain Date", "Max Heart Rate", "Max HR Date"]
    # dict_keys = ["num_acts", "tot_dist_miles", "tot_dist_km", "avg_dist_miles", "avg_dist_km", "tot_elev_gain_m", "tot_elev_gain_feet", "tot_elev_gain_miles", "tot_elev_gain_km",
    #                     "tot_dur_hours", "tot_dur_days", "avg_dur_min", "tot_moving_time_hours", "tot_moving_time_days", "avg_mov_time_min", 
    #                     "avg_speed_mph", "avg_speed_kph", "max_speed_mph", "max_speed_kph", "max_speed_date", "max_elev_gain_ft", "max_elev_gain_m", 
    #                     "max_elev_gain_date", "max_hr", "max_hr_date"]
    context["summary_headings"] = headings
    context["summary_dict_keys"] = dict_keys
    # For each heading, create a list of values in year order for the heading.
    sum_table_rows = []
    totals_list = []
    for h,k in zip(headings, dict_keys) :
        row_list = []
        for dict in context["year_list"]:
            row_list.append(dict[k])
        sum_table_rows.append(row_list)
        totals_list.append(summary_dict[k])
    context["summary_table_rows"] = zip(headings, sum_table_rows, totals_list)
    context["totals"] = totals_list
    
    #return render(request, 'strava_info/'+act_type.lower()+'.html', context)
    return render(request, 'strava_info/activity.html', context)

def compute_metrics(acts_qs, dict) :
    num_acts = acts_qs.count()
    dict["num_acts"] = num_acts
    if num_acts > 0 :
        total_dist_m = acts_qs.aggregate(Sum('distance_meters')).get("distance_meters__sum")
        dict["tot_dist_miles"] = '{:,}'.format(round(total_dist_m * 0.000621371,2))
        dict["tot_dist_km"] = '{:,}'.format(round(total_dist_m / 1000, 2))
        dict["avg_dist_miles"] = '{:,}'.format(round((total_dist_m * 0.000621371)/dict["num_acts"],2))
        dict["avg_dist_km"] = '{:,}'.format(round((total_dist_m/1000)/dict["num_acts"],2))
        longest_distance_activity = acts_qs.order_by('-distance_meters')[0]
        dict["greatest_dist_miles"] = '{:,}'.format(round(longest_distance_activity.distance_miles))
        dict["greatest_dist_km"] = '{:,}'.format(round(longest_distance_activity.distance_km))
        dict["greatest_dist_date"] = (longest_distance_activity.activity_id, longest_distance_activity.start_date.date)
    #    dict["greatest_dist_link"] = longest_distance_activity.activity_id
        tot_elev_gain = acts_qs.aggregate(Sum('total_elevation_gain_m')).get("total_elevation_gain_m__sum")
        dict["tot_elev_gain_m"] = '{:,}'.format(round(tot_elev_gain, 2))
        dict["tot_elev_gain_feet"] = '{:,}'.format(round(tot_elev_gain * 3.28084, 2))
        dict["tot_elev_gain_miles"] = '{:,}'.format(round(tot_elev_gain * 3.28084/5280, 2))
        dict["tot_elev_gain_km"] = '{:,}'.format(round(tot_elev_gain / 1000,2))
        tot_dur_sec = acts_qs.aggregate(Sum('elapsed_time_sec')).get('elapsed_time_sec__sum')
        avg_dur_sec = acts_qs.aggregate(Avg('elapsed_time_sec')).get('elapsed_time_sec__avg')
        dict["tot_dur_hours"] = '{:,}'.format(round(tot_dur_sec / 3600, 2))
        dict["tot_dur_days"] = '{:,}'.format(round(tot_dur_sec / (3600 * 24),2))
        dict["avg_dur_min"] = '{:,}'.format(round(avg_dur_sec / 60, 2))
        tot_moving_s = acts_qs.aggregate(Sum('moving_time_sec')).get('moving_time_sec__sum')
        avg_moving_s = acts_qs.aggregate(Avg('moving_time_sec')).get('moving_time_sec__avg')
        dict["tot_moving_time_hours"] = '{:,}'.format(round(tot_moving_s / 3600,2))
        dict["tot_moving_time_days"] = '{:,}'.format(round(tot_moving_s / (3600*24), 2))
        dict["avg_mov_time_min"] = '{:,}'.format(round(avg_moving_s / 60))
        avg_speed_mps = total_dist_m / tot_moving_s
        dict["avg_speed_mph"] = '{:,}'.format(round(avg_speed_mps * 2.23694, 2))
        dict["avg_speed_kph"] = '{:,}'.format(round(avg_speed_mps * 3.6,2))
        dict["max_speed_mph"]  = '{:,}'.format(round(acts_qs.aggregate(Max('max_speed_mph')).get("max_speed_mph__max"),2))
        dict["max_speed_kph"]  = '{:,}'.format(round(acts_qs.aggregate(Max('max_speed_kph')).get("max_speed_kph__max"),2))
        fastest = acts_qs.order_by('-max_speed_mps')[0]
        dict["max_speed_date"] = (fastest.activity_id, fastest.start_date.date)
        dict["max_elev_gain_ft"] = '{:,}'.format(round(acts_qs.aggregate(Max('elev_gain_ft')).get('elev_gain_ft__max'),2))
        dict["max_elev_gain_m"] = '{:,}'.format(round(acts_qs.aggregate(Max('total_elevation_gain_m')).get('total_elevation_gain_m__max'),2))
        most_gain = acts_qs.order_by('-total_elevation_gain_m')[0]
        dict["max_elev_gain_date"] = (most_gain.activity_id, most_gain.start_date.date)
        dict["max_hr"] = acts_qs.aggregate(Max("max_heartrate")).get('max_heartrate__max')
        max_hr = acts_qs.order_by('-max_heartrate')[0]
        dict["max_hr_date"] = (max_hr.activity_id, max_hr.start_date.date)
    else :
        dict["tot_dist_miles"] = str(0.0)
        dict["tot_dist_km"] = str(0.0)
        dict["avg_dist_miles"] = str(0.0)
        dict["avg_dist_km"] = str(0.0)
        dict["greatest_dist_miles"] = str(0.0)
        dict["greatest_dist_km"] = str(0.0)
        dict["greatest_dist_date"] = ("#", "")
        dict["tot_elev_gain_m"] = str(0.0)
        dict["tot_elev_gain_feet"] = str(0.0)
        dict["tot_elev_gain_miles"] = str(0.0)
        dict["tot_elev_gain_km"] = str(0.0)
        dict["tot_dur_hours"] = str(0.0)
        dict["tot_dur_days"] = str(0.0)
        dict["avg_dur_min"] = str(0.0)
        dict["tot_moving_time_hours"] = str(0.0)
        dict["tot_moving_time_days"] = str(0.0)
        dict["avg_mov_time_min"] = str(0.0)
        dict["avg_speed_mph"] = str(0.0)
        dict["avg_speed_kph"] = str(0.0)
        dict["max_speed_mph"]  = str(0.0)
        dict["max_speed_kph"]  = str(0.0)
        dict["max_speed_date"] = ("#", "")
        dict["max_elev_gain_ft"] = str(0.0)
        dict["max_elev_gain_m"] = str(0.0)
        dict["max_elev_gain_date"] = ("#", "")
        dict["max_hr"] = str(0)
        dict["max_hr_date"] = ("#", "")
        
@login_required
def switch_units(request) :
    su = request.user.stravauser
    if su.preferred_units == "imperial" :
       su.preferred_units = "metric"
    else :
        su.preferred_units = "imperial"
    su.save()
    return redirect(request.META.get('HTTP_REFERER')) 

@login_required
def search_strava_data(request) :
    context = get_base_context(request)
    results = []
    type_list = get_strava_activity_type_list(request.user)
    # context["type_list"] = type_list
    # context["metric"] = "distance"
    # context["time_span"] = "monthly"
    if request.user.stravauser.preferred_units == "imperial" :
        form = ImperialStravaSearchForm(request.GET, type_choices=type_list)
    else :
        form = MetricStravaSearchForm(request.GET, type_choices=type_list)
    if form.is_valid() :
        title_key = form.cleaned_data["activity_title"]  
        d = float(form.cleaned_data['distance']) if form.cleaned_data['distance'] else None
        elev = float(form.cleaned_data['elev_gain']) if form.cleaned_data['elev_gain'] else None
        act_type = form.cleaned_data['activity_type']
        elapsed_min = form.cleaned_data['elapsed_time_min']
        moving_min = form.cleaned_data['moving_time_min']
        met = False if request.user.stravauser.preferred_units == "imperial" else True
        start_date = form.cleaned_data['start_date']
        end_date = form.cleaned_data['end_date']
        results = suggest_similar_activities(request, elev_gain=elev, distance=d, metric=met, activity_type=act_type, activity_title_key=title_key,
                                             elapsed_time=elapsed_min, moving_time=moving_min, start_date=start_date, end_date=end_date)
    elif request.user.stravauser.preferred_units == "imperial" :
        form = ImperialStravaSearchForm(type_choices=type_list)
    else :
        form = MetricStravaSearchForm(type_choices=type_list)
    context['form'] = form
    context["results"] = results
    # type_list = get_strava_activity_type_list(request.user)
    # context["type_list"] = type_list
    return render(request, 'strava_info/search_strava_data.html', context)
    
    
def suggest_similar_activities(request, *, elev_gain=None, distance=None, dist_fudge=0.1, elev_fudge=0.1, metric=False, activity_type="Ride", 
                               activity_title_key=None, time_fudge=0.1, elapsed_time=None, moving_time=None, start_date=None, end_date=None) :
    """
    Takes an elevation gain and a distance and returns a list of URLs of your past Strava activities
    that have similar elevation gain and distance.

    The fudge factors let you define the degree of similarity. The defaults are 0.1.
    The default units are feet of elevation gain and miles of distance, but if you set
    the metric flag to True, the units are meters of elevation gain and kilometers of
    distance. Finally, the default activity is Ride. To specify a different activity type,
    set the activity_type parameter to it. Just make sure you name it the same as Strava does.

    Parameters
    ----------
    elev_gain : float, optional
        The elevation gain of the activity you want a suggestion for (default is None, but
        elev_gain and distance can't both be None)
    distance: float, optional
        The distance of the activity you want a suggestion for (default is None, but
        elev_gain and distance can't both be None)
    dist_fudge : float, optional
        Defines what it means for a ride to have a similar distance to another (default is 0.1)
    elev_fudge : float, optional
        Defines what it means for a ride to have a similar elevation gain to another (default is 0.1)
    metric : bool, optional
        Flag that specifies whether to use the metric system (default is False)
    activity_type : str, optional
        The activity type that you are interested in (default is "Ride")

    Returns
    -------
    list
        list of URLs of your past Strava activites that have similar
        elevation gain and distance.
    """
    su = request.user.stravauser
    # Start with all of the user's activites. that are of this type.
    acts_qs = StravaActivity.objects.filter(site_user=request.user)
    if (not elev_gain and not distance and not activity_type and not activity_title_key
        and not moving_time and not start_date and not end_date) :
        return None
    if activity_type :
        acts_qs = acts_qs.filter(type__in=activity_type)
    # Search for the title keyword
    if activity_title_key :
        acts_qs = acts_qs.filter(name__icontains=activity_title_key)
    if distance or elev_gain :
        if not metric :
            if elev_gain and distance :
                acts_qs = acts_qs.filter(distance_miles__gte=(distance - dist_fudge*distance), distance_miles__lte=(distance + dist_fudge*distance),
                                            elev_gain_ft__gte=(elev_gain - elev_fudge*elev_gain), elev_gain_ft__lte=(elev_gain + elev_fudge*elev_gain))
            elif not elev_gain :
                acts_qs = acts_qs.filter(distance_miles__gte=(distance - dist_fudge*distance), distance_miles__lte=(distance + dist_fudge*distance))
            elif not distance :
                acts_qs = acts_qs.filter(elev_gain_ft__gte=(elev_gain - elev_fudge*elev_gain), elev_gain_ft__lte=(elev_gain + elev_fudge*elev_gain))
        else :
            if elev_gain and distance :
                acts_qs = acts_qs.filter(distance_km__gte=(distance - dist_fudge*distance), distance_km__lte=(distance + dist_fudge*distance),
                                            total_elevation_gain_m__gte=(elev_gain - elev_fudge*elev_gain), total_elevation_gain_m__lte=(elev_gain + elev_fudge*elev_gain))
            elif not elev_gain :
                acts_qs = acts_qs.filter(distance_km__gte=(distance - dist_fudge*distance), distance_km__lte=(distance + dist_fudge*distance))
            elif not distance :
                acts_qs = acts_qs.filter(total_elevation_gain_m__gte=(elev_gain - elev_fudge*elev_gain), total_elevation_gain_m__lte=(elev_gain + elev_fudge*elev_gain))
    if elapsed_time :
        acts_qs = acts_qs.filter(elapsed_time_min__gte=(elapsed_time - time_fudge*elapsed_time), elapsed_time_min__lte=(elapsed_time + time_fudge*elapsed_time))
    if moving_time :
        acts_qs = acts_qs.filter(moving_time_min__gte=(moving_time - time_fudge*moving_time), moving_time_min__lte=(moving_time + time_fudge*moving_time))
    if start_date :
        acts_qs = acts_qs.filter(start_date__date__gte=start_date)
    if end_date :
        acts_qs = acts_qs.filter(start_date__date__lte=end_date)
        
    results_list = []
    if len(acts_qs) > 0 :
        for a in acts_qs :
            info = {}
            info["id"] = (str(a.activity_id))
            info["name"] = a.name
            a_dist = '{:,}'.format(round(a.distance_miles,2)) + " miles" if not metric else '{:,}'.format(round(a.distance_miles,2)) + " km"
            a_elev = '{:,}'.format(round(a.elev_gain_ft,2)) + " feet" if not metric else '{:,}'.format(round(a.total_elevation_gain_m,2)) + " m"
            info["dist"] = a_dist
            info["elev"] = a_elev
            info["elapsed"] = '{:,}'.format(int(a.elapsed_time_min))
            info["moving"] = '{:,}'.format(int(a.moving_time_min))
            info["date"] = a.start_date
            results_list.append(info)
    return results_list
    
            
    return render(request, 'strava_info/search_strava_data.html', context)

# @login_required
# def annual_charts(request, act_type) :
#     acts_qs = StravaActivity.objects.filter(site_user=request.user)
#     acts_qs = acts_qs.filter(type=act_type)
#     start_year = acts_qs.aggregate(Min("start_date")).get("start_date__min").year
#     end_year = acts_qs.aggregate(Max("start_date")).get("start_date__max").year
#     labels = [ str(y) for y in range(start_year, end_year+1)]
#     data = []
#     acts_qs = acts_qs.values("start_date__year").annotate(miles_per_year=Sum('distance_miles')).order_by('start_date__year')
#     for a in acts_qs :
#         data.append(a['miles_per_year'])
#     context = {}
#     context["act_type"] = act_type
#     context["type_list"] = get_strava_activity_type_list(request.user)
#     context["metric"] = "distance"
#     context["time_span"] = "monthly"
#     context["labels"] = labels
#     context["data"] = data
#     return render(request, 'strava_info/annual_charts.html', context)

@login_required
def monthly_charts(request, act_type, metric) :
    context = get_base_context(request)
    context["act_type"] = act_type
#    context["metric"] = metric
#    context["type_list"] = get_strava_activity_type_list(request.user)
    context["metrics"] = ["distance", "moving_time", "elevation_gain"]
#    context["time_span"] = "monthly"
    return render(request, 'strava_info/monthly_charts.html', context)

@login_required
def monthly_charts_data(request, act_type, metric) :
    title_text = ""
    scale_title = ""
    if metric == "distance" :
        title_text = "Monthly " + act_type + " Total " + metric.capitalize() + " Comparison"
        scale_title = "Miles per month"
    elif metric == "moving_time" :
        title_text = "Monthly " + act_type + " Total Moving Time Comparison"
        scale_title = "Hours per month"
    
    acts_qs = StravaActivity.objects.filter(site_user=request.user)
    acts_qs = acts_qs.filter(type=act_type)
    start_year = acts_qs.aggregate(Min("start_date")).get("start_date__min").year
    end_year = acts_qs.aggregate(Max("start_date")).get("start_date__max").year
    labels = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    # For each year sum the metric in question in each month
    datasets = []
    years = []
    for y in range(start_year, end_year+1) :
        years.append(y)
        qs = acts_qs.filter(start_date__year=y)
        if metric == "distance" :
            qs = qs.values("start_date__month").annotate(miles_per_month=Sum('distance_miles'))
        elif metric == "moving_time" :
            qs = qs.values("start_date__month").annotate(time_per_month=Sum('moving_time_sec'))
        y_data_dict = {}
        for q in qs :
            if metric == "distance" :
                y_data_dict[q["start_date__month"]] = round(q['miles_per_month'],0)
            elif metric == "moving_time" :
                y_data_dict[q["start_date__month"]] = round(q['time_per_month']/3600,0)
        y_data = [y_data_dict[m] if m in y_data_dict else 0 for m in range(1,13) ]            
        datasets.append(y_data)    
    return JsonResponse(data={
        'labels': labels,
        'datasets' : datasets,
        'years' : years,
        'title_text' : title_text,
        'scale_title' : scale_title
    })
    
@login_required
def charts(request, act_type, metric) :
    context = {}
    context["act_type"] = act_type
    context["metric"] = metric
    #context["time_span"] = time_span
    context["type_list"] = get_strava_activity_type_list(request.user)
    context["metrics"] = ["distance", "moving_time", "elevation_gain"]
    context["time_spans"] = ["monthly", "annual"]
    return render(request, 'strava_info/charts.html', context)

@login_required
def charts_data(request, act_type, metric, time_span) :
    if time_span == "annual" :
        return get_annual_chart_data(request, act_type, metric)
    elif time_span == "monthly" :
        return get_monthly_charts_data(request, act_type, metric)
    else :
        return None
    
@login_required
def get_monthly_charts_data(request, act_type, metric) :
    title_text = "Problem in monthly"
    scale_title = "Dude, really"
    if metric == "distance" :
        title_text = "Monthly " + act_type + " Total Distance Comparison"
        if request.user.stravauser.preferred_units == "imperial" :
            scale_title = "Miles per month"
        else :
            scale_title = "KM per month"
    elif metric == "moving_time" :
        title_text = "Monthly " + act_type + " Total Moving Time Comparison"
        scale_title = "Hours per month"
    elif metric == "elevation_gain" :
        title_text = "Monthly " + act_type + " Total Elevation Gain Comparison"        
        if request.user.stravauser.preferred_units == "imperial" :
            scale_title = "Feet per month"
        else :
            scale_title = "Meters per month"
    
    acts_qs = StravaActivity.objects.filter(site_user=request.user)
    acts_qs = acts_qs.filter(type=act_type)
    start_year = acts_qs.aggregate(Min("start_date")).get("start_date__min").year
    end_year = acts_qs.aggregate(Max("start_date")).get("start_date__max").year
    labels = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    # For each year sum the metric in question in each month
    datasets = []
    years = []
    for y in range(start_year, end_year+1) :
        years.append(y)
        qs = acts_qs.filter(start_date__year=y)
        if metric == "distance" :
            if request.user.stravauser.preferred_units == "imperial" :
                qs = qs.values("start_date__month").annotate(miles_per_month=Sum('distance_miles'))
            else :
                qs = qs.values("start_date__month").annotate(km_per_month=Sum('distance_km'))
        elif metric == "moving_time" :
            qs = qs.values("start_date__month").annotate(time_per_month=Sum('moving_time_sec'))
        elif metric == "elevation_gain" :
            if request.user.stravauser.preferred_units == "imperial" :
                qs = qs.values("start_date__month").annotate(feet_per_month=Sum('elev_gain_ft'))
            else :
                qs = qs.values("start_date__month").annotate(meters_per_month=Sum('total_elevation_gain_m'))
        y_data_dict = {}
        for q in qs :
            if metric == "distance" :
                if request.user.stravauser.preferred_units == "imperial" :
                    y_data_dict[q["start_date__month"]] = round(q['miles_per_month'],0)
                else :
                    y_data_dict[q["start_date__month"]] = round(q['km_per_month'],0)
            elif metric == "moving_time" :
                y_data_dict[q["start_date__month"]] = round(q['time_per_month']/3600,0)
            elif metric == "elevation_gain" :
                if request.user.stravauser.preferred_units == "imperial" :
                    y_data_dict[q["start_date__month"]] = round(q['feet_per_month'],0)
                else :
                    y_data_dict[q["start_date__month"]] = round(q['meters_per_month'],0)
        y_data = [y_data_dict[m] if m in y_data_dict else 0 for m in range(1,13) ]            
        datasets.append(y_data)    
    return JsonResponse(data={
        'labels': labels,
        'datasets' : datasets,
        'years' : years,
        'title_text' : title_text,
        'scale_title' : scale_title
    })
    
    
@login_required
def get_annual_chart_data(request, act_type, metric) :
    title_text = "Problem in annual"
    scale_title = "Dude, really"
    if metric == "distance" :
        title_text = "Annual " + act_type + " Total Distance Comparison"
        if request.user.stravauser.preferred_units == "imperial" :
            scale_title = "Miles per year"
        else :
            scale_title = "KM per year"
    elif metric == "moving_time" :
        title_text = "Annual " + act_type + " Total Moving Time Comparison"
        scale_title = "Hours per year"
    elif metric == "elevation_gain" :
        title_text = "Annual " + act_type + " Total Elevation Gain Comparison"        
        if request.user.stravauser.preferred_units == "imperial" :
            scale_title = "Feet per year"
        else :
            scale_title = "Meters per year"
    
    acts_qs = StravaActivity.objects.filter(site_user=request.user)
    acts_qs = acts_qs.filter(type=act_type)
    start_year = acts_qs.aggregate(Min("start_date")).get("start_date__min").year
    end_year = acts_qs.aggregate(Max("start_date")).get("start_date__max").year
    labels = [ str(y) for y in range(start_year, end_year+1)]
    data_label = "Year"
    # For each year sum the metric in question 
    datasets = []
    data = []
    if metric == "distance" :
        if request.user.stravauser.preferred_units == "imperial" :
            acts_qs = acts_qs.values("start_date__year").annotate(metric_per_year=Sum('distance_miles')).order_by('start_date__year')
        else :
            acts_qs = acts_qs.values("start_date__year").annotate(metric_per_year=Sum('distance_km')).order_by('start_date__year')
    elif metric == "moving_time" :
        acts_qs = acts_qs.values("start_date__year").annotate(metric_per_year=Sum('moving_time_sec')/3600).order_by('start_date__year')
    elif metric == "elevation_gain" :
        if request.user.stravauser.preferred_units == "imperial" :
            acts_qs = acts_qs.values("start_date__year").annotate(metric_per_year=Sum('elev_gain_ft')).order_by('start_date__year')
        else :
            acts_qs = acts_qs.values("start_date__year").annotate(metric_per_year=Sum('total_elevation_gain_m')).order_by('start_date__year')

    for a in acts_qs :
        data.append(a['metric_per_year'])
    datasets.append(data)
    
    return JsonResponse(data={
        'labels': labels,
        'datasets' : datasets,
        'single_label': data_label,
        'title_text' : title_text,
        'scale_title' : scale_title
    })        

@login_required
def pie_chart_data(request) :
    acts_qs = StravaActivity.objects.filter(site_user=request.user)
    # For each activity type sum the moving time for that activity and compute the percentage that is of the whole.
    all_moving_time = acts_qs.aggregate(Sum('moving_time_sec')).get('moving_time_sec__sum')
    acts_qs = acts_qs.values("type").annotate(total_moving_time=Sum('moving_time_sec'))
    data=[]
    labels=[]
    for a in acts_qs :
        #data.append(round(a['total_moving_time']/all_moving_time))
        #data.append(round(a['total_moving_time']))
        perc = round((a['total_moving_time']/all_moving_time)*100)
        data.append(perc)
        labels.append("Percent " + a["type"])
    return JsonResponse(data={
        'data' : data,
        'labels' : labels,
        'title_text' : "Percentage of total moving time of each activity type you've ever recorded on Strava"
    })
    
@login_required
def strava_settings(request) :
    context = get_base_context(request)
    return render(request, 'strava_info/strava_settings.html', context)

def get_base_context(request) :
    context = {}
    context["type_list"] = get_strava_activity_type_list(request.user)
    context["metric"] = "distance"
    #context["time_span"] = "monthly"
    return context