# ==============================================================================
# TEST TRACKER WRITES
# ==============================================================================
# Verify committed write observation, origin filtering and execution isolation.
# ==============================================================================

import asyncio
import tempfile
import threading
import time

from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import patch

import o


class TestTrackerWrites(o.Tester):

	RUNTIME_PREFIX = 'o_tracker_writes_'

	# ======================================================================
	# PUBLIC METHODS
	# ======================================================================

	# Record owners of successful O writes, without duplicates.
	# ----------------------------------------------------------------------
	@classmethod
	def test_committed_owner_ids(cls):
		state = cls._patch_runtime()

		try:
			memory  = o.services.Memory
			tracker = o.services.Tracker

			with tracker.track_writes() as writes:
				memory.set('tracker/writes/one', 1, 101)
				memory.set('tracker/writes/one', 2, 101)
				memory.set('tracker/writes/two', 3, 202)
				assert writes == {101, 202}

			assert writes == {101, 202}
		finally:
			cls._restore_runtime(state)

	# Public O mutations must report the owner that changed.
	# ----------------------------------------------------------------------
	@classmethod
	def test_public_ontology_mutation(cls):
		state = cls._patch_runtime()

		try:
			items = o.Dict({'value': 1})

			with o.services.Tracker.track_writes() as writes:
				items['value'] = 2
				items['extra'] = 3
				del items['extra']

			assert items.id in writes
			assert items['value'] == 2
			assert 'extra' not in items
		finally:
			cls._restore_runtime(state)

	# Reads and out-of-scope writes must not enter a write trace.
	# ----------------------------------------------------------------------
	@classmethod
	def test_read_only_and_scope_boundary(cls):
		state = cls._patch_runtime()

		try:
			memory  = o.services.Memory
			tracker = o.services.Tracker
			memory.set('tracker/writes/previous', 1, 301)

			with tracker.track_writes() as writes:
				assert memory.get('tracker/writes/previous') == 1
				assert writes == set()
				memory.set('tracker/writes/current', 2, 302)

			memory.set('tracker/writes/later', 3, 303)
			assert writes == {302}
		finally:
			cls._restore_runtime(state)

	# The outer transaction confirms all owners only after its commit.
	# ----------------------------------------------------------------------
	@classmethod
	def test_nested_transaction_commits_once(cls):
		state = cls._patch_runtime()

		try:
			memory = o.services.Memory

			with o.services.Tracker.track_writes() as writes:
				with memory.write() as batch:
					batch.set('tracker/writes/outer', 1, 401)

					with memory.write() as nested:
						assert nested is batch
						nested.set('tracker/writes/inner', 2, 402)

					assert writes == set()

				assert writes == {401, 402}
		finally:
			cls._restore_runtime(state)

	# A rolled-back transaction must never publish its pending owners.
	# ----------------------------------------------------------------------
	@classmethod
	def test_rollback_omits_writes(cls):
		state = cls._patch_runtime()

		try:
			memory = o.services.Memory

			with o.services.Tracker.track_writes() as writes:
				try:
					with memory.write() as batch:
						batch.set('tracker/writes/abort', 1, 501)
						raise ValueError('Abort')
				except ValueError:
					pass

				assert writes == set()
				assert not memory.has('tracker/writes/abort')
		finally:
			cls._restore_runtime(state)

	# A failure in a nested batch aborts even if the caller catches it.
	# ----------------------------------------------------------------------
	@classmethod
	def test_nested_failed_batch_omits_writes(cls):
		state = cls._patch_runtime()

		try:
			memory = o.services.Memory
			failed = False

			with o.services.Tracker.track_writes() as writes:
				try:
					with memory.write() as outer:
						outer.set('tracker/writes/nested_abort', 1, 601)

						try:
							with memory.write() as inner:
								inner.set('tracker/writes/nested_abort_2', 2, 602)
								raise ValueError('Abort')
						except ValueError:
							pass
				except RuntimeError:
					failed = True

			assert failed
			assert writes == set()
			assert not memory.has('tracker/writes/nested_abort')
		finally:
			cls._restore_runtime(state)

	# Broader scopes observe nested commits; inner scopes do not see outer-only work.
	# ----------------------------------------------------------------------
	@classmethod
	def test_nested_write_scopes(cls):
		state = cls._patch_runtime()

		try:
			memory  = o.services.Memory
			tracker = o.services.Tracker

			with tracker.track_writes() as outer:
				memory.set('tracker/writes/start', 1, 701)

				with tracker.track_writes() as inner:
					memory.set('tracker/writes/nested', 2, 702)

				memory.set('tracker/writes/end', 3, 703)

			assert outer == {701, 702, 703}
			assert inner == {702}
		finally:
			cls._restore_runtime(state)

	# The source flag distinguishes real local commits from remote invalidations.
	# ----------------------------------------------------------------------
	@classmethod
	def test_remote_origin_is_excluded_even_in_same_thread(cls):
		state = cls._patch_runtime()

		try:
			sync = o.services.Sync

			with o.services.Tracker.track_writes() as writes:
				sync.publish_change([801], local=False)
				o.services.Memory.set('tracker/writes/local', 1, 802)

			assert writes == {802}
		finally:
			cls._restore_runtime(state)

	# The producer thread must own the commit observation.
	# ----------------------------------------------------------------------
	@classmethod
	def test_other_thread_events_are_excluded(cls):
		state = cls._patch_runtime()

		try:
			with o.services.Tracker.track_writes() as writes:
				thread = threading.Thread(
					target = o.services.Sync.publish_change,
					args   = ([901],),
					kwargs = {'local': False},
				)
				thread.start()
				thread.join(timeout=5)
				assert not thread.is_alive()
				assert writes == set()

				o.services.Memory.set('tracker/writes/local', 1, 902)

			assert writes == {902}
		finally:
			cls._restore_runtime(state)

	# Two concurrent producer threads must retain separate ID sets.
	# ----------------------------------------------------------------------
	@classmethod
	def test_concurrent_threads(cls):
		state = cls._patch_runtime()

		try:
			tracker = o.services.Tracker
			memory  = o.services.Memory
			barrier = threading.Barrier(2)
			lock    = threading.Lock()

			def worker(owner):
				with tracker.track_writes() as writes:
					barrier.wait(timeout=10)

					with lock:
						memory.set(f'tracker/writes/thread_{owner}', owner, owner)

					barrier.wait(timeout=10)

				return writes

			with ThreadPoolExecutor(max_workers=2) as pool:
				first  = pool.submit(worker, 1001)
				second = pool.submit(worker, 1002)
				assert first.result(timeout=15) == {1001}
				assert second.result(timeout=15) == {1002}
		finally:
			cls._restore_runtime(state)

	# Concurrent async tasks in one thread must not share write scopes.
	# ----------------------------------------------------------------------
	@classmethod
	def test_concurrent_async_tasks(cls):
		state = cls._patch_runtime()

		try:
			async def worker(owner):
				with o.services.Tracker.track_writes() as writes:
					await asyncio.sleep(0)
					o.services.Memory.set(f'tracker/writes/task_{owner}', owner, owner)
					await asyncio.sleep(0)

				return writes

			async def run():
				return await asyncio.gather(worker(1101), worker(1102))

			first, second = asyncio.run(run())
			assert first == {1101}
			assert second == {1102}
		finally:
			cls._restore_runtime(state)

	# A full invalidation is represented by the None wildcard.
	# ----------------------------------------------------------------------
	@classmethod
	def test_unknown_owner_reports_full_invalidation(cls):
		state = cls._patch_runtime()

		try:
			with o.services.Tracker.track_writes() as writes:
				o.services.Memory.set('tracker/writes/unknown', 1, None)
				o.services.Memory.set('tracker/writes/known', 2, 1201)

			assert writes == {None}
		finally:
			cls._restore_runtime(state)

	# Exceptions close tracking scopes without removing committed observations.
	# ----------------------------------------------------------------------
	@classmethod
	def test_exception_restores_hook(cls):
		state = cls._patch_runtime()

		try:
			tracker  = o.services.Tracker
			sync     = o.services.Sync
			original = type(sync).__dict__['publish_change']
			writes   = None
			failed   = False

			try:
				with tracker.track_writes() as writes:
					assert type(sync).__dict__['publish_change'] is not original
					o.services.Memory.set('tracker/writes/before_error', 1, 1301)
					raise ValueError('Expected')
			except ValueError:
				failed = True

			assert failed
			assert writes == {1301}
			assert type(sync).__dict__['publish_change'] is original
			o.services.Memory.set('tracker/writes/after_error', 2, 1302)
			assert writes == {1301}
		finally:
			cls._restore_runtime(state)

	# Read observation and write observation must not alter each other's work.
	# ----------------------------------------------------------------------
	@classmethod
	def test_read_tracking_coexists_with_write_tracking(cls):
		state = cls._patch_runtime()

		try:
			Model   = o.T.extend('TrackerWriteReadCoexist', value=int)
			person  = Model(value=1)
			tracker = o.services.Tracker

			with tracker.track_reads() as resource:
				with tracker.track_writes() as writes:
					assert person.value == 1
					o.services.Memory.set('tracker/writes/read_coexist', 2, 1401)

			assert writes == {1401}
			assert person.id in resource.dependencies
		finally:
			cls._restore_runtime(state)

	# Each ontology fork uses its own Sync publisher and Tracker scopes.
	# ----------------------------------------------------------------------
	@classmethod
	def test_fork_isolation(cls):
		with tempfile.TemporaryDirectory(prefix='o_tracker_write_forks_') as directory:
			app   = SimpleNamespace(__lib_path__=directory)
			alice = o.fork(f'tracker_write_alice_{time.time_ns()}')
			bob   = o.fork(f'tracker_write_bob_{time.time_ns()}')

			with patch.object(type(o), '__app__', app):
				try:
					alice.start()
					bob.start()

					with alice.services.Tracker.track_writes() as first:
						with bob.services.Tracker.track_writes() as second:
							alice.services.Memory.set('tracker/writes/alice', 1, 1501)
							bob.services.Memory.set('tracker/writes/bob', 2, 1502)

					assert first == {1501}
					assert second == {1502}
				finally:
					for source in (alice, bob):
						if 'env' in source.services.Memory.__dict__:
							source.services.Memory.env.close()


if __name__ == '__main__':
	TestTrackerWrites.run()
