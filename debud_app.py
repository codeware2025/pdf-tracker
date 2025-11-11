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

# Enhanced logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('debug.log')
    ]
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

def check_environment_variables():
    """Check if all required environment variables are set"""
    required_vars = {
        'EMAIL_FROM': os.getenv('EMAIL_FROM'),
        'EMAIL_PASSWORD': os.getenv('EMAIL_PASSWORD'),
        'EMAIL_TO': os.getenv('EMAIL_TO'),
        'WHATSAPP_INSTANCE_ID': os.getenv('WHATSAPP_INSTANCE_ID'),
        'WHATSAPP_TOKEN': os.getenv('WHATSAPP_TOKEN'),
        'WHATSAPP_TO_NUMBER': os.getenv('WHATSAPP_TO_NUMBER')
    }
    
    logger.info("🔍 CHECKING ENVIRONMENT VARIABLES:")
    for key, value in required_vars.items():
        if value:
            logger.info(f"✅ {key}: {'*' * 8}{value[-4:]}" if len(value) > 8 else f"✅ {key}: {value}")
        else:
            logger.error(f"❌ {key}: NOT SET")
    
    return required_vars

class DebugPDFTracker:
    def __init__(self):
        self.env_vars = check_environment_variables()
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
                debug_info TEXT,
                status TEXT DEFAULT 'delivered'
            )
        ''')
        self.conn.commit()
    
    def test_email_connection(self):
        """Test email configuration with detailed debugging"""
        try:
            logger.info("🧪 TESTING EMAIL CONNECTION...")
            
            smtp_server = "smtp.gmail.com"
            smtp_port = 587
            email_from = self.env_vars['EMAIL_FROM']
            email_password = self.env_vars['EMAIL_PASSWORD']
            
            if not email_from or not email_password:
                logger.error("❌ Email credentials missing")
                return False
            
            logger.debug(f"Connecting to {smtp_server}:{smtp_port}")
            server = smtplib.SMTP(smtp_server, smtp_port)
            server.set_debuglevel(1)  # Enable verbose debugging
            
            logger.debug("Starting TLS...")
            server.starttls()
            
            logger.debug(f"Attempting login with: {email_from}")
            server.login(email_from, email_password)
            
            logger.debug("Login successful, closing connection...")
            server.quit()
            
            logger.info("✅ EMAIL CONNECTION TEST: SUCCESS")
            return True
            
        except smtplib.SMTPAuthenticationError as e:
            logger.error(f"❌ EMAIL AUTHENTICATION FAILED: {e}")
            logger.error("💡 TIP: Use Gmail App Password, not your regular password")
            return False
        except Exception as e:
            logger.error(f"❌ EMAIL CONNECTION FAILED: {e}")
            return False
    
    def test_whatsapp_connection(self):
        """Test WhatsApp configuration with detailed debugging"""
        try:
            logger.info("🧪 TESTING WHATSAPP CONNECTION...")
            
            instance_id = self.env_vars['WHATSAPP_INSTANCE_ID']
            token = self.env_vars['WHATSAPP_TOKEN']
            
            if not instance_id or not token:
                logger.error("❌ WhatsApp credentials missing")
                return False
            
            # Test the instance status
            url = f"https://api.ultramsg.com/{instance_id}/instance/me"
            params = {"token": token}
            
            logger.debug(f"Testing WhatsApp API: {url}")
            response = requests.get(url, params=params, timeout=10)
            
            logger.debug(f"API Response Status: {response.status_code}")
            logger.debug(f"API Response: {response.text}")
            
            if response.status_code == 200:
                data = response.json()
                if data.get('accountStatus') == 'authenticated':
                    logger.info("✅ WHATSAPP CONNECTION TEST: SUCCESS")
                    return True
                else:
                    logger.error(f"❌ WHATSAPP NOT AUTHENTICATED: {data}")
                    return False
            else:
                logger.error(f"❌ WHATSAPP API ERROR: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"❌ WHATSAPP CONNECTION FAILED: {e}")
            return False
    
    def send_email_notification(self, pdf_id, client_name, access_data):
        """Send email notification with enhanced error handling"""
        try:
            logger.info(f"📧 ATTEMPTING TO SEND EMAIL FOR {pdf_id}")
            
            email_from = self.env_vars['EMAIL_FROM']
            email_password = self.env_vars['EMAIL_PASSWORD']
            email_to = self.env_vars['EMAIL_TO']
            
            if not all([email_from, email_password, email_to]):
                error_msg = "Email configuration incomplete"
                logger.error(f"❌ {error_msg}")
                return f"config_error: {error_msg}"
            
            # Create message
            message = MIMEMultipart()
            message['From'] = email_from
            message['To'] = email_to
            message['Subject'] = f"PDF Opened: {pdf_id} - {client_name}"
            
            body = f"""
            PDF Tracking Notification
            
            Document: {pdf_id}
            Client: {client_name}
            Opened: {access_data['access_time']}
            Location: {access_data['city']}, {access_data['country']}
            IP Address: {access_data['ip_address']}
            
            This PDF was successfully delivered and opened by the recipient.
            """
            
            message.attach(MIMEText(body, 'plain'))
            
            # Send email
            logger.debug("Connecting to SMTP server...")
            server = smtplib.SMTP('smtp.gmail.com', 587)
            server.set_debuglevel(1)  # Enable verbose output
            
            logger.debug("Starting TLS...")
            server.starttls()
            
            logger.debug("Logging in...")
            server.login(email_from, email_password)
            
            logger.debug("Sending email...")
            server.send_message(message)
            server.quit()
            
            logger.info(f"✅ EMAIL SENT SUCCESSFULLY FOR {pdf_id}")
            return "sent"
            
        except smtplib.SMTPAuthenticationError as e:
            error_msg = f"SMTP Authentication failed: {e}"
            logger.error(f"❌ {error_msg}")
            return f"auth_error: {error_msg}"
        except smtplib.SMTPException as e:
            error_msg = f"SMTP error: {e}"
            logger.error(f"❌ {error_msg}")
            return f"smtp_error: {error_msg}"
        except Exception as e:
            error_msg = f"Unexpected error: {e}"
            logger.error(f"❌ {error_msg}")
            return f"error: {error_msg}"
    
    def send_whatsapp_notification(self, pdf_id, client_name, access_data):
        """Send WhatsApp notification with enhanced error handling"""
        try:
            logger.info(f"💬 ATTEMPTING TO SEND WHATSAPP FOR {pdf_id}")
            
            instance_id = self.env_vars['WHATSAPP_INSTANCE_ID']
            token = self.env_vars['WHATSAPP_TOKEN']
            to_number = self.env_vars['WHATSAPP_TO_NUMBER']
            
            if not all([instance_id, token, to_number]):
                error_msg = "WhatsApp configuration incomplete"
                logger.error(f"❌ {error_msg}")
                return f"config_error: {error_msg}"
            
            message = f"""PDF Tracking Alert

Document: {pdf_id}
Client: {client_name}
Opened: {access_data['access_time']}
Location: {access_data['city']}, {access_data['country']}
IP: {access_data['ip_address']}

PDF successfully delivered and opened!"""
            
            url = f"https://api.ultramsg.com/{instance_id}/messages/chat"
            payload = {
                "token": token,
                "to": f"+{to_number}",
                "body": message
            }
            
            logger.debug(f"WhatsApp API URL: {url}")
            logger.debug(f"WhatsApp Payload: {payload}")
            
            response = requests.post(url, data=payload, timeout=30)
            
            logger.debug(f"API Response Status: {response.status_code}")
            logger.debug(f"API Response Text: {response.text}")
            
            if response.status_code == 200:
                logger.info(f"✅ WHATSAPP SENT SUCCESSFULLY FOR {pdf_id}")
                return "sent"
            else:
                error_msg = f"API returned {response.status_code}: {response.text}"
                logger.error(f"❌ WHATSAPP FAILED: {error_msg}")
                return f"api_error: {error_msg}"
                
        except requests.exceptions.RequestException as e:
            error_msg = f"Request failed: {e}"
            logger.error(f"❌ WHATSAPP REQUEST FAILED: {error_msg}")
            return f"request_error: {error_msg}"
        except Exception as e:
            error_msg = f"Unexpected error: {e}"
            logger.error(f"❌ WHATSAPP FAILED: {error_msg}")
            return f"error: {error_msg}"
    
    def get_geo_info(self, ip_address):
        """Get geographic information from IP address"""
        try:
            if ip_address.startswith(('192.168.', '10.', '172.', '127.', '0.')):
                return {'country': 'Local', 'city': 'Internal', 'ip': ip_address}
            
            response = requests.get(f'http://ipapi.co/{ip_address}/json/', timeout=10)
            if response.status_code == 200:
                data = response.json()
                return {
                    'country': data.get('country_name', 'Unknown'),
                    'city': data.get('city', 'Unknown'),
                    'ip': ip_address
                }
        except Exception as e:
            logger.error(f"Geo location error: {e}")
        
        return {'country': 'Unknown', 'city': 'Unknown', 'ip': ip_address}

    def record_access(self, pdf_id, client_name, ip_address, user_agent):
        """Record document access and send notifications"""
        try:
            logger.info(f"🎯 RECORDING ACCESS: {pdf_id} for {client_name}")
            
            geo_info = self.get_geo_info(ip_address)
            access_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            access_data = {
                'access_time': access_time,
                'ip_address': ip_address,
                'country': geo_info['country'],
                'city': geo_info['city'],
                'user_agent': user_agent
            }
            
            # Send notifications
            logger.info("Sending notifications...")
            email_status = self.send_email_notification(pdf_id, client_name, access_data)
            whatsapp_status = self.send_whatsapp_notification(pdf_id, client_name, access_data)
            
            debug_info = f"IP: {ip_address}, Geo: {geo_info['city']}, {geo_info['country']}"
            
            # Save to database
            cursor = self.conn.cursor()
            cursor.execute('''
                INSERT INTO pdf_access 
                (pdf_id, client_name, access_time, ip_address, country, city, user_agent, email_status, whatsapp_status, debug_info, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (pdf_id, client_name, access_time, ip_address, 
                  geo_info['country'], geo_info['city'], user_agent, 
                  email_status, whatsapp_status, debug_info, 'opened'))
            self.conn.commit()
            
            logger.info(f"✅ ACCESS RECORDED: {pdf_id}")
            logger.info(f"   📧 Email: {email_status}")
            logger.info(f"   💬 WhatsApp: {whatsapp_status}")
            logger.info(f"   📍 Location: {geo_info['city']}, {geo_info['country']}")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ ERROR RECORDING ACCESS: {e}")
            return False

