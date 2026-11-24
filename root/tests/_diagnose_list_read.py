# ==============================================================================
# ATOMIC READ DIAGNOSTIC
# ==============================================================================
# Isolate attribute access and equivalent unwrapping on actual O entities.
# ==============================================================================

import dis
import json
import os
import statistics
import sys
import tempfile
import time
import timeit

from contextlib    import nullcontext
from types         import SimpleNamespace
from unittest.mock import patch

import almasi
from almasi import o


# Compare the existing class lookup with direct type lookup.
# ------------------------------------------------------------------------------
def value_by_type(service, identifier):
	entity = service.get(identifier)
	value  = entity

	if entity is not o.Undefined:
		if type(entity).__is_atom__:
			value = entity.__value__

	return value


# Measure a single expression using the current thread's CPU time.
# ------------------------------------------------------------------------------
def measure(statement, scope):
	timer   = timeit.Timer('for i in range(200000): ' + statement, timer=time.thread_time, globals=scope)
	samples = timer.repeat(repeat=3, number=1)

	return statistics.median(samples) * 5


# Compare the original expression against each operation it performs.
# ------------------------------------------------------------------------------
def sample(items):
	service = o.services.Entity
	ids     = items.__items__
	atom    = service.get(ids[0])
	cls     = type(atom)
	scope   = {
		'items'         : items,
		'ids'           : ids,
		'atom'          : atom,
		'cls'           : cls,
		'service'       : service,
		'get'           : service.get,
		'value'         : service.value,
		'value_by_type' : value_by_type,
	}

	assert atom.__class__ is cls
	assert atom.__value__ == 1
	assert cls.__is_atom__
	assert value_by_type(service, ids[0]) == service.value(ids[0])

	cases = {
		'list'         : 'items[i % 5]',
		'get'          : 'get(ids[i % 5])',
		'value'        : 'value(ids[i % 5])',
		'class'        : 'atom.__class__',
		'type'         : 'type(atom)',
		'flag'         : 'cls.__is_atom__',
		'class_flag'   : 'atom.__class__.__is_atom__',
		'type_flag'    : 'type(atom).__is_atom__',
		'atom_value'   : 'atom.__value__',
		'by_type'      : 'value_by_type(service, ids[i % 5])',
		'inline'       : 'entity = get(ids[i % 5]); result = entity.__value__ if entity.__class__.__is_atom__ else entity',
		'inline_type'  : 'entity = get(ids[i % 5]); result = entity.__value__ if type(entity).__is_atom__ else entity',
	}
	results = {name: measure(statement, scope) for name, statement in cases.items()}

	dis.dis(service.value, adaptive=True, show_caches=True, file=sys.stderr)
	dis.dis(service.get, adaptive=True, show_caches=True, file=sys.stderr)
	dis.dis(value_by_type, adaptive=True, show_caches=True, file=sys.stderr)

	return results


# Preserve real initialization while controlling filesystem observation.
# ------------------------------------------------------------------------------
def run():
	root        = os.environ['EXPECTED_ROOT']
	mode        = sys.argv[1]
	filesystem  = almasi.services.Filesystem
	observation = patch.object(type(filesystem), '_watch', return_value=None) if mode == 'no_watch' else nullcontext()

	assert os.path.realpath(o.__path__) == os.path.join(root, 'root')
	assert os.path.realpath(almasi.__lib_file__) == os.path.join(os.environ['EXPECTED_CORE'], 'almasi.py')

	with tempfile.TemporaryDirectory(prefix='o_read_diagnostic_') as directory:
		type(o).__app__ = SimpleNamespace(__lib_path__=directory)

		with observation:
			o.start(tree_mode=False, multiprocess=False)
			o.Timer.enabled = False
			o.T.extend('APerfRun')
			o.Timer.reset()

			items   = o.List([1, 2, 3, 4, 5])
			results = sample(items)

			o.services.Memory.env.close()

	print(json.dumps(results))


if __name__ == '__main__':
	run()
