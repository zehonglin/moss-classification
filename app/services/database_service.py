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
                    thumbnail_path TEXT,
                    prediction TEXT,
                    confidence REAL,
                    corrected_label TEXT,
                    is_corrected INTEGER DEFAULT 0
                )
            ''')

            # migration: 为旧库补 thumbnail_path 列（不丢数据）
            cols = [row[1] for row in cursor.execute("PRAGMA table_info(records)").fetchall()]
            if 'thumbnail_path' not in cols:
                cursor.execute("ALTER TABLE records ADD COLUMN thumbnail_path TEXT")
                logger.info("Migrated records table: added thumbnail_path column.")

            # migration: 图像质量状态（拒采帧标记，不产出品级）
            if 'quality_status' not in cols:
                cursor.execute("ALTER TABLE records ADD COLUMN quality_status TEXT DEFAULT 'ok'")
                logger.info("Migrated records table: added quality_status column.")
            if 'rejected_reason' not in cols:
                cursor.execute("ALTER TABLE records ADD COLUMN rejected_reason TEXT")
                logger.info("Migrated records table: added rejected_reason column.")
            
            # Create index for faster queries by timestamp (common query pattern)
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_records_timestamp 
                ON records(timestamp DESC)
            ''')
            
            conn.commit()
            logger.info("Database schema initialized.")

    def add_record(self, timestamp, image_path, prediction, confidence,
                   thumbnail_path=None, quality_status='ok', rejected_reason=None) -> int:
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
                    INSERT INTO records (timestamp, image_path, thumbnail_path, prediction, confidence,
                                         quality_status, rejected_reason)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (timestamp, str(image_path), str(thumbnail_path) if thumbnail_path else None,
                      prediction, confidence, quality_status, rejected_reason))
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
                    SELECT id, timestamp, image_path, thumbnail_path, prediction, confidence,
                           corrected_label, quality_status
                    FROM records
                    ORDER BY id DESC
                    LIMIT ?
                ''', (limit,))
                rows = cursor.fetchall()
                return rows
            except sqlite3.Error as e:
                logger.error(f"Database error in get_recent_records: {e}")
                return []

    def search_records(self, prediction=None, quality_status=None,
                       start_time=None, end_time=None, limit: int = 200) -> list:
        """按品级/质量状态/时间范围筛选记录（列与 get_recent_records 一致）。

        quality_status: None=全部, "ok"=正常, "rejected"=拒采, 其他=精确状态值。
        """
        with self._lock:
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                sql = (
                    "SELECT id, timestamp, image_path, thumbnail_path, prediction, "
                    "confidence, corrected_label, quality_status FROM records WHERE 1=1"
                )
                params = []
                if prediction:
                    sql += " AND prediction = ?"
                    params.append(prediction)
                if quality_status == "rejected":
                    sql += " AND quality_status != 'ok'"
                elif quality_status and quality_status != "all":
                    sql += " AND quality_status = ?"
                    params.append(quality_status)
                if start_time:
                    sql += " AND timestamp >= ?"
                    params.append(start_time)
                if end_time:
                    sql += " AND timestamp <= ?"
                    params.append(end_time)
                sql += " ORDER BY id DESC LIMIT ?"
                params.append(limit)
                return cursor.execute(sql, params).fetchall()
            except sqlite3.Error as e:
                logger.error(f"Database error in search_records: {e}")
                return []

    def search_records_paged(self, prediction=None, quality_status=None,
                             page: int = 1, page_size: int = 50) -> tuple[list, int]:
        """按品级/质量状态筛选并分页返回记录（供 HistoryList 分页浏览）。

        Args:
            prediction: 品级筛选；None=不过滤。
            quality_status: 质量状态精确匹配；None=不过滤。
            page: 页码，从 1 起。
            page_size: 每页行数。

        Returns:
            ``(rows, total)``：rows 列顺序与 ``get_recent_records`` 一致
            ``(id, timestamp, image_path, thumbnail_path, prediction, confidence,
               corrected_label, quality_status)``；total 是匹配 WHERE 条件的总数
            （非整表总数）。page<1 视作 1。
        """
        with self._lock:
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                where, params = [], []
                if prediction:
                    where.append("prediction = ?")
                    params.append(prediction)
                if quality_status:
                    where.append("quality_status = ?")
                    params.append(quality_status)
                clause = ("WHERE " + " AND ".join(where)) if where else ""

                total = cursor.execute(
                    f"SELECT COUNT(*) FROM records {clause}", params
                ).fetchone()[0]

                offset = max(page - 1, 0) * page_size
                rows = cursor.execute(
                    "SELECT id, timestamp, image_path, thumbnail_path, prediction, "
                    f"confidence, corrected_label, quality_status FROM records {clause} "
                    "ORDER BY id DESC LIMIT ? OFFSET ?",
                    params + [page_size, offset],
                ).fetchall()
                return rows, total
            except sqlite3.Error as e:
                logger.error(f"Database error in search_records_paged: {e}")
                return [], 0

    def get_record(self, record_id: int):
        """按 id 查单条记录。返回 (id, timestamp, image_path, prediction, confidence, corrected_label) 或 None。"""
        with self._lock:
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT id, timestamp, image_path, thumbnail_path, prediction, confidence,
                           corrected_label, quality_status, rejected_reason
                    FROM records WHERE id = ?
                ''', (record_id,))
                return cursor.fetchone()
            except sqlite3.Error as e:
                logger.error(f"Database error in get_record: {e}")
                return None

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

    def count_by_final_grade(self) -> dict:
        """按最终品级(corrected_label 优先于 prediction)聚合统计 + 纠错数 + 不合格数。

        Returns:
            ``{"A": int, "B": int, "C": int, "D": int, "corrected": int, "rejected": int}``
            - 品级 A/B/C/D：仅统计 ``quality_status = 'ok'`` 或 NULL 的记录，
              品级取 ``COALESCE(corrected_label, prediction)``（已纠正者按新值计）。
            - corrected：``corrected_label`` 非空且非空串的记录数。
            - rejected：``quality_status`` 非空且不为 ``'ok'`` 的记录数（不计入品级）。
        """
        with self._lock:
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT COALESCE(corrected_label, prediction) AS g, COUNT(*) "
                    "FROM records "
                    "WHERE quality_status = 'ok' OR quality_status IS NULL "
                    "GROUP BY g"
                )
                grades = {"A": 0, "B": 0, "C": 0, "D": 0}
                for g, n in cursor.fetchall():
                    if g in grades:
                        grades[g] = n
                corrected = cursor.execute(
                    "SELECT COUNT(*) FROM records "
                    "WHERE corrected_label IS NOT NULL AND corrected_label != ''"
                ).fetchone()[0]
                rejected = cursor.execute(
                    "SELECT COUNT(*) FROM records "
                    "WHERE quality_status IS NOT NULL AND quality_status != 'ok'"
                ).fetchone()[0]
                return {**grades, "corrected": corrected, "rejected": rejected}
            except sqlite3.Error as e:
                logger.error(f"Database error in count_by_final_grade: {e}")
                return {"A": 0, "B": 0, "C": 0, "D": 0,
                        "corrected": 0, "rejected": 0}

    def count_records_before(self, cutoff_timestamp):
        """统计 timestamp < cutoff 的记录数（用于启动时只报告不删除）。"""
        with self._lock:
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM records WHERE timestamp < ?", (cutoff_timestamp,))
                return cursor.fetchone()[0]
            except sqlite3.Error as e:
                logger.error(f"Database error in count_records_before: {e}")
                return 0

    def delete_records_before_in_batches(self, cutoff_timestamp, limit=500):
        """分页返回 timestamp < cutoff 的记录 (id, image_path, thumbnail_path)。

        供调用方先删文件后按 id 批量删除（DB 删除单事务，避免一次性大事务）。
        """
        with self._lock:
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT id, image_path, thumbnail_path FROM records "
                    "WHERE timestamp < ? ORDER BY id ASC LIMIT ?",
                    (cutoff_timestamp, limit),
                )
                return cursor.fetchall()
            except sqlite3.Error as e:
                logger.error(f"Database error in delete_records_before_in_batches: {e}")
                return []

    def delete_records_by_ids(self, ids):
        """按 id 列表删除记录（单事务）。返回删除行数。"""
        with self._lock:
            if not ids:
                return 0
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                cursor.executemany("DELETE FROM records WHERE id = ?", [(i,) for i in ids])
                conn.commit()
                return cursor.rowcount
            except sqlite3.Error as e:
                logger.error(f"Database error in delete_records_by_ids: {e}")
                return 0

    def delete_records_before(self, cutoff_timestamp):
        """删除 timestamp < cutoff 的记录，返回 [(image_path, thumbnail_path), ...] 供调用方清理文件。
        ISO8601 字符串按字典序比较等价于时间序比较（本项目 timestamp 均为 datetime.isoformat()）。"""
        with self._lock:
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                cursor.execute("SELECT image_path, thumbnail_path FROM records WHERE timestamp < ?", (cutoff_timestamp,))
                rows = cursor.fetchall()
                cursor.execute("DELETE FROM records WHERE timestamp < ?", (cutoff_timestamp,))
                conn.commit()
                return rows
            except sqlite3.Error as e:
                logger.error(f"Database error in delete_records_before: {e}")
                return []

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

