from .models import StravaActivity, StravaUser, WebhookSubscription
from social_django.models import UserSocialAuth
import requests
from dateutil import parser
import pytz
import distinctipy
from django.conf import settings
import time
from django.contrib import messages
from django.db.models import Sum, Max, Min, Avg
from django.http import JsonResponse
from django.contrib.auth.models import User
import logging

logging.basicConfig(format='%(asctime)s %(levelname)s:%(message)s', level=logging.DEBUG)
logger = logging.getLogger(__name__)

def save_strava_activity(result, the_user) :
    """Save the details of a user's Strava activity to the database.
    
    Save each relevant piece of activity data to a StravaActivity model.

    Args:
        result (dict): Json data for a single activity obtained from a call to the Strava API
        the_user (User): The user associated with the Strava activity
    """
    sa = StravaActivity()
    sa.site_user = the_user
    sa.activity_id = result.get("id")
    sa.name = result.get("name")
    sa.distance_meters = result.get("distance",0.0)
    sa.moving_time_sec = result.get("moving_time",0)
    sa.elapsed_time_sec = result.get("elapsed_time", 0)
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
    sa.elapsed_time_min = result.get("elapsed_time",0) / 60
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

def save_strava_data(results, the_user) :
    """Save a list of Strava activity Json results to the database.

    Args:
        results (list): List of dictionaries of Json data retrieved by a call to the Strava API
        the_user (User): The user associated with the Strava data.
    """
    for result in results :
        save_strava_activity(result, the_user)
        

def get_strava_activity_type_list(user) :
    """
    Return the list Strava activty types that the user has ever participated in.

    Args:
        user (User): The logged in User.

    Returns:
        list: all of the Strava activity types that the user has participated in
    """
    type_list = []
    if user.is_authenticated :
        try :
            su = user.stravauser
            if su.is_strava_verified and su.has_completed_initial_download :
                all_acts = StravaActivity.objects.filter(site_user=user)
                type_list = all_acts.values_list('sport_type', flat=True).distinct()
        except StravaUser.DoesNotExist as e :
            pass
    return type_list


def download_strava_data(request, start_from=None) :
    """
    Make the Strava API calls to download the logged in User's Strava data.

    Args:
        request (HttpRequest): the http request that called the function that called this one.
        start_from (DateTime, optional): Don't download any activities that occurred before this date. Defaults to None.
    """
    # Get the StravaUser object associated with this user and
    # the strava social auth info for that user.
    su = request.user.stravauser
    try :
        strava_login = request.user.social_auth.get(provider='strava')
    except UserSocialAuth.DoesNotExist as e :
        # If the logic of this site is correct, this should never happen.
        # Just in case, though, return an empty list.
        return []
    
    # Here we need to get the user's access and refresh tokens from the DB.
    # If access_token has expired, use the refresh_token to get the new access_token
    try :
        check_and_refresh_access_token(request.user)
    except requests.exceptions.RequestException as e :
        # There was a problem checking. For now just return an empty list.
        return []
    # Get the data
    page = 1
    url = "https://www.strava.com/api/v3/activities"
    if not start_from :
        # We don't have a start_from date specified so create a Datetime
        # object representing the beginning of time.
        # Set the timezone to UTC
        start_date = "January 1, 1970"
        startDT = parser.parse(start_date)
        timezone = pytz.timezone("UTC")
        startDT = timezone.localize(startDT)
    else :
        # We do have a start_from DateTime specified so we're good to go.
        startDT = start_from
    # Create a timestamp that the Strava API wants.
    start_stamp = str(int(startDT.timestamp()))
    # A list to hold the results. Each element in results is a dictionary representing the
    # the aspects of a single activity.
    results = []
    while True:
        # There could be many many activities so get them a page at a time.        
        # We're going to get 200 at a time.
        #payload = {'access_token': su.access_token, 'after': start_stamp, 'per_page' : '200', 'page': str(page)}
        payload = {'access_token': strava_login.extra_data['access_token'],
                   'after': start_stamp, 'per_page' : '200',
                   'page': str(page)}
        try:
            r = requests.get(url, params = payload)
        except requests.exceptions.RequestException as e:
            # Couldn't make the connection.
            # Return an empty list for now.
            return []
        r = r.json()
        # If no results, then exit loop
        if (not r):
            break
        # Add the results list.
        results = results + r
        # increment page.
        page += 1

    # Now that you have it all, save it.
    save_strava_data(results, request.user)
    # Indicate that the user has completed the initial download and that they are no longer downloading.
    # This will tell the index page that it should display some summary info about the user's data.
    su.has_completed_initial_download = True
    su.downloading = False
    # Update the user's pie chart color dictionary. The colors are based on the types of activities they user
    # has engaged in on Strava.
    su.pie_color_palette = compute_pie_colors(request.user)
    su.save()

    if not start_from :
        messages.success(request, "Sucessfully downloaded!")
    else :
        messages.success(request, "Sucessfully updated! Found " + str(len(results)) + " new activities.")
    


