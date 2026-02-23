# -*- coding: utf-8 -*-
"""
Точка входа для Bitcoin-майнера версия 0.6
Реализован параллельный майнинг на нескольких ядрах CPU с использованием multiprocessing
"""

import time
import multiprocessing as mp
from threading import Thread
import struct
import random
import copy
from typing import Dict, Any

# Импорты из проекта
from config import CHECK_INTERVAL, WALLET_ADDRESS, WORKER_COUNT, NONCE_CHUNK_SIZE
from rpc_client import rpc_call, get_block_template
from block_header_builder import build_block_header
from full_block_builder import build_full_block
from utils import double_sha256, target_from_bits


def worker_process(worker_id: int,
                   input_slots: Any,
                   stats_array: Any,
                   result_slot: Any,
                   result_lock: Any):
    """
    Поиск подходящего nonce для майнинга блока в параллельном режиме.

    Worker запускается в отдельном дочернем процессе и выполняет следующие действия:
    1. Периодически проверяет shared memory на наличие нового задания
    2. Для каждого задания обрабатывает свой диапазон nonce согласно алгоритму распределения нагрузки
    3. Вычисляет хеш для комбинации заголовка и nonce
    4. Сравнивает полученный хеш с целевым значением
    5. При успешном нахождении подходящего nonce сохраняет результат в shared memory

    Args:
        worker_id (int): Уникальный идентификатор worker процесса для распределения диапазонов nonce
        input_slots (Any): Область shared memory, содержащая текущие задачи для worker'ов (id_task, заголовок, target)
        stats_array (Any): Область shared memory для сбора статистики по количеству обработанных nonce
        result_slot (Any): Область shared memory для передачи найденного решения (id_task и nonce)
        result_lock (Any): Mutex для синхронизации доступа к result_slot

    Returns:
        None: Функция ничего не возвращает, работает как бесконечный цикл в фоновом процессе.
    """
    # Константы
    SLOT_SIZE = 8 + 76 + 32  # id_task (8B) + header (76B) + target (32B)
    FULL_NONCE_SPACE = 0x100000000  # 2^32 (4294967296)

    # Определение фиксированного диапазона для воркера
    chunk_size_per_worker = FULL_NONCE_SPACE // WORKER_COUNT
    start_nonce = worker_id * chunk_size_per_worker
    end_nonce = min((worker_id + 1) * chunk_size_per_worker, FULL_NONCE_SPACE)
    slot_offset = worker_id * SLOT_SIZE

    # Локальная ссылка для быстрого доступа к функции
    _double_sha256 = double_sha256

    print(f"[WORKER {worker_id}] Запущен. Работает в диапазоне: {start_nonce:#x}-{end_nonce:#x}")

    while True:
        try:
            # 1. Атомарное чтение текущего задания из shared memory
            slot_data = bytearray(SLOT_SIZE)
            # Прямой доступ к RawArray - самая быстрая операция
            for i in range(SLOT_SIZE):
                slot_data[i] = input_slots[slot_offset + i]

            # Проверка наличия задания (id_task)
            id_task = int.from_bytes(slot_data[0:8], 'little')
            if id_task == 0:
                time.sleep(0.001)
                continue

            # Извлечение данных из локальной копии
            block_header = bytes(slot_data[8:84])  # 76 байт
            target_int = int.from_bytes(slot_data[84:116], 'little')  # 32 байта

            # 2. Определение случайной стартовой позиции в диапазоне
            if end_nonce - start_nonce > NONCE_CHUNK_SIZE:
                current_nonce = random.randrange(start_nonce, end_nonce - NONCE_CHUNK_SIZE + 1)
            else:
                # Если диапазон меньше размера чанка, поиск с начала диапазона
                current_nonce = start_nonce

            # 3. Обработка NONCE_CHUNK_SIZE возможных nonce
            attempts = 0
            found = False

            # Определение конца диапазона текущей итерации
            end_current_iteration = min(current_nonce + NONCE_CHUNK_SIZE, end_nonce)

            # Основной цикл хэширования
            for nonce in range(current_nonce, end_current_iteration):
                # Добавление проверяемого nonce к заголовку блока
                header_with_nonce = block_header + nonce.to_bytes(4, 'little')

                # Вычисление хеша и преобразование к integer для сравнения
                hash_int = int.from_bytes(_double_sha256(header_with_nonce), 'little')

                # Сравнение
                if hash_int < target_int:
                    # Найден подходящий nonce!
                    with result_lock:
                            struct.pack_into('<QI', result_slot, 0, id_task, nonce)
                    print(f"[WORKER {worker_id}] Найден nonce {nonce:#x} для задачи {id_task}")
                    found = True
                    break

                attempts += 1

            # 4. Обновление статистики
            with result_lock:
                stats_array[worker_id] += attempts

        except Exception as e:
            print(f"[WORKER {worker_id}] Ошибка: {str(e)}")

