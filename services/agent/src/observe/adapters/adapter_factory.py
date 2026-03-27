"""
Adapter Factory
===============
Single entry point for constructing the configured Observe layer
adapter. The agent core calls AdapterFactory.create() and never
imports individual adapters directly.

To add a new adapter:
  1. Implement it in src/observe/adapters/your_adapter.py
  2. Add one line to the registry dict below.
  3. Set adapter: "your_adapter" in agent_config.yaml.

No other files need to change.
"""

import logging
from src.observe.adapters.synthetic_adapter import SyntheticAdapter
from src.observe.adapters.gaia_adapter import GaiaAdapter

logger = logging.getLogger(__name__)

# Registry — add new adapters here only
_REGISTRY = {
    "synthetic": SyntheticAdapter,
    "gaia": GaiaAdapter,
}


class AdapterFactory:

    @staticmethod
    def create(config: dict):
        """
        Instantiate and return the adapter specified in config.
        Raises ValueError for unknown adapter names.
        """
        adapter_name = config.get("data", {}).get("adapter", "synthetic")

        if adapter_name not in _REGISTRY:
            available = list(_REGISTRY.keys())
            raise ValueError(
                f"Unknown adapter '{adapter_name}'. " f"Available: {available}"
            )

        adapter_cls = _REGISTRY[adapter_name]
        adapter = adapter_cls(config)

        logger.info(
            f"AdapterFactory — created '{adapter_name}' adapter "
            f"({adapter_cls.__name__})"
        )
        return adapter
