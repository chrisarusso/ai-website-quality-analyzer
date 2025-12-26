"""Google OAuth2 authentication for Website Quality Agent.

Restricts access to users with @savaslabs.com email addresses.
"""

import secrets
from typing import Optional
from urllib.parse import urlencode

from authlib.integrations.starlette_client import OAuth
from fastapi import HTTPException, Request, status
from fastapi.responses import RedirectResponse
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from starlette.middleware.sessions import SessionMiddleware

from ..config import (
    GOOGLE_CLIENT_ID,
    GOOGLE_CLIENT_SECRET,
    ALLOWED_EMAIL_DOMAIN,
    SESSION_SECRET_KEY,
    API_BASE_URL,
)

# OAuth setup
oauth = OAuth()

oauth.register(
    name='google',
    client_id=GOOGLE_CLIENT_ID,
    client_secret=GOOGLE_CLIENT_SECRET,
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={
        'scope': 'openid email profile',
    },
)

# Session serializer for secure cookies
serializer = URLSafeTimedSerializer(SESSION_SECRET_KEY or secrets.token_hex(32))


def get_current_user(request: Request) -> Optional[dict]:
    """Get the current authenticated user from session.

    Returns user dict with email, name, picture or None if not authenticated.
    """
    user = request.session.get('user')
    return user


def require_auth(request: Request) -> dict:
    """Require authentication, raise 401 if not authenticated.

    For API endpoints that need auth.
    """
    user = get_current_user(request)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Please login at /auth/login",
        )
    return user


def require_auth_or_redirect(request: Request) -> Optional[dict]:
    """Get current user or return None for redirect.

    For HTML pages that should redirect to login.
    """
    return get_current_user(request)


def get_path_prefix():
    """Extract path prefix from API_BASE_URL."""
    from urllib.parse import urlparse
    if API_BASE_URL:
        parsed = urlparse(API_BASE_URL)
        if parsed.path and parsed.path != '/':
            return parsed.path.rstrip('/')
    return ""


async def login(request: Request) -> RedirectResponse:
    """Initiate Google OAuth login flow."""
    # Store the original URL to redirect back after login
    prefix = get_path_prefix()
    next_url = request.query_params.get('next', f'{prefix}/')
    request.session['next_url'] = next_url

    redirect_uri = f"{API_BASE_URL}/auth/callback"
    return await oauth.google.authorize_redirect(request, redirect_uri)


async def callback(request: Request) -> RedirectResponse:
    """Handle Google OAuth callback."""
    try:
        token = await oauth.google.authorize_access_token(request)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"OAuth authentication failed: {str(e)}",
        )

    # Get user info from the ID token
    user_info = token.get('userinfo')
    if not user_info:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not retrieve user information from Google",
        )

    email = user_info.get('email', '')

    # Verify email domain
    if ALLOWED_EMAIL_DOMAIN:
        if not email.endswith(f"@{ALLOWED_EMAIL_DOMAIN}"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access restricted to @{ALLOWED_EMAIL_DOMAIN} users. "
                       f"You signed in as {email}",
            )

    # Store user in session
    request.session['user'] = {
        'email': email,
        'name': user_info.get('name', ''),
        'picture': user_info.get('picture', ''),
    }

    # Redirect to original URL or home
    prefix = get_path_prefix()
    next_url = request.session.pop('next_url', f'{prefix}/')
    return RedirectResponse(url=next_url)


async def logout(request: Request) -> RedirectResponse:
    """Clear session and logout."""
    request.session.clear()
    prefix = get_path_prefix()
    return RedirectResponse(url=f'{prefix}/')


def get_login_url(next_url: str = '/') -> str:
    """Get the login URL with optional next redirect."""
    params = urlencode({'next': next_url})
    return f"/auth/login?{params}"
