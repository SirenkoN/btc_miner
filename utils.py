# -*- coding: utf-8 -*-
"""
Утилиты для Bitcoin-майнера.
Содержит вспомогательные функции хеширования и работы с целевыми значениями.
"""

import hashlib  # SHA-256 хеширование


def double_sha256(data: bytes) -> bytes:
    """
    Возвращает двойной SHA-256 хеш входных данных.

    Параметры
    ----------
    data : bytes
        Входные данные для хеширования.

    Возвращает
    -------
    bytes
        Двойной SHA-256 хеш в виде байтов.
    """
    return hashlib.sha256(hashlib.sha256(data).digest()).digest()


def target_from_bits(bits):
    """
    Переводит compact-формат `bits` (см. BIP 0032) в целевой хеш.

    Параметры
    ----------
    bits : int | str
        Compact representation of the difficulty target.
        Если строка, она должна быть в hex-формате вида '0x1d00ffff'.

    Возвращает
    -------
    bytes
        32-байтовый целевой хеш в big-endian формате.
    """
    if isinstance(bits, str):
        bits = int(bits, 16)

    exp = bits >> 24  # экспонента – верхние 8 бит
    coeff = bits & 0xffffff  # коэффициент – нижние 24 бит
    target_int = coeff << (8 * (exp - 3))
    return target_int.to_bytes(32, byteorder='big')