from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional

class MemoryBase(ABC):
    @abstractmethod
    async def add_fact(
        self,
        text: str,
        importance: float,
        decay_rate: float,
        evidence_id: Optional[str] = None
    ) -> str:
        """
        Добавить новый факт в память.
        :param text: Содержание факта (например, "Пользователь пьет кофе в 8 утра")
        :param importance: Стартовая важность факта (от 0.0 до 1.0)
        :param decay_rate: Скорость затухания (0.0 — никогда не забывать, 0.5 — быстро)
        :param evidence_id: ID связанного скриншота/доказательства (опционально)
        :return: Уникальный ID созданного факта
        """
        pass

    @abstractmethod
    async def get_relevant_facts(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Извлечь факты, релевантные текущему контексту (для сборки XML-пакета).
        """
        pass

    @abstractmethod
    async def apply_night_decay(self) -> Dict[str, int]:
        """
        Запустить ночной полураспад. Уменьшает веса фактов на их decay_rate.
        Удаляет затухшие факты.
        :return: Статистика (сколько фактов обновлено, сколько удалено)
        """
        pass
