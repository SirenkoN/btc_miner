# -*- coding: utf-8 -*-
"""
Модуль для централизованного логирования в проекте Bitcoin-майнера.
"""

import logging
import sys


def setup_logger() -> logging.Logger:
    """
    Настраивает и возвращает глобальный логер для проекта.

    Создает логер с цветным форматированием сообщений и выводом в консоль.
    Обеспечивает отсутствие дублирования обработчиков при повторных вызовах.

    Returns:
        logging.Logger: Настроенный логер с цветным выводом и форматированием.
    """
    logger = logging.getLogger("bitcoin_miner")
    logger.setLevel(logging.INFO)

    # Проверка наличия обработчиков для предотвращения дублирования
    if logger.handlers:
        return logger

    # Создание обработчика для вывода сообщений в консоль
    handler = logging.StreamHandler(sys.stdout)

    # Определение цветовой схемы
    class ColoredFormatter(logging.Formatter):
        COLORS = {
            'DEBUG': '\033[94m',  # Синий
            'INFO': '\033[92m',  # Зеленый
            'WARNING': '\033[93m',  # Желтый
            'ERROR': '\033[91m',  # Красный
            'CRITICAL': '\033[91m\033[1m',  # Жирный красный
            'RESET': '\033[0m'
        }

        def format(
                self,
                record
                ):
            """
            Применяет цветовую схему к форматированному сообщению.

            Args:
                record (logging.LogRecord): Запись лога для форматирования.

            Returns:
                str: Отформатированное сообщение с цветовой разметкой.
            """
            color = self.COLORS.get(record.levelname, self.COLORS['RESET'])
            reset = self.COLORS['RESET']
            message = super().format(record)
            return f"{color}{message}{reset}"

    formatter = ColoredFormatter(
        '[%(asctime)s] [%(levelname)s] %(message)s',
        datefmt='%H:%M:%S'
    )
    handler.setFormatter(formatter)

    logger.addHandler(handler)
    return logger


# Создание глобального экземпляра логера
logger = setup_logger()
