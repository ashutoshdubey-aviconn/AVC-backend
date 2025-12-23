#!/bin/bash

cd /home/ubuntu/django_project/
. virtualwarehouse/bin/activate
celery -A warehouse worker -l info -c1 -Q queue1 -f /home/ubuntu/django_project/celerylogs/celery_logs_of_server.log -n worker1@%h
