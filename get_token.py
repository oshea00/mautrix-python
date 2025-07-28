#!/usr/bin/env python3

import asyncio
import json
import sys
from getpass import getpass
from mautrix.api import HTTPAPI
from mautrix.types import UserID


async def get_matrix_token(homeserver: str, username: str, password: str, device_name: str = "chatcli"):
    """Get a Matrix access token using login credentials"""
    
    # Create a temporary API client without token for login
    api = HTTPAPI(homeserver)
    
    try:
        # Prepare login data
        login_data = {
            "type": "m.login.password",
            "user": username,
            "password": password,
            "initial_device_display_name": device_name
        }
        
        # Make login request
        response = await api.request(
            method="POST",
            path="/_matrix/client/r0/login",
            content=login_data
        )
        
        return {
            "access_token": response["access_token"],
            "device_id": response["device_id"],
            "user_id": response["user_id"]
        }
        
    finally:
        # Close the session
        if api.session and not api.session.closed:
            await api.session.close()


async def main():
    if len(sys.argv) < 3:
        print("Usage: python get_token.py <homeserver> <username> [device_name]")
        print("Example: python get_token.py https://matrix.org poolagent")
        print("         python get_token.py https://matrix.org @poolagent:matrix.org myclient")
        sys.exit(1)
    
    homeserver = sys.argv[1]
    username = sys.argv[2]
    device_name = sys.argv[3] if len(sys.argv) > 3 else "chatcli"
    
    # Get password securely
    password = getpass(f"Password for {username}: ")
    
    try:
        print(f"Logging in to {homeserver} as {username}...")
        
        result = await get_matrix_token(homeserver, username, password, device_name)
        
        print("\nLogin successful!")
        print(f"User ID: {result['user_id']}")
        print(f"Device ID: {result['device_id']}")
        print(f"Access Token: {result['access_token']}")
        
        # Save to file for convenience
        token_file = "matrix_token.json"
        with open(token_file, 'w') as f:
            json.dump(result, f, indent=2)
        
        print(f"\nCredentials saved to {token_file}")
        print(f"\nTo use with chatcli:")
        print(f"python3 chatcli.py {homeserver} {result['user_id']} {result['access_token']} {result['device_id']}")
        
    except Exception as e:
        print(f"Login failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())