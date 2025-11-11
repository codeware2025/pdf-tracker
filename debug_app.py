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
                region TEXT,
                latitude REAL,
                longitude REAL,
                user_agent TEXT,
                email_status TEXT,
                whatsapp_status TEXT,
                status TEXT DEFAULT 'delivered'
            )
        ''')
        self.conn.commit()
        logger.info("Database initialized successfully")
    
    def get_accurate_location(self, ip_address):
        """Get accurate GPS location using multiple geolocation APIs"""
        location_data = {
            'ip': ip_address,
            'country': 'Unknown',
            'city': 'Unknown',
            'region': 'Unknown',
            'latitude': None,
            'longitude': None,
            'accuracy': 'low',
            'service': 'none'
        }
        
        # Skip local IPs
        if ip_address in ['127.0.0.1', 'localhost'] or ip_address.startswith(('192.168.', '10.', '172.', '0.')):
            location_data.update({
                'country': 'Local Network',
                'city': 'Internal',
                'accuracy': 'local'
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
                location_data['accuracy'] = 'high'
                break
            elif result and result.get('city') != 'Unknown':
                location_data.update(result)
                if not location_data['latitude'] or not location_data['longitude']:
                    location_data['accuracy'] = 'medium'
        
        logger.info(f"📍 Location for {ip_address}: {location_data['city']}, {location_data['country']} "
                   f"({location_data['latitude']}, {location_data['longitude']})")
        
        return location_data
    
    def _try_ipapi(self, ip_address):
        """Try ipapi.co service (usually most accurate)"""
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

    def send_email_via_smtp(self, pdf_id, client_name, access_data, location_data):
        """Try SMTP method for email sending"""
        try:
            smtp_server = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
            smtp_port = int(os.getenv('SMTP_PORT', '587'))
            email_from = os.getenv('EMAIL_FROM', '')
            email_password = os.getenv('EMAIL_PASSWORD', '')
            email_to = os.getenv('EMAIL_TO', email_from)
            
            if not email_from or not email_password:
                return "not_configured"
            
            # Build email content
            location_parts = []
            if location_data['city'] != 'Unknown':
                location_parts.append(location_data['city'])
            if location_data['region'] != 'Unknown':
                location_parts.append(location_data['region'])
            if location_data['country'] != 'Unknown':
                location_parts.append(location_data['country'])
            
            location_str = ', '.join(location_parts) if location_parts else 'Location unknown'
            
            gps_section = ""
            if location_data['latitude'] and location_data['longitude']:
                lat = location_data['latitude']
                lng = location_data['longitude']
                google_maps_url = f"https://www.google.com/maps?q={lat},{lng}"
                
                gps_section = f"""
🎯 GPS COORDINATES:
   📍 Latitude: {lat:.6f}
   📍 Longitude: {lng:.6f}

🗺️ Google Maps: {google_maps_url}

"""
            
            body = f"""🔔 PDF TRACKING NOTIFICATION

📄 Document: {pdf_id}
👤 Client: {client_name}
🕒 Opened: {access_data['access_time']}
🌐 IP Address: {access_data['ip_address']}

📍 LOCATION:
   🏙️ City: {location_data['city']}
   🏞️ Region: {location_data['region']}
   🌍 Country: {location_data['country']}
   📊 Accuracy: {location_data['accuracy'].upper()}

{gps_section}
📱 Device: {access_data['user_agent']}

---
PDF Tracking System"""
            
            message = MIMEMultipart()
            message['From'] = email_from
            message['To'] = email_to
            message['Subject'] = f"📍 PDF Opened: {pdf_id} - {client_name}"
            message.attach(MIMEText(body, 'plain'))
            
            # Try SMTP with shorter timeout
            server = smtplib.SMTP(smtp_server, smtp_port, timeout=10)
            server.starttls()
            server.login(email_from, email_password)
            server.send_message(message)
            server.quit()
            
            logger.info(f"✅ Email sent via SMTP for {pdf_id}")
            return "sent_via_smtp"
            
        except Exception as e:
            logger.warning(f"SMTP failed: {e}")
            return None

    def send_email_via_resend(self, pdf_id, client_name, access_data, location_data):
        """Try Resend.com API for email sending"""
        try:
            resend_api_key = os.getenv('RESEND_API_KEY')
            if not resend_api_key:
                return None
            
            email_from = os.getenv('EMAIL_FROM', '')
            email_to = os.getenv('EMAIL_TO', email_from)
            
            # Build email content
            location_parts = []
            if location_data['city'] != 'Unknown':
                location_parts.append(location_data['city'])
            if location_data['region'] != 'Unknown':
                location_parts.append(location_data['region'])
            if location_data['country'] != 'Unknown':
                location_parts.append(location_data['country'])
            
            location_str = ', '.join(location_parts) if location_parts else 'Location unknown'
            
            gps_section = ""
            if location_data['latitude'] and location_data['longitude']:
                lat = location_data['latitude']
                lng = location_data['longitude']
                google_maps_url = f"https://www.google.com/maps?q={lat},{lng}"
                
                gps_section = f"""
🎯 GPS COORDINATES:
   📍 Latitude: {lat:.6f}
   📍 Longitude: {lng:.6f}

🗺️ Google Maps: {google_maps_url}

"""
            
            body = f"""🔔 PDF TRACKING NOTIFICATION

📄 Document: {pdf_id}
👤 Client: {client_name}
🕒 Opened: {access_data['access_time']}
🌐 IP Address: {access_data['ip_address']}

📍 LOCATION:
   🏙️ City: {location_data['city']}
   🏞️ Region: {location_data['region']}
   🌍 Country: {location_data['country']}
   📊 Accuracy: {location_data['accuracy'].upper()}

{gps_section}
📱 Device: {access_data['user_agent']}

---
PDF Tracking System"""
            
            # Send via Resend API
            url = "https://api.resend.com/emails"
            headers = {
                "Authorization": f"Bearer {resend_api_key}",
                "Content-Type": "application/json"
            }
            data = {
                "from": f"PDF Tracker <{email_from}>",
                "to": [email_to],
                "subject": f"📍 PDF Opened: {pdf_id} - {client_name}",
                "text": body
            }
            
            response = requests.post(url, json=data, headers=headers, timeout=10)
            if response.status_code == 200:
                logger.info(f"✅ Email sent via Resend API for {pdf_id}")
                return "sent_via_resend"
            else:
                logger.warning(f"Resend API failed: {response.status_code} - {response.text}")
                return None
                
        except Exception as e:
            logger.warning(f"Resend API failed: {e}")
            return None

    def send_email_via_webhook(self, pdf_id, client_name, access_data, location_data):
        """Try webhook service for email sending"""
        try:
            webhook_url = os.getenv('EMAIL_WEBHOOK_URL')
            if not webhook_url:
                return None
            
            # Build the payload
            payload = {
                'pdf_id': pdf_id,
                'client_name': client_name,
                'access_time': access_data['access_time'],
                'ip_address': access_data['ip_address'],
                'location': {
                    'city': location_data['city'],
                    'region': location_data['region'],
                    'country': location_data['country'],
                    'latitude': location_data['latitude'],
                    'longitude': location_data['longitude'],
                    'accuracy': location_data['accuracy']
                },
                'user_agent': access_data['user_agent']
            }
            
            response = requests.post(webhook_url, json=payload, timeout=10)
            if response.status_code == 200:
                logger.info(f"✅ Notification sent via webhook for {pdf_id}")
                return "sent_via_webhook"
            else:
                logger.warning(f"Webhook failed: {response.status_code}")
                return None
                
        except Exception as e:
            logger.warning(f"Webhook failed: {e}")
            return None

    def send_email_notification(self, pdf_id, client_name, access_data, location_data):
        """Send email using multiple fallback methods"""
        logger.info(f"📧 Attempting to send email for {pdf_id}")
        
        # Try methods in order of preference
        methods = [
            self.send_email_via_smtp,
            self.send_email_via_resend,
            self.send_email_via_webhook
        ]
        
        for method in methods:
            try:
                result = method(pdf_id, client_name, access_data, location_data)
                if result and 'sent' in result:
                    return result
            except Exception as e:
                logger.warning(f"Email method {method.__name__} failed: {e}")
                continue
        
        # If all methods fail
        error_msg = "All email methods failed - Network may be blocked"
        logger.error(f"❌ {error_msg}")
        return f"error: {error_msg}"
    
    def send_whatsapp_notification(self, pdf_id, client_name, access_data, location_data):
        """Send WhatsApp notification with GPS location"""
        try:
            instance_id = os.getenv('WHATSAPP_INSTANCE_ID', '')
            token = os.getenv('WHATSAPP_TOKEN', '')
            to_number = os.getenv('WHATSAPP_TO_NUMBER', '')
            
            if not all([instance_id, token, to_number]):
                logger.warning("WhatsApp configuration incomplete")
                return "not_configured"
            
            # Build location string
            location_parts = []
            if location_data['city'] != 'Unknown':
                location_parts.append(location_data['city'])
            if location_data['region'] != 'Unknown':
                location_parts.append(location_data['region'])
            if location_data['country'] != 'Unknown':
                location_parts.append(location_data['country'])
            
            location_str = ', '.join(location_parts) if location_parts else 'Unknown location'
            
            # Build GPS section
            gps_section = ""
            if location_data['latitude'] and location_data['longitude']:
                lat = location_data['latitude']
                lng = location_data['longitude']
                maps_link = f"https://maps.google.com/?q={lat},{lng}"
                
                gps_section = f"""
📍 *GPS Coordinates:*
   🎯 {lat:.6f}, {lng:.6f}

🗺️ *View on Maps:*
   {maps_link}

"""
            
            message = f"""📍 *PDF TRACKING ALERT*

📄 *Document:* {pdf_id}
👤 *Client:* {client_name}
🕒 *Time:* {access_data['access_time']}
🌐 *IP:* {access_data['ip_address']}

🏙️ *Location:* {location_str}
📊 *Accuracy:* {location_data['accuracy'].upper()}

{gps_section}
Document opened with location tracking! 🎯"""
            
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

    def record_access_async(self, pdf_id, client_name, ip_address, user_agent):
        """Record access and send notifications in background thread"""
        def process_notifications():
            try:
                logger.info(f"🎯 Processing notifications for {pdf_id}")
                
                # Get accurate location
                location_data = self.get_accurate_location(ip_address)
                access_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
                access_data = {
                    'access_time': access_time,
                    'ip_address': ip_address,
                    'user_agent': user_agent
                }
                
                # Save to database first
                cursor = self.conn.cursor()
                cursor.execute('''
                    INSERT INTO pdf_access 
                    (pdf_id, client_name, access_time, ip_address, country, city, region, latitude, longitude, user_agent, email_status, whatsapp_status, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    pdf_id, client_name, access_time, ip_address,
                    location_data['country'], location_data['city'], location_data['region'],
                    location_data['latitude'], location_data['longitude'], user_agent,
                    'processing', 'processing', 'opened'
                ))
                self.conn.commit()
                
                record_id = cursor.lastrowid
                
                # Send notifications
                email_status = self.send_email_notification(pdf_id, client_name, access_data, location_data)
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
    return render_template('index.html')

