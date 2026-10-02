from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from wareApp import tasks
from wareApp.mqtt import load


class LoadHandlerTests(SimpleTestCase):
    message = (
        "Load_Power:14,R_Volt:230,Y_Volt:231,B_Volt:232,R_Current:1,Y_Current:2,"
        "B_Current:3,Power_Source:1,Status:ON,Meter_Number:2,Time:now"
    )

    def test_parser_reads_gateway_payload(self):
        values = load._parse_load_message(self.message)

        self.assertEqual(values["load_power"], 14.0)
        self.assertEqual(values["power_source"], "1")
        self.assertEqual(values["meter_number"], 2)

    def test_creates_first_load_power_record(self):
        site = SimpleNamespace(show_voltage_alarms=False, is_pf_visible=False)
        entries = Mock(first=Mock(return_value=None))
        with patch(
            "wareApp.mqtt.load.SiteLoadPower.objects.filter", return_value=entries
        ), patch("wareApp.mqtt.load.SiteLoadPower.objects.create") as create:
            load.handle_load_message(site, 156, "gateway-01", self.message)

        self.assertEqual(create.call_args.kwargs["min_load"], 14.0)
        self.assertEqual(create.call_args.kwargs["Supply_Source"], "1")

    def test_updates_existing_load_power_record(self):
        site = SimpleNamespace(show_voltage_alarms=False, is_pf_visible=False)
        entries = Mock(first=Mock(return_value=object()))
        with patch(
            "wareApp.mqtt.load.SiteLoadPower.objects.filter", return_value=entries
        ):
            load.handle_load_message(site, 156, "gateway-01", self.message)

        self.assertEqual(entries.update.call_args.kwargs["Site_Total_Load"], 14.0)
        self.assertEqual(entries.update.call_args.kwargs["Status"], "ON")

    def test_does_not_evaluate_power_factor_for_first_load_record(self):
        site = SimpleNamespace(show_voltage_alarms=False, is_pf_visible=True)
        entries = Mock(first=Mock(return_value=None))
        with patch(
            "wareApp.mqtt.load.SiteLoadPower.objects.filter", return_value=entries
        ), patch("wareApp.mqtt.load.SiteLoadPower.objects.create"), patch(
            "wareApp.mqtt.load._record_power_factor_alarm"
        ) as record_pf:
            load.handle_load_message(site, 156, "gateway-01", self.message)

        record_pf.assert_not_called()

    def test_power_factor_record_uses_zero_for_non_violating_phases(self):
        site = SimpleNamespace(
            is_pf_visible=True,
            r_phase_pf_threshold=0.9,
            y_phase_pf_threshold=0.9,
            b_phase_pf_threshold=0.9,
        )
        values = {
            "power_factors": (0.8, 0.95, 0.95),
            "status": "ON",
            "power_source": "1",
            "meter_number": 2,
        }
        existing_alarms = Mock(exists=Mock(return_value=True))

        with patch("wareApp.mqtt.load.PowerFactorData.objects.create") as create, patch(
            "wareApp.mqtt.load.NewAlarmsNotifications.objects.filter",
            return_value=existing_alarms,
        ):
            load._record_power_factor_alarm(site, values)

        self.assertEqual(create.call_args.kwargs["r_phase_pf"], 0.8)
        self.assertEqual(create.call_args.kwargs["y_phase_pf"], 0.0)
        self.assertEqual(create.call_args.kwargs["b_phase_pf"], 0.0)

    def test_high_voltage_alarm_requires_sustained_readings_and_notifies(self):
        site = SimpleNamespace(
            id=156,
            r_phase_voltage_threshold_max=220,
            y_phase_voltage_threshold_max=220,
            b_phase_voltage_threshold_max=220,
            r_phase_voltage_threshold_min=180,
            y_phase_voltage_threshold_min=180,
            b_phase_voltage_threshold_min=180,
        )
        values = {
            "r_volt": 230.0,
            "y_volt": 230.0,
            "b_volt": 230.0,
            "power_source": "1",
            "meter_number": 2,
        }
        history = Mock()
        history.order_by.return_value = [
            SimpleNamespace(r_phase=230, y_phase=230, b_phase=230)
            for _ in range(7)
        ]
        existing_alarms = Mock(exists=Mock(return_value=False))

        with patch(
            "wareApp.mqtt.load.SiteLoadParameters.objects.create"
        ) as create_parameter, patch(
            "wareApp.mqtt.load.SiteLoadParameters.objects.filter",
            return_value=history,
        ), patch(
            "wareApp.mqtt.load.NewAlarmsNotifications.objects.filter",
            return_value=existing_alarms,
        ), patch(
            "wareApp.mqtt.load.NewAlarmsNotifications.objects.create"
        ) as create_alarm, patch(
            "wareApp.mqtt.load.send_alarm_for_high_voltage"
        ) as notify:
            load._record_voltage_alarm(site, values, parameter_type=0)

        create_parameter.assert_called_once()
        create_alarm.assert_called_once()
        notify.assert_called_once_with(
            {
                "r_volts": 230.0,
                "y_volts": 230.0,
                "b_volts": 230.0,
                "r_volt_threshold": 220,
                "y_volt_threshold": 220,
                "b_volt_threshold": 220,
                "site_id": 156,
            }
        )

    def test_processing_task_resolves_site_and_calls_handler(self):
        site = SimpleNamespace(id=156)
        with patch("wareApp.tasks.Site.objects.get", return_value=site), patch(
            "wareApp.tasks.handle_load_message"
        ) as handle:
            tasks.process_load_message.run(156, "gateway-01", self.message)

        handle.assert_called_once_with(site, 156, "gateway-01", self.message)
