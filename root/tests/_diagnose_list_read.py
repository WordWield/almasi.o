# ==============================================================================
# LIST READ DIAGNOSTIC
# ==============================================================================
# PURPOSE:
# Separate first-read interpreter state from filesystem worker interference.
# ==============================================================================
import gc
import json
import os
import runpy
import statistics
import sys
import tempfile
import threading
import time
from contextlib   import nullcontext
from types        import SimpleNamespace
from unittest.mock import patch

import almasi
from almasi import o


def measure(items, size):
	cpu     = time.thread_time_ns()
	started = time.perf_counter_ns()

	for index in range(size):
		items[index % 5]

	elapsed = (time.perf_counter_ns() - started) / size / 1000
	cpu     = (time.thread_time_ns() - cpu) / size / 1000
	return elapsed, cpu


def run():
	root        = os.environ['EXPECTED_ROOT']
	assert os.path.realpath(o.__path__) == os.path.join(root, 'root')
	assert os.path.realpath(almasi.__lib_file__) == os.path.join(os.environ['EXPECTED_CORE'], 'almasi.py')
	benchmark   = runpy.run_path(os.path.join(root, 'root/tests/_test_performance.py'))['TestPerformance']
	filesystem  = almasi.services.Filesystem
	mode        = sys.argv[1]
	results     = {}

	with tempfile.TemporaryDirectory(prefix='o_read_diagnostic_') as directory:
		type(o).__app__ = SimpleNamespace(__lib_path__=directory)

		with patch.object(type(filesystem), '_watch', return_value=None) if mode == 'no_watch' else nullcontext():
			o.start(tree_mode=False, multiprocess=False)
			o.Timer.enabled = False
			o.T.extend('APerfRun')
			o.Timer.reset()

			if mode == 'settled':
				time.sleep(.25)

			# Use the exact benchmark method first, not a module-scope loop.
			results['original_first'] = benchmark.trigger_list_getitem(1000) * 1000
			results['original_second'] = benchmark.trigger_list_getitem(1000) * 1000
			items = o.List([1, 2, 3, 4, 5])

			elapsed, cpu = measure(items, 1000)
			results['function_wall'] = elapsed
			results['function_cpu'] = cpu
			samples = [measure(items, 100000) for _ in range(3)]
			results['warm_wall'] = statistics.median(sample[0] for sample in samples)
			results['warm_cpu'] = statistics.median(sample[1] for sample in samples)

			gc.collect()
			results['after_gc'] = measure(items, 1000)[0]
			results['threads'] = len(threading.enumerate())
			results['watchers'] = len(filesystem._watchers)
			o.services.Memory.env.close()

	print(json.dumps(results))


if __name__ == '__main__':
	run()
