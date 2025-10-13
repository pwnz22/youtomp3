from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Index
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)  # Telegram user_id
    username = Column(String, nullable=True)
    first_name = Column(String, nullable=True)
    last_active = Column(DateTime, nullable=False, default=datetime.utcnow)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # Relationships
    downloads = relationship("Download", back_populates="user")
    errors = relationship("Error", back_populates="user")

    __table_args__ = (
        Index('idx_users_last_active', 'last_active'),
    )


class Download(Base):
    __tablename__ = "downloads"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    url = Column(String, nullable=False)
    title = Column(String, nullable=False)
    file_size = Column(Integer, nullable=False)
    duration = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # Relationships
    user = relationship("User", back_populates="downloads")

    __table_args__ = (
        Index('idx_downloads_user_id', 'user_id'),
        Index('idx_downloads_created_at', 'created_at'),
    )


class Error(Base):
    __tablename__ = "errors"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    url = Column(String, nullable=False)
    error_type = Column(String, nullable=False)
    error_message = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # Relationships
    user = relationship("User", back_populates="errors")

    __table_args__ = (
        Index('idx_errors_user_id', 'user_id'),
        Index('idx_errors_error_type', 'error_type'),
        Index('idx_errors_created_at', 'created_at'),
    )
