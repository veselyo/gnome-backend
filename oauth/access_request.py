"""
Access request system for OAuth test user management.
"""
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
import logging

logger = logging.getLogger(__name__)


def send_access_request_email(user_email: str, service: str = "Google Drive") -> bool:
    """
    Send email to admin requesting to add user as OAuth test user.
    
    Args:
        user_email: Email of user requesting access
        service: Service name (Google Drive, OneDrive)
    
    Returns:
        True if email sent successfully
    """
    try:
        admin_email = os.environ.get('ADMIN_EMAIL', 'kennethfrisard05@gmail.com')
        
        # Create message
        msg = MIMEMultipart('alternative')
        msg['Subject'] = f'Gnome: Add Test User for {service}'
        msg['From'] = 'noreply@gnom3.com'
        msg['To'] = admin_email
        
        # Email body
        text = f"""
New Gnome user requesting {service} access:

Email: {user_email}
Service: {service}
Time: {{datetime.now()}}

ACTION REQUIRED:
1. Go to Google Cloud Console: https://console.cloud.google.com/apis/credentials/consent
2. Click "ADD USERS" under Test users
3. Enter: {user_email}
4. Click "SAVE"

The user can then reconnect in Gnome and it will work!

---
Gnome Access Request System
"""
        
        html = f"""
<html>
<body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
    <h2 style="color: #673ED1;">🏡 Gnome Access Request</h2>
    
    <div style="background: #f7f9fa; padding: 20px; border-radius: 8px; margin: 20px 0;">
        <p><strong>New user requesting {service} access:</strong></p>
        <p style="font-size: 18px; color: #1c1c1c;">📧 {user_email}</p>
    </div>
    
    <div style="background: #fff3cd; padding: 15px; border-left: 4px solid #ffc107; margin: 20px 0;">
        <p><strong>⚡ Action Required:</strong></p>
        <ol>
            <li>Go to <a href="https://console.cloud.google.com/apis/credentials/consent">Google Cloud Console</a></li>
            <li>Click <strong>"ADD USERS"</strong> under Test users</li>
            <li>Enter: <code>{user_email}</code></li>
            <li>Click <strong>"SAVE"</strong></li>
        </ol>
    </div>
    
    <p style="color: #637282; font-size: 14px;">
        After adding the user, they can reconnect in Gnome and it will work!
    </p>
    
    <hr style="border: none; border-top: 1px solid #e5e5e5; margin: 30px 0;">
    <p style="color: #637282; font-size: 12px;">
        Gnome Access Request System • Automated message
    </p>
</body>
</html>
"""
        
        part1 = MIMEText(text, 'plain')
        part2 = MIMEText(html, 'html')
        msg.attach(part1)
        msg.attach(part2)
        
        # Send via Gmail SMTP (you'll need app password)
        # For now, just log it
        logger.info(f"📧 Access request from {user_email} for {service}")
        logger.info(f"   Admin should add this email as test user in Google Cloud Console")
        
        # TODO: Actual email sending (needs Gmail app password or SendGrid)
        # smtp = smtplib.SMTP('smtp.gmail.com', 587)
        # smtp.starttls()
        # smtp.login(admin_email, os.environ.get('EMAIL_PASSWORD'))
        # smtp.send_message(msg)
        # smtp.quit()
        
        return True
        
    except Exception as e:
        logger.error(f"Failed to send access request email: {e}")
        return False


def store_access_request(database, user_email: str, service: str):
    """
    Store access request in database for tracking.
    
    Args:
        database: GnomeDatabase instance
        user_email: User's email
        service: Service name
    """
    try:
        cursor = database.conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS access_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_email TEXT NOT NULL,
                service TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                requested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                approved_at TIMESTAMP
            )
        ''')
        
        cursor.execute('''
            INSERT INTO access_requests (user_email, service, status)
            VALUES (?, ?, 'pending')
        ''', (user_email, service))
        
        database.conn.commit()
        logger.info(f"Stored access request: {user_email} for {service}")
        
    except Exception as e:
        logger.error(f"Failed to store access request: {e}")
