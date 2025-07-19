import requests
import os
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional

# Cache for Calendly bookings to reduce API calls
_booking_cache = {}
_cache_duration = timedelta(minutes=5)  # Cache for 5 minutes

def _is_cache_valid(cache_time: datetime) -> bool:
    """Check if cache entry is still valid"""
    return datetime.now() - cache_time < _cache_duration

def check_email_booked(email_to_check: str, user_uuid: Optional[str] = None, token: Optional[str] = None) -> bool:
    """
    Check if an email has booked a call in Calendly with caching
    
    Args:
        email_to_check (str): Email address to check
        user_uuid (str): Calendly user UUID (optional, will use env var if not provided)
        token (str): Calendly API token (optional, will use env var if not provided)
    
    Returns:
        bool: True if booking found, False otherwise
    """
    # Normalize email for cache key
    email_key = email_to_check.lower().strip()
    
    # Check cache first
    if email_key in _booking_cache:
        cache_entry = _booking_cache[email_key]
        if _is_cache_valid(cache_entry['timestamp']):
            logging.info(f"Using cached result for {email_to_check}: {cache_entry['result']}")
            return cache_entry['result']
        else:
            # Remove expired cache entry
            del _booking_cache[email_key]
    
    # Get credentials from environment variables if not provided
    if not user_uuid:
        user_uuid = os.getenv('CALENDLY_USER_UUID', '2ae4f947-d7f5-4610-93cf-fc67ff729342')
    if not token:
        token = os.getenv('CALENDLY_TOKEN', 'eyJraWQiOiIxY2UxZTEzNjE3ZGNmNzY2YjNjZWJjY2Y4ZGM1YmFmYThhNjVlNjg0MDIzZjdjMzJiZTgzNDliMjM4MDEzNWI0IiwidHlwIjoiUEFUIiwiYWxnIjoiRVMyNTYifQ.eyJpc3MiOiJodHRwczovL2F1dGguY2FsZW5kbHkuY29tIiwiaWF0IjoxNzUyNzY4MDI1LCJqdGkiOiIyY2Q4MjQ5OS0wNmI3LTRjM2QtYmI3MS01MDMxZWFkZTRiYjYiLCJ1c2VyX3V1aWQiOiIyYWU0Zjk0Ny1kN2Y1LTQ2MTAtOTNjZi1mYzY3ZmY3MjkzNDIifQ.-Ff2-NjGkvV6f9eSEbMT6qoRDIlactRzPFGa9r8ooW3AmYHZvMCxpSd4apwZodBx45HBMshq98Bt0f8tv6cVbQ')
    
    if not user_uuid or not token:
        logging.error("Missing Calendly credentials")
        return False
    
    try:
        # 1. Get all scheduled events for the user
        events_url = "https://api.calendly.com/scheduled_events"
        user_url = f"https://api.calendly.com/users/{user_uuid}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        params = {
            "user": user_url,
            "count": 100,  # max per page
            "status": "active"  # Only check active events
        }
        
        response = requests.get(events_url, headers=headers, params=params, timeout=5)  # Reduced timeout
        if response.status_code != 200:
            logging.error(f"Error fetching events: {response.status_code} - {response.text}")
            return False

        events = response.json().get("collection", [])
        logging.info(f"Found {len(events)} active events to check for email: {email_to_check}")
        
        # Limit to recent events to speed up checking
        recent_events = events[:10]  # Only check last 10 events
        
        for event in recent_events:
            event_uuid = event["uri"].split("/")[-1]
            # 2. For each event, get invitees
            invitees_url = f"https://api.calendly.com/scheduled_events/{event_uuid}/invitees"
            invitees_resp = requests.get(invitees_url, headers=headers, timeout=5)  # Reduced timeout
            if invitees_resp.status_code != 200:
                logging.warning(f"Error fetching invitees for event {event_uuid}: {invitees_resp.status_code}")
                continue
                
            invitees = invitees_resp.json().get("collection", [])
            for invitee in invitees:
                invitee_email = invitee.get("email", "").lower()
                if invitee_email == email_key:
                    logging.info(f"Found booking for {email_to_check} in event {event_uuid}")
                    # Cache the positive result
                    _booking_cache[email_key] = {
                        'result': True,
                        'timestamp': datetime.now()
                    }
                    return True
                    
        logging.info(f"No booking found for {email_to_check}")
        # Cache the negative result
        _booking_cache[email_key] = {
            'result': False,
            'timestamp': datetime.now()
        }
        return False
        
    except requests.exceptions.Timeout:
        logging.error(f"Timeout checking Calendly booking for {email_to_check}")
        return False
    except requests.exceptions.RequestException as e:
        logging.error(f"Request error checking Calendly booking for {email_to_check}: {e}")
        return False
    except Exception as e:
        logging.error(f"Unexpected error checking Calendly booking for {email_to_check}: {e}")
        return False

def clear_booking_cache():
    """Clear the booking cache"""
    global _booking_cache
    _booking_cache.clear()
    logging.info("Calendly booking cache cleared")

def get_cache_stats():
    """Get cache statistics"""
    valid_entries = sum(1 for entry in _booking_cache.values() if _is_cache_valid(entry['timestamp']))
    total_entries = len(_booking_cache)
    return {
        'total_entries': total_entries,
        'valid_entries': valid_entries,
        'expired_entries': total_entries - valid_entries
    }

