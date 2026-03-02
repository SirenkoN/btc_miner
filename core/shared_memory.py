# -*- coding: utf-8 -*-
"""
Модуль для централизованного управления shared memory структурами.
Содержит логику инициализации и определения всех структур, используемых для взаимодействия между процессами.
"""

import multiprocessing as mp

# Импорты из проекта
from config import WORKER_COUNT

# Константы размеров shared memory структур
SLOT_SIZE = 8 + 76 + 32  # id_task (8B) + header (76B) + target (32B)
RESULT_SIZE = 12  # id_task (8B) + nonce (4B)


def init_shared_memory():
    """
    Инициализирует все необходимые структуры shared memory для работы майнера.

    Создает и возвращает следующие структуры:
    - input_slots: Буфер для передачи заданий worker процессам
    - stats_array: Массив для сбора статистики хеширования
    - result_slot: Область для передачи найденных решений
    - result_lock: Мьютекс для синхронизации доступа к result_slot
    - template_cache: Управляемый словарь для кэширования шаблонов блоков
    - cache_lock: Мьютекс для синхронизации доступа к template_cache

    Returns:
        dict: Словарь с инициализированными структурами shared memory.
    """
    # Создание shared memory структур
    input_slots = mp.RawArray('B', WORKER_COUNT * SLOT_SIZE)
    stats_array = mp.RawArray('Q', WORKER_COUNT)
    result_slot = mp.RawArray('B', RESULT_SIZE)

    # Синхронизация (Mutex)
    result_lock = mp.Lock()

    # Кэш шаблонов
    manager = mp.Manager()
    template_cache = manager.dict()
    cache_lock = manager.Lock()

    return {
        'input_slots': input_slots,
        'stats_array': stats_array,
        'result_slot': result_slot,
        'result_lock': result_lock,
        'template_cache': template_cache,
        'cache_lock': cache_lock
    }
