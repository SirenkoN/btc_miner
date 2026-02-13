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
    Переводит compact-формат `bits` в целевой хеш согласно Bitcoin протоколу.

    Параметры
    ----------
    bits : int | str
        Compact representation of the difficulty target.
        Если строка, она должна быть в hex-формате вида '0x1d00ffff'.

    Возвращает
    -------
    bytes
        32-байтовый целевой хеш в big-endian формате.

    Примечание
    ----------
    Согласно Bitcoin протоколу:
    - Если экспонента <= 3, вычисляем target = coefficient >> (8 * (3 - exponent))
    - Иначе target = coefficient << (8 * (exponent - 3))
    - Проверяем на переполнение (максимум 256 бит)
    """
    if isinstance(bits, str):
        # Убираем префикс '0x', если он есть
        bits = bits.replace('0x', '')
        bits = int(bits, 16)

    # Извлекаем экспоненту и коэффициент
    exponent = bits >> 24
    coefficient = bits & 0x00ffffff

    # Обработка особых случаев согласно Bitcoin протоколу
    if exponent <= 3:
        # Слишком маленькая экспонента
        target = coefficient >> (8 * (3 - exponent))
    else:
        # Обычный случай
        target = coefficient << (8 * (exponent - 3))

    # Проверка на переполнение (максимум 256 бит)
    if target > 2 ** 256 - 1:
        target = 2 ** 256 - 1

    return target.to_bytes(32, 'big')
