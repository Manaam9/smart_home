""" File contains description of views. """


import json

import requests
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import FormView
from marshmallow import ValidationError
from requests import RequestException

from house import settings
from house.core.tasks import get_api, post_api, smart_home_manager
from .models import Setting
from .form import ControllerForm


class ControllerView(FormView):
    """ Controller View. Manages Controler`s logick. """

    form_class = ControllerForm
    template_name = 'core/control.html'
    success_url = reverse_lazy('form')
    states = {}

    # We get the data from the API (get_api method)
    def get_context_data(self, **kwargs):
        controller_url = settings.SMART_HOME_API_URL
        headers = {'Authorization': 'Bearer {}'.format(settings.SMART_HOME_ACCESS_TOKEN)}
        try:
            r = requests.get(controller_url, headers=headers)
        except RequestException:
            return HttpResponse('No connection to controllers API', status=502)
        if r.json()['status'] != 'ok':
            return HttpResponse('No connection to controllers API', status=502)

        api_data = r.json()
        states = dict()
        for d in api_data['data']:
            states[d['name']] = d['value']
        self.states = states  # save data from the API in a convenient way
        context = super(ControllerView, self).get_context_data()
        context['data'] = states
        return context

    # Initialize the form, take the temperature from the database, the data from the API (get_api method)
    def get_initial(self):
        return {"bedroom_target_temperature": Setting.objects.get(controller_name='bedroom_target_temperature').value,
                "hot_water_target_temperature": Setting.objects.get(controller_name='hot_water_target_temperature').value,
                "bedroom_light": self.states['bedroom_light'],
                "bathroom_light": self.states['bathroom_light']
                }

    # Validate the form, compare the data with the API
    def form_valid(self, form):
        return super(ControllerView, self).form_valid(form)

    # Override the form's get method
    def get(self, request, *args, **kwargs):
        try:
            get_api(**kwargs)
            return super(ControllerView, self).get(request, *args, **kwargs)
        except Exception:
            return HttpResponse('No connection to controllers API', status=502)

    # Override the form's post method
    def post(self, request, *args, **kwargs):
        self.get_context_data()
        form = self.get_form(self.form_class)
        if form.is_valid():
            to_controllers = []
            if self.states['bedroom_light'] != form.cleaned_data['bedroom_light']:
                to_controllers.append(
                    {'name': 'bedroom_light', 'value': form.cleaned_data['bedroom_light']})
            if self.states['bathroom_light'] != form.cleaned_data['bathroom_light']:
                to_controllers.append(
                    {'name': 'bathroom_light', 'value': form.cleaned_data['bathroom_light']})
            if len(to_controllers) != 0:
                to_controllers = {'controllers': to_controllers}
                post_api(json=to_controllers)  # Send data to API
                # Store values from valid form to database
                Setting.objects.filter(controller_name='bedroom_target_temperature').update(
                    value=form.cleaned_data['bedroom_target_temperature'])
                Setting.objects.filter(controller_name='hot_water_target_temperature').update(
                    value=form.cleaned_data['hot_water_target_temperature'])
            else:
                smart_home_manager()
            return super(ControllerView, self).post(request, *args, **kwargs)
        else:
            return HttpResponse('Invalid data!', status=502)

