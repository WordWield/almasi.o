# ==============================================================================
# LIST READ DIAGNOSTIC
# ==============================================================================
# Compare original and fresh bytecode before and after clearing lookup caches.
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
import timeit

from functools     import partial
from types         import FunctionType, MethodType, SimpleNamespace
from unittest.mock import patch

import almasi
from almasi import o


# Create a worker without entering the native filesystem observer.
# ------------------------------------------------------------------------------
def idle_watch(root, stop):
	stop.wait()


# Preserve startup registration without retaining a running observer.
# ------------------------------------------------------------------------------
def skip_watch(root, stop):
	return None


# Start native observation only after the initial measurements.
# ------------------------------------------------------------------------------
def deferred_watch(watch, ready, root, stop):
	ready.wait()
	watch(root, stop)


# Create a bound method with identical source and a fresh adaptive code object.
# ------------------------------------------------------------------------------
def fresh(method):
	function = method.__func__
	copy     = FunctionType(function.__code__.replace(), function.__globals__, function.__name__)

	return MethodType(copy, method.__self__)


# Keep the original measurement loop and compare fresh code on the same objects.
# ------------------------------------------------------------------------------
def sample(items, results, phase):
	entity = o.services.Entity
	ids    = items.__items__
	scope  = {
		'items'       : items,
		'ids'         : ids,
		'get'         : entity.get,
		'value'       : entity.value,
		'fresh_get'   : fresh(entity.get),
		'fresh_value' : fresh(entity.value),
	}

	cases = {
		'list'        : 'items[i % 5]',
		'get'         : 'get(ids[i % 5])',
		'value'       : 'value(ids[i % 5])',
		'fresh_get'   : 'fresh_get(ids[i % 5])',
		'fresh_value' : 'fresh_value(ids[i % 5])',
	}

	for name, statement in cases.items():
		timer   = timeit.Timer('for i in range(100000): ' + statement, timer=time.thread_time, globals=scope)
		samples = timer.repeat(repeat=3, number=1)
		results[phase + '/' + name] = statistics.median(samples) * 10

	print(phase, file=sys.stderr)

	for method in (entity.get, entity.value, scope['fresh_get'], scope['fresh_value']):
		dis.dis(method, adaptive=True, show_caches=True, file=sys.stderr)


# Compare lookup state without changing ontology data or observer lifetimes.
# ------------------------------------------------------------------------------
def run():
	root       = os.environ['EXPECTED_ROOT']
	mode       = sys.argv[1]
	filesystem = almasi.services.Filesystem
	benchmark  = runpy.run_path(os.path.join(root, 'root/tests/_test_performance.py'))['TestPerformance']
	ready      = threading.Event()
	results    = {}

	assert os.path.realpath(o.__path__) == os.path.join(root, 'root')
	assert os.path.realpath(almasi.__lib_file__) == os.path.join(os.environ['EXPECTED_CORE'], 'almasi.py')

	watch = {
		'immediate': filesystem._watch,
		'idle'     : idle_watch,
		'deferred' : partial(deferred_watch, filesystem._watch, ready),
		'no_watch' : skip_watch,
	}[mode]

	with tempfile.TemporaryDirectory(prefix='o_read_diagnostic_') as directory:
		type(o).__app__ = SimpleNamespace(__lib_path__=directory)

		with patch.object(type(filesystem), '_watch', staticmethod(watch)):
			o.start(tree_mode=False, multiprocess=False)
			o.Timer.enabled = False
			o.T.extend('APerfRun')
			o.Timer.reset()

			results['original_first'] = benchmark.trigger_list_getitem(1000) * 1000
			items = o.List([1, 2, 3, 4, 5])

			try:
				sample(items, results, 'initial')
				sys._clear_type_cache()
				sample(items, results, 'cleared')
				time.sleep(.25)
				sample(items, results, 'later')
			finally:
				ready.set()

				for entry in filesystem._watchers.values():
					entry['stop'].set()

				for entry in filesystem._watchers.values():
					entry['thread'].join(2)
					assert not entry['thread'].is_alive()

				o.services.Memory.env.close()

	print(json.dumps(results))


if __name__ == '__main__':
	run()
