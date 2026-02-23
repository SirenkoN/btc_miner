# -*- coding: utf-8 -*-
"""
Сборщик полных блоков для Bitcoin-майнера.
Содержит логику сериализации блока для отправки ноде.
"""

from utils import encode_varint, create_raw_coinbase_transaction


def build_full_block(header: bytes, template: dict, wallet_address: str) -> bytes:
    """
    Собирает полный блок из заголовка и транзакций.

    Args:
        header (bytes): Сериализованный заголовок (80 байт) с nonce.
        template (dict): Результат `getblocktemplate`.
        wallet_address (str): Адрес кошелька майнера

    Returns:
        bytes: Полный сериализованный блок для отправки.
    """
    # 1. Полный заголовок блока (80 байт): 76 байт основного заголовка + 4 байта nonce
    block = header

    # 2. Добавление количества транзакций как varint
    # Coinbase + остальные транзакции
    tx_count = 1 + len(template.get('transactions', []))
    block += encode_varint(tx_count)

    # 3. Добавление coinbase транзакции
    raw_coinbase = create_raw_coinbase_transaction(wallet_address, template)
    block += raw_coinbase

    # 4. Добавление остальных транзакций
    for tx in template.get('transactions', []):
        # В шаблоне от getblocktemplate каждая транзакция имеет поле 'data'
        tx_data = bytes.fromhex(tx['data'])
        block += tx_data

    return block
