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

	# Match changed owner IDs through the existing sparse/dense subscription index.
	# ----------------------------------------------------------------------
	def _matches_generator(self, changed):
		changes = changed if changed is None or isinstance(changed, frozenset) else self._scope(changed)

		if changes is None or len(self._snapshot) <= 16:
			candidates = self._snapshot
		elif changes:
			with self._subscription_lock:
				potential = len(self._broad) + sum(
					len(self._by_id.get(identifier, ())) for identifier in changes
				)

				if potential * 2 >= len(self._subscriptions):
					candidates = self._snapshot
				else:
					matched = set(self._broad)

					for identifier in changes:
						matched.update(self._by_id.get(identifier, ()))

					candidates = tuple(
						(subscription, subscription._identifiers)
						for subscription in sorted(matched, key=self._subscriptions.__getitem__)
					)
		else:
			candidates = ()

		for subscription, identifiers in candidates:
			matching = None if changes is None else (
				changes if identifiers is None else changes & identifiers
			)

			if (changes is None or matching) and not getattr(subscription, '_commit_observer', False):
				yield subscription, matching

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

	# Create a computed resource without assigning external identity.
	# ----------------------------------------------------------------------
	def resource(self):
		return o.ComputedResource()

	# Bind a computed resource to its observed O owners, initially broad.
	# Preserve one independent source Subscription per listener.
	# ----------------------------------------------------------------------
	def subscribe(self, ids=None, callback=None, local_only=False):
		if type(local_only) is not bool:
			raise TypeError('local_only must be bool')

		resource = ids if isinstance(ids, o.ComputedResource) else None

		if resource is not None:
			if not callable(callback):
				raise TypeError('Computed resource subscriber must be callable')

			ids             = None if resource.value is o.Undefined and not resource.dependencies else resource.dependencies
			resource_target = callback

			def resource_callback(changed):
				resource._invalidate()
				resource_target(changed)

			callback = resource_callback

		if local_only:
			if callback is None:
				callback = ids
				ids      = None

			if not callable(callback):
				raise TypeError('Sync subscriber must be callable')

			# Close over the original callback before wrapping remote events.
			# --------------------------------------------------------------
			local_target = callback

			def local_callback(changed):
				if self._delivery_local:
					local_target(changed)

			callback = local_callback

		with self._subscription_lock:
			subscription = super().subscribe(ids, callback)

			if resource is not None:
				subscription._resource = resource

		return subscription

	# Observe successful commits before the asynchronous delivery queue.
	# Reuse a broad Subscribable registration rather than another observer index.
	# ----------------------------------------------------------------------
	def watch_commits(self, callback):
		with self._subscription_lock:
			subscription = super().subscribe(None, callback)
			subscription._commit_observer = True

		return subscription

	# Commit the value and its dependencies with no gap against publication.
	# The source lock precedes the resource lock in both competing operations.
	# ----------------------------------------------------------------------
	def commit_resource(self, resource, identifiers):
		with self._subscription_lock:
			resource._publish(identifiers, self)

	# Refresh all current listeners of one computed resource in the source.
	# Do not maintain a second resource-to-listener index.
	# ----------------------------------------------------------------------
	def update_resource(self, resource, identifiers):
		with self._subscription_lock:
			for subscription in tuple(self._subscriptions):
				if getattr(subscription, '_resource', None) is resource:
					self._update_subscription(subscription, identifiers)

	# Confirm committed changes synchronously to in-flight observations.
	# Ordinary listeners still receive only worker-delivered invalidations.
	# ----------------------------------------------------------------------
	def publish_change(self, ids, local=True):
		with self._subscription_lock:
			for subscription in tuple(self._broad):
				if getattr(subscription, '_commit_observer', False) and subscription._active:
					subscription._callback(ids)

			if not local or self._subscriptions:
				self._queue.put((ids, local))
