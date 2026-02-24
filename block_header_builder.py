# -*- coding: utf-8 -*-
"""
Сборщик заголовков блоков для Bitcoin-майнера.
Содержит логику сериализации заголовка блока.
"""

import time
from config import WALLET_ADDRESS
from utils import calculate_merkle_root


def build_block_header(
        template: dict
) -> bytes:
    """
    Составляет заголовок блока из шаблона без nonce.

    Использование времени из шаблона вместо текущего системного времени.
    Корректировка времени в пределах допустимого отклонения (±2 часа).
    Обработка случая, когда время в шаблоне отсутствует.

    Args:
        template (dict): Результат `getblocktemplate`.

    Returns:
        bytes: Сериализованный заголовок (76 байт, без nonce).
    """
    version = template['version'].to_bytes(4, 'little')

    # previousblockhash приходит как строка в шестнадцатеричном формате (hex).
    prev_hash = bytes.fromhex(template['previousblockhash'])[::-1]

    # merkle_root формируется из coinbase транзакции и транзакций mempool'а.
    merkle_root = calculate_merkle_root(WALLET_ADDRESS, template)

    # Использование времени из шаблона с корректировкой
    current_time = template.get('curtime', int(time.time()))

    # Правила Bitcoin: время блока должно быть:
    # - Не больше чем на 2 часа вперед от системного времени
    # - Не больше чем на 2 часа назад от системного времени
    max_time_offset = 7200  # 2 часа в секундах
    median_time = template.get('mediantime', int(time.time()))
    corrected_time = max(median_time - max_time_offset,
                         min(median_time + max_time_offset, current_time))
    time_sec = corrected_time.to_bytes(4, 'little')

    # bits – возможно строка; преобразование к int.
    bits_int = template['bits']
    if isinstance(bits_int, str):
        bits_int = int(bits_int, 16)
    bits = bits_int.to_bytes(4, 'little')

    return (
            version + prev_hash + merkle_root +
            time_sec + bits
    )
