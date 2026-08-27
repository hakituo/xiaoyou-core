from core.utils.logger import get_logger
import asyncio
import uuid

from typing import Callable, List, Dict, Any, Optional

from core.contracts import TransactionStatus

logger = get_logger("SAGA_TRANSACTION")


class SagaStep:
    def __init__(
        self,
        name: str,
        action: Callable[..., Any],
        compensation: Callable[..., Any],
        timeout: int = 10,
    ):
        self.name = name
        self.action = action
        self.compensation = compensation
        self.timeout = timeout


class SagaTransaction:
    """
    Saga Transaction Manager (Orchestration-based)
    Implements a simple Saga pattern for distributed transactions in Python.
    """

    def __init__(self, transaction_id: str = None):
        self.transaction_id = transaction_id or str(uuid.uuid4())
        self.steps: List[SagaStep] = []
        self.completed_steps: List[SagaStep] = []
        self.status = TransactionStatus.PENDING
        self.context: Dict[str, Any] = {}
        self.error: Optional[Exception] = None

    def add_step(
        self, name: str, action: Callable, compensation: Callable, timeout: int = 10
    ):
        """Add a step to the Saga transaction chain"""
        step = SagaStep(name, action, compensation, timeout)
        self.steps.append(step)
        return self

    async def execute(self, initial_context: Dict[str, Any] = None):
        """Execute the Saga transaction"""
        self.context = initial_context or {}
        logger.info(f"Starting Saga Transaction {self.transaction_id}")

        try:
            for step in self.steps:
                logger.info(f"Executing step: {step.name}")

                # Execute action with timeout
                try:
                    result = await asyncio.wait_for(
                        step.action(self.context), timeout=step.timeout
                    )

                    # Update context with result if it's a dict
                    if isinstance(result, dict):
                        self.context.update(result)

                    self.completed_steps.append(step)

                except Exception as e:
                    logger.error(f"Step {step.name} failed: {e}")
                    raise e

            self.status = TransactionStatus.COMPLETED
            logger.info(
                f"Saga Transaction {self.transaction_id} completed successfully"
            )
            return self.context

        except Exception as e:
            self.error = e
            self.status = TransactionStatus.FAILED
            logger.warning(
                f"Saga Transaction {self.transaction_id} failed, starting compensation"
            )
            await self._compensate()
            raise e

    async def _compensate(self):
        """Execute compensation logic in reverse order"""
        self.status = TransactionStatus.COMPENSATING
        failed_compensations = []

        # Compensate in reverse order of completion
        for step in reversed(self.completed_steps):
            logger.info(f"Compensating step: {step.name}")
            try:
                await asyncio.wait_for(
                    step.compensation(self.context), timeout=step.timeout
                )
            except Exception as e:
                logger.error(f"Compensation for step {step.name} failed: {e}")
                failed_compensations.append((step.name, str(e)))

        if failed_compensations:
            self.status = TransactionStatus.COMPENSATION_FAILED
            logger.critical(
                f"Saga Transaction {self.transaction_id} compensation failed for steps: {failed_compensations}"
            )
        else:
            self.status = TransactionStatus.COMPENSATED
            logger.info(f"Saga Transaction {self.transaction_id} fully compensated")
