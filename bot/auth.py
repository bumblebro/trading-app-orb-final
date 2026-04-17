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
    
    api_key = get_setting("api_key")
    client_id = get_setting("client_id")
    pin = get_setting("pin")
    totp_secret = get_setting("totp_secret")

    if not all([api_key, client_id, pin, totp_secret]):
        logger.error("Angel One login failed: Missing credentials in settings")
        return None, None

    try:
        # 1. Generate TOTP
        try:
            # Aggressively clean the secret: remove spaces, ensure uppercase, and strip any non-base32 characters
            import re
            clean_secret = re.sub(r'[^A-Z2-7]', '', totp_secret.upper().strip())
            totp = pyotp.TOTP(clean_secret).now()
        except Exception as te:
            logger.error(f"TOTP generation failed (Secret length={len(totp_secret)}): {te}")
            return None, None

        # 2. Initialize SmartConnect
        smart_api = SmartConnect(api_key=api_key)

        # 3. Generate Session
        data = smart_api.generateSession(client_id, pin, totp)
        
        if data and data['status']:
            feed_token = smart_api.getfeedToken()
            logger.info(f"Angel One session generated for client: {client_id}")
            return smart_api, feed_token
        else:
            logger.error(f"Angel One login failed: {data.get('message', 'Unknown error')}")
            return None, None

    except Exception as e:
        logger.error(f"Angel One authentication error: {e}")
        return None, None