def check_and_refresh_access_token(user) :
    """
    Check if the user's Strava access token has expired and update it as needed.

    Args:
        user (User): The currently logged in User
    """
    strava_soc = user.social_auth.get(provider='strava')
    # See if the access token has expired.
    if strava_soc.extra_data['expires_at'] < time.time():
        # It has expired.
        # Make Strava auth API call with current refresh token
        # and get the response that has the new token.
        try :
            response = requests.post(
                url = 'https://www.strava.com/oauth/token',
                data = {
                    'client_id': settings.SOCIAL_AUTH_STRAVA_KEY,
                    'client_secret': settings.SOCIAL_AUTH_STRAVA_SECRET,
                    'grant_type': 'refresh_token',
                    'refresh_token': strava_soc.extra_data['refresh_token']
                }
            )
        except requests.exceptions.RequestException as e:
            raise(e)
        # Replace the old strava_tokens with the response.
        tokens = response.json()
        strava_soc.extra_data["token_type"] = tokens["token_type"]
        strava_soc.extra_data["access_token"] = tokens['access_token']
        strava_soc.extra_data["auth_time"] = time.time()
        strava_soc.extra_data["expires_at"] = tokens['expires_at']
        strava_soc.extra_data["expires"] = tokens['expires_in']
        strava_soc.extra_data["refresh_token"] = tokens['refresh_token']
        strava_soc.save()
        # stravauser.token_type = tokens["token_type"]
        # stravauser.access_token = tokens['access_token']
        # stravauser.expires_at = tokens['expires_at']
        # stravauser.expires_in = tokens['expires_in']
        # stravauser.refresh_token = tokens['refresh_token']
        # stravauser.save()
        

def compute_pie_colors(user) :
    """
    Generate a dictionary of distinct colors representing each Strava Activity type the user has recorded.

    Args:
        user (User): the logged in user

    Returns:
        dict : keys are activity types; values are colors
    """
    # If the number of activities is less than or equal to the length of
    # these default colors, just use them and don't generate any others.
    default_colors = [(54/255, 162/255, 235/255),(255/255, 99/255, 132/255), (255/255, 159/255, 64/255), (255/255, 205/255, 86/255),
                      (75/255, 192/255, 192/255), (153/255, 102/255, 255/255), (201/255, 203/255, 207/255)]
    WHITE = (1.0, 1.0, 1.0)
    BLACK = (0.0, 0.0, 0.0)
    white_black = [WHITE, BLACK]
    # If we need to generate new colors don't include any of the
    # the default colors or white and black.
    exclude_cols = default_colors + white_black
    types = get_strava_activity_type_list(user)
    n = len(types)
    # The dict that we will return.
    colors = {}
    if n <= len(default_colors) :
        # We can just use the default colors.
        list_of_colors = default_colors
    else :
        # Use the default colors and add more as needed using distinctipy.
        list_of_colors = default_colors + distinctipy.get_colors(n-len(default_colors), exclude_colors=exclude_cols, pastel_factor=0.7)
    # Fill in the dictionary converting to hex as we go.
    for i,t in enumerate(types) :
        c = list_of_colors[i]
        colors[t] = "#" + hex_val(c[0])+hex_val(c[1])+hex_val(c[2])
    return colors


