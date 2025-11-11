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
import threading
import time

# Configure logging
logging.basicConfig(
    level=logging.INFO,
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
        self.conn = sqlite3.connect('/tmp/pdf_tracking.db', check_same_thread=False)
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
            response = requests.get(f'http://ipapi.co/{ip_address}/json/', timeout=5)
            
            if response.status_code == 200:
                data = response.json()
                return {
                    'country': data.get('country_name', 'Unknown'),
                    'city': data.get('city', 'Unknown'),
                    'ip': ip_address
                }
        except Exception as e:
            logger.error(f"Geo location error: {str(e)}")
        
        return {'country': 'Unknown', 'city': 'Unknown', 'ip': ip_address}
    
    def send_email_notification_async(self, pdf_id, client_name, access_data):
        """Send email notification in a separate thread to avoid timeouts"""
        def send_email():
            try:
                # Get configuration from environment
                smtp_server = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
                smtp_port = int(os.getenv('SMTP_PORT', 587))
                email_from = os.getenv('EMAIL_FROM', '')
                email_password = os.getenv('EMAIL_PASSWORD', '')
                email_to = os.getenv('EMAIL_TO', email_from)
                
                # Validate configuration
                if not email_from or not email_password:
                    logger.error("Email configuration missing")
                    self.update_email_status(pdf_id, 'not_configured')
                    return
                
                logger.info(f"📧 Starting email send for {pdf_id}")
                
                # Create email message
                message = MIMEMultipart()
                message['From'] = email_from
                message['To'] = email_to
                message['Subject'] = f"PDF Opened: {pdf_id} - {client_name}"
                
                body = f"""PDF Tracking Notification

Document: {pdf_id}
Client: {client_name}
Opened: {access_data['access_time']}
Location: {access_data['city']}, {access_data['country']}
IP Address: {access_data['ip_address']}

This PDF was successfully delivered and opened by the recipient."""
                
                message.attach(MIMEText(body, 'plain'))
                
                # Send email with timeout
                logger.debug(f"Connecting to {smtp_server}:{smtp_port}")
                server = smtplib.SMTP(smtp_server, smtp_port, timeout=10)
                server.starttls()
                server.login(email_from, email_password)
                server.send_message(message)
                server.quit()
                
                logger.info(f"✅ Email sent successfully for {pdf_id}")
                self.update_email_status(pdf_id, 'sent')
                
            except smtplib.SMTPAuthenticationError as e:
                logger.error(f"❌ Email authentication failed: {str(e)}")
                self.update_email_status(pdf_id, f'auth_error: {str(e)}')
            except smtplib.SMTPException as e:
                logger.error(f"❌ SMTP error: {str(e)}")
                self.update_email_status(pdf_id, f'smtp_error: {str(e)}')
            except Exception as e:
                logger.error(f"❌ Email sending failed: {str(e)}")
                self.update_email_status(pdf_id, f'error: {str(e)}')
        
        # Start email in background thread
        thread = threading.Thread(target=send_email)
        thread.daemon = True
        thread.start()
        
        # Return immediately to avoid timeout
        return 'processing'
    
    def send_whatsapp_notification_async(self, pdf_id, client_name, access_data):
        """Send WhatsApp notification in a separate thread"""
        def send_whatsapp():
            try:
                # Get configuration from environment
                instance_id = os.getenv('WHATSAPP_INSTANCE_ID', '')
                token = os.getenv('WHATSAPP_TOKEN', '')
                to_number = os.getenv('WHATSAPP_TO_NUMBER', '')
                
                # Validate configuration
                if not all([instance_id, token, to_number]):
                    logger.warning("WhatsApp configuration incomplete")
                    self.update_whatsapp_status(pdf_id, 'not_configured')
                    return
                
                logger.info(f"💬 Starting WhatsApp send for {pdf_id}")
                
                # Format message
                message = f"""PDF Tracking Alert

Document: {pdf_id}
Client: {client_name}
Opened: {access_data['access_time']}
Location: {access_data['city']}, {access_data['country']}
IP: {access_data['ip_address']}

The document has been opened by the client."""
                
                # Prepare API request
                url = f"https://api.ultramsg.com/{instance_id}/messages/chat"
                payload = {
                    "token": token,
                    "to": f"+{to_number}",
                    "body": message
                }
                
                # Send request with timeout
                response = requests.post(url, data=payload, timeout=10)
                
                if response.status_code == 200:
                    result = response.json()
                    if result.get('sent') == 'true':
                        logger.info(f"✅ WhatsApp sent successfully for {pdf_id}")
                        self.update_whatsapp_status(pdf_id, 'sent')
                    else:
                        logger.error(f"❌ WhatsApp API error: {result}")
                        self.update_whatsapp_status(pdf_id, f'api_error: {result}')
                else:
                    logger.error(f"❌ WhatsApp HTTP error: {response.status_code}")
                    self.update_whatsapp_status(pdf_id, f'http_error: {response.status_code}')
                    
            except Exception as e:
                logger.error(f"❌ WhatsApp sending failed: {str(e)}")
                self.update_whatsapp_status(pdf_id, f'error: {str(e)}')
        
        # Start WhatsApp in background thread
        thread = threading.Thread(target=send_whatsapp)
        thread.daemon = True
        thread.start()
        
        # Return immediately to avoid timeout
        return 'processing'
    
    def update_email_status(self, pdf_id, status):
        """Update email status in database"""
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                'UPDATE pdf_access SET email_status = ? WHERE pdf_id = ? ORDER BY id DESC LIMIT 1',
                (status, pdf_id)
            )
            self.conn.commit()
            logger.debug(f"Updated email status for {pdf_id}: {status}")
        except Exception as e:
            logger.error(f"Error updating email status: {str(e)}")
    
    def update_whatsapp_status(self, pdf_id, status):
        """Update WhatsApp status in database"""
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                'UPDATE pdf_access SET whatsapp_status = ? WHERE pdf_id = ? ORDER BY id DESC LIMIT 1',
                (status, pdf_id)
            )
            self.conn.commit()
            logger.debug(f"Updated WhatsApp status for {pdf_id}: {status}")
        except Exception as e:
            logger.error(f"Error updating WhatsApp status: {str(e)}")

    def record_access(self, pdf_id, client_name, ip_address, user_agent):
        """Record document access and send notifications (non-blocking)"""
        try:
            logger.info(f"Recording access for {pdf_id} - {client_name}")
            
            # Get location information (fast operation)
            geo_info = self.get_geo_info(ip_address)
            access_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            access_data = {
                'access_time': access_time,
                'ip_address': ip_address,
                'country': geo_info['country'],
                'city': geo_info['city'],
                'user_agent': user_agent
            }
            
            # Save to database first (fast operation)
            cursor = self.conn.cursor()
            cursor.execute('''
                INSERT INTO pdf_access 
                (pdf_id, client_name, access_time, ip_address, country, city, user_agent, email_status, whatsapp_status, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                pdf_id, client_name, access_time, ip_address, 
                geo_info['country'], geo_info['city'], user_agent, 
                'pending', 'pending', 'opened'
            ))
            self.conn.commit()
            
            # Start notifications in background (non-blocking)
            email_status = self.send_email_notification_async(pdf_id, client_name, access_data)
            whatsapp_status = self.send_whatsapp_notification_async(pdf_id, client_name, access_data)
            
            logger.info(f"✅ Access recorded for {pdf_id} from {geo_info['city']}, {geo_info['country']}")
            logger.info(f"📧 Email: {email_status}, 💬 WhatsApp: {whatsapp_status}")
            
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
    """Quick email test with timeout"""
    try:
        # Simple test that won't timeout
        smtp_server = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
        smtp_port = int(os.getenv('SMTP_PORT', 587))
        email_from = os.getenv('EMAIL_FROM', '')
        
        if not email_from:
            return jsonify({
                'success': False,
                'error': 'EMAIL_FROM not configured'
            })
        
        # Just test connection, don't send email
        server = smtplib.SMTP(smtp_server, smtp_port, timeout=5)
        server.quit()
        
        return jsonify({
            'success': True,
            'message': f'Can connect to {smtp_server}:{smtp_port}',
            'email_from': email_from
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/test-email-full', methods=['GET'])
def test_email_full():
    """Full email test (runs in background)"""
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
        
        # This will run in background and not block
        tracker.send_email_notification_async(
            test_data['pdf_id'], 
            test_data['client_name'], 
            test_data
        )
        
        return jsonify({
            'success': True,
            'message': 'Email test started in background. Check logs for results.',
            'test_id': test_data['pdf_id']
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/test-whatsapp', methods=['GET'])
def test_whatsapp():
    """WhatsApp test (runs in background)"""
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
        
        tracker.send_whatsapp_notification_async(
            test_data['pdf_id'], 
            test_data['client_name'], 
            test_data
        )
        
        return jsonify({
            'success': True,
            'message': 'WhatsApp test started in background. Check logs for results.',
            'test_id': test_data['pdf_id']
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/track-pdf/<pdf_id>/<client_name>', methods=['GET'])
def track_pdf_access(pdf_id, client_name):
    """Endpoint to track PDF access - FAST and NON-BLOCKING"""
    try:
        # Get client information
        if request.headers.get('X-Forwarded-For'):
            ip_address = request.headers.get('X-Forwarded-For').split(',')[0]
        else:
            ip_address = request.remote_addr
        
        user_agent = request.headers.get('User-Agent', 'Unknown')
        
        logger.info(f"📥 Tracking request: {pdf_id} - {client_name} from {ip_address}")
        
        # Record the access (non-blocking)
        success = tracker.record_access(pdf_id, client_name, ip_address, user_agent)
        
        if success:
            # Return a transparent 1x1 pixel immediately
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
    </style>
</head>
<body>
    <div class="header">
        <h1>COMPANY DOCUMENT</h1>
        <p>Document ID: {pdf_id} | Client: {client_name}</p>
    </div>
    
    <div class="disclaimer">
        <strong>Privacy Notice:</strong> This document contains tracking to monitor delivery and engagement.
    </div>
    
    <div class="content">
        {content}
    </div>
    
    <!-- Tracking pixel -->
    <img src="{tracking_url}" width="1" height="1" style="display:none">
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
        'email_from': 'Configured' if email_configured else 'Not set',
        'whatsapp_to_number': 'Configured' if whatsapp_configured else 'Not set',
        'smtp_server': os.getenv('SMTP_SERVER', 'smtp.gmail.com'),
        'smtp_port': os.getenv('SMTP_PORT', '587')
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    logger.info(f"🚀 Starting PDF Tracking System on port {port}")
    logger.info("📧 Test endpoints:")
    logger.info("  - /test-email - Quick connection test")
    logger.info("  - /test-email-full - Full email test (background)")
    logger.info("  - /test-whatsapp - WhatsApp test (background)")
    logger.info("  - /config-status - Check configuration")
    app.run(host='0.0.0.0', port=port, debug=False)
