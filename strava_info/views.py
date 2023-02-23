from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.contrib import messages
from django.db.models import Sum, Max, Min, Avg
from django.http import JsonResponse, HttpResponse, HttpResponseForbidden
import requests
from .models import StravaUser, StravaActivity, WebhookSubscription
from .forms import ImperialStravaSearchForm, MetricStravaSearchForm
from django.conf import settings
from dateutil import parser
import pytz
import django.template.loader as loader
import threading
from social_django.models import UserSocialAuth
import logging
import json
from .strava_helpers import download_strava_data, remove_user_strava_data, compute_metrics, compute_pie_colors, get_strava_activity_type_list, suggest_similar_activities, check_and_refresh_access_token, save_strava_activity, save_strava_data, get_monthly_charts_data, get_annual_chart_data, get_base_context, send_strava_webhook_subscription_request, async_handle

logger = logging.getLogger(__name__)

def index(request) :
    """Generate the home page of the site.
    
    Checks if the user is authenticated with the site, if the user has
    gone through Strava's OAuth process, and if the user has completed
    the initial download of their Strava data. Based on the results
    of the checks it provides the appropriate context for the homepage.

    Args:
        request (HttpReqest): The request for the home page

    Returns:
        HttpResponse: The template and context for the index page.
    """
    user = request.user
    context = {}
    # See if the user has logged in.
    if user.is_authenticated :
        # The user has logged in. Now see if they have done the Strava OAuth.
        try :
            soc = user.social_auth
            strava_login = soc.get(provider='strava')
        except UserSocialAuth.DoesNotExist as e :
            # We know the user hasn't been through the OAuth process since
            # because we triggered the exception. No need to do anything.
            pass
        else :
            # The user has been through the Strava OAuth process.
            if strava_login :
                # I want there to be an expires_at field so add it to the strava_login extra_data.
                strava_login.extra_data["expires_at"] = strava_login.extra_data["auth_time"] + strava_login.extra_data["expires"]
                strava_login.save()
                # Now see if we have have created a stravauser yet for the user.
                try :
                    su = user.stravauser
                except StravaUser.DoesNotExist as e :
                    # We haven't created one yet, so do so and
                    # set the verified flag to true.
                    user.stravauser = StravaUser()
                    user.stravauser.is_strava_verified = True
                    #user.stravauser.token_type = strava_login.extra_data["token_type"]
                    #user.stravauser.access_token = strava_login.extra_data['access_token']
                    #user.stravauser.expires_at = strava_login.extra_data['expires_at']
                    #user.stravauser.expires_in = strava_login.extra_data['expires']
                    #user.stravauser.refresh_token = strava_login.extra_data['refresh_token']
                    user.stravauser.save()
                finally :
                    # Now that we have a stravauser for sure
                    su = user.stravauser
                    # Check if the su has been through Strava OAuth and has completed the initial download.
                    if su.is_strava_verified and su.has_completed_initial_download :
                        # Get the five (or fewer) most recent activities so that we can display them on the homepage.
                        all_acts = StravaActivity.objects.filter(site_user=user)
                        num2word = {0:"zero", 1:"one", 2:"two", 3:"three", 4:"four", 5:"five"}
                        most_recent = all_acts.order_by('-start_date')[0:5]
                        context = get_base_context(request)
                        context["most_recent"] = most_recent
                        context["num_recent"] = num2word[len(most_recent)]
                        # For Super user only:
                        if user.is_superuser :
                            # Figure out if we've subscribed to Strava webhooks yet.
                            all_subs = WebhookSubscription.objects.filter(service="Strava")
                            if all_subs :
                                sub_id = all_subs[0].sub_id
                                context["strava_web_subscribed"] = True
                                context["strava_web_sub_id"] = sub_id
                            else :
                                context["strava_web_subscribed"] = False
    return render(request, 'strava_info/index.html', context)
            

