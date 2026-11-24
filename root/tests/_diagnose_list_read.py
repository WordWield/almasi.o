# ==============================================================================
# LIST READ DIAGNOSTIC
# ==============================================================================
# PURPOSE:
# Separate first-read interpreter state from filesystem worker interference.
# ==============================================================================
import dis
import json
import os
import runpy
import statistics
import sys
import tempfile
import threading
import time
from types         import SimpleNamespace
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


# Measure both process and calling-thread CPU to expose observer work.
# ------------------------------------------------------------------------------
def sample(items):
	process = time.process_time_ns()
	samples = [measure(items, 100000) for _ in range(3)]
	elapsed = statistics.median(sample[0] for sample in samples)
	cpu     = statistics.median(sample[1] for sample in samples)
	other   = (time.process_time_ns() - process) / 300000 / 1000 - statistics.mean(sample[1] for sample in samples)

	return elapsed, cpu, other


# Compare the same live ontology before and after stopping only its observers.
# ------------------------------------------------------------------------------
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

		with patch.object(filesystem, '_changed_paths', **({'return_value': None} if mode == 'no_delivery' else {'wraps': filesystem._changed_paths})) as delivery:
			o.start(tree_mode=False, multiprocess=False)
			o.Timer.enabled = False
			o.T.extend('APerfRun')
			o.Timer.reset()

			time.sleep(.25)

			# Use the exact benchmark method first, not a module-scope loop.
			results['original_first'] = benchmark.trigger_list_getitem(1000) * 1000
			results['original_second'] = benchmark.trigger_list_getitem(1000) * 1000
			items = o.List([1, 2, 3, 4, 5])

			elapsed, cpu = measure(items, 1000)
			results['function_wall'] = elapsed
			results['function_cpu'] = cpu
			elapsed, cpu, other = sample(items)
			results['warm_wall']  = elapsed
			results['warm_cpu']   = cpu
			results['other_cpu']  = other
			results['batches']    = delivery.call_count
			results['paths']      = sum(len(call.args[1]) for call in delivery.call_args_list)
			results['resources']  = len(filesystem._resources)
			results['threads']    = len(threading.enumerate())

			# Keep the calling thread on a known CPU and move watchers elsewhere.
			cpus = os.sched_getaffinity(0)

			if len(cpus) > 1:
				main_cpu = min(cpus)
				os.sched_setaffinity(0, {main_cpu})

				for entry in filesystem._watchers.values():
					thread = entry['thread']

					if thread.is_alive():
						os.sched_setaffinity(thread.native_id, cpus - {main_cpu})

				elapsed, cpu, other = sample(items)
				results['pinned_wall'] = elapsed
				results['pinned_cpu']  = cpu
				results['pinned_other_cpu'] = other

			# Stop actual threads without rebuilding resources or the interpreter.
			for entry in filesystem._watchers.values():
				entry['stop'].set()

			for entry in filesystem._watchers.values():
				entry['thread'].join(2)
				assert not entry['thread'].is_alive()

			elapsed, cpu, other = sample(items)
			results['stopped_wall'] = elapsed
			results['stopped_cpu']  = cpu
			results['stopped_other_cpu'] = other
			results['total_batches'] = delivery.call_count
			results['total_paths'] = sum(len(call.args[1]) for call in delivery.call_args_list)

			print('watch roots:', tuple(filesystem._watchers), file=sys.stderr)
			print('cpus:', sorted(cpus), file=sys.stderr)

			for method in (o.List.__getitem__, o.services.Entity.value, o.services.Entity.get):
				print(method.__qualname__, ' '.join(ins.opname for ins in dis.get_instructions(method, adaptive=True)), file=sys.stderr)

			o.services.Memory.env.close()

	print(json.dumps(results))


if __name__ == '__main__':
	run()
