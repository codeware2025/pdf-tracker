import os
import requests
import sqlite3
from datetime import datetime
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import logging
from flask import Flask, request, Response, render_template
import base64

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Environment variables for configuration
EMAIL_CONFIG = {
    'smtp_server': os.getenv('SMTP_SERVER', 'smtp.gmail.com'),
    'smtp_port': int(os.getenv('SMTP_PORT', 587)),
    'email_from': os.getenv('EMAIL_FROM'),
    'email_password': os.getenv('EMAIL_PASSWORD'),
    'email_to': os.getenv('EMAIL_TO')
}

WHATSAPP_CONFIG = {
    'instance_id': os.getenv('WHATSAPP_INSTANCE_ID'),
    'token': os.getenv('WHATSAPP_TOKEN'),
    'to_number': os.getenv('WHATSAPP_TO_NUMBER')
}

class ProductionPDFTracker:
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
    
    def send_email_notification(self, pdf_id, client_name, access_data):
        """Send email notification when PDF is opened"""
        try:
            config = EMAIL_CONFIG
            if not all([config['email_from'], config['email_password'], config['email_to']]):
                logger.warning("Email configuration incomplete")
                return "not_configured"
            
            message = MIMEMultipart()
            message['From'] = config['email_from']
            message['To'] = config['email_to']
            message['Subject'] = f"PDF Opened: {pdf_id} - {client_name}"
            
            body = f"""
            PDF Tracking Notification
            
            Document: {pdf_id}
            Client: {client_name}
            Opened: {access_data['access_time']}
            Location: {access_data['city']}, {access_data['country']}
            IP Address: {access_data['ip_address']}
            User Agent: {access_data['user_agent']}
            
            This PDF was successfully delivered and opened by the recipient.
            """
            
            message.attach(MIMEText(body, 'plain'))
            
            server = smtplib.SMTP(config['smtp_server'], config['smtp_port'])
            server.starttls()
            server.login(config['email_from'], config['email_password'])
            server.send_message(message)
            server.quit()
            
            logger.info(f"Email notification sent for {pdf_id}")
            return "sent"
            
        except Exception as e:
            logger.error(f"Email notification failed: {e}")
            return f"error: {str(e)}"
    
    def send_whatsapp_notification(self, pdf_id, client_name, access_data):
        """Send WhatsApp notification via UltraMSG"""
        try:
            config = WHATSAPP_CONFIG
            if not all([config['instance_id'], config['token'], config['to_number']]):
                logger.warning("WhatsApp configuration incomplete")
                return "not_configured"
            
            message = f"""PDF Tracking Alert

Document: {pdf_id}
Client: {client_name}
Opened: {access_data['access_time']}
Location: {access_data['city']}, {access_data['country']}
IP: {access_data['ip_address']}

PDF successfully delivered and opened!"""
            
            url = f"https://api.ultramsg.com/{config['instance_id']}/messages/chat"
            payload = {
                "token": config['token'],
                "to": f"+{config['to_number']}",
                "body": message
            }
            
            response = requests.post(url, data=payload, timeout=10)
            
            if response.status_code == 200:
                logger.info(f"WhatsApp notification sent for {pdf_id}")
                return "sent"
            else:
                logger.error(f"WhatsApp API error: {response.status_code}")
                return f"api_error_{response.status_code}"
                
        except Exception as e:
            logger.error(f"WhatsApp notification failed: {e}")
            return f"error: {str(e)}"

    def record_access(self, pdf_id, client_name, ip_address, user_agent):
        """Record document access and send notifications"""
        try:
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
            email_status = self.send_email_notification(pdf_id, client_name, access_data)
            whatsapp_status = self.send_whatsapp_notification(pdf_id, client_name, access_data)
            
            # Save to database
            cursor = self.conn.cursor()
            cursor.execute('''
                INSERT INTO pdf_access 
                (pdf_id, client_name, access_time, ip_address, country, city, user_agent, email_status, whatsapp_status, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (pdf_id, client_name, access_time, ip_address, 
                  geo_info['country'], geo_info['city'], user_agent, 
                  email_status, whatsapp_status, 'opened'))
            self.conn.commit()
            
            logger.info(f"Access recorded for {pdf_id} from {geo_info['city']}, {geo_info['country']}")
            return True
            
        except Exception as e:
            logger.error(f"Error recording access: {e}")
            return False

# Initialize tracker
tracker = ProductionPDFTracker()

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/health')
def health():
    return {'status': 'healthy', 'message': 'PDF Tracker is running'}

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
        logger.error(f"Tracking error: {e}")
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
        
        return {
            'pdf_id': pdf_id,
            'total_opens': len(accesses),
            'accesses': results
        }
    except Exception as e:
        return {'error': str(e)}, 500

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
        <strong>Privacy Notice:</strong> This document contains tracking to monitor delivery and engagement for business purposes.
    </div>
    
    <div class="content">
        {content}
    </div>
    
    <!-- Tracking pixel -->
    <img src="{tracking_url}" width="1" height="1" style="display:none">
</body>
</html>"""
        
        return {
            'success': True,
            'pdf_id': pdf_id,
            'client_name': client_name,
            'html_content': html_content,
            'tracking_url': tracking_url,
            'download_filename': f"{pdf_id}_{client_name}.html"
        }
        
    except Exception as e:
        return {'success': False, 'error': str(e)}, 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)