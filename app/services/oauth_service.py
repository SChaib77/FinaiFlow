from typing import Optional, Dict, Any
from authlib.integrations.httpx_client import AsyncOAuth2Client
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import httpx
import structlog

from app.core.config import settings
from app.core.exceptions import AuthenticationError, ExternalServiceError
from app.models.user import User
from app.models.auth import OAuth2Account
from app.models.tenant import Tenant

logger = structlog.get_logger()


class OAuth2Provider:
    """Base OAuth2 provider"""
    
    def __init__(self, client_id: str, client_secret: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self.client = AsyncOAuth2Client(
            client_id=client_id,
            client_secret=client_secret
        )
    
    async def get_authorization_url(self, redirect_uri: str, state: str) -> str:
        """Get authorization URL"""
        raise NotImplementedError
    
    async def exchange_code(self, code: str, redirect_uri: str) -> Dict[str, Any]:
        """Exchange authorization code for tokens"""
        raise NotImplementedError
    
    async def get_user_info(self, access_token: str) -> Dict[str, Any]:
        """Get user information from provider"""
        raise NotImplementedError


class GoogleOAuth2Provider(OAuth2Provider):
    """Google OAuth2 provider"""
    
    def __init__(self):
        super().__init__(
            client_id=settings.GOOGLE_CLIENT_ID,
            client_secret=settings.GOOGLE_CLIENT_SECRET
        )
        self.authorization_endpoint = "https://accounts.google.com/o/oauth2/v2/auth"
        self.token_endpoint = "https://oauth2.googleapis.com/token"
        self.userinfo_endpoint = "https://www.googleapis.com/oauth2/v2/userinfo"
    
    async def get_authorization_url(self, redirect_uri: str, state: str) -> str:
        """Get Google authorization URL"""
        return self.client.create_authorization_url(
            self.authorization_endpoint,
            redirect_uri=redirect_uri,
            scope="openid email profile",
            state=state
        )[0]
    
    async def exchange_code(self, code: str, redirect_uri: str) -> Dict[str, Any]:
        """Exchange code for Google tokens"""
        try:
            token = await self.client.fetch_token(
                self.token_endpoint,
                code=code,
                redirect_uri=redirect_uri
            )
            return token
        except Exception as e:
            logger.error("Google token exchange failed", error=str(e))
            raise ExternalServiceError("Failed to exchange authorization code")
    
    async def get_user_info(self, access_token: str) -> Dict[str, Any]:
        """Get Google user information"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    self.userinfo_endpoint,
                    headers={"Authorization": f"Bearer {access_token}"}
                )
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error("Google user info fetch failed", error=str(e))
            raise ExternalServiceError("Failed to fetch user information")


class GitHubOAuth2Provider(OAuth2Provider):
    """GitHub OAuth2 provider"""
    
    def __init__(self):
        super().__init__(
            client_id=settings.GITHUB_CLIENT_ID,
            client_secret=settings.GITHUB_CLIENT_SECRET
        )
        self.authorization_endpoint = "https://github.com/login/oauth/authorize"
        self.token_endpoint = "https://github.com/login/oauth/access_token"
        self.userinfo_endpoint = "https://api.github.com/user"
    
    async def get_authorization_url(self, redirect_uri: str, state: str) -> str:
        """Get GitHub authorization URL"""
        return self.client.create_authorization_url(
            self.authorization_endpoint,
            redirect_uri=redirect_uri,
            scope="user:email",
            state=state
        )[0]
    
    async def exchange_code(self, code: str, redirect_uri: str) -> Dict[str, Any]:
        """Exchange code for GitHub tokens"""
        try:
            token = await self.client.fetch_token(
                self.token_endpoint,
                code=code,
                redirect_uri=redirect_uri
            )
            return token
        except Exception as e:
            logger.error("GitHub token exchange failed", error=str(e))
            raise ExternalServiceError("Failed to exchange authorization code")
    
    async def get_user_info(self, access_token: str) -> Dict[str, Any]:
        """Get GitHub user information"""
        try:
            async with httpx.AsyncClient() as client:
                # Get user info
                response = await client.get(
                    self.userinfo_endpoint,
                    headers={"Authorization": f"Bearer {access_token}"}
                )
                response.raise_for_status()
                user_data = response.json()
                
                # Get user emails
                email_response = await client.get(
                    "https://api.github.com/user/emails",
                    headers={"Authorization": f"Bearer {access_token}"}
                )
                email_response.raise_for_status()
                emails = email_response.json()
                
                # Find primary email
                primary_email = next(
                    (email['email'] for email in emails if email['primary']),
                    user_data.get('email')
                )
                
                user_data['email'] = primary_email
                return user_data
                
        except Exception as e:
            logger.error("GitHub user info fetch failed", error=str(e))
            raise ExternalServiceError("Failed to fetch user information")


class MicrosoftOAuth2Provider(OAuth2Provider):
    """Microsoft OAuth2 provider"""
    
    def __init__(self):
        super().__init__(
            client_id=settings.MICROSOFT_CLIENT_ID,
            client_secret=settings.MICROSOFT_CLIENT_SECRET
        )
        self.authorization_endpoint = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
        self.token_endpoint = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
        self.userinfo_endpoint = "https://graph.microsoft.com/v1.0/me"
    
    async def get_authorization_url(self, redirect_uri: str, state: str) -> str:
        """Get Microsoft authorization URL"""
        return self.client.create_authorization_url(
            self.authorization_endpoint,
            redirect_uri=redirect_uri,
            scope="openid email profile",
            state=state
        )[0]
    
    async def exchange_code(self, code: str, redirect_uri: str) -> Dict[str, Any]:
        """Exchange code for Microsoft tokens"""
        try:
            token = await self.client.fetch_token(
                self.token_endpoint,
                code=code,
                redirect_uri=redirect_uri
            )
            return token
        except Exception as e:
            logger.error("Microsoft token exchange failed", error=str(e))
            raise ExternalServiceError("Failed to exchange authorization code")
    
    async def get_user_info(self, access_token: str) -> Dict[str, Any]:
        """Get Microsoft user information"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    self.userinfo_endpoint,
                    headers={"Authorization": f"Bearer {access_token}"}
                )
                response.raise_for_status()
                user_data = response.json()
                
                # Normalize field names
                return {
                    'id': user_data.get('id'),
                    'email': user_data.get('mail') or user_data.get('userPrincipalName'),
                    'name': user_data.get('displayName'),
                    'given_name': user_data.get('givenName'),
                    'family_name': user_data.get('surname')
                }
        except Exception as e:
            logger.error("Microsoft user info fetch failed", error=str(e))
            raise ExternalServiceError("Failed to fetch user information")


