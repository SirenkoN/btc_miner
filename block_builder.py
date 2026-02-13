# -*- coding: utf-8 -*-
"""
Сборщик заголовков блоков для Bitcoin-майнера.
Содержит логику сериализации заголовка блока.
"""

import time


def build_block_header(template: dict, nonce: int) -> bytes:
    """
    Составляет заголовок блока из шаблона и заданного nonce.

    Параметры
    ----------
    template : dict
        Результат `getblocktemplate`.
    nonce : int
        Текущий пробный nonce.

    Возвращает
    -------
    bytes
        Сериализованный заголовок (80 байт).

    Примечание
    ----------
    - Используем время из шаблона вместо текущего системного времени
    - Корректируем время в пределах допустимого отклонения (±2 часа)
    - Обрабатываем случай, когда время в шаблоне отсутствует
    """
    version = template['version'].to_bytes(4, 'little')

    # previousblockhash приходит как hex-строка.
    prev_hash = bytes.fromhex(template['previousblockhash'])[::-1]

    # merkle_root формируется из txid первой транзакции.
    merkle_root = bytes.fromhex(template['transactions'][0]['txid'])[::-1]

    # Используем время из шаблона с корректировкой
    current_time = template.get('curtime', int(time.time()))

    # Правила Bitcoin: время блока должно быть:
    # - Не больше чем на 2 часа вперед от системного времени
    # - Не больше чем на 2 часа назад от системного времени
    max_time_offset = 7200  # 2 часа в секундах
    system_time = int(time.time())
    corrected_time = max(system_time - max_time_offset,
                         min(system_time + max_time_offset, current_time))
    time_sec = corrected_time.to_bytes(4, 'little')

    # bits – возможно строка; преобразуем к int.
    bits_int = template['bits']
    if isinstance(bits_int, str):
        bits_int = int(bits_int, 16)
    bits = bits_int.to_bytes(4, 'little')

    nonce_b = nonce.to_bytes(4, 'little')

    return (
            version + prev_hash + merkle_root +
            time_sec + bits + nonce_b
    )
