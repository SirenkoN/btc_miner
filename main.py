# -*- coding: utf-8 -*-
"""
Точка входа для Bitcoin-майнера версии 0.3.
Реализация автообновления задания.
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
    target_int = int.from_bytes(target_bytes, 'big')

    nonce_counter = 0

    print(f"[INFO] Начинаем поиск nonce для блока {template['height']}...")

    while nonce_counter <= NONCE_CHUNK_SIZE:
        # В биткоин Nonce — это 4-байтовое (32-битное) поле
        nonce = getrandbits(32)
        header = build_block_header(template, nonce)
        hash_val = double_sha256(header)

        # В Bitcoin хеш интерпретируется как little-endian целое число при сравнении
        if int.from_bytes(hash_val, 'little') < target_int:
            print(f"[SUCCESS] Найден подходящий nonce: {nonce}")
            return nonce, header

        nonce_counter += 1

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
def run_miner():
    """
    Основной цикл майнера с автообновлением задания.

    Особенности реализации:
    - Кэширование текущего шаблона блока
    - Отслеживание previousblockhash для обнаружения новых блоков в сети
    - Проверка высоты блока для определения обновлений цепочки
    - Эффективное использование ресурсов (не запрашиваем новый шаблон каждый раз)
    """
    print("=== Bitcoin-майнер (версия 0.3) ===")
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
                    # Проверяем, изменился ли предыдущий хеш (означает появление нового блока в сети)
                    if new_template['previousblockhash'] != current_template['previousblockhash']:
                        print(f"[INFO] Обнаружен новый блок в сети. "
                              f"Старый хеш: {current_template['previousblockhash'][:10]}..., "
                              f"Новый хеш: {new_template['previousblockhash'][:10]}...")
                        should_update = True
                    # Проверяем, увеличилась ли высота блока
                    elif new_template['height'] > current_template['height']:
                        print(f"[INFO] Высота блока увеличилась с {current_template['height']} "
                              f"до {new_template['height']}. Обновляем шаблон.")
                        should_update = True

            # Обновляем шаблон при необходимости
            if should_update:
                current_template = get_block_template()
                print(f"[INFO] Получен новый шаблон блока. Высота: {current_template['height']}, "
                      f"Целевая сложность: {current_template['bits']}")

            # Майнинг текущего шаблона
            if current_template:
                # Перед майнингом проверяем, не устарел ли шаблон
                current_block_template = get_block_template()
                if (current_template['previousblockhash'] != current_block_template['previousblockhash'] or
                        current_template['height'] < current_block_template['height']):
                    print("[INFO] Шаблон устарел во время поиска nonce. Пропускаем текущий цикл.")
                    current_template = None
                    continue

                result = mine_block(current_template)
                if result:
                    if (current_template['previousblockhash'] == current_block_template['previousblockhash'] and
                            current_template['height'] == current_block_template['height']):
                        submit_block(result[1])
                    else:
                        print("[WARN] Шаблон устарел перед отправкой. Пропускаем отправку.")
            else:
                # Ждем получения первого шаблона
                time.sleep(0.1)

        except Exception as e:
            print(f"[ERROR] {str(e)}")

        # Небольшая задержка для снижения нагрузки на CPU
        time.sleep(0.01)


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
