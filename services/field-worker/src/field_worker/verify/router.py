"""Model Router, Eligibility Rules, and Contributor Model Guard (Task T2.057 / FR2.056, FR2.059, PR2.16, TC2.148)."""

from pydantic import BaseModel


class FieldContributorModelConfig(Exception):  # noqa: N818
    """Raised when any configured model ends in -contributor, violating data sovereignty rules (FR2.059, TC2.148)."""

    pass


class ModelRouterConfig(BaseModel):
    primary_model: str = "muse-spark-1.3"
    fallback_model: str = "llama-3.2-11b-vision-instruct"
    allowlist: list[str] = [
        "muse-spark-1.3",
        "llama-3.2-11b-vision-instruct",
        "llama-3.2-90b-vision-instruct",
    ]


class ModelRouter:
    """Routes captures for AI verification and selects non-contributor model endpoints."""

    def __init__(self, config: ModelRouterConfig = ModelRouterConfig()) -> None:
        self.config = config
        self._validate_models()

    def _validate_models(self) -> None:
        """Enforces FR2.059 / TC2.148: Refuse startup if any model name ends in -contributor."""
        all_models = [self.config.primary_model, self.config.fallback_model] + self.config.allowlist
        for m in all_models:
            if m.lower().endswith("-contributor"):
                raise FieldContributorModelConfig(
                    f"Configured model '{m}' ends in -contributor. Customer data must not train vendor models."
                )

    @staticmethod
    def should_verify(readability: float, on_task: bool) -> bool:
        """PR2.16: Queues verification iff readability < 0.90 or on_task is False. Otherwise not_needed."""
        return (readability < 0.90) or (not on_task)

    def select_model(self, tenant_residency_strict: bool = False) -> str:
        """Selects verification model based on tenant residency rules.

        Strict local residency routes directly to self-hosted Llama.
        """
        if tenant_residency_strict:
            return self.config.fallback_model
        return self.config.primary_model
