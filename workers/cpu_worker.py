# -*- coding: utf-8 -*-
"""
Модуль CPU-воркеров для Bitcoin-майнера.
Содержит реализацию параллельных процессов, выполняющих поиск подходящего nonce.
"""

import random
import struct
import time
from typing import Any

# Импорты из проекта
from blockchain.utils import double_sha256
from config import NONCE_CHUNK_SIZE, WORKER_COUNT
from core.shared_memory import SLOT_SIZE
from utils.logger import logger


def cpu_worker_process(
        worker_id: int,
        input_slots: Any,
        stats_array: Any,
        result_slot: Any,
        result_lock: Any
) -> None:
    """
    Поиск подходящего nonce для майнинга блока в параллельном режиме.

    Worker запускается в отдельном дочернем процессе и выполняет следующие действия:
    1. Периодически проверяет shared memory на наличие нового задания
    2. Для каждого задания обрабатывает свой диапазон nonce согласно алгоритму распределения диапазона nonce
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
    FULL_NONCE_SPACE = 0x100000000  # 2^32 (4294967296)

    # Определение фиксированного диапазона для воркера
    chunk_size_per_worker = FULL_NONCE_SPACE // WORKER_COUNT
    start_nonce = worker_id * chunk_size_per_worker
    end_nonce = min((worker_id + 1) * chunk_size_per_worker, FULL_NONCE_SPACE)
    slot_offset = worker_id * SLOT_SIZE

    # Локальная ссылка для быстрого доступа к функции
    _double_sha256 = double_sha256

    logger.info(f"[CPU WORKER {worker_id}] Запущен. Работает в диапазоне nonce: {start_nonce:#x}-{end_nonce:#x}")

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
                    logger.info(f"[CPU WORKER {worker_id}] Найден nonce {nonce:#x} для задачи {id_task}")
                    break

                attempts += 1

            # 4. Обновление статистики
            with result_lock:
                stats_array[worker_id] += attempts

        except Exception as e:
            logger.error(f"[CPU WORKER {worker_id}] Ошибка: {str(e)}")
