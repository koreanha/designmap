from __future__ import annotations

from abc import ABC, abstractmethod

from src.models import DesignPatent


class BaseCollector(ABC):
    """각국 특허청 디자인 데이터 수집기의 기본 클래스"""

    @abstractmethod
    async def search(
        self,
        locarno_class: str,
        keyword: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        max_results: int = 100,
    ) -> list[DesignPatent]:
        ...

    @abstractmethod
    async def get_patent(self, application_number: str) -> DesignPatent | None:
        ...

    @abstractmethod
    async def download_drawings(self, patent: DesignPatent, output_dir: str) -> list[str]:
        ...
