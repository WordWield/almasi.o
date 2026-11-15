# ==============================================================================
# SYNC SERVICE
# ==============================================================================
# Queue committed changes from memory and transport through one worker.
# ==============================================================================

import logging
import os
import threading

from queue import SimpleQueue
from time  import sleep

import o


class Sync(o.Subscribable):

	# ======================================================================
	# PRIVATE METHODS
	# ======================================================================

	# One delivery point for local and external invalidations.
	# ----------------------------------------------------------------------
	def _update(self, ids, local=True):
		if not local:
			try:
				o.services.Cache.invalidate(ids)
			except Exception:
				logging.exception('Critical cache invalidation failure')
				os._exit(1)

		# Producer-specific origin gating stays behind the existing worker.
		# --------------------------------------------------------------
		self._delivery_local = local
		self._dispatch(ids)

	# Merge adjacent invalidations without changing local/remote ordering.
	# ----------------------------------------------------------------------
	def _deliver(self, events):
		changed = set()
		local   = events[0][1]

		for ids, origin in events:
			if origin != local:
				self._update(None if changed is None else frozenset(changed), local=local)
				changed = set()
				local   = origin

			if ids is None:
				changed = None
			elif changed is not None:
				changed.update(ids)

		self._update(None if changed is None else frozenset(changed), local=local)

	# Wait for work, then collect a bounded burst without busy polling.
	# ----------------------------------------------------------------------
	def _run_worker_loop(self):
		while True:
			first = self._queue.get()
			sleep(0.0001)
			events = [first]

			for _ in range(self._queue.qsize()):
				events.append(self._queue.get_nowait())

			self._deliver(events)

	# ======================================================================
	# PUBLIC METHODS
	# ======================================================================

	# Create one worker per ontology; there is no pre-commit fallback.
	# ----------------------------------------------------------------------
	def initialize(self):
		# Only the worker handles delivery.
		# --------------------------------------------------------------
		self._queue = SimpleQueue()

		self._worker = threading.Thread(
			target = self._run_worker_loop,
			name   = 'o-sync',
			daemon = True,
		)
		self._worker.start()

	# Extend the shared registration with O's local-only Transport semantics.
	# ----------------------------------------------------------------------
	def subscribe(self, ids=None, callback=None, local_only=False):
		if type(local_only) is not bool:
			raise TypeError('local_only must be bool')

		if local_only:
			if callback is None:
				callback = ids
				ids      = None

			if not callable(callback):
				raise TypeError('Sync subscriber must be callable')

			# Close over the original callback before wrapping remote events.
			# --------------------------------------------------------------
			target = callback

			def local_callback(changed):
				if self._delivery_local:
					target(changed)

			callback = local_callback

		return super().subscribe(ids, callback)

	# Skip unobserved local changes; remote changes still invalidate caches.
	# ----------------------------------------------------------------------
	def publish_change(self, ids, local=True):
		if not local or self._subscriptions:
			self._queue.put((ids, local))
