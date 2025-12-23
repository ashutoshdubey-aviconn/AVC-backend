import os
from prettytable import PrettyTable
import subprocess
import json
from datetime import datetime
import time
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "warehouse.settings")
import django
django.setup()
import psycopg2
import sys
import paho.mqtt.client as mqtt
import logging
from wareApp.views import *

def commandValidate(rssh_port):
    try:
        check_port_cmd = 'netstat -plant | grep {}'.format(rssh_port)
        output_bytes = subprocess.check_output(check_port_cmd,shell=True)
        output = output_bytes.decode('utf-8')
        print("output>>>>>>", output)
        if 'LISTEN' in output:
            command = f'sudo fuser -k {rssh_port}/tcp'
            os.system(command)

       	    print("listen mode")
        else:
            pass
    except:
        pass
def rssh():
    site= HomeGatewayId.objects.all().prefetch_related('connected_to').order_by('id')
    #print(site)
    x = PrettyTable(padding_width=4,left_padding_width=7)
    x.field_names = ["S.no","ID",  "SITE_LOCATION",  "HGW_ID",  "RSSH_PORT",  "MONITORING_PORT"]
    for index, i in enumerate(site, start=1):
        x.add_row([index,i.connected_to.id,i.connected_to.location,i.hgw_id,i.rssh_port,i.monitoring_port])
    print(x)
    gateway_id = int(input('enter serial no.---> '))
    s=list(site)    
    indexx=gateway_id - 1
    hgw_id=x[indexx][0]  
    c = site[indexx].__dict__
    print(c)
    hgwId = c['hgw_id']
    print("hgw_Id : ", c['hgw_id'])
    locId = c['connected_to_id']
    rssh_port = c["rssh_port"]
    print("location_Id : ", c['connected_to_id'])
    
    print('SELECT 1 or 2 FROM OPTIONS')
    print(' #######   Options  ########  \n')
    print(' 1. Start autossh ')
    print(' 2. Stop autossh ')
    print(' 3. Restart gateway rssh  service through mqtt ')
    autossh_options = int(input("Enter your choice from ID---> "))
    if autossh_options == 1:
        commandValidate(rssh_port)
        value = 'mosquitto_pub -p 1883 -t "/Acclivate/iOmniControl/{}/{}/in/remoteAccess/state" -m "start_1"'.format(
            locId, hgwId)
        os.system(value)
        print("Connecting to gateway....")
        time.sleep(3)
        cmd = 'ssh -p {} odroid@localhost'.format(rssh_port)
        os.system(cmd)
    elif autossh_options == 2:
        value = 'mosquitto_pub -p 1883 -t "/Acclivate/iOmniControl/{}/{}/in/remoteAccess/state" -m "stop_1"'.format(
            locId, hgwId)
        os.system(value)
    elif autossh_options == 3:
        value = 'mosquitto_pub -p 1883 -t "/Acclivate/iOmniControl/{}/{}/in/remoteAccess/state" -m "restart_1"'.format(
            locId, hgwId)
        os.system(value)
    else:
        print("you have choose wrong option")
        exit(1)


if __name__ == "__main__":
     rssh()

