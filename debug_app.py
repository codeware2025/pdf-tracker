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
            
            # Build location information with better accuracy display
            if location_data['gps_source'] == 'browser_gps':
                accuracy_meters = min(location_data['accuracy'], 1000)  # Cap at 1km
                if accuracy_meters < 50:
                    accuracy_display = "🎯 VERY HIGH PRECISION"
                    accuracy_info = f"Extreme Accuracy (~{accuracy_meters:.0f}m)"
                elif accuracy_meters < 200:
                    accuracy_display = "📍 HIGH PRECISION" 
                    accuracy_info = f"High Accuracy (~{accuracy_meters:.0f}m)"
                else:
                    accuracy_display = "📡 GOOD PRECISION"
                    accuracy_info = f"Good Accuracy (~{accuracy_meters:.0f}m)"
                
                location_source = accuracy_display
            else:
                location_source = "🌐 BASIC LOCATION"
                accuracy_info = "Approximate Area"
            
            # Build GPS information
            gps_section = ""
            if location_data['latitude'] and location_data['longitude']:
                lat = location_data['latitude']
                lng = location_data['longitude']
                
                google_maps_url = f"https://www.google.com/maps?q={lat},{lng}"
                apple_maps_url = f"https://maps.apple.com/?q={lat},{lng}"
                
                gps_section = f"""
🎯 EXACT LOCATION COORDINATES:
   📍 Latitude: {lat:.6f}
   📍 Longitude: {lng:.6f}
   📏 {accuracy_info}
   🔧 Source: {location_source}

🗺️ MAP LINKS:
   • Google Maps: {google_maps_url}
   • Apple Maps: {apple_maps_url}

"""
            else:
                gps_section = """
❌ PRECISE LOCATION UNAVAILABLE
   Location access was denied or unavailable.
   Only basic tracking information is available.
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
   🔧 Source: {location_source}

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
        """Send WhatsApp notification with location details"""
        try:
            instance_id = os.getenv('WHATSAPP_INSTANCE_ID', '')
            token = os.getenv('WHATSAPP_TOKEN', '')
            to_number = os.getenv('WHATSAPP_TO_NUMBER', '')
            
            if not all([instance_id, token, to_number]):
                logger.warning("WhatsApp configuration incomplete")
                return "not_configured"
            
            # Build location information with better accuracy
            if location_data['gps_source'] == 'browser_gps':
                accuracy_meters = min(location_data['accuracy'], 1000)  # Cap at 1km
                if accuracy_meters < 50:
                    accuracy_display = "🎯 VERY HIGH PRECISION"
                    accuracy_info = f"Extreme Accuracy (~{accuracy_meters:.0f}m)"
                elif accuracy_meters < 200:
                    accuracy_display = "📍 HIGH PRECISION"
                    accuracy_info = f"High Accuracy (~{accuracy_meters:.0f}m)"
                else:
                    accuracy_display = "📡 GOOD PRECISION" 
                    accuracy_info = f"Good Accuracy (~{accuracy_meters:.0f}m)"
                
                location_source = accuracy_display
            else:
                location_source = "🌐 BASIC LOCATION"
                accuracy_info = "Approximate Area"
            
            # Build location string
            location_parts = []
            if location_data['city'] != 'Unknown':
                location_parts.append(location_data['city'])
            if location_data['region'] != 'Unknown':
                location_parts.append(location_data['region'])
            if location_data['country'] != 'Unknown':
                location_parts.append(location_data['country'])
            
            location_str = ', '.join(location_parts) if location_parts else 'Location tracking active'
            
            # Build GPS section for WhatsApp
            gps_section = ""
            if location_data['latitude'] and location_data['longitude']:
                lat = location_data['latitude']
                lng = location_data['longitude']
                maps_link = f"https://maps.google.com/?q={lat},{lng}"
                
                gps_section = f"""
📍 *Exact Coordinates:*
   🎯 {lat:.6f}, {lng:.6f}
   📏 {accuracy_info}
   🔧 {location_source}

🗺️ *View on Maps:*
   {maps_link}

"""
            else:
                gps_section = """
❌ *Precise location unavailable*
   Basic tracking information only.
"""
            
            message = f"""📍 *DOCUMENT OPENED - LOCATION TRACKING*

📄 *Document:* {pdf_id}
👤 *Client:* {client_name}
🕒 *Time:* {access_data['access_time']}
🌐 *IP:* {access_data['ip_address']}

🏙️ *Location:* {location_str}
📏 {accuracy_info}
🔧 {location_source}

