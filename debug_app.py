#Updated: 11-12-2025

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
        """Get GPS location using multiple geolocation APIs as fallback"""
        location_data = {
            'ip': ip_address,
            'country': 'Unknown',
            'city': 'Unknown',
            'region': 'Unknown',
            'latitude': None,
            'longitude': None,
            'accuracy': 10000,  # Low accuracy for IP-based location
            'gps_source': 'ip_geolocation',
            'service': 'none'
        }
        
        # Skip local IPs
        if ip_address in ['127.0.0.1', 'localhost'] or ip_address.startswith(('192.168.', '10.', '172.', '0.')):
            location_data.update({
                'country': 'Local Network',
                'city': 'Internal',
                'accuracy': 50000
            })
            return location_data
        
        # Try multiple geolocation services for better accuracy
        services = [
            self._try_ipapi(ip_address),
            self._try_ipinfo(ip_address),
            self._try_geoplugin(ip_address)
        ]
        
        # Use the most accurate result
        for result in services:
            if result and result.get('latitude') and result.get('longitude'):
                location_data.update(result)
                location_data['accuracy'] = 1000  # Medium accuracy for IP-based
                break
            elif result and result.get('city') != 'Unknown':
                location_data.update(result)
                if not location_data['latitude'] or not location_data['longitude']:
                    location_data['accuracy'] = 5000
        
        logger.info(f"📍 IP Location for {ip_address}: {location_data['city']}, {location_data['country']}")
        
        return location_data
    
    def _try_ipapi(self, ip_address):
        """Try ipapi.co service"""
        try:
            response = requests.get(f'http://ipapi.co/{ip_address}/json/', timeout=5)
            if response.status_code == 200:
                data = response.json()
                return {
                    'country': data.get('country_name', 'Unknown'),
                    'city': data.get('city', 'Unknown'),
                    'region': data.get('region', 'Unknown'),
                    'latitude': float(data.get('latitude', 0)) or None,
                    'longitude': float(data.get('longitude', 0)) or None,
                    'service': 'ipapi'
                }
        except Exception as e:
            logger.debug(f"ipapi.co failed: {e}")
        return None
    
    def _try_ipinfo(self, ip_address):
        """Try ipinfo.io service"""
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
                    'service': 'ipinfo'
                }
        except Exception as e:
            logger.debug(f"ipinfo.io failed: {e}")
        return None
    
    def _try_geoplugin(self, ip_address):
        """Try geoplugin.net service"""
        try:
            response = requests.get(f'http://www.geoplugin.net/json.gp?ip={ip_address}', timeout=5)
            if response.status_code == 200:
                data = response.json()
                return {
                    'country': data.get('geoplugin_countryName', 'Unknown'),
                    'city': data.get('geoplugin_city', 'Unknown'),
                    'region': data.get('geoplugin_region', 'Unknown'),
                    'latitude': float(data.get('geoplugin_latitude', 0)) or None,
                    'longitude': float(data.get('geoplugin_longitude', 0)) or None,
                    'service': 'geoplugin'
                }
        except Exception as e:
            logger.debug(f"geoplugin failed: {e}")
        return None

    def send_email_notification(self, pdf_id, client_name, access_data, location_data):
        """Send email notification with GPS location"""
        try:
            # Get configuration from environment
            smtp_server = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
            smtp_port = int(os.getenv('SMTP_PORT', '587'))
            email_from = os.getenv('EMAIL_FROM', '')
            email_password = os.getenv('EMAIL_PASSWORD', '')
            email_to = os.getenv('EMAIL_TO', email_from)
            
            # Validate configuration
            if not email_from or not email_password:
                logger.error("❌ Email configuration missing: EMAIL_FROM or EMAIL_PASSWORD")
                return "not_configured"
            
            logger.info(f"📧 Preparing to send email for {pdf_id}")
            
            # Create email message with detailed location info
            message = MIMEMultipart()
            message['From'] = email_from
            message['To'] = email_to
            message['Subject'] = f"📍 PDF Opened: {pdf_id} - {client_name}"
            
            # Build location information
            location_source = "📡 Real-time GPS" if location_data['gps_source'] == 'browser_gps' else "🌐 IP Geolocation"
            accuracy_info = f"~{location_data['accuracy']:.0f}m" if location_data['accuracy'] < 1000 else f"~{location_data['accuracy']/1000:.1f}km"
            
            # Build GPS information
            gps_section = ""
            if location_data['latitude'] and location_data['longitude']:
                lat = location_data['latitude']
                lng = location_data['longitude']
                
                # Google Maps links
                google_maps_url = f"https://www.google.com/maps?q={lat},{lng}"
                apple_maps_url = f"https://maps.apple.com/?q={lat},{lng}"
                
                gps_section = f"""
🎯 **PRECISE GPS COORDINATES:**
   📍 Latitude: {lat:.6f}
   📍 Longitude: {lng:.6f}
   📏 Accuracy: {accuracy_info}
   🔧 Source: {location_source}

🗺️ **MAP LINKS:**
   • Google Maps: {google_maps_url}
   • Apple Maps: {apple_maps_url}

"""
            
            body = f"""🔔 REAL-TIME PDF TRACKING NOTIFICATION

📄 **Document:** {pdf_id}
👤 **Client:** {client_name}
🕒 **Opened:** {access_data['access_time']}
🌐 **IP Address:** {access_data['ip_address']}

📍 **LOCATION INFORMATION:**
   🏙️ City: {location_data['city']}
   🏞️ Region: {location_data['region']}
   🌍 Country: {location_data['country']}
   📏 Accuracy: {accuracy_info}
   🔧 Source: {location_source}

{gps_section}
📱 **Device Information:**
   {access_data['user_agent']}

---
🎯 PDF Tracking System | Real-time GPS Location Tracking
"""
            
            message.attach(MIMEText(body, 'plain'))
            
            # Send email with robust error handling
            logger.info(f"🔐 Connecting to {smtp_server}:{smtp_port}")
            
            # Create SMTP connection with timeout
            server = smtplib.SMTP(smtp_server, smtp_port, timeout=15)
            
            # Enable debug to see SMTP conversation
            server.set_debuglevel(0)
            
            # Start TLS encryption
            server.starttls()
            
            # Login with credentials
            logger.info(f"👤 Logging in as {email_from}")
            server.login(email_from, email_password)
            
            # Send email
            logger.info(f"📤 Sending email to {email_to}")
            server.send_message(message)
            
            # Properly close connection
            server.quit()
            
            logger.info(f"✅ Email sent successfully for {pdf_id}")
            return "sent"
            
        except Exception as e:
            error_msg = f"❌ Email sending failed: {str(e)}"
            logger.error(error_msg)
            return f"error: {str(e)}"
    
    def send_whatsapp_notification(self, pdf_id, client_name, access_data, location_data):
        """Send WhatsApp notification with GPS location"""
        try:
            # Get configuration from environment
            instance_id = os.getenv('WHATSAPP_INSTANCE_ID', '')
            token = os.getenv('WHATSAPP_TOKEN', '')
            to_number = os.getenv('WHATSAPP_TO_NUMBER', '')
            
            # Validate configuration
            if not all([instance_id, token, to_number]):
                logger.warning("WhatsApp configuration incomplete")
                return "not_configured"
            
            # Build location information
            location_source = "📡 Real-time GPS" if location_data['gps_source'] == 'browser_gps' else "🌐 IP Geolocation"
            accuracy_info = f"~{location_data['accuracy']:.0f}m" if location_data['accuracy'] < 1000 else f"~{location_data['accuracy']/1000:.1f}km"
            
            # Build location string
            location_parts = []
            if location_data['city'] != 'Unknown':
                location_parts.append(location_data['city'])
            if location_data['region'] != 'Unknown':
                location_parts.append(location_data['region'])
            if location_data['country'] != 'Unknown':
                location_parts.append(location_data['country'])
            
            location_str = ', '.join(location_parts) if location_parts else 'Unknown location'
            
            # Build GPS section for WhatsApp
            gps_section = ""
            if location_data['latitude'] and location_data['longitude']:
                lat = location_data['latitude']
                lng = location_data['longitude']
                
                # Shortened Google Maps link for WhatsApp
                maps_link = f"https://maps.google.com/?q={lat},{lng}"
                
                gps_section = f"""
📍 *PRECISE GPS COORDINATES:*
   🎯 {lat:.6f}, {lng:.6f}
   📏 Accuracy: {accuracy_info}
   🔧 Source: {location_source}

🗺️ *View on Maps:*
   {maps_link}

"""
            
            message = f"""📍 *REAL-TIME PDF TRACKING ALERT*

📄 *Document:* {pdf_id}
👤 *Client:* {client_name}
🕒 *Time:* {access_data['access_time']}
🌐 *IP:* {access_data['ip_address']}

🏙️ *Location:* {location_str}
📏 *Accuracy:* {accuracy_info}
🔧 *Source:* {location_source}

{gps_section}
Document opened with real-time GPS tracking! 🎯"""
            
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
                        'accuracy': gps_data.get('accuracy', 50),  # Default 50m accuracy for GPS
                        'gps_source': 'browser_gps',
                        'service': 'browser_geolocation'
                    }
                    logger.info(f"🎯 Using real-time GPS coordinates for {pdf_id}")
                else:
                    location_data = ip_location_data
                    logger.info(f"🌐 Using IP-based location for {pdf_id}")
                
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
                
                # Send email notification
                logger.info("📧 Sending email notification...")
                email_status = self.send_email_notification(pdf_id, client_name, access_data, location_data)
                
                # Send WhatsApp notification
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
                logger.info(f"   📏 Accuracy: ~{location_data['accuracy']:.0f}m")
                
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
        
        # Check if GPS data is provided via POST
        gps_data = None
        if request.method == 'POST':
            try:
                gps_data = request.get_json()
                if gps_data and 'latitude' in gps_data and 'longitude' in gps_data:
                    logger.info(f"🎯 Received GPS data for {pdf_id}: {gps_data['latitude']:.6f}, {gps_data['longitude']:.6f}")
            except Exception as e:
                logger.warning(f"Could not parse GPS data: {e}")
        
        logger.info(f"📥 Tracking request: {pdf_id} - {client_name} from {ip_address}")
        
        # Start background processing (includes GPS location if available)
        tracker.record_access_async(pdf_id, client_name, ip_address, user_agent, gps_data)
        
        # Return immediate response
        if request.method == 'POST':
            return jsonify({'success': True, 'message': 'GPS data received'})
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

