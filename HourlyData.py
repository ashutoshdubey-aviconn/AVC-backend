import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "warehouse.settings")
import django
django.setup()
from wareApp.models import *
from datetime import datetime, timedelta
import csv
from openpyxl import Workbook

def getHourlyData(start, end):
    start = datetime.strptime(start + " 0:0:0", "%d-%m-%Y %H:%M:%S")
    end = datetime.strptime(end + " 0:0:0", "%d-%m-%Y %H:%M:%S")+timedelta(days=1)
    DataReading = HourlySiteReading.objects.filter(associated_Site_id = 150, reading_from__range = (start, end), reading_to__range = (start, end))
    return DataReading


def generate_data(dataset):
    data = {}
    for i in dataset:
        aisleGroup = i.aisle_group_id
        date = str(i.reading_from.date())
        unitConsumption = i.unit_consumption
        hour = i.reading_from.hour
        if date not in data.keys():
            data[date] = {}
        if aisleGroup not in data[date].keys():
            data[date][aisleGroup] = {}
        data[date][aisleGroup][f'{hour}:00'] = unitConsumption
    return data

def write_data_to_excel(data):
    # Create a new Workbook
    workbook = Workbook()

    # Iterate over dates in the data dictionary
    for date, aisle_data in data.items():
        # Create a new sheet for each date
        sheet = workbook.create_sheet(title=date)
        
        # Write headers for aisle groups ID and hourly data
        sheet['A1'] = 'Aisle Group ID'
        for hour in range(24):
            sheet.cell(row=1, column=hour + 2, value=str(hour).zfill(2) + ':00')  # Write hourly headers
        
        # Write data to the sheet
        row_index = 2  # Start writing data from row 2
        for aisle_id, hourly_data in aisle_data.items():
            print(hourly_data)
            sheet.cell(row=row_index, column=1, value=AisleGroup.objects.get(id = aisle_id).aisleGroupName)  # Write aisle group ID
            # Write hourly data
            for hour in range(24):
                hour_str = str(hour) + ':00'  # Hour string in format "00:00"
                value = hourly_data.get(hour_str, 0.0) # Get hourly value for the hour
                print(value)
                sheet.cell(row=row_index, column=hour + 2, value=round(value,2))  # Write value to corresponding column
            row_index += 1

    # Remove the default sheet created by openpyxl
    workbook.remove(workbook['Sheet'])

    # Save workbook to a file
    workbook.save('output_excel_file.xlsx')
    pass

def main():
    start = input("enter start date (dd-mm-yyyy) ")
    end = input("enter end date (dd-mm-yyyy) ")
    dataset = getHourlyData(start, end)
    data = generate_data(dataset)
    write_data_to_excel(data)

main()

