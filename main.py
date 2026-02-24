# -*- coding: utf-8 -*-
"""
Точка входа для Bitcoin-майнера версия 0.61
Добавлен отдельный поток статистики хэшрейта, оптимизирована работа с кэшем.
Изменена логика сборки заголовка блока, вместо системного времени используется медианное.
"""

import time
import multiprocessing as mp
from threading import Thread
import struct
import random
import copy
from typing import Dict, Any

# Импорты из проекта
from config import CHECK_INTERVAL, WALLET_ADDRESS, WORKER_COUNT, NONCE_CHUNK_SIZE
from rpc_client import rpc_call, get_block_template
from block_header_builder import build_block_header
from full_block_builder import build_full_block
from utils import double_sha256, target_from_bits


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
    SLOT_SIZE = 8 + 76 + 32  # id_task (8B) + header (76B) + target (32B)
    FULL_NONCE_SPACE = 0x100000000  # 2^32 (4294967296)

    # Определение фиксированного диапазона для воркера
    chunk_size_per_worker = FULL_NONCE_SPACE // WORKER_COUNT
    start_nonce = worker_id * chunk_size_per_worker
    end_nonce = min((worker_id + 1) * chunk_size_per_worker, FULL_NONCE_SPACE)
    slot_offset = worker_id * SLOT_SIZE

    # Локальная ссылка для быстрого доступа к функции
    _double_sha256 = double_sha256

    print(f"[CPU WORKER {worker_id}] Запущен. Работает в диапазоне nonce: {start_nonce:#x}-{end_nonce:#x}")

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
                    print(f"[CPU WORKER {worker_id}] Найден nonce {nonce:#x} для задачи {id_task}")
                    break

                attempts += 1

            # 4. Обновление статистики
            with result_lock:
                stats_array[worker_id] += attempts

        except Exception as e:
            print(f"[CPU WORKER {worker_id}] Ошибка: {str(e)}")


def result_checker_thread(
        wallet_address: str,
        result_slot: Any,
        result_lock: Any,
        cache_data: Dict[int, dict],
        cache_lock: Any
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
        result_lock (Any): Mutex для синхронизации доступа к result_slot
        cache_data (Dict[int, dict]): Кэш шаблонов блоков, сопоставляющий id_task с соответствующим шаблоном блока
        cache_lock (Any): Mutex для синхронизации доступа к cache_data

    Returns:
        None: Функция ничего не возвращает, работает как бесконечный цикл в фоновом потоке.
    """

    print("[RESULT CHECKER] Запущен поток проверки результатов")

    while True:
        # Проверка наличия результата
        with result_lock:
            id_task = struct.unpack_from('<Q', result_slot, 0)[0]
            if id_task == 0:
                time.sleep(0.01)
                continue
            nonce = struct.unpack_from('<I', result_slot, 8)[0]

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

            result = rpc_call('submitblock', [full_block.hex()])
            print(f"[RESULT CHECKER] Отправляем блок {template['height']} с nonce {nonce:#x}")

            status = "успешно отправлен и принят!" if result is None else "ошибка"
            message = f"Блок {template['height']} {status}"
            if result is not None:
                message += f": {result}"
            print(f"[RESULT CHECKER] {message}")

        except Exception as e:
            print(f"[RESULT CHECKER] Ошибка при обработке результата: {str(e)}")
        finally:
            # Очистка слота ПОСЛЕ всех операций
            with result_lock:
                struct.pack_into('<Q', result_slot, 0, 0)


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
        interval (float, optional): Интервал обновления статистики в секундах. По умолчанию 5.0.

    Returns:
        None: Функция работает в бесконечном цикле пока существует основной процесс.
    """
    print(f"[HASHRATE] Запущен поток сбора статистики (обновление каждые {interval} секунд)")

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

            print(f"[HASHRATE] Скорость хеширования: {formatted_hashrate} | "
                  f"Всего проверено: {total_attempts:,} nonce")

            # Обновление данных для следующего расчета
            last_stats = current_stats
            last_update = current_time

        except Exception as e:
            print(f"[HASHRATE] Ошибка при сборе статистики: {str(e)}")


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
        print(f"[CACHE] Очищено {removed_count} устаревших записей кэша (высота блока меньше чем {threshold_height})")


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
    print("=== Bitcoin-майнер (версия 0.61) ===")
    print("Майнер запущен с поддержкой параллельного майнинга на CPU")
    print(f"Используется {WORKER_COUNT} worker процессов")

    # Создание shared memory структуры
    SLOT_SIZE = 8 + 76 + 32  # id_task (8B) + header (76B) + target (32B)
    RESULT_SIZE = 12  # id_task (8B) + nonce (4B)

    input_slots = mp.RawArray('B', WORKER_COUNT * SLOT_SIZE)
    stats_array = mp.RawArray('Q', WORKER_COUNT)
    result_slot = mp.RawArray('B', RESULT_SIZE)

    # Синхронизация (Mutex)
    result_lock = mp.Lock()

    # Кэш шаблонов
    manager = mp.Manager()
    template_cache = manager.dict()  # Теперь будет хранить словари с шаблоном и высотой
    cache_lock = manager.Lock()

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
        print(f"[INFO] Запущен CPU worker процесс {i} (PID: {p.pid})")
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

    print(f"[INFO] Ожидание нового задания (проверка каждые {CHECK_INTERVAL} сек)...")

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
                    print(f"[ERROR] Ошибка получения шаблона: {str(e)}")
                    time.sleep(1)
                    continue

                if current_template is None:
                    # Первый запуск
                    should_update = True
                    update_reason = "первый запуск"
                    print(f"[INFO] Получен первый шаблон блока")
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
                        print(f"\n[NETWORK] Высота блока в сети изменилась. Текущая высота блока: {new_height}, "
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
                    print(f"[TASK] Новое задание #{current_id}: {update_reason}")
                    print(f"[TASK] Высота: {current_template['height']}, "
                          f"Целевая сложность: {current_template['bits']}. "
                          f"Транзакций в шаблоне: {tx_count}")
                    print(f"[TASK] Начата обработка задачи #{current_id}")

            time.sleep(0.1)

    except KeyboardInterrupt:
        print("\n[INFO] Майнер остановлен пользователем.")
    except Exception as e:
        print(f"[FATAL] Необработанная ошибка: {str(e)}")
    finally:
        print("[INFO] Остановка worker процессов...")
        for p in worker_processes:
            p.terminate()
        for p in worker_processes:
            p.join(timeout=2.0)
        print("[INFO] Работа завершена")


if __name__ == "__main__":
    try:
        run_miner()
    except KeyboardInterrupt:
        print("\n[INFO] Майнер остановлен пользователем.")
