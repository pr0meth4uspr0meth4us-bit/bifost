# bifrost/services/email_service.py
import smtplib
import os
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import current_app

log = logging.getLogger(__name__)


def get_default_logo_url():
    base_url = current_app.config.get('BIFROST_PUBLIC_URL', '').rstrip('/')
    return f"{base_url}/static/logo.png" if base_url else ""


def load_email_template(filename='verification_email.html'):
    template_path = os.path.join(current_app.root_path, 'templates', filename)
    try:
        with open(template_path, 'r', encoding='utf-8') as file:
            return file.read()
    except FileNotFoundError:
        return "<html><body><h1>{TITLE}</h1><p>{SUBTITLE}</p><p>Code: {OTP_CODE}</p></body></html>"


def send_email(to_email, subject, html_content, text_content, app_name):
    sender_email = current_app.config['SENDER_EMAIL']
    app_password = current_app.config['EMAIL_PASSWORD']
    smtp_server = current_app.config['SMTP_SERVER']
    smtp_port = current_app.config['SMTP_PORT']

    message = MIMEMultipart("alternative")
    message["From"] = f"{app_name} <{sender_email}>"
    message["To"] = to_email
    message["Subject"] = subject
    message.attach(MIMEText(text_content, "plain"))
    message.attach(MIMEText(html_content, "html"))

    try:
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(sender_email, app_password)
        server.sendmail(sender_email, to_email, message.as_string())
        server.quit()
        return True
    except Exception as e:
        log.error(f"Email failed: {e}")
        return False


def send_otp_email(to_email, otp, app_name="Bifrost Identity", logo_url=None, app_url="#"):
    """Sends a standard OTP verification email."""
    html_template = load_email_template('verification_email.html')
    final_logo = logo_url if logo_url else get_default_logo_url()

    html_content = html_template.replace("{OTP_CODE}", str(otp)) \
        .replace("{APP_NAME}", app_name) \
        .replace("{LOGO_URL}", final_logo) \
        .replace("{APP_URL}", app_url) \
        .replace("{TITLE}", "Verification Code") \
        .replace("{SUBTITLE}", f"Use this code to verify your account for <b>{app_name}</b>.")

    text_content = f"Your {app_name} code is: {otp}"
    return send_email(to_email, f"🔐 {app_name} Code", html_content, text_content, app_name)


def send_invite_email(to_email, otp, app_name, verification_id, client_id, logo_url=None):
    """
    Sends an invitation email with a direct link to the password setup page.
    The link includes the verification_id so the user can enter their OTP and set a password.
    """
    html_template = load_email_template('verification_email.html')
    final_logo = logo_url if logo_url else get_default_logo_url()

    # Build the complete URL to the set-password page
    base_url = current_app.config.get('BIFROST_PUBLIC_URL', 'http://localhost:5000')
    setup_url = f"{base_url}/auth/ui/set-password?verification_id={verification_id}&client_id={client_id}"

    html_content = html_template.replace("{OTP_CODE}", str(otp)) \
        .replace("{APP_NAME}", app_name) \
        .replace("{LOGO_URL}", final_logo) \
        .replace("{APP_URL}", setup_url) \
        .replace("{TITLE}", "You've been invited!") \
        .replace("{SUBTITLE}",
                 f"You have been granted access to <b>{app_name}</b>. Click below to activate your account.")

    text_content = f"You've been invited to {app_name}! Your activation code is: {otp}\nVisit: {setup_url}"
    return send_email(to_email, f"👋 Welcome to {app_name}", html_content, text_content, app_name)


def send_reset_email(to_email, otp):
    """
    Sends a password reset OTP via SMTP.
    """
    app_name = "Bifrost Security"
    html_template = load_email_template('verification_email.html')
    final_logo = get_default_logo_url()

    # We point them to the backoffice login for context, though they need to use the OTP on the reset screen.
    base_url = current_app.config.get('BIFROST_PUBLIC_URL', '')
    login_url = f"{base_url}/backoffice/login"

    html_content = html_template.replace("{OTP_CODE}", str(otp)) \
        .replace("{APP_NAME}", app_name) \
        .replace("{LOGO_URL}", final_logo) \
        .replace("{APP_URL}", login_url) \
        .replace("{TITLE}", "Reset Password") \
        .replace("{SUBTITLE}", "A request was made to reset your Bifrost password. Use the code below.")

    text_content = f"Bifrost Password Reset Code: {otp}"

    return send_email(to_email, "⚠️ Password Reset Request", html_content, text_content, app_name)