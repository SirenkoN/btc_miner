# -*- coding: utf-8 -*-
"""
Сборщик заголовков блоков для Bitcoin-майнера.
Содержит логику сериализации заголовка блока.
"""

import time
from config import WALLET_ADDRESS
from utils import double_sha256


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
    """
    version = template['version'].to_bytes(4, 'little')

    # previousblockhash приходит как hex-строка.
    prev_hash = bytes.fromhex(template['previousblockhash'])[::-1]

    # merkle_root формируется из txid первой транзакции.
    merkle_root = bytes.fromhex(template['transactions'][0]['txid'])[::-1]

    time_sec = int(time.time()).to_bytes(4, 'little')

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