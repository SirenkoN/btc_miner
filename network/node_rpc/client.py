# -*- coding: utf-8 -*-
"""
Hight-level клиент для взаимодействия с Bitcoin-нодой.
Содержит высокоуровневые методы для работы с нодой через RPC.

- Метод для получения шаблонов блоков
- Метод для отправки сформированных блоков в сеть

Все методы абстрагируют низкоуровневые детали RPC.
"""

from typing import Any

# Импорты из проекта
from network.node_rpc.transport import rpc_call


def get_block_template() -> dict:
    """
    Возвращает шаблон блока через RPC.

    Использует метод getblocktemplate с параметром:
    {"rules": ["segwit"]}

    Returns:
        dict: Шаблон блока в формате, определенном Bitcoin Core
    """
    return rpc_call("getblocktemplate", [{"rules": ["segwit"]}])


def submit_block(
        block_hex: str
) -> Any:
    """
    Отправляет сформированный блок в Bitcoin-сеть через RPC.

    Использует метод submitblock для передачи сериализованного блока в hex-формате.

    Args:
        block_hex (str): Сериализованный блок в шестнадцатеричном формате

    Returns:
        Any: Результат вызова RPC. None в случае успешной передачи блока.

    Raises:
        RuntimeError: При возникновении ошибки при отправке блока
    """
    return rpc_call("submitblock", [block_hex])
