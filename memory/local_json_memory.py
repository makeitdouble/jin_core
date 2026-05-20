import os
import json
import uuid
import asyncio
from typing import List, Dict, Any, Optional
from memory_base import MemoryBase

class LocalJsonMemory(MemoryBase):
    def __init__(self, file_path: str = "jin_memory.json"):
        self.file_path = file_path
        self.lock = asyncio.Lock()  # Защита от одновременной записи из разных асинхронных задач
        self._ensure_file_exists()

    def _ensure_file_exists(self):
        if not os.path.exists(self.file_path):
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump({}, f, ensure_ascii=False, indent=4)

    async def _read_db(self) -> Dict[str, Dict[str, Any]]:
        async with self.lock:
            with open(self.file_path, "r", encoding="utf-8") as f:
                return json.load(f)

    async def _write_db(self, data: Dict[str, Dict[str, Any]]):
        async with self.lock:
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)

    async def add_fact(
        self,
        text: str,
        importance: float,
        decay_rate: float,
        evidence_id: Optional[str] = None
    ) -> str:
        db = await self._read_db()
        fact_id = str(uuid.uuid4())

        db[fact_id] = {
            "id": fact_id,
            "text": text,
            "weight": max(0.0, min(1.0, importance)),  # Ограничение 0.0 - 1.0
            "decay_rate": max(0.0, decay_rate),
            "evidence_id": evidence_id,
            "hits": 1  # Сколько раз этот факт подтверждался/вспоминался
        }

        await self._write_db(db)
        return fact_id

    async def get_relevant_facts(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        db = await self._read_db()
        query_words = set(query.lower().split())
        scored_facts = []

        for fact in db.values():
            # Простейший поиск по пересечению слов (заглушка до графов/эмбеддингов)
            fact_words = set(fact["text"].lower().split())
            matches = len(query_words.intersection(fact_words))

            # Релевантность = совпадение слов * текущий вес факта в памяти
            relevance = matches * fact["weight"]

            if relevance > 0 or fact["decay_rate"] == 0.0:  # Пропускаем константы (имя и т.д.) всегда
                scored_facts.append((relevance, fact))

        # Сортируем по релевантности и возвращаем чистый список фактов
        scored_facts.sort(key=lambda x: x[0], reverse=True)
        return [item[1] for item in scored_facts[:limit]]

    async def apply_night_decay(self) -> Dict[str, int]:
        """
        Линейно снижает вес каждого факта на его decay_rate.
        Если вес падает ниже порогового (0.15) и это не константа — факт удаляется.
        """
        db = await self._read_db()
        updated_count = 0
        deleted_count = 0
        new_db = {}

        for fact_id, fact in db.items():
            # Если decay_rate == 0, факт бессмертен (например, имя пользователя)
            if fact["decay_rate"] == 0.0:
                new_db[fact_id] = fact
                continue

            # Формула затухания: уменьшаем вес
            fact["weight"] = round(fact["weight"] - fact["decay_rate"], 3)

            # Порог утилизации факта (например, 0.15)
            if fact["weight"] <= 0.15:
                deleted_count += 1
            else:
                new_db[fact_id] = fact
                updated_count += 1

        await self._write_db(new_db)
        return {"updated": updated_count, "deleted": deleted_count}