def hex_val(y) :
    """
    Convert a float between 0 and 1 to a hex string.
    
    This only works if y is between 0 and 1 inclusive.

    Args:
        y (float): rgb val between 0 and 1

    Returns:
        str: hex val of y
    """
    
    # Deal with the fact that distinipy uses rgb values from 0 to 1.
    y = round(y*255)
    # Store what A-F in hex are in base 10.
    partial_hex_table = {10:"A", 11:"B", 12:"C", 13:"D", 14:"E", 15:"F"}
    l = y//16 # This will always be less than 16 because y is <= 255.
    r = y%16 # So will this.
    if r < 10 :
        r = str(r)
    else :
        r = partial_hex_table[r]
            
    if l < 10 :
        l = str(l)
    else :
        l = partial_hex_table[l]
    return l+r 


def remove_user_strava_data(user, deauthorized_strava=False) :
    """
    Delete all of a user's stored Strava data and remove Strava authorization if the user has revoked access.

    Args:
        user (User): a user of the app
        deauthorized_strava (bool, optional): Flag stating if the user has revoked Strava access. Defaults to False.
    """
    
    # Get all of this user's StavaActivities and delete them.
    all_acts = StravaActivity.objects.filter(site_user=user)
    all_acts.all().delete()
    # Now indicate that the user hasn't completed the initial download.
    su = user.stravauser
    su.has_completed_initial_download = False
    # Remove stored Strava authorization info if the user has revoked access.
    if deauthorized_strava :
        su.is_strava_verified = False
        # Also remove the social auth record
        soc = user.social_auth
        strava_soc = soc.get(provider='strava')
        strava_soc.delete()
    su.save()
    
