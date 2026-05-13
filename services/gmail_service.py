"""
Gmail API Service for TapHoa39BackEnd.
Ported from SongMinhQuanLyGmail, adapted for Flask.
Reads Gmail tokens from shared Firestore (quanlysongminh project).
"""

import os
import base64
import re
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta

from google.oauth2.credentials import Credentials
from google.auth.exceptions import RefreshError
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


class GmailTokenExpiredError(Exception):
    """Raised when Gmail access token is expired and cannot be refreshed."""
    pass


class GmailService:
    """
    Gmail API wrapper for reading invoice emails.

    Usage:
        gmail = GmailService(access_token, refresh_token)
        labels = gmail.list_labels()
        messages = gmail.list_messages(days_back=2, label_ids=[label_id])
        metadata = gmail.get_message_metadata(msg_id)
    """

    SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']

    def __init__(self, access_token: str, refresh_token: Optional[str] = None):
        self.credentials = Credentials(
            token=access_token,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=os.environ.get("GOOGLE_CLIENT_ID", ""),
            client_secret=os.environ.get("GOOGLE_CLIENT_SECRET", ""),
            scopes=self.SCOPES,
        )
        self.service = build('gmail', 'v1', credentials=self.credentials)

    def list_labels(self) -> List[Dict[str, Any]]:
        """List user-created Gmail labels."""
        try:
            response = self.service.users().labels().list(userId='me').execute()
            labels = response.get('labels', [])
            user_labels = [
                {'id': l.get('id'), 'name': l.get('name'), 'type': l.get('type')}
                for l in labels if l.get('type') == 'user'
            ]
            user_labels.sort(key=lambda x: x['name'].lower())
            return user_labels
        except RefreshError as error:
            raise GmailTokenExpiredError(f"Gmail token hết hạn. Vui lòng đăng nhập lại. ({error})")
        except HttpError as error:
            if error.resp.status == 401:
                raise GmailTokenExpiredError("Gmail token hết hạn. Vui lòng đăng nhập lại.")
            print(f"Gmail API error listing labels: {error}")
            raise

    def list_messages(
        self,
        days_back: int = 2,
        max_results: int = 50,
        query: Optional[str] = None,
        label_ids: Optional[List[str]] = None
    ) -> List[Dict[str, str]]:
        """List message stubs from Gmail with optional label and date filters."""
        after_date = datetime.now() - timedelta(days=days_back)
        full_query = f"after:{after_date.strftime('%Y/%m/%d')}"
        if query:
            full_query = f"{full_query} {query}"

        messages = []
        page_token = None

        try:
            while len(messages) < max_results:
                params = {
                    'userId': 'me',
                    'q': full_query,
                    'maxResults': min(max_results - len(messages), 100),
                }
                if page_token:
                    params['pageToken'] = page_token
                if label_ids:
                    params['labelIds'] = label_ids

                response = self.service.users().messages().list(**params).execute()
                if 'messages' in response:
                    messages.extend(response['messages'])

                page_token = response.get('nextPageToken')
                if not page_token:
                    break
        except RefreshError as error:
            raise GmailTokenExpiredError(f"Gmail token hết hạn. Vui lòng đăng nhập lại. ({error})")
        except HttpError as error:
            if error.resp.status == 401:
                raise GmailTokenExpiredError("Gmail token hết hạn. Vui lòng đăng nhập lại.")
            print(f"Gmail API error listing messages: {error}")
            raise

        return messages[:max_results]

    def get_message_metadata(self, message_id: str) -> Optional[Dict[str, Any]]:
        """Get email metadata: from, subject, date, snippet, attachment filenames."""
        try:
            message = self.service.users().messages().get(
                userId='me', id=message_id, format='full'
            ).execute()

            headers = {h['name']: h['value'] for h in message.get('payload', {}).get('headers', [])}
            from_raw = headers.get('From', '')
            from_email = self._extract_email(from_raw)

            return {
                'gmail_id': message_id,
                'from_address': from_email,
                'from_domain': self._extract_domain(from_email),
                'subject': headers.get('Subject', ''),
                'date': self._parse_date(headers.get('Date', '')).isoformat(),
                'snippet': message.get('snippet', ''),
                'attachments': self._extract_attachments(message),
                'internal_date': int(message.get('internalDate', 0)),
            }
        except HttpError as error:
            print(f"Error fetching message {message_id}: {error}")
            return None

    def get_xml_attachment(self, message_id: str) -> Optional[bytes]:
        """Download first XML attachment from a message."""
        return self._get_attachment_by_ext(message_id, '.xml', 'xml')

    def get_pdf_attachment(self, message_id: str) -> Optional[tuple]:
        """Download first PDF attachment. Returns (bytes, filename) or None."""
        return self._get_attachment_by_ext(message_id, '.pdf', 'application/pdf', return_filename=True)

    def get_zip_attachment(self, message_id: str) -> Optional[tuple]:
        """Download first ZIP attachment. Returns (bytes, filename) or None."""
        return self._get_attachment_by_ext(message_id, '.zip', 'application/zip', return_filename=True)

    def _get_attachment_by_ext(
        self, message_id: str, ext: str, mime_hint: str, return_filename: bool = False
    ) -> Optional[Any]:
        """Generic attachment downloader by file extension."""
        try:
            message = self.service.users().messages().get(
                userId='me', id=message_id, format='full'
            ).execute()

            def find_part(parts: List[Dict]) -> Optional[Dict]:
                for part in parts:
                    filename = part.get('filename', '').lower()
                    mime_type = part.get('mimeType', '').lower()
                    if filename.endswith(ext) or mime_hint in mime_type:
                        return part
                    if 'parts' in part:
                        result = find_part(part['parts'])
                        if result:
                            return result
                return None

            payload = message.get('payload', {})
            target_part = find_part(payload.get('parts', []))

            if not target_part:
                return None

            filename = target_part.get('filename', f'attachment{ext}')
            attachment_id = target_part.get('body', {}).get('attachmentId')

            if attachment_id:
                attachment = self.service.users().messages().attachments().get(
                    userId='me', messageId=message_id, id=attachment_id
                ).execute()
                data = base64.urlsafe_b64decode(attachment.get('data', ''))
            else:
                raw = target_part.get('body', {}).get('data', '')
                data = base64.urlsafe_b64decode(raw) if raw else None

            if not data:
                return None

            if return_filename:
                return (data, filename)
            return data

        except HttpError as error:
            print(f"Error getting {ext} attachment from {message_id}: {error}")
            return None

    def get_email_body_html(self, message_id: str) -> Optional[str]:
        """Get email body as HTML string."""
        try:
            message = self.service.users().messages().get(
                userId='me', id=message_id, format='full'
            ).execute()

            payload = message.get('payload', {})
            return self._extract_body_html(payload)

        except HttpError as error:
            print(f"Error getting email body for {message_id}: {error}")
            return None

    def _extract_body_html(self, payload: Dict) -> Optional[str]:
        """Recursively extract HTML body from email payload."""
        mime_type = payload.get('mimeType', '')

        # Direct HTML body
        if mime_type == 'text/html':
            data = payload.get('body', {}).get('data', '')
            if data:
                return base64.urlsafe_b64decode(data).decode('utf-8', errors='replace')

        # Multipart: search parts recursively
        parts = payload.get('parts', [])
        for part in parts:
            part_mime = part.get('mimeType', '')
            if part_mime == 'text/html':
                data = part.get('body', {}).get('data', '')
                if data:
                    return base64.urlsafe_b64decode(data).decode('utf-8', errors='replace')
            if 'parts' in part:
                result = self._extract_body_html(part)
                if result:
                    return result

        # Fallback: plain text
        for part in parts:
            if part.get('mimeType') == 'text/plain':
                data = part.get('body', {}).get('data', '')
                if data:
                    return base64.urlsafe_b64decode(data).decode('utf-8', errors='replace')

        return None

    # --- helpers ---

    def _extract_email(self, from_header: str) -> str:
        match = re.search(r'<([^>]+)>', from_header)
        if match:
            return match.group(1).lower()
        match = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', from_header)
        return match.group(0).lower() if match else from_header.lower()

    def _extract_domain(self, email: str) -> str:
        parts = email.split('@')
        return parts[1] if len(parts) > 1 else ''

    def _parse_date(self, date_str: str) -> datetime:
        from email.utils import parsedate_to_datetime
        try:
            return parsedate_to_datetime(date_str)
        except Exception:
            return datetime.now()

    def _extract_attachments(self, message: Dict) -> List[str]:
        filenames = []

        def extract(parts):
            for part in parts:
                fn = part.get('filename', '')
                if fn:
                    filenames.append(fn)
                if 'parts' in part:
                    extract(part['parts'])

        payload = message.get('payload', {})
        if 'parts' in payload:
            extract(payload['parts'])
        return filenames