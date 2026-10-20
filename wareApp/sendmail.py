import logging
import smtplib
import ssl
import secrets
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from django.conf import settings

from datetime import timedelta

from django.utils import timezone
from django.template.loader import render_to_string
from wareApp.models import OTP, User, Site

logger = logging.getLogger(__name__)

# SMTP configuration comes from Django settings (warehouse/.env: EMAIL_HOST,
# EMAIL_PORT, EMAIL_USE_TLS, EMAIL_USE_SSL, EMAIL_HOST_USER, EMAIL_HOST_PASSWORD,
# DEFAULT_FROM_EMAIL). Nothing secret lives in this file.


def _smtp_config():
    user = settings.EMAIL_HOST_USER
    return {
        "host": settings.EMAIL_HOST,
        "port": settings.EMAIL_PORT,
        "user": user,
        "password": settings.EMAIL_HOST_PASSWORD,
        "use_tls": settings.EMAIL_USE_TLS,
        "use_ssl": getattr(settings, "EMAIL_USE_SSL", False),
        "timeout": getattr(settings, "EMAIL_TIMEOUT", 10),
        "from": settings.DEFAULT_FROM_EMAIL or user,
    }


def _alarm_override_recipients():
    """Addresses that replace every alarm email's recipients (test servers), or []."""
    return list(getattr(settings, "ALARM_EMAIL_OVERRIDE_TO", []) or [])


def _send_smtp_email(
    subject, html_message, to, cc=None, bcc=None, from_email=None, is_alarm=True
):
    """Send an HTML email via smtplib using values from Django settings.

    Args:
        subject (str): Email subject
        html_message (str): HTML body
        to (list[str] | str): recipient(s)
        cc (list[str] | None): CC list
        bcc (list[str] | None): BCC list
        from_email (str | None): From address (defaults to settings.DEFAULT_FROM_EMAIL or EMAIL_HOST_USER)
    Returns:
        bool: True on success, False otherwise
    """
    if isinstance(to, str):
        to = [to]
    to = [address for address in (to or []) if address]
    if cc is None:
        cc = []
    if bcc is None:
        bcc = []

    override = _alarm_override_recipients() if is_alarm else []
    if override:
        # Test server: every alarm email goes only to the override address(es);
        # the intended recipients are shown at the top of the email and logged.
        intended = list(dict.fromkeys(to + cc + bcc))
        logger.info(
            "Alarm email redirected: subject=%r intended=%s to=%s", subject, intended, override
        )
        html_message = (
            '<p style="background:#fff3cd;padding:8px;font-family:Arial,sans-serif;">'
            f"TEST REDIRECT. Intended recipients: {', '.join(intended) or 'none'}</p>"
            + html_message
        )
        to, cc, bcc = override, [], []
    if not to:
        logger.warning("Email not sent, no recipients: subject=%r", subject)
        return False

    smtp = _smtp_config()
    if not smtp["host"]:
        logger.error("Email failed: subject=%r error=EMAIL_HOST not configured", subject)
        return False
    from_addr = from_email or smtp["from"]

    # Build MIME message
    msg = MIMEMultipart("alternative")
    msg["From"] = from_addr
    msg["To"] = ", ".join(to)
    if cc:
        msg["Cc"] = ", ".join(cc)
    msg["Subject"] = subject
    msg.attach(MIMEText(html_message, "html"))

    recipients = list(dict.fromkeys(to + cc + bcc))  # de-dup while preserving order

    try:
        context = ssl.create_default_context()
        if smtp["use_ssl"] and not smtp["use_tls"]:
            connection = smtplib.SMTP_SSL(
                smtp["host"], smtp["port"], context=context, timeout=smtp["timeout"]
            )
        else:
            connection = smtplib.SMTP(smtp["host"], smtp["port"], timeout=smtp["timeout"])
        with connection as server:
            if not smtp["use_ssl"]:
                server.ehlo()
                if smtp["use_tls"]:
                    server.starttls(context=context)
                    server.ehlo()
            if smtp["user"] and smtp["password"]:
                server.login(smtp["user"], smtp["password"])
            server.sendmail(from_addr, recipients, msg.as_string())
        logger.info("Email sent: subject=%r to=%s", subject, recipients)
        return True
    except Exception as e:  # pragma: no cover
        logger.error("Email failed: subject=%r to=%s error=%s: %s", subject, recipients, type(e).__name__, e)
        return False