@login_required
def get_strava_data(request) :
    """
    Asynchronously retrieve the user's Strava Data.
    
    Spawns a new thread to do the API call and downloading so that the system
    does not block.

    Args:
        request (HttpRequest): the HttpRequest 

    Returns:
        HttpResponse: Redirect back to the index page.
    """
    try :
        # Start a new thread to do the API call and downloading. Call 
        # download_strava_data to do those.
        t = threading.Thread(target=download_strava_data, args=[request])
        t.setDaemon(True)
        t.start()
    except requests.exceptions.RequestException as e :
        # If there's a problem just redirect to the index.
        return redirect('index')
    else :
        # Set the downloading flag on stravauser to True. This let's the index page
        # know that it should display a message asking for patience while the download
        # takes place.
        su = request.user.stravauser
        su.downloading = True
        su.save()
    return redirect('index')


@login_required
def update_strava_data(request) :
    """
    Any new activities that may have been uploaded since initial download or last update.
    
    This function is no longer necessary because the application will be subscribed to Webhooks.
    Strava Webhooks push updates to the application which then handles them as needed.

    Args:
        request (HttpRequest): the http request that got us to this function

    Returns:
        HttpResponse: redirect to the index page
    """
    # Order the downloaded activities by start date with most recent first.
    most_recent_list = StravaActivity.objects.filter(site_user=request.user).order_by('-start_date')
    if not most_recent_list :
        messages.error(request, "You haven't downloaded any activities yet.")
        return redirect('index')
    # Now get the most recent one and it's date.
    most_recent = most_recent_list[0]
    most_recent_date = most_recent.start_date
    # We're only going to download activities that happened after that time.
    try :
        t = threading.Thread(target=download_strava_data, args=[request, most_recent_date])
        t.setDaemon(True)
        t.start()
    except requests.exceptions.RequestException as e :
        return redirect('index')
    else :
        su = request.user.stravauser
        # Have to let the app know that we're in the process of downloading
        # so that index can display the appropriate message.
        su.downloading = True
        su.save()
    return redirect('index')

@login_required
def delete_strava_data(request) :
    """
    Delete a user's stored Stava data.

    Args:
        request (HttpRequest): the request that got us to this view

    Returns:
        HttpResponse: the index page if POST, otherwise a confirmation page
    """
    
    if request.method == "POST" :
        user = request.user
        # Delete the date and redirect to index.
        remove_user_strava_data(user)
        messages.success(request, "Sucessfully deleted!")
        return redirect('index')    
    context = get_base_context(request)
    # Send to the confirmation page.
    return render(request, "strava_info/delete_strava_data.html", context)


@login_required
def analyze_activity_type(request, act_type) :
    """
    Compute various statistics about one of the User's activity types.

    Args:
        request (HttpRequest): the request that brought us to this view
        act_type (str): the name of the Strava activity

    Returns:
        HttpResponse: page containing the results
    """
    
    # Get the stravauser object associated with this user.
    su = request.user.stravauser
    # Get all of the user's Strava activites that are of this type.
    all_acts = StravaActivity.objects.filter(site_user=request.user, sport_type=act_type)
    # Get the first and last year, the user has been on Strava
    first_year = all_acts.aggregate(Min('start_date')).get('start_date__min').year
    last_year = all_acts.aggregate(Max('start_date')).get('start_date__max').year
    
    # Get the basic context needed by all pages in the app.
    context = get_base_context(request)
    
    # Calculate stats for each year
    context["act_type"] = act_type
    context["year_list"] = []
    for y in range(first_year, last_year+1) :
        year_acts = all_acts.filter(start_date__year=y)
        year_dict = compute_metrics(year_acts)
        year_dict["year"] = y
        context["year_list"].append(year_dict)
    
    summary_dict = compute_metrics(all_acts)

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
    
    return render(request, 'strava_info/activity.html', context)


        
