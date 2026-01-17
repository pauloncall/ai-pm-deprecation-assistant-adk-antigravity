# src/connectors/gdrive_connector.py
import os
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from typing import List
from src.models import BacklogTask

class GDriveConnector:
    SCOPES = ['https://www.googleapis.com/auth/drive.readonly']

    def __init__(self, credentials_path: str = None):
        self.creds = None
        self.service = None
        self.mock_mode = False
        
        if not credentials_path or not os.path.exists(credentials_path):
            print(f"Credentials not found at {credentials_path}. Mock mode enabled.")
            self.mock_mode = True
            return

        # Usual OAuth flow
        # In a real app, this would be more complex (token storage)
        # But for hackathon, we assume credentials_path is provided
        try:
            self.creds = Credentials.from_authorized_user_file(credentials_path, self.SCOPES)
        except Exception:
            if os.path.exists('token.json'):
                self.creds = Credentials.from_authorized_user_file('token.json', self.SCOPES)
            
        if not self.creds or not self.creds.valid:
            if self.creds and self.creds.expired and self.creds.refresh_token:
                self.creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(credentials_path, self.SCOPES)
                self.creds = flow.run_local_server(port=0)
            with open('token.json', 'w') as token:
                token.write(self.creds.to_json())

        self.service = build('drive', 'v3', credentials=self.creds)

    def get_backlog_tasks(self, folder_name: str = None) -> List[BacklogTask]:
        if folder_name is None:
            folder_name = os.getenv("GDRIVE_FOLDER", "Deprecation Notes")
        if self.mock_mode:
            return [
                BacklogTask(title="Deprecate old SSL", description="Remove SSL v2/v3 support", source_file="ssl_notes.txt"),
                BacklogTask(title="New deprecation for email module", description="Deprecate old email formats", source_file="email_notes.txt"),
            ]

        # Search for the folder
        results = self.service.files().list(
            q=f"name = '{folder_name}' and mimeType = 'application/vnd.google-apps.folder'",
            spaces='drive',
            fields='nextPageToken, files(id, name)').execute()
        items = results.get('files', [])

        if not items:
            return []

        folder_id = items[0]['id']
        
        # List files in the folder (Text files OR Google Docs)
        results = self.service.files().list(
            q=f"'{folder_id}' in parents and (mimeType = 'text/plain' or mimeType = 'application/vnd.google-apps.document')",
            fields='nextPageToken, files(id, name, mimeType)').execute()
        files = results.get('files', [])
        
        tasks = []
        for file in files:
            # Get the content of the file
            try:
                if file['mimeType'] == 'application/vnd.google-apps.document':
                    # Google Docs must be exported
                    content = self.service.files().export_media(fileId=file['id'], mimeType='text/plain').execute().decode('utf-8')
                else:
                    # Regular text files
                    content = self.service.files().get_media(fileId=file['id']).execute().decode('utf-8')
                
                tasks.append(BacklogTask(
                    title=file['name'],
                    description=content,
                    source_file=file['name']
                ))
            except Exception as e:
                print(f"Error reading file {file['name']}: {e}")
                continue
            
        return tasks
