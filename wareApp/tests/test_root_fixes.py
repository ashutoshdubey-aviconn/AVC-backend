"""Fixes from the wareApp/warehouse root-file review.

Password reset (OTP not returned, expiry, single use), login serializer,
user/aisle signals, SiteLoadParameters.save, entryExit, sendmail settings,
and fuel-provider credentials.
"""

import base64
import io
from contextlib import redirect_stdout
from datetime import timedelta
from unittest import mock

from django.contrib.auth.models import Group
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from wareApp import fuel_providers, sendmail
from wareApp.models import OTP, AisleGroup, Site, SiteLoadParameters, User
from wareApp.serializers import LoginSerializer
from wareApp.utility import entryExit


class PasswordResetTests(TestCase):
    def setUp(self):
        cache.clear()  # throttles
        self.client = APIClient()
        self.user = User.objects.create_user(
            username="alice", email="alice@example.com", password="old-pass-123",
            Contact_number="9999999999", UserType=4,
        )

    def forgot(self):
        with mock.patch.object(sendmail, "_send_smtp_email", return_value=True) as send:
            response = self.client.post(
                "/api/forgot/",
                {"Username": "alice", "email": "alice@example.com", "mobile": "9999999999"},
                format="json",
            )
        return response, send

    def reset(self, otp, password="new-pass-456", **extra):
        return self.client.post(
            "/api/reset/", {"otp": otp, "newpassword": password, **extra}, format="json"
        )

    def test_forgot_does_not_return_the_otp(self):
        response, send = self.forgot()
        self.assertEqual(response.data["result"], 1)
        self.assertNotIn("otp", response.data)
        otp = OTP.objects.get(user_id=self.user.id).otp
        self.assertIn(otp, send.call_args.args[1])  # sent by e-mail only

    @override_settings(PASSWORD_RESET_RETURN_OTP=True)
    def test_old_clients_can_get_the_otp_back(self):
        response, _ = self.forgot()
        self.assertEqual(response.data["otp"], OTP.objects.get(user_id=self.user.id).otp)

    def test_new_request_replaces_the_previous_code(self):
        self.forgot()
        self.forgot()
        self.assertEqual(OTP.objects.filter(user_id=self.user.id).count(), 1)

    def test_valid_otp_resets_once(self):
        self.forgot()
        otp = OTP.objects.get(user_id=self.user.id).otp
        self.assertEqual(self.reset(otp).status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("new-pass-456"))
        self.assertFalse(OTP.objects.filter(user_id=self.user.id).exists())
        self.assertEqual(self.reset(otp, "another-789").status_code, 400)

    def test_expired_otp_is_rejected(self):
        self.forgot()
        code = OTP.objects.get(user_id=self.user.id)
        OTP.objects.filter(pk=code.pk).update(created=timezone.now() - timedelta(minutes=11))
        self.assertEqual(self.reset(code.otp).status_code, 400)

    def test_wrong_otp_and_wrong_username_are_rejected(self):
        self.forgot()
        otp = OTP.objects.get(user_id=self.user.id).otp
        wrong = f"{(int(otp) + 1) % 100000:05d}"
        self.assertEqual(self.reset(wrong).status_code, 400)
        self.assertEqual(self.reset(otp, username="bob").status_code, 400)
        self.assertEqual(self.reset(otp, username="alice").status_code, 200)

    def test_otp_is_five_digits(self):
        for _ in range(20):
            code = sendmail.line(5)
            self.assertRegex(code, r"^\d{5}$")


class LoginSerializerTests(TestCase):
    def setUp(self):
        User.objects.create_user(username="bob", password="secret-pass-1", UserType=4)

    def validate(self, password):
        out = io.StringIO()
        with redirect_stdout(out):
            serializer = LoginSerializer(data={"username": "bob", "password": password})
            valid = serializer.is_valid()
        return valid, out.getvalue()

    def test_valid_login_prints_nothing(self):
        valid, printed = self.validate(base64.b64encode(b"secret-pass-1").decode())
        self.assertTrue(valid)
        self.assertEqual(printed, "")

    def test_bad_base64_is_invalid_not_a_crash(self):
        valid, printed = self.validate("not base64!!")
        self.assertFalse(valid)
        self.assertEqual(printed, "")


