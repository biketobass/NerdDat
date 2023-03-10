from django.urls import path, include
from . import views
from django.conf import settings

app_name = 'strava_info'
urlpatterns = [
    #path('', views.strava_index, name='strava_index'),
    path('get_strava_data', views.get_strava_data, name='get_strava_data'),
    path('update_strava_data', views.update_strava_data, name='update_strava_data'),
    path('delete_strava_data', views.delete_strava_data, name='delete_strava_data'),
    path('analyze_activity_type/<str:act_type>', views.analyze_activity_type, name='analyze_activity_type'),
    path('switch_units', views.switch_units, name='switch_units'),
    path('search_strava_data', views.search_strava_data, name='search_strava_data'),
    #path('charts/<str:act_type>/<str:metric>/<str:time_span>', views.charts, name='charts'),
    path('charts/<str:act_type>/<str:metric>', views.charts, name='charts'),
    path('annual_charts', views.annual_charts, name='annual_charts'),
    path('annual_pie_chart_data/<int:year>', views.annual_pie_chart_data, name='annual_pie_chart_data'),
    #path('annual_charts/<str:act_type>', views.annual_charts, name='annual_charts'),
    #path('monthly_charts/<str:act_type>/<str:metric>', views.monthly_charts, name='monthly_charts'),
    #path('monthly_charts_data/<str:act_type>/<str:metric>', views.monthly_charts_data, name='monthly_charts_data'),
    path('charts_data/<str:act_type>/<str:metric>/<str:time_span>', views.charts_data, name='charts_data'),
    path('pie_chart_data', views.pie_chart_data, name='pie_chart_data'),
    path('strava_settings', views.strava_settings, name='strava_settings'),
    path('subscribe_to_strava_webhooks', views.subscribe_to_strava_webhooks, name='subscribe_to_strava_webhooks'),
    path('unsubscribe_strava_webhooks', views.unsubscribe_strava_webhooks, name='unsubscribe_strava_webhooks'),
    path('webhooks/'+settings.STRAVA_CB_LONG_PART, views.handle_strava_webhook, name='handle_strava_webhook'),
]