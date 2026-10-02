"""core/utils/concurrency/saga_manager.py 单测。

覆盖 Saga 事务的正向执行、失败后逆序补偿、补偿自身失败降级，以及超时分支。

关于「禁止 flaky」：超时分支不依赖真实时间流逝。做法是把模块内的 `asyncio`
引用替换成代理对象，由代理精确决定第几次 `wait_for` 抛 `asyncio.TimeoutError`，
同时记录传进来的 timeout 值（顺带锁住「step.timeout 确实被转发给 wait_for」这条契约）。
"""

from __future__ import annotations

import asyncio

import pytest

from core.contracts import TransactionStatus
from core.utils.concurrency import saga_manager
from core.utils.concurrency.saga_manager import SagaStep, SagaTransaction


class _WaitForProxy:
    """替换模块内 `asyncio` 引用的代理。

    - `raise_timeout_calls`：需要抛超时的调用序号（0 起），其余调用走真实实现。
    - `timeouts`：按调用顺序记录收到的 timeout 实参，用于断言转发正确。
    """

    TimeoutError = asyncio.TimeoutError

    def __init__(self, raise_timeout_calls=()):
        self._raise = set(raise_timeout_calls)
        self.timeouts: list[float] = []
        self.calls = 0

    async def wait_for(self, coro, timeout):
        index = self.calls
        self.calls += 1
        self.timeouts.append(timeout)
        if index in self._raise:
            # 关掉未被消费的协程，避免 "coroutine was never awaited" 噪音
            coro.close()
            raise asyncio.TimeoutError()
        return await asyncio.wait_for(coro, timeout=timeout)


# ============================================================
# SagaStep
# ============================================================


class TestSagaStep:
    def test_stores_all_fields(self):
        async def act(ctx):
            return None

        async def comp(ctx):
            return None

        step = SagaStep("s1", act, comp, timeout=7)
        assert step.name == "s1"
        assert step.action is act
        assert step.compensation is comp
        assert step.timeout == 7

    def test_default_timeout_is_ten(self):
        step = SagaStep("s1", lambda c: None, lambda c: None)
        assert step.timeout == 10


# ============================================================
# SagaTransaction 初始化与 add_step
# ============================================================


class TestTransactionInit:
    def test_generates_uuid_and_starts_pending(self):
        tx = SagaTransaction()
        assert tx.transaction_id
        assert tx.status is TransactionStatus.PENDING
        assert tx.steps == []
        assert tx.completed_steps == []
        assert tx.context == {}
        assert tx.error is None

    def test_uses_explicit_transaction_id(self):
        assert SagaTransaction("tx-1").transaction_id == "tx-1"

    def test_two_transactions_get_distinct_ids(self):
        assert SagaTransaction().transaction_id != SagaTransaction().transaction_id


class TestAddStep:
    def test_is_chainable_and_keeps_insertion_order(self):
        async def act(ctx):
            return None

        tx = SagaTransaction("t")
        returned = tx.add_step("a", act, act).add_step("b", act, act)
        assert returned is tx
        assert [s.name for s in tx.steps] == ["a", "b"]

    def test_timeout_is_stored_on_step(self):
        async def act(ctx):
            return None

        tx = SagaTransaction("t")
        tx.add_step("a", act, act, timeout=42)
        assert tx.steps[0].timeout == 42


# ============================================================
# 成功路径
# ============================================================


class TestExecuteSuccess:
    @pytest.mark.asyncio
    async def test_runs_steps_in_order_and_returns_merged_context(self):
        order: list[str] = []

        async def one(ctx):
            order.append("one")
            return {"a": 1}

        async def two(ctx):
            order.append("two")
            return {"b": 2}

        tx = SagaTransaction("t")
        tx.add_step("one", one, one).add_step("two", two, two)

        result = await tx.execute()

        assert order == ["one", "two"]
        assert result == {"a": 1, "b": 2}
        assert tx.context == {"a": 1, "b": 2}
        assert tx.status is TransactionStatus.COMPLETED
        assert tx.error is None
        assert [s.name for s in tx.completed_steps] == ["one", "two"]

    @pytest.mark.asyncio
    async def test_initial_context_is_visible_to_steps_and_returned(self):
        seen: dict = {}

        async def act(ctx):
            seen.update(ctx)

        tx = SagaTransaction("t")
        tx.add_step("a", act, act)

        result = await tx.execute({"seed": 1})

        assert seen == {"seed": 1}
        assert result == {"seed": 1}

    @pytest.mark.asyncio
    async def test_none_initial_context_becomes_empty_dict(self):
        tx = SagaTransaction("t")
        assert await tx.execute(None) == {}

    @pytest.mark.asyncio
    async def test_non_dict_result_is_not_merged_into_context(self):
        async def act(ctx):
            return ["not", "a", "dict"]

        tx = SagaTransaction("t")
        tx.add_step("a", act, act)

        assert await tx.execute({"seed": 1}) == {"seed": 1}

    @pytest.mark.asyncio
    async def test_transaction_without_steps_completes(self):
        tx = SagaTransaction("t")
        assert await tx.execute() == {}
        assert tx.status is TransactionStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_step_timeout_is_forwarded_to_wait_for(self, monkeypatch):
        proxy = _WaitForProxy()
        monkeypatch.setattr(saga_manager, "asyncio", proxy)

        async def act(ctx):
            return None

        tx = SagaTransaction("t")
        tx.add_step("a", act, act, timeout=3)
        tx.add_step("b", act, act, timeout=9)

        await tx.execute()

        assert proxy.timeouts == [3, 9]


