from __future__ import absolute_import, unicode_literals

import datetime

import requests
from celery import task
from django.core.mail import send_mail
from django.http import HttpResponse
from django.shortcuts import redirect
from requests import RequestException

from house import settings
from house.settings import EMAIL_RECEPIENT
from .models import Setting

leak_detector = False


# API reading method
def get_api(**kwargs):
    controller_url = settings.SMART_HOME_API_URL
    headers = {'Authorization': 'Bearer {}'.format(settings.SMART_HOME_ACCESS_TOKEN)}
    try:
        r = requests.get(controller_url, headers=headers)
    except RequestException:
        return HttpResponse('No connection to controllers API', status=502)
    if r.json()['status'] != 'ok':
        return HttpResponse('No connection to controllers API', status=502)
    # Get the answer, convert to json
    response = r.json()
    api_data = {}
    # Read data from the API for transmission to the ControllerView
    for controller in response['data']:
        api_data[controller['name']] = controller['value']
    return api_data


# Method to send data to API
def post_api(json, **kwargs):
    controller_url = settings.SMART_HOME_API_URL
    headers = {'Authorization': 'Bearer {}'.format(settings.SMART_HOME_ACCESS_TOKEN)}
    try:
        r = requests.post(controller_url, headers=headers, json=json)
    except RequestException:
        return HttpResponse('No connection to controllers API', status=502)
    if r.json()['status'] != 'ok':
        return HttpResponse('No connection to controllers API', status=502)


# Controller management. Warnings and precautions conditions.
@task()
def smart_home_manager():
    # Here is your verification code
    try:
        api_data = get_api()
    except Exception:
        return HttpResponse('No connection to controllers API', status=502)

    global leak_detector

    write_data = {}
    # 1 Water leakage in the house.
    if api_data['leak_detector']:
        write_data['cold_water'] = False
        write_data['hot_water'] = False
        write_data['boiler'] = False
        write_data['washing_machine'] = 'off'
        if not leak_detector:
            send_mail(
                'Leak detector',
                'Leak time detection {}.'.format(datetime.datetime.now()),
                'from@example.com',
                [EMAIL_RECEPIENT],
                fail_silently=False,
            )

    # 3 Boiler
    boiler_temperature = api_data['boiler_temperature']
    if boiler_temperature is not None:
        if boiler_temperature < (Setting.objects.get(controller_name='hot_water_target_temperature').value * 0.9):
            write_data['boiler'] = True
        elif boiler_temperature >= (Setting.objects.get(controller_name='hot_water_target_temperature').value * 1.1):
            write_data['boiler'] = False

    # 4.5 Illumination in the house.
    if api_data['curtains'] != 'slightly_open':
        outdoor_light = api_data['outdoor_light']
        if outdoor_light < 50 and not api_data['bedroom_light']:
            write_data['curtains'] = 'open'
        elif outdoor_light > 50 or api_data['bedroom_light']:
            write_data['curtains'] = 'close'

    # 7 Control the temperature in the bedroom. Air conditioning.
    bedroom_temperature = api_data['bedroom_temperature']
    if bedroom_temperature > (Setting.objects.get(controller_name='bedroom_target_temperature').value * 1.1):
        write_data['air_conditioner'] = True
    elif bedroom_temperature < (Setting.objects.get(controller_name='bedroom_target_temperature').value * 0.9):
        write_data['air_conditioner'] = False

    # 6 Smoke in the house.
    if api_data['smoke_detector']:
        write_data['washing_machine'] = 'off'
        for el in ['air_conditioner', 'bedroom_light', 'bathroom_light', 'boiler']:
            write_data[el] = False

    # 2 Cold water off.
    if not api_data['cold_water']:
        write_data['boiler'] = False
        write_data['washing_machine'] = 'off'

    # We iterate through the api_data dictionary and the write_data dictionary, form the data to be sent by the post method
    send_data = []
    for key, value in api_data.items():  # We look at the key from the value from api_data
        new_value = write_data.get(key)  # We look at the value from write_data by key
        if (new_value is not None) and (new_value != value):  # If the new value is not equal to the value with the API
            send_data.append({'name': key, 'value': new_value})  # Create a new list to send

    if len(send_data) > 0:
        to_controllers = {'controllers': send_data}
        post_api(to_controllers)  # Send data to API



