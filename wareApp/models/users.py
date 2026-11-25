"""Users, groups and one-time passwords."""

from django.contrib.auth.models import AbstractUser
from django.contrib.auth.models import Group
from django.db import models
from django.db.models.signals import post_save
from django.db.models.signals import pre_save


class User(AbstractUser):
    """Login user with a user type (Super Admin, Aviconn Admin / Executive, Customer, Site Manager, AVC
    Super Admin) and the customer it belongs to.

    Origin: Ashu (changed from main)
    """
    user_type = (
        (1, "Super_Admin"),
        (2, "Aviconn_Admin"),
        (3, "Aviconn_Executive"),
        (4, "Customer"),
        (5, "Cust_Site_Manager"),
    )
    # Least privilege: a user created without a type is a Customer (it used to
    # default to Super_Admin, which also grants admin-site access).
    UserType = models.PositiveIntegerField(default=4, choices=user_type)
    Contact_number = models.CharField(
        max_length=15, help_text="Enter the contact number"
    )


def Create_Group(sender, instance, *args, **kwargs):
    """Make sure the group of a new user's type exists (it used to be created
    only when it already existed, which raised IntegrityError).

    Origin: Ashu (changed from main)
    """
    if instance._state.adding:
        Group.objects.get_or_create(name=instance.get_UserType_display())


def Add_group_to_user(sender, instance, *args, update_fields=None, **kwargs):
    """Put the user in the group of its type; Super_Admin users get admin access.

    Skipped for saves that only touch last_login (every login).

    Origin: Ashu (changed from main)
    """
    if update_fields is not None and set(update_fields) <= {"last_login"}:
        return
    if instance.UserType == 1 and not instance.is_staff:
        User.objects.filter(pk=instance.pk).update(is_staff=True)
    instance.groups.set(Group.objects.filter(name=instance.get_UserType_display()))


post_save.connect(Add_group_to_user, sender=User)


pre_save.connect(Create_Group, sender=User)


class OTP(models.Model):
    """Table wareApp_otp: o t p. Fields: otp, user_id, created.

    Origin: Ashu (changed from main)
    """
    otp = models.CharField(blank=True, null=True, max_length=5)
    user_id = models.PositiveIntegerField(default=0)
    created = models.DateTimeField(auto_now=False, auto_now_add=True)

    def __str__(self):
        """Text for this row in admin and logs: 'OTP {} on {}'.format(self.otp, self.created).

        Origin: main (unchanged)
        """
        return "OTP  {} on {}".format(self.otp, self.created)
