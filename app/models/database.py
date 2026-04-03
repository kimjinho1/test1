from sqlalchemy import create_engine, Column, Integer, Float, Text, DateTime
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from datetime import datetime

from app.config import settings


engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False},
    echo=False,
)
# Enable WAL mode for concurrent reads
with engine.connect() as conn:
    conn.exec_driver_sql("PRAGMA journal_mode=WAL")
    conn.commit()

SessionLocal = sessionmaker(bind=engine)


class Base(DeclarativeBase):
    pass


class Trade(Base):
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(Text, nullable=False)
    action = Column(Text, nullable=False)  # BUY, SELL
    quantity = Column(Integer, nullable=False)
    price = Column(Float, nullable=False)
    broker_order_id = Column(Text)
    strategy_name = Column(Text)
    signal_confidence = Column(Float)
    status = Column(Text, default="PENDING")  # PENDING, FILLED, PARTIAL, CANCELLED, ERROR
    created_at = Column(DateTime, default=datetime.utcnow)


class Signal(Base):
    __tablename__ = "signals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(Text, nullable=False)
    action = Column(Text, nullable=False)  # BUY, SELL, HOLD
    confidence = Column(Float)
    reason = Column(Text)
    strategy_name = Column(Text)
    acted_on = Column(Integer, default=0)  # 0=pending, 1=executed, 2=ignored
    created_at = Column(DateTime, default=datetime.utcnow)


class Position(Base):
    __tablename__ = "positions"

    ticker = Column(Text, primary_key=True)
    quantity = Column(Integer, nullable=False)
    avg_price = Column(Float, nullable=False)
    current_price = Column(Float)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


def init_db():
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
