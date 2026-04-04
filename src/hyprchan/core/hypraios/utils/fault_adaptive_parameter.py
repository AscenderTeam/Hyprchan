import json
from pathlib import Path


class FaultAdaptiveParameter:
    """
    Incomplete version of the parameter that accepts the given parameter and slowly adapts 
    if the wrong constant causes error or system breakdown.
    
    It caches the value and saves it just like weights.
    Bounds are derived from the initial value using min/max delta.
    """
    DEFAULT_WEIGHTS_DIR = ".weights"
    DEFAULT_CACHE_NAME = "fault_adaptive_parameter"

    def __init__(
        self, 
        value: float, 
        max_delta: float = 0.5,
        min_delta: float = 0.5,
        step: float = 0.01,
        cache_key: str | None = None,
        weights_dir: str = DEFAULT_WEIGHTS_DIR
    ) -> None:
        self.cache_key = cache_key or self.DEFAULT_CACHE_NAME
        self.weights_dir = weights_dir
        self.max_delta = max_delta
        self.min_delta = min_delta
        self.step = step
        self._base_value = value
        self._normalize_bounds()
        self._value = self._clamp(value)
        self._root_dir = self._find_project_root()
        self._load_cache()
    
    @property
    def value(self):
        return self._value

    @value.setter
    def value(self, new_val: float):
        self._value = self._clamp(new_val)
    
    def adjust(self, x: float):
        """
        If error signal (x) is too aggressive, then > 0.
        If error signal (x) is weak, then < 0.

        Args:
            x (float): Error signal rate.
        """
        if x == 0:
            return self._value

        direction = -1 if x > 0 else 1
        delta = abs(x) * self.step
        new_val = self._value + (direction * delta)

        if new_val >= self._max_value:
            new_val = max(self._min_value, self._max_value - self.step)
        elif new_val <= self._min_value:
            new_val = min(self._max_value, self._min_value + self.step)

        self._value = self._clamp(new_val)
        self._save_cache()
        return self._value

    def _normalize_bounds(self):
        self.min_delta = abs(self.min_delta)
        self.max_delta = abs(self.max_delta)
        self._min_value = self._base_value - self.min_delta
        self._max_value = self._base_value + self.max_delta

    def _clamp(self, value: float) -> float:
        return max(self._min_value, min(self._max_value, value))

    def _weights_root(self):
        root = Path(self.weights_dir)
        if root.is_absolute():
            return root
        return self._root_dir / root

    def _find_project_root(self):
        start = Path(__file__).resolve()
        for parent in (start, *start.parents):
            if (parent / "pyproject.toml").exists() or (parent / ".git").exists():
                return parent
        return Path.cwd()

    def _cache_path(self):
        return self._weights_root() / f"{self.cache_key}.json"

    def _load_cache(self):
        cache_path = self._cache_path()
        if not cache_path.exists():
            return
        try:
            data = json.loads(cache_path.read_text())
        except (OSError, ValueError):
            return
        cached_val = data.get("value")
        if isinstance(cached_val, (int, float)):
            self._value = self._clamp(float(cached_val))

    def _save_cache(self):
        cache_path = self._cache_path()
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps({"value": self._value}))
        except OSError:
            return