@login_required
def switch_units(request) :
    """
    Switch from Imperial units to metric or vice versa.

    Args:
        request (HttpRequest): the request that brough us to this view

    Returns:
        HttpResponse: back to the calling URL
    """
    
    su = request.user.stravauser
    if su.preferred_units == "imperial" :
       su.preferred_units = "metric"
    else :
        su.preferred_units = "imperial"
    su.save()
    return redirect(request.META.get('HTTP_REFERER')) 

@login_required
def search_strava_data(request) :
    """
    Generate a list of Strava activities that meet criteria.

    Args:
        request (HttpRequest): the request that brough us to this view

    Returns:
        HttpResponse: the serach page
    """
    
    context = get_base_context(request)
    results = []
    type_list = get_strava_activity_type_list(request.user)
    if request.user.stravauser.preferred_units == "imperial" :
        form = ImperialStravaSearchForm(request.GET, type_choices=type_list)
    else :
        form = MetricStravaSearchForm(request.GET, type_choices=type_list)
    # Do the search if the search form is valid.
    # Otherwise, generate a clean form and send it to the search page.
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
    return render(request, 'strava_info/search_strava_data.html', context)
    

# @login_required
# def monthly_charts(request, act_type, metric) :
#     context = get_base_context(request)
#     context["act_type"] = act_type
#     context["metrics"] = ["distance", "moving_time", "elevation_gain"]
#     return render(request, 'strava_info/monthly_charts.html', context)

# @login_required
# def monthly_charts_data(request, act_type, metric) :
#     title_text = ""
#     scale_title = ""
#     if metric == "distance" :
#         title_text = "Monthly " + act_type + " Total " + metric.capitalize() + " Comparison"
#         scale_title = "Miles per month"
#     elif metric == "moving_time" :
#         title_text = "Monthly " + act_type + " Total Moving Time Comparison"
#         scale_title = "Hours per month"
    
#     acts_qs = StravaActivity.objects.filter(site_user=request.user)
#     acts_qs = acts_qs.filter(type=act_type)
#     start_year = acts_qs.aggregate(Min("start_date")).get("start_date__min").year
#     end_year = acts_qs.aggregate(Max("start_date")).get("start_date__max").year
#     labels = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
#     # For each year sum the metric in question in each month
#     datasets = []
#     years = []
#     for y in range(start_year, end_year+1) :
#         years.append(y)
#         qs = acts_qs.filter(start_date__year=y)
#         if metric == "distance" :
#             qs = qs.values("start_date__month").annotate(miles_per_month=Sum('distance_miles'))
#         elif metric == "moving_time" :
#             qs = qs.values("start_date__month").annotate(time_per_month=Sum('moving_time_sec'))
#         y_data_dict = {}
#         for q in qs :
#             if metric == "distance" :
#                 y_data_dict[q["start_date__month"]] = round(q['miles_per_month'],0)
#             elif metric == "moving_time" :
#                 y_data_dict[q["start_date__month"]] = round(q['time_per_month']/3600,0)
#         y_data = [y_data_dict[m] if m in y_data_dict else 0 for m in range(1,13) ]            
#         datasets.append(y_data)    
#     return JsonResponse(data={
#         'labels': labels,
#         'datasets' : datasets,
#         'years' : years,
#         'title_text' : title_text,
#         'scale_title' : scale_title
#     })
    
@login_required
def charts(request, act_type, metric) :
    """
    Render the bar charts page.

    Args:
        request (HttpRequest): the request that brought us here
        act_type (str): name of Strava activity
        metric (str): the metric we will be charting (distance, elevation gain, moving time)

    Returns:
        HttpResponse: the bar charts page
    """
    
    context = {}
    context["act_type"] = act_type
    context["metric"] = metric
    context["type_list"] = get_strava_activity_type_list(request.user)
    context["metrics"] = ["distance", "moving_time", "elevation_gain"]
    context["time_spans"] = ["monthly", "annual"]
    return render(request, 'strava_info/charts.html', context)

