# -*- coding: utf-8 -*-
"""
Модуль для сбора и отображения статистики хешрейта майнера.
Содержит реализацию потока, который регулярно вычисляет и выводит текущую скорость майнинга.
"""

import time
from typing import Any

# Импорты из проекта
from config import WORKER_COUNT
from utils.logger import logger


def hashrate_stats_thread(
        stats_array: Any,
        interval: float = 5.0
) -> None:
    """
    Поток для сбора и отображения хешрейта.

    Отвечает за регулярный сбор статистики скорости майнинга и вывода
    этой информации в консоль без вмешательства в основной процесс майнинга.

    Особенности реализации:
    - Использует прямое чтение shared memory без блокировки
    - Берет выборку статистики каждые `interval` секунд
    - Вычисляет общий хешрейт всех запущенных процессов и выводит его в понятном формате

    Обоснование отсутствия блокировки:
    * 8-байтовые целые числа обновляются атомарно на современных CPU (x86/x64)
    * Небольшая неточность статистики допустима для мониторинга
    * Worker процессы не должны испытывать задержек из-за сбора статистики
    * Основная цель - максимальная скорость майнинга, статистика вторична

    Args:
        stats_array (Any): Область shared memory с массивом счетчиков для каждого worker'а
        interval (float): Интервал обновления статистики в секундах. По умолчанию 5.0.

    Returns:
        None: Функция работает в бесконечном цикле пока существует основной процесс.
    """
    logger.info(f"[HASHRATE] Запущен поток сбора статистики (обновление каждые {interval} секунд)")

    # Инициализация данных для расчета скорости
    last_stats = [0] * WORKER_COUNT
    last_update = time.time()

    while True:
        # Задержка перед следующим обновлением
        time.sleep(interval)

        try:
            # Чтение данных без блокировки
            current_stats = [stats_array[i] for i in range(WORKER_COUNT)]
            current_time = time.time()

            # Расчет общего количества проверенных nonce за период
            total_attempts = sum(current_stats)
            total_last = sum(last_stats)
            attempts_delta = total_attempts - total_last

            # Вычисление времени между замерами и скорости хеширования
            time_delta = current_time - last_update
            hashrate = attempts_delta / time_delta if time_delta > 0 else 0

            # Логирование статистики
            # Форматирование хешрейта в удобочитаемый вид (TH/s, GH/s и т.д.)
            if hashrate > 1e12:
                formatted_hashrate = f"{hashrate / 1e12:.2f} TH/s"
            elif hashrate > 1e9:
                formatted_hashrate = f"{hashrate / 1e9:.2f} GH/s"
            elif hashrate > 1e6:
                formatted_hashrate = f"{hashrate / 1e6:.2f} MH/s"
            elif hashrate > 1e3:
                formatted_hashrate = f"{hashrate / 1e3:.2f} KH/s"
            else:
                formatted_hashrate = f"{hashrate:.2f} H/s"

            logger.info(f"[HASHRATE] Скорость хеширования: {formatted_hashrate} | "
                        f"Всего проверено: {total_attempts:,} nonce")

            # Обновление данных для следующего расчета
            last_stats = current_stats
            last_update = current_time

        except Exception as e:
            logger.error(f"[HASHRATE] Ошибка при сборе статистики: {str(e)}")