# ---------------- Helpers ---------------- #

def line(size, li=range(10)):
    """Random digit string (cryptographically secure: used for OTPs)."""
    return "".join(str(secrets.choice(li)) for _ in range(size))


def _now_str():
    return timezone.now().strftime("%b %d,%Y %H:%M:%S")


# ---------------- Clean HTML templates (kept close to originals) ---------------- #

def _tpl_header(title_text=None):
    title = f"<h1 style=\"color:#ff6600;\">{title_text}</h1>" if title_text else ""
    return f"""
    <div class=\"header\" style=\"background:#fff;color:#333;padding:10px 0;text-align:center\">
        <img style=\"max-width:100px;display:block;margin:0 auto 10px\" src=\"https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcQPfXCmcxjjrtoMcDqmJp2Smioacg6H5NUasXP8MCAQDAUzqfqcHqmwGayPJSR1FZikCus&usqp=CAU\" alt=\"Aviconn Solutions Logo\" />
        <p>Aviconn Solutions Pvt. Ltd.</p>
        {title}
    </div>
    """


def _tpl_footer():
    return """
    <br><br>
    Sincerely,<br>
    Smart Energy Management (SEM) Team<br>
    Aviconn Solution Pvt Ltd
    <br><br>
    <p style=\"color:red;\">** This is a system generated mail. Please do not reply to this e-mail ID. **</p>
    <br><br>
    <center>********</center>
    """


# ---------------- Original function names (SMTP-based) ---------------- #

def send_mail_for_sensor_by_pass(site_id, aisle_id, options):
    site = Site.objects.get(id=site_id)
    site_name = site.site_name
    location = getattr(site, "location", "-")

    current_time = _now_str()
    if options == 1:
        html_message = f"""
            <html><head></head><body>
            Dear Aviconn Team,
            <br>
            <p>Aviconn System would like to inform you about the following alarm detected at your site.</p>
            <br>
            Site-Name : {site_name}<br>
            Location  : {location}<br>
            Alarm     : System By-Pass(Either Fire Alarm activated at site OR Manual By-Pass) <br>
            Aisle Names : {', '.join(aisle_id)} <br>
            Detected Date/Time : {current_time}<br><br>

            Could you please check at your end and take corrective measure.
            In case it is a false fire alarm OR by mistake manually by-pass, we request you to bring the system back to energy-saving mode to avoid wastage of energy.
            { _tpl_footer() }
            </body></html>
        """
        subject_mail = f"Notification for {site_name},{location} : Alarm for system By-Pass"
        to = ['mandeep.kahlon@aviconncorp.com', 'rnd@aviconn.in']
        return _send_smtp_email(subject_mail, html_message, to, cc=None, bcc=None)
    else:
        html_message = f"""
            <html><head></head><body>
            Dear Customer,
            <br>
            <p>Aviconn System would like to inform you about the following alarm detected at your site.</p>
            <br>
            Site-Name : {site_name}<br>
            Location  : {location}<br>
            Alarm     : System By-Pass(Either Fire Alarm activated at site OR Manual By-Pass) <br>
            Detected Date/Time : {current_time}<br><br>

            Could you please check at your end and take corrective measure.
            In case it is a false fire alarm OR by mistake manually by-pass, we request you to bring the system back to energy-saving mode to avoid wastage of energy.
            { _tpl_footer() }
            </body></html>
        """
        subject_mail = f"Aviconn Notification for {site_name},{location} : Alarm for system By-Pass"
        to = ['nidhish.shahi@myntra.Com']
        cc = ['mandeep.kahlon@aviconncorp.com']
        bcc = ['manish@aviconncorp.com', 'rnd@aviconn.in']
        return _send_smtp_email(subject_mail, html_message, to, cc=cc, bcc=bcc)


