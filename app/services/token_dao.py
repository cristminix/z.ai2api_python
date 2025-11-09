"""
Lapisan Akses Data Token (DAO)
Menyediakan operasi CRUD dan fungsi query untuk Token
"""
import aiosqlite
import sqlite3
from typing import List, Optional, Dict, Tuple
from datetime import datetime
from contextlib import asynccontextmanager
import os

from app.models.token_db import SQL_CREATE_TABLES, DB_PATH
from app.utils.logger import logger


class TokenDAO:
    """Objek Akses Data Token"""

    def __init__(self, db_path: str = DB_PATH):
        """Inisialisasi DAO"""
        self.db_path = db_path
        self._ensure_db_directory()

    def _ensure_db_directory(self):
        """Memastikan direktori database ada"""
        db_dir = os.path.dirname(self.db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)

    @asynccontextmanager
    async def get_connection(self):
        """Mendapatkan koneksi database asinkron"""
        conn = await aiosqlite.connect(self.db_path)
        conn.row_factory = aiosqlite.Row  # Mengembalikan hasil seperti kamus

        # Mengaktifkan batasan foreign key (SQLite dinonaktifkan secara default)
        await conn.execute("PRAGMA foreign_keys = ON")

        try:
            yield conn
        finally:
            await conn.close()

    def get_sync_connection(self):
        """Mendapatkan koneksi database sinkron (untuk inisialisasi)"""
        conn = sqlite3.connect(self.db_path)
        # Mengaktifkan batasan foreign key
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    async def init_database(self):
        """Inisialisasi struktur tabel database"""
        try:
            # Menggunakan koneksi sinkron untuk membuat tabel (menghindari masalah inisialisasi asinkron)
            conn = self.get_sync_connection()
            conn.executescript(SQL_CREATE_TABLES)
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"❌ Gagal menginisialisasi database Token: {e}")
            raise

    # ==================== Operasi CRUD Token ====================

    async def add_token(
        self,
        provider: str,
        token: str,
        token_type: str = "user",
        priority: int = 0,
        validate: bool = True
    ) -> Optional[int]:
        """
        Menambahkan Token baru (validasi opsional)

        Args:
            provider: Nama penyedia
            token: Nilai Token
            token_type: Tipe Token (akan ditimpa oleh hasil validasi jika validate=True)
            priority: Prioritas
            validate: Apakah akan memvalidasi Token (hanya untuk penyedia zai)

        Returns:
            token_id atau None (validasi gagal atau sudah ada)
        """
        try:
            # Untuk penyedia zai, validasi Token secara paksa
            if provider == "zai" and validate:
                from app.utils.token_pool import ZAITokenValidator

                validated_type, is_valid, error_msg = await ZAITokenValidator.validate_token(token)

                # Tolak token tamu
                if validated_type == "guest":
                    logger.warning(f"🚫 Menolak menambahkan Token pengguna anonim: {token[:20]}... - {error_msg}")
                    return None

                # Tolak token tidak valid
                if not is_valid:
                    logger.warning(f"🚫 Validasi Token gagal: {token[:20]}... - {error_msg}")
                    return None

                # Gunakan tipe yang sudah divalidasi
                token_type = validated_type

            async with self.get_connection() as conn:
                cursor = await conn.execute("""
                    INSERT OR IGNORE INTO tokens (provider, token, token_type, priority)
                    VALUES (?, ?, ?, ?)
                """, (provider, token, token_type, priority))

                await conn.commit()

                if cursor.lastrowid > 0:
                    # Buat juga catatan statistik
                    await conn.execute("""
                        INSERT INTO token_stats (token_id)
                        VALUES (?)
                    """, (cursor.lastrowid,))
                    await conn.commit()
                    logger.info(f"✅ Token ditambahkan: {provider} ({token_type}) - {token[:20]}...")
                    return cursor.lastrowid
                else:
                    logger.warning(f"⚠️ Token sudah ada: {provider} - {token[:20]}...")
                    return None
        except Exception as e:
            logger.error(f"❌ Gagal menambahkan Token: {e}")
            return None

    async def get_tokens_by_provider(self, provider: str, enabled_only: bool = True) -> List[Dict]:
        """
        Mendapatkan semua Token dari penyedia tertentu

        Args:
            provider: Nama penyedia
            enabled_only: Apakah hanya mengembalikan Token yang diaktifkan
        """
        try:
            async with self.get_connection() as conn:
                query = """
                    SELECT t.*, ts.total_requests, ts.successful_requests, ts.failed_requests,
                           ts.last_success_time, ts.last_failure_time
                    FROM tokens t
                    LEFT JOIN token_stats ts ON t.id = ts.token_id
                    WHERE t.provider = ?
                """
                params = [provider]

                if enabled_only:
                    query += " AND t.is_enabled = 1"

                query += " ORDER BY t.priority DESC, t.id ASC"

                cursor = await conn.execute(query, params)
                rows = await cursor.fetchall()

                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"❌ Gagal mengkueri Token: {e}")
            return []

    async def get_all_tokens(self, enabled_only: bool = False) -> List[Dict]:
        """Mendapatkan semua Token"""
        try:
            async with self.get_connection() as conn:
                query = """
                    SELECT t.*, ts.total_requests, ts.successful_requests, ts.failed_requests,
                           ts.last_success_time, ts.last_failure_time
                    FROM tokens t
                    LEFT JOIN token_stats ts ON t.id = ts.token_id
                """

                if enabled_only:
                    query += " WHERE t.is_enabled = 1"

                query += " ORDER BY t.provider, t.priority DESC, t.id ASC"

                cursor = await conn.execute(query)
                rows = await cursor.fetchall()

                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"❌ Gagal mengkueri semua Token: {e}")
            return []

    async def update_token_status(self, token_id: int, is_enabled: bool):
        """Memperbarui status aktif Token"""
        try:
            async with self.get_connection() as conn:
                await conn.execute("""
                    UPDATE tokens SET is_enabled = ? WHERE id = ?
                """, (is_enabled, token_id))
                await conn.commit()
                logger.info(f"✅ Status Token diperbarui: id={token_id}, enabled={is_enabled}")
        except Exception as e:
            logger.error(f"❌ Gagal memperbarui status Token: {e}")

    async def update_token_type(self, token_id: int, token_type: str):
        """Memperbarui tipe Token"""
        try:
            async with self.get_connection() as conn:
                await conn.execute("""
                    UPDATE tokens SET token_type = ? WHERE id = ?
                """, (token_type, token_id))
                await conn.commit()
                logger.info(f"✅ Tipe Token diperbarui: id={token_id}, type={token_type}")
        except Exception as e:
            logger.error(f"❌ Gagal memperbarui tipe Token: {e}")

    async def delete_token(self, token_id: int):
        """Menghapus Token (penghapusan berjenjang data statistik)"""
        try:
            async with self.get_connection() as conn:
                await conn.execute("DELETE FROM tokens WHERE id = ?", (token_id,))
                await conn.commit()
                logger.info(f"✅ Token dihapus: id={token_id}")
        except Exception as e:
            logger.error(f"❌ Gagal menghapus Token: {e}")

    async def delete_tokens_by_provider(self, provider: str):
        """Menghapus semua Token dari penyedia tertentu"""
        try:
            async with self.get_connection() as conn:
                await conn.execute("DELETE FROM tokens WHERE provider = ?", (provider,))
                await conn.commit()
                logger.info(f"✅ Semua Token penyedia dihapus: {provider}")
        except Exception as e:
            logger.error(f"❌ Gagal menghapus Token penyedia: {e}")

    # ==================== Operasi Statistik Token ====================

    async def record_success(self, token_id: int):
        """Mencatat keberhasilan penggunaan Token"""
        try:
            async with self.get_connection() as conn:
                await conn.execute("""
                    UPDATE token_stats
                    SET total_requests = total_requests + 1,
                        successful_requests = successful_requests + 1,
                        last_success_time = CURRENT_TIMESTAMP
                    WHERE token_id = ?
                """, (token_id,))
                await conn.commit()
        except Exception as e:
            logger.error(f"❌ Gagal mencatat keberhasilan: {e}")

    async def record_failure(self, token_id: int):
        """Mencatat kegagalan penggunaan Token"""
        try:
            async with self.get_connection() as conn:
                await conn.execute("""
                    UPDATE token_stats
                    SET total_requests = total_requests + 1,
                        failed_requests = failed_requests + 1,
                        last_failure_time = CURRENT_TIMESTAMP
                    WHERE token_id = ?
                """, (token_id,))
                await conn.commit()
        except Exception as e:
            logger.error(f"❌ Gagal mencatat kegagalan: {e}")

    async def get_token_stats(self, token_id: int) -> Optional[Dict]:
        """Mendapatkan informasi statistik Token"""
        try:
            async with self.get_connection() as conn:
                cursor = await conn.execute("""
                    SELECT * FROM token_stats WHERE token_id = ?
                """, (token_id,))
                row = await cursor.fetchone()
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"❌ Gagal mendapatkan informasi statistik: {e}")
            return None

    # ==================== Operasi Batch ====================

    async def bulk_add_tokens(
        self,
        provider: str,
        tokens: List[str],
        token_type: str = "user",
        validate: bool = True
    ) -> Tuple[int, int]:
        """
        Menambahkan Token secara massal (validasi opsional)

        Args:
            provider: Nama penyedia
            tokens: Daftar Token
            token_type: Tipe Token (akan ditimpa jika validate=True)
            validate: Apakah akan memvalidasi Token (hanya untuk zai)

        Returns:
            (Jumlah yang berhasil ditambahkan, Jumlah yang gagal)
        """
        added_count = 0
        failed_count = 0

        for token in tokens:
            if token.strip():  # 过滤空 token
                token_id = await self.add_token(
                    provider,
                    token.strip(),
                    token_type,
                    validate=validate
                )
                if token_id:
                    added_count += 1
                else:
                    failed_count += 1

        logger.info(f"✅ Penambahan massal selesai: {provider} - Berhasil {added_count}/{len(tokens)}, Gagal {failed_count}")
        return added_count, failed_count

    async def replace_tokens(self, provider: str, tokens: List[str],
                            token_type: str = "user"):
        """
        Mengganti semua Token dari penyedia tertentu (hapus dulu, lalu tambahkan)
        """
        # 删除旧 Token
        await self.delete_tokens_by_provider(provider)

        # 添加新 Token
        added_count = await self.bulk_add_tokens(provider, tokens, token_type)

        logger.info(f"✅ Penggantian Token selesai: {provider} - {added_count} buah")
        return added_count

    # ==================== Metode Utilitas ====================

    async def get_token_by_value(self, provider: str, token: str) -> Optional[Dict]:
        """Mencari berdasarkan nilai Token"""
        try:
            async with self.get_connection() as conn:
                cursor = await conn.execute("""
                    SELECT t.*, ts.total_requests, ts.successful_requests, ts.failed_requests
                    FROM tokens t
                    LEFT JOIN token_stats ts ON t.id = ts.token_id
                    WHERE t.provider = ? AND t.token = ?
                """, (provider, token))
                row = await cursor.fetchone()
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"❌ Gagal mengkueri Token: {e}")
            return None

    async def get_provider_stats(self, provider: str) -> Dict:
        """Mendapatkan informasi statistik penyedia"""
        try:
            async with self.get_connection() as conn:
                cursor = await conn.execute("""
                    SELECT
                        COUNT(*) as total_tokens,
                        SUM(CASE WHEN is_enabled = 1 THEN 1 ELSE 0 END) as enabled_tokens,
                        SUM(ts.total_requests) as total_requests,
                        SUM(ts.successful_requests) as successful_requests,
                        SUM(ts.failed_requests) as failed_requests
                    FROM tokens t
                    LEFT JOIN token_stats ts ON t.id = ts.token_id
                    WHERE t.provider = ?
                """, (provider,))
                row = await cursor.fetchone()
                return dict(row) if row else {}
        except Exception as e:
            logger.error(f"❌ Gagal mendapatkan statistik penyedia: {e}")
            return {}

    # ==================== Operasi Validasi Token ====================

    async def validate_and_update_token(self, token_id: int) -> bool:
        """
        Memvalidasi Token tunggal dan memperbarui tipenya

        Args:
            token_id: ID database Token

        Returns:
            Apakah Token pengguna yang terautentikasi valid
        """
        try:
            # 获取 Token 信息
            async with self.get_connection() as conn:
                cursor = await conn.execute("""
                    SELECT provider, token FROM tokens WHERE id = ?
                """, (token_id,))
                row = await cursor.fetchone()

                if not row:
                    logger.error(f"❌ Token ID {token_id} tidak ada")
                    return False

                provider = row["provider"]
                token = row["token"]

            # Hanya validasi untuk penyedia zai
            if provider != "zai":
                logger.info(f"⏭️ Melewati validasi Token untuk penyedia non-zai: {provider}")
                return True

            # 验证 Token
            from app.utils.token_pool import ZAITokenValidator

            token_type, is_valid, error_msg = await ZAITokenValidator.validate_token(token)

            # 更新 Token 类型
            await self.update_token_type(token_id, token_type)

            if not is_valid:
                logger.warning(f"⚠️ Validasi Token gagal: id={token_id}, type={token_type}, error={error_msg}")

            return is_valid

        except Exception as e:
            logger.error(f"❌ Gagal memvalidasi Token: {e}")
            return False

    async def validate_all_tokens(self, provider: str = "zai") -> Dict[str, int]:
        """
        Memvalidasi semua Token secara massal

        Args:
            provider: Nama penyedia (default zai)

        Returns:
            Hasil statistik {"valid": jumlah, "guest": jumlah, "invalid": jumlah}
        """
        try:
            tokens = await self.get_tokens_by_provider(provider, enabled_only=False)

            if not tokens:
                logger.warning(f"⚠️ Tidak ada Token {provider} yang perlu divalidasi")
                return {"valid": 0, "guest": 0, "invalid": 0}

            logger.info(f"🔍 Memulai validasi massal {len(tokens)} Token {provider}...")

            stats = {"valid": 0, "guest": 0, "invalid": 0}

            for token_record in tokens:
                token_id = token_record["id"]
                is_valid = await self.validate_and_update_token(token_id)

                # 重新查询更新后的类型
                async with self.get_connection() as conn:
                    cursor = await conn.execute("""
                        SELECT token_type FROM tokens WHERE id = ?
                    """, (token_id,))
                    row = await cursor.fetchone()
                    token_type = row["token_type"] if row else "unknown"

                if token_type == "user":
                    stats["valid"] += 1
                elif token_type == "guest":
                    stats["guest"] += 1
                else:
                    stats["invalid"] += 1

            logger.info(f"✅ Validasi massal selesai: Valid {stats['valid']}, Tamu {stats['guest']}, Tidak Valid {stats['invalid']}")
            return stats

        except Exception as e:
            logger.error(f"❌ Validasi massal gagal: {e}")
            return {"valid": 0, "guest": 0, "invalid": 0}


# Singleton global
_token_dao: Optional[TokenDAO] = None


def get_token_dao() -> TokenDAO:
    """Mendapatkan instance TokenDAO global"""
    global _token_dao
    if _token_dao is None:
        _token_dao = TokenDAO()
    return _token_dao


async def init_token_database():
    """Inisialisasi database Token"""
    dao = get_token_dao()
    await dao.init_database()
