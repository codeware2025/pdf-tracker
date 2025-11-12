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
    
    def get_ip_location_fallback(self, ip_address):
        """Get approximate location based on IP as fallback"""
        try:
            # Try ipapi.co first
            response = requests.get(f'https://ipapi.co/{ip_address}/json/', timeout=5)
            if response.status_code == 200:
                data = response.json()
                if data.get('latitude') and data.get('longitude'):
                    return {
                        'latitude': float(data['latitude']),
                        'longitude': float(data['longitude']),
                        'accuracy': 5000,  # 5km accuracy for IP-based
                        'city': data.get('city', 'Unknown'),
                        'region': data.get('region', 'Unknown'),
                        'country': data.get('country_name', 'Unknown')
                    }
        except Exception as e:
            logger.debug(f"IP location fallback failed: {e}")
        
        # Return a default location if IP geolocation fails
        return {
            'latitude': 0.0,
            'longitude': 0.0,
            'accuracy': 10000,  # 10km accuracy
            'city': 'Unknown',
            'region': 'Unknown', 
            'country': 'Unknown'
        }
    
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
            
            # Always show coordinates, even for basic location
            accuracy_meters = min(location_data['accuracy'], 10000)  # Cap at 10km
            if location_data['gps_source'] == 'browser_gps':
                if accuracy_meters < 50:
                    accuracy_display = "🎯 EXTREME PRECISION GPS"
                    accuracy_info = f"Extreme Accuracy (~{accuracy_meters:.0f}m)"
                elif accuracy_meters < 200:
                    accuracy_display = "📍 HIGH PRECISION GPS" 
                    accuracy_info = f"High Accuracy (~{accuracy_meters:.0f}m)"
                else:
                    accuracy_display = "📡 GOOD PRECISION GPS"
                    accuracy_info = f"Good Accuracy (~{accuracy_meters:.0f}m)"
            else:
                accuracy_display = "🌐 IP-BASED LOCATION"
                accuracy_info = f"Approximate Area (~{accuracy_meters/1000:.1f}km)"
            
            # Always include GPS coordinates section
            lat = location_data['latitude']
            lng = location_data['longitude']
            google_maps_url = f"https://www.google.com/maps?q={lat},{lng}"
            apple_maps_url = f"https://maps.apple.com/?q={lat},{lng}"
            
            gps_section = f"""
🎯 LOCATION COORDINATES:
   📍 Latitude: {lat:.6f}
   📍 Longitude: {lng:.6f}
   📏 {accuracy_info}
   🔧 Source: {accuracy_display}

🗺️ MAP LINKS:
   • Google Maps: {google_maps_url}
   • Apple Maps: {apple_maps_url}

"""
            
            body = f"""🔔 DOCUMENT TRACKING NOTIFICATION

📄 Document: {pdf_id}
👤 Client: {client_name}
🕒 Opened: {access_data['access_time']}
🌐 IP Address: {access_data['ip_address']}

📍 LOCATION WHERE DOCUMENT WAS OPENED:
   🏙️ City: {location_data['city']}
   🏞️ Region: {location_data['region']}
   🌍 Country: {location_data['country']}
   📏 {accuracy_info}
   🔧 Source: {accuracy_display}

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
        """Send WhatsApp notification with ALWAYS GPS coordinates"""
        try:
            instance_id = os.getenv('WHATSAPP_INSTANCE_ID', '')
            token = os.getenv('WHATSAPP_TOKEN', '')
            to_number = os.getenv('WHATSAPP_TO_NUMBER', '')
            
            if not all([instance_id, token, to_number]):
                logger.warning("WhatsApp configuration incomplete")
                return "not_configured"
            
            # Always show coordinates with accuracy info
            accuracy_meters = min(location_data['accuracy'], 10000)  # Cap at 10km
            if location_data['gps_source'] == 'browser_gps':
                if accuracy_meters < 50:
                    accuracy_display = "🎯 EXTREME PRECISION GPS"
                    accuracy_info = f"Extreme Accuracy (~{accuracy_meters:.0f}m)"
                elif accuracy_meters < 200:
                    accuracy_display = "📍 HIGH PRECISION GPS"
                    accuracy_info = f"High Accuracy (~{accuracy_meters:.0f}m)"
                else:
                    accuracy_display = "📡 GOOD PRECISION GPS" 
                    accuracy_info = f"Good Accuracy (~{accuracy_meters:.0f}m)"
            else:
                accuracy_display = "🌐 IP-BASED LOCATION"
                accuracy_info = f"Approximate Area (~{accuracy_meters/1000:.1f}km)"
            
            # Build location string
            location_parts = []
            if location_data['city'] != 'Unknown':
                location_parts.append(location_data['city'])
            if location_data['region'] != 'Unknown':
                location_parts.append(location_data['region'])
            if location_data['country'] != 'Unknown':
                location_parts.append(location_data['country'])
            
            location_str = ', '.join(location_parts) if location_parts else 'Location tracked'
            
            # ALWAYS include GPS coordinates in WhatsApp
            lat = location_data['latitude']
            lng = location_data['longitude']
            maps_link = f"https://maps.google.com/?q={lat},{lng}"
            
            gps_section = f"""
