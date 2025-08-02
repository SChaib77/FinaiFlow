from celery import Task
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import structlog

from app.core.celery_app import celery_app
from app.core.config import settings

logger = structlog.get_logger()


class EmailTask(Task):
    """Base email task with retry logic"""
    autoretry_for = (smtplib.SMTPException, ConnectionError)
    retry_kwargs = {"max_retries": 3, "countdown": 60}


@celery_app.task(bind=True, base=EmailTask, name="app.tasks.email.send_email")
def send_email(self, to_email: str, subject: str, body: str, html_body: str = None):
    """Send email task"""
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = settings.SMTP_USER
        msg["To"] = to_email
        
        # Add text part
        msg.attach(MIMEText(body, "plain"))
        
        # Add HTML part if provided
        if html_body:
            msg.attach(MIMEText(html_body, "html"))
        
        # Send email
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
            if settings.SMTP_TLS:
                server.starttls()
            if settings.SMTP_USER and settings.SMTP_PASSWORD:
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.send_message(msg)
        
        logger.info("Email sent successfully", to=to_email, subject=subject)
        return {"status": "sent", "to": to_email}
        
    except Exception as e:
        logger.error("Email send failed", to=to_email, error=str(e))
        raise self.retry(exc=e)


@celery_app.task(name="app.tasks.email.send_welcome_email")
def send_welcome_email(user_email: str, user_name: str, tenant_name: str):
    """Send welcome email to new user"""
    subject = f"Welcome to {tenant_name}!"
    body = f"""
    Hi {user_name},
    
    Welcome to {tenant_name}! Your account has been created successfully.
    
    You can now log in and start using the platform.
    
    Best regards,
    The {tenant_name} Team
    """
    
    html_body = f"""
    <html>
        <body>
            <h2>Welcome to {tenant_name}!</h2>
            <p>Hi {user_name},</p>
            <p>Welcome to {tenant_name}! Your account has been created successfully.</p>
            <p>You can now log in and start using the platform.</p>
            <p>Best regards,<br>The {tenant_name} Team</p>
        </body>
    </html>
    """
    
    return send_email.delay(user_email, subject, body, html_body)


@celery_app.task(name="app.tasks.email.send_password_reset")
def send_password_reset_email(user_email: str, user_name: str, reset_token: str):
    """Send password reset email"""
    subject = "Password Reset Request"
    reset_url = f"{settings.FRONTEND_URL}/reset-password?token={reset_token}"
    
    body = f"""
    Hi {user_name},
    
    You requested a password reset. Click the link below to reset your password:
    
    {reset_url}
    
    This link will expire in 1 hour.
    
    If you didn't request this, please ignore this email.
    """
    
    html_body = f"""
    <html>
        <body>
            <h2>Password Reset Request</h2>
            <p>Hi {user_name},</p>
            <p>You requested a password reset. Click the link below to reset your password:</p>
            <p><a href="{reset_url}">Reset Password</a></p>
            <p>This link will expire in 1 hour.</p>
            <p>If you didn't request this, please ignore this email.</p>
        </body>
    </html>
    """
    
    return send_email.delay(user_email, subject, body, html_body)


@celery_app.task(name="app.tasks.email.send_email_verification")
def send_email_verification(user_email: str, user_name: str, verification_token: str):
    """Send email verification"""
    subject = "Verify Your Email Address"
    verify_url = f"{settings.FRONTEND_URL}/verify-email?token={verification_token}"
    
    body = f"""
    Hi {user_name},
    
    Please verify your email address by clicking the link below:
    
    {verify_url}
    
    This link will expire in 24 hours.
    """
    
    html_body = f"""
    <html>
        <body>
            <h2>Verify Your Email Address</h2>
            <p>Hi {user_name},</p>
            <p>Please verify your email address by clicking the link below:</p>
            <p><a href="{verify_url}">Verify Email</a></p>
            <p>This link will expire in 24 hours.</p>
        </body>
    </html>
    """
    
    return send_email.delay(user_email, subject, body, html_body)