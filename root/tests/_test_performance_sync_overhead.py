# ==============================================================================
# SYNC PRODUCER OVERHEAD DIAGNOSTIC
# ==============================================================================
# PURPOSE:
# Measure committed writes, publication, matching and dependency refresh.
#
# RESPONSIBILITY BOUNDARIES:
# Owns: Timings of identical isolated workloads across revisions.
# Delegates: Persistence, indexing and delivery to the actual O runtime.
# ==============================================================================

import argparse
import json
import os
import statistics
import subprocess
import sys
import tempfile
import threading
import time

from types import SimpleNamespace

from almasi import o

OWNER_ID = 1 << 60
BLOCK_ID = OWNER_ID + 1
DRAIN_ID = OWNER_ID + 2


class TestPerformanceSyncOverhead(o.Tester):

	# ======================================================================
	# PRIVATE METHODS
	# ======================================================================

	# Wait for all previously queued publications to reach the worker.
	# ----------------------------------------------------------------------
	@classmethod
	def _drain(cls, sync):
		done     = threading.Event()
		callback = sync.subscribe({DRAIN_ID}, lambda ids: done.set())

		try:
			sync.publish_change([DRAIN_ID])
			assert done.wait(10), 'Changes worker did not drain'
		finally:
			cls._cancel(callback)

	# Accept the master handle and the current cancellation callable in A/B runs.
	# ----------------------------------------------------------------------
	@staticmethod
	def _cancel(handle, resource=None):
		if callable(handle):
			handle()
		elif resource is not None and not hasattr(handle, 'cancel'):
			resource.unsubscribe(handle)
		else:
			handle.cancel()

	# Each sample runs in a fresh process with an independent LMDB store.
	# ----------------------------------------------------------------------
	@classmethod
	def _measure(cls, mode, size):
		with tempfile.TemporaryDirectory(prefix='o_sync_overhead_') as directory:
			type(o).__app__ = SimpleNamespace(__lib_path__=directory)
			o.start(multiprocess=False)

			memory   = o.services.Memory
			sync     = o.services.Changes
			release  = threading.Event()
			entered  = threading.Event()
			callback = None
			result   = {}

			try:
				cls._drain(sync)

				if mode == 'stub':
					memory.sync = SimpleNamespace(publish_change=lambda ids, local=True: None)

				elif mode == 'paused':
					# Suspend the worker inside a test subscriber, leaving
					# the real producer queue available for write operations.
					# ----------------------------------------------------------
					def block(ids):
						entered.set()
						assert release.wait(20), 'Paused worker timeout'

					callback = sync.subscribe({BLOCK_ID}, block)
					sync.publish_change([BLOCK_ID])
					assert entered.wait(5), 'Worker did not pause'

				elif mode == 'subscriber':
					callback = sync.subscribe({OWNER_ID}, lambda ids: None)

				# Separate LMDB commit for each mutation.
				# --------------------------------------------------------------
				started = time.perf_counter_ns()

				for index in range(size):
					memory.set('sync/perf/overhead', index, OWNER_ID)

				result['write_single'] = (time.perf_counter_ns() - started) / (1000 * size)

				if mode not in ('stub', 'paused'):
					cls._drain(sync)

				# Isolate publish_change from any LMDB activity.
				# --------------------------------------------------------------
				publish = memory.sync.publish_change
				ids     = [OWNER_ID]
				started = time.perf_counter_ns()

				for index in range(size):
					publish(ids, local=True)

				result['publish_only'] = (time.perf_counter_ns() - started) / (1000 * size)

			finally:
				if mode == 'paused':
					release.set()

				if callback is not None:
					cls._cancel(callback)

				if mode != 'stub':
					cls._drain(sync)

				memory.env.close()

		return result

	# Supply the same minimal callback to every measured observer.
	# ----------------------------------------------------------------------
	@staticmethod
	def _ignore(ids):
		return None

	# Time direct delivery without worker scheduling or storage operations.
	# ----------------------------------------------------------------------
	@classmethod
	def _measure_dispatch(
		cls,
		sync,
		count,
		iterations,
		dense=False
	):
		handles = [
			sync.subscribe({OWNER_ID if dense else OWNER_ID + index}, cls._ignore)
			for index in range(count)
		]
		changed = frozenset({OWNER_ID})

		try:
			for index in range(100):
				sync._dispatch(changed)

			started = time.perf_counter_ns()

			for index in range(iterations):
				sync._dispatch(changed)

			result = (time.perf_counter_ns() - started) / (1000 * iterations)
		finally:
			for handle in handles:
				cls._cancel(handle)

		return result

	# Measure multiple listeners on a real computed resource and repeated reads.
	# ----------------------------------------------------------------------
	@classmethod
	def _measure_computed(cls, sync, size):
		item     = o.List([1])
		resource = sync.resource()
		handles  = [resource.subscribe(cls._ignore) for index in range(32)]

		try:
			with o.services.Tracker.track_reads(resource) as observed:
				observed.value = item[0]

			cls._drain(sync)
			changed = frozenset({item.id})

			started = time.perf_counter_ns()

			for index in range(size):
				sync._dispatch(changed)

			delivery = (time.perf_counter_ns() - started) / (1000 * size)

			started = time.perf_counter_ns()

			for index in range(size):
				with o.services.Tracker.track_reads(resource) as observed:
					observed.value = item[0]

			refresh = (time.perf_counter_ns() - started) / (1000 * size)
		finally:
			for handle in handles:
				cls._cancel(handle, resource)

		return delivery, refresh

	# ======================================================================
	# PUBLIC METHODS
	# ======================================================================

	# Compare actual source dispatch and repeated tracked computation.
	# ----------------------------------------------------------------------
	@classmethod
	def measure_dispatch(cls, size):
		with tempfile.TemporaryDirectory(prefix='o_sync_dispatch_') as directory:
			type(o).__app__ = SimpleNamespace(__lib_path__=directory)
			o.start(multiprocess=False)

			sync   = o.services.Changes
			result = {}

			try:
				result['small_sparse'] = cls._measure_dispatch(sync, 8, size)
				result['large_sparse'] = cls._measure_dispatch(sync, 1000, size)
				result['large_dense']  = cls._measure_dispatch(sync, 1000, min(size, 300), dense=True)

				result['shared_delivery'], result['unchanged_refresh'] = cls._measure_computed(sync, size)
			finally:
				o.services.Memory.env.close()

		return result

	# Run one producer diagnostic with an isolated store.
	# ----------------------------------------------------------------------
	@classmethod
	def measure(cls, mode, size):
		return cls._measure(mode, size)