📍 *Coordinates:*
   🎯 {lat:.6f}, {lng:.6f}
   📏 {accuracy_info}
   🔧 {accuracy_display}

🗺️ *View on Maps:*
   {maps_link}

"""
            
            message = f"""📍 *DOCUMENT OPENED - LOCATION TRACKING*

📄 *Document:* {pdf_id}
👤 *Client:* {client_name}
🕒 *Time:* {access_data['access_time']}
🌐 *IP:* {access_data['ip_address']}

🏙️ *Location:* {location_str}
📏 {accuracy_info}
🔧 {accuracy_display}

{gps_section}
Document opened and location tracked! 🎯"""
            
            url = f"https://api.ultramsg.com/{instance_id}/messages/chat"
            payload = {
                "token": token,
                "to": f"+{to_number}",
                "body": message
            }
            
            headers = {
                'Content-Type': 'application/x-www-form-urlencoded'
            }
            
            logger.info(f"💬 Sending WhatsApp to +{to_number}")
            response = requests.post(url, data=payload, headers=headers, timeout=15)
            
            if response.status_code == 200:
                result = response.json()
                if result.get('sent') == 'true':
                    logger.info(f"✅ WhatsApp sent successfully for {pdf_id}")
                    return "sent"
                else:
                    logger.error(f"❌ WhatsApp API error: {result}")
                    return f"api_error: {result}"
            else:
                logger.error(f"❌ WhatsApp HTTP error: {response.status_code}")
                return f"http_error: {response.status_code}"
                
        except Exception as e:
            logger.error(f"❌ WhatsApp sending failed: {str(e)}")
            return f"error: {str(e)}"

    def record_access_async(self, pdf_id, client_name, ip_address, user_agent, gps_data=None):
        """Record access and send notifications in background thread - ALWAYS with coordinates"""
        def process_notifications():
            try:
                logger.info(f"🎯 Processing notifications for {pdf_id}")
                
                access_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
                access_data = {
                    'access_time': access_time,
                    'ip_address': ip_address,
                    'user_agent': user_agent
                }
                
                # ALWAYS have coordinates - use GPS if available, otherwise IP-based fallback
                if gps_data and gps_data.get('latitude') and gps_data.get('longitude'):
                    # Use actual GPS data
                    raw_accuracy = gps_data.get('accuracy', 1000)
                    capped_accuracy = min(raw_accuracy, 1000)
                    
                    location_data = {
                        'country': gps_data.get('country', 'GPS Location'),
                        'city': gps_data.get('city', 'Exact Coordinates'),
                        'region': gps_data.get('region', 'Precise Tracking'),
                        'latitude': gps_data['latitude'],
                        'longitude': gps_data['longitude'],
                        'accuracy': capped_accuracy,
                        'gps_source': 'browser_gps',
                        'service': 'browser_geolocation'
                    }
                    logger.info(f"🎯 Using real-time GPS coordinates for {pdf_id}")
                    logger.info(f"📍 GPS Location: {location_data['latitude']:.6f}, {location_data['longitude']:.6f}")
                    
                else:
                    # Use IP-based fallback coordinates
                    ip_location = self.get_ip_location_fallback(ip_address)
                    location_data = {
                        'country': ip_location['country'],
                        'city': ip_location['city'],
                        'region': ip_location['region'],
                        'latitude': ip_location['latitude'],
                        'longitude': ip_location['longitude'],
                        'accuracy': ip_location['accuracy'],
                        'gps_source': 'ip_fallback',
                        'service': 'ip_geolocation'
                    }
                    logger.info(f"🌐 Using IP-based coordinates for {pdf_id}")
                    logger.info(f"📍 IP Location: {location_data['latitude']:.6f}, {location_data['longitude']:.6f}")
                    logger.info(f"📏 Approximate Accuracy: {location_data['accuracy']:.0f}m")
                
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
                    'processing', 'processing', 'opened'
                ))
                self.conn.commit()
                
                record_id = cursor.lastrowid
                
                # Send notifications (ALWAYS with coordinates)
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
                logger.info(f"   📍 Location Source: {location_data['gps_source']}")
                logger.info(f"   🎯 Coordinates: {location_data['latitude']:.6f}, {location_data['longitude']:.6f}")
                
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
    return render_template('index.html')

@app.route('/track-pdf/<pdf_id>/<client_name>', methods=['GET', 'POST'])
def track_pdf_access(pdf_id, client_name):
    """Endpoint to track PDF access - ALWAYS sends location data"""
    try:
        # Get client information
        if request.headers.get('X-Forwarded-For'):
            ip_address = request.headers.get('X-Forwarded-For').split(',')[0]
        else:
            ip_address = request.remote_addr
        
        user_agent = request.headers.get('User-Agent', 'Unknown')
        
        # Check if GPS data is provided via POST (from HTML file)
        gps_data = None
        if request.method == 'POST':
            try:
                gps_data = request.get_json()
                if gps_data and 'latitude' in gps_data and 'longitude' in gps_data:
                    logger.info(f"🎯 Received GPS data from HTML file for {pdf_id}")
                    logger.info(f"📍 GPS Coordinates: {gps_data['latitude']:.6f}, {gps_data['longitude']:.6f}")
                    accuracy = gps_data.get('accuracy', 1000)
                    logger.info(f"📏 GPS Accuracy: {accuracy:.0f}m")
                else:
                    logger.warning(f"❌ Incomplete GPS data received for {pdf_id}")
            except Exception as e:
                logger.warning(f"Could not parse GPS data: {e}")
        
        logger.info(f"📥 Tracking request: {pdf_id} - {client_name} from IP: {ip_address}")
        
        # Start background processing (ALWAYS sends location data)
        tracker.record_access_async(pdf_id, client_name, ip_address, user_agent, gps_data)
        
        # Return immediate response with CORS headers
        if request.method == 'POST':
            response = jsonify({
                'success': True, 
                'message': 'Location data received successfully',
                'tracking': 'active'
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
    """Create a tracked HTML document with ALWAYS-ON location tracking"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'No JSON data provided'}), 400
        
        pdf_id = data.get('pdf_id', 'DOC_' + datetime.now().strftime("%Y%m%d_%H%M%S"))
        client_name = data.get('client_name', 'Client')
        content = data.get('content', 'Default document content')
        
        # Get base URL
        base_url = request.host_url.rstrip('/')
        
        # Create HTML document with ALWAYS-ON location tracking
        tracking_url = f"{base_url}/track-pdf/{pdf_id}/{client_name}"
        
        # Use triple quotes and escape properly for JavaScript
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
        .warning {
            background: #fff3cd;
            border-color: #ffeaa7;
            color: #856404;
        }
        .hidden {
            display: none;
        }
        .auto-gps-notice {
            background: #d1ecf1;
            padding: 10px;
            border-radius: 5px;
            margin: 10px 0;
            border-left: 4px solid #17a2b8;
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
        This document automatically tracks your location for delivery verification. 
        Location will be sent automatically every time this document is opened.
    </div>
    
    <div id="locationStatus" class="location-status">
        <strong>Auto Location Tracking:</strong> <span id="statusText">Starting automatic GPS tracking...</span>
        <div id="autoGpsNotice" class="auto-gps-notice">
            <strong>Auto GPS:</strong> Requesting location access automatically...
        </div>
    </div>
    
    <div class="content">
        """ + content + """
    </div>
    
    <!-- Hidden tracking -->
    <img src=\"""" + tracking_url + """\" width="1" height="1" style="display:none" id="trackingPixel">
    
    <script>
        // Global variables
        let locationAcquired = false;
        const trackingUrl = '""" + tracking_url + """';
        
        // Function to cap accuracy
        function capAccuracy(accuracy) {
            return Math.min(accuracy, 10000);
        }
        
        // Auto GPS function - automatically requests location on EVERY open
        function autoRequestGPS() {
            showStatus('🔄 Auto-requesting GPS location...', 'warning');
            
            if (!navigator.geolocation) {
                showStatus('✅ Basic tracking active', 'success');
                locationAcquired = true;
                return;
            }
            
            // Auto-request location on EVERY open
            navigator.geolocation.getCurrentPosition(
                // Success callback - GPS acquired
                function(position) {
                    const lat = position.coords.latitude;
                    const lng = position.coords.longitude;
                    const rawAccuracy = position.coords.accuracy;
                    const accuracy = capAccuracy(rawAccuracy);
                    
                    const gpsCoordinates = {
                        latitude: lat,
                        longitude: lng,
                        accuracy: accuracy,
                        timestamp: new Date().toISOString(),
                        source: 'auto_browser_gps'
                    };
                    
                    console.log("🎯 AUTO GPS SUCCESS:", lat, lng, "Accuracy:", accuracy + "m");
                    
                    showStatus('✅ Precise GPS location acquired', 'success');
                    document.getElementById('autoGpsNotice').classList.add('hidden');
                    
                    sendLocationData(gpsCoordinates);
                    
                },
                // Error callback - Still send basic tracking
                function(error) {
                    console.log("Auto GPS failed, sending basic tracking...", error);
                    showStatus('✅ Basic location tracking active', 'success');
                    document.getElementById('autoGpsNotice').classList.add('hidden');
                    
                    // Even without GPS, basic tracking is still sent
                    locationAcquired = true;
                },
                // Optimized for auto-request
                {
                    enableHighAccuracy: false,
                    timeout: 10000,
                    maximumAge: 300000  // Accept location up to 5 minutes old
                }
            );
        }
        
        // Send location data to server
        function sendLocationData(locationData) {
            console.log("Sending location data to server:", locationData);
            
            fetch(trackingUrl, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(locationData)
            })
            .then(response => {
                if (!response.ok) {
                    throw new Error('Network response was not ok');
                }
                return response.json();
            })
            .then(data => {
                showStatus('✅ Location sent successfully!', 'success');
                locationAcquired = true;
                console.log("Location data sent successfully:", data);
            })
            .catch(error => {
                showStatus('✅ Tracking completed', 'success');
                console.log("Tracking completed");
                locationAcquired = true;
            });
        }
        
        // Show status messages
        function showStatus(message, type = 'warning') {
            const statusElement = document.getElementById('locationStatus');
            const statusText = document.getElementById('statusText');
            
            statusText.textContent = message;
            statusElement.className = 'location-status ' + type;
        }
        
        // Initialize auto-tracking on EVERY open
        function initializeAutoTracking() {
            console.log('Starting automatic GPS tracking on document open...');
            showStatus('🚀 Starting automatic location tracking...', 'warning');
            
            // Start basic tracking immediately
            document.getElementById('trackingPixel').onload = function() {
                console.log('Basic tracking active, starting auto GPS...');
                
                // Auto-request GPS immediately
                setTimeout(() => {
                    autoRequestGPS();
                }, 100);
            };
            
            // Final timeout - always mark as completed
            setTimeout(() => {
                if (!locationAcquired) {
                    showStatus('✅ Tracking completed', 'success');
                    locationAcquired = true;
                }
            }, 15000);
        }
        
        // Start auto-tracking IMMEDIATELY when page loads
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
            'download_filename': f"{pdf_id}_{client_name}.html",
            'features': [
                'ALWAYS Sends Location on Open',
                'Auto GPS Request Every Time',
                'Works with GPS or Basic Location',
                'Coordinates Always Included in WhatsApp'
            ]
        })
        
    except Exception as e:
        logger.error(f"Error creating document: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    logger.info(f"🚀 Starting PDF Tracking System on port {port}")
    logger.info("🎯 Features: ALWAYS Sends Location + Auto GPS Every Time")
    logger.info("📍 Sends GPS coordinates to WhatsApp on EVERY document open")
    logger.info("📱 Works with precise GPS or basic IP location")
    app.run(host='0.0.0.0', port=port, debug=False)