class UserAndAisleSignalTests(TestCase):
    def test_new_user_defaults_to_customer_and_joins_its_group(self):
        user = User.objects.create_user(username="carol", password="x-pass-123")
        self.assertEqual(user.UserType, 4)
        self.assertFalse(User.objects.get(pk=user.pk).is_staff)
        self.assertTrue(Group.objects.filter(name="Customer").exists())
        self.assertEqual(list(user.groups.values_list("name", flat=True)), ["Customer"])

    def test_existing_group_does_not_break_user_creation(self):
        Group.objects.create(name="Customer")
        User.objects.create_user(username="dave", password="x-pass-123", UserType=4)
        self.assertEqual(Group.objects.filter(name="Customer").count(), 1)

    def test_super_admin_gets_admin_access(self):
        user = User.objects.create_user(username="root2", password="x-pass-123", UserType=1)
        self.assertTrue(User.objects.get(pk=user.pk).is_staff)

    def test_aisle_leg_id_set_on_create_and_kept_on_edit(self):
        site = Site.objects.create(site_name="S", site_type=1)
        aisle = AisleGroup.objects.create(site=site, aisleGroupName="A")
        aisle.refresh_from_db()
        self.assertEqual(aisle.attached_leg_id, str(aisle.id))
        aisle.attached_leg_id = "custom-7"
        aisle.save()
        aisle.refresh_from_db()
        self.assertEqual(aisle.attached_leg_id, "custom-7")

    def test_site_load_parameters_with_empty_phase(self):
        site = Site.objects.create(site_name="S2", site_type=1)
        row = SiteLoadParameters.objects.create(site_id=site, r_phase=1.234, y_phase=None)
        row.refresh_from_db()
        self.assertEqual(float(row.r_phase), 1.23)
        self.assertIsNone(row.y_phase)


class EntryExitTests(SimpleTestCase):
    def test_attribute_and_value_errors_become_400(self):
        @entryExit
        def broken_attr():
            return None.missing  # AttributeError without .detail

        @entryExit
        def broken_value():
            raise ValueError("bad input")

        self.assertEqual(broken_attr().status_code, 400)
        response = broken_value()
        self.assertEqual((response.status_code, response.data), (400, {"error": "bad input"}))
        self.assertEqual(broken_value.__name__, "broken_value")


class SendmailSettingsTests(SimpleTestCase):
    @override_settings(
        EMAIL_HOST="smtp.example.com", EMAIL_PORT=587, EMAIL_USE_TLS=True,
        EMAIL_HOST_USER="sender@example.com", EMAIL_HOST_PASSWORD="from-env",
        DEFAULT_FROM_EMAIL="", ALARM_EMAIL_OVERRIDE_TO=[],
    )
    def test_smtp_uses_django_settings(self):
        with mock.patch.object(sendmail.smtplib, "SMTP") as smtp:
            self.assertTrue(sendmail._send_smtp_email("s", "<p>x</p>", ["to@example.com"]))
        smtp.assert_called_once_with("smtp.example.com", 587, timeout=10)
        server = smtp.return_value.__enter__.return_value
        server.login.assert_called_once_with("sender@example.com", "from-env")
        self.assertEqual(server.sendmail.call_args.args[0], "sender@example.com")

    @override_settings(EMAIL_HOST="")
    def test_no_host_means_no_email(self):
        self.assertFalse(sendmail._send_smtp_email("s", "<p>x</p>", ["to@example.com"]))

    def test_fems_mail_has_each_mailbox_once(self):
        with mock.patch.object(sendmail, "render_to_string", return_value="<p/>"), \
                mock.patch.object(sendmail, "_send_smtp_email", return_value=True) as send:
            sendmail.send_mail_fire_equipments_system_after4days([], None)
            sendmail.send_mail_fire_equipments_system_45days_before([], None)
        first, second = (call.args[2] for call in send.call_args_list)
        self.assertEqual(len(first), len({a.lower() for a in first}))
        self.assertIn("binolasecurity@myntra.com", second)


class FuelProviderCredentialTests(SimpleTestCase):
    @override_settings(ROADCAST_PULL_USERNAME="u", ROADCAST_PULL_PASSWORD="p", LOCONAV_API_TOKEN="t")
    def test_credentials_come_from_settings(self):
        self.assertEqual(
            fuel_providers.roadcast_auth_headers(),
            {"Authorization": "Basic " + base64.b64encode(b"u:p").decode()},
        )
        self.assertEqual(fuel_providers.roadcast_pull_params(), {"username": "u", "password": "p"})
        self.assertEqual(fuel_providers.loconav_auth_headers(), {"User-Authentication": "t"})

    @override_settings(ROADCAST_PULL_USERNAME="", ROADCAST_PULL_PASSWORD="", LOCONAV_API_TOKEN="")
    def test_unset_credentials_send_no_auth(self):
        self.assertEqual(fuel_providers.roadcast_auth_headers(), {})
        self.assertEqual(fuel_providers.loconav_auth_headers(), {})

    def test_no_credentials_in_source(self):
        source = open(fuel_providers.__file__).read()
        self.assertNotRegex(source, r"Basic [A-Za-z0-9+/=]{16,}")
        self.assertNotIn("pull_api?username=", source)
        self.assertNotRegex(source, r'"User-Authentication":\s*"[^"]')
        self.assertNotRegex(open(sendmail.__file__).read(), r'SMTP_PASS\s*=\s*"')
