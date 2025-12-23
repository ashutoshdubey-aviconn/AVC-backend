#!/bin/sh
cd /home/ubuntu/django_project
source virtualWarehouse/bin/activate
python manage.py runserver 0.0.0.0:8001