def result_checker(wallet_address: str,
                   result_slot: Any,
                   result_lock: Any,
                   cache_data: Dict[int, dict],
                   cache_lock: Any):
    """
    Проверяет и обрабатывает найденные решения, отправляя их ноде.

    Поток проверки результатов майнинга выполняет следующие действия:
    1. Периодически проверяет shared memory на наличие найденного решения
    2. При обнаружении результата извлекает его и проверяет на актуальность
    3. Получает соответствующий шаблон блока из кэша
    4. Формирует и отправляет полный блок ноде через RPC
    5. Очищает результат после обработки для возможности поиска новых решений

    Args:
        wallet_address (str): Адрес кошелька, куда будет направлено вознаграждения за найденный блок
        result_slot (Any): Область shared memory, содержащая результат поиска (id_task и nonce)
        result_lock (Any): Mutex для синхронизации доступа к result_slot
        cache_data (Dict[int, dict]): Кэш шаблонов блоков, сопоставляющий id_task с соответствующим шаблоном блока
        cache_lock (Any): Mutex для синхронизации доступа к cache_data

    Returns:
        None: Функция ничего не возвращает, работает как бесконечный цикл в фоновом потоке.
    """

    print("[CHECKER] Запущен поток проверки результатов")

    while True:
        # Проверка наличия результата
        with result_lock:
            id_task = struct.unpack_from('<Q', result_slot, 0)[0]
            if id_task == 0:
                time.sleep(0.01)
                continue
            nonce = struct.unpack_from('<I', result_slot, 8)[0]

        # Получение и создание deep copy шаблона под блокировкой
        with cache_lock:
            template = cache_data.get(id_task)
            if template:
                template = copy.deepcopy(template)

        # Пропуск при устаревании шаблона
        if not template:
            with result_lock:
                struct.pack_into('<Q', result_slot, 0, 0)
            continue

        # Формирование и отправка блока
        try:
            header = build_block_header(template)
            header_with_nonce = header + nonce.to_bytes(4, 'little')
            full_block = build_full_block(header_with_nonce, template, wallet_address)

            print(f"[CHECKER] Отправляем блок {template['height']} с nonce {nonce:#x}")
            result = rpc_call('submitblock', [full_block.hex()])

            status = "успешно отправлен и принят!" if result is None else "ошибка"
            message = f"Блок {template['height']} {status}"
            if result is not None:
                message += f": {result}"
            print(f"[CHECKER] {message}")

        except Exception as e:
            print(f"[CHECKER] Ошибка при обработке результата: {str(e)}")
        finally:
            # Очистка слота ПОСЛЕ всех операций
            with result_lock:
                struct.pack_into('<Q', result_slot, 0, 0)


