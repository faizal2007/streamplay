# Placeholder SQLAlchemy models and engine setup for MariaDB (expand later)
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Text, JSON
from sqlalchemy.orm import declarative_base, sessionmaker
import os
from datetime import datetime

DATABASE_URL = os.getenv("DATABASE_URL", "mysql+pymysql://root:example@db:3306/streamer")

engine = create_engine(DATABASE_URL, echo=False, future=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

Base = declarative_base()

class Session(Base):
    __tablename__ = "sessions"
    id = Column(String(36), primary_key=True, index=True)
    url = Column(Text)
    status = Column(String(32), default="created")
    created_at = Column(DateTime, default=datetime.utcnow)
    meta = Column(JSON, nullable=True)

# You can add Actions, Errors, Screenshots tables later.