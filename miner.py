#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# --------------------------------------------------------------
# Bitcoin‑майнер (версия 0.1) – простой solo‑майнер на Python,
# использующий для хэширования только CPU.
# --------------------------------------------------------------

__version__ = "0.1"

import hashlib  # SHA‑256 хеширование
import time  # таймеры и текущий UNIX‑timestamp
import requests  # HTTP‑запросы к RPC‑серверу

# ------------------------------------------------------------------
# 1. Конфигурация ноды
# ------------------------------------------------------------------
RPC_USER = "your_rpc_user"  # имя пользователя RPC
RPC_PASSWORD = "your_rpc_password"  # пароль RPC
RPC_HOST = "127.0.0.1"  # адрес ноды
RPC_PORT = 8332  # порт JSON‑RPC

# Создаём сессию, чтобы повторно использовать соединение.
session = requests.Session()
session.auth = (RPC_USER, RPC_PASSWORD)


# ------------------------------------------------------------------
# 2. Утилита RPC
# ------------------------------------------------------------------
def rpc_call(method: str, params=None) -> dict:
    """
    Выполняет JSON‑RPC вызов к локальной ноде и возвращает `result`.

    Parameters
    ----------
    method : str
        Имя метода (например, 'getblocktemplate').
    params : list | dict | None
        Параметры метода. Если ``None`` – передаётся пустой список.

    Returns
    -------
    dict
        Результат RPC в виде Python‑объекта.
    """
    url = f"http://{RPC_HOST}:{RPC_PORT}"
    payload = {
        "jsonrpc": "1.0",
        "id": 1,
        "method": method,
        "params": params or []
    }

    try:
        resp = session.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()

        if data.get("error"):
            raise RuntimeError(f"{method} error: {data['error']}")

        return data["result"]
    except Exception as exc:
        print(f"[ERROR] RPC вызов {method} не выполнен: {exc}")
        raise


# ------------------------------------------------------------------
# 3. Хеширование блока
# ------------------------------------------------------------------
def double_sha256(data: bytes) -> bytes:
    """Возвращает двойной SHA‑256 хеш входных данных."""
    return hashlib.sha256(hashlib.sha256(data).digest()).digest()


# ------------------------------------------------------------------
# 4. Целевой target из bits
# ------------------------------------------------------------------
def target_from_bits(bits):
    """
    Переводит compact‑формат `bits` (см. BIP 0032) в целевой хеш.

    Parameters
    ----------
    bits : int | str
        Компактное представление уровня сложности.
        Если строка, она должна быть в hex‑формате вида '0x1d00ffff'.

    Returns
    -------
    bytes
        32‑байтовый целевой хеш в big‑endian формате.
    """
    if isinstance(bits, str):
        bits = int(bits, 16)

    exp = bits >> 24  # экспонента – верхние 8 бит
    coeff = bits & 0xffffff  # коэффициент – нижние 24 бит
    target_int = coeff << (8 * (exp - 3))
    return target_int.to_bytes(32, byteorder='big')


# ------------------------------------------------------------------
# 5. Формирование заголовка блока
# ------------------------------------------------------------------
def build_block_header(template: dict, nonce: int) -> bytes:
    """
    Составляем заголовок блока из шаблона и заданного nonce.

    Parameters
    ----------
    template : dict
        Результат `getblocktemplate`.
    nonce : int
        Текущий пробный nonce.

    Returns
    -------
    bytes
        Сериализованный заголовок (80 байт).
    """
    version = template['version'].to_bytes(4, 'little')

    # previousblockhash и txid приходят как hex‑строки.
    prev_hash = bytes.fromhex(template['previousblockhash'])[::-1]
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


# ------------------------------------------------------------------
# 6. Поиск подходящего nonce
# ------------------------------------------------------------------
def mine_block(template: dict):
    """
    Ищет nonce, удовлетворяющий target для заданного шаблона блока.

    Parameters
    ----------
    template : dict
        Данные от `getblocktemplate`.

    Returns
    -------
    tuple[int, bytes] | None
        (nonce, block_header) при успехе; ``None`` – если не найден.
    """
    target_bytes = target_from_bits(template['bits'])
    target_int = int.from_bytes(target_bytes, 'big')

    nonce = 0
    max_nonce = 2 ** 32 - 1

    print("[INFO] Начинаем поиск nonce…")

    while nonce <= max_nonce:
        header = build_block_header(template, nonce)
        hash_val = double_sha256(header)

        # В Bitcoin хеш считается в обратном порядке байт.
        if int.from_bytes(hash_val[::-1], 'big') < target_int:
            print(f"[SUCCESS] Найден подходящий nonce: {nonce}")
            return nonce, header

        nonce += 1

    print("[WARN] Не удалось найти nonce в пределах диапазона.")
    return None


# ------------------------------------------------------------------
# 7. Отправка блока в сеть
# ------------------------------------------------------------------
def submit_block(header: bytes) -> bool:
    """
    Отправляет заголовок блока в ноду через RPC.

    Parameters
    ----------
    header : bytes
        Сериализованный заголовок (80 байт).

    Returns
    -------
    bool
        ``True`` – если блок принят; ``False`` – иначе.
    """
    block_hex = header.hex()
    result = rpc_call('submitblock', [block_hex])

    if result is None:
        print("[INFO] Блок успешно отправлен в сеть.")
        return True

    print(f"[ERROR] submitblock вернул: {result}")
    return False


# ------------------------------------------------------------------
# 8. Основная функция
# ------------------------------------------------------------------
def main():
    """
    Точка входа для майнера.

    Пошаговый процесс:
      1. Запрашиваем блок‑template от ноды.
      2. Ищем nonce, удовлетворяющий target.
      3. Отправляем найденный блок в сеть.
    """
    print("=== Bitcoin‑майнер (версия 0.1) ===")

    # Получаем шаблон блока
    try:
        # Передаём объект‑параметр с правилом segwit.
        template = rpc_call('getblocktemplate', [{"rules": ["segwit"]}])
    except Exception as exc:
        print(f"[FATAL] Не удалось получить шаблон: {exc}")
        return

    # Ищем nonce
    result = mine_block(template)
    if not result:
        print("[EXIT] Поиск nonce завершился без результата.")
        return

    nonce, header = result

    # Отправляем блок
    submit_block(header)


# ------------------------------------------------------------------
# 9. Запуск скрипта
# ------------------------------------------------------------------
if __name__ == "__main__":
    main()
