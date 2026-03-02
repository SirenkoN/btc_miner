# -*- coding: utf-8 -*-
"""
Low-level клиент для взаимодействия с Bitcoin-нодой.
Содержит логику выполнения JSON-RPC вызовов.
"""

import time

import requests

# Импорты из проекта
from config import RPC_USER, RPC_PASSWORD, RPC_HOST, RPC_PORT
from utils.logger import logger

# 1. Создание сессии для повторного использования соединения.
session = requests.Session()
session.auth = (RPC_USER, RPC_PASSWORD)


# 2. Утилита RPC
def rpc_call(
        method: str,
        params=None
) -> any:
    """
    Выполняет JSON-RPC вызов к локальной ноде и возвращает `result`.
    В случае временной сетевой ошибки (например, недоступность ноды) предпринимает до 10 повторных попыток с задержкой 10 секунд между ними.

    Args:
        method (str): Имя метода (например, 'getblocktemplate').
        params (list | dict | None): Параметры метода. Если `None` – передаётся пустой список.

    Returns:
        any: Результат RPC в виде Python-объекта.

    Raises:
        RuntimeError: Если после 10 попыток соединение не установлено или вызов завершился с ошибкой.
    """
    url = f"http://{RPC_HOST}:{RPC_PORT}"
    payload = {
        "jsonrpc": "1.0",
        "id": 1,
        "method": method,
        "params": params or []
    }
    max_retries = 10

    for attempt in range(max_retries):
        try:
            resp = session.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()

            if data.get("error"):
                raise RuntimeError(f"{method} error: {data['error']}")

            return data["result"]

        except requests.exceptions.RequestException as req_exc:
            # Обработка сетевых ошибок (нет HTTP-ответа)
            if req_exc.response is None:
                # Ещё есть попытки
                if attempt < max_retries - 1:
                    logger.info(
                        f"[RPC CLIENT] Попытка подключения к ноде {attempt + 1}/{max_retries} не удалась. Повтор через 10 сек...")
                    time.sleep(10)
                    continue

                # Все попытки исчерпаны
                error_msg = f"Не удалось подключиться к ноде после {max_retries} попыток"
                logger.error(f"[RPC CLIENT] {error_msg}: {req_exc}")
                raise RuntimeError(error_msg) from req_exc

            # Ошибки с HTTP-ответом (401, 500 и т.д.)
            error_msg = f"Критическая ошибка RPC: {req_exc}"
            logger.error(f"[RPC CLIENT] {error_msg}")
            raise RuntimeError(error_msg) from req_exc

        except Exception as exc:
            error_msg = f"Необработанная ошибка: {exc}"
            logger.error(f"[RPC CLIENT] {error_msg}")
            raise RuntimeError(error_msg) from exc
    return None