def send_mail_fire_alarm_aviconn_user(alarm_type):
    date_str = timezone.now().strftime("%b %d,%Y")
    html_message = f"""
        <html><head></head><body>
        Dear Customer
        <br><br>
        Your system is working on {alarm_type} mode at {date_str}.
        <br><br>
        Aviconn Solution Pvt Ltd
        </body></html>
    """
    subject_mail = "Fire Alarm Generated"
    to = ["komal.bhati@aviconn.in", "mandeep.kahlon@aviconncorp.com"]
    return _send_smtp_email(subject_mail, html_message, to)


# Fire-equipment (FEMS) service and warranty reminders: same template and
# recipients, only the subject differs. The internal BCC list these functions
# used to build was never passed to the sender, so it is left out.
_FEMS_RECIPIENTS = [
    "jatender.talwandi@myntra.com",
    "rewexecutivebinola@myntra.com",
    "jatender.s@flipkart.com",
]


def _send_fems_email(devices, subject, extra_to=()):
    html_message = render_to_string("femDeviceEmail.html", {"allDevicesData": devices})
    return _send_smtp_email(subject, html_message, [*_FEMS_RECIPIENTS, *extra_to])


def send_mail_fire_equipments_system_8days_before(devices, userEmail):
    return _send_fems_email(
        devices, "FEMS Device next service date information alert Before 8 Days"
    )


def send_mail_fire_equipments_system_after4days(devices, userEmail):
    return _send_fems_email(
        devices, "FEMS device service due information alert After 4 days"
    )


def send_mail_fire_equipments_system_45days_before(devices, userEmail):
    return _send_fems_email(
        devices,
        "Before 45 Days device Warranty expired information alert.",
        extra_to=["binolasecurity@myntra.com"],
    )


def send_mail_fire_equipments_system_30days_before(devices, userEmail):
    return _send_fems_email(
        devices, "Before 30 Days device Warranty expired information alert."
    )


def send_mail_fire_alarm_user(email, alarm_type, device_type, motor_status=0):

    if motor_status == 1:
        motor_mode = "Yes"
        current_status = "On"
        previous_status = "Off"
    else:
        motor_mode = "No"
        current_status = "Off"
        previous_status = "Off"

    if alarm_type == "Manual-Mode to Auto-Mode":
        subject = "Manual is on"
        current_mode = "Auto"
        previous_mode = "Manual"
        alarm_mode = "Yes"
    elif alarm_type == "Auto-Mode to Manual-Mode":
        subject = "Auto is on"
        current_mode = "Manual"
        previous_mode = "Auto"
        alarm_mode = "Yes"
    elif alarm_type == "Auto-Mode to Off-Mode":
        subject = "Auto to Off"
        current_mode = "Off"
        previous_mode = "Auto"
        alarm_mode = "Yes"
    elif alarm_type == "Manual-Mode to Off-Mode":
        subject = "Manual to Off"
        current_mode = "Off"
        previous_mode = "Manual"
        alarm_mode = "Yes"
    elif alarm_type == "Off-Mode to Manual-Mode":
        subject = "Off to Manual"
        current_mode = "Manual"
        previous_mode = "Off"
        alarm_mode = "Yes"
    elif alarm_type == "Off-Mode to Auto-Mode":
        subject = "Off to Auto"
        current_mode = "Auto"
        previous_mode = "Off"
        alarm_mode = "Yes"
    elif alarm_type == "Motor-On in Auto-Mode":
        current_mode = "Auto"
        previous_mode = "Manual"
        alarm_mode = "No"
    elif alarm_type == "Motor-On in Manual-Mode":
        current_mode = "Manual"
        previous_mode = "Auto"
        alarm_mode = "No"
    else:
        current_mode = "-"
        previous_mode = "-"
        alarm_mode = "-"
    current_time = _now_str()

    html_message = f"""
    <html><head></head><body>
    Dear Customer,
    <br><br>
    <p>This is to notify you that below are the changes detected in your {device_type}.</p>
    <br>
    <b>Fire-System Mode Change Notification:</b><br>
        Mode Changed: {alarm_mode}<br>
        Current Mode: {current_mode}<br>
        Previous Mode: {previous_mode}<br>
        Current Status Detected Date/Time: {current_time}<br><br>

    <b>Notification for Fire-System Motor:</b><br>
        Motor Status Changed: {motor_mode}<br>
        Current Status: {current_status}<br>
        Previous Status: {previous_status}<br>
        Current Status Detected Date/Time: {current_time}<br><br>

    You can also check your current system status on your Smart dashboard <a href=\"https://asem.aviconncorp.com/login\">here</a> . If you face any problem, then please contact with aviconn team.
    { _tpl_footer() }
    </body></html>
    """

    subject_mail = "Aviconn IOT System Notification - Change in Status"
    to = ["rewexecutivebinola@myntra.com", "jatender.s@flipkart.com"]
    bcc = ['ashutosh.dubey@aviconncorp.com', 'mandeep.kahlon@aviconncorp.com']
    return _send_smtp_email(subject_mail, html_message, to, cc=None, bcc=bcc)


