# -*- coding: utf-8 -*-
"""
Модуль для обработки результатов майнинга.
Содержит реализацию потока, который проверяет найденные решения и отправляет их в сеть.
"""

import copy
import struct
import time
from threading import Lock
from typing import Any, Dict

# Импорты из проекта
from blockchain.block_header_builder import build_block_header
from blockchain.full_block_builder import build_full_block
from network.node_rpc.client import submit_block
from utils.logger import logger


def result_checker_thread(
        wallet_address: str,
        result_slot: Any,
        result_lock: Lock,
        cache_data: Dict[int, dict],
        cache_lock: Lock
) -> None:
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
        result_lock (Lock): Мьютекс для синхронизации доступа к result_slot
        cache_data (Dict[int, dict]): Кэш шаблонов блоков, сопоставляющий id_task с соответствующим шаблоном блока
        cache_lock (Lock): Мьютекс для синхронизации доступа к cache_data

    Returns:
        None: Функция ничего не возвращает, работает как бесконечный цикл в фоновом потоке.
    """

    logger.info("[RESULT CHECKER] Запущен поток проверки результатов")

    while True:
        # Проверка наличия результата
        with result_lock:
            id_task = struct.unpack_from('<Q', result_slot, 0)[0]
            if id_task == 0:
                time.sleep(0.01)
                continue
            nonce = struct.unpack_from('<I', result_slot, 8)[0]

        template = None
        # Получение и создание deep copy шаблона под блокировкой
        with cache_lock:
            template_entry = cache_data.get(id_task)
            if template_entry:
                template = copy.deepcopy(template_entry['template'])

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

            result = submit_block(full_block.hex())
            logger.info(f"[RESULT CHECKER] Отправляем блок {template['height']} с nonce {nonce:#x}")

            status = "успешно отправлен и принят!" if result is None else "ошибка"
            message = f"Блок {template['height']} {status}"
            if result is not None:
                message += f": {result}"
            logger.info(f"[RESULT CHECKER] {message}")

        except Exception as e:
            logger.error(f"[RESULT CHECKER] Ошибка при обработке результата: {str(e)}")
        finally:
            # Очистка слота ПОСЛЕ всех операций
            with result_lock:
                struct.pack_into('<Q', result_slot, 0, 0)