@login_required
def charts_data(request, act_type, metric, time_span) :
    """
    Produce data for bar charts.

    Args:
        request (HttpRequest): the request that brought us here
        act_type (str): name of Strava activity
        metric (str): the metric we will be charting (distance, elevation gain, moving time)
        time_span (str): annual or monthly

    Returns:
        JsonResponse: JsonResponse containing the chart data
    """
    
    if time_span == "annual" :
        resp = get_annual_chart_data(request, act_type, metric)
        logger.warning("Annual bar req response = " + str(resp.content))
        return resp
    elif time_span == "monthly" :
        resp = get_monthly_charts_data(request, act_type, metric)
        logger.warning("Monthly bar req response = " + str(resp.content))
        return resp
    else :
        return None
        

@login_required
def pie_chart_data(request) :
    """
    Produce json data for pie charts.

    Args:
        request (HttpRequest): the request that brought us to this view

    Returns:
        JsonResponse: Json data for the pie chart
    """
    
    acts_qs = StravaActivity.objects.filter(site_user=request.user)
    # For each activity type sum the moving time for that activity and compute the percentage that is of the whole.
    all_moving_time = acts_qs.aggregate(Sum('moving_time_sec')).get('moving_time_sec__sum')
    acts_qs = acts_qs.values("sport_type").annotate(total_moving_time=Sum('moving_time_sec'))
    data=[]
    labels=[]
    colors = []
    colors_dict = request.user.stravauser.pie_color_palette
    for a in acts_qs :
        perc = round((a['total_moving_time']/all_moving_time)*100)
        data.append(perc)
        labels.append(a["sport_type"])
        colors.append(colors_dict[a["sport_type"]])
    return JsonResponse(data={
        'data' : data,
        'labels' : labels,
        'title_text' : "Percentage of total moving time of each activity type you've ever recorded on Strava",
        'colors' : colors
    })

@login_required
def annual_charts(request) :
    """
    Render the pie charts page.

    Args:
        request (HttpRequest): the request that brough us to this view

    Returns:
        HttpResponse: the piecharts page
    """
    context = get_base_context(request)
    # We're going to want a pie chart for each year. That means we are going to create
    # a canvas in the html for each year. Get the list of years.
    acts_qs = StravaActivity.objects.filter(site_user=request.user)
    year_list = sorted(acts_qs.values_list("start_date__year", flat=True).distinct(), reverse=True)
    context["year_list"] = year_list
    return render(request, 'strava_info/piecharts.html', context)

    
@login_required
def annual_pie_chart_data(request, year) :
    """
    Generate the Json data for a pie charts for a particular year.

    Args:
        request (HttpRequest): the request that brought us here.
        year (int): the year in question

    Returns:
        JsonResponse: Json data for the pie chart
    """
    
    acts_qs = StravaActivity.objects.filter(site_user=request.user, start_date__year=year)
    # For each activity type sum the moving time for that activity and compute the percentage that is of the whole.
    all_moving_time = acts_qs.aggregate(Sum('moving_time_sec')).get('moving_time_sec__sum')
    acts_qs = acts_qs.values("sport_type").annotate(total_moving_time=Sum('moving_time_sec'))
    data=[]
    labels=[]
    colors = []
    colors_dict = request.user.stravauser.pie_color_palette
    #colors_dict = compute_pie_colors(request.user)
    for a in acts_qs :
        #data.append(round(a['total_moving_time']/all_moving_time))
        #data.append(round(a['total_moving_time']))
        perc = round((a['total_moving_time']/all_moving_time)*100)
        data.append(perc)
        labels.append(a["sport_type"])
        colors.append(colors_dict[a["sport_type"]])
    return JsonResponse(data={
        'data' : data,
        'labels' : labels,
        'title_text' : str(year) + " moving time percentages",
        'colors' : colors
    })
    
