import smtplib
import ssl
import os
import random
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from warehouse import settings

# Try to load project settings like the original code; fall back to Django's settings
from django.utils import timezone
from django.template.loader import render_to_string
from wareApp.models import OTP, User, Site

# ---------------- SMTP CONFIG (reads from Django settings) ---------------- #
SMTP_HOST =  "smtp.gmail.com"
SMTP_PORT = 587
SMTP_USER = "no.reply@aviconncorp.com"
SMTP_PASS = "fnrv wpyz ofed gkgc"
USE_TLS = True
USE_SSL =  False
DEFAULT_FROM = "no.reply@aviconncorp.com"
# ------------------------------------------------------------------------ #


def _send_smtp_email(subject, html_message, to, cc=None, bcc=None, from_email=None):
    """Send an HTML email via smtplib using values from Django settings.

    Args:
        subject (str): Email subject
        html_message (str): HTML body
        to (list[str] | str): recipient(s)
        cc (list[str] | None): CC list
        bcc (list[str] | None): BCC list
        from_email (str | None): From address (defaults to DEFAULT_FROM / SMTP_USER)
    Returns:
        bool: True on success, False otherwise
    """
    if not to:
        return False
    if isinstance(to, str):
        to = [to]
    if cc is None:
        cc = []
    if bcc is None:
        bcc = []

    from_addr = from_email or DEFAULT_FROM or SMTP_USER

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
        if USE_SSL and not USE_TLS:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=context) as server:
                if SMTP_USER and SMTP_PASS:
                    server.login(SMTP_USER, SMTP_PASS)
                server.sendmail(from_addr, recipients, msg.as_string())
        else:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
                server.ehlo()
                if USE_TLS:
                    context = ssl.create_default_context()
                    server.starttls(context=context)
                    server.ehlo()
                if SMTP_USER and SMTP_PASS:
                    server.login(SMTP_USER, SMTP_PASS)
                server.sendmail(from_addr, recipients, msg.as_string())
        print(f"✅ Email sent: {subject}")
        return True
    except Exception as e:  # pragma: no cover
        print(f"❌ Failed to send email: {e}")
        return False


# ---------------- Helpers ---------------- #

def line(size, li=range(10)):
    return ''.join(map(str, ([random.choice(li) for _ in range(size)])))


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
    from_mail = DEFAULT_FROM
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
        to = ['mandeep.kahlon@aviconn.in', 'rnd@aviconn.in']
        return _send_smtp_email(subject_mail, html_message, to, cc=None, bcc=None, from_email=from_mail)
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
        cc = ['mandeep.kahlon@aviconn.in']
        bcc = ['manish@aviconn.in', 'rnd@aviconn.in']
        return _send_smtp_email(subject_mail, html_message, to, cc=cc, bcc=bcc, from_email=from_mail)


def send_mail_fire_alarm_aviconn_user(alarm_type):
    from_mail = DEFAULT_FROM
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
    to = ["komal.bhati@aviconn.in", "mandeep.kahlon@aviconn.in"]
    return _send_smtp_email(subject_mail, html_message, to, from_email=from_mail)


def send_mail_fire_equipments_system_8days_before(devices, userEmail):
    from_mail = DEFAULT_FROM
    htmlPath = os.path.join(settings.BASE_DIR, 'templates')
    html_message = render_to_string(f"{htmlPath}/femDeviceEmail.html", {"allDevicesData": devices})
    subject = 'FEMS Device next service date information alert Before 8 Days'
    to = [
        "nidhish.shahi@myntra.Com", "Jatender.talwandi@myntra.Com", "Mahesh.kumar11@myntra.Com",
        "Rewexecutivebinola@myntra.Com", "Binolasecurity@myntra.Com", "mandeep.kahlon@aviconn.in"
    ]
    return _send_smtp_email(subject, html_message, to, from_email=from_mail)


def send_mail_fire_equipments_system_after4days(devices, userEmail):
    from_mail = DEFAULT_FROM
    htmlPath = os.path.join(settings.BASE_DIR, 'templates')
    html_message = render_to_string(f"{htmlPath}/femDeviceEmail.html", {"allDevicesData": devices})
    subject = 'FEMS device service due information alert After 4 days'
    to = [
        "nidhish.shahi@myntra.Com", "Jatender.talwandi@myntra.Com", "Mahesh.kumar11@myntra.Com",
        "Rewexecutivebinola@myntra.Com", "Binolasecurity@myntra.Com", "mandeep.kahlon@aviconn.in"
    ]
    return _send_smtp_email(subject, html_message, to, from_email=from_mail)


def send_mail_fire_equipments_system_45days_before(devices, userEmail):
    from_mail = DEFAULT_FROM
    htmlPath = os.path.join(settings.BASE_DIR, 'templates')
    html_message = render_to_string(f"{htmlPath}/femDeviceEmail.html", {"allDevicesData": devices})
    subject = 'Before 45 Days device Warranty expired information alert.'
    to = [
        "nidhish.shahi@myntra.Com", "Jatender.talwandi@myntra.Com", "Mahesh.kumar11@myntra.Com",
        "Rewexecutivebinola@myntra.Com", "Binolasecurity@myntra.Com", "mandeep.kahlon@aviconn.in"
    ]
    return _send_smtp_email(subject, html_message, to, from_email=from_mail)


