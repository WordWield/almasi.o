# ==============================================================================
# PERFORMANCE: INSTANCE VERSION ALLOCATION
# ==============================================================================
# Compare the old cached counter with the cross-process-safe LMDB counter.
# Run as a standalone script; the comparison is a microbenchmark, not a
# substitute for end-to-end object creation measurements.
# ==============================================================================

import os
import statistics
import tempfile
import time

from types import SimpleNamespace

from almasi import o
ITERATIONS = 3000
ROUNDS     = 5


# ==============================================================================
# BENCHMARK
# ==============================================================================

# Measure the cached counter and the committed counter under equal writes.
# ------------------------------------------------------------------------------
def measure(atomic, iterations=ITERATIONS):
	memory = o.services.Memory
	key    = 'bench/instance_version'
	owner  = o.T.id
	version = 0

	started = time.perf_counter_ns()

	for _ in range(iterations):
		with memory.write():
			if atomic:
				version = memory.get(key, 0)

			memory.set(key, version + 1, owner)
			version += 1

	elapsed = time.perf_counter_ns() - started
	return elapsed / iterations / 1000


# Keep the benchmark ontology isolated from application state.
# ------------------------------------------------------------------------------
def main():
	with tempfile.TemporaryDirectory(prefix='o_version_perf_') as directory:
		type(o).__app__ = SimpleNamespace(__lib_path__=directory)
		o.start()

		cached = []
		atomic = []

		for index in range(ROUNDS):
			if index % 2:
				atomic.append(measure(True))
				cached.append(measure(False))
			else:
				cached.append(measure(False))
				atomic.append(measure(True))

		a = statistics.median(cached)
		b = statistics.median(atomic)
		print(f'Cached: {a:.3f} us / allocation')
		print(f'Atomic: {b:.3f} us / allocation')
		print(f'Delta:  {b - a:+.3f} us / allocation ({(b / a - 1) * 100:+.1f}%)')


if __name__ == '__main__':
	main()
