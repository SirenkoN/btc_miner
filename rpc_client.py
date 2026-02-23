# -*- coding: utf-8 -*-
"""
RPC-клиент для взаимодействия с Bitcoin-нодой.
Содержит логику выполнения JSON-RPC вызовов.
"""

import requests
from config import RPC_USER, RPC_PASSWORD, RPC_HOST, RPC_PORT


# 1. Создание сессии для повторного использования соединения.
session = requests.Session()
session.auth = (RPC_USER, RPC_PASSWORD)


# 2. Утилита RPC
def rpc_call(method: str, params=None) -> any:
    """
    Выполняет JSON-RPC вызов к локальной ноде и возвращает `result`.

    Args:
        method (str): Имя метода (например, 'getblocktemplate').
        params (list | dict | None): Параметры метода. Если `None` – передаётся пустой список.

    Returns:
        any: Результат RPC в виде Python-объекта.

    Raises:
        RuntimeError: Если произошла ошибка RPC-вызова.
    """
    url = f"http://{RPC_HOST}:{RPC_PORT}"
    payload = {
        "jsonrpc": "1.0",
        "id": 1,
        "method": method,
        "params": params or []
    }

    try:
        resp = session.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()

        if data.get("error"):
            raise RuntimeError(f"{method} error: {data['error']}")

        return data["result"]
    except Exception as exc:
        print(f"[ERROR] RPC вызов {method} не выполнен: {exc}")
        raise


# 3. Получение шаблона блока
def get_block_template() -> dict:
    """
    Возвращает шаблон блока через RPC.

    Использует метод getblocktemplate с параметром:
    {"rules": ["segwit"]}

    Returns:
        dict: Шаблон блока в формате, определенном Bitcoin Core
    """
    return rpc_call("getblocktemplate", [{"rules": ["segwit"]}])