# Alternate subprocess modes to limit thermal and ordering bias.
# ------------------------------------------------------------------------------
if __name__ == '__main__':
	parser = argparse.ArgumentParser()
	parser.add_argument('--size', type=int, default=10000)
	parser.add_argument('--rounds', type=int, default=5)
	parser.add_argument('--mode', choices=('all', 'stub', 'paused', 'worker', 'subscriber'), default='all')
	parser.add_argument('--_json', action='store_true', help=argparse.SUPPRESS)
	parser.add_argument('--dispatch', action='store_true')
	args = parser.parse_args()

	if args.size <= 0 or args.rounds <= 0:
		parser.error('size and rounds must be positive')

	if args.dispatch:
		print(json.dumps(TestPerformanceSyncOverhead.measure_dispatch(args.size)))
	elif args._json:
		print(json.dumps(TestPerformanceSyncOverhead.measure(args.mode, args.size)))
	else:
		modes   = ('stub', 'paused', 'worker', 'subscriber') if args.mode == 'all' else (args.mode,)
		runner  = os.path.abspath(__file__)
		samples = {mode: {} for mode in modes}

		print(f'{args.rounds} rounds x {args.size} iterations; multiprocess=False.', flush=True)

		for round_index in range(args.rounds):
			order = modes if round_index % 2 == 0 else tuple(reversed(modes))

			for mode in order:
				print(f'Round {round_index + 1}/{args.rounds}: {mode}', flush=True)
				completed = subprocess.run(
					[sys.executable, runner, '--_json', '--mode', mode, '--size', str(args.size)],
					capture_output = True,
					text           = True,
				)

				if completed.returncode:
					raise RuntimeError(f'{mode}: ' + completed.stdout + completed.stderr)

				for name, microseconds in json.loads(completed.stdout.strip().splitlines()[-1]).items():
					samples[mode].setdefault(name, []).append(microseconds)

		print()
		print('Microseconds per operation: median [min..max]. Lower is faster.')
		print(f'{"Mode":12} {"Write + commit":>27} {"Publish only":>27}')
		print('-' * 69)

		for mode in modes:
			columns = []

			for name in ('write_single', 'publish_only'):
				values = samples[mode][name]
				columns.append(
					f'{statistics.median(values):8.3f} [{min(values):8.3f}..{max(values):8.3f}]'
				)

			print(f'{mode:12} {columns[0]:>27} {columns[1]:>27}')

		print()
		print('stub: no Changes publication')
		print('paused: real queue, worker blocked during timing')
		print('worker: active Changes, no observers; local notifications are skipped')
		print('subscriber: real Changes, one no-op subscriber')
		print('Differences include thread scheduling/GIL, not just method execution.')