@app.route('/test-email', methods=['GET'])
def test_email():
    """Test email configuration"""
    try:
        test_ip = "8.8.8.8"
        location_data = tracker.get_accurate_location(test_ip)
        
        test_data = {
            'pdf_id': 'TEST_EMAIL',
            'client_name': 'Test Client',
            'access_time': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'ip_address': test_ip,
            'user_agent': 'Test User Agent'
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
            'message': 'Email test completed'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/test-smtp', methods=['GET'])
def test_smtp():
    """Test SMTP connection specifically"""
    try:
        import socket
        smtp_server = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
        smtp_port = int(os.getenv('SMTP_PORT', '587'))
        
        # Test network connectivity first
        logger.info(f"Testing connection to {smtp_server}:{smtp_port}")
        
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(10)
        result = sock.connect_ex((smtp_server, smtp_port))
        sock.close()
        
        if result == 0:
            return jsonify({
                'success': True,
                'message': f'Network connection to {smtp_server}:{smtp_port} is OK'
            })
        else:
            return jsonify({
                'success': False,
                'error': f'Network connection failed: error code {result}',
                'solution': 'SMTP is blocked. Use Resend.com API instead.'
            })
            
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/test-whatsapp', methods=['GET'])
def test_whatsapp():
    """Test WhatsApp configuration"""
    try:
        test_ip = "8.8.8.8"
        location_data = tracker.get_accurate_location(test_ip)
        
        test_data = {
            'pdf_id': 'TEST_WHATSAPP',
            'client_name': 'Test Client',
            'access_time': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'ip_address': test_ip,
            'user_agent': 'Test User Agent'
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

# ... (keep the rest of your routes the same - track-pdf, analytics, create-document, etc.)

@app.route('/config-status', methods=['GET'])
def config_status():
    """Check configuration status"""
    email_configured = bool(os.getenv('EMAIL_FROM') and os.getenv('EMAIL_PASSWORD'))
    resend_configured = bool(os.getenv('RESEND_API_KEY'))
    webhook_configured = bool(os.getenv('EMAIL_WEBHOOK_URL'))
    whatsapp_configured = bool(
        os.getenv('WHATSAPP_INSTANCE_ID') and 
        os.getenv('WHATSAPP_TOKEN') and 
        os.getenv('WHATSAPP_TO_NUMBER')
    )
    
    return jsonify({
        'email_configured': email_configured,
        'resend_configured': resend_configured,
        'webhook_configured': webhook_configured,
        'whatsapp_configured': whatsapp_configured,
        'smtp_server': os.getenv('SMTP_SERVER', 'smtp.gmail.com'),
        'smtp_port': os.getenv('SMTP_PORT', '587'),
        'recommendation': 'Use Resend.com API if SMTP is blocked'
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    logger.info(f"🚀 Starting PDF Tracking System on port {port}")
    logger.info("🔧 Test endpoints:")
    logger.info("  - /test-smtp - Check SMTP connectivity")
    logger.info("  - /test-email - Test email with fallback methods")
    logger.info("  - /test-whatsapp - Test WhatsApp")
    logger.info("  - /config-status - Check configuration")
    app.run(host='0.0.0.0', port=port, debug=False)
