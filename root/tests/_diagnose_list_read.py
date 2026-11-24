# ==============================================================================
# LIST READ DIAGNOSTIC
# ==============================================================================
# Compare first List reads before and after filesystem observer startup.
# ==============================================================================

import json
import os
import runpy
import statistics
import sys
import tempfile
import time

from contextlib    import nullcontext
from types         import SimpleNamespace
from unittest.mock import patch

import almasi
from almasi import o


# Measure the same indexing loop in wall, thread and process CPU time.
# ------------------------------------------------------------------------------
def measure(items, size):
	process = time.process_time_ns()
	cpu     = time.thread_time_ns()
	started = time.perf_counter_ns()

	for index in range(size):
		items[index % 5]

	elapsed = (time.perf_counter_ns() - started) / size / 1000
	cpu     = (time.thread_time_ns() - cpu) / size / 1000
	other   = (time.process_time_ns() - process) / size / 1000 - cpu

	return elapsed, cpu, other


# Compare independent startup conditions without changing the List read path.
# ------------------------------------------------------------------------------
def run():
	root       = os.environ['EXPECTED_ROOT']
	mode       = sys.argv[1]
	filesystem = almasi.services.Filesystem
	benchmark  = runpy.run_path(os.path.join(root, 'root/tests/_test_performance.py'))['TestPerformance']
	results    = {}

	assert os.path.realpath(o.__path__) == os.path.join(root, 'root')
	assert os.path.realpath(almasi.__lib_file__) == os.path.join(os.environ['EXPECTED_CORE'], 'almasi.py')
	assert mode in ('immediate', 'settled', 'no_watch')

	observation = patch.object(type(filesystem), '_watch', return_value=None) if mode == 'no_watch' else nullcontext()

	with tempfile.TemporaryDirectory(prefix='o_read_diagnostic_') as directory:
		type(o).__app__ = SimpleNamespace(__lib_path__=directory)

		with observation:
			o.start(tree_mode=False, multiprocess=False)
			o.Timer.enabled = False
			o.T.extend('APerfRun')
			o.Timer.reset()

			if mode == 'settled':
				time.sleep(.25)

			if mode == 'no_watch':
				assert not any(entry['thread'].is_alive() for entry in filesystem._watchers.values())

			results['original_first']  = benchmark.trigger_list_getitem(1000) * 1000
			results['original_second'] = benchmark.trigger_list_getitem(1000) * 1000

			items   = o.List([1, 2, 3, 4, 5])
			samples = [measure(items, 100000) for _ in range(3)]

			results['warm_wall']  = statistics.median(sample[0] for sample in samples)
			results['warm_cpu']   = statistics.median(sample[1] for sample in samples)
			results['other_cpu']  = statistics.mean(sample[2] for sample in samples)
			results['observers'] = sum(entry['thread'].is_alive() for entry in filesystem._watchers.values())

			o.services.Memory.env.close()

	print(json.dumps(results))


if __name__ == '__main__':
	run()