# Initialize tracker
tracker = DebugPDFTracker()

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/debug')
def debug_info():
    """Debug endpoint to check configuration"""
    email_test = tracker.test_email_connection()
    whatsapp_test = tracker.test_whatsapp_connection()
    
    return jsonify({
        'environment_variables': {
            'EMAIL_FROM_set': bool(tracker.env_vars['EMAIL_FROM']),
            'EMAIL_PASSWORD_set': bool(tracker.env_vars['EMAIL_PASSWORD']),
            'EMAIL_TO_set': bool(tracker.env_vars['EMAIL_TO']),
            'WHATSAPP_INSTANCE_ID_set': bool(tracker.env_vars['WHATSAPP_INSTANCE_ID']),
            'WHATSAPP_TOKEN_set': bool(tracker.env_vars['WHATSAPP_TOKEN']),
            'WHATSAPP_TO_NUMBER_set': bool(tracker.env_vars['WHATSAPP_TO_NUMBER'])
        },
        'tests': {
            'email_connection': email_test,
            'whatsapp_connection': whatsapp_test
        },
        'server_info': {
            'render_url': os.getenv('RENDER_EXTERNAL_URL'),
            'python_version': os.getenv('PYTHON_VERSION')
        }
    })

@app.route('/test-notifications')
def test_notifications():
    """Test endpoint to trigger notifications"""
    test_ip = request.remote_addr
    test_user_agent = request.headers.get('User-Agent', 'Test')
    
    success = tracker.record_access(
        "TEST_DOC", 
        "Test Client", 
        test_ip, 
        test_user_agent
    )
    
    return jsonify({
        'success': success,
        'message': 'Test notifications triggered. Check logs for details.'
    })

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
        
        logger.info(f"📄 TRACKING REQUEST: {pdf_id} - {client_name}")
        logger.info(f"   IP: {ip_address}")
        logger.info(f"   User Agent: {user_agent}")
        
        # Record the access
        success = tracker.record_access(pdf_id, client_name, ip_address, user_agent)
        
        if success:
            # Return a transparent 1x1 pixel
            pixel = base64.b64decode('R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7')
            return Response(pixel, mimetype='image/gif', headers={
                'Cache-Control': 'no-cache, no-store, must-revalidate',
                'Pragma': 'no-cache',
                'Expires': '0'
            })
        else:
            return "Tracking Error", 500
            
    except Exception as e:
        logger.error(f"❌ TRACKING ERROR: {e}")
        return "Server Error", 500

