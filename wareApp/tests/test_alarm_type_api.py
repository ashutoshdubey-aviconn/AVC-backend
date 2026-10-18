from unittest.mock import Mock, patch

from django.test import SimpleTestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from wareApp.views import SuperUserAllAlarmsTypeBasedOnCustomersList


class AlarmTypeApiAuthorizationTests(SimpleTestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.view = SuperUserAllAlarmsTypeBasedOnCustomersList.as_view()

    def test_anonymous_user_is_rejected(self):
        response = self.view(self.factory.post("/alarmTypeApi/", {}, format="json"))

        self.assertEqual(response.status_code, 401)

    def test_non_super_admin_is_forbidden(self):
        request = self.factory.post("/alarmTypeApi/", {}, format="json")
        force_authenticate(request, user=Mock(UserType=4, is_authenticated=True))

        response = self.view(request)

        self.assertEqual(response.status_code, 403)

    def test_super_admin_can_access_alarm_types(self):
        request = self.factory.post("/alarmTypeApi/", {}, format="json")
        force_authenticate(request, user=Mock(UserType=1, is_authenticated=True))

        with patch("wareApp.views.User.objects.filter", return_value=[]):
            response = self.view(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {"data": []})