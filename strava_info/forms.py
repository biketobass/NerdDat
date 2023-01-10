from django import forms
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Submit, Row, Column, Reset

class StravaSearchForm(forms.Form) :

    activity_types = []
        
    def __init__(self, *args, **kwargs) :
        choices = kwargs.pop("type_choices")
        activity_types = zip(choices, choices)
        super().__init__(*args, **kwargs)
        #self.fields['activity_type'] = forms.ChoiceField(required=True, label="Activity Type", choices=activity_types)
        self.fields['activity_type'] = forms.MultipleChoiceField(required=False, label="Activity Types", widget=forms.CheckboxSelectMultiple,
                                                                 choices=activity_types)
    
    activity_title = forms.CharField(max_length=100, required=False, label="Activity Title Keyword")
    #activity_type = forms.ChoiceField(required=True, label="Activity Type", choices=activity_types)
    elapsed_time_min = forms.IntegerField(min_value=0, required=False, label="Total Elapsed Time (min)")
    moving_time_min = forms.IntegerField(min_value=0, required=False, label="Moving Time (min)")
    start_date = forms.DateField(widget=forms.widgets.DateInput(attrs={'type': 'date'}), label="Start Date", required=False)
    end_date = forms.DateField(widget=forms.widgets.DateInput(attrs={'type': 'date'}), label="End Date", required=False)

class ImperialStravaSearchForm(StravaSearchForm) :
    distance = forms.DecimalField(min_value=0.0, required=False, label="Distance in Miles")
    elev_gain = forms.DecimalField(min_value=0.0, required=False, label="Elevation Gain in Feet")
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.layout = Layout(
            Row(
                Column('activity_type'),
                Column('activity_title'),
                Column('distance'),
                Column('elev_gain')
            ),
            Row(
                Column('start_date'),
                Column('end_date'),
                Column('elapsed_time_min'),
                Column('moving_time_min'),
            ),
            Submit('submit', 'Search'),
        )
    
class MetricStravaSearchForm(StravaSearchForm) :
    distance = forms.DecimalField(min_value=0.0, required=False, label="Distance in Kilometers")
    elev_gain = forms.DecimalField(min_value=0.0, required=False, label="Elevation Gain in Meters")
    