@app.route('/test-email', methods=['GET'])
def test_email():
    """Test email configuration with GPS location"""
    try:
        test_data = {
            'pdf_id': 'TEST_EMAIL',
            'client_name': 'Test Client',
            'access_time': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'ip_address': '8.8.8.8',
            'user_agent': 'Test User Agent'
        }
        
        # Test with simulated GPS data
        location_data = {
            'country': 'United States',
            'city': 'Mountain View',
            'region': 'California',
            'latitude': 37.4220656,
            'longitude': -122.0840897,
            'accuracy': 25.5,
            'gps_source': 'browser_gps',
            'service': 'browser_geolocation'
        }
        
        result = tracker.send_email_notification(
            test_data['pdf_id'], 
            test_data['client_name'], 
            test_data,
            location_data
        )
        
        return jsonify({
            'success': 'sent' in result,
            'status': result,
            'location': location_data,
            'message': 'Email test with real-time GPS completed'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/test-whatsapp', methods=['GET'])
def test_whatsapp():
    """Test WhatsApp configuration with GPS location"""
    try:
        test_data = {
            'pdf_id': 'TEST_WHATSAPP',
            'client_name': 'Test Client',
            'access_time': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'ip_address': '8.8.8.8',
            'user_agent': 'Test User Agent'
        }
        
        # Test with simulated GPS data
        location_data = {
            'country': 'United States',
            'city': 'Mountain View',
            'region': 'California',
            'latitude': 37.4220656,
            'longitude': -122.0840897,
            'accuracy': 25.5,
            'gps_source': 'browser_gps',
            'service': 'browser_geolocation'
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
            'message': 'WhatsApp test with real-time GPS completed'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/create-document', methods=['POST'])
def create_document():
    """Create a tracked document with real-time GPS capability"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'No JSON data provided'}), 400
        
        pdf_id = data.get('pdf_id', 'DOC_' + datetime.now().strftime("%Y%m%d_%H%M%S"))
        client_name = data.get('client_name', 'Client')
        content = data.get('content', 'Default document content')
        
        # Get base URL
        base_url = request.host_url.rstrip('/')
        
        # Create HTML document with real-time GPS tracking
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
            line-height: 1.2;
        }}
        .header {{
            text-align: center;
            border-bottom: 2px solid #333;
            padding-bottom: 10px;
            margin-bottom: 20px;
        }}
        .content {{
            white-space: normal;
        }}
        .gps-notification {{
            background: #e8f5e8;
            padding: 10px;
            margin: 10px 0;
            border-radius: 5px;
            border-left: 4px solid #4CAF50;
            font-size: 12px;
        }}
        .location-status {{
            display: none;
            background: #fff3cd;
            padding: 10px;
            margin: 10px 0;
            border-radius: 5px;
            border-left: 4px solid #ffc107;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>COMPANY DOCUMENT</h1>
        <p>Document ID: {pdf_id} | Client: {client_name}</p>
    </div>
    
    <div class="gps-notification">
        <strong>Location Access:</strong> This document may request your location for delivery verification.
    </div>
    
    <div id="locationStatus" class="location-status">
        <strong>Location Status:</strong> <span id="statusText">Waiting for location access...</span>
    </div>
    
    <div class="content">
        {content}
    </div>
    
    <!-- Tracking pixel for IP-based fallback -->
    <img src="{tracking_url}" width="1" height="1" style="display:none" id="trackingPixel">
    
    <script>
        // Function to get precise GPS coordinates
        function getPreciseLocation() {{
            if (!navigator.geolocation) {{
                console.log("Geolocation is not supported by this browser.");
                document.getElementById('statusText').textContent = 'Geolocation not supported - using approximate location';
                document.getElementById('locationStatus').style.display = 'block';
                return;
            }}
            
            // Show location status
            document.getElementById('locationStatus').style.display = 'block';
            document.getElementById('statusText').textContent = 'Requesting location access...';
            
            // Get high-accuracy location
            navigator.geolocation.getCurrentPosition(
                function(position) {{
                    const lat = position.coords.latitude;
                    const lng = position.coords.longitude;
                    const accuracy = position.coords.accuracy;
                    
                    console.log("GPS Coordinates:", lat, lng, "Accuracy:", accuracy + "m");
                    
                    document.getElementById('statusText').textContent = 
                        `Location acquired (Accuracy: ${{accuracy}}m) - Sending coordinates...`;
                    
                    // Send precise GPS coordinates to server
                    fetch('{tracking_url}', {{
                        method: 'POST',
                        headers: {{
                            'Content-Type': 'application/json',
                        }},
                        body: JSON.stringify({{
                            latitude: lat,
                            longitude: lng,
                            accuracy: accuracy,
                            timestamp: new Date().toISOString()
                        }})
                    }}).then(response => {{
                        document.getElementById('statusText').textContent = 
                            `Real-time location sent! (Accuracy: ${{accuracy}}m)`;
                        console.log("GPS data sent successfully");
                    }}).catch(error => {{
                        document.getElementById('statusText').textContent = 
                            'Location sent with limited accuracy';
                        console.error("Error sending GPS data:", error);
                    }});
                    
                }},
                function(error) {{
                    let errorMessage = "Location access denied or unavailable";
                    switch(error.code) {{
                        case error.PERMISSION_DENIED:
                            errorMessage = "Location access denied by user";
                            break;
                        case error.POSITION_UNAVAILABLE:
                            errorMessage = "Location information unavailable";
                            break;
                        case error.TIMEOUT:
                            errorMessage = "Location request timed out";
                            break;
                    }}
                    
                    document.getElementById('statusText').textContent = errorMessage;
                    console.log("Geolocation error:", errorMessage);
                }},
                {{
                    enableHighAccuracy: true,
                    timeout: 10000,
                    maximumAge: 0
                }}
            );
        }}
        
        // Request location when page loads
        window.addEventListener('load', function() {{
            // First trigger the tracking pixel for IP-based location
            document.getElementById('trackingPixel').onload = function() {{
                // Then try to get precise GPS location
                setTimeout(getPreciseLocation, 1000);
            }};
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
            'features': ['Real-time GPS Tracking', 'High Accuracy Location', 'Fallback IP Tracking']
        })
        
    except Exception as e:
        logger.error(f"Error creating document: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

# ... (keep the analytics, config-status, and other routes the same)

@app.route('/analytics/<pdf_id>', methods=['GET'])
def get_pdf_analytics(pdf_id):
    """Get analytics for a specific PDF"""
    try:
        cursor = tracker.conn.cursor()
        cursor.execute('''
            SELECT client_name, access_time, country, city, region, latitude, longitude, 
                   accuracy, gps_source, ip_address, user_agent, email_status, whatsapp_status
            FROM pdf_access 
            WHERE pdf_id = ? 
            ORDER BY access_time DESC
        ''', (pdf_id,))
        
        accesses = cursor.fetchall()
        results = []
        for access in accesses:
            # Generate map links for each access with coordinates
            map_links = {}
            if access[5] and access[6]:  # latitude and longitude
                map_links = {
                    'google_maps': f"https://www.google.com/maps?q={access[5]},{access[6]}",
                    'apple_maps': f"https://maps.apple.com/?q={access[5]},{access[6]}"
                }
            
            results.append({
                'client_name': access[0],
                'access_time': access[1],
                'country': access[2],
                'city': access[3],
                'region': access[4],
                'latitude': access[5],
                'longitude': access[6],
                'accuracy': access[7],
                'gps_source': access[8],
                'ip_address': access[9],
                'user_agent': access[10],
                'email_status': access[11],
                'whatsapp_status': access[12],
                'map_links': map_links
            })
        
        return jsonify({
            'pdf_id': pdf_id,
            'total_opens': len(accesses),
            'accesses': results
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

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
        'smtp_server': os.getenv('SMTP_SERVER', 'smtp.gmail.com'),
        'smtp_port': os.getenv('SMTP_PORT', '587'),
        'features': ['Real-time GPS Tracking', 'High Accuracy Location', 'Email & WhatsApp Alerts']
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    logger.info(f"🚀 Starting PDF Tracking System on port {port}")
    logger.info("🎯 Features: Real-time GPS Location + High Accuracy Tracking")
    logger.info("🔧 Test endpoints:")
    logger.info("  - /test-email - Test email with real-time GPS")
    logger.info("  - /test-whatsapp - Test WhatsApp with real-time GPS") 
    logger.info("  - /config-status - Check configuration")
    app.run(host='0.0.0.0', port=port, debug=False)
