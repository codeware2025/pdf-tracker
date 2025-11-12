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
        """Send WhatsApp notification with location details"""
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
                
                access_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
                access_data = {
                    'access_time': access_time,
                    'ip_address': ip_address,
                    'user_agent': user_agent
                }
                
                # Use GPS data if available, otherwise use IP location (with fallback)
                if gps_data and gps_data.get('latitude') and gps_data.get('longitude'):
                    location_data = {
                        'country': gps_data.get('country', 'Unknown'),
                        'city': gps_data.get('city', 'Unknown'),
                        'region': gps_data.get('region', 'Unknown'),
                        'latitude': gps_data['latitude'],
                        'longitude': gps_data['longitude'],
                        'accuracy': gps_data.get('accuracy', 50),
                        'gps_source': 'browser_gps',
                        'service': 'browser_geolocation'
                    }
                    logger.info(f"🎯 Using real-time GPS coordinates for {pdf_id}")
                    logger.info(f"📍 GPS Location: {location_data['latitude']:.6f}, {location_data['longitude']:.6f}")
                else:
                    # Use a default location that indicates GPS wasn't available
                    location_data = {
                        'country': 'GPS Not Available',
                        'city': 'Location Access Denied',
                        'region': 'Use IP Geolocation',
                        'latitude': None,
                        'longitude': None,
                        'accuracy': 50000,
                        'gps_source': 'gps_denied',
                        'service': 'none'
                    }
                    logger.warning(f"❌ GPS location not available for {pdf_id}, using fallback")
                
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
                    logger.info(f"📏 GPS Accuracy: {gps_data.get('accuracy', 'Unknown')}m")
                else:
                    logger.warning(f"❌ Incomplete GPS data received for {pdf_id}")
            except Exception as e:
                logger.warning(f"Could not parse GPS data: {e}")
        else:
            logger.info(f"📥 GET request received for {pdf_id} (IP-based tracking only)")
        
        logger.info(f"📥 Tracking request: {pdf_id} - {client_name} from IP: {ip_address}")
        
        # Start background processing (includes GPS location if available)
        tracker.record_access_async(pdf_id, client_name, ip_address, user_agent, gps_data)
        
        # Return immediate response with CORS headers for GPS requests
        if request.method == 'POST':
            response = jsonify({'success': True, 'message': 'GPS location data received successfully'})
            response.headers.add('Access-Control-Allow-Origin', '*')
            return response
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
        .error {{
            background: #f8d7da;
            border-color: #f5c6cb;
            color: #721c24;
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
        .location-details {{
            background: #e9ecef;
            padding: 10px;
            border-radius: 5px;
            margin: 10px 0;
            font-family: monospace;
            font-size: 12px;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>COMPANY DOCUMENT</h1>
        <p>Document ID: {pdf_id} | Client: {client_name}</p>
    </div>
    
    <div class="tracking-notice">
        <strong>📍 PRECISE LOCATION TRACKING ACTIVE</strong><br>
        This document will request your <strong>exact GPS location</strong> for delivery verification. 
        Please <strong>allow location access</strong> when prompted by your browser for accurate tracking.
    </div>
    
    <div id="locationStatus" class="location-status hidden">
        <strong>Real-time Location Tracking:</strong> <span id="statusText">Initializing GPS...</span>
        <div id="locationDetails" class="location-details hidden"></div>
    </div>
    
    <div class="content">
        {content}
    </div>
    
    <!-- Hidden tracking image for basic tracking -->
    <img src="{tracking_url}" width="1" height="1" style="display:none" id="trackingPixel">
    
    <script>
        // Global variables
        let locationAcquired = false;
        let gpsCoordinates = null;
        const trackingUrl = '{tracking_url}';
        
        // Improved function to get precise GPS coordinates
        function getPreciseLocation() {{
            showStatus('🔍 Requesting precise GPS location access...', 'warning');
            
            if (!navigator.geolocation) {{
                showStatus('❌ Geolocation not supported by this browser', 'error');
                return;
            }}
            
            console.log("Starting high-accuracy GPS location request...");
            
            // Get high-accuracy location with better options
            navigator.geolocation.getCurrentPosition(
                // Success callback
                function(position) {{
                    const lat = position.coords.latitude;
                    const lng = position.coords.longitude;
                    const accuracy = position.coords.accuracy;
                    
                    gpsCoordinates = {{
                        latitude: lat,
                        longitude: lng,
                        accuracy: accuracy,
                        timestamp: new Date().toISOString(),
                        source: 'browser_geolocation'
                    }};
                    
                    console.log("🎯 SUCCESS: Acquired High-Accuracy GPS:", lat, lng, "Accuracy:", accuracy + "m");
                    
                    // Show location details to user
                    showLocationDetails(lat, lng, accuracy);
                    showStatus(`✅ Acquired precise GPS location (Accuracy: ${{accuracy}}m)`, 'success');
                    
                    // Send precise GPS coordinates to server
                    sendLocationData(gpsCoordinates);
                    
                }},
                // Error callback
                function(error) {{
                    let errorMessage = "Location access unavailable";
                    switch(error.code) {{
                        case error.PERMISSION_DENIED:
                            errorMessage = "❌ LOCATION ACCESS DENIED - You must allow location access for accurate tracking";
                            break;
                        case error.POSITION_UNAVAILABLE:
                            errorMessage = "❌ GPS location unavailable - Please check your device location services";
                            break;
                        case error.TIMEOUT:
                            errorMessage = "❌ GPS location request timed out - Please try again";
                            break;
                    }}
                    
                    showStatus(errorMessage, 'error');
                    console.error("Geolocation error:", errorMessage, error);
                    
                    // Mark as acquired even if GPS fails
                    locationAcquired = true;
                }},
                // Options - maximum accuracy
                {{
                    enableHighAccuracy: true,    // Force GPS usage
                    timeout: 30000,             // 30 seconds timeout
                    maximumAge: 0               // No cached position - always get fresh location
                }}
            );
        }}
        
        // Function to show location details
        function showLocationDetails(lat, lng, accuracy) {{
            const detailsElement = document.getElementById('locationDetails');
            detailsElement.innerHTML = `
                <strong>GPS Coordinates:</strong><br>
                Latitude: ${"${lat.toFixed(6)}"}<br>
                Longitude: ${"${lng.toFixed(6)}"}<br>
                Accuracy: ${"${accuracy}"} meters<br>
                <a href="https://maps.google.com/?q=${"${lat}"},${"${lng}"}" target="_blank">View on Google Maps</a>
            `;
            detailsElement.classList.remove('hidden');
        }}
        
        // Function to send location data to server
        function sendLocationData(locationData) {{
            console.log("Sending GPS data to server:", locationData);
            
            fetch(trackingUrl, {{
                method: 'POST',
                headers: {{
                    'Content-Type': 'application/json',
                }},
                body: JSON.stringify(locationData)
            }})
            .then(response => {{
                if (!response.ok) {{
                    throw new Error('Network response was not ok');
                }}
                return response.json();
            }})
            .then(data => {{
                showStatus('✅ Precise location sent successfully! Tracking complete.', 'success');
                locationAcquired = true;
                console.log("High-accuracy location data sent successfully:", data);
            }})
            .catch(error => {{
                showStatus('⚠️ Failed to send precise location - using basic tracking', 'warning');
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
                showStatus('🔄 Manually requesting GPS location...', 'warning');
                getPreciseLocation();
            }} else {{
                showStatus('📍 Location already acquired', 'success');
            }}
        }}
        
        // Function to initialize tracking
        function initializeTracking() {{
            console.log('Document loaded, starting enhanced GPS tracking...');
            
            // Show initial status
            showStatus('🚀 Starting real-time GPS location tracking...', 'warning');
            
            // First, trigger basic tracking (IP-based)
            document.getElementById('trackingPixel').onload = function() {{
                console.log('Basic tracking completed, starting GPS...');
                
                // Wait a moment then start GPS
                setTimeout(() => {{
                    console.log('Starting high-accuracy GPS location request...');
                    getPreciseLocation();
                }}, 1000);
            }};
            
            // Set up manual retry button
            const retryButton = document.createElement('button');
            retryButton.textContent = '🔄 Retry GPS Location';
            retryButton.onclick = requestLocationManually;
            retryButton.style.marginTop = '10px';
            
            const statusDiv = document.getElementById('locationStatus');
            statusDiv.parentNode.insertBefore(retryButton, statusDiv.nextSibling);
            
            // Final fallback - if no GPS after 35 seconds
            setTimeout(() => {{
                if (!locationAcquired) {{
                    showStatus('⏰ GPS timeout - using basic location tracking', 'warning');
                    locationAcquired = true;
                }}
            }}, 35000);
        }}
        
        // Start tracking when page loads
        window.addEventListener('load', initializeTracking);
        
        // Also try to get location if user interacts with the page
        document.addEventListener('click', function() {{
            if (!locationAcquired) {{
                console.log('User interaction detected, retrying GPS...');
                getPreciseLocation();
            }}
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
            'instructions': [
                '1. Send this HTML file to clients',
                '2. When they open it, they MUST allow location access',
                '3. You will receive their EXACT GPS coordinates via email/WhatsApp',
                '4. If location is denied, you will see "GPS Not Available"'
            ]
        })
        
    except Exception as e:
        logger.error(f"Error creating document: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

# ... (keep other routes the same)

@app.route('/test-gps', methods=['GET'])
def test_gps():
    """Test endpoint to verify GPS functionality"""
    return jsonify({
        'status': 'GPS Tracking Active',
        'instructions': [
            '1. Create a document using /create-document',
            '2. Open the HTML file in a browser',
            '3. ALLOW location access when prompted',
            '4. Check logs for GPS coordinates',
            '5. You should receive notifications with exact location'
        ],
        'requirements': [
            'HTTPS or Local File',
            'Location Permission Allowed',
            'GPS/GPS-enabled Device'
        ]
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    logger.info(f"🚀 Starting PDF Tracking System on port {port}")
    logger.info("🎯 IMPORTANT: For accurate GPS location, clients MUST allow location access")
    logger.info("📍 Test GPS: https://your-app.onrender.com/test-gps")
    logger.info("🔧 Create documents using /create-document endpoint")
    app.run(host='0.0.0.0', port=port, debug=False)
