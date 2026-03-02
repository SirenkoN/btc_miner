# -*- coding: utf-8 -*-
"""
Точка входа для Bitcoin-майнера версия 0.63
Рефакторинг: переход с print на логирование.
"""

import multiprocessing as mp
import struct
import time
from threading import Thread

# Импорты из проекта
from blockchain.block_header_builder import build_block_header
from blockchain.utils import target_from_bits
from config import CHECK_INTERVAL, WALLET_ADDRESS, WORKER_COUNT
from core.cpu_stats import hashrate_stats_thread
from core.result_handler import result_checker_thread
from core.shared_memory import init_shared_memory, SLOT_SIZE
from core.utils import clean_obsolete_templates
from network.node_rpc.client import get_block_template
from utils.logger import logger
from workers.cpu_worker import cpu_worker_process


def run_miner() -> None:
    """
    Запускает майнер и управляет всем процессом майнинга, включая параллельные worker процессы.

    Основной цикл майнера выполняет следующие задачи:
    1. Инициализирует shared memory структуры для обмена данными между процессами и потоками
    2. Запускает worker процессы для параллельного поиска nonce
    3. Запускает поток проверки результатов для обработки найденных решений
    4. Запускает поток подсчета и печати статисктики
    5. Периодически проверяет наличие обновленных шаблонов блоков от ноды
    6. При получении нового шаблона распределяет его среди worker процессов
    7. Обрабатывает сигналы остановки и завершает работу корректно

    Returns:
        None: Функция ничего не возвращает после завершения работы.
    """
    logger.info("=== Bitcoin-майнер (версия 0.63) ===")
    logger.info("Майнер запущен с поддержкой параллельного майнинга на CPU")
    logger.info(f"Используется {WORKER_COUNT} worker процессов")

    # Инициализация shared memory структур
    memory_structs = init_shared_memory()
    input_slots = memory_structs['input_slots']
    stats_array = memory_structs['stats_array']
    result_slot = memory_structs['result_slot']
    result_lock = memory_structs['result_lock']
    template_cache = memory_structs['template_cache']
    cache_lock = memory_structs['cache_lock']

    # Запуск worker процессов
    worker_processes = []
    for i in range(WORKER_COUNT):
        p = mp.Process(
            target=cpu_worker_process,
            args=(i, input_slots, stats_array, result_slot,
                  result_lock),
            daemon=True
        )
        p.start()
        logger.info(f"[INFO] Запущен CPU worker процесс {i} (PID: {p.pid})")
        worker_processes.append(p)

    # Запуск потока проверки результатов
    checker_thread = Thread(
        target=result_checker_thread,
        args=(WALLET_ADDRESS, result_slot,
              result_lock, template_cache, cache_lock),
        daemon=True
    )
    checker_thread.start()

    # Запуск потока статистики
    stats_thread = Thread(
        target=hashrate_stats_thread,
        args=(stats_array,),
        daemon=True
    )
    stats_thread.start()

    # Переменные для управления шаблоном
    current_template = None
    last_check_time = 0
    current_id = 0
    current_height = -1

    logger.info(f"[INFO] Ожидание нового задания (проверка каждые {CHECK_INTERVAL} сек)...")

    try:
        while True:
            current_time = time.time()
            should_update = False
            update_reason = ""

            # Проверка необходимости обновления шаблона
            if (current_template is None or
                    (current_time - last_check_time) >= CHECK_INTERVAL):

                new_template = None
                try:
                    new_template = get_block_template()
                    last_check_time = current_time
                except Exception as e:
                    logger.error(f"[ERROR] Ошибка получения шаблона: {str(e)}")
                    time.sleep(1)
                    continue

                if current_template is None:
                    # Первый запуск
                    should_update = True
                    update_reason = "первый запуск"
                    logger.info(f"[INFO] Получен первый шаблон блока")
                else:
                    # Проверка наличия изменений
                    new_height = int(new_template['height'])
                    current_height = int(current_template['height'])
                    tx_count_diff = abs(len(new_template.get('transactions', [])) -
                                        len(current_template.get('transactions', [])))

                    # 1. Изменение высоты блока
                    if new_height > current_height:
                        should_update = True
                        update_reason = f"изменение высоты блока с {current_height} на {new_height}"
                        logger.info(f"\n[NETWORK] Высота блока в сети изменилась. Текущая высота блока: {new_height}, "
                                    f"целевая сложность: {new_template['bits']}")
                        current_height = new_height

                    # 2. Значительное изменение количества транзакций
                    elif tx_count_diff > 100:
                        should_update = True
                        update_reason = f"значительное изменение mempool ({tx_count_diff} транзакций)"

                # Обработка необходимости обновления
                if should_update:
                    current_template = new_template

                    current_id += 1

                    # Сборка заголовка и target
                    header = build_block_header(current_template)
                    target = target_from_bits(current_template['bits'])

                    # Кэширование шаблона
                    with cache_lock:
                        template_cache[current_id] = {
                            'template': current_template,
                            'height': current_template['height']
                        }

                    # Рассылка задания worker процессам
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

                    # Если это изменение высоты блока, очистить устаревшие записи
                    # Только после обновления задания worker процессов
                    if "изменение высоты блока" in update_reason:
                        clean_obsolete_templates(template_cache, cache_lock, new_height)

                    # Определение количества транзакций для вывода
                    tx_count = 1 + len(current_template.get('transactions', []))

                    # Вывод информации об обновлении задания
                    logger.info(f"[TASK] Новое задание #{current_id}: {update_reason}")
                    logger.info(f"[TASK] Высота: {current_template['height']}, "
                                f"Целевая сложность: {current_template['bits']}. "
                                f"Транзакций в шаблоне: {tx_count}")
                    logger.info(f"[TASK] Начата обработка задачи #{current_id}")

            time.sleep(0.1)

    except KeyboardInterrupt:
        logger.info("\n[INFO] Майнер остановлен пользователем.")
    except Exception as e:
        logger.error(f"[FATAL] Необработанная ошибка: {str(e)}")
    finally:
        logger.info("[INFO] Остановка worker процессов...")
        for p in worker_processes:
            p.terminate()
        for p in worker_processes:
            p.join(timeout=2.0)
        logger.info("[INFO] Работа завершена")


if __name__ == "__main__":
    try:
        run_miner()
    except KeyboardInterrupt:
        logger.info("\n[INFO] Майнер остановлен пользователем.")