def send_mail_for_motor_aviconn_user(motor):
    date_str = timezone.now().strftime("%b %d,%Y")
    html_message = f"""
    <html><head></head><body>
    Dear Customer
    <br><br>
    Your Motor is turned {motor} at {date_str}.
    <br><br>
    Aviconn Solution Pvt Ltd
    </body></html>
    """
    subject_mail = "Motor Status"
    to = ["komal.bhati@aviconn.in", "mandeep.kahlon@aviconncorp.com"]
    return _send_smtp_email(subject_mail, html_message, to)


def emailcheck(id, username, email):
    userId = User.objects.get(username=username).id
    otp = line(5)
    # One valid code per user; expired codes of everyone are dropped.
    valid_after = timezone.now() - timedelta(
        minutes=getattr(settings, "PASSWORD_RESET_OTP_MINUTES", 10)
    )
    OTP.objects.filter(user_id=userId).delete()
    OTP.objects.filter(created__lt=valid_after).delete()
    OTP.objects.create(otp=otp, user_id=userId)
    date_str = timezone.now().strftime("%b %d,%Y")

    html_message = f"""
    <html><head></head><body>
    Dear Customer  &emsp;&emsp;&emsp;&emsp;&emsp;&emsp;&emsp;&emsp;  {date_str}
    <br><br>
    Thank you for using Aviconn Smart Energy Management (SEM)<a href=\"http://asem.aviconncorp.com/login\">here</a>.<br><br>
    One Time Password (OTP) for the process to Reset Password is <b>{otp}</b>.
    <br><br>
    Do not share your password with anyone.
    <br><br>
    <p style=\"color:red;\"> Looking forward to more opportunities to be of service to you.</p>
    <br>
    <br>
    Aviconn Solution Pvt Ltd
    </body></html>
    """

    subject_mail = "Password Change Request for Your Smart Meter Account"
    to = [email]
    _send_smtp_email(subject_mail, html_message, to, is_alarm=False)
    return otp


def send_mail_fire_equipments_system(device):
    html_message = f"""
        <html><head></head><body>
        Dear Customer,
        <br><br>
        <p>Device list{device}.</p>
        <p>Looking forward to your co-operation in helping us serve you better.</p>
        { _tpl_footer() }
        </body></html>
        """

    subject_mail = "fire Equipemnt System"
    to = ['komalbhati8527@gmai.com']
    bcc = ['komal.bhati@aviconn.in', 'mandeep.kahlon@aviconncorp.com', "ashutosh.dubey@aviconncorp.com"]
    return _send_smtp_email(subject_mail, html_message, to, cc=None, bcc=bcc)


