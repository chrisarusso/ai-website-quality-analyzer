from abc import ABC, abstractmethod
from typing import List

from website_agent.models import Issue, PageResult


class Analyzer(ABC):
    category: str = "general"

    @abstractmethod
    def analyze(self, page: PageResult) -> List[Issue]:
        raise NotImplementedError

