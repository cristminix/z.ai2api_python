"""
Lapisan Akses Data Log Permintaan (DAO)
Menyediakan operasi CRUD dan fungsi query untuk log permintaan
"""
import aiosqlite
import sqlite3
from typing import List, Dict, Optional
from datetime import datetime, timedelta
from contextlib import asynccontextmanager
import os

from app.models.request_log import SQL_CREATE_REQUEST_LOGS_TABLE, DB_PATH
from app.utils.logger import logger


class RequestLogDAO:
    """Objek Akses Data Log Permintaan"""

    def __init__(self, db_path: str = DB_PATH):
        """Inisialisasi DAO"""
        self.db_path = db_path
        self._ensure_db_directory()
        self._init_db()

    def _ensure_db_directory(self):
        """Memastikan direktori database ada"""
        db_dir = os.path.dirname(self.db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)

    def _init_db(self):
        """Inisialisasi tabel database"""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.executescript(SQL_CREATE_REQUEST_LOGS_TABLE)
            conn.commit()
            conn.close()
            logger.debug("Tabel log permintaan berhasil diinisialisasi")
        except Exception as e:
            logger.error(f"Gagal menginisialisasi tabel log permintaan: {e}")

    @asynccontextmanager
    async def get_connection(self):
        """Mendapatkan koneksi database asinkron"""
        conn = await aiosqlite.connect(self.db_path)
        conn.row_factory = aiosqlite.Row
        try:
            yield conn
        finally:
            await conn.close()

    async def add_log(
        self,
        provider: str,
        model: str,
        success: bool,
        duration: float = 0.0,
        first_token_time: float = 0.0,
        input_tokens: int = 0,
        output_tokens: int = 0,
        error_message: str = None
    ) -> int:
        """
        Menambahkan log permintaan

        Args:
            provider: Nama penyedia
            model: Nama model
            success: Apakah berhasil
            duration: Total waktu yang dibutuhkan (detik)
            first_token_time: Waktu tunggu token pertama (detik)
            input_tokens: Jumlah token input
            output_tokens: Jumlah token output
            error_message: Pesan error

        Returns:
            ID log
        """
        total_tokens = input_tokens + output_tokens

        async with self.get_connection() as conn:
            cursor = await conn.execute(
                """
                INSERT INTO request_logs
                (provider, model, success, duration, first_token_time,
                 input_tokens, output_tokens, total_tokens, error_message)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (provider, model, success, duration, first_token_time,
                 input_tokens, output_tokens, total_tokens, error_message)
            )
            await conn.commit()
            return cursor.lastrowid

    async def get_recent_logs(
        self,
        limit: int = 100,
        provider: str = None,
        model: str = None,
        success: bool = None
    ) -> List[Dict]:
        """
        Mendapatkan log permintaan terbaru

        Args:
            limit: Batas jumlah yang dikembalikan
            provider: Filter penyedia
            model: Filter model
            success: Filter status berhasil/gagal

        Returns:
            Daftar log
        """
        query = "SELECT * FROM request_logs WHERE 1=1"
        params = []

        if provider:
            query += " AND provider = ?"
            params.append(provider)

        if model:
            query += " AND model = ?"
            params.append(model)

        if success is not None:
            query += " AND success = ?"
            params.append(success)

        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        async with self.get_connection() as conn:
            cursor = await conn.execute(query, params)
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_logs_by_time_range(
        self,
        start_time: datetime,
        end_time: datetime,
        provider: str = None,
        model: str = None
    ) -> List[Dict]:
        """
        Mendapatkan log berdasarkan rentang waktu

        Args:
            start_time: Waktu mulai
            end_time: Waktu selesai
            provider: Filter penyedia
            model: Filter model

        Returns:
            Daftar log
        """
        query = "SELECT * FROM request_logs WHERE timestamp BETWEEN ? AND ?"
        params = [start_time.isoformat(), end_time.isoformat()]

        if provider:
            query += " AND provider = ?"
            params.append(provider)

        if model:
            query += " AND model = ?"
            params.append(model)

        query += " ORDER BY timestamp DESC"

        async with self.get_connection() as conn:
            cursor = await conn.execute(query, params)
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_model_stats_from_db(self, hours: int = 24) -> Dict:
        """
        Mendapatkan statistik model dari database (N jam terakhir)

        Args:
            hours: Jumlah jam

        Returns:
            Data statistik model
        """
        start_time = datetime.now() - timedelta(hours=hours)

        async with self.get_connection() as conn:
            cursor = await conn.execute(
                """
                SELECT
                    model,
                    COUNT(*) as total,
                    SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as success,
                    SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) as failed,
                    SUM(input_tokens) as input_tokens,
                    SUM(output_tokens) as output_tokens,
                    SUM(total_tokens) as total_tokens,
                    AVG(duration) as avg_duration,
                    AVG(first_token_time) as avg_first_token_time
                FROM request_logs
                WHERE timestamp >= ?
                GROUP BY model
                ORDER BY total DESC
                """,
                (start_time.isoformat(),)
            )
            rows = await cursor.fetchall()

            result = {}
            for row in rows:
                model = row['model']
                result[model] = {
                    'total': row['total'],
                    'success': row['success'],
                    'failed': row['failed'],
                    'input_tokens': row['input_tokens'] or 0,
                    'output_tokens': row['output_tokens'] or 0,
                    'total_tokens': row['total_tokens'] or 0,
                    'avg_duration': round(row['avg_duration'] or 0, 2),
                    'avg_first_token_time': round(row['avg_first_token_time'] or 0, 2),
                    'success_rate': round((row['success'] / row['total'] * 100) if row['total'] > 0 else 0, 1)
                }

            return result

    async def delete_old_logs(self, days: int = 30) -> int:
        """
        Menghapus log lama

        Args:
            days: Jumlah hari yang dipertahankan

        Returns:
            Jumlah record yang dihapus
        """
        cutoff_time = datetime.now() - timedelta(days=days)

        async with self.get_connection() as conn:
            cursor = await conn.execute(
                "DELETE FROM request_logs WHERE timestamp < ?",
                (cutoff_time.isoformat(),)
            )
            await conn.commit()
            return cursor.rowcount


# Instance singleton global
_request_log_dao: Optional[RequestLogDAO] = None


def get_request_log_dao() -> RequestLogDAO:
    """
    Mendapatkan singleton DAO log permintaan

    Returns:
        Instance RequestLogDAO
    """
    global _request_log_dao
    if _request_log_dao is None:
        _request_log_dao = RequestLogDAO()
    return _request_log_dao


def init_request_log_dao():
    """Inisialisasi DAO log permintaan"""
    global _request_log_dao
    _request_log_dao = RequestLogDAO()
    return _request_log_dao