def send_mail_for_pf_fluctuation(data):
    def row(phase):
        value = data[f"{phase}_pf"]
        threshold = data[f"{phase}_pf_threshold"]
        return (
            f"{phase.upper()}-Phase PF",
            f"{value:.2f} (threshold {threshold:.2f})",
            value < threshold,
        )

    return send_alarm_email(
        "PF Fluctuation Alarm",
        data["site_id"],
        [("Power source", data.get("power_source"), False), row("r"), row("y"), row("b")],
    )


def send_alarm_email(alarm_name, site_id, details):
    """Generic alarm email: ``details`` is a list of (label, value, highlight).

    Recipients: ALARM_EMAIL_OVERRIDE_TO when set (test servers), otherwise
    ALARM_EMAIL_DEFAULT_TO; with neither configured nothing is sent.
    """
    from django.conf import settings as django_settings

    site = Site.objects.filter(id=site_id).first()
    site_name = site.site_name if site else f"site {site_id}"
    rows = "".join(
        f'<p style="{"color:red;" if highlight else ""}"><strong>{label}: </strong>{value}</p>'
        for label, value, highlight in details
    )
    html_message = f"""
        <html><head><title>{alarm_name}</title></head>
        <body style="font-family:Arial,sans-serif;background:#f0f0f0;color:#333;">
        {_tpl_header(alarm_name)}
        <div class="container" style="background:#fff;border:1px solid #ccc;border-radius:5px;padding:20px;margin:20px;">
            <p>Dear Customer,</p>
            <p>Our monitoring system has raised the following alarm.</p>
            <p><strong>Site Name: </strong>{site_name}</p>
            <p><strong>Alarm Name: </strong>{alarm_name}</p>
            <p><strong>Time: </strong>{_now_str()}</p>
            {rows}
            <p>Thank you for your attention to this matter. Please feel free to contact us.</p>
            {_tpl_footer()}
        </div>
        </body>
        </html>
    """
    to = list(getattr(django_settings, "ALARM_EMAIL_DEFAULT_TO", []) or [])
    return _send_smtp_email(f"{alarm_name} - {site_name}", html_message, to)


def send_alarm_for_high_voltage(data):
    site = Site.objects.get(id=data['site_id'])
    site_name = site.site_name
    r_max_volt = data['r_volt_threshold']
    y_max_volt = data['y_volt_threshold']
    b_max_volt = data['b_volt_threshold']

    r_phase_color = 'color:red;' if int(data['r_volts']) > int(r_max_volt) else 'color:green;'
    y_phase_color = 'color:red;' if int(data['y_volts']) > int(y_max_volt) else 'color:green;'
    b_phase_color = 'color:red;' if int(data['b_volts']) > int(b_max_volt) else 'color:green;'

    html_message = f"""
        <html><head><title>High Voltage Alarm</title></head>
        <body style=\"font-family:Arial,sans-serif;background:#f0f0f0;color:#333;\">
        {_tpl_header("High Voltage Alarm")}
        <div class=\"container\" style=\"background:#fff;border:1px solid #ccc;border-radius:5px;padding:20px;margin:20px;\">
            <p>Dear Customer,</p>
            <p>Our monitoring system has detected a high voltage alarm at your premises.</p>
            <p><strong>Site Name: </strong>{site_name}.</p>
            <p><strong>Alarm Name: </strong>High Voltage Alarm</p>
            <p style=\"{r_phase_color}\">R_Phase_Max_Thresold: {r_max_volt}, R-Phase: {data['r_volts']}.</p>
            <p style=\"{y_phase_color}\">Y_Phase_Max_Thresold: {y_max_volt}, Y-Phase: {data['y_volts']}.</p>
            <p style=\"{b_phase_color}\">B_Phase_Max_Thresold: {b_max_volt}, B-Phase: {data['b_volts']}.</p>
            <p>Thank you for your attention to this matter. Please feel free to contact us.</p>
            {_tpl_footer()}
        </div>
        </body>
        </html>
    """

    subject_mail = "High Voltage Alarm Testing"
    to = ['abhishek.mehra@aviconn.in','mandeep.kahlon@aviconncorp.com']
    return _send_smtp_email(subject_mail, html_message, to)


