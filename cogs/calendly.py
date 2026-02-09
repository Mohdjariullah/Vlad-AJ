# Calendly booking integration – COMMENTED OUT (not deleted).
# To re-enable: 1) Uncomment this file body below. 2) In cogs/verification.py uncomment
# the Calendly import and the "has_booked, event_type = check_email_booked_specific_events(...)" block,
# and switch the modal to call assign_role_based_on_booking(interaction, email, event_type) when has_booked.
#
import requests
import os
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple, List
import time
from functools import lru_cache

# Production Configuration
CALENDLY_TOKEN = os.getenv('CALENDLY_TOKEN')
CALENDLY_USER_URI = os.getenv('CALENDLY_USER_URI')



# Event UUIDs for specific call types
MASTERMIND_EVENT_UUID = "b14efb6e-2e2c-403c-a883-fc27b95ef6ee"  # Mastermind Onboarding Roadmap Call
GAMEPLAN_EVENT_UUID = "fd175687-be69-45f1-964b-52478d350ebb"  # Profitability Game Plan Call

# API Configuration
REQUEST_TIMEOUT = 30  # Increased timeout
MAX_RETRIES = 5  # More retries
CACHE_DURATION = 600  # 10 minutes cache

# Global cache for API responses
_api_cache = {}
_cache_timestamps = {}

class CalendlyAPIError(Exception):
    """Custom exception for Calendly API errors"""
    pass