def compute_metrics(acts_qs) :
    """
    Compute varous metrics for a Strava activity type.

    Args:
        acts_qs (QuerySet): QuerySet of StravaActivities of a single type

    Returns:
        dict: dictionary of metrics
    """
    
    summary_dict = {}
    num_acts = acts_qs.count()
    summary_dict["num_acts"] = num_acts
    if num_acts > 0 :
        total_dist_m = acts_qs.aggregate(Sum('distance_meters')).get("distance_meters__sum")
        summary_dict["tot_dist_miles"] = '{:,}'.format(round(total_dist_m * 0.000621371,2))
        summary_dict["tot_dist_km"] = '{:,}'.format(round(total_dist_m / 1000, 2))
        summary_dict["avg_dist_miles"] = '{:,}'.format(round((total_dist_m * 0.000621371)/summary_dict["num_acts"],2))
        summary_dict["avg_dist_km"] = '{:,}'.format(round((total_dist_m/1000)/summary_dict["num_acts"],2))
        longest_distance_activity = acts_qs.order_by('-distance_meters')[0]
        summary_dict["greatest_dist_miles"] = '{:,}'.format(round(longest_distance_activity.distance_miles))
        summary_dict["greatest_dist_km"] = '{:,}'.format(round(longest_distance_activity.distance_km))
        summary_dict["greatest_dist_date"] = (longest_distance_activity.activity_id, longest_distance_activity.start_date_local.date)
        tot_elev_gain = acts_qs.aggregate(Sum('total_elevation_gain_m')).get("total_elevation_gain_m__sum")
        summary_dict["tot_elev_gain_m"] = '{:,}'.format(round(tot_elev_gain, 2))
        summary_dict["tot_elev_gain_feet"] = '{:,}'.format(round(tot_elev_gain * 3.28084, 2))
        summary_dict["tot_elev_gain_miles"] = '{:,}'.format(round(tot_elev_gain * 3.28084/5280, 2))
        summary_dict["tot_elev_gain_km"] = '{:,}'.format(round(tot_elev_gain / 1000,2))
        tot_dur_sec = acts_qs.aggregate(Sum('elapsed_time_sec')).get('elapsed_time_sec__sum')
        avg_dur_sec = acts_qs.aggregate(Avg('elapsed_time_sec')).get('elapsed_time_sec__avg')
        summary_dict["tot_dur_hours"] = '{:,}'.format(round(tot_dur_sec / 3600, 2))
        summary_dict["tot_dur_days"] = '{:,}'.format(round(tot_dur_sec / (3600 * 24),2))
        summary_dict["avg_dur_min"] = '{:,}'.format(round(avg_dur_sec / 60, 2))
        tot_moving_s = acts_qs.aggregate(Sum('moving_time_sec')).get('moving_time_sec__sum')
        avg_moving_s = acts_qs.aggregate(Avg('moving_time_sec')).get('moving_time_sec__avg')
        summary_dict["tot_moving_time_hours"] = '{:,}'.format(round(tot_moving_s / 3600,2))
        summary_dict["tot_moving_time_days"] = '{:,}'.format(round(tot_moving_s / (3600*24), 2))
        summary_dict["avg_mov_time_min"] = '{:,}'.format(round(avg_moving_s / 60))
        avg_speed_mps = total_dist_m / tot_moving_s
        summary_dict["avg_speed_mph"] = '{:,}'.format(round(avg_speed_mps * 2.23694, 2))
        summary_dict["avg_speed_kph"] = '{:,}'.format(round(avg_speed_mps * 3.6,2))
        summary_dict["max_speed_mph"]  = '{:,}'.format(round(acts_qs.aggregate(Max('max_speed_mph')).get("max_speed_mph__max"),2))
        summary_dict["max_speed_kph"]  = '{:,}'.format(round(acts_qs.aggregate(Max('max_speed_kph')).get("max_speed_kph__max"),2))
        fastest = acts_qs.order_by('-max_speed_mps')[0]
        summary_dict["max_speed_date"] = (fastest.activity_id, fastest.start_date_local.date)
        summary_dict["max_elev_gain_ft"] = '{:,}'.format(round(acts_qs.aggregate(Max('elev_gain_ft')).get('elev_gain_ft__max'),2))
        summary_dict["max_elev_gain_m"] = '{:,}'.format(round(acts_qs.aggregate(Max('total_elevation_gain_m')).get('total_elevation_gain_m__max'),2))
        most_gain = acts_qs.order_by('-total_elevation_gain_m')[0]
        summary_dict["max_elev_gain_date"] = (most_gain.activity_id, most_gain.start_date_local.date)
        summary_dict["max_hr"] = acts_qs.aggregate(Max("max_heartrate")).get('max_heartrate__max')
        max_hr = acts_qs.order_by('-max_heartrate')[0]
        summary_dict["max_hr_date"] = (max_hr.activity_id, max_hr.start_date_local.date)
    else :
        summary_dict["tot_dist_miles"] = str(0.0)
        summary_dict["tot_dist_km"] = str(0.0)
        summary_dict["avg_dist_miles"] = str(0.0)
        summary_dict["avg_dist_km"] = str(0.0)
        summary_dict["greatest_dist_miles"] = str(0.0)
        summary_dict["greatest_dist_km"] = str(0.0)
        summary_dict["greatest_dist_date"] = ("#", "")
        summary_dict["tot_elev_gain_m"] = str(0.0)
        summary_dict["tot_elev_gain_feet"] = str(0.0)
        summary_dict["tot_elev_gain_miles"] = str(0.0)
        summary_dict["tot_elev_gain_km"] = str(0.0)
        summary_dict["tot_dur_hours"] = str(0.0)
        summary_dict["tot_dur_days"] = str(0.0)
        summary_dict["avg_dur_min"] = str(0.0)
        summary_dict["tot_moving_time_hours"] = str(0.0)
        summary_dict["tot_moving_time_days"] = str(0.0)
        summary_dict["avg_mov_time_min"] = str(0.0)
        summary_dict["avg_speed_mph"] = str(0.0)
        summary_dict["avg_speed_kph"] = str(0.0)
        summary_dict["max_speed_mph"]  = str(0.0)
        summary_dict["max_speed_kph"]  = str(0.0)
        summary_dict["max_speed_date"] = ("#", "")
        summary_dict["max_elev_gain_ft"] = str(0.0)
        summary_dict["max_elev_gain_m"] = str(0.0)
        summary_dict["max_elev_gain_date"] = ("#", "")
        summary_dict["max_hr"] = str(0)
        summary_dict["max_hr_date"] = ("#", "")
    return summary_dict
    
