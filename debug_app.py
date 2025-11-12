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
    
    def get_accurate_location(self, ip_address):
        """Get GPS location using multiple geolocation APIs with better services"""
        location_data = {
            'ip': ip_address,
            'country': 'Unknown',
            'city': 'Unknown',
            'region': 'Unknown',
            'latitude': None,
            'longitude': None,
            'accuracy': 50000,  # Very low accuracy for IP-based
            'gps_source': 'ip_geolocation',
            'service': 'none'
        }
        
        # Skip local IPs
        if ip_address in ['127.0.0.1', 'localhost'] or ip_address.startswith(('192.168.', '10.', '172.', '0.')):
            location_data.update({
                'country': 'Local Network',
                'city': 'Internal',
                'accuracy': 100000
            })
            return location_data
        
        # Try multiple better geolocation services
        services = [
            self._try_ipapi(ip_address),
            self._try_ip2location(ip_address),
            self._try_abstractapi(ip_address),
            self._try_ipgeolocation(ip_address),
            self._try_ipinfo(ip_address)
        ]
        
        # Use the best available result
        best_result = None
        for result in services:
            if result and result.get('latitude') and result.get('longitude'):
                if not best_result or (result.get('accuracy', 1000) < best_result.get('accuracy', 1000)):
                    best_result = result
        
        if best_result:
            location_data.update(best_result)
            logger.info(f"📍 Better location found for {ip_address}: {location_data['city']}, {location_data['country']}")
        else:
            logger.warning(f"🌐 No accurate location found for {ip_address}, using fallback")
        
        return location_data
    
    def _try_ipapi(self, ip_address):
        """Try ipapi.co with better error handling"""
        try:
            response = requests.get(f'https://ipapi.co/{ip_address}/json/', timeout=5)
            if response.status_code == 200:
                data = response.json()
                if data.get('error'):
                    return None
                return {
                    'country': data.get('country_name', 'Unknown'),
                    'city': data.get('city', 'Unknown'),
                    'region': data.get('region', 'Unknown'),
                    'latitude': float(data.get('latitude', 0)) or None,
                    'longitude': float(data.get('longitude', 0)) or None,
                    'accuracy': 5000,  # Medium accuracy for IP
                    'service': 'ipapi'
                }
        except Exception as e:
            logger.debug(f"ipapi.co failed: {e}")
        return None
    
    def _try_ip2location(self, ip_address):
        """Try ip2location.io (more accurate)"""
        try:
            # You can get a free API key from ip2location.io
            api_key = os.getenv('IP2LOCATION_API_KEY', '')
            if api_key:
                response = requests.get(f'https://api.ip2location.io/?key={api_key}&ip={ip_address}', timeout=5)
            else:
                response = requests.get(f'https://api.ip2location.io/?ip={ip_address}', timeout=5)
                
            if response.status_code == 200:
                data = response.json()
                return {
                    'country': data.get('country_name', 'Unknown'),
                    'city': data.get('city_name', 'Unknown'),
                    'region': data.get('region_name', 'Unknown'),
                    'latitude': float(data.get('latitude', 0)) or None,
                    'longitude': float(data.get('longitude', 0)) or None,
                    'accuracy': 3000,
                    'service': 'ip2location'
                }
        except Exception as e:
            logger.debug(f"ip2location failed: {e}")
        return None
    
    def _try_abstractapi(self, ip_address):
        """Try abstractapi.com (very accurate)"""
        try:
            api_key = os.getenv('ABSTRACT_API_KEY', '')
            if api_key:
                response = requests.get(f'https://ipgeolocation.abstractapi.com/v1/?api_key={api_key}&ip_address={ip_address}', timeout=5)
                if response.status_code == 200:
                    data = response.json()
                    return {
                        'country': data.get('country', 'Unknown'),
                        'city': data.get('city', 'Unknown'),
                        'region': data.get('region', 'Unknown'),
                        'latitude': float(data.get('latitude', 0)) or None,
                        'longitude': float(data.get('longitude', 0)) or None,
                        'accuracy': 2000,
                        'service': 'abstractapi'
                    }
        except Exception as e:
            logger.debug(f"abstractapi failed: {e}")
        return None
    
    def _try_ipgeolocation(self, ip_address):
        """Try ipgeolocation.io"""
        try:
            api_key = os.getenv('IPGEOLOCATION_API_KEY', '')
            if api_key:
                response = requests.get(f'https://api.ipgeolocation.io/ipgeo?apiKey={api_key}&ip={ip_address}', timeout=5)
                if response.status_code == 200:
                    data = response.json()
                    return {
                        'country': data.get('country_name', 'Unknown'),
                        'city': data.get('city', 'Unknown'),
                        'region': data.get('state_prov', 'Unknown'),
                        'latitude': float(data.get('latitude', 0)) or None,
                        'longitude': float(data.get('longitude', 0)) or None,
                        'accuracy': 4000,
                        'service': 'ipgeolocation'
                    }
        except Exception as e:
            logger.debug(f"ipgeolocation failed: {e}")
        return None
    
    def _try_ipinfo(self, ip_address):
        """Try ipinfo.io as fallback"""
        try:
            response = requests.get(f'https://ipinfo.io/{ip_address}/json', timeout=5)
            if response.status_code == 200:
                data = response.json()
                loc = data.get('loc', '').split(',')
                latitude = float(loc[0]) if loc and loc[0] else None
                longitude = float(loc[1]) if len(loc) > 1 and loc[1] else None
                
                return {
                    'country': data.get('country', 'Unknown'),
                    'city': data.get('city', 'Unknown'),
                    'region': data.get('region', 'Unknown'),
                    'latitude': latitude,
                    'longitude': longitude,
                    'accuracy': 10000,
                    'service': 'ipinfo'
                }
        except Exception as e:
            logger.debug(f"ipinfo.io failed: {e}")
        return None

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
                location_source = "🎯 REAL-TIME GPS LOCATION"
                accuracy_info = f"High Accuracy (~{location_data['accuracy']:.0f}m)"
            else:
                location_source = "🌐 IP GEOLOCATION (APPROXIMATE)"
                accuracy_info = f"Low Accuracy (~{location_data['accuracy']/1000:.1f}km)"
            
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
                gps_section = """
❌ PRECISE LOCATION UNAVAILABLE
   Location could not be determined accurately.
   Client may have denied location access or is using VPN.
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
        """Send WhatsApp notification with improved location accuracy"""
        try:
            instance_id = os.getenv('WHATSAPP_INSTANCE_ID', '')
            token = os.getenv('WHATSAPP_TOKEN', '')
            to_number = os.getenv('WHATSAPP_TO_NUMBER', '')
            
            if not all([instance_id, token, to_number]):
                logger.warning("WhatsApp configuration incomplete")
                return "not_configured"
            
            # Build location information
            if location_data['gps_source'] == 'browser_gps':
                location_source = "🎯 REAL-TIME GPS"
                accuracy_info = f"High Accuracy (~{location_data['accuracy']:.0f}m)"
            else:
                location_source = "🌐 IP GEOLOCATION"
                accuracy_info = f"Low Accuracy (~{location_data['accuracy']/1000:.1f}km)"
            
            # Build location string
            location_parts = []
            if location_data['city'] != 'Unknown':
                location_parts.append(location_data['city'])
            if location_data['region'] != 'Unknown':
                location_parts.append(location_data['region'])
            if location_data['country'] != 'Unknown':
                location_parts.append(location_data['country'])
            
            location_str = ', '.join(location_parts) if location_parts else 'Location unavailable'
            
            # Build GPS section for WhatsApp
            gps_section = ""
            if location_data['latitude'] and location_data['longitude']:
                lat = location_data['latitude']
                lng = location_data['longitude']
                maps_link = f"https://maps.google.com/?q={lat},{lng}"
                
                gps_section = f"""
