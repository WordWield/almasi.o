import tempfile

from types import SimpleNamespace

from almasi import o
with tempfile.TemporaryDirectory(prefix='o_test_') as directory:
	type(o).__app__ = SimpleNamespace(__lib_path__=directory)
	o.start()

	import tester
	o.tester.run()