@app.route('/analytics/<pdf_id>', methods=['GET'])
def get_pdf_analytics(pdf_id):
    """Get analytics for a specific PDF"""
    try:
        cursor = tracker.conn.cursor()
        cursor.execute('''
            SELECT client_name, access_time, country, city, ip_address, user_agent, email_status, whatsapp_status, debug_info
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
                'whatsapp_status': access[7],
                'debug_info': access[8]
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
        data = request.json
        pdf_id = data.get('pdf_id', 'DOC_' + datetime.now().strftime("%Y%m%d_%H%M%S"))
        client_name = data.get('client_name', 'Client')
        content = data.get('content', 'Default document content')
        
        # Get base URL
        base_url = request.host_url
        if base_url.endswith('/'):
            base_url = base_url[:-1]
        
        # Create HTML document with tracking
        tracking_url = f"{base_url}/track-pdf/{pdf_id}/{client_name}"
        
        html_content = f"""<!DOCTYPE html>
<html>
<head>
    <title>Document: {pdf_id}</title>
    <style>
        body {{
            font-family: Arial, sans-serif;
            max-width: 800px;
            margin: 0 auto;
            padding: 20px;
            background: white;
        }}
        .header {{
            text-align: center;
            border-bottom: 2px solid #333;
            padding-bottom: 10px;
            margin-bottom: 20px;
        }}
        .content {{
            line-height: 1.6;
            white-space: pre-line;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>COMPANY DOCUMENT</h1>
        <p>Document ID: {pdf_id} | Client: {client_name}</p>
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
        return jsonify({'success': False, 'error': str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    logger.info(f"🚀 Starting Debug PDF Tracker on port {port}")
    app.run(host='0.0.0.0', port=port, debug=False)
