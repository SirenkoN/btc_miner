# -*- coding: utf-8 -*-
"""
Модуль для вспомогательных утилит и функций, используемых в основном процессе майнинга.
Содержит служебные функции, которые не относятся к конкретным компонентам системы.
"""

from typing import Dict, Any

# Импорты из проекта
from utils.logger import logger


def clean_obsolete_templates(
        cache_data: Dict[int, dict],
        cache_lock: Any,
        current_height: int
) -> None:
    """
    Очищает кэш от устаревших шаблонов блоков.

    Удаляет все записи в кэше, для которых высота блока меньше текущей на 2 и более.
    Например, если текущая высота = 1000, то будут удалены записи для высот <= 998.

    Args:
        cache_data (Dict[int, dict]): Кэш шаблонов блоков
        cache_lock (Any): Mutex для синхронизации доступа к cache_data
        current_height (int): Текущая высота блока в сети

    Returns:
        None: Функция удаляет устаревшие записи из кэша.
    """
    # Пороговая высота для удаления (более старые записи удаляются)
    threshold_height = current_height - 2
    removed_count = 0

    with cache_lock:
        # Создаем список ключей для проверки, чтобы не итерироваться по изменяемому словарю
        keys_to_check = list(cache_data.keys())

        for key in keys_to_check:
            entry = cache_data.get(key)
            if entry and entry['height'] < threshold_height:
                del cache_data[key]
                removed_count += 1

    if removed_count > 0:
        logger.info(
            f"[CACHE] Очищено {removed_count} устаревших записей кэша (высота блока меньше чем {threshold_height})")