def suggest_similar_activities(request, *, elev_gain=None, distance=None, dist_fudge=0.1, elev_fudge=0.1, metric=False, activity_type="Ride", 
                               activity_title_key=None, time_fudge=0.1, elapsed_time=None, moving_time=None, start_date=None, end_date=None) :
    """
    Take an elevation gain and/or a distance and return a list of URLs of your past Strava activities
    that have similar elevation gain and/or distance.

    The fudge factors let you define the degree of similarity. The defaults are 0.1.
    The default units are feet of elevation gain and miles of distance, but if you set
    the metric flag to True, the units are meters of elevation gain and kilometers of
    distance. Finally, the default activity is Ride. To specify a different activity type,
    set the activity_type parameter to it. Just make sure you name it the same as Strava does.

    Args:
        request (HttpRequest): the request that brought us to the view that called this helper
        elev_gain (float, optional): the elevation gain you want a suggestion for. Defaults to None.
        distance (float, optional): the distance you want a suggestion for. Defaults to None.
        dist_fudge (float, optional): defines what it means for a ride to have a similar distance to another. Defaults to 0.1.
        elev_fudge (float, optional): defines what it means for a ride to have a similar elevation gain to another. Defaults to 0.1.
        metric (bool, optional): flag that specifies whether to use the metric system. Defaults to False.
        activity_type (str, optional): the activity type that you are interested in. Defaults to "Ride".
        activity_title_key (str, optional): title of the Strava activity. Defaults to None.
        time_fudge (float, optional): how similar in duration two activities are. Defaults to 0.1.
        elapsed_time (float, optional): elapsed time of activity. Defaults to None.
        moving_time (float, optional): moving time of activity. Defaults to None.
        start_date (DateTime, optional): date to start searching from. Defaults to None.
        end_date (_type_, optional): date to end the search. Defaults to None.

    Returns:
        list: list of URL's to Strava activities
    """
    
    # Start with all of the user's activites. that are of this type.
    acts_qs = StravaActivity.objects.filter(site_user=request.user)
    # You need to have something to search for. Otherwise just return None.
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
        acts_qs = acts_qs.filter(start_date_local__date__gte=start_date)
    if end_date :
        acts_qs = acts_qs.filter(start_date_local__date__lte=end_date)
        
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
            info["date"] = a.start_date_local
            results_list.append(info)
    return results_list

def get_monthly_charts_data(request, act_type, metric) :
    """
    Produce data for monthly bar charts.

    Args:
        request (HttpRequest): the request that brought us here
        act_type (str): name of Strava activity
        metric (str): the metric we will be charting (distance, elevation gain, moving time)

    Returns:
        JsonResponse: JsonResponse containing the chart data
    """
    
    title_text = "Problem in monthly" # Should never see this string in a chart. It's a sanity check.
    scale_title = "Dude, really" # Ditto
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
    acts_qs = acts_qs.filter(sport_type=act_type)
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
    
def get_annual_chart_data(request, act_type, metric) :
    """
    Produce data for annual bar charts.

    Args:
        request (HttpRequest): the request that brought us here
        act_type (str): name of Strava activity
        metric (str): the metric we will be charting (distance, elevation gain, moving time)

    Returns:
        JsonResponse: JsonResponse containing the chart data
    """
    title_text = "Problem in annual" # Should never see this string in a chart. It's a sanity check.
    scale_title = "Dude, really" # Ditto
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
    acts_qs = acts_qs.filter(sport_type=act_type)
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
        logger.warning("here's the dict: " + str(acts_qs))
    elif metric == "elevation_gain" :
        if request.user.stravauser.preferred_units == "imperial" :
            acts_qs = acts_qs.values("start_date__year").annotate(metric_per_year=Sum('elev_gain_ft')).order_by('start_date__year')
        else :
            acts_qs = acts_qs.values("start_date__year").annotate(metric_per_year=Sum('total_elevation_gain_m')).order_by('start_date__year')

    for a in acts_qs :
        data.append(a['metric_per_year'])
    datasets.append(data)
    color = request.user.stravauser.pie_color_palette[act_type]
    
    return JsonResponse(data={
        'labels': labels,
        'datasets' : datasets,
        'single_label': data_label,
        'title_text' : title_text,
        'scale_title' : scale_title,
        'color': color
    })        

