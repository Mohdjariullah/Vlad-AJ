# Discord Verification Bot

A simplified Discord bot that handles user verification through Calendly booking checks and automatic role assignment.

## Features

### ✅ DM-Based Verification Flow
1. **Automatic Welcome DM**: When a user joins the server, they automatically receive a welcome DM
2. **Verification Button**: The DM contains a "Start Verification" button
3. **Email Collection**: Clicking the button opens a modal asking for the user's email address
4. **Calendly Integration**: The bot checks if the email has booked specific events in Calendly
5. **Automatic Role Assignment**: Based on the booking type, the appropriate role is assigned

### 📅 Calendly Event Types
- **Mastermind Call** (`d5f0c7b0-7424-4e33-ac47-ed44c8ca2453`) → Assigns `MASTERMIND_ROLE`
- **Game Plan Call** (`fd175687-be69-45f1-964b-52478d350ebb`) → Assigns `GAMEPLAN_ROLE`

## Environment Variables

### Required
- `DISCORD_TOKEN`: Your Discord bot token
- `GUILD_ID`: Your Discord server ID
- `LOGS_CHANNEL_ID`: Channel ID for logging verification events

### Role IDs
- `MASTERMIND_ROLE_ID`: Role ID for users who booked Mastermind calls
- `GAMEPLAN_ROLE_ID`: Role ID for users who booked Game Plan calls
- `UNVERIFIED_ROLE_ID`: Role ID for unverified users (optional)

### Calendly Configuration
- `CALENDLY_USER_UUID`: Your Calendly user UUID
- `CALENDLY_TOKEN`: Your Calendly API token
- `CALENDLY_LINK`: Your Calendly booking link

## How It Works

1. **User Joins Server**: Bot automatically sends welcome DM with verification button
2. **User Clicks Verify**: Modal appears asking for email address
3. **Email Check**: Bot checks Calendly for past bookings with that email
4. **Role Assignment**: 
   - If Mastermind call found → Assign `MASTERMIND_ROLE`
   - If Game Plan call found → Assign `GAMEPLAN_ROLE`
   - If no booking found → Show booking link and ask to try again
5. **Success**: User receives confirmation and DM notification

## Installation

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Set up environment variables in a `.env` file or your system

3. Run the bot:
```bash
python main.py
```

## Security Features

- Rate limiting on verification attempts
- Input validation for email addresses
- Secure logging with sensitive data redaction
- Bypass role system for administrators
- Audit log monitoring

## Logging

All verification events are logged to the configured logs channel, including:
- User joins and leaves
- Verification attempts
- Role assignments
- Errors and failures

## Bypass System

Users with specific bypass roles (configured in `bypass_roles.json`) can skip the verification process entirely.