class CalendlyBookingChecker:
    """Production-level Calendly booking checker"""
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'Authorization': f'Bearer {CALENDLY_TOKEN}',
            'Content-Type': 'application/json',
            'User-Agent': 'AJ-Trading-Bot/1.0'
        })
        
        if not CALENDLY_TOKEN:
            raise CalendlyAPIError("CALENDLY_TOKEN environment variable is required")
    
    def _make_request(self, url: str, params: Dict = None) -> Optional[Dict]:
        """Make a robust API request with retries and error handling - NO RATE LIMITING"""
        cache_key = f"{url}:{json.dumps(params) if params else '{}'}"
        
        # Check cache first
        if cache_key in _api_cache:
            if time.time() - _cache_timestamps.get(cache_key, 0) < CACHE_DURATION:
                return _api_cache[cache_key]
        
        for attempt in range(MAX_RETRIES):
            try:
                response = self.session.get(
                    url, 
                    params=params, 
                    timeout=REQUEST_TIMEOUT
                )
                
                if response.status_code == 200:
                    data = response.json()
                    # Cache successful response
                    _api_cache[cache_key] = data
                    _cache_timestamps[cache_key] = time.time()
                    return data
                
                elif response.status_code == 401:
                    raise CalendlyAPIError("Invalid Calendly token")
                elif response.status_code == 403:
                    raise CalendlyAPIError("Insufficient permissions for Calendly API")
                elif response.status_code == 429:
                    # Rate limit hit - just retry immediately without waiting
                    if attempt < MAX_RETRIES - 1:
                        continue
                    else:
                        raise CalendlyAPIError("Rate limit exceeded after all retries")
                else:
                    error_msg = f"API request failed: {response.status_code}"
                    try:
                        error_data = response.json()
                        if 'message' in error_data:
                            error_msg += f" - {error_data['message']}"
                        if 'title' in error_data:
                            error_msg += f" ({error_data['title']})"
                    except:
                        pass
                    raise CalendlyAPIError(error_msg)
                    
            except requests.exceptions.Timeout:
                if attempt < MAX_RETRIES - 1:
                    continue
                else:
                    raise CalendlyAPIError("Request timeout")
            except requests.exceptions.RequestException as e:
                if attempt < MAX_RETRIES - 1:
                    continue
                else:
                    raise CalendlyAPIError(f"Request failed: {str(e)}")
        
        return None
    
    def get_user_info(self) -> Optional[Dict]:
        """Get current user information"""
        return self._make_request("https://api.calendly.com/users/me")
    
    def get_scheduled_events(self, user_uri: str = None, count: int = 100) -> Optional[Dict]:
        """Get scheduled events for a user - NO LIMITS"""
        if not user_uri:
            user_uri = CALENDLY_USER_URI or self._get_user_uri()
        
        params = {
            "user": user_uri,
            "count": min(count, 100),  # Calendly max is 100
            "status": "active"
        }
        return self._make_request("https://api.calendly.com/scheduled_events", params)
    
    def get_event_invitees(self, event_uuid: str) -> Optional[Dict]:
        """Get invitees for a specific event"""
        return self._make_request(f"https://api.calendly.com/scheduled_events/{event_uuid}/invitees")
    
    def _get_user_uri(self) -> str:
        """Get user URI from API or environment"""
        # Get the user URI from the API (the one the token has access to)
        user_info = self.get_user_info()
        if user_info and 'resource' in user_info:
            user_uri = user_info['resource'].get('uri', CALENDLY_USER_URI)
            return user_uri
        return CALENDLY_USER_URI
    
    def check_email_booking(self, email: str) -> Tuple[bool, Optional[str]]:
        """
        Check if an email has booked either Mastermind or Game Plan call
        
        Args:
            email (str): Email address to check
            
        Returns:
            Tuple[bool, Optional[str]]: (has_booked, event_type)
                - has_booked: True if booking found in either event
                - event_type: "mastermind", "gameplan", or None
        """
        if not email or '@' not in email:
            logging.error(f"Invalid email: {email}")
            return False, None
        
        email = email.lower().strip()
        
        try:
            # Get user URI
            user_uri = self._get_user_uri()
            if not user_uri:
                logging.error("No user URI available")
                return False, None
            
            # Get scheduled events (max 100 per request)
            events_data = self.get_scheduled_events(user_uri, count=100)
            if not events_data:
                logging.error("Failed to get scheduled events")
                return False, None
            
            events = events_data.get("collection", [])
            
            # Check each event for the email
            for event in events:
                event_uuid = event.get("uri", "").split("/")[-1]
                event_type_uri = event.get('event_type', '')
                event_type_uuid = event_type_uri.split('/')[-1] if '/' in event_type_uri else ''
                
                if not event_uuid:
                    continue
                
                # Only check our specific events
                if event_type_uuid not in [MASTERMIND_EVENT_UUID, GAMEPLAN_EVENT_UUID]:
                    continue
                
                # Get invitees for this event
                invitees_data = self.get_event_invitees(event_uuid)
                if not invitees_data:
                    continue
                
                invitees = invitees_data.get("collection", [])
                
                # Check if email matches any invitee
                for invitee in invitees:
                    invitee_email = invitee.get("email", "").lower()
                    status = invitee.get("status", "unknown")
                    
                    if invitee_email == email and status == "active":
                        # Determine event type
                        event_type = None
                        if event_type_uuid == MASTERMIND_EVENT_UUID:
                            event_type = "mastermind"
                        elif event_type_uuid == GAMEPLAN_EVENT_UUID:
                            event_type = "gameplan"
                        
                        if event_type:
                            return True, event_type
            
            return False, None
            
        except CalendlyAPIError as e:
            logging.error(f"Calendly API error: {e}")
            return False, None
        except Exception as e:
            logging.error(f"Unexpected error checking booking for {email}: {e}")
            return False, None
    
    def get_booking_details(self, email: str) -> Optional[Dict]:
        """
        Get detailed booking information for an email
        
        Args:
            email (str): Email address to check
            
        Returns:
            Dict with booking details or None if not found
        """
        if not email or '@' not in email:
            return None
        
        email = email.lower().strip()
        
        try:
            user_uri = self._get_user_uri()
            if not user_uri:
                return None
            
            events_data = self.get_scheduled_events(user_uri, count=50)
            if not events_data:
                return None
            
            events = events_data.get("collection", [])
            
            for event in events:
                event_uuid = event.get("uri", "").split("/")[-1]
                event_type_uri = event.get('event_type', '')
                event_type_uuid = event_type_uri.split('/')[-1] if '/' in event_type_uri else ''
                
                invitees_data = self.get_event_invitees(event_uuid)
                if not invitees_data:
                    continue
                
                invitees = invitees_data.get("collection", [])
                
                for invitee in invitees:
                    invitee_email = invitee.get("email", "").lower()
                    status = invitee.get("status", "unknown")
                    
                    if invitee_email == email and status == "active":
                        # Determine event type
                        event_type = None
                        if event_type_uuid == MASTERMIND_EVENT_UUID:
                            event_type = "mastermind"
                        elif event_type_uuid == GAMEPLAN_EVENT_UUID:
                            event_type = "gameplan"
                        
                        return {
                            'email': email,
                            'event_uuid': event_uuid,
                            'event_type': event_type,
                            'event_type_uuid': event_type_uuid,
                            'status': status,
                            'event_name': event.get('name', 'Unknown'),
                            'start_time': event.get('start_time'),
                            'end_time': event.get('end_time'),
                            'invitee_name': invitee.get('name', 'Unknown'),
                            'invitee_uri': invitee.get('uri')
                        }
            
            return None
            
        except Exception as e:
            logging.error(f"Error getting booking details for {email}: {e}")
            return None
    
    def test_connection(self) -> bool:
        """Test Calendly API connection"""
        try:
            user_info = self.get_user_info()
            if user_info and 'resource' in user_info:
                user_name = user_info['resource'].get('name', 'Unknown')
                logging.info(f"✅ Calendly connection successful - User: {user_name}")
                return True
            else:
                logging.error("❌ Failed to get user info")
                return False
        except Exception as e:
            logging.error(f"❌ Calendly connection failed: {e}")
            return False