def get_base_context(request) :
    """
    Return a dictionary with some basic context info that every page needs.

    Args:
        request (HttpRequest): the request that brough us to the view that called this function

    Returns:
        dict: basic context info
    """
    context = {}
    context["type_list"] = get_strava_activity_type_list(request.user)
    context["metric"] = "distance"
    return context

# def download_strava_data_iter(request, start_from=None) :
#     t = loader.get_template('strava_info/downloading_strava_data.html')
#     context = get_base_context(request)
#     context["user"] = request.user
#     yield t.render(context)
    
#     su = request.user.stravauser
    
#     # Here need to get the user's access and refresh tokens from the DB.
#     # If access_token has expired, use the refresh_token to get the new access_token
#     try :
#         check_and_refresh_access_token(su)
#     except requests.exceptions.RequestException as e :
#         messages.error(request, "Encountered an exception trying to refresh tokens.")
#         raise(e)
    
#     page = 1
#     url = "https://www.strava.com/api/v3/activities"
#     if not start_from :
#         # Parse the start date by parsing it into a Datetime object.
#         # Set the timezone to UTC
#         start_date = "January 1, 1970"
#         startDT = parser.parse(start_date)
#         timezone = pytz.timezone("UTC")
#         startDT = timezone.localize(startDT)
#     else :
#         startDT = start_from
#     start_stamp = str(int(startDT.timestamp()))
#     results = []
#     while True:        
#         # get page of activities from Strava
#         # We're going to get 200 at a time.
#         #payload = {'access_token': su.access_token, 'after': start_stamp, 'before': end_stamp, 'per_page' : '200', 'page': str(page)}
#         payload = {'access_token': su.access_token, 'after': start_stamp, 'per_page' : '200', 'page': str(page)}
#         try:
#             r = requests.get(url, params = payload)
#         except requests.exceptions.RequestException as e:
#             messages.error(request, "Encountered an exception downloading data.")
#             raise(e)
#         r = r.json()
#         # If no results, then exit loop
#         if (not r):
#             break
#         results = results + r
#         # increment page.
#         page += 1
#         yield "Working..."

#     # Now that you have it all, save it.
#     save_strava_data(results, request.user)
#     su.has_completed_initial_download = True
#     su.save()
#     # Here we need to update the user's pie chart color dictionary.
#     su.pie_color_palette = compute_pie_colors(request.user)
#     su.save()

#     if not start_from :
#         messages.success(request, "Sucessfully downloaded!")
#     else :
#         messages.success(request, "Sucessfully updated! Found " + str(len(results)) + " new activities.")

#     yield "Click the home button<br>"

def send_strava_webhook_subscription_request() :
    """Send a webhood subscription to Strava.
    """

    subscribe_url = "https://www.strava.com/api/v3/push_subscriptions"
    callback_url = settings.STRAVA_CB_URL
    verify_token = settings.STRAVA_SUB_VERIFY_TOKEN
    payload = {'client_id': settings.SOCIAL_AUTH_STRAVA_KEY,
            'client_secret': settings.SOCIAL_AUTH_STRAVA_SECRET,
            'callback_url' : callback_url,
            'verify_token' : verify_token}
    try :
        #logger.warning("Subscribe: Sending subscription request")
        response = requests.post(url=subscribe_url, 
                                data=payload)
        #logger.warning("Subscribe: Got a response")
    except requests.exceptions.RequestException as e :
        raise(e)
    else :
        # Now get the subscription id and save the subscription
        # to the database.
        r = response.json()
        #logger.warning("Subscribe got this reponse " + str(r))
        if not r.get("errors") :
            sub = WebhookSubscription()
            sub.service = "Strava"
            sub.sub_id = r["id"]
            sub.save()
            
