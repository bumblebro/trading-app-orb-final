"""
Authentication module for Angel One SmartAPI.
Handles session generation, TOTP, and login.
"""

import pyotp
from SmartApi import SmartConnect
from database import get_setting
from logger import get_logger

def login_and_get_session():
    """
    Perform login and return an authenticated SmartConnect instance and feed token.
    Returns: (SmartConnect object, feed_token) or (None, None) if failed.
    """
    logger = get_logger()
    
    api_key = (get_setting("api_key") or "").strip()
    client_id = (get_setting("client_id") or "").strip()
    pin = (get_setting("pin") or "").strip()
    totp_secret = (get_setting("totp_secret") or "").strip()

    if not all([api_key, client_id, pin, totp_secret]):
        logger.error("Angel One login failed: Missing credentials in settings")
        return None, None

    try:
        # 1. Prepare Credentials
        # Aggressively clean the secret: remove spaces, ensure uppercase, and strip any non-base32 characters
        import re
        clean_secret = re.sub(r'[^A-Z2-7]', '', totp_secret.upper())
        
        if len(clean_secret) < 8:
            logger.error(f"Angel One login failed: TOTP secret seems too short ({len(clean_secret)} chars). Please check your secret.")
            return None, None

        # 2. Initialize SmartConnect
        smart_api = SmartConnect(api_key=api_key)

        # 3. Generate Session with TOTP Retry (for clock drift)
        # We try 3 windows: [current, -30s, +30s]
        import time
        from datetime import datetime
        
        system_now = datetime.now().strftime("%H:%M:%S")
        logger.info(f"Attempting Angel One login for {client_id} (System time: {system_now})")
        
        # Try current window first
        totp_obj = pyotp.TOTP(clean_secret)
        
        # Try a few windows to account for server/client clock mismatch
        # Offset 0 (current), -1 (30s ago), +1 (30s future)
        for offset in [0, -1, 1]:
            try:
                # Calculate TOTP for the specific offset
                # pyotp.TOTP.at() takes a timestamp
                target_time = time.time() + (offset * 30)
                totp = totp_obj.at(target_time)
                
                data = smart_api.generateSession(client_id, pin, totp)
                
                if data and data['status']:
                    feed_token = smart_api.getfeedToken()
                    logger.info(f"Angel One session generated for client: {client_id} (Window offset: {offset})")
                    return smart_api, feed_token
                
                # If it's a specific "Invalid TOTP" error, we continue to next window
                # Error code AB1050 is "Invalid totp and client combination"
                error_msg = data.get('message', '')
                error_code = data.get('errorcode', '')
                
                if "totp" in error_msg.lower() or error_code == "AB1050":
                    if offset != 1: # Log only if we have more windows to try
                        logger.warning(f"Login failed for {client_id} with TOTP window {offset}. Trying next window...")
                    continue
                else:
                    # Other errors (e.g. invalid password/api key) shouldn't be retried with different TOTP
                    logger.error(f"Angel One login failed: {error_msg} (Code: {error_code})")
                    return None, None
                    
            except Exception as e:
                logger.error(f"Error during login attempt (offset {offset}): {e}")
                continue

        logger.error(f"Angel One login failed for {client_id} after trying multiple TOTP windows. Please verify your TOTP Secret, Client ID, and PIN.")
        return None, None

    except Exception as e:
        logger.error(f"Angel One authentication error: {e}")
        return None, None
