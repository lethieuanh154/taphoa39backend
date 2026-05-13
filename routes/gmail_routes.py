"""
Gmail API routes for invoice email processing.
Reads Gmail tokens from Firestore (Auth project).
Supports server-side OAuth2 flow for refresh_token.
"""

import os
import base64
from flask import Blueprint, request, jsonify, redirect
from firebase.init_firebase import init_firestore
from services.gmail_service import GmailService, GmailTokenExpiredError
from services.zip_extractor import extract_xml_from_zip, extract_pdf_from_zip
from services.invoice_parsers import TaxInvoiceXMLParser
from services.email_body_parser import EmailBodyParser
from google_auth_oauthlib.flow import Flow


GMAIL_SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']

# Store PKCE code_verifier between auth_url and callback requests
# Key: uid (state param), Value: code_verifier string
_pending_code_verifiers = {}


def _get_user_db():
    """Get Firestore client for the Gmail/quanlysongminh project."""
    return init_firestore("FIREBASE_SERVICE_ACCOUNT_GMAIL", app_name="gmail_app")


def _get_gmail_service(uid: str) -> GmailService:
    """Create GmailService from Firestore-stored tokens for given user.
    After API calls, if token was refreshed, save new access_token back."""
    db = _get_user_db()
    user_doc = db.collection('users').document(uid).get()

    if not user_doc.exists:
        raise ValueError(f"User {uid} not found in Firestore")

    user_data = user_doc.to_dict()
    tokens = user_data.get('gmailTokens', {})

    if not tokens.get('accessToken') and not tokens.get('refreshToken'):
        raise ValueError(f"No Gmail tokens found for user {uid}. Please link your Gmail account.")

    access_token = tokens.get('accessToken', '')
    refresh_token = tokens.get('refreshToken')

    print(f"🔍 [Gmail] uid={uid}, hasAccessToken={bool(access_token)}, hasRefreshToken={bool(refresh_token)}, "
          f"accessTokenLen={len(access_token) if access_token else 0}, "
          f"refreshTokenLen={len(refresh_token) if refresh_token else 0}")

    gmail = GmailService(
        access_token=access_token,
        refresh_token=refresh_token
    )

    # Store uid and db reference for post-call token update
    gmail._uid = uid
    gmail._db = db
    gmail._original_token = access_token

    return gmail


def _save_refreshed_token(gmail: GmailService):
    """If the access_token was refreshed by google-auth, save it back to Firestore."""
    try:
        new_token = gmail.credentials.token
        if new_token and hasattr(gmail, '_original_token') and new_token != gmail._original_token:
            gmail._db.collection('users').document(gmail._uid).set(
                {'gmailTokens': {'accessToken': new_token}},
                merge=True
            )
    except Exception as e:
        print(f"Warning: Failed to save refreshed token: {e}")


def _get_oauth_flow(redirect_uri: str) -> Flow:
    """Create Google OAuth2 flow for Gmail scope."""
    client_config = {
        "web": {
            "client_id": os.environ.get("GOOGLE_CLIENT_ID", ""),
            "client_secret": os.environ.get("GOOGLE_CLIENT_SECRET", ""),
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [redirect_uri]
        }
    }
    flow = Flow.from_client_config(client_config, scopes=GMAIL_SCOPES)
    flow.redirect_uri = redirect_uri
    return flow