def async_handle(event) :
    """
    Handle a webhook event in a separate thread (started in the calling function).

    Args:
        event (dict): data from the webhook
    """
    
    #subscription_id = event["subscription_id"]
    aspect_type = event.get("aspect_type") # 'create', 'update', or 'delete'
    #event_time = event.get("event_time") # When the event occured.
    object_id = event.get("object_id") # Activity ID if activity, athlete id if athlete.
    object_type = event.get("object_type") # 'activity' or 'athlete'
    owner_id = event.get("owner_id") # Athlete id
    updates = event.get("updates") # Dictionary. For activity update events, keys can contain "title," "type," and "private,"
                                # which is always "true" (activity visibility set to Only You) or "false"
                                # (activity visibility set to Followers Only or Everyone). For app deauthorization events,
                                # there is always an "authorized" : "false" key-value pair.
    # Check if any of those are None
    # if not aspect_type :
    #     logger.warning("aspect_type is None.")
    # if not object_id :
    #     logger.warning("object_id is None.")
    # if not object_type :
    #     logger.warning("object_type is None.")
    # if not owner_id :
    #     logger.warning("owner_id is None.")
    # if not updates :
    #     logger.warning("updates is None.")
    # Check tokens.
    # Need to get the user with the owner_id.
    u_id = UserSocialAuth.objects.filter(provider="strava", uid=owner_id)[0].user_id
    site_user = User.objects.filter(id=u_id)[0]
    strava_login = site_user.social_auth.get(provider='strava')
    #strava_user = site_user.stravauser
    
    # Deal with activities 
    if object_type == "activity" :
        # Deal with creating a new activity.
        logger.warning("Dealing with an activity update")
        if aspect_type == "create" :
            logger.warning("New event created at Strava")
            # Get the new activity.
            # try :
            #     check_and_refresh_access_token(site_user)
            # except requests.exceptions.RequestException as e :
            #     raise(e)
            url = "https://www.strava.com/api/v3/activities/"+str(object_id)
            payload = {'access_token': strava_login.extra_data["access_token"]}
            # If we make the request very quickly after receiving the webhook,
            # we get an invalid response that has a null activity id.
            # If that happens, wait 6 seconds and try again. Try that at most 10 times.
            # That's just an arbitary amount of time on my part.
            for i in range(0,10) :
                try:
                    check_and_refresh_access_token(site_user)
                    r = requests.get(url, params = payload)
                except requests.exceptions.RequestException as e:
                    raise(e)
                r = r.json()
                if not r.get("id") :
                    # Wait 6 seconds and try again
                    time.sleep(6)
                else :
                    break
            logger.warning("Got the new activity with dict = " + str(r))
            if not r.get("id") :
                logger.warning("Handling still got a null id. Not saving the activity.")
            else :
                save_strava_activity(r, site_user)
                # Also need to recompute pie chart colors because we may be
                # downloading an activity we haven't seen before.
                site_user.stravauser.pie_color_palette = compute_pie_colors(site_user)
                site_user.stravauser.save()
        elif aspect_type == "update" :
        #    logger.warning("update to existing event")
            act = StravaActivity.objects.get(site_user=site_user, activity_id=object_id)
            if updates.get("title") :
                # Get the currently saved version of this activity
                act.name=updates["title"]
            if updates.get("type") :
                act.type=updates["type"]
                act.sport_type=updates["type"]
            act.save()
        elif aspect_type == "delete" :
         #   logger.warning("deleting existing activity")
            act = StravaActivity.objects.get(site_user=site_user, activity_id=object_id)
            act.delete()
    elif object_type == "athlete" :
        if aspect_type == "update" :
            logger.warning("Got an athlete update webhook")
            if updates.get("authorized") :
                logger.warning("Deauthorization")
                if updates["authorized"] == "false":
                    # We need to record that the user has deauthorized
                    # the app from looking at their data.
                    logger.warning("Removing user's strava data")
                    remove_user_strava_data(site_user, True)                
    