class OAuth2Service:
    """OAuth2 authentication service"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.providers = {
            'google': GoogleOAuth2Provider(),
            'github': GitHubOAuth2Provider(),
            'microsoft': MicrosoftOAuth2Provider()
        }
    
    def get_provider(self, provider_name: str) -> OAuth2Provider:
        """Get OAuth2 provider by name"""
        provider = self.providers.get(provider_name.lower())
        if not provider:
            raise ValueError(f"Unsupported OAuth2 provider: {provider_name}")
        return provider
    
    async def get_authorization_url(
        self, 
        provider_name: str, 
        redirect_uri: str, 
        state: str
    ) -> str:
        """Get authorization URL for provider"""
        provider = self.get_provider(provider_name)
        return await provider.get_authorization_url(redirect_uri, state)
    
    async def authenticate_with_code(
        self,
        provider_name: str,
        code: str,
        redirect_uri: str,
        tenant_id: str
    ) -> User:
        """Authenticate user with OAuth2 authorization code"""
        provider = self.get_provider(provider_name)
        
        # Exchange code for tokens
        tokens = await provider.exchange_code(code, redirect_uri)
        access_token = tokens.get('access_token')
        
        if not access_token:
            raise AuthenticationError("Failed to obtain access token")
        
        # Get user info from provider
        user_info = await provider.get_user_info(access_token)
        provider_user_id = str(user_info.get('id'))
        email = user_info.get('email')
        
        if not provider_user_id or not email:
            raise AuthenticationError("Incomplete user information from provider")
        
        # Check if OAuth2 account exists
        result = await self.db.execute(
            select(OAuth2Account).where(
                OAuth2Account.provider == provider_name,
                OAuth2Account.provider_user_id == provider_user_id
            )
        )
        oauth_account = result.scalar_one_or_none()
        
        if oauth_account:
            # Update tokens
            oauth_account.access_token = access_token
            oauth_account.refresh_token = tokens.get('refresh_token')
            if 'expires_in' in tokens:
                from datetime import datetime, timedelta
                oauth_account.expires_at = datetime.utcnow() + timedelta(seconds=tokens['expires_in'])
            
            user = await self.db.get(User, oauth_account.user_id)
            if not user or not user.is_active:
                raise AuthenticationError("User account is inactive")
                
            await self.db.commit()
            return user
        
        # Check if user exists with this email
        result = await self.db.execute(
            select(User).where(User.email == email)
        )
        user = result.scalar_one_or_none()
        
        if user:
            # Link OAuth2 account to existing user
            oauth_account = OAuth2Account(
                provider=provider_name,
                provider_user_id=provider_user_id,
                provider_email=email,
                provider_username=user_info.get('login') or user_info.get('username'),
                access_token=access_token,
                refresh_token=tokens.get('refresh_token'),
                user_id=user.id,
                provider_data=str(user_info)  # Store as JSON string
            )
            
            if 'expires_in' in tokens:
                from datetime import datetime, timedelta
                oauth_account.expires_at = datetime.utcnow() + timedelta(seconds=tokens['expires_in'])
            
            self.db.add(oauth_account)
            await self.db.commit()
            return user
        
        # Create new user
        # Get tenant
        tenant = await self.db.get(Tenant, tenant_id)
        if not tenant or not tenant.is_active:
            raise AuthenticationError("Invalid tenant")
        
        # Extract name information
        first_name = user_info.get('given_name') or user_info.get('name', '').split(' ')[0] or 'User'
        last_name = user_info.get('family_name') or ' '.join(user_info.get('name', '').split(' ')[1:]) or 'Name'
        
        # Create user
        user = User(
            email=email,
            first_name=first_name,
            last_name=last_name,
            is_email_verified=True,  # OAuth2 emails are pre-verified
            tenant_id=tenant_id,
            avatar_url=user_info.get('avatar_url') or user_info.get('picture')
        )
        
        self.db.add(user)
        await self.db.flush()  # Get user ID
        
        # Create OAuth2 account
        oauth_account = OAuth2Account(
            provider=provider_name,
            provider_user_id=provider_user_id,
            provider_email=email,
            provider_username=user_info.get('login') or user_info.get('username'),
            access_token=access_token,
            refresh_token=tokens.get('refresh_token'),
            user_id=user.id,
            provider_data=str(user_info)
        )
        
        if 'expires_in' in tokens:
            from datetime import datetime, timedelta
            oauth_account.expires_at = datetime.utcnow() + timedelta(seconds=tokens['expires_in'])
        
        self.db.add(oauth_account)
        await self.db.commit()
        
        logger.info("New user created via OAuth2", 
                   user_id=str(user.id), 
                   provider=provider_name, 
                   tenant_id=tenant_id)
        
        return user