@login_required
def strava_settings(request) :
    """
    Return the settings page.

    Args:
        request (HttpRequest): the request that brought us to this view

    Returns:
        HttpResponse: the settings page
    """
    context = get_base_context(request)
    return render(request, 'strava_info/strava_settings.html', context)

@login_required 
def subscribe_to_strava_webhooks(request) :
    """
    Subscribe to Strava Webhooks.

    Args:
        request (HttpRequest): the request that brought us to this view

    Returns:
        HttpResponse: redirect back to index
    """
    
    # Only let a superuser do this.
    if request.user.is_superuser :
        #logger.warning("Subscribe starting thread.")
        t = threading.Thread(target=send_strava_webhook_subscription_request)
        t.setDaemon(True)
        t.start()
    return redirect('index')


@login_required 
def unsubscribe_strava_webhooks(request) :
    """
    Unsubscribe to Strava Webhooks.

    Args:
        request (HttpRequest): the request that brought us to this view

    Returns:
        HttpResponse: redirect back to index
    """
    
    # Only let a superuser do this.
    if request.user.is_superuser :
        deleted_subs = []
        all_subs = WebhookSubscription.objects.filter(service="Strava")
        for sub in all_subs :
            sub_id = sub.sub_id
            unsub_url = "https://www.strava.com/api/v3/push_subscriptions/"+str(sub_id)
            payload = {'client_id': settings.SOCIAL_AUTH_STRAVA_KEY,
                       'client_secret': settings.SOCIAL_AUTH_STRAVA_SECRET,
                       'id' : sub_id}
            try :
                response = requests.delete(url=unsub_url, 
                                        data=payload)
            except requests.exceptions.RequestException as e :
                raise(e)
            else :
                if response.status_code == 204 :
                    deleted_subs.append(sub_id)
        for sub_id in deleted_subs :
            WebhookSubscription.objects.filter(sub_id=sub_id).delete()
            #all_subs.all().delete()
    return redirect('index')
        

@require_http_methods(["GET", "POST"])
@csrf_exempt
def handle_strava_webhook(request) :
    """
    Handle an incoming Strava webhook

    Args:
        request (HttpRequest): request for this view

    Returns:
        HttpResponse: response to the webhook
    """
    
    #logger.warning("Handle webhook got this request " + str(request))
    if request.method == "GET" :
        # We're dealing with a response to our request for a
        # subscription. These are the only GET requests
        # Strava webhooks will make.
        validation_req = request.GET
        logger.warning("handle: validation_req is " + str(validation_req))
        mode = validation_req["hub.mode"]
        challenge = validation_req["hub.challenge"]
        hub_token = validation_req["hub.verify_token"]
        logger.warning("mode = " + mode + " challenge = " + challenge + " hub_token = " + hub_token)
        if (mode and hub_token) :
            if (hub_token == settings.STRAVA_SUB_VERIFY_TOKEN and
                mode == "subscribe") :
                response_data = {"hub.challenge":challenge}
                json_response = JsonResponse(data=response_data)
                logger.warning("handle sending this json response " + str(json_response))
                return json_response
        logger.warning("handle sending forbidden")
        return HttpResponseForbidden("not allowed")
    else :
        # We're dealing with a post which is an indication of
        # a webhook event.
        all_subs = WebhookSubscription.objects.filter(service="Strava")
        sub_id = all_subs[0].sub_id
        #event = request.POST
        event = json.loads(request.body)
        logger.warning("  body = " + str(event))
        if not event.get("subscription_id") or event["subscription_id"] != sub_id :
            logger.warning("Handle not allowing")
            return HttpResponseForbidden("Post not allowed")
        # We've come this far so handle the webhook.
        t = threading.Thread(target=async_handle, args=[event])
        t.setDaemon(True)
        t.start()
        return HttpResponse('success')
    

