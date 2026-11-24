# ==============================================================================
# LIST READ DIAGNOSTIC
# ==============================================================================
# Separate native observation from thread startup and isolate read operations.
# ==============================================================================

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
from types         import SimpleNamespace
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


# Compare separate stages of the same public List read using thread CPU time.
# ------------------------------------------------------------------------------
def sample(items, results, phase):
	entity = o.services.Entity
	ids    = items.__items__
	scope  = {'o': o, 'items': items, 'ids': ids, 'entity': entity, 'value': entity.value, 'get': entity.get}

	cases = {
		'list'     : 'items[i % 5]',
		'ids'      : 'ids[i % 5]',
		'items'    : 'items.__items__[i % 5]',
		'get'      : 'get(ids[i % 5])',
		'value'    : 'value(ids[i % 5])',
		'lookup'   : 'o.services.Entity',
		'fullvalue': 'o.services.Entity.value(ids[i % 5])',
		'timer'    : "o.Timer.start('o.List.__getitem__'); o.Timer.stop('o.List.__getitem__')",
	}

	for name, statement in cases.items():
		timer   = timeit.Timer('for i in range(100000): ' + statement, timer=time.thread_time, globals=scope)
		samples = timer.repeat(repeat=3, number=1)
		results[phase + '/' + name] = statistics.median(samples) * 10


# Compare native, idle, deferred and absent observers during ontology startup.
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
				ready.set()
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