def calendly_get_user_info(user_uuid=None, token=None):
    """Get Calendly user information"""
    if not user_uuid:
        user_uuid = os.getenv('CALENDLY_USER_UUID', '2ae4f947-d7f5-4610-93cf-fc67ff729342')
    if not token:
        token = os.getenv('CALENDLY_TOKEN', 'eyJraWQiOiIxY2UxZTEzNjE3ZGNmNzY2YjNjZWJjY2Y4ZGM1YmFmYThhNjVlNjg0MDIzZjdjMzJiZTgzNDliMjM4MDEzNWI0IiwidHlwIjoiUEFUIiwiYWxnIjoiRVMyNTYifQ.eyJpc3MiOiJodHRwczovL2F1dGguY2FsZW5kbHkuY29tIiwiaWF0IjoxNzUyNzY4MDI1LCJqdGkiOiIyY2Q4MjQ5OS0wNmI3LTRjM2QtYmI3MS01MDMxZWFkZTRiYjYiLCJ1c2VyX3V1aWQiOiIyYWU0Zjk0Ny1kN2Y1LTQ2MTAtOTNjZi1mYzY3ZmY3MjkzNDIifQ.-Ff2-NjGkvV6f9eSEbMT6qoRDIlactRzPFGa9r8ooW3AmYHZvMCxpSd4apwZodBx45HBMshq98Bt0f8tv6cVbQ')
    
    url = "https://api.calendly.com/users/me"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}"
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=5)  # Reduced timeout
        if response.status_code == 200:
            return response.json()
        else:
            logging.error(f"Error getting user info: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        logging.error(f"Error getting Calendly user info: {e}")
        return None

def calendly_get_event_types(user_uuid=None, token=None):
    """Get Calendly event types"""
    if not user_uuid:
        user_uuid = os.getenv('CALENDLY_USER_UUID', '2ae4f947-d7f5-4610-93cf-fc67ff729342')
    if not token:
        token = os.getenv('CALENDLY_TOKEN', 'eyJraWQiOiIxY2UxZTEzNjE3ZGNmNzY2YjNjZWJjY2Y4ZGM1YmFmYThhNjVlNjg0MDIzZjdjMzJiZTgzNDliMjM4MDEzNWI0IiwidHlwIjoiUEFUIiwiYWxnIjoiRVMyNTYifQ.eyJpc3MiOiJodHRwczovL2F1dGguY2FsZW5kbHkuY29tIiwiaWF0IjoxNzUyNzY4MDI1LCJqdGkiOiIyY2Q4MjQ5OS0wNmI3LTRjM2QtYmI3MS01MDMxZWFkZTRiYjYiLCJ1c2VyX3V1aWQiOiIyYWU0Zjk0Ny1kN2Y1LTQ2MTAtOTNjZi1mYzY3ZmY3MjkzNDIifQ.-Ff2-NjGkvV6f9eSEbMT6qoRDIlactRzPFGa9r8ooW3AmYHZvMCxpSd4apwZodBx45HBMshq98Bt0f8tv6cVbQ')
    
    url = "https://api.calendly.com/event_types"
    user_url = f"https://api.calendly.com/users/{user_uuid}"
    params = {"user": user_url}
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}"
    }
    
    try:
        response = requests.get(url, headers=headers, params=params, timeout=5)  # Reduced timeout
        if response.status_code == 200:
            return response.json()
        else:
            logging.error(f"Error getting event types: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        logging.error(f"Error getting Calendly event types: {e}")
        return None

if __name__ == "__main__":
    # Test the functions
    user_uuid = "2ae4f947-d7f5-4610-93cf-fc67ff729342"
    token = "eyJraWQiOiIxY2UxZTEzNjE3ZGNmNzY2YjNjZWJjY2Y4ZGM1YmFmYThhNjVlNjg0MDIzZjdjMzJiZTgzNDliMjM4MDEzNWI0IiwidHlwIjoiUEFUIiwiYWxnIjoiRVMyNTYifQ.eyJpc3MiOiJodHRwczovL2F1dGguY2FsZW5kbHkuY29tIiwiaWF0IjoxNzUyNzY4MDI1LCJqdGkiOiIyY2Q4MjQ5OS0wNmI3LTRjM2QtYmI3MS01MDMxZWFkZTRiYjYiLCJ1c2VyX3V1aWQiOiIyYWU0Zjk0Ny1kN2Y1LTQ2MTAtOTNjZi1mYzY3ZmY3MjkzNDIifQ.-Ff2-NjGkvV6f9eSEbMT6qoRDIlactRzPFGa9r8ooW3AmYHZvMCxpSd4apwZodBx45HBMshq98Bt0f8tv6cVbQ"
    email = "mjsistoxic53@gmail.com"

    print("Testing Calendly integration...")
    print(f"Checking booking for: {email}")
    
    result = check_email_booked(email, user_uuid, token)
    print(f"Booking found: {result}")
    
    # Test cache
    print("\nTesting cache...")
    result2 = check_email_booked(email, user_uuid, token)
    print(f"Cached result: {result2}")
    
    print("\nCache stats:")
    stats = get_cache_stats()
    print(f"Total entries: {stats['total_entries']}")
    print(f"Valid entries: {stats['valid_entries']}")
    print(f"Expired entries: {stats['expired_entries']}")
    
    print("\nGetting user info...")
    user_info = calendly_get_user_info(user_uuid, token)
    if user_info:
        print("User info retrieved successfully")
    
    print("\nGetting event types...")
    event_types = calendly_get_event_types(user_uuid, token)
    if event_types:
        print("Event types retrieved successfully")
