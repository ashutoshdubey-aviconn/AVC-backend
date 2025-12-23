import smtplib
from email.mime.text import MIMEText

msg = MIMEText("This is a test email sent using Gmail SMTP with app password.")
msg["Subject"] = "Test Email"
msg["From"] = "no.reply@aviconncorp.com"
msg["To"] = "sachmann.kochar@aviconncorp.com"

with smtplib.SMTP("smtp.gmail.com", 587) as server:
    server.starttls()
    server.login("no.reply@aviconncorp.com", "fnrv wpyz ofed gkgc")
    server.send_message(msg)

print("Email sent successfully!")
