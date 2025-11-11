import os
import requests
import sqlite3
from datetime import datetime
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import logging
from flask import Flask, request, Response, render_template, jsonify
import base64
import json

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

class PDFTracker:
    def __init__(self):
        self.setup_database()
    
    def setup_database(self):
        """Initialize SQLite database for tracking"""
        self.conn = sqlite3.connect('pdf_tracking.db', check_same_thread=False)
        cursor = self.conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS pdf_access (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pdf_id TEXT,
                client_name TEXT,
                access_time TIMESTAMP,
                ip_address TEXT,
                country TEXT,
                city TEXT,
                user_agent TEXT,
                email_status TEXT,
                whatsapp_status TEXT,
                status TEXT DEFAULT 'delivered'
            )
        ''')
        self.conn.commit()
        logger.info("Database initialized successfully")
    
    def get_geo_info(self, ip_address):
        """Get geographic information from IP address"""
        try:
            if ip_address in ['127.0.0.1', 'localhost'] or ip_address.startswith(('192.168.', '10.', '172.', '0.')):
                return {'country': 'Local', 'city': 'Internal', 'ip': ip_address}
            
            logger.debug(f"Fetching geo info for IP: {ip_address}")
            response = requests.get(f'http://ipapi.co/{ip_address}/json/', timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                logger.debug(f"Geo API response: {data}")
                return {
                    'country': data.get('country_name', 'Unknown'),
                    'city': data.get('city', 'Unknown'),
                    'ip': ip_address
                }
            else:
                logger.warning(f"Geo API returned status: {response.status_code}")
                
        except Exception as e:
            logger.error(f"Geo location error: {str(e)}")
        
        return {'country': 'Unknown', 'city': 'Unknown', 'ip': ip_address}
    
    def send_email_notification(self, pdf_id, client_name, access_data):
        """Send email notification when PDF is opened"""
        try:
            # Get configuration from environment with fallbacks
            smtp_server = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
            smtp_port = int(os.getenv('SMTP_PORT', 587))
            email_from = os.getenv('EMAIL_FROM', '')
            email_password = os.getenv('EMAIL_PASSWORD', '')
            email_to = os.getenv('EMAIL_TO', email_from)  # Default to sender if not specified
            
            # Validate configuration
            if not email_from or not email_password:
                logger.error("Email configuration missing: EMAIL_FROM or EMAIL_PASSWORD not set")
                return "not_configured"
            
            logger.debug(f"Attempting to send email via {smtp_server}:{smtp_port}")
            logger.debug(f"From: {email_from}, To: {email_to}")
            
            # Create email message
            message = MIMEMultipart()
            message['From'] = email_from
            message['To'] = email_to
            message['Subject'] = f"📄 PDF Opened: {pdf_id} - {client_name}"
            
            body = f"""🔔 PDF Tracking Notification

📄 Document: {pdf_id}
👤 Client: {client_name}
🕒 Opened: {access_data['access_time']}
📍 Location: {access_data['city']}, {access_data['country']}
🌐 IP Address: {access_data['ip_address']}
🔍 User Agent: {access_data['user_agent']}

This PDF was successfully delivered and opened by the recipient.

---
PDF Tracking System
"""
            
            message.attach(MIMEText(body, 'plain'))
            
            # Send email
            server = smtplib.SMTP(smtp_server, smtp_port)
            server.set_debuglevel(1)  # Enable verbose debug output
            
            server.starttls()
            server.login(email_from, email_password)
            server.send_message(message)
            server.quit()
            
            logger.info(f"✅ Email notification sent successfully for {pdf_id}")
            return "sent"
            
        except smtplib.SMTPAuthenticationError as e:
            logger.error(f"❌ Email authentication failed: {str(e)}")
            return f"auth_error: {str(e)}"
        except smtplib.SMTPException as e:
            logger.error(f"❌ SMTP error: {str(e)}")
            return f"smtp_error: {str(e)}"
        except Exception as e:
            logger.error(f"❌ Email sending failed: {str(e)}")
            return f"error: {str(e)}"
    
    def send_whatsapp_notification(self, pdf_id, client_name, access_data):
        """Send WhatsApp notification via UltraMSG"""
        try:
            # Get configuration from environment
            instance_id = os.getenv('WHATSAPP_INSTANCE_ID', '')
            token = os.getenv('WHATSAPP_TOKEN', '')
            to_number = os.getenv('WHATSAPP_TO_NUMBER', '')
            
            # Validate configuration
            if not all([instance_id, token, to_number]):
                logger.warning("WhatsApp configuration incomplete")
                return "not_configured"
            
            # Format message
            message = f"""🔔 PDF Tracking Alert

📄 Document: {pdf_id}
👤 Client: {client_name}
🕒 Opened: {access_data['access_time']}
📍 Location: {access_data['city']}, {access_data['country']}
🌐 IP: {access_data['ip_address']}

The document has been opened by the client."""
            
            # Prepare API request
            url = f"https://api.ultramsg.com/{instance_id}/messages/chat"
            payload = {
                "token": token,
                "to": f"+{to_number}",
                "body": message
            }
            
            headers = {
                'Content-Type': 'application/x-www-form-urlencoded'
            }
            
            logger.debug(f"Sending WhatsApp to: +{to_number}")
            logger.debug(f"API URL: {url}")
            
            # Send request
            response = requests.post(
                url, 
                data=payload, 
                headers=headers,
                timeout=60
            )
            
            logger.debug(f"WhatsApp API response: {response.status_code}")
            logger.debug(f"WhatsApp API content: {response.text}")
            
            if response.status_code == 200:
                result = response.json()
                if result.get('sent') == 'true':
                    logger.info(f"✅ WhatsApp notification sent successfully for {pdf_id}")
                    return "sent"
                else:
                    logger.error(f"❌ WhatsApp API returned error: {result}")
                    return f"api_error: {result}"
            else:
                logger.error(f"❌ WhatsApp API HTTP error: {response.status_code} - {response.text}")
                return f"http_error: {response.status_code}"
                
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ WhatsApp request failed: {str(e)}")
            return f"request_error: {str(e)}"
        except Exception as e:
            logger.error(f"❌ WhatsApp notification failed: {str(e)}")
            return f"error: {str(e)}"

    def record_access(self, pdf_id, client_name, ip_address, user_agent):
        """Record document access and send notifications"""
        try:
            logger.info(f"Recording access for {pdf_id} - {client_name}")
            
            # Get location information
            geo_info = self.get_geo_info(ip_address)
            access_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            access_data = {
                'access_time': access_time,
                'ip_address': ip_address,
                'country': geo_info['country'],
                'city': geo_info['city'],
                'user_agent': user_agent
            }
            
            logger.debug(f"Access data: {access_data}")
            
            # Send notifications
            logger.info("Sending email notification...")
            email_status = self.send_email_notification(pdf_id, client_name, access_data)
            
            logger.info("Sending WhatsApp notification...")
            whatsapp_status = self.send_whatsapp_notification(pdf_id, client_name, access_data)
            
            # Save to database
            cursor = self.conn.cursor()
            cursor.execute('''
                INSERT INTO pdf_access 
                (pdf_id, client_name, access_time, ip_address, country, city, user_agent, email_status, whatsapp_status, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                pdf_id, client_name, access_time, ip_address, 
                geo_info['country'], geo_info['city'], user_agent, 
                email_status, whatsapp_status, 'opened'
            ))
            self.conn.commit()
            
            logger.info(f"✅ Successfully recorded access for {pdf_id}")
            logger.info(f"📍 Location: {geo_info['city']}, {geo_info['country']}")
            logger.info(f"📧 Email status: {email_status}")
            logger.info(f"💬 WhatsApp status: {whatsapp_status}")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Error recording access: {str(e)}")
            return False