📍 *Coordinates:*
   🎯 {lat:.6f}, {lng:.6f}
   📏 {accuracy_info}
   🔧 {location_source}

🗺️ *View on Maps:*
   {maps_link}

"""
            else:
                gps_section = """
❌ *Precise location unavailable*
   Client may have denied location access.
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
Document tracking completed! 🎯"""
            
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
                
                # Get IP-based location as fallback
                ip_location_data = self.get_accurate_location(ip_address)
                access_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
                access_data = {
                    'access_time': access_time,
                    'ip_address': ip_address,
                    'user_agent': user_agent
                }
                
                # Use GPS data if available, otherwise use IP location
                if gps_data and gps_data.get('latitude') and gps_data.get('longitude'):
                    location_data = {
                        'country': gps_data.get('country', ip_location_data['country']),
                        'city': gps_data.get('city', ip_location_data['city']),
                        'region': gps_data.get('region', ip_location_data['region']),
                        'latitude': gps_data['latitude'],
                        'longitude': gps_data['longitude'],
                        'accuracy': gps_data.get('accuracy', 50),
                        'gps_source': 'browser_gps',
                        'service': 'browser_geolocation'
                    }
                    logger.info(f"🎯 Using real-time GPS coordinates for {pdf_id}")
                else:
                    location_data = ip_location_data
                    logger.info(f"🌐 Using IP-based location for {pdf_id}")
                    logger.info(f"📍 IP Location: {location_data['city']}, {location_data['country']}")
                
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
                logger.info(f"   📍 Location: {location_data['city']}, {location_data['country']}")
                logger.info(f"   🎯 GPS Source: {location_data['gps_source']}")
                logger.info(f"   📏 Accuracy: {location_data['accuracy']:.0f}m")
                
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
                    logger.info(f"🎯 Received GPS data from HTML file for {pdf_id}: {gps_data['latitude']:.6f}, {gps_data['longitude']:.6f}")
            except Exception as e:
                logger.warning(f"Could not parse GPS data: {e}")
        
        logger.info(f"📥 Tracking request: {pdf_id} - {client_name} from IP: {ip_address}")
        
        # Start background processing (includes GPS location if available)
        tracker.record_access_async(pdf_id, client_name, ip_address, user_agent, gps_data)
        
        # Return immediate response
        if request.method == 'POST':
            return jsonify({'success': True, 'message': 'Location data received successfully'})
        else:
            pixel = base64.b64decode('R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7')
            response = Response(pixel, mimetype='image/gif')
            response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
            response.headers['Pragma'] = 'no-cache'
            response.headers['Expires'] = '0'
            return response
            
    except Exception as e:
        logger.error(f"Tracking error: {str(e)}")
        return "Server Error", 500

# ... (keep create-document, test-email, test-whatsapp, analytics, config-status routes the same)

@app.route('/create-document', methods=['POST'])
def create_document():
    """Create a tracked HTML document with improved GPS tracking"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'No JSON data provided'}), 400
        
        pdf_id = data.get('pdf_id', 'DOC_' + datetime.now().strftime("%Y%m%d_%H%M%S"))
        client_name = data.get('client_name', 'Client')
        content = data.get('content', 'Default document content')
        
        # Get base URL
        base_url = request.host_url.rstrip('/')
        
        # Create HTML document with improved GPS tracking
        tracking_url = f"{base_url}/track-pdf/{pdf_id}/{client_name}"
        
        html_content = f"""<!DOCTYPE html>
<html>
<head>
    <title>Document: {pdf_id}</title>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body {{
            font-family: Arial, sans-serif;
            max-width: 100vw;
            margin: 0 auto;
            padding: 20px;
            background: white;
            line-height: 1.4;
        }}
        .header {{
            text-align: center;
            border-bottom: 2px solid #333;
            padding-bottom: 10px;
            margin-bottom: 20px;
        }}
        .content {{
            white-space: normal;
            margin-bottom: 30px;
        }}
        .tracking-notice {{
            background: #e8f4fd;
            padding: 15px;
            margin: 20px 0;
            border-radius: 8px;
            border-left: 4px solid #2196F3;
            font-size: 14px;
        }}
        .location-status {{
            background: #f8f9fa;
            padding: 15px;
            margin: 15px 0;
            border-radius: 8px;
            border: 1px solid #dee2e6;
            font-size: 13px;
        }}
        .success {{
            background: #d4edda;
            border-color: #c3e6cb;
            color: #155724;
        }}
        .warning {{
            background: #fff3cd;
            border-color: #ffeaa7;
            color: #856404;
        }}
        .hidden {{
            display: none;
        }}
        button {{
            background: #007bff;
            color: white;
            border: none;
            padding: 10px 20px;
            border-radius: 5px;
            cursor: pointer;
            margin: 5px;
        }}
        button:hover {{
            background: #0056b3;
        }}
        button:disabled {{
            background: #6c757d;
            cursor: not-allowed;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>COMPANY DOCUMENT</h1>
        <p>Document ID: {pdf_id} | Client: {client_name}</p>
    </div>
    
    <div class="tracking-notice">
        <strong>📍 Location Tracking Active</strong><br>
        This document includes location tracking for delivery verification. 
        For accurate location, please allow location access when prompted.
    </div>
    
    <div id="locationStatus" class="location-status hidden">
        <strong>Location Status:</strong> <span id="statusText">Initializing...</span>
    </div>
    
    <div class="content">
        {content}
    </div>
    
    <!-- Hidden tracking image for initial IP-based tracking -->
    <img src="{tracking_url}" width="1" height="1" style="display:none" id="trackingPixel">
    
    <script>
        // Global variables
        let locationAcquired = false;
        const trackingUrl = '{tracking_url}';
        
        // Improved function to get precise GPS coordinates
        function getPreciseLocation() {{
            showStatus('Requesting precise location access...', 'warning');
            
            if (!navigator.geolocation) {{
                showStatus('Geolocation not supported by this browser', 'warning');
                return;
            }}
            
            // Get high-accuracy location with better options
            navigator.geolocation.getCurrentPosition(
                function(position) {{
                    const lat = position.coords.latitude;
                    const lng = position.coords.longitude;
                    const accuracy = position.coords.accuracy;
                    
                    console.log("📍 Acquired High-Accuracy GPS:", lat, lng, "Accuracy:", accuracy + "m");
                    
                    showStatus(`🎯 Acquired precise location (Accuracy: ${{accuracy}}m) - Sending...`, 'warning');
                    
                    // Send precise GPS coordinates to server
                    sendLocationData({{
                        latitude: lat,
                        longitude: lng,
                        accuracy: accuracy,
                        timestamp: new Date().toISOString(),
                        source: 'browser_geolocation'
                    }});
                    
                }},
                function(error) {{
                    let errorMessage = "Location access unavailable";
                    switch(error.code) {{
                        case error.PERMISSION_DENIED:
                            errorMessage = "❌ Location access denied - using approximate IP location only";
                            break;
                        case error.POSITION_UNAVAILABLE:
                            errorMessage = "❌ Location information unavailable";
                            break;
                        case error.TIMEOUT:
                            errorMessage = "❌ Location request timed out";
                            break;
                    }}
                    
                    showStatus(errorMessage, 'warning');
                    console.log("Geolocation error:", errorMessage);
                    
                    // Mark as acquired even if GPS fails (we still have IP)
                    locationAcquired = true;
                }},
                {{
                    enableHighAccuracy: true,
                    timeout: 20000,  // 20 seconds timeout
                    maximumAge: 0    // No cached position
                }}
            );
        }}
        
        // Function to send location data to server
        function sendLocationData(locationData) {{
            fetch(trackingUrl, {{
                method: 'POST',
                headers: {{
                    'Content-Type': 'application/json',
                }},
                body: JSON.stringify(locationData)
            }})
            .then(response => response.json())
            .then(data => {{
                showStatus('✅ Precise location sent successfully! Tracking complete.', 'success');
                locationAcquired = true;
                console.log("High-accuracy location data sent successfully:", data);
            }})
            .catch(error => {{
                showStatus('⚠️ Location sent with limited accuracy', 'warning');
                console.error("Error sending location data:", error);
                locationAcquired = true;
            }});
        }}
        
        // Function to show status messages
        function showStatus(message, type = 'warning') {{
            const statusElement = document.getElementById('locationStatus');
            const statusText = document.getElementById('statusText');
            
            statusText.textContent = message;
            statusElement.className = 'location-status ' + type;
            statusElement.classList.remove('hidden');
        }}
        
        // Function to manually trigger location access
        function requestLocationManually() {{
            if (!locationAcquired) {{
                getPreciseLocation();
            }} else {{
                showStatus('Location already acquired', 'success');
            }}
        }}
        
        // Initialize tracking when page loads
        window.addEventListener('load', function() {{
            console.log('Document loaded, starting enhanced tracking process...');
            
            // Show initial status
            showStatus('Document loaded - starting enhanced location tracking...', 'warning');
            
            // First, the tracking pixel will load (IP-based tracking)
            // Then attempt to get precise GPS location with delay
            setTimeout(() => {{
                console.log('Attempting to get high-accuracy GPS location...');
                getPreciseLocation();
            }}, 1500);
            
            // Final fallback
            setTimeout(() => {{
                if (!locationAcquired) {{
                    showStatus('Tracking completed with available location data', 'success');
                    locationAcquired = true;
                }}
            }}, 25000);
        }});
        
        // Add manual location request button for user control
        document.addEventListener('DOMContentLoaded', function() {{
            const manualButton = document.createElement('button');
            manualButton.textContent = '📡 Get Precise Location';
            manualButton.onclick = requestLocationManually;
            manualButton.style.marginTop = '10px';
            
            const statusDiv = document.getElementById('locationStatus');
            statusDiv.parentNode.insertBefore(manualButton, statusDiv.nextSibling);
        }});
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
            'instructions': 'Send this HTML file to clients. When they open it, you will receive their precise location via email and WhatsApp.'
        })
        
    except Exception as e:
        logger.error(f"Error creating document: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

# ... (keep other routes the same)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    logger.info(f"🚀 Starting PDF Tracking System on port {port}")
    logger.info("🎯 Features: Improved Location Accuracy + Better GPS Tracking")
    logger.info("🔧 For better accuracy, consider adding API keys for:")
    logger.info("   - IP2Location: https://www.ip2location.io/")
    logger.info("   - AbstractAPI: https://www.abstractapi.com/")
    logger.info("   - IPGeolocation: https://ipgeolocation.io/")
    app.run(host='0.0.0.0', port=port, debug=False)