def send_mail_fire_equipments_system_30days_before(devices, userEmail):
    from_mail = DEFAULT_FROM
    htmlPath = os.path.join(settings.BASE_DIR, 'templates')
    html_message = render_to_string(f"{htmlPath}/femDeviceEmail.html", {"allDevicesData": devices})
    subject = 'Before 30 Days device Warranty expired information alert.'
    to = [
        "nidhish.shahi@myntra.Com", "Jatender.talwandi@myntra.Com", "Mahesh.kumar11@myntra.Com",
        "Rewexecutivebinola@myntra.Com", "Binolasecurity@myntra.Com", "mandeep.kahlon@aviconn.in"
    ]
    return _send_smtp_email(subject, html_message, to, from_email=from_mail)


def send_mail_fire_alarm_user(email, alarm_type, device_type, motor_status=0):
    from_mail = DEFAULT_FROM

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

    You can also check your current system status on your Smart dashboard <a href=\"https://asem1.aviconn.in/login\">here</a> . If you face any problem, then please contact with aviconn team.
    { _tpl_footer() }
    </body></html>
    """

    subject_mail = "Aviconn IOT System Notification - Change in Status"
    to = ["abhishek.mehra@aviconn.in"]
    bcc = ['komal.bhati@aviconn.in', 'mandeep.kahlon@aviconn.in']
    return _send_smtp_email(subject_mail, html_message, to, cc=None, bcc=bcc, from_email=from_mail)


def send_mail_for_motor_aviconn_user(motor):
    from_mail = DEFAULT_FROM
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
    to = ["komal.bhati@aviconn.in", "mandeep.kahlon@aviconn.in"]
    return _send_smtp_email(subject_mail, html_message, to, from_email=from_mail)


def emailcheck(id, username, email):
    from_mail = DEFAULT_FROM
    userId = User.objects.get(username=username).id
    otp = line(5)
    OTP.objects.create(otp=otp, user_id=userId)
    date_str = timezone.now().strftime("%b %d,%Y")

    html_message = f"""
    <html><head></head><body>
    Dear Customer  &emsp;&emsp;&emsp;&emsp;&emsp;&emsp;&emsp;&emsp;  {date_str}
    <br><br>
    Thank you for using Aviconn Smart Energy Management (SEM)<a href=\"http://asem1.aviconn.in/login\">here</a>.<br><br>
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
    _send_smtp_email(subject_mail, html_message, to, from_email=from_mail)
    return otp


def send_mail_fire_equipments_system(device):
    from_mail = DEFAULT_FROM
    html_message = f"""
       <html><head></head><body>
       Dear Customer,
       <br><br>
       <p>Device list{device}.</p>
       <p>Looking forward to your co-operation in helping us serve you better.</p>
       { _tpl_footer() }
       </body></html>
       """

    subject_mail = "fireequipemntSystem"
    to = ['komalbhati8527@gmai.com']
    bcc = ['komal.bhati@aviconn.in']
    return _send_smtp_email(subject_mail, html_message, to, cc=None, bcc=bcc, from_email=from_mail)


def send_mail_for_pf_fluctuation(data):
    site = Site.objects.get(id=data['site_id'])
    print(data)
    # Original script only printed; keeping behavior. Implement mailing here if needed.


def send_alarm_for_high_voltage(data):
    site = Site.objects.get(id=data['site_id'])
    site_name = site.site_name
    r_max_volt = data['r_volt_threshold']
    y_max_volt = data['y_volt_threshold']
    b_max_volt = data['b_volt_threshold']
    from_mail = DEFAULT_FROM

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
    to = ['abhishek.mehra@aviconn.in','mandeep.kahlon@aviconn.in']
    return _send_smtp_email(subject_mail, html_message, to, from_email=from_mail)


def send_alarm_for_low_voltage(data):
    site = Site.objects.get(id=data['site_id'])
    site_name = site.site_name
    r_min_volt = data['r_volt_threshold']
    y_min_volt = data['y_volt_threshold']
    b_min_volt = data['b_volt_threshold']
    from_mail = DEFAULT_FROM

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
    to = ['abhishek.mehra@aviconn.in', 'mandeep.kahlon@aviconn.in']
    return _send_smtp_email(subject_mail, html_message, to, from_email=from_mail)


def send_mail_for_dg_fuel_under_level(data):
    site = Site.objects.get(id=data['site_id'])
    site_name = site.site_name
    from_mail = DEFAULT_FROM

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
    to = ['abhishek.mehra@aviconn.in','mandeep.kahlon@aviconn.in']
    return _send_smtp_email(subject_mail, html_message, to, from_email=from_mail)


def send_alarm_for_dg_overtime(data):
    site = Site.objects.get(id=data['site_id'])
    # Original function was a stub; preserved.
    return None

