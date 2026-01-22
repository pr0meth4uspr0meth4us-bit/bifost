import smtplib
import os
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import current_app, url_for

log = logging.getLogger(__name__)

def get_default_logo_url():
    """Constructs the public URL for the Bifrost static logo."""
    base_url = current_app.config.get('BIFROST_PUBLIC_URL', '').rstrip('/')
    if not base_url:
        return ""
    # We construct the path manually to avoid request-context issues in background threads
    return f"{base_url}/static/logo.png"

def load_email_template(filename='verification_email.html'):
    """Loads the HTML template."""
    template_path = os.path.join(current_app.root_path, 'templates', filename)
    try:
        with open(template_path, 'r', encoding='utf-8') as file:
            return file.read()
    except FileNotFoundError:
        log.error(f"Template not found at: {template_path}")
        return "<html><body><h1>{TITLE}</h1><p>{SUBTITLE}</p><p>Code: {OTP_CODE}</p></body></html>"

def send_email(to_email, subject, html_content, text_content, app_name):
    """Core email sending logic."""
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
        log.info(f"✅ Email sent to {to_email} for {app_name}")
        return True
    except Exception as e:
        log.error(f"❌ Failed to send email: {e}")
        return False

def send_otp_email(to_email, otp, app_name="Bifrost Identity", logo_url=None, app_url="#"):
    """
    Sends a standard Login Verification Code.
    """
    html_template = load_email_template('verification_email.html')

    # Use provided logo, otherwise fall back to Bifrost System Logo
    final_logo = logo_url if logo_url else get_default_logo_url()

    html_content = html_template.replace("{OTP_CODE}", str(otp)) \
        .replace("{APP_NAME}", app_name) \
        .replace("{LOGO_URL}", final_logo) \
        .replace("{APP_URL}", app_url) \
        .replace("{TITLE}", "Verification Code") \
        .replace("{SUBTITLE}", f"Please use the following code to complete your sign-in to <strong>{app_name}</strong>.")

    text_content = f"Your {app_name} login code is: {otp}"

    return send_email(to_email, f"🔐 {app_name} Login Code", html_content, text_content, app_name)

def send_invite_email(to_email, otp, app_name, login_url, logo_url=None):
    """
    Sends an Invitation Email to a new user.
    """
    html_template = load_email_template('verification_email.html')

    # Use provided logo, otherwise fall back to Bifrost System Logo
    final_logo = logo_url if logo_url else get_default_logo_url()

    html_content = html_template.replace("{OTP_CODE}", str(otp)) \
        .replace("{APP_NAME}", app_name) \
        .replace("{LOGO_URL}", final_logo) \
        .replace("{APP_URL}", login_url) \
        .replace("{TITLE}", "You've been invited!") \
        .replace("{SUBTITLE}", f"You have been granted access to <strong>{app_name}</strong>. Use this code to set your password and log in.")

    text_content = f"You have been invited to {app_name}.\nYour Setup Code is: {otp}\nLogin here: {login_url}"

    return send_email(to_email, f"👋 Welcome to {app_name}", html_content, text_content, app_name)