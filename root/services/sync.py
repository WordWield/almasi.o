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


class Sync(o.Service):

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

		with self._lock:
			callbacks = tuple(self._subscribers.items())

		full = ids is None

		for callback, (watched, local_only) in callbacks:
			if local or not local_only:
				matching = ids if full or watched is None else ids & watched

				if full or matching:
					try:
						callback(matching)
					except Exception:
						logging.exception('O Sync subscriber failed')

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
		self._queue       = SimpleQueue()
		self._lock        = threading.Lock()
		self._subscribers = {}

		self._worker = threading.Thread(
			target = self._run_worker_loop,
			name   = 'o-sync',
			daemon = True,
		)
		self._worker.start()

	# Subscribe to all changes or only those originating in this process.
	# Accept subscribe(callback) or subscribe({id, ...}, callback).
	# ----------------------------------------------------------------------
	def subscribe(self, ids=None, callback=None, local_only=False):
		if callback is None:
			callback = ids
			ids      = None

		if not callable(callback):
			raise TypeError('Sync subscriber must be callable')

		if type(local_only) is not bool:
			raise TypeError('local_only must be bool')

		if ids is not None:
			if not isinstance(ids, (set, frozenset)):
				raise TypeError('Sync subscription IDs must be a set')

			ids = frozenset(ids)

		with self._lock:
			self._subscribers[callback] = (ids, local_only)

		return callback

	# Stop notifications to the given callback.
	# ----------------------------------------------------------------------
	def unsubscribe(self, callback):
		with self._lock:
			self._subscribers.pop(callback, None)

	# Skip unobserved local changes; remote changes still invalidate caches.
	# ----------------------------------------------------------------------
	def publish_change(self, ids, local=True):
		if not local or self._subscribers:
			self._queue.put((ids, local))
