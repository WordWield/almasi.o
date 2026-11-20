# ==============================================================================
# TEST MULTIPROCESS IDENTITY
# ==============================================================================
# Verify that independent processes never allocate the same persistent ID.
# ==============================================================================

import os
import select
import subprocess
import sys
import tempfile

from types import SimpleNamespace

import o


TIMEOUT = 15


# ==============================================================================
# CHILD PROCESS
# ==============================================================================

# Load the shared type without creating an instance yet.
# ------------------------------------------------------------------------------
def child(directory, mode, value=None):
	type(o).__app__ = SimpleNamespace(__lib_path__=directory)
	o.start()

	if mode == 'prepare':
		o.T.extend('IdentityProbe', value=int)
		print('PREPARED', flush=True)
		return

	Probe = o.T.IdentityProbe
	print(f'READY {Probe.__version__}', flush=True)

	if sys.stdin.readline().strip() != 'GO':
		raise RuntimeError('Missing creation signal')

	item = Probe(value=int(value))
	print(f'CREATED {item.id} {item.__proto__} {item.value}', flush=True)


# ==============================================================================
# REGRESSION TEST
# ==============================================================================

class TestMultiprocessIdentity(o.Tester):

	# ======================================================================
	# PRIVATE METHODS
	# ======================================================================

	# Start an isolated Python interpreter against the same LMDB directory.
	# ----------------------------------------------------------------------
	@classmethod
	def _start(cls, directory, mode, value=None):
		command = [sys.executable, os.path.realpath(__file__), mode, directory]

		if value is not None:
			command.append(str(value))

		return subprocess.Popen(
			command,
			stdin  = subprocess.PIPE,
			stdout = subprocess.PIPE,
			stderr = subprocess.PIPE,
			text   = True,
		)

	# Wait until an independent process has loaded the shared class version.
	# ----------------------------------------------------------------------
	@classmethod
	def _ready(cls, process):
		ready, _, _ = select.select([process.stdout], [], [], TIMEOUT)
		assert ready, f'Child did not initialize (exit={process.poll()})'
		line = process.stdout.readline().strip()
		assert line.startswith('READY '), f'Unexpected child output: {line!r}'
		return line

	# ======================================================================
	# PUBLIC METHODS
	# ======================================================================

	# Two processes that loaded the same version must create distinct IDs.
	# ----------------------------------------------------------------------
	@classmethod
	def test_shared_type_version_allocation(cls):
		with tempfile.TemporaryDirectory(prefix='o_identity_') as directory:
			prepare = cls._start(directory, 'prepare')

			try:
				stdout, stderr = prepare.communicate(timeout=TIMEOUT)
				assert prepare.returncode == 0, stderr
				assert 'PREPARED' in stdout
			finally:
				if prepare.poll() is None:
					prepare.kill()
					prepare.communicate()

			processes = [cls._start(directory, 'worker', value) for value in (11, 22)]

			try:
				loaded = [cls._ready(process) for process in processes]
				assert loaded[0] == loaded[1], f'Expected same starting version: {loaded!r}'

				# Both children have the same cached version before either
				# creates an object. Release both only after this barrier.
				# ----------------------------------------------------------
				for process in processes:
					process.stdin.write('GO\n')
					process.stdin.flush()
					process.stdin.close()
					process.stdin = None

				created = []

				for process in processes:
					stdout, stderr = process.communicate(timeout=TIMEOUT)
					assert process.returncode == 0, stderr or stdout
					line = next((line for line in stdout.splitlines() if line.startswith('CREATED ')), None)
					assert line is not None, f'Missing creation output: {stdout!r}'
					_, identifier, proto, value = line.split()
					created.append((int(identifier), proto, int(value)))

				assert created[0][0] != created[1][0], (
					f'Persistent identity collision: both processes loaded {loaded[0]!r}, '
					f'created={created!r}'
				)
				assert {item[2] for item in created} == {11, 22}
			finally:
				for process in processes:
					if process.poll() is None:
						process.kill()
						process.communicate()


if __name__ == '__main__':
	if len(sys.argv) >= 3 and sys.argv[1] in ('prepare', 'worker'):
		child(sys.argv[2], sys.argv[1], sys.argv[3] if len(sys.argv) == 4 else None)
	else:
		TestMultiprocessIdentity.run()