# Initialize tracker
tracker = PDFTracker()

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/test-email', methods=['GET'])
def test_email():
    """Test email configuration"""
    try:
        test_data = {
            'pdf_id': 'TEST_EMAIL',
            'client_name': 'Test Client',
            'access_time': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'ip_address': '127.0.0.1',
            'country': 'Test Country',
            'city': 'Test City',
            'user_agent': 'Test User Agent'
        }
        
        result = tracker.send_email_notification(
            test_data['pdf_id'], 
            test_data['client_name'], 
            test_data
        )
        
        return jsonify({
            'success': 'sent' in result,
            'status': result,
            'message': 'Email test completed'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/test-whatsapp', methods=['GET'])
def test_whatsapp():
    """Test WhatsApp configuration"""
    try:
        test_data = {
            'pdf_id': 'TEST_WHATSAPP',
            'client_name': 'Test Client',
            'access_time': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'ip_address': '127.0.0.1',
            'country': 'Test Country',
            'city': 'Test City',
            'user_agent': 'Test User Agent'
        }
        
        result = tracker.send_whatsapp_notification(
            test_data['pdf_id'], 
            test_data['client_name'], 
            test_data
        )
        
        return jsonify({
            'success': 'sent' in result,
            'status': result,
            'message': 'WhatsApp test completed'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/track-pdf/<pdf_id>/<client_name>', methods=['GET'])
def track_pdf_access(pdf_id, client_name):
    """Endpoint to track PDF access"""
    try:
        # Get client information
        if request.headers.get('X-Forwarded-For'):
            ip_address = request.headers.get('X-Forwarded-For').split(',')[0]
        else:
            ip_address = request.remote_addr
        
        user_agent = request.headers.get('User-Agent', 'Unknown')
        
        logger.info(f"📥 Tracking request received: {pdf_id} - {client_name}")
        logger.debug(f"IP: {ip_address}")
        logger.debug(f"User Agent: {user_agent}")
        
        # Record the access
        success = tracker.record_access(pdf_id, client_name, ip_address, user_agent)
        
        if success:
            # Return a transparent 1x1 pixel
            pixel = base64.b64decode('R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7')
            response = Response(pixel, mimetype='image/gif')
            response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
            response.headers['Pragma'] = 'no-cache'
            response.headers['Expires'] = '0'
            return response
        else:
            return "Tracking Error", 500
            
    except Exception as e:
        logger.error(f"Tracking error: {str(e)}")
        return "Server Error", 500

@app.route('/analytics/<pdf_id>', methods=['GET'])
def get_pdf_analytics(pdf_id):
    """Get analytics for a specific PDF"""
    try:
        cursor = tracker.conn.cursor()
        cursor.execute('''
            SELECT client_name, access_time, country, city, ip_address, user_agent, email_status, whatsapp_status
            FROM pdf_access 
            WHERE pdf_id = ? 
            ORDER BY access_time DESC
        ''', (pdf_id,))
        
        accesses = cursor.fetchall()
        results = []
        for access in accesses:
            results.append({
                'client_name': access[0],
                'access_time': access[1],
                'country': access[2],
                'city': access[3],
                'ip_address': access[4],
                'user_agent': access[5],
                'email_status': access[6],
                'whatsapp_status': access[7]
            })
        
        return jsonify({
            'pdf_id': pdf_id,
            'total_opens': len(accesses),
            'accesses': results
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/create-document', methods=['POST'])
def create_document():
    """Create a tracked document"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'No JSON data provided'}), 400
        
        pdf_id = data.get('pdf_id', 'DOC_' + datetime.now().strftime("%Y%m%d_%H%M%S"))
        client_name = data.get('client_name', 'Client')
        content = data.get('content', 'Default document content')
        
        # Get base URL
        base_url = request.host_url.rstrip('/')
        
        # Create HTML document with tracking
        tracking_url = f"{base_url}/track-pdf/{pdf_id}/{client_name}"
        
        html_content = f"""<!DOCTYPE html>
<html>
<head>
    <title>Document: {pdf_id}</title>
    <meta charset="UTF-8">
    <style>
        body {{
            font-family: Arial, sans-serif;
            max-width: 800px;
            margin: 0 auto;
            padding: 20px;
            background: white;
            line-height: 1.6;
        }}
        .header {{
            text-align: center;
            border-bottom: 2px solid #333;
            padding-bottom: 10px;
            margin-bottom: 20px;
        }}
        .content {{
            white-space: pre-line;
        }}
        .disclaimer {{
            background: #f5f5f5;
            padding: 10px;
            margin: 20px 0;
            border-left: 4px solid #007cba;
            font-size: 12px;
        }}
        @media print {{
            .disclaimer {{ display: none; }}
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>COMPANY DOCUMENT</h1>
        <p>Document ID: {pdf_id} | Client: {client_name}</p>
    </div>
    
    <div class="disclaimer">
        <strong>Privacy Notice:</strong> This document contains tracking to monitor delivery and engagement for business purposes.
    </div>
    
    <div class="content">
        {content}
    </div>
    
    <!-- Tracking pixel -->
    <img src="{tracking_url}" width="1" height="1" style="display:none" alt="tracking">
</body>
</html>"""
        
        return jsonify({
            'success': True,
            'pdf_id': pdf_id,
            'client_name': client_name,
            'html_content': html_content,
            'tracking_url': tracking_url,
            'download_filename': f"{pdf_id}_{client_name}.html"
        })
        
    except Exception as e:
        logger.error(f"Error creating document: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/config-status', methods=['GET'])
def config_status():
    """Check configuration status"""
    email_configured = bool(os.getenv('EMAIL_FROM') and os.getenv('EMAIL_PASSWORD'))
    whatsapp_configured = bool(
        os.getenv('WHATSAPP_INSTANCE_ID') and 
        os.getenv('WHATSAPP_TOKEN') and 
        os.getenv('WHATSAPP_TO_NUMBER')
    )
    
    return jsonify({
        'email_configured': email_configured,
        'whatsapp_configured': whatsapp_configured,
        'email_from': os.getenv('EMAIL_FROM', 'Not set'),
        'whatsapp_to_number': os.getenv('WHATSAPP_TO_NUMBER', 'Not set')
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    logger.info(f"Starting PDF Tracking System on port {port}")
    logger.info("Test endpoints:")
    logger.info("  - /test-email - Test email configuration")
    logger.info("  - /test-whatsapp - Test WhatsApp configuration")
    logger.info("  - /config-status - Check current configuration")
    app.run(host='0.0.0.0', port=port, debug=False)
