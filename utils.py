# -*- coding: utf-8 -*-
"""
Утилиты для Bitcoin-майнера.
Содержит вспомогательные функции хеширования и работы с целевыми значениями.
"""

import hashlib  # SHA-256 хеширование
import struct
import bech32
import base58


def double_sha256(data: bytes) -> bytes:
    """
    Возвращает двойной SHA-256 хеш входных данных.

    Args:
        data (bytes): Входные данные для хеширования.

    Returns:
        bytes: Двойной SHA-256 хеш в виде байтов.
    """
    return hashlib.sha256(hashlib.sha256(data).digest()).digest()


def target_from_bits(bits):
    """
    Переводит compact-формат `bits` в целевой хеш согласно Bitcoin протоколу.

    Согласно Bitcoin протоколу:
    - Если экспонента <= 3, вычисление target = coefficient >> (8 * (3 - exponent))
    - Иначе target = coefficient << (8 * (exponent - 3))
    - Проверка на переполнение (максимум 256 бит)

    Args:
        bits (int | str): Компактное представление целевой сложности.
            Если строка, она должна быть в hex-формате вида '0x1d00ffff'.

    Returns:
        bytes: 32-байтовый целевой хеш в big-endian формате.
    """
    if isinstance(bits, str):
        # Обработка префикса '0x', при наличии
        bits = bits.replace('0x', '')
        bits = int(bits, 16)

    # Извлечение экспоненты и коэффициента
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


def calculate_merkle_root(address, template):
    """
    Вычисляет Merkle Root и возвращает его в виде BYTES (Little-Endian), готовых для сборки заголовка блока.

    Args:
        address (str): Адрес получения вознаграждения за майнинг.
        template (dict): Шаблон блока от getblocktemplate.

    Returns:
        bytes: Merkle Root в формате little-endian (32 байта), готовый для включения в заголовок блока.
    """
    # 1. Получение сырой coinbase транзакцию и вычисление её хеша
    raw_coinbase = create_raw_coinbase_transaction(address, template)
    # Вычисление хеша и разворот байтов для формата little-endian (как хранится в блоке)
    cb_tx_hash = double_sha256(raw_coinbase)[::-1]

    # 2. Сборка списка всех TXID в байтах (Little-Endian)
    nodes = [cb_tx_hash]

    for tx in template.get('transactions', []):
        # В template txid — это hex-строка (Big-Endian).
        # Перевод в байты и разворот в Little-Endian.
        txid_bytes = bytes.fromhex(tx['txid'])[::-1]
        nodes.append(txid_bytes)

    # 3. Построение merkle tree
    if not nodes:
        return b"\x00" * 32

    while len(nodes) > 1:
        if len(nodes) % 2 != 0:
            nodes.append(nodes[-1])

        new_level = []
        for i in range(0, len(nodes), 2):
            # Конкатенация байтов + двойной SHA256
            combined = nodes[i] + nodes[i + 1]
            # Результат хеширования используется как есть (32 байта)
            new_level.append(double_sha256(combined))
        nodes = new_level

    # 4. Результат: единственный элемент списка (32 байта)
    return nodes[0]


def encode_varint(n):
    """
    Кодирует целое число в формат varint, используемый в протоколе Bitcoin.

    Varint используется для эффективного представления целых чисел переменной длины.
    Формат позволяет экономить пространство в сетевом трафике.

    Args:
        n (int): Целочисленное значение для кодирования.

    Returns:
        bytes: Сериализованное значение в формате varint, соответствующее правилам Bitcoin:
            * Если n < 0xfd: 1 байт (значение)
            * Если n <= 0xffff: 3 байта (0xfd + 2-байтовое значение)
            * Если n <= 0xffffffff: 5 байт (0xfe + 4-байтовое значение)
            * Если n <= 0xffffffffffffffff: 9 байт (0xff + 8-байтовое значение)
    """
    if n < 0xfd:
        return struct.pack("<B", n)
    elif n <= 0xffff:
        return b"\xfd" + struct.pack("<H", n)
    elif n <= 0xffffffff:
        return b"\xfe" + struct.pack("<I", n)
    else:
        return b"\xff" + struct.pack("<Q", n)


