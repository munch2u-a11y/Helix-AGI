import os
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    'https://www.googleapis.com/auth/gmail.modify',
    'https://www.googleapis.com/auth/calendar',
    'https://www.googleapis.com/auth/drive',
    'https://www.googleapis.com/auth/tasks',
    'https://www.googleapis.com/auth/contacts'
]

def main():
    creds_path = '~/.config/helix/google_credentials.json'
    token_path = '~/.config/helix/google_token.json'
    
    if not os.path.exists(creds_path):
        print(f"Error: {creds_path} not found.")
        return

    print("Authenticating with Google... A browser window should open.")
    flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
    creds = flow.run_local_server(port=0)
    
    with open(token_path, 'w') as token:
        token.write(creds.to_json())
        
    print(f"\nSuccess! New OAuth token saved to {token_path}")

if __name__ == '__main__':
    main()