def create_gmail_routes_bp():
    bp = Blueprint('gmail_routes', __name__, url_prefix='/api/gmail')

    @bp.route('/health', methods=['GET'])
    def health_check():
        """Check Gmail service configuration and Firestore connection."""
        try:
            db = _get_user_db()
            return jsonify({
                'status': 'healthy',
                'project_id': db.project,
                'service': 'gmail_routes'
            })
        except Exception as e:
            return jsonify({'status': 'error', 'error': str(e)}), 500

    # =========================================================
    # OAuth2 Server-Side Flow (gets refresh_token)
    # =========================================================

    @bp.route('/auth/url', methods=['GET'])
    def get_auth_url():
        """
        GET /api/gmail/auth/url?uid=xxx
        Returns Google OAuth2 authorization URL.
        User opens this URL to grant Gmail access with refresh_token.
        """
        uid = request.args.get('uid')
        login_hint = request.args.get('login_hint', '')
        if not uid:
            return jsonify({'success': False, 'error': 'uid is required'}), 400

        redirect_uri = request.host_url.rstrip('/') + '/api/gmail/auth/callback'
        flow = _get_oauth_flow(redirect_uri)

        auth_kwargs = {
            'access_type': 'offline',
            'prompt': 'consent',
            'state': uid
        }
        if login_hint:
            auth_kwargs['login_hint'] = login_hint

        auth_url, _ = flow.authorization_url(**auth_kwargs)

        # Save PKCE code_verifier for callback (flow object is lost between requests)
        if hasattr(flow, 'code_verifier') and flow.code_verifier:
            _pending_code_verifiers[uid] = flow.code_verifier

        return jsonify({'success': True, 'url': auth_url})

    @bp.route('/auth/callback', methods=['GET'])
    def auth_callback():
        """
        GET /api/gmail/auth/callback?code=xxx&state=uid
        Google redirects here after user consents.
        Exchanges code for access_token + refresh_token, saves to Firestore.
        Returns HTML that closes the popup window.
        """
        code = request.args.get('code')
        uid = request.args.get('state')
        error = request.args.get('error')

        if error:
            return f"""<html><body>
                <h3>Lỗi: {error}</h3>
                <script>window.close();</script>
            </body></html>"""

        if not code or not uid:
            return jsonify({'success': False, 'error': 'Missing code or state'}), 400

        try:
            redirect_uri = request.host_url.rstrip('/') + '/api/gmail/auth/callback'
            flow = _get_oauth_flow(redirect_uri)

            # Restore PKCE code_verifier from auth_url request
            saved_verifier = _pending_code_verifiers.pop(uid, None)
            if saved_verifier:
                flow.code_verifier = saved_verifier

            flow.fetch_token(code=code)

            credentials = flow.credentials
            tokens = {
                'accessToken': credentials.token,
                'refreshToken': credentials.refresh_token,
            }

            # Save to Firestore
            db = _get_user_db()
            db.collection('users').document(uid).set({'gmailTokens': tokens}, merge=True)

            # Return HTML that notifies opener and closes popup
            return """<html><body>
                <h3 style="font-family:sans-serif;color:#4CAF50;">
                    Gmail connected successfully!
                </h3>
                <p style="font-family:sans-serif;">This window will close automatically...</p>
                <script>
                    if (window.opener) {
                        window.opener.postMessage({ type: 'GMAIL_AUTH_SUCCESS' }, '*');
                    }
                    setTimeout(() => window.close(), 1500);
                </script>
            </body></html>"""

        except Exception as e:
            print(f"OAuth callback error: {e}")
            return f"""<html><body>
                <h3 style="font-family:sans-serif;color:red;">Lỗi: {e}</h3>
                <script>setTimeout(() => window.close(), 3000);</script>
            </body></html>"""

    @bp.route('/auth/save', methods=['POST'])
    def save_gmail_tokens():
        """
        POST /api/gmail/auth/save
        Body: { "uid": "...", "tokens": { "accessToken": "...", "refreshToken": "..." } }
        Save Gmail tokens for the user after frontend OAuth flow.
        """
        try:
            data = request.get_json()
            uid = data.get('uid')
            tokens = data.get('tokens')

            if not uid or not tokens:
                return jsonify({'success': False, 'error': 'Missing uid or tokens'}), 400

            db = _get_user_db()
            # Merge tokens - don't overwrite refreshToken if not provided
            existing_doc = db.collection('users').document(uid).get()
            if existing_doc.exists:
                existing_tokens = existing_doc.to_dict().get('gmailTokens', {})
                if not tokens.get('refreshToken') and existing_tokens.get('refreshToken'):
                    tokens['refreshToken'] = existing_tokens['refreshToken']

            db.collection('users').document(uid).set({'gmailTokens': tokens}, merge=True)
            return jsonify({'success': True, 'message': 'Tokens saved successfully'})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500

    @bp.route('/auth/status', methods=['GET'])
    def auth_status():
        """
        GET /api/gmail/auth/status?uid=xxx
        Check if user has valid Gmail tokens (especially refresh_token).
        """
        uid = request.args.get('uid')
        if not uid:
            return jsonify({'success': False, 'error': 'uid is required'}), 400

        try:
            db = _get_user_db()
            user_doc = db.collection('users').document(uid).get()

            if not user_doc.exists:
                return jsonify({'success': True, 'hasTokens': False, 'hasRefreshToken': False})

            tokens = user_doc.to_dict().get('gmailTokens', {})
            return jsonify({
                'success': True,
                'hasTokens': bool(tokens.get('accessToken')),
                'hasRefreshToken': bool(tokens.get('refreshToken'))
            })
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500

    # =========================================================
    # Gmail API endpoints
    # =========================================================

    @bp.route('/labels', methods=['GET'])
    def get_labels():
        """GET /api/gmail/labels?uid=xxx - List Gmail labels."""
        uid = request.args.get('uid')
        if not uid:
            return jsonify({'success': False, 'error': 'uid is required'}), 400

        try:
            gmail = _get_gmail_service(uid)
            labels = gmail.list_labels()
            _save_refreshed_token(gmail)
            return jsonify({'success': True, 'labels': labels})
        except GmailTokenExpiredError as e:
            print(f"❌ [Gmail labels] TOKEN_EXPIRED for uid={uid}: {e}")
            return jsonify({'success': False, 'error': str(e), 'code': 'TOKEN_EXPIRED'}), 401
        except ValueError as e:
            print(f"❌ [Gmail labels] ValueError for uid={uid}: {e}")
            if "not found in Firestore" in str(e):
                return jsonify({'success': False, 'error': str(e)}), 404
            else:
                return jsonify({'success': False, 'error': str(e)}), 409
        except Exception as e:
            print(f"❌ [Gmail labels] Unexpected error for uid={uid}: {type(e).__name__}: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @bp.route('/emails', methods=['GET'])
    def list_emails():
        """
        GET /api/gmail/emails?uid=xxx&label_id=yyy&days_back=2
        List emails with metadata for the given label and date range.
        """
        uid = request.args.get('uid')
        label_id = request.args.get('label_id')
        days_back = int(request.args.get('days_back', '7'))

        if not uid:
            return jsonify({'success': False, 'error': 'uid is required'}), 400

        try:
            gmail = _get_gmail_service(uid)

            label_ids = [label_id] if label_id else None
            message_stubs = gmail.list_messages(
                days_back=days_back,
                max_results=50,
                label_ids=label_ids
            )

            # Fetch metadata for each message
            emails = []
            for stub in message_stubs:
                metadata = gmail.get_message_metadata(stub['id'])
                if metadata:
                    emails.append(metadata)

            _save_refreshed_token(gmail)
            return jsonify({'success': True, 'emails': emails, 'total': len(emails)})
        except GmailTokenExpiredError as e:
            return jsonify({'success': False, 'error': str(e), 'code': 'TOKEN_EXPIRED'}), 401
        except ValueError as e:
            if "not found in Firestore" in str(e):
                return jsonify({'success': False, 'error': str(e)}), 404
            else:
                return jsonify({'success': False, 'error': str(e)}), 409
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500

    @bp.route('/emails/<email_id>/process', methods=['POST'])
    def process_email(email_id):
        """
        POST /api/gmail/emails/<email_id>/process
        Body: {"uid": "xxx"}

        Auto-detect attachment type and process:
        - XML → parse with TaxInvoiceXMLParser
        - ZIP → extract XML → parse (or extract PDF → return for Gemini)
        - PDF → return base64 for frontend Gemini processing
        - None → return type='none'
        """
        data = request.get_json() or {}
        uid = data.get('uid') or request.args.get('uid')

        if not uid:
            return jsonify({'success': False, 'error': 'uid is required'}), 400

        try:
            gmail = _get_gmail_service(uid)
            metadata = gmail.get_message_metadata(email_id)

            if not metadata:
                _save_refreshed_token(gmail)
                return jsonify({'success': False, 'error': 'Email not found'}), 404

            # Extract portal URL from email body HTML
            portal_info = {}
            try:
                email_body_html = gmail.get_email_body_html(email_id)
                if email_body_html:
                    parser = EmailBodyParser()
                    portal_info = parser.extract_portal_url(email_body_html)
            except Exception as e:
                print(f"Warning: Failed to extract portal URL: {e}")

            attachments = metadata.get('attachments', [])
            attachments_lower = [a.lower() for a in attachments]

            has_xml = any(a.endswith('.xml') for a in attachments_lower)
            has_zip = any(a.endswith('.zip') for a in attachments_lower)
            has_pdf = any(a.endswith('.pdf') for a in attachments_lower)

            # Common portal fields to include in all responses
            portal_fields = {
                'portalUrl': portal_info.get('portalUrl', ''),
                'invoiceProvider': portal_info.get('provider', ''),
                'portalPdfUrl': portal_info.get('portalPdfUrl', ''),
                'portalCredentials': portal_info.get('credentials', {}),
            }

            # Priority 1: Direct XML attachment
            if has_xml:
                xml_bytes = gmail.get_xml_attachment(email_id)
                if xml_bytes:
                    invoices, errors = TaxInvoiceXMLParser.parse(xml_bytes)
                    _save_refreshed_token(gmail)
                    return jsonify({
                        'success': True,
                        'type': 'xml',
                        'invoices': invoices,
                        'parse_errors': errors,
                        'email': metadata,
                        **portal_fields
                    })

            # Priority 2: ZIP → extract XML first, then PDF
            if has_zip:
                zip_result = gmail.get_zip_attachment(email_id)
                if zip_result:
                    zip_bytes, zip_name = zip_result

                    # Try XML from ZIP
                    xml_result = extract_xml_from_zip(zip_bytes)
                    if xml_result:
                        xml_bytes, xml_name = xml_result
                        invoices, errors = TaxInvoiceXMLParser.parse(xml_bytes)
                        _save_refreshed_token(gmail)
                        return jsonify({
                            'success': True,
                            'type': 'zip_xml',
                            'invoices': invoices,
                            'parse_errors': errors,
                            'source_file': xml_name,
                            'email': metadata,
                            **portal_fields
                        })

                    # Try PDF from ZIP
                    pdf_result = extract_pdf_from_zip(zip_bytes)
                    if pdf_result:
                        pdf_bytes, pdf_name = pdf_result
                        pdf_b64 = base64.b64encode(pdf_bytes).decode('utf-8')
                        _save_refreshed_token(gmail)
                        return jsonify({
                            'success': True,
                            'type': 'zip_pdf',
                            'needs_gemini': True,
                            'pdf_base64': pdf_b64,
                            'pdf_filename': pdf_name,
                            'email': metadata,
                            **portal_fields
                        })

            # Priority 3: Direct PDF attachment
            if has_pdf:
                pdf_result = gmail.get_pdf_attachment(email_id)
                if pdf_result:
                    pdf_bytes, pdf_name = pdf_result
                    pdf_b64 = base64.b64encode(pdf_bytes).decode('utf-8')
                    _save_refreshed_token(gmail)
                    return jsonify({
                        'success': True,
                        'type': 'pdf',
                        'needs_gemini': True,
                        'pdf_base64': pdf_b64,
                        'pdf_filename': pdf_name,
                        'email': metadata,
                        **portal_fields
                    })

            # No processable attachment
            _save_refreshed_token(gmail)
            return jsonify({
                'success': True,
                'type': 'none',
                'message': 'Không có file đính kèm xử lý được. Vui lòng import XML thủ công.',
                'email': metadata,
                **portal_fields
            })

        except GmailTokenExpiredError as e:
            return jsonify({'success': False, 'error': str(e), 'code': 'TOKEN_EXPIRED'}), 401
        except ValueError as e:
            if "not found in Firestore" in str(e):
                return jsonify({'success': False, 'error': str(e)}), 404
            else:
                return jsonify({'success': False, 'error': str(e)}), 409
        except Exception as e:
            print(f"Error processing email {email_id}: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    return bp