def decode_address_to_hash(address):
    """
    Декодирует Bitcoin-адрес в хеш публичного ключа (pubkey hash).

    Функция поддерживает все основные типы Bitcoin-адресов и корректно обрабатывает
    различия в кодировании между ними. Для Bech32 адресов выполняется 5-битная конвертация
    в 8-битные данные и извлечение witness программ.

    Args:
        address (str): Bitcoin-адрес в любом поддерживаемом формате:
            * P2PKH (начинается с '1')
            * P2SH (начинается с '3')
            * Bech32 P2WPKH (начинается с 'bc1q')

    Returns:
        bytes: 20-байтовый хеш публичного ключа в формате, подходящем для использования
            в скриптах транзакций (байтовый порядок соответствует сети Bitcoin)

    Raises:
        ValueError: При некорректном формате адреса или неверной контрольной сумме
    """
    address = address.lower().strip()

    if address.startswith('bc1q'):
        hrp, data = bech32.decode('bc', address)
        if data is None:
            raise ValueError(f"Неверная контрольная сумма Bech32: {address}")

        # data[0] - это witness version (0)
        # data[1:] - это 5-битные данные.
        # Нужно превратить в 8-битные (20 байт хеша)

        res = []
        acc = 0
        bits = 0
        # Стандартный алгоритм конвертации 5to8
        for value in data[1:]:
            acc = (acc << 5) | value
            bits += 5
            while bits >= 8:
                bits -= 8
                res.append((acc >> bits) & 0xff)

        # Обработка остаточных битов
        if bits > 0:
            res.append((acc << (8 - bits)) & 0xff)

        # Для P2WPKH (bc1q + 38 символов) должно получиться ровно 20 байт
        pubkey_hash = bytes(res[:20])
        return pubkey_hash

    # Для старых адресов (1... и 3...)
    return base58.b58decode_check(address)[1:21]


def create_raw_coinbase_transaction(address, template, extranonce_hex="0000"):
    """
    Генерирует сырую coinbase транзакцию без хеширования.

    Автоматически определяет тип адреса и формирует соответствующий скрипт.
    Включает высоту блока в scriptsig согласно правилам coinbase.
    Поддерживает SegWit через добавление witness commitment при наличии.
    Соблюдает требования протокола к формату coinbase транзакции.
    Для P2WPKH адресов использует формат OP_0 + pushdata.

    Args:
        address (str): Адрес получателя вознаграждения в поддерживаемом формате
        template (dict): Шаблон блока от getblocktemplate, содержащий:
            * coinbasevalue: сумма вознаграждения
            * height: высота блока
            * default_witness_commitment: опциональный commitment для SegWit
        extranonce_hex (str, optional): Дополнительное поле для включения в scriptsig (по умолчанию "0000")

    Returns:
        bytes: Сериализованная сырая coinbase транзакция, готовая к включению в блок
    """
    # 1. Извлечение данных
    value_satoshi = int(template['coinbasevalue'])
    block_height = int(template['height'])
    witness_commitment_hex = template.get('default_witness_commitment', '')

    # 2. Формирование Version (байты)
    tx = struct.pack("<I", 2)

    # 3. Inputs
    tx += b"\x01"  # input count
    tx += b"\x00" * 32  # prev txid
    tx += b"\xff\xff\xff\xff"  # vout index

    # ScriptSig (Height + ExtraNonce)
    height_bytes = block_height.to_bytes((block_height.bit_length() + 7) // 8, 'little')
    scriptsig_content = bytes([len(height_bytes)]) + height_bytes + bytes.fromhex(extranonce_hex)
    tx += encode_varint(len(scriptsig_content)) + scriptsig_content
    tx += b"\xff\xff\xff\xff"  # sequence

    # 4. Outputs
    has_witness = len(witness_commitment_hex) > 0
    tx += encode_varint(2 if has_witness else 1)

    # Output 1: Награда
    pubkey_hash = decode_address_to_hash(address)

    if address.startswith('1'):
        script = b"\x76\xa9\x14" + pubkey_hash + b"\x88\xac"
    elif address.startswith('3'):
        script = b"\xa9\x14" + pubkey_hash + b"\x87"
    elif address.startswith('bc1q'):
        # Формат для P2WPKH: OP_0 <20-byte-key-hash>
        script = b"\x00" + bytes([len(pubkey_hash)]) + pubkey_hash
    else:
        raise ValueError(f"Unsupported address format: {address}")

    tx += struct.pack("<Q", value_satoshi)
    tx += encode_varint(len(script)) + script

    # Output 2: SegWit Commitment
    if has_witness:
        commitment_script = bytes.fromhex("6a24aa21a9ed") + bytes.fromhex(witness_commitment_hex)
        tx += struct.pack("<Q", 0)
        tx += encode_varint(len(commitment_script)) + commitment_script

    # 5. Locktime
    tx += b"\x00\x00\x00\x00"

    return tx