# Global instance
_calendly_checker = None

def get_calendly_checker() -> CalendlyBookingChecker:
    """Get or create the global Calendly checker instance"""
    global _calendly_checker
    if _calendly_checker is None:
        _calendly_checker = CalendlyBookingChecker()
    return _calendly_checker

def check_email_booked(email: str) -> Tuple[bool, Optional[str]]:
    """
    Check if an email has booked a call (main function)
    
    Args:
        email (str): Email address to check
        
    Returns:
        Tuple[bool, Optional[str]]: (has_booked, event_type)
    """
    checker = get_calendly_checker()
    return checker.check_email_booking(email)

def get_booking_details(email: str) -> Optional[Dict]:
    """
    Get detailed booking information for an email
    
    Args:
        email (str): Email address to check
        
    Returns:
        Dict with booking details or None if not found
    """
    checker = get_calendly_checker()
    return checker.get_booking_details(email)

def test_calendly_connection() -> bool:
    """Test Calendly API connection"""
    checker = get_calendly_checker()
    return checker.test_connection()

def clear_cache():
    """Clear API cache"""
    global _api_cache, _cache_timestamps
    _api_cache.clear()
    _cache_timestamps.clear()
    logging.info("Calendly API cache cleared")

# Legacy function for backward compatibility
def check_email_booked_specific_events(email: str) -> Tuple[bool, Optional[str]]:
    """Legacy function - same as check_email_booked"""
    return check_email_booked(email)

# Calendly main (commented out – re-enable when using Calendly)
# if __name__ == "__main__":
#     print("🧪 Testing Calendly Connection...")
#     if test_calendly_connection():
#         print("✅ Connection successful!")
#         test_email = "suspiciouscarson3@justzeus.com"
#         print(f"\n📧 Testing booking for: {test_email}")
#         has_booked, event_type = check_email_booked(test_email)
#         if has_booked:
#             print(f"✅ Booking found! Event type: {event_type}")
#             details = get_booking_details(test_email)
#             if details:
#                 print(f"📋 Booking details: Event: {details.get('event_name')} Type: {details.get('event_type')}")
#         else:
#             print("❌ No booking found")
#     else:
#         print("❌ Connection failed!")