def send_alarm_for_low_voltage(data):
    site = Site.objects.get(id=data['site_id'])
    site_name = site.site_name
    r_min_volt = data['r_volt_threshold']
    y_min_volt = data['y_volt_threshold']
    b_min_volt = data['b_volt_threshold']

    r_phase_color = 'color:red;' if int(data['r_volts']) < int(r_min_volt) else 'color:green;'
    y_phase_color = 'color:red;' if int(data['y_volts']) < int(y_min_volt) else 'color:green;'
    b_phase_color = 'color:red;' if int(data['b_volts']) < int(b_min_volt) else 'color:green;'

    html_message = f"""
        <html><head><title>Low Voltage Alarm</title></head>
        <body style=\"font-family:Arial,sans-serif;background:#f0f0f0;color:#333;\">
        {_tpl_header("Low Voltage Alarm")}
        <div class=\"container\" style=\"background:#fff;border:1px solid #ccc;border-radius:5px;padding:20px;margin:20px;\">
            <p>Dear Customer,</p>
            <p>Our monitoring system has detected a low voltage alarm at your premises.</p>
            <p><strong>Site Name: </strong>{site_name}.</p>
            <p><strong>Alarm Name: </strong>Low Voltage Alarm</p>
            <p style=\"{r_phase_color}\">R_Phase_Min_Thresold: {r_min_volt}, R-Phase: {data['r_volts']}.</p>
            <p style=\"{y_phase_color}\">Y_Phase_Min_Thresold: {y_min_volt}, Y-Phase: {data['y_volts']}.</p>
            <p style=\"{b_phase_color}\">B_Phase_Min_Thresold: {b_min_volt}, B-Phase: {data['b_volts']}.</p>
            <p>Thank you for your attention to this matter. Please feel free to contact us.</p>
            {_tpl_footer()}
        </div>
        </body>
        </html>
    """

    subject_mail = "Low Voltage Alarm Testing"
    to = ['abhishek.mehra@aviconn.in', 'mandeep.kahlon@aviconncorp.com']
    return _send_smtp_email(subject_mail, html_message, to)


def send_mail_for_dg_fuel_under_level(data):
    site = Site.objects.get(id=data['site_id'])
    site_name = site.site_name

    html_message = f"""
        <html><head><title>Fuel Level Alarm</title></head>
        <body style=\"font-family:Arial,sans-serif;background:#f0f0f0;color:#333;\">
        {_tpl_header("Fuel Level Alarm")}
        <div class=\"container\" style=\"background:#fff;border:1px solid #ccc;border-radius:5px;padding:20px;margin:20px;\">
            <p>Dear Customer,</p>
            <p>We would like to bring to your attention that the fuel level within our system has fallen below the predetermined threshold.</p>
            <p><strong>Site Name: </strong>{site_name}.</p>
            <p><strong>Alarm Name: </strong>Fuel Level Alarm</p>
            <p><strong>Alarm Threshold: </strong> {data['fuel_level']}%* below the tank Capacity {data['tank_capacity']} ltr</p>
            <p>Thank you for your attention to this matter. Please feel free to contact us.</p>
            {_tpl_footer()}
        </div>
        </body>
        </html>
    """

    subject_mail = "Fuel Level Alarm Testing"
    to = ['abhishek.mehra@aviconn.in','mandeep.kahlon@aviconncorp.com']
    return _send_smtp_email(subject_mail, html_message, to)


def send_alarm_for_dg_overtime(data):
    # Not implemented yet (no email is sent for DG overtime).
    return None


