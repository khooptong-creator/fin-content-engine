"""Scheduler tests (Part II §4.4, decision #22).

The async-def invariant: every registered job MUST be async def. register_jobs
asserts this and fails at BOOT naming the offending job id.
"""

from __future__ import annotations

import asyncio

import pytest

from app.scheduler import JobSpec, make_scheduler, register_jobs, with_advisory_lock


class TestAsyncDefInvariant:
    """Decision #22: every job under AsyncIOExecutor MUST be async def."""

    def test_async_job_passes(self):
        async def good_job():
            return 42

        spec = JobSpec(id="good", minutes=30, fn=good_job)
        scheduler = make_scheduler()
        # Should not raise.
        register_jobs(scheduler, [spec])

    def test_lambda_rejected_even_if_it_calls_async(self):
        """Regression for a real prod bug: wrapping an async call in a lambda
        breaks the invariant (lambdas are never coroutine functions). Caught
        on first prod deploy after the original unit tests passed."""
        async def real_async_fn():
            return 42

        # The lambda *calls* real_async_fn, but the lambda itself is not a
        # coroutine function — inspect.iscoroutinefunction returns False.
        bad_lambda = lambda: real_async_fn()  # noqa: E731

        spec = JobSpec(id="lambda_job", minutes=30, fn=bad_lambda)
        scheduler = make_scheduler()
        with pytest.raises(RuntimeError) as exc_info:
            register_jobs(scheduler, [spec])
        assert "lambda_job" in str(exc_info.value)

    def test_sync_job_rejected_with_named_id(self):
        def bad_job():
            return 42  # plain def, not async def

        spec = JobSpec(id="bad_job_id", minutes=30, fn=bad_job)
        scheduler = make_scheduler()
        with pytest.raises(RuntimeError) as exc_info:
            register_jobs(scheduler, [spec])
        # The error must name the offending job id — that's the whole point.
        assert "bad_job_id" in str(exc_info.value)

    def test_mixed_batch_rejects_only_the_sync_one(self):
        async def good():
            pass

        def bad():
            pass

        specs = [
            JobSpec(id="good1", minutes=30, fn=good),
            JobSpec(id="bad_one", minutes=30, fn=bad),
            JobSpec(id="good2", minutes=30, fn=good),
        ]
        scheduler = make_scheduler()
        with pytest.raises(RuntimeError) as exc_info:
            register_jobs(scheduler, specs)
        assert "bad_one" in str(exc_info.value)


class TestAdvisoryLockExemption:
    """db_health is exempt (decision #27)."""

    def test_db_health_spec_has_lock_false(self):
        # The build_job_specs helper must mark db_health as lock=False.
        # We construct a JobSpec manually here to document the contract.
        async def db_ping():
            return True

        spec = JobSpec(id="db_health", minutes=5, fn=db_ping, lock=False)
        assert spec.lock is False


class TestMakeScheduler:
    def test_config_matches_spec(self):
        """§4.3: MemoryJobStore, AsyncIOExecutor, coalesce=True, max_instances=1,
        misfire_grace_time=60."""
        from apscheduler.executors.asyncio import AsyncIOExecutor
        from apscheduler.jobstores.memory import MemoryJobStore

        scheduler = make_scheduler(max_workers=4)
        # APScheduler 3.11 stores these as dicts: {'default': <impl>}.
        assert isinstance(scheduler._jobstores["default"], MemoryJobStore)
        assert isinstance(scheduler._executors["default"], AsyncIOExecutor)
        # _job_defaults is a dict in 3.11 (not a namespace object).
        defaults = scheduler._job_defaults
        assert defaults["coalesce"] is True
        assert defaults["max_instances"] == 1
        assert defaults["misfire_grace_time"] == 60
