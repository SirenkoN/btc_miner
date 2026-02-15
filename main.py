# -*- coding: utf-8 -*-
"""
Точка входа для Bitcoin-майнера версии 0.4.
Реализация создания coinbase транзакция и расчета merkle root, включающего все транзакции из mempool'а.
"""

import time
from random import getrandbits

from config import NONCE_CHUNK_SIZE, CHECK_INTERVAL
from rpc_client import rpc_call, get_block_template
from utils import double_sha256, target_from_bits
from block_builder import build_block_header


# ------------------------------------------------------------------
# 1. Поиск подходящего nonce
# ------------------------------------------------------------------
def mine_block(template: dict):
    """
    Ищет nonce, удовлетворяющий target для заданного блока.

    Parameters
    ----------
    template : dict
        Данные от `getblocktemplate`.

    Returns
    -------
    tuple[int, bytes] or None
        (nonce, block_header) при успехе; None – если не найден.
    """
    target_bytes = target_from_bits(template['bits'])
    target_int = int.from_bytes(target_bytes, 'big')

    nonce_counter = 0

    print(f"[INFO] Начинаем поиск nonce для блока {template['height']}...")

    header = build_block_header(template)

    while nonce_counter <= NONCE_CHUNK_SIZE:
        # В биткоин Nonce — это 4-байтовое (32-битное) поле
        nonce = getrandbits(32)
        header_with_nonce = header + nonce.to_bytes(4, 'little')
        hash_val = double_sha256(header_with_nonce)

        # В Bitcoin хеш интерпретируется как little-endian целое число при сравнении
        if int.from_bytes(hash_val, 'little') < target_int:
            print(f"[SUCCESS] Найден подходящий nonce: {nonce}")
            return nonce, header_with_nonce

        nonce_counter += 1

    print("[WARN] Не удалось найти nonce в пределах диапазона.")
    return None


# ------------------------------------------------------------------
# 2. Отправка блока в сеть
# ------------------------------------------------------------------
def submit_block(header: bytes) -> bool:
    """
    Отправляет заголовок блока ноде через RPC.

    Parameters
    ----------
    header : bytes
        Сериализованный заголовок (80 байт).

    Returns
    -------
    bool
        True – если блок принят; False – иначе.
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
def run_miner():
    """
    Основной цикл майнера с автообновлением задания.

    Notes
    -----
    - Создается coinbase транзакция из представленного пользователем адреса и ответа ноды
    - Создается merkle tree и вычисляется merkle root
    - Оптимизация: заголовок блока без nonce вычисляется один раз для проверки всего диапазона NONCE_CHUNK_SIZE (а не для каждого nonce, как раньше)
    - Оптимизация: кэширование текущего шаблона блока
    - Проверка высоты блока для определения обновлений цепочки
    """
    print("=== Bitcoin-майнер (версия 0.4) ===")
    print("Майнер запущен")

    # Переменные для отслеживания актуальности шаблона
    current_template = None
    last_check_time = 0

    while True:
        try:
            current_time = time.time()

            # Проверяем, нужно ли обновить шаблон (с ограничением по частоте проверок)
            should_update = False

            # Первый запуск или прошло достаточно времени с последней проверки
            if current_template is None or (current_time - last_check_time) >= CHECK_INTERVAL:
                # Получаем текущий шаблон для сравнения
                new_template = get_block_template()
                last_check_time = current_time

                if current_template is None:
                    # Первый запуск
                    should_update = True
                else:
                    if new_template['height'] > current_template['height']:
                        print(f"[INFO] Высота блока увеличилась с {current_template['height']} "
                              f"до {new_template['height']}. Обновляем шаблон.")
                        should_update = True

            # Обновляем шаблон при необходимости
            if should_update:
                current_template = get_block_template()
                print(f"[INFO] Получен новый шаблон блока. Высота: {current_template['height']}, "
                      f"Целевая сложность: {current_template['bits']}")

            # Майнинг текущего шаблона
            result = mine_block(current_template)
            if result:
                    submit_block(result[1])

        except Exception as e:
            print(f"[ERROR] {str(e)}")


# ------------------------------------------------------------------
# 4. Запуск скрипта
# ------------------------------------------------------------------
if __name__ == "__main__":
    try:
        run_miner()
    except KeyboardInterrupt:
        print("\n[INFO] Майнер остановлен пользователем.")
    except Exception as e:
        print(f"[FATAL] Произошла ошибка при запуске майнера: {e}")
        exit(1)
