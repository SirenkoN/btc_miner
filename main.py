# -*- coding: utf-8 -*-
"""
Точка входа для Bitcoin-майнера версии 0.2.
Обновление структуры - разделение на компоненты для соблюдения SRP.
Базовая структура без автообновления задания.
"""

from config import RPC_USER, RPC_PASSWORD, RPC_HOST, RPC_PORT, WALLET_ADDRESS, GPU_ENABLED
from rpc_client import rpc_call
from utils import double_sha256, target_from_bits
from block_builder import build_block_header


# ------------------------------------------------------------------
# 1. Поиск подходящего nonce
# ------------------------------------------------------------------
def mine_block(template: dict):
    """
    Ищет nonce, удовлетворяющий target для заданного блока-template.

    Параметры
    ----------
    template : dict
        Данные от `getblocktemplate`.

    Возвращает
    -------
    tuple[int, bytes] | None
        (nonce, block_header) при успехе; ``None`` – если не найден.
    """
    target_bytes = target_from_bits(template['bits'])
    target_int   = int.from_bytes(target_bytes, 'big')

    nonce     = 0
    max_nonce = 2 ** 32 - 1

    print("[INFO] Начинаем поиск nonce…")

    while nonce <= max_nonce:
        header   = build_block_header(template, nonce)
        hash_val = double_sha256(header)

        # В Bitcoin хеш считается в обратном порядке байт.
        if int.from_bytes(hash_val[::-1], 'big') < target_int:
            print(f"[SUCCESS] Найден подходящий nonce: {nonce}")
            return nonce, header

        nonce += 1

    print("[WARN] Не удалось найти nonce в пределах диапазона.")
    return None

# ------------------------------------------------------------------
# 2. Отправка блока в сеть
# ------------------------------------------------------------------
def submit_block(header: bytes) -> bool:
    """
    Отправляет заголовок блока в ноду через RPC.

    Параметры
    ----------
    header : bytes
        Сериализованный заголовок (80 байт).

    Возвращает
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
# 3. Основная функция
# ------------------------------------------------------------------
def main():
    """
    Точка входа для майнера.

    Пошаговый процесс:
      1. Запрашиваем блок-template от ноды.
      2. Ищем nonce, удовлетворяющий target.
      3. Отправляем найденный блок в сеть.
    """
    print("=== Bitcoin-майнер (версия 0.2) ===")
    print("Майнер запущен")

    # Получаем шаблон блока
    try:
        # Передаём объект-параметр с правилом segwit.
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
# 4. Запуск скрипта
# ------------------------------------------------------------------
if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"[FATAL] Произошла ошибка при запуске майнера: {e}")
        exit(1)