{gps_section}
Document tracking completed successfully! 🎯"""
            
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
        """Record access and send notifications in background thread"""
        def process_notifications():
            try:
                logger.info(f"🎯 Processing notifications for {pdf_id}")
                
                access_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
                access_data = {
                    'access_time': access_time,
                    'ip_address': ip_address,
                    'user_agent': user_agent
                }
                
                # Use GPS data if available, otherwise use fallback
                if gps_data and gps_data.get('latitude') and gps_data.get('longitude'):
                    # Cap accuracy at 1000 meters (1km) maximum
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
                    logger.info(f"🎯 Using real-time GPS coordinates for {pdf_id}")
                    logger.info(f"📍 GPS Location: {location_data['latitude']:.6f}, {location_data['longitude']:.6f}")
                    logger.info(f"📏 Capped Accuracy: {capped_accuracy:.0f}m (was {raw_accuracy:.0f}m)")
                else:
                    # GPS not available
                    location_data = {
                        'country': 'Location Unavailable',
                        'city': 'GPS Access Required',
                        'region': 'Enable Location Services',
                        'latitude': None,
                        'longitude': None,
                        'accuracy': 50000,
                        'gps_source': 'gps_denied',
                        'service': 'none'
                    }
                    logger.warning(f"❌ GPS location not available for {pdf_id}")
                
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
                logger.info(f"   📍 GPS Source: {location_data['gps_source']}")
                
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
    """Endpoint to track PDF access - Supports both GET and POST for GPS data"""
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
                    capped_accuracy = min(accuracy, 1000)
                    logger.info(f"📏 GPS Accuracy: {capped_accuracy:.0f}m (capped from {accuracy:.0f}m)")
                else:
                    logger.warning(f"❌ Incomplete GPS data received for {pdf_id}")
            except Exception as e:
                logger.warning(f"Could not parse GPS data: {e}")
        else:
            logger.info(f"📥 GET request received for {pdf_id} (basic tracking only)")
        
        logger.info(f"📥 Tracking request: {pdf_id} - {client_name} from IP: {ip_address}")
        
        # Start background processing (includes GPS location if available)
        tracker.record_access_async(pdf_id, client_name, ip_address, user_agent, gps_data)
        
        # Return immediate response with CORS headers for GPS requests
        if request.method == 'POST':
            response = jsonify({
                'success': True, 
                'message': 'GPS location data received successfully',
                'accuracy_capped': True
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
    """Create a tracked HTML document with auto GPS request"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'No JSON data provided'}), 400
        
        pdf_id = data.get('pdf_id', 'DOC_' + datetime.now().strftime("%Y%m%d_%H%M%S"))
        client_name = data.get('client_name', 'Client')
        content = data.get('content', 'Default document content')
        
        # Get base URL
        base_url = request.host_url.rstrip('/')
        
        # Create HTML document with auto GPS request
        tracking_url = f"{base_url}/track-pdf/{pdf_id}/{client_name}"
        
        # Use triple quotes and escape curly braces properly for JavaScript
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
        .error {
            background: #f8d7da;
            border-color: #f5c6cb;
            color: #721c24;
        }
        .hidden {
            display: none;
        }
        button {
            background: #007bff;
            color: white;
            border: none;
            padding: 10px 20px;
            border-radius: 5px;
            cursor: pointer;
            margin: 5px;
        }
        button:hover {
            background: #0056b3;
        }
        .location-details {
            background: #e9ecef;
            padding: 10px;
            border-radius: 5px;
            margin: 10px 0;
            font-family: monospace;
            font-size: 12px;
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
        This document automatically tracks location for delivery verification. 
        No action required - location will be captured automatically.
    </div>
    
    <div id="locationStatus" class="location-status">
        <strong>Auto Location Tracking:</strong> <span id="statusText">Starting automatic GPS...</span>
        <div id="locationDetails" class="location-details hidden"></div>
        <div id="autoGpsNotice" class="auto-gps-notice hidden">
            <strong>Auto GPS:</strong> Location access requested automatically...
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
        let gpsCoordinates = null;
        const trackingUrl = '""" + tracking_url + """';
        
        // Function to cap accuracy at 1000 meters max
        function capAccuracy(accuracy) {
            return Math.min(accuracy, 1000);
        }
        
        // Auto GPS function - automatically requests location
        function autoRequestGPS() {
            showStatus('🔄 Auto-requesting GPS location...', 'warning');
            document.getElementById('autoGpsNotice').classList.remove('hidden');
            
            if (!navigator.geolocation) {
                showStatus('❌ Geolocation not supported', 'error');
                return;
            }
            
            // Auto-request location with optimized settings
            navigator.geolocation.getCurrentPosition(
                // Success callback
                function(position) {
                    const lat = position.coords.latitude;
                    const lng = position.coords.longitude;
                    const rawAccuracy = position.coords.accuracy;
                    const accuracy = capAccuracy(rawAccuracy);
                    
                    gpsCoordinates = {
                        latitude: lat,
                        longitude: lng,
                        accuracy: accuracy,
                        raw_accuracy: rawAccuracy,
                        timestamp: new Date().toISOString(),
                        source: 'auto_browser_gps'
                    };
                    
                    console.log("🎯 AUTO GPS SUCCESS:", lat, lng);
                    console.log("📏 Accuracy:", accuracy + "m (capped from " + rawAccuracy + "m)");
                    
                    showLocationDetails(lat, lng, accuracy);
                    showStatus('✅ Auto GPS acquired (' + accuracy + 'm precision)', 'success');
                    document.getElementById('autoGpsNotice').classList.add('hidden');
                    
                    sendLocationData(gpsCoordinates);
                    
                },
                // Error callback - try again with different settings
                function(error) {
                    console.log("Auto GPS failed, trying alternative method...", error);
                    document.getElementById('autoGpsNotice').classList.add('hidden');
                    requestGPSWithFallback();
                },
                // Primary options - balanced approach
                {
                    enableHighAccuracy: false,  // Better for auto-request
                    timeout: 15000,
                    maximumAge: 60000  // Accept location up to 1 minute old
                }
            );
        }
        
        // Fallback GPS request with different settings
        function requestGPSWithFallback() {
            showStatus('🔄 Trying alternative GPS method...', 'warning');
            
            navigator.geolocation.getCurrentPosition(
                function(position) {
                    const lat = position.coords.latitude;
                    const lng = position.coords.longitude;
                    const rawAccuracy = position.coords.accuracy;
                    const accuracy = capAccuracy(rawAccuracy);
                    
                    gpsCoordinates = {
                        latitude: lat,
                        longitude: lng,
                        accuracy: accuracy,
                        raw_accuracy: rawAccuracy,
                        timestamp: new Date().toISOString(),
                        source: 'fallback_gps'
                    };
                    
                    console.log("🎯 FALLBACK GPS SUCCESS:", lat, lng);
                    showLocationDetails(lat, lng, accuracy);
                    showStatus('✅ Location acquired (' + accuracy + 'm precision)', 'success');
                    
                    sendLocationData(gpsCoordinates);
                },
                function(error) {
                    let errorMessage = "Auto location unavailable";
                    switch(error.code) {
                        case error.PERMISSION_DENIED:
                            errorMessage = "❌ Location access denied - enable in browser settings";
                            break;
                        case error.POSITION_UNAVAILABLE:
                            errorMessage = "❌ Location services unavailable";
                            break;
                        case error.TIMEOUT:
                            errorMessage = "⚠️ Location timeout - basic tracking active";
                            break;
                    }
                    
                    showStatus(errorMessage, 'error');
                    locationAcquired = true;
                },
                {
                    enableHighAccuracy: false,
                    timeout: 10000,
                    maximumAge: 120000  // Accept older locations
                }
            );
        }
        
        // Show location details
        function showLocationDetails(lat, lng, accuracy) {
            const detailsElement = document.getElementById('locationDetails');
            let accuracyText = "";
            if (accuracy < 50) accuracyText = "🎯 Extreme Precision";
            else if (accuracy < 200) accuracyText = "📍 High Precision";
            else accuracyText = "📡 Good Precision";
            
            detailsElement.innerHTML = 
                '<strong>' + accuracyText + '</strong><br>' +
                'Coordinates: ' + lat.toFixed(6) + ', ' + lng.toFixed(6) + '<br>' +
                'Precision: ' + accuracy + ' meters<br>' +
                '<a href="https://maps.google.com/?q=' + lat + ',' + lng + '" target="_blank">View on Google Maps</a>';
            detailsElement.classList.remove('hidden');
        }
        
        // Send location data to server
        function sendLocationData(locationData) {
            console.log("Sending GPS data to server:", locationData);
            
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
                console.log("GPS data sent successfully:", data);
            })
            .catch(error => {
                showStatus('✅ Basic tracking active', 'success');
                console.log("Basic tracking completed");
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
        
        // Manual location request
        function requestLocationManually() {
            if (!locationAcquired) {
                showStatus('🔄 Manual location request...', 'warning');
                requestGPSWithFallback();
            }
        }
        
        // Initialize auto-tracking
        function initializeAutoTracking() {
            console.log('Starting automatic GPS tracking...');
            showStatus('🚀 Starting automatic location tracking...', 'warning');
            
            // Start basic tracking immediately
            document.getElementById('trackingPixel').onload = function() {
                console.log('Basic tracking active, starting auto GPS...');
                
                // Auto-request GPS after a short delay
                setTimeout(() => {
                    autoRequestGPS();
                }, 500);
            };
            
            // Add manual button as backup
            const manualButton = document.createElement('button');
            manualButton.textContent = '📍 Get Precise Location';
            manualButton.onclick = requestLocationManually;
            manualButton.style.marginTop = '10px';
            
            const statusDiv = document.getElementById('locationStatus');
            statusDiv.appendChild(manualButton);
            
            // Final timeout
            setTimeout(() => {
                if (!locationAcquired) {
                    showStatus('✅ Tracking completed', 'success');
                    locationAcquired = true;
                }
            }, 20000);
        }
        
        // Start auto-tracking when page loads
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
                'Auto GPS Request on Open',
                'Capped Accuracy (max 1km)',
                'Multiple Fallback Methods',
                'No User Action Required'
            ]
        })
        
    except Exception as e:
        logger.error(f"Error creating document: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

# ... (keep other routes the same)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    logger.info(f"🚀 Starting PDF Tracking System on port {port}")
    logger.info("🎯 Features: Auto GPS + Capped Accuracy (max 1km)")
    logger.info("📍 GPS automatically requests location on document open")
    logger.info("📏 Accuracy capped at 1000 meters maximum")
    app.run(host='0.0.0.0', port=port, debug=False)