def run_miner():
    """
    Запускает майнер и управляет всем процессом майнинга, включая параллельные worker процессы.

    Основной цикл майнера выполняет следующие задачи:
    1. Инициализирует shared memory структуры для обмена данными между процессами
    2. Запускает worker процессы для параллельного поиска nonce
    3. Запускает поток проверки результатов для обработки найденных решений
    4. Периодически проверяет наличие обновленных шаблонов блоков от ноды
    5. При получении нового шаблона распределяет его среди worker процессов
    6. Мониторит и выводит скорость хеширования и другую статистику
    7. Обрабатывает сигналы остановки и завершает работу корректно

    Returns:
        None: Функция ничего не возвращает после завершения работы.
    """
    print("=== Bitcoin-майнер (версия 0.6) ===")
    print("Майнер запущен с поддержкой параллельного майнинга на CPU")
    print(f"Используется {WORKER_COUNT} worker процессов")

    # Создание shared memory структуры
    SLOT_SIZE = 8 + 76 + 32  # id_task (8B) + header (76B) + target (32B)
    RESULT_SIZE = 12  # id_task (8B) + nonce (4B)

    input_slots = mp.RawArray('B', WORKER_COUNT * SLOT_SIZE)
    stats_array = mp.RawArray('Q', WORKER_COUNT)
    result_slot = mp.RawArray('B', RESULT_SIZE)

    # Синхронизация (Mutex)
    result_lock = mp.Lock()

    # Кэш шаблонов
    manager = mp.Manager()
    template_cache = manager.dict()
    cache_lock = manager.Lock()

    # Запуск worker процессов
    worker_processes = []
    for i in range(WORKER_COUNT):
        p = mp.Process(
            target=worker_process,
            args=(i, input_slots, stats_array, result_slot,
                  result_lock),
            daemon=True
        )
        p.start()
        print(f"[INFO] Запущен worker процесс {i} (PID: {p.pid})")
        worker_processes.append(p)

    # Запуск потока проверки результатов
    checker_thread = Thread(
        target=result_checker,
        args=(WALLET_ADDRESS, result_slot,
              result_lock, template_cache, cache_lock),
        daemon=True
    )
    checker_thread.start()

    # Инициализация для мониторинга скорости
    last_stats_time = time.time()
    last_stats = [0] * WORKER_COUNT

    # Переменные для управления шаблоном
    current_template = None
    last_check_time = 0
    current_id = 0

    print(f"[INFO] Ожидание нового задания (проверка каждые {CHECK_INTERVAL} сек)...")

    try:
        while True:
            current_time = time.time()
            should_update = False

            # Проверка необходимости обновления шаблона
            if (current_template is None or
                    (current_time - last_check_time) >= CHECK_INTERVAL):

                try:
                    new_template = get_block_template()
                    last_check_time = current_time

                    if current_template is None:
                        should_update = True
                        print(f"[INFO] Получен первый шаблон блока")
                    else:
                        # Проверка изменений в шаблоне
                        if (new_template['height'] > current_template['height'] or
                                len(new_template.get('transactions', [])) !=
                                len(current_template.get('transactions', []))):
                            should_update = True
                except Exception as e:
                    print(f"[ERROR] Ошибка получения шаблона: {str(e)}")
                    time.sleep(1)
                    continue

            # Обновление шаблона при необходимости
            if should_update:
                current_template = new_template
                current_id += 1

                # Сборка заголовока и target
                header = build_block_header(current_template)
                target = target_from_bits(current_template['bits'])

                # Кэширование шаблона
                with cache_lock:
                    template_cache[current_id] = current_template

                # Рассылка задания всем воркерам
                for i in range(WORKER_COUNT):
                    start_idx = i * SLOT_SIZE

                    # Запись id_task (8 байт, little-endian)
                    struct.pack_into('<Q', input_slots, start_idx, current_id)

                    # Запись block_header (76 байт)
                    header_offset = start_idx + 8
                    for j, b in enumerate(header):
                        input_slots[header_offset + j] = b

                    # Запись target (32 байта)
                    target_offset = header_offset + 76
                    for j, b in enumerate(target):
                        input_slots[target_offset + j] = b

                print(f"\n[INFO] Получен новый шаблон блока. "
                      f"Высота: {current_template['height']}, "
                      f"Целевая сложность: {current_template['bits']}. "
                      f"Транзакций в шаблоне: {len(current_template.get('transactions', [])) + 1}")
                print(f"[INFO] Начата обработка задачи #{current_id}")

            # Мониторинг скорости (раз в 5 секунд)
            if current_time - last_stats_time >= 5.0:
                current_stats = list(stats_array)
                total_attempts = sum(current_stats)
                delta = total_attempts - sum(last_stats)
                hashrate = delta / (current_time - last_stats_time)
                last_stats = current_stats
                last_stats_time = current_time

                print(f"[STATS] Скорость хеширования: {int(hashrate):,} h/s | "
                      f"Всего попыток: {total_attempts:,}")

            time.sleep(0.1)  # Предотвращение избыточного использования CPU

    except KeyboardInterrupt:
        print("\n[INFO] Майнер остановлен пользователем.")
    except Exception as e:
        print(f"[FATAL] Необработанная ошибка: {str(e)}")
    finally:
        print("[INFO] Останавливаю worker процессы...")
        for p in worker_processes:
            p.terminate()
        for p in worker_processes:
            p.join(timeout=2.0)
        print("[INFO] Работа завершена")


if __name__ == "__main__":
    try:
        run_miner()
    except KeyboardInterrupt:
        print("\n[INFO] Майнер остановлен пользователем.")
