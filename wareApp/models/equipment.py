"""Fire equipment inventory, lights and fans."""

from django.db import models
from .setup import Site


class FireEquipmentsSystemType(models.Model):
    site = models.ForeignKey(Site, on_delete=models.CASCADE, null=True, blank=True)
    devicename = models.CharField(max_length=30, null=True, blank=True)
    categories = models.CharField(max_length=30, null=True, blank=True)

    def __str__(self):
        return self.devicename


class FireEquipmentsSystem(models.Model):
    deviceType = models.ForeignKey(
        FireEquipmentsSystemType, on_delete=models.CASCADE, null=True, blank=True
    )
    assetNo = models.CharField(max_length=20, null=True, blank=True)
    modelNo = models.CharField(max_length=30, null=True, blank=True)
    loaction = models.CharField(max_length=30, null=True, blank=True)
    Warrenty_till = models.DateField(blank=True, null=True)
    last_service = models.DateField(blank=True, null=True)
    next_service = models.DateField(blank=True, null=True)
    updatedBy = models.CharField(max_length=25, blank=True, null=True)

    def __str__(self):
        return self.modelNo


class LightsData(models.Model):
    areaName = models.CharField(max_length=40, null=True, blank=True)
    totalLights = models.IntegerField(null=True, blank=True)
    watt_18_Lights = models.IntegerField(null=True, blank=True)
    watt_20_Lights = models.IntegerField(null=True, blank=True)
    watt_24_Lights = models.IntegerField(null=True, blank=True)
    watt_36_Lights = models.IntegerField(null=True, blank=True)
    watt_40_Lights = models.IntegerField(null=True, blank=True)
    totalWattLights = models.IntegerField(null=True, blank=True)
    totalUnits = models.FloatField(null=True, blank=True)

    def __str__(self):
        return self.areaName


class FansData(models.Model):
    areaName = models.CharField(max_length=40, null=True, blank=True)
    totalFans = models.IntegerField(null=True, blank=True)
    watt_80_Lights = models.IntegerField(null=True, blank=True)
    watt_100_Lights = models.IntegerField(null=True, blank=True)
    totalWattFans = models.IntegerField(null=True, blank=True)
    totalUnits = models.FloatField(null=True, blank=True)

    def __str__(self):
        return self.areaName