# ============================================================
# 失败与补偿
# ============================================================


class TestFailureAndCompensation:
    @pytest.mark.asyncio
    async def test_failure_marks_error_and_reraises(self):
        async def ok(ctx):
            return None

        async def boom(ctx):
            raise ValueError("nope")

        tx = SagaTransaction("t")
        tx.add_step("ok", ok, ok).add_step("boom", boom, boom)

        with pytest.raises(ValueError, match="nope"):
            await tx.execute()

        assert isinstance(tx.error, ValueError)
        # 补偿全部成功 → 状态落在 COMPENSATED
        assert tx.status is TransactionStatus.COMPENSATED

    @pytest.mark.asyncio
    async def test_compensation_runs_in_reverse_order_and_skips_failed_step(self):
        comp_order: list[str] = []

        def comp_for(name: str):
            async def comp(ctx):
                comp_order.append(name)

            return comp

        async def ok(ctx):
            return None

        async def boom(ctx):
            raise RuntimeError("x")

        tx = SagaTransaction("t")
        tx.add_step("s1", ok, comp_for("s1"))
        tx.add_step("s2", ok, comp_for("s2"))
        tx.add_step("s3", boom, comp_for("s3"))

        with pytest.raises(RuntimeError):
            await tx.execute()

        # 逆序补偿；失败步自身未完成，不参与补偿
        assert comp_order == ["s2", "s1"]

    @pytest.mark.asyncio
    async def test_steps_after_failure_are_never_executed(self):
        ran: list[str] = []

        async def ok(ctx):
            ran.append("ok")

        async def boom(ctx):
            raise RuntimeError("x")

        async def noop(ctx):
            return None

        tx = SagaTransaction("t")
        # 补偿用 noop，避免「补偿也调用 ok」污染 ran，让 ran 只反映 action 的调用
        tx.add_step("ok", ok, noop)
        tx.add_step("boom", boom, noop)
        tx.add_step("never", ok, noop)

        with pytest.raises(RuntimeError):
            await tx.execute()

        assert ran == ["ok"]
        assert [s.name for s in tx.completed_steps] == ["ok"]

    @pytest.mark.asyncio
    async def test_status_is_compensating_while_compensating(self):
        observed: list[TransactionStatus] = []
        tx = SagaTransaction("t")

        async def ok(ctx):
            return None

        async def boom(ctx):
            raise RuntimeError("x")

        async def comp(ctx):
            observed.append(tx.status)

        tx.add_step("ok", ok, comp)
        tx.add_step("boom", boom, boom)

        with pytest.raises(RuntimeError):
            await tx.execute()

        assert observed == [TransactionStatus.COMPENSATING]

    @pytest.mark.asyncio
    async def test_failed_compensation_does_not_block_remaining_and_downgrades_status(self):
        comp_order: list[str] = []

        async def ok(ctx):
            return None

        async def boom(ctx):
            raise RuntimeError("x")

        async def bad_comp(ctx):
            comp_order.append("bad")
            raise ValueError("comp 失败")

        async def good_comp(ctx):
            comp_order.append("good")

        tx = SagaTransaction("t")
        tx.add_step("s1", ok, good_comp)
        tx.add_step("s2", ok, bad_comp)
        tx.add_step("s3", boom, boom)

        with pytest.raises(RuntimeError):
            await tx.execute()

        # 坏补偿不阻断后续补偿；顺序仍为逆序
        assert comp_order == ["bad", "good"]
        assert tx.status is TransactionStatus.COMPENSATION_FAILED

    @pytest.mark.asyncio
    async def test_action_timeout_is_treated_as_failure_then_compensated(self, monkeypatch):
        # 调用序号：0 = s1 正向（正常），1 = s2 正向（抛超时），2 = s1 补偿（正常）
        proxy = _WaitForProxy(raise_timeout_calls={1})
        monkeypatch.setattr(saga_manager, "asyncio", proxy)

        comp: list[str] = []

        async def ok(ctx):
            return None

        async def comp_fn(ctx):
            comp.append("c")

        tx = SagaTransaction("t")
        tx.add_step("s1", ok, comp_fn)  # 先成功一步，失败后才有东西可补偿
        tx.add_step("s2", ok, comp_fn)

        with pytest.raises(asyncio.TimeoutError):
            await tx.execute()

        assert comp == ["c"]
        assert isinstance(tx.error, asyncio.TimeoutError)
        assert tx.status is TransactionStatus.COMPENSATED

    @pytest.mark.asyncio
    async def test_compensation_timeout_downgrades_status(self, monkeypatch):
        # 调用序号：0 = s1 正向（正常），1 = s2 正向（抛业务异常），2 = s1 补偿（抛超时）
        proxy = _WaitForProxy(raise_timeout_calls={2})
        monkeypatch.setattr(saga_manager, "asyncio", proxy)

        async def ok(ctx):
            return None

        async def boom(ctx):
            raise RuntimeError("x")

        async def comp_fn(ctx):
            return None

        tx = SagaTransaction("t")
        tx.add_step("s1", ok, comp_fn)
        tx.add_step("s2", boom, comp_fn)

        with pytest.raises(RuntimeError, match="x"):
            await tx.execute()

        assert tx.status is TransactionStatus.COMPENSATION_FAILED
