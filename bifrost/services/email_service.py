import smtplib
import os
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import current_app

log = logging.getLogger(__name__)

def load_email_template():
    """Loads the HTML template."""
    template_path = os.path.join(current_app.root_path, 'templates', 'verification_email.html')
    try:
        with open(template_path, 'r', encoding='utf-8') as file:
            return file.read()
    except FileNotFoundError:
        log.error(f"Template not found at: {template_path}")
        return "<html><body><h1>Verification Code: {OTP_CODE}</h1><p>For: {APP_NAME}</p></body></html>"

def send_otp_email(to_email, otp, app_name="Bifrost Identity"):
    """
    Sends an OTP email branded with the specific app_name.
    """
    # Load config
    sender_email = current_app.config['SENDER_EMAIL']
    app_password = current_app.config['EMAIL_PASSWORD']
    smtp_server = current_app.config['SMTP_SERVER']
    smtp_port = current_app.config['SMTP_PORT']

    # Create message
    message = MIMEMultipart("alternative")
    message["From"] = f"{app_name} <{sender_email}>"
    message["To"] = to_email
    message["Subject"] = f"🔐 {app_name} Login Verification"

    # Inject variables into template
    html_template = load_email_template()
    html_content = html_template.replace("{OTP_CODE}", str(otp)).replace("{APP_NAME}", app_name)

    # Plain text fallback
    text_content = f"""
    {app_name} - Login Verification
    Your code is: {otp}
    Expires in 10 minutes.
    """

    message.attach(MIMEText(text_content, "plain"))
    message.attach(MIMEText(html_content, "html"))

    try:
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(sender_email, app_password)
        server.sendmail(sender_email, to_email, message.as_string())
        server.quit()
        log.info(f"✅ Email sent to {to_email} for {app_name}")
        return True
    except Exception as e:
        log.error(f"❌ Failed to send email: {e}")
        return False