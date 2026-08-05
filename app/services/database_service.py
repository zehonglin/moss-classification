import sqlite3
import os
import threading
import logging
from datetime import datetime
from app.utils.config_manager import ConfigManager

logger = logging.getLogger(__name__)


class DatabaseService:
    """
    Database service with connection pooling and thread safety.
    
    Performance Optimizations:
    - Maintains a persistent connection instead of creating/closing per operation
    - Uses WAL (Write-Ahead Logging) mode for better concurrent performance
    - Thread-safe via locking mechanism
    - Implements proper connection cleanup on shutdown
    
    For SQLite in multi-threaded environments:
    - SQLite itself is thread-safe when using check_same_thread=False
    - We add our own lock for additional safety and to serialize writes
    """
    
    def __init__(self, config_manager: ConfigManager):
        self.config = config_manager
        self.db_path = self.config.get("data_paths.db_filename", "data/moss.db")
        
        # Thread lock for serializing database access
        self._lock = threading.Lock()
        
        # Persistent connection (will be created on first use)
        self._connection: sqlite3.Connection | None = None
        
        # Initialize database
        self._init_db()
        
        logger.info(f"DatabaseService initialized with db: {self.db_path}")

    def _get_connection(self) -> sqlite3.Connection:
        """
        Get or create the persistent database connection.
        Thread-safe: should only be called while holding self._lock.
        """
        if self._connection is None:
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
            
            # Create connection with thread-safety enabled
            self._connection = sqlite3.connect(
                self.db_path,
                check_same_thread=False,  # Allow access from multiple threads
                timeout=30.0  # Wait up to 30 seconds for locks
            )
            
            # Enable WAL mode for better concurrent read/write performance
            # WAL allows readers and writers to operate concurrently
            self._connection.execute("PRAGMA journal_mode=WAL")
            
            # Enable foreign keys (good practice)
            self._connection.execute("PRAGMA foreign_keys=ON")
            
            # Synchronous mode: NORMAL is a good balance between safety and speed
            self._connection.execute("PRAGMA synchronous=NORMAL")
            
            logger.info("Database connection established with WAL mode enabled.")
        
        return self._connection

    def _init_db(self):
        """Initialize the database schema."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            # Create main records table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    image_path TEXT NOT NULL,
                    prediction TEXT,
                    confidence REAL,
                    corrected_label TEXT,
                    is_corrected INTEGER DEFAULT 0
                )
            ''')
            
            # Create index for faster queries by timestamp (common query pattern)
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_records_timestamp 
                ON records(timestamp DESC)
            ''')
            
            conn.commit()
            logger.info("Database schema initialized.")

    def add_record(self, timestamp, image_path, prediction, confidence) -> int:
        """
        Add a new inference record.
        Thread-safe: uses locking for concurrent access.
        
        Returns:
            The ID of the newly created record.
        """
        with self._lock:
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO records (timestamp, image_path, prediction, confidence)
                    VALUES (?, ?, ?, ?)
                ''', (timestamp, str(image_path), prediction, confidence))
                conn.commit()
                record_id = cursor.lastrowid
                return record_id
            except sqlite3.Error as e:
                logger.error(f"Database error in add_record: {e}")
                # Re-raise to let caller handle
                raise

    def update_correction(self, record_id: int, corrected_label: str) -> bool:
        """
        Update a record with a correction.
        Thread-safe: uses locking for concurrent access.
        
        Returns:
            True if the update was successful, False otherwise.
        """
        with self._lock:
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE records
                    SET corrected_label = ?, is_corrected = 1
                    WHERE id = ?
                ''', (corrected_label, record_id))
                conn.commit()
                return cursor.rowcount > 0
            except sqlite3.Error as e:
                logger.error(f"Database error in update_correction: {e}")
                return False

    def get_recent_records(self, limit: int = 50) -> list:
        """
        Get the most recent records.
        Thread-safe: uses locking for concurrent access.
        
        Args:
            limit: Maximum number of records to return.
            
        Returns:
            List of tuples: (id, timestamp, image_path, prediction, confidence, corrected_label)
        """
        with self._lock:
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT id, timestamp, image_path, prediction, confidence, corrected_label
                    FROM records
                    ORDER BY id DESC
                    LIMIT ?
                ''', (limit,))
                rows = cursor.fetchall()
                return rows
            except sqlite3.Error as e:
                logger.error(f"Database error in get_recent_records: {e}")
                return []

    def get_record_count(self) -> int:
        """
        Get total number of records in the database.
        Useful for monitoring database size.
        """
        with self._lock:
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                cursor.execute('SELECT COUNT(*) FROM records')
                return cursor.fetchone()[0]
            except sqlite3.Error as e:
                logger.error(f"Database error in get_record_count: {e}")
                return 0

    def close(self):
        """
        Close the database connection.
        Should be called when the application is shutting down.
        """
        with self._lock:
            if self._connection is not None:
                try:
                    # Checkpoint WAL to main database before closing
                    self._connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                    self._connection.close()
                    logger.info("Database connection closed.")
                except sqlite3.Error as e:
                    logger.error(f"Error closing database: {e}")
                finally:
                    self._connection = None

    def __del__(self):
        """Destructor to ensure connection is closed."""
        self.close()

