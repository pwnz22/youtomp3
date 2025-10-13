import logging
from datetime import datetime
from typing import Optional, Dict, Any

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import select, func

from app.models import Base, User, Download, Error

logger = logging.getLogger(__name__)


class DatabaseService:
    """Service for database operations"""

    def __init__(self, database_url: str):
        """
        Initialize database service

        Args:
            database_url: SQLAlchemy database URL (e.g., sqlite+aiosqlite:///data/bot.db)
        """
        # Configure engine with proper settings
        engine_kwargs = {
            "echo": False,
        }

        # SQLite-specific settings
        if "sqlite" in database_url:
            engine_kwargs["connect_args"] = {"check_same_thread": False}
        else:
            # Pool settings only for non-SQLite databases
            engine_kwargs["pool_size"] = 5
            engine_kwargs["max_overflow"] = 10
            engine_kwargs["pool_pre_ping"] = True

        self.engine = create_async_engine(database_url, **engine_kwargs)
        self.async_session = async_sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False
        )

    async def init_db(self):
        """Initialize database (create tables)"""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database initialized")

    async def close(self):
        """Close database connections"""
        await self.engine.dispose()
        logger.info("Database connections closed")

    # User operations
    async def upsert_user(
        self, user_id: int, username: Optional[str], first_name: Optional[str]
    ) -> User:
        """
        Insert or update user (update last_active if exists)
        Uses merge for atomic upsert operation

        Args:
            user_id: Telegram user ID
            username: Telegram username
            first_name: User's first name

        Returns:
            User object
        """
        async with self.async_session() as session:
            # Create user object
            user = User(
                id=user_id,
                username=username,
                first_name=first_name,
                last_active=datetime.utcnow(),
                created_at=datetime.utcnow(),
            )

            # Use merge for atomic upsert - SQLAlchemy handles the race condition
            user = await session.merge(user)

            # For existing users, update last_active manually
            user.last_active = datetime.utcnow()

            await session.commit()
            await session.refresh(user)
            logger.info(f"Upserted user {user_id}")
            return user

    # Download operations
    async def add_download(
        self,
        user_id: int,
        url: str,
        title: str,
        file_size: int,
        duration: Optional[int] = None,
    ) -> Download:
        """
        Record a successful download

        Args:
            user_id: Telegram user ID
            url: YouTube video URL
            title: Video title
            file_size: File size in bytes
            duration: Video duration in seconds

        Returns:
            Download object
        """
        async with self.async_session() as session:
            download = Download(
                user_id=user_id,
                url=url,
                title=title,
                file_size=file_size,
                duration=duration,
                created_at=datetime.utcnow(),
            )
            session.add(download)
            await session.commit()
            await session.refresh(download)
            logger.info(f"Recorded download for user {user_id}: {title}")
            return download

    # Error operations
    async def add_error(
        self, user_id: int, url: str, error_type: str, error_message: Optional[str]
    ) -> Error:
        """
        Record a failed download attempt

        Args:
            user_id: Telegram user ID
            url: YouTube video URL
            error_type: Exception class name
            error_message: Error message

        Returns:
            Error object
        """
        async with self.async_session() as session:
            error = Error(
                user_id=user_id,
                url=url,
                error_type=error_type,
                error_message=error_message,
                created_at=datetime.utcnow(),
            )
            session.add(error)
            await session.commit()
            await session.refresh(error)
            logger.info(f"Recorded error for user {user_id}: {error_type}")
            return error

    # Statistics operations
    async def get_stats(self) -> Dict[str, Any]:
        """
        Get bot statistics

        Returns:
            Dictionary with stats:
            - total_users: Total number of users
            - total_downloads: Total successful downloads
            - total_errors: Total failed attempts
        """
        async with self.async_session() as session:
            # Count users
            users_result = await session.execute(select(func.count(User.id)))
            total_users = users_result.scalar()

            # Count downloads
            downloads_result = await session.execute(select(func.count(Download.id)))
            total_downloads = downloads_result.scalar()

            # Count errors
            errors_result = await session.execute(select(func.count(Error.id)))
            total_errors = errors_result.scalar()

            total_requests = total_downloads + total_errors

            return {
                "total_users": total_users,
                "total_downloads": total_downloads,
                "total_errors": total_errors,
                "total_requests": total_requests,
            }
