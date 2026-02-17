# -*- coding: utf-8 -*-
"""
Точка входа для Bitcoin-майнера версии 0.5.
Изменение логики отправки найденного блока ноде.
Вместо заголовка блока ноде отправляется полный блок, включающий все транзакции.
Добавлено информирование о скорости хэширования.
"""

import time
from random import getrandbits

from config import NONCE_CHUNK_SIZE, CHECK_INTERVAL, WALLET_ADDRESS
from rpc_client import rpc_call, get_block_template
from utils import double_sha256, target_from_bits
from block_header_builder import build_block_header
from full_block_builder import build_full_block


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
    tuple[int, bytes, dict] or None
        (nonce, block_header, template) при успехе; None – если не найден.
    """
    target_bytes = target_from_bits(template['bits'])
    target_int = int.from_bytes(target_bytes, 'big')

    nonce_counter = 0

    print(f"[INFO] Поиск nonce для блока {template['height']}...")

    header = build_block_header(template)

    start_chunk_time = time.time()

    while nonce_counter <= NONCE_CHUNK_SIZE:
        # В биткоин Nonce — это 4-байтовое (32-битное) поле
        nonce = getrandbits(32)
        header_with_nonce = header + nonce.to_bytes(4, 'little')
        hash_val = double_sha256(header_with_nonce)

        # В Bitcoin хеш интерпретируется как little-endian целое число при сравнении
        if int.from_bytes(hash_val, 'little') < target_int:
            print(f"[SUCCESS] Найден подходящий nonce: {nonce}")
            return nonce, header_with_nonce, template

        nonce_counter += 1

    heshing_speed = NONCE_CHUNK_SIZE / (time.time() - start_chunk_time)  # Расчет скорости хэширования

    print(f"[INFO] Не удалось найти nonce в пределах диапазона. Cкорость хэширования {int(heshing_speed)} h/s")
    return None


# ------------------------------------------------------------------
# 2. Отправка блока в сеть
# ------------------------------------------------------------------
def submit_block(header: bytes, template: dict, wallet_address: str) -> bool:
    """
    Отправляет полный блок ноде через RPC.

    Parameters
    ----------
    header : bytes
        Сериализованный заголовок (80 байт) с nonce.
    template : dict
        Шаблон блока, использованный для создания заголовка.
    wallet_address : str
        Адрес кошелька майнера

    Returns
    -------
    bool
        True – если блок принят; False – иначе.
    """
    # Собираем полный блок
    full_block = build_full_block(header, template, wallet_address)
    block_hex = full_block.hex()

    result = rpc_call('submitblock', [block_hex])

    if result is None:
        print(f"[SUCCESS] Блок {template['height']} успешно отправлен и принят сетью.")
        return True

    print(f"[ERROR] submitblock вернул ошибку: {result}")
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
    print("=== Bitcoin-майнер (версия 0.5) ===")
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
                nonce, header, used_template = result
                submit_block(header, used_template, WALLET_ADDRESS)

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
