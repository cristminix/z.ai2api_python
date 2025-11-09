#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Manajer kumpulan Token - Rotasi Token dan pemeriksaan kesehatan berbasis database

Fitur inti:
1. Mekanisme rotasi Token - Load balancing dan toleransi kesalahan
2. Verifikasi antarmuka autentikasi resmi Z.AI - Membedakan jenis pengguna berdasarkan bidang peran
3. Pemantauan kesehatan Token - Otomatis menonaktifkan Token yang gagal
4. Integrasi database - Bekerja sama dengan TokenDAO
"""

import asyncio
import time
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from threading import Lock
import httpx

from app.utils.logger import logger


# ==================== Token 状态管理 ====================


@dataclass
class TokenStatus:
    """Status runtime Token (dalam memori)"""
    token: str
    token_id: int  # ID database, digunakan untuk sinkronisasi statistik
    token_type: str = "unknown"  # "user", "guest", "unknown"
    is_available: bool = True
    failure_count: int = 0
    last_failure_time: float = 0.0
    last_success_time: float = 0.0
    total_requests: int = 0
    successful_requests: int = 0

    @property
    def success_rate(self) -> float:
        """Tingkat keberhasilan"""
        if self.total_requests == 0:
            return 1.0
        return self.successful_requests / self.total_requests

    @property
    def is_healthy(self) -> bool:
        """
        Penentuan status kesehatan Token

        Standar kesehatan:
        1. Harus berupa Token pengguna terautentikasi (token_type = "user")
        2. Saat ini tersedia (is_available = True)
        3. Tingkat keberhasilan >= 50% atau jumlah total permintaan <= 3 (toleransi Token baru)

        Perhatian:
        - Token guest selalu tidak sehat
        - Token unknown selalu tidak sehat
        """
        # Token guest dan unknown selalu tidak sehat
        if self.token_type != "user":
            return False

        # Token yang tidak tersedia tidak sehat
        if not self.is_available:
            return False

        # Toleransi kesalahan token baru: ketika jumlah permintaan sangat sedikit, token dianggap sehat selama tidak ada kegagalan
        if self.total_requests <= 3:
            return self.failure_count == 0

        # Penilaian berdasarkan tingkat keberhasilan
        return self.success_rate >= 0.5


# ==================== Token 验证服务 ====================


class ZAITokenValidator:
    """Validator Token Z.AI (menggunakan antarmuka autentikasi resmi)"""

    AUTH_URL = "https://chat.z.ai/api/v1/auths/"

    @staticmethod
    def get_headers(token: str) -> Dict[str, str]:
        """Membangun header permintaan autentikasi"""
        return {
            "Accept": "*/*",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Authorization": f"Bearer {token}",
            "Connection": "keep-alive",
            "Content-Type": "application/json",
            "DNT": "1",
            "Referer": "https://chat.z.ai/",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36",
            "sec-ch-ua": '"Chromium";v="140", "Not=A?Brand";v="24", "Google Chrome";v="140"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"'
        }

    @classmethod
    async def validate_token(cls, token: str) -> Tuple[str, bool, Optional[str]]:
        """
        Verifikasi validitas Token dan kembalikan jenisnya

        Args:
            token: Token yang akan diverifikasi

        Returns:
            (token_type, is_valid, error_message)
            - token_type: "user" | "guest" | "unknown"
            - is_valid: True berarti Token pengguna terautentikasi yang valid
            - error_message: Alasan kegagalan (hanya memiliki nilai ketika is_valid=False)
        """
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(
                    cls.AUTH_URL,
                    headers=cls.get_headers(token)
                )

                # Parsing respons
                return cls._parse_auth_response(response)

        except httpx.TimeoutException:
            return ("unknown", False, "Permintaan timeout")
        except httpx.ConnectError:
            return ("unknown", False, "Koneksi gagal")
        except Exception as e:
            return ("unknown", False, f"Exception validasi: {str(e)}")

    @staticmethod
    def _parse_auth_response(response: httpx.Response) -> Tuple[str, bool, Optional[str]]:
        """
        Parse respons antarmuka autentikasi Z.AI

        Contoh format respons:
        {
            "id": "...",
            "email": "user@example.com",
            "role": "user"  # atau "guest"
        }

        Aturan verifikasi:
        - role: "user" → Token pengguna terautentikasi (valid, dapat ditambahkan)
        - role: "guest" → Token pengguna anonim (tidak valid, tolak penambahan)
        - Kasus lain → Token tidak valid
        """
        # Periksa kode status HTTP
        if response.status_code != 200:
            return ("unknown", False, f"HTTP {response.status_code}")

        try:
            data = response.json()

            # Verifikasi format respons
            if not isinstance(data, dict):
                return ("unknown", False, "Format respons tidak valid")

            # Periksa apakah ada informasi error
            if "error" in data or "message" in data:
                error_msg = data.get("error") or data.get("message", "Kesalahan tidak diketahui")
                return ("unknown", False, str(error_msg))

            # Verifikasi inti: periksa bidang role
            role = data.get("role")

            if role == "user":
                return ("user", True, None)
            elif role == "guest":
                return ("guest", False, "Token pengguna anonim tidak diizinkan untuk ditambahkan")
            else:
                return ("unknown", False, f"role tidak diketahui: {role}")

        except (ValueError, Exception) as e:
            return ("unknown", False, f"Gagal memparse respons: {str(e)}")


# ==================== Token 池管理器 ====================


class TokenPool:
    """Manajer kumpulan Token (berbasis database)"""

    def __init__(
        self,
        tokens: List[Tuple[int, str, str]],  # [(token_id, token_value, token_type), ...]
        failure_threshold: int = 3,
        recovery_timeout: int = 1800
    ):
        """
        Inisialisasi kumpulan Token

        Args:
            tokens: Daftar Token [(token_id, token_value, token_type), ...]
            failure_threshold: Ambang kegagalan, melebihi jumlah ini akan ditandai sebagai tidak tersedia
            recovery_timeout: Waktu habis pemulihan (detik), Token gagal akan dicoba kembali setelah waktu ini
        """
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self._lock = Lock()
        self._current_index = 0

        # Inisialisasi status Token (dalam memori)
        self.token_statuses: Dict[str, TokenStatus] = {}
        self.token_id_map: Dict[str, int] = {}  # pemetaan token -> token_id

        for token_id, token_value, token_type in tokens:
            if token_value and token_value not in self.token_statuses:
                self.token_statuses[token_value] = TokenStatus(
                    token=token_value,
                    token_id=token_id,
                    token_type=token_type
                )
                self.token_id_map[token_value] = token_id

        if not self.token_statuses:
            logger.warning("⚠️ Kumpulan Token kosong, akan bergantung pada mode anonim")

    def get_next_token(self) -> Optional[str]:
        """
        Dapatkan Token pengguna terautentikasi berikutnya yang tersedia (algoritma rotasi)

        Returns:
            String Token yang tersedia, jika tidak ada Token yang tersedia maka kembalikan None
        """
        with self._lock:
            if not self.token_statuses:
                return None

            available_tokens = self._get_available_user_tokens()
            if not available_tokens:
                # Coba pulihkan Token yang gagal kedaluwarsa
                self._try_recover_failed_tokens()
                available_tokens = self._get_available_user_tokens()

                if not available_tokens:
                    logger.warning("⚠️ Tidak ada Token pengguna terautentikasi yang tersedia")
                    return None

            # Pemilihan round-robin
            token = available_tokens[self._current_index % len(available_tokens)]
            self._current_index = (self._current_index + 1) % len(available_tokens)

            return token

    def _get_available_user_tokens(self) -> List[str]:
        """
        Dapatkan daftar Token pengguna terautentikasi yang saat ini tersedia

        Kondisi filter:
        1. is_available = True
        2. token_type == "user"
        """
        available_user_tokens = [
            status.token for status in self.token_statuses.values()
            if status.is_available and status.token_type == "user"
        ]

        # Peringatan: jika ada guest token tapi tidak ada user token
        if not available_user_tokens and self.token_statuses:
            guest_count = sum(
                1 for status in self.token_statuses.values()
                if status.token_type == "guest"
            )
            if guest_count > 0:
                logger.warning(f"⚠️ Mendeteksi {guest_count} Token pengguna anonim, mekanisme rotasi akan melewati Token ini")

        return available_user_tokens

    def _try_recover_failed_tokens(self):
        """Coba pulihkan Token yang gagal (hanya untuk Token pengguna terautentikasi)"""
        current_time = time.time()
        recovered_count = 0

        for status in self.token_statuses.values():
            # Hanya pulihkan Token pengguna terautentikasi
            if (
                status.token_type == "user"
                and not status.is_available
                and current_time - status.last_failure_time > self.recovery_timeout
            ):
                status.is_available = True
                status.failure_count = 0
                recovered_count += 1
                logger.info(f"🔄 Memulihkan Token gagal: {status.token[:20]}...")

        if recovered_count > 0:
            logger.info(f"✅ Memulihkan {recovered_count} Token yang gagal")

    def mark_token_success(self, token: str):
        """Tandai penggunaan Token berhasil"""
        with self._lock:
            if token in self.token_statuses:
                status = self.token_statuses[token]
                status.total_requests += 1
                status.successful_requests += 1
                status.last_success_time = time.time()
                status.failure_count = 0  # Reset penghitung kegagalan

                if not status.is_available:
                    status.is_available = True
                    logger.info(f"✅ Token pulih dan tersedia: {token[:20]}...")

    def mark_token_failure(self, token: str, error: Exception = None):
        """Tandai penggunaan Token gagal"""
        with self._lock:
            if token in self.token_statuses:
                status = self.token_statuses[token]
                status.total_requests += 1
                status.failure_count += 1
                status.last_failure_time = time.time()

                if status.failure_count >= self.failure_threshold:
                    status.is_available = False
                    logger.warning(f"🚫 Token telah dinonaktifkan: {token[:20]}... (gagal {status.failure_count} kali)")

    def get_token_id(self, token: str) -> Optional[int]:
        """Dapatkan ID database Token"""
        return self.token_id_map.get(token)

    def get_pool_status(self) -> Dict:
        """Dapatkan informasi status kumpulan Token"""
        with self._lock:
            available_count = len(self._get_available_user_tokens())
            total_count = len(self.token_statuses)
            healthy_count = sum(1 for status in self.token_statuses.values() if status.is_healthy)

            # Statistik berbagai jenis Token
            user_count = sum(1 for s in self.token_statuses.values() if s.token_type == "user")
            guest_count = sum(1 for s in self.token_statuses.values() if s.token_type == "guest")
            unknown_count = sum(1 for s in self.token_statuses.values() if s.token_type == "unknown")

            status_info = {
                "total_tokens": total_count,
                "available_tokens": available_count,
                "unavailable_tokens": total_count - available_count,
                "healthy_tokens": healthy_count,
                "unhealthy_tokens": total_count - healthy_count,
                "user_tokens": user_count,
                "guest_tokens": guest_count,
                "unknown_tokens": unknown_count,
                "current_index": self._current_index,
                "tokens": []
            }

            for token, status in self.token_statuses.items():
                status_info["tokens"].append({
                    "token": f"{token[:10]}...{token[-10:]}",
                    "token_id": status.token_id,
                    "token_type": status.token_type,
                    "is_available": status.is_available,
                    "failure_count": status.failure_count,
                    "success_count": status.successful_requests,
                    "success_rate": f"{status.success_rate:.2%}",
                    "total_requests": status.total_requests,
                    "is_healthy": status.is_healthy,
                    "last_failure_time": status.last_failure_time,
                    "last_success_time": status.last_success_time
                })

            return status_info

    def update_token_type(self, token: str, token_type: str):
        """Perbarui jenis Token (untuk pembaruan setelah pemeriksaan kesehatan)"""
        with self._lock:
            if token in self.token_statuses:
                old_type = self.token_statuses[token].token_type
                self.token_statuses[token].token_type = token_type

                if old_type != token_type:
                    logger.info(f"🔄 Perbarui jenis Token: {token[:20]}... {old_type} → {token_type}")

    async def health_check_token(self, token: str) -> bool:
        """
        Pemeriksaan kesehatan Token tunggal secara asinkron (menggunakan antarmuka autentikasi resmi Z.AI)

        Args:
            token: Token yang akan diperiksa

        Returns:
            Apakah Token sehat (True = Token pengguna terautentikasi yang valid)
        """
        token_type, is_valid, error_message = await ZAITokenValidator.validate_token(token)

        # Perbarui jenis Token
        self.update_token_type(token, token_type)

        # Perbarui status
        if is_valid:
            self.mark_token_success(token)
        else:
            self.mark_token_failure(token, Exception(error_message or "Validasi gagal"))

        return is_valid

    async def health_check_all(self):
        """Pemeriksaan kesehatan semua Token secara asinkron"""
        if not self.token_statuses:
            logger.warning("⚠️ Kumpulan Token kosong, lewati pemeriksaan kesehatan")
            return

        total_tokens = len(self.token_statuses)
        logger.info(f"🔍 Mulai pemeriksaan kesehatan kumpulan Token... (total {total_tokens} Token)")

        # Eksekusi pemeriksaan kesehatan semua Token secara konkuren
        tasks = [
            self.health_check_token(token)
            for token in self.token_statuses.keys()
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Statistik hasil
        healthy_count = sum(1 for r in results if r is True)
        failed_count = sum(1 for r in results if r is False)
        exception_count = sum(1 for r in results if isinstance(r, Exception))

        health_rate = (healthy_count / total_tokens) * 100 if total_tokens > 0 else 0

        if healthy_count == 0 and total_tokens > 0:
            logger.warning(f"⚠️ Pemeriksaan kesehatan selesai: 0/{total_tokens} Token sehat - Silakan periksa konfigurasi Token")
        elif failed_count > 0:
            logger.warning(f"⚠️ Pemeriksaan kesehatan selesai: {healthy_count}/{total_tokens} Token sehat ({health_rate:.1f}%)")
        else:
            logger.info(f"✅ Pemeriksaan kesehatan selesai: {healthy_count}/{total_tokens} Token sehat")

        if exception_count > 0:
            logger.error(f"💥 {exception_count} Token mengalami pengecualian pemeriksaan")

    async def sync_from_database(self, provider: str = "zai"):
        """
        Sinkronkan status Token dari database (status nonaktif/aktif)

        Args:
            provider: Nama penyedia

        Penjelasan:
            - Baca status aktivasi Token terbaru dari database
            - Jika Token dinonaktifkan dalam database, hapus dari kumpulan
            - Jika ada Token aktif baru dalam database, tambahkan ke kumpulan
            - Pertahankan statistik runtime Token yang ada (jumlah permintaan, tingkat keberhasilan, dll.)
        """
        from app.services.token_dao import get_token_dao

        dao = get_token_dao()

        # Muat semua Token pengguna terautentikasi yang diaktifkan dari database
        token_records = await dao.get_tokens_by_provider(provider, enabled_only=True)

        # Bangun pemetaan Token dalam database
        db_tokens = {
            record["token"]: (record["id"], record.get("token_type", "unknown"))
            for record in token_records
            if record.get("token_type") != "guest"  # Saring Token guest
        }

        with self._lock:
            # 1. Hapus Token yang telah dinonaktifkan dalam database
            tokens_to_remove = []
            for token_value in list(self.token_statuses.keys()):
                if token_value not in db_tokens:
                    tokens_to_remove.append(token_value)

            for token_value in tokens_to_remove:
                del self.token_statuses[token_value]
                del self.token_id_map[token_value]
                logger.info(f"🗑️ Hapus Token yang dinonaktifkan dari kumpulan: {token_value[:20]}...")

            # 2. Tambahkan Token yang baru diaktifkan
            new_tokens_count = 0
            for token_value, (token_id, token_type) in db_tokens.items():
                if token_value not in self.token_statuses:
                    self.token_statuses[token_value] = TokenStatus(
                        token=token_value,
                        token_id=token_id,
                        token_type=token_type
                    )
                    self.token_id_map[token_value] = token_id
                    new_tokens_count += 1
                    logger.info(f"➕ Tambahkan Token yang baru diaktifkan: {token_value[:20]}...")

            # 3. Perbarui jenis Token yang ada (jika ada pembaruan dalam database)
            for token_value, (token_id, token_type) in db_tokens.items():
                if token_value in self.token_statuses:
                    old_type = self.token_statuses[token_value].token_type
                    if old_type != token_type:
                        self.token_statuses[token_value].token_type = token_type
                        logger.info(f"🔄 Perbarui jenis Token: {token_value[:20]}... {old_type} → {token_type}")

            logger.info(
                f"✅ Sinkronisasi kumpulan Token selesai: "
                f"Saat ini {len(self.token_statuses)} Token "
                f"(hapus {len(tokens_to_remove)}, tambah baru {new_tokens_count})"
            )


# ==================== 全局实例管理 ====================


_token_pool: Optional[TokenPool] = None
_pool_lock = Lock()


def get_token_pool() -> Optional[TokenPool]:
    """获取全局 Token 池实例"""
    return _token_pool


async def initialize_token_pool_from_db(
    provider: str = "zai",
    failure_threshold: int = 3,
    recovery_timeout: int = 1800
) -> Optional[TokenPool]:
    """
    Inisialisasi kumpulan Token global dari database

    Args:
        provider: Nama penyedia (zai, k2think, longcat)
        failure_threshold: Ambang kegagalan
        recovery_timeout: Waktu habis pemulihan (detik)

    Returns:
        Instance TokenPool (akan membuat kumpulan kosong bahkan tanpa Token)
    """
    global _token_pool

    from app.services.token_dao import get_token_dao

    dao = get_token_dao()

    # Muat Token dari database (hanya muat Token pengguna terautentikasi yang diaktifkan)
    token_records = await dao.get_tokens_by_provider(provider, enabled_only=True)

    # Konversi ke format yang dibutuhkan TokenPool
    tokens = []
    if token_records:
        tokens = [
            (record["id"], record["token"], record.get("token_type", "unknown"))
            for record in token_records
        ]

        # Filter Token guest (seharusnya tidak ada dalam database, tetapi pemeriksaan defensif)
        user_tokens = [
            (tid, tval, ttype) for tid, tval, ttype in tokens
            if ttype != "guest"
        ]

        if len(user_tokens) < len(tokens):
            guest_count = len(tokens) - len(user_tokens)
            logger.warning(f"⚠️ Memfilter {guest_count} Token pengguna anonim")

        tokens = user_tokens

    # Selalu buat instance kumpulan Token (bahkan jika kosong)
    with _pool_lock:
        _token_pool = TokenPool(tokens, failure_threshold, recovery_timeout)

        if not tokens:
            logger.warning(f"⚠️ {provider} tidak memiliki Token pengguna terautentikasi yang valid, telah membuat kumpulan Token kosong")
        else:
            logger.info(f"🔧 Inisialisasi kumpulan Token dari database ({provider}), total {len(tokens)} Token")

        return _token_pool


async def sync_token_stats_to_db():
    """
    Sinkronkan statistik Token dalam memori ke database

    Harus dipanggil saat layanan ditutup atau secara berkala, untuk memastikan statistik tidak hilang
    """
    pool = get_token_pool()
    if not pool:
        return

    from app.services.token_dao import get_token_dao

    dao = get_token_dao()

    with pool._lock:
        for token, status in pool.token_statuses.items():
            token_id = status.token_id

            # Perbarui statistik database (versi sederhana, implementasi aktual mungkin memerlukan pembaruan inkremental)
            if status.successful_requests > 0:
                for _ in range(status.successful_requests):
                    await dao.record_success(token_id)

            if status.total_requests - status.successful_requests > 0:
                for _ in range(status.total_requests - status.successful_requests):
                    await dao.record_failure(token_id)

    logger.info("✅ Statistik Token telah disinkronkan